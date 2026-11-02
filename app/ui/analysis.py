"""The step-by-step analysis wizard: pinboard of steps on the left, preview right."""
from __future__ import annotations

import re
import traceback
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import build_info as info
from ..wgdi.pipeline import Listener, Pipeline
from ..wgdi.conf import WgdiParams
from ..wgdi.project import STEPS, Filters, GenomeInput, Project, default_projects_dir
from . import icons, theme
from .widgets import Card, Check, SectionHeader, SegmentedControl

KEYS = [k for k, _ in STEPS]
TITLES = dict(STEPS)

KINDS_ALL = [("genome", "基因组 FASTA"), ("fai", "基因组 .fai"),
             ("gff", "注释 GFF3 / GTF"), ("pep", "蛋白 FASTA"), ("cds", "CDS FASTA")]
FILTERS = {
    "genome": "序列文件 (*.fa *.fasta *.fna);;所有文件 (*)",
    "gff": "注释文件 (*.gff3 *.gff *.gtf);;所有文件 (*)",
    "fai": "长度文件 (*.fai *.len);;所有文件 (*)",
    "pep": "蛋白序列 (*.fasta *.fa *.pep *.faa);;所有文件 (*)",
    "cds": "CDS 序列 (*.fasta *.fa *.cds *.fna);;所有文件 (*)",
}
BLAST_FILE = "比对结果 (*.txt *.m8 *.tsv *.blast);;所有文件 (*)"

# 每一步可编辑的 WgdiParams 字段：参数名 -> (界面标签, 类型)
PARAM_FIELDS = {
    "dotplot": [("score", "score", "int"), ("dot_repeat_number", "repeat_number", "int"),
                ("dot_markersize", "markersize", "float"), ("dot_figsize", "figsize", "text")],
    "collinearity": [("score", "score", "int"), ("evalue", "evalue", "text"),
                     ("grading", "grading", "text"), ("mg", "mg", "text"),
                     ("pvalue", "pvalue", "float"), ("repeat_number_icl", "repeat_number", "int"),
                     ("process", "process", "int")],
    "ks": [("align_software", "比对软件", "align")],
    "blockinfo": [("repeat_number_bi", "repeat_number", "int"),
                  ("ks_col", "ks_col", "text")],
    "blockks": [("bk_pvalue", "pvalue", "float"), ("bk_tandem", "tandem", "bool"),
                ("bk_tandem_length", "tandem_length", "int"), ("bk_area", "area", "text"),
                ("bk_block_length", "block_length", "int")],
    "kspeaks": [("kp_ks_area", "ks_area", "text"), ("kp_area", "area", "text"),
                ("kp_homo", "homo", "text"), ("kp_fontsize", "fontsize", "int")],
}
DESCRIPTIONS = {
    "prep": "把基因组与注释转成 WGDI 需要的 gff / len / 蛋白 / CDS，默认只保留染色体。",
    "blast": "先建比对库再两两比对，产出 m8 表；已有结果也可以直接上传。",
    "dotplot": "用比对结果画共线性点阵图。",
    "collinearity": "在点阵基础上筛共线块，产出 collinearity 文件。",
    "ks": "对共线块里的基因对做 Ka/Ks（muscle + pal2nal + PAML）。",
    "blockinfo": "汇总共线块与 Ks，得到 block_information.csv。",
    "blockks": "按块画 Ks 点阵图。",
    "kspeaks": "画 Ks 中位数分布图。",
    "circos": "用块信息画 Circos 图，可载入绘图页继续调样式。",
}


class DeterminateBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(5)
        self._value = 0
        t = theme.theme()
        self._track = QColor(t["track"])
        self._fill = QColor(t["accent"])

    def set_value(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        if value != self._value:
            self._value = value
            self.update()

    def paintEvent(self, ev) -> None:  # noqa: D102
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        rect = QRectF(self.rect())
        p.setBrush(self._track)
        p.drawRoundedRect(rect, 3, 3)
        if self._value:
            p.setBrush(self._fill)
            p.drawRoundedRect(QRectF(0, 0, max(5.0, rect.width() * self._value / 100.0),
                                     rect.height()), 3, 3)
        p.end()


class _Bridge(Listener):
    def __init__(self, signals: "WorkerSignals"):
        self._s = signals

    def log(self, message: str) -> None:
        self._s.log.emit(message)

    def step(self, key: str, state: str) -> None:
        self._s.step.emit(key, state)

    def progress(self, key: str, done: int, total: int, eta: float | None) -> None:
        self._s.progress.emit(key, done, total, -1.0 if eta is None else eta)

    def failed(self, key: str, message: str) -> None:
        self._s.log.emit(f"[失败] {key}: {message}")


class WorkerSignals(QWidget):
    log = Signal(str)
    step = Signal(str, str)
    progress = Signal(str, int, int, float)
    done = Signal(list)
    failed = Signal(str)


class PipelineWorker(QThread):
    """Run a list of steps; the wizard passes one, 「全部运行」 passes all."""

    def __init__(self, project: Project, rt, keys: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.project = project
        self.rt = rt
        self.keys = keys
        self.signals = WorkerSignals()
        self.pipeline: Pipeline | None = None
        self.last: list = []

    def run(self) -> None:  # noqa: D102
        try:
            self.pipeline = Pipeline(self.project, _Bridge(self.signals), self.rt)
            if self.keys and len(self.keys) == 1:
                self.last = [self.pipeline.run_step(self.keys[0])]
            elif self.keys:
                self.last = self.pipeline.run(only=self.keys)
            else:
                self.last = self.pipeline.run()
            self.signals.done.emit([(r.key, r.ok, r.skipped, r.message) for r in self.last])
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.signals.failed.emit(str(exc))


class GenomeBox(Card):
    def __init__(self, title: str, parent=None):
        super().__init__(padding=10, spacing=6, parent=parent)
        t = theme.theme()
        self.fields: dict[str, QLineEdit] = {}
        self._rows: dict[str, QWidget] = {}

        head = SectionHeader("", title)
        self.mode = SegmentedControl(["自动解析", "手动上传"], height=26)
        self.mode.changed.connect(self._on_mode)
        head.add_right(self.mode)
        self.add(head)

        for key, label in KINDS_ALL:
            row = QWidget()
            lay = QVBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(2)
            caption = QLabel(label)
            caption.setStyleSheet(f"font-size:10px;color:{t['ink3']};background:transparent;")
            line = QHBoxLayout()
            line.setSpacing(6)
            edit = QLineEdit()
            edit.setReadOnly(True)
            edit.setFixedHeight(25)
            edit.setPlaceholderText("未选择")
            line.addWidget(edit, 1)
            button = QPushButton("选")
            button.setObjectName("ghost")
            button.setFixedSize(28, 25)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self._browse(k))
            line.addWidget(button)
            lay.addWidget(caption)
            lay.addLayout(line)
            self.fields[key] = edit
            self._rows[key] = row
            self.add(row)

        self.display = QLineEdit()
        self.display.setFixedHeight(25)
        self.display.setPlaceholderText("图上显示的名称（可留空）")
        self.add(self.display)
        self._on_mode(0)

    def _browse(self, key: str) -> None:
        current = self.fields[key].text()
        start = str(Path(current).parent) if current else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "选择文件", start, FILTERS[key])
        if path:
            self.fields[key].setText(path)
            self.fields[key].setToolTip(path)

    def _on_mode(self, index: int) -> None:
        auto = index == 0
        self._rows["genome"].setVisible(auto)
        self._rows["fai"].setVisible(not auto)
        self._rows["pep"].setVisible(not auto)
        self._rows["cds"].setVisible(not auto)

    def load(self, genome: GenomeInput) -> None:
        self.mode.set_current(0 if genome.mode == "auto" else 1, emit=True)
        for key, edit in self.fields.items():
            edit.setText(getattr(genome, key) or "")
        self.display.setText(genome.display_name or "")

    def to_input(self, fallback: str) -> GenomeInput:
        mode = "auto" if self.mode.current() == 0 else "manual"
        data = {k: (v.text().strip() or None) for k, v in self.fields.items()}
        name = self.display.text().strip()
        prefix = _prefix_from(name or data.get("genome") or data.get("fai")
                              or data.get("pep") or fallback)
        return GenomeInput(prefix=prefix, mode=mode, genome=data.get("genome"),
                           gff=data.get("gff"), pep=data.get("pep"), cds=data.get("cds"),
                           fai=data.get("fai"), display_name=name)

    def missing(self) -> list[str]:
        keys = ["genome", "gff"] if self.mode.current() == 0 else ["fai", "gff", "pep"]
        return [k for k in keys if not self.fields[k].text().strip()]


def _prefix_from(path: str) -> str:
    stem = Path(path).name.split(".")[0]
    stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "", stem) or "genome"
    return stem[:12]


def _tiny(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"font-size:10px;color:{theme.theme()['ink3']};background:transparent;")
    return label


def _row(layout) -> QWidget:
    widget = QWidget()
    layout.setContentsMargins(0, 0, 0, 0)
    widget.setLayout(layout)
    return widget


class StepRow(QWidget):
    clicked = Signal(str)

    def __init__(self, key: str, index: int, parent=None):
        super().__init__(parent)
        self.key = key
        self._state = "pending"
        self._current = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(26)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(8)
        self.mark = QLabel("○")
        self.mark.setFixedWidth(12)
        self.name = QLabel(f"{index:02d}  {TITLES[key]}")
        lay.addWidget(self.mark)
        lay.addWidget(self.name, 1)
        self.tag = QLabel("可上传" if key == "blast" else "")
        self.tag.setStyleSheet(f"font-size:9px;color:{theme.theme()['ink3']};"
                              "background:transparent;")
        lay.addWidget(self.tag)
        self.repaint_style()

    def set_state(self, state: str) -> None:
        self._state = state
        self.repaint_style()

    def set_current(self, current: bool) -> None:
        self._current = current
        self.repaint_style()

    def repaint_style(self) -> None:
        t = theme.theme()
        glyph = {"done": "✓", "running": "●", "failed": "✕", "skipped": "⊘"}.get(self._state, "○")
        color = {"done": t["accent"], "running": t["accent"], "failed": "#c0392b",
                 "skipped": t["ink3"]}.get(self._state, t["ink3"])
        self.mark.setText(glyph)
        weight = "600" if self._current else "400"
        ink = t["ink"] if self._current else t["ink2"]
        if self._state == "failed":
            ink = "#c0392b"
        self.mark.setStyleSheet(f"font-size:11px;color:{color};background:transparent;")
        self.name.setStyleSheet(f"font-size:12px;color:{ink};font-weight:{weight};"
                                "background:transparent;")
        bg = t["accent_soft"] if self._current else "transparent"
        self.setStyleSheet(f"StepRow{{background:{bg};border-radius:6px;}}")

    def mousePressEvent(self, ev) -> None:  # noqa: D102
        self.clicked.emit(self.key)

# ---------------------------------------------------------------------------
# 向导左栏
# ---------------------------------------------------------------------------
class WizardPanel(QWidget):
    run_requested = Signal(str)
    run_all_requested = Signal()
    notified = Signal(str)
    step_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        t = theme.theme()
        self._project: Project | None = None
        self._current = KEYS[0]
        self._rows: dict[str, StepRow] = {}
        self._forms: dict[str, QWidget] = {}
        self._widgets: dict[str, dict] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(16, 6, 16, 6)
        v.setSpacing(6)

        steps = Card(padding=8, spacing=2)
        steps.add(SectionHeader("1", "步骤"))
        for index, key in enumerate(KEYS, 1):
            row = StepRow(key, index)
            row.clicked.connect(self.select)
            steps.add(row)
            self._rows[key] = row
        v.addWidget(steps)

        self.forms = QStackedWidget()
        self._build_forms()
        v.addWidget(self.forms)
        v.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        foot = QWidget()
        foot.setObjectName("panelFooter")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(16, 12, 16, 12)
        fl.setSpacing(8)
        self.prev_btn = QPushButton("← 上一步")
        self.prev_btn.setObjectName("ghost")
        self.prev_btn.setMinimumHeight(38)
        self.prev_btn.setCursor(Qt.PointingHandCursor)
        self.prev_btn.clicked.connect(self._go_prev)
        self.run_btn = QPushButton("运行本步")
        self.run_btn.setObjectName("primary")
        self.run_btn.setMinimumHeight(38)
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.setIcon(icons.icon("circle-dot", t["accent_ink"], 15))
        self.run_btn.clicked.connect(self._run)
        self.next_btn = QPushButton("下一步 →")
        self.next_btn.setObjectName("ghost")
        self.next_btn.setMinimumHeight(38)
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.clicked.connect(self._go_next)
        fl.addWidget(self.prev_btn, 1)
        fl.addWidget(self.run_btn, 2)
        fl.addWidget(self.next_btn, 1)
        outer.addWidget(foot)

        self.select(KEYS[0])

    # --- forms --------------------------------------------------------
    def _build_forms(self) -> None:
        self._forms["prep"] = self._form_prep()
        self._forms["blastdb"] = self._form_note(
            "本步没有参数。物种 A 的蛋白建库后会放在项目的 prepared 目录。")
        self._forms["blast"] = self._form_blast()
        for key in ("dotplot", "collinearity", "ks", "blockinfo", "blockks", "kspeaks"):
            self._forms[key] = self._form_params(key)
        self._forms["circos"] = self._form_circos()
        for key in KEYS:
            self.forms.addWidget(self._forms[key])

    def _wrap(self, *cards) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        for card in cards:
            lay.addWidget(card)
        lay.addStretch(1)
        return page

    def _form_note(self, text: str) -> QWidget:
        card = Card(padding=10, spacing=6)
        card.add(SectionHeader("2", "说明"))
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"font-size:11px;color:{theme.theme()['ink2']};"
                            "background:transparent;")
        card.add(label)
        return self._wrap(card)

    def _form_prep(self) -> QWidget:
        t = theme.theme()
        card = Card(padding=9, spacing=6)
        card.add(SectionHeader("2", "项目"))
        self.dir_edit = QLineEdit(str(default_projects_dir()))
        self.dir_edit.setFixedHeight(25)
        card.add(self.dir_edit)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.name_edit = QLineEdit("analysis")
        self.name_edit.setFixedHeight(25)
        self.name_edit.setPlaceholderText("项目名")
        browse = QPushButton("…")
        browse.setObjectName("ghost")
        browse.setFixedSize(28, 25)
        browse.setCursor(Qt.PointingHandCursor)
        browse.clicked.connect(self._choose_dir)
        row.addWidget(self.name_edit, 1)
        row.addWidget(browse)
        card.add(_row(row))

        self.self_check = Check("自比较（只用物种 A，B 自动沿用 A）")
        self.self_check.setChecked(True)
        self.self_check.toggled.connect(self._on_self)
        card.add(self.self_check)

        self.box_a = GenomeBox("物种 A")
        self.box_b = GenomeBox("物种 B")
        self.box_b.setVisible(False)

        filt = Card(padding=9, spacing=6)
        filt.add(SectionHeader("3", "序列过滤"))
        self.only_chrom = Check("只保留染色体（排除 scaffold / contig / unplaced）")
        self.only_chrom.setChecked(True)
        filt.add(self.only_chrom)
        hint = QLabel("点阵图、共线性与 Circos 的坐标轴只使用保留下来的序列。")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size:10px;color:{t['ink3']};background:transparent;")
        filt.add(hint)
        self.extra_exclude = QLineEdit()
        self.extra_exclude.setFixedHeight(25)
        self.extra_exclude.setPlaceholderText("额外排除（正则，可留空）")
        filt.add(self.extra_exclude)
        self.strip_prefix = QLineEdit()
        self.strip_prefix.setFixedHeight(25)
        self.strip_prefix.setPlaceholderText("染色体名去掉前缀（可留空）")
        filt.add(self.strip_prefix)
        return self._wrap(card, self.box_a, self.box_b, filt)

    def _form_blast(self) -> QWidget:
        card = Card(padding=9, spacing=6)
        card.add(SectionHeader("2", "比对方式"))
        self.blast_mode = SegmentedControl(["现在比对", "上传已有结果"], height=26)
        self.blast_mode.changed.connect(self._on_blast_mode)
        card.add(self.blast_mode)
        tip = QLabel("手上已有 blastp 结果（outfmt 6）就不用重跑，切到右边直接导入。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"font-size:10px;color:{theme.theme()['ink3']};"
                          "background:transparent;")
        card.add(tip)

        self.blast_run = QWidget()
        run_lay = QVBoxLayout(self.blast_run)
        run_lay.setContentsMargins(0, 0, 0, 0)
        run_lay.setSpacing(6)
        self.engine = SegmentedControl(["blastp", "diamond"], height=26)
        run_lay.addWidget(self.engine)
        spec = QHBoxLayout()
        spec.setSpacing(6)
        spec.addWidget(_tiny("线程"))
        self.threads = QSpinBox()
        self.threads.setRange(1, 64)
        self.threads.setValue(_default_threads())
        self.threads.setFixedSize(52, 25)
        spec.addWidget(self.threads)
        spec.addWidget(_tiny("E 值"))
        self.evalue = QLineEdit("1e-5")
        self.evalue.setFixedSize(60, 25)
        spec.addWidget(self.evalue)
        spec.addStretch(1)
        run_lay.addWidget(_row(spec))
        note = QLabel("diamond 比 blastp 快 10–50 倍，但灵敏度略低、默认参数下结果会有差异；追求质量请用 blastp。")
        note.setWordWrap(True)
        note.setStyleSheet(f"font-size:10px;color:{theme.theme()['ink3']};background:transparent;")
        run_lay.addWidget(note)
        card.add(self.blast_run)

        self.blast_upload = QWidget()
        up_lay = QVBoxLayout(self.blast_upload)
        up_lay.setContentsMargins(0, 0, 0, 0)
        up_lay.setSpacing(6)
        self.upload_edit = QLineEdit()
        self.upload_edit.setReadOnly(True)
        self.upload_edit.setFixedHeight(25)
        self.upload_edit.setPlaceholderText("选择 outfmt 6 的比对结果")
        pick = QPushButton("选择文件")
        pick.setObjectName("ghost")
        pick.setFixedHeight(25)
        pick.setCursor(Qt.PointingHandCursor)
        pick.clicked.connect(self._pick_blast)
        up_lay.addWidget(self.upload_edit)
        up_lay.addWidget(pick)
        up_note = QLabel("至少 6 列（outfmt 6 默认 12 列），第一列是查询蛋白 ID。")
        up_note.setWordWrap(True)
        up_note.setStyleSheet(f"font-size:10px;color:{theme.theme()['ink3']};background:transparent;")
        up_lay.addWidget(up_note)
        card.add(self.blast_upload)
        self.blast_upload.setVisible(False)
        return self._wrap(card)

    def _form_params(self, key: str) -> QWidget:
        card = Card(padding=9, spacing=6)
        card.add(SectionHeader("2", "本步参数"))
        store: dict[str, QWidget] = {}
        for attr, label, kind in PARAM_FIELDS.get(key, []):
            line = QHBoxLayout()
            line.setSpacing(6)
            line.addWidget(_tiny(label))
            if kind == "int":
                widget = QSpinBox()
                widget.setRange(0, 1_000_000)
                widget.setFixedSize(78, 25)
            elif kind == "bool":
                widget = Check("启用")
            elif kind == "align":
                widget = SegmentedControl(["muscle", "mafft"], height=25)
            else:
                widget = QLineEdit()
                widget.setFixedHeight(25)
            _seed(widget, getattr(WgdiParams(), attr, ""))
            line.addWidget(widget, 1)
            card.add(_row(line))
            store[attr] = widget
        self._widgets[key] = store
        hint = QLabel("score / evalue 与前后多步共用，改动会影响后续步骤。")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size:10px;color:{theme.theme()['ink3']};background:transparent;")
        card.add(hint)
        frame = self._wrap(card)
        self._widgets.setdefault(key, store)
        return frame

    def _form_circos(self) -> QWidget:
        card = Card(padding=9, spacing=6)
        card.add(SectionHeader("2", "输出"))
        self.fmt_pdf = Check("PDF")
        self.fmt_pdf.setChecked(True)
        self.fmt_svg = Check("SVG")
        self.fmt_svg.setChecked(True)
        self.fmt_png = Check("PNG")
        self.fmt_png.setChecked(True)
        for widget in (self.fmt_pdf, self.fmt_svg, self.fmt_png):
            card.add(widget)
        note = QLabel("跑完可以点「载入 Circos」到绘图页继续调样式与导出。")
        note.setWordWrap(True)
        note.setStyleSheet(f"font-size:10px;color:{theme.theme()['ink3']};background:transparent;")
        card.add(note)
        return self._wrap(card)

    # --- 状态 ---------------------------------------------------------
    def current_key(self) -> str:
        return self._current

    def select(self, key: str) -> None:
        if key not in self._forms:
            return
        self._current = key
        self.forms.setCurrentWidget(self._forms[key])
        for name, row in self._rows.items():
            row.set_current(name == key)
        self._sync_buttons()
        self.step_changed.emit(key)

    def project(self) -> Project | None:
        return self._project

    def set_project(self, project: Project) -> None:
        self._project = project
        self.dir_edit.setText(str(project.root.parent))
        self.name_edit.setText(project.name)
        self.self_check.setChecked(project.self_compare)
        self.box_a.load(project.genome_a)
        if project.genome_b is not None:
            self.box_b.load(project.genome_b)
        self.only_chrom.setChecked(project.filters.chromosomes_only)
        self.extra_exclude.setText(project.filters.extra_exclude)
        self.strip_prefix.setText(project.filters.strip_prefix)
        self.threads.setValue(project.threads)
        self.engine.set_current(1 if project.engine == "diamond" else 0)
        self.evalue.setText(project.params.evalue)
        upload = project.blast_input.source == "upload"
        self.blast_mode.set_current(1 if upload else 0, emit=True)
        self.upload_edit.setText(project.blast_input.uploaded or "")
        for _key, store in self._widgets.items():
            for attr, widget in store.items():
                _seed(widget, getattr(project.params, attr, ""))
        self.refresh_states()

    def refresh_states(self) -> None:
        for key, row in self._rows.items():
            row.set_state(self._project.step_state(key) if self._project else "pending")
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        index = KEYS.index(self._current)
        self.prev_btn.setEnabled(index > 0)
        state = self._project.step_state(self._current) if self._project else "pending"
        done = state in ("done", "skipped")
        self.next_btn.setEnabled(done and index < len(KEYS) - 1)
        self.next_btn.setToolTip("" if done else "先运行本步，成功后即可继续")
        if state == "done":
            self.run_btn.setText("重新运行本步")
        else:
            self.run_btn.setText("运行本步")

    def set_running(self, running: bool) -> None:
        self.run_btn.setEnabled(not running)
        self.prev_btn.setEnabled(not running and KEYS.index(self._current) > 0)
        self.next_btn.setEnabled(False if running else self.next_btn.isEnabled())

    # --- 交互 ---------------------------------------------------------
    def _choose_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择项目所在目录", self.dir_edit.text())
        if path:
            self.dir_edit.setText(path)

    def _on_self(self, checked: bool) -> None:
        self.box_b.setVisible(not checked)

    def _on_blast_mode(self, index: int) -> None:
        upload = index == 1
        self.blast_run.setVisible(not upload)
        self.blast_upload.setVisible(upload)

    def _pick_blast(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择比对结果", str(Path.home()), BLAST_FILE)
        if path:
            self.upload_edit.setText(path)
            self.upload_edit.setToolTip(path)

    def _go_prev(self) -> None:
        index = KEYS.index(self._current)
        if index > 0:
            self.select(KEYS[index - 1])

    def _go_next(self) -> None:
        index = KEYS.index(self._current)
        if index < len(KEYS) - 1:
            self.select(KEYS[index + 1])

    def _run(self) -> None:
        project = self.ensure_project()
        if project is None:
            return
        if self._current == "blast" and self.blast_mode.current() == 1 \
                and not self.upload_edit.text().strip():
            self.notified.emit("还没有选择比对结果文件")
            return
        self.run_requested.emit(self._current)

    # --- 项目与参数 ---------------------------------------------------
    def _read_param(self, attr: str, widget) -> object:
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, Check):
            return widget.isChecked()
        if isinstance(widget, SegmentedControl):
            return "mafft" if widget.current() == 1 else "muscle"
        return widget.text().strip()

    def ensure_project(self) -> Project | None:
        if self._project is None:
            missing = self.box_a.missing()
            if missing:
                self.notified.emit("物种 A 还缺：" + "、".join(missing))
                return None
            selb = not self.self_check.isChecked()
            if selb and self.box_b.missing():
                self.notified.emit("物种 B 还缺：" + "、".join(self.box_b.missing()))
                return None
            for box in (self.box_a, self.box_b):
                for edit in box.fields.values():
                    text = edit.text().strip()
                    if text and not Path(text).exists():
                        self.notified.emit(f"文件不存在：{text}")
                        return None
            base = Path(self.dir_edit.text().strip() or str(default_projects_dir()))
            name = self.name_edit.text().strip() or "analysis"
            try:
                project = Project.create(
                    base, name, self_compare=not selb,
                    genome_a=self.box_a.to_input("A"),
                    genome_b=self.box_b.to_input("B") if selb else None,
                    engine="diamond" if self.engine.current() == 1 else "blastp",
                    threads=self.threads.value(), app_version=info.VERSION)
            except Exception as exc:  # noqa: BLE001
                self.notified.emit(f"无法创建项目：{exc}")
                return None
            self._project = project
            self.notified.emit(f"项目：{project.root}")
            self._project = project
            self.set_project(project)
        self.apply_to(self._project)
        self._project.save()
        return self._project

    def apply_to(self, project: Project) -> None:
        project.self_compare = self.self_check.isChecked()
        project.genome_a = self.box_a.to_input(project.genome_a.prefix or "A")
        if not project.self_compare:
            fallback = project.genome_b.prefix if project.genome_b else "B"
            project.genome_b = self.box_b.to_input(fallback)
        else:
            project.genome_b = None
        project.filters = Filters(
            chromosomes_only=self.only_chrom.isChecked(),
            extra_exclude=self.extra_exclude.text().strip(),
            strip_prefix=self.strip_prefix.text().strip())
        project.engine = "diamond" if self.engine.current() == 1 else "blastp"
        project.threads = self.threads.value()
        updates: dict[str, object] = {"evalue": self.evalue.text().strip() or "1e-5"}
        for key, store in self._widgets.items():
            for attr, widget in store.items():
                value = self._read_param(attr, widget)
                updates[attr] = value
        try:
            project.params = replace(project.params, **updates)
        except TypeError:
            pass
        if self.blast_mode.current() == 1:
            project.blast_input.source = "upload"
            project.blast_input.uploaded = self.upload_edit.text().strip() or None
        else:
            project.blast_input.source = "run"
            project.blast_input.uploaded = None


def _seed(widget, value) -> None:
    """Write a parameter value into whatever control represents it."""
    if isinstance(widget, QSpinBox):
        widget.setValue(int(value) if isinstance(value, (int, float)) else 0)
    elif isinstance(widget, Check):
        widget.setChecked(bool(value))
    elif isinstance(widget, SegmentedControl):
        widget.set_current(1 if str(value) == "mafft" else 0)
    else:
        widget.setText("" if value is None else str(value))


def _default_threads() -> int:
    import os

    return max(1, min(8, os.cpu_count() or 4))


# ---------------------------------------------------------------------------
# 向导右栏
# ---------------------------------------------------------------------------
class PreviewStage(QWidget):
    cancel_requested = Signal()
    run_all_requested = Signal()
    load_requested = Signal(str)
    results_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        from .preview import PreviewPane

        t = theme.theme()
        self._project: Project | None = None
        self._key = KEYS[0]

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(10)
        mark = QLabel()
        mark.setPixmap(icons.pixmap("circle-dot", t["accent"], 20))
        head.addWidget(mark)
        self.title = QLabel("1. 预处理")
        self.title.setStyleSheet(f"font-size:16px;font-weight:700;color:{t['ink']};")
        head.addWidget(self.title)
        head.addStretch(1)
        self.results_btn = QPushButton("查看结果图")
        self.results_btn.setObjectName("ghost")
        self.results_btn.setFixedHeight(32)
        self.results_btn.setCursor(Qt.PointingHandCursor)
        self.results_btn.clicked.connect(self._show_results)
        head.addWidget(self.results_btn)
        self.load_btn = QPushButton("载入 Circos")
        self.load_btn.setObjectName("ghost")
        self.load_btn.setFixedHeight(32)
        self.load_btn.setCursor(Qt.PointingHandCursor)
        self.load_btn.clicked.connect(self._load)
        head.addWidget(self.load_btn)
        self.all_btn = QPushButton("连续运行剩余步骤")
        self.all_btn.setObjectName("primary")
        self.all_btn.setFixedHeight(32)
        self.all_btn.setCursor(Qt.PointingHandCursor)
        self.all_btn.clicked.connect(self.run_all_requested.emit)
        head.addWidget(self.all_btn)
        lay.addLayout(head)

        self.subtitle = QLabel(DESCRIPTIONS[KEYS[0]])
        self.subtitle.setWordWrap(True)
        self.subtitle.setStyleSheet(f"font-size:11px;color:{t['ink3']};")
        lay.addWidget(self.subtitle)

        self.bar = DeterminateBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        bar_row = QHBoxLayout()
        bar_row.setSpacing(10)
        self.eta = QLabel("")
        self.eta.setStyleSheet(f"font-size:10px;color:{t['ink3']};")
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("ghost")
        self.cancel_btn.setFixedHeight(26)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        bar_row.addWidget(self.eta, 1)
        bar_row.addWidget(self.cancel_btn)
        lay.addLayout(bar_row)

        self.pane = PreviewPane()
        lay.addWidget(self.pane, 3)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setFixedHeight(120)
        self.log.setStyleSheet(
            f"QPlainTextEdit{{background:{t['card']};border:1px solid {t['border']};"
            f"border-radius:10px;color:{t['ink2']};font-size:11px;"
            f"font-family:Consolas,monospace;padding:6px;}}")
        lay.addWidget(self.log, 0)

    # --- api ----------------------------------------------------------
    def set_project(self, project: Project | None) -> None:
        self._project = project

    def select(self, key: str) -> None:
        self._key = key
        index = KEYS.index(key) + 1
        self.title.setText(f"{index}. {TITLES[key]}")
        self.subtitle.setText(DESCRIPTIONS[key])
        self.refresh()

    def refresh(self) -> None:
        if self._project is None:
            self.pane.clear()
            first = KEYS.index(self._key) == 0
            self.pane.hint.setText(
                "先在左侧填好物种，然后点「运行本步」。" if first else
                f"还没有项目。先完成第 1 步「预处理」，再回来做「{TITLES[self._key]}」。")
            self.pane.stack.setCurrentIndex(0)
        else:
            from ..wgdi import preview as preview_mod

            self.pane.show_preview(preview_mod.build(self._project, self._key))
        stem = self._project.stem if self._project else ""
        self.load_btn.setEnabled(bool(stem) and self._project is not None
                                 and (self._project.results / f"{stem}.pdf").exists())
        figures = 0
        if self._project is not None:
            figures = len(list(self._project.work.glob(f"{stem}*.png"))) + \
                len(list(self._project.results.glob(f"{stem}*.png")))
        self.results_btn.setEnabled(figures > 0)

    def append(self, message: str) -> None:
        self.log.appendPlainText(message)

    def set_running(self, running: bool) -> None:
        self.bar.setVisible(running)
        self.cancel_btn.setVisible(running)
        self.all_btn.setEnabled(not running)
        if running:
            self.bar.set_value(0)
        else:
            self.eta.setText("")

    def set_progress(self, key: str, done: int, total: int, eta: float) -> None:
        if total:
            self.bar.set_value(int(done * 100 / total))
        if eta >= 0:
            self.eta.setText(f"{done}/{total} · 预计剩余 {int(eta) // 60} 分 {int(eta) % 60} 秒")
        else:
            self.eta.setText(f"{done}/{total}")

    def fail(self, message: str) -> None:
        self.bar.setVisible(False)
        self.cancel_btn.setVisible(False)
        self.append("出错：" + message)

    def _show_results(self) -> None:
        if self._project is not None:
            self.results_requested.emit(str(self._project.root))

    def _load(self) -> None:
        if self._project is not None:
            self.load_requested.emit(str(self._project.root))
