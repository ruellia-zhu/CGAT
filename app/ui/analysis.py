"""The full-pipeline analysis page: form on the left, progress on the stage."""
from __future__ import annotations

import re
import traceback
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import build_info as info
from ..wgdi.pipeline import Listener, Pipeline
from ..wgdi.project import STEPS, GenomeInput, Project, default_projects_dir
from . import icons, theme
from .widgets import Card, Check, SectionHeader, SegmentedControl

KINDS_ALL = [("genome", "基因组 FASTA"), ("fai", "基因组 .fai"),
             ("gff", "注释 GFF3 / GTF"), ("pep", "蛋白 FASTA"), ("cds", "CDS FASTA")]
FILTERS = {
    "genome": "序列文件 (*.fa *.fasta *.fna);;所有文件 (*)",
    "gff": "注释文件 (*.gff3 *.gff *.gtf);;所有文件 (*)",
    "fai": "长度文件 (*.fai *.len);;所有文件 (*)",
    "pep": "蛋白序列 (*.fasta *.fa *.pep *.faa);;所有文件 (*)",
    "cds": "CDS 序列 (*.fasta *.fa *.cds *.fna);;所有文件 (*)",
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
    def __init__(self, project: Project, rt, parent=None):
        super().__init__(parent)
        self.project = project
        self.rt = rt
        self.signals = WorkerSignals()
        self.pipeline: Pipeline | None = None

    def run(self) -> None:  # noqa: D102
        try:
            self.pipeline = Pipeline(self.project, _Bridge(self.signals), self.rt)
            results = self.pipeline.run()
            self.signals.done.emit([(r.key, r.ok, r.skipped, r.message) for r in results])
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.signals.failed.emit(str(exc))


class GenomeBox(Card):
    """One side of the comparison, sized for the narrow left panel."""

    def __init__(self, title: str, parent=None):
        super().__init__(padding=10, spacing=6, parent=parent)
        t = theme.theme()
        self.fields: dict[str, QLineEdit] = {}
        self._rows: dict[str, QWidget] = {}

        head = SectionHeader("2", title)
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


class AnalysisPanel(QWidget):
    """Left side of the analysis page: what to analyse."""

    start_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        t = theme.theme()
        self.messages: list[str] = []
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

        card = Card(padding=9, spacing=6)
        card.add(SectionHeader("1", "项目"))
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
        v.addWidget(card)

        self.self_check = Check("自比较（只用物种 A，B 自动沿用 A）")
        self.self_check.setChecked(True)
        self.self_check.toggled.connect(self._on_self)
        v.addWidget(self.self_check)

        self.box_a = GenomeBox("物种 A")
        self.box_b = GenomeBox("物种 B")
        self.box_b.setVisible(False)
        v.addWidget(self.box_a)
        v.addWidget(self.box_b)

        params = Card(padding=9, spacing=6)
        params.add(SectionHeader("3", "参数"))
        spec = QHBoxLayout()
        spec.setSpacing(6)
        spec.addWidget(_tiny("线程"))
        self.threads = QSpinBox()
        self.threads.setRange(1, 64)
        self.threads.setValue(_default_threads())
        self.threads.setFixedSize(50, 25)
        spec.addWidget(self.threads)
        spec.addWidget(_tiny("E 值"))
        self.evalue = QLineEdit("1e-5")
        self.evalue.setFixedSize(56, 25)
        spec.addWidget(self.evalue)
        spec.addStretch(1)
        params.add(_row(spec))
        self.engine = SegmentedControl(["blastp", "diamond"], height=26)
        params.add(self.engine)
        hint = QLabel("diamond 比 blastp 快 10–50 倍，但灵敏度略低、默认参数下结果会有差异；追求质量请用 blastp。")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size:10px;color:{t['ink3']};background:transparent;")
        params.add(hint)
        v.addWidget(params)
        v.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        foot = QWidget()
        foot.setObjectName("panelFooter")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(16, 12, 16, 12)
        fl.setSpacing(8)
        self.start_btn = QPushButton("开始分析")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumHeight(38)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setIcon(icons.icon("circle-dot", t["accent_ink"], 15))
        self.start_btn.clicked.connect(self._on_start)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("ghost")
        self.cancel_btn.setMinimumHeight(38)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        fl.addWidget(self.start_btn, 2)
        fl.addWidget(self.cancel_btn, 1)
        outer.addWidget(foot)

    def _choose_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择项目所在目录", self.dir_edit.text())
        if path:
            self.dir_edit.setText(path)

    def _on_self(self, checked: bool) -> None:
        self.box_b.setVisible(not checked)

    def _on_start(self) -> None:
        project = self.build_project()
        if project is not None:
            self.start_requested.emit(project)

    def build_project(self) -> Project | None:
        missing = self.box_a.missing()
        if missing:
            self.messages.append("物种 A 还缺：" + "、".join(missing))
            return None
        selb = not self.self_check.isChecked()
        if selb and self.box_b.missing():
            self.messages.append("物种 B 还缺：" + "、".join(self.box_b.missing()))
            return None
        for box in (self.box_a, self.box_b):
            for edit in box.fields.values():
                text = edit.text().strip()
                if text and not Path(text).exists():
                    self.messages.append(f"文件不存在：{text}")
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
            self.messages.append(f"无法创建项目：{exc}")
            return None
        params = project.params
        project.params = type(params)(**{**params.to_dict(),
                                         "evalue": self.evalue.text().strip() or params.evalue})
        project.save()
        return project

    def set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)


class AnalysisStage(QWidget):
    """Right side of the analysis page: steps, progress, log, results."""

    cancel_requested = Signal()
    load_requested = Signal(str)
    results_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        t = theme.theme()
        self._project: Project | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(10)
        mark = QLabel()
        mark.setPixmap(icons.pixmap("circle-dot", t["accent"], 20))
        head.addWidget(mark)
        self.title = QLabel("全流程分析")
        self.title.setStyleSheet(f"font-size:16px;font-weight:700;color:{t['ink']};")
        head.addWidget(self.title)
        head.addStretch(1)
        self.results_btn = QPushButton("查看结果图")
        self.results_btn.setObjectName("ghost")
        self.results_btn.setCursor(Qt.PointingHandCursor)
        self.results_btn.setFixedHeight(32)
        self.results_btn.setEnabled(False)
        self.results_btn.clicked.connect(self._show_results)
        head.addWidget(self.results_btn)
        self.load_btn = QPushButton("载入 Circos")
        self.load_btn.setObjectName("primary")
        self.load_btn.setCursor(Qt.PointingHandCursor)
        self.load_btn.setFixedHeight(32)
        self.load_btn.setEnabled(False)
        self.load_btn.clicked.connect(self._load)
        head.addWidget(self.load_btn)
        lay.addLayout(head)

        self.subtitle = QLabel("选好物种与参数，点「开始分析」")
        self.subtitle.setStyleSheet(f"font-size:11px;color:{t['ink3']};")
        lay.addWidget(self.subtitle)

        self.bar = DeterminateBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.eta = QLabel("")
        self.eta.setStyleSheet(f"font-size:10px;color:{t['ink3']};")
        lay.addWidget(self.eta)

        steps_card = Card(padding=12, spacing=5)
        self._rows: dict[str, tuple[QLabel, QLabel]] = {}
        for key, title in STEPS:
            row = QHBoxLayout()
            row.setSpacing(10)
            name = QLabel(title)
            name.setStyleSheet(f"font-size:12px;color:{t['ink2']};background:transparent;")
            state = QLabel("等待")
            state.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            state.setStyleSheet(f"font-size:11px;color:{t['ink3']};background:transparent;")
            row.addWidget(name, 1)
            row.addWidget(state, 0)
            steps_card.add(_row(row))
            self._rows[key] = (name, state)
        lay.addWidget(steps_card, 0)

        log_card = Card(padding=10, spacing=6)
        log_card.add(SectionHeader("", "日志"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        self.log.setStyleSheet(
            f"QPlainTextEdit{{background:{t['card']};border:1px solid {t['border']};"
            f"border-radius:10px;color:{t['ink2']};font-size:11px;"
            f"font-family:Consolas,monospace;padding:8px;}}")
        log_card.add(self.log)
        lay.addWidget(log_card, 1)

    def begin(self, project: Project) -> None:
        t = theme.theme()
        self._project = project
        self.title.setText(project.name)
        self.subtitle.setText(f"对比 {project.stem} · {project.root}")
        for name, state in self._rows.values():
            state.setText("等待")
            name.setStyleSheet(f"font-size:12px;color:{t['ink2']};background:transparent;")
            state.setStyleSheet(f"font-size:11px;color:{t['ink3']};background:transparent;")
        self.bar.setVisible(True)
        self.bar.set_value(0)
        self.eta.setText("")
        self.load_btn.setEnabled(False)
        self.results_btn.setEnabled(False)
        self.append(f"项目：{project.root}")
        self.append(f"对比：{project.stem}（{'自比较' if project.self_compare else '两物种'}）")

    def append(self, message: str) -> None:
        self.log.appendPlainText(message)

    def set_step(self, key: str, state: str) -> None:
        if key not in self._rows:
            return
        t = theme.theme()
        name, label = self._rows[key]
        label.setText({"pending": "等待", "running": "进行中…", "done": "完成",
                       "skipped": "跳过", "failed": "失败"}.get(state, state))
        keys = [k for k, _ in STEPS]
        index = keys.index(key) if key in keys else 0
        if state in ("done", "skipped"):
            self.bar.set_value((index + 1) * 10)
        elif state == "running":
            self.bar.set_value(index * 10)
        if state == "done":
            name.setStyleSheet(f"font-size:12px;color:{t['ink']};"
                               "background:transparent;font-weight:600;")
            label.setStyleSheet(f"font-size:11px;color:{t['accent']};background:transparent;")
        elif state == "running":
            label.setStyleSheet(f"font-size:11px;color:{t['accent']};"
                                "background:transparent;font-weight:600;")
        elif state == "failed":
            label.setStyleSheet("font-size:11px;color:#c0392b;background:transparent;")

    def set_progress(self, key: str, done: int, total: int, eta: float) -> None:
        keys = [k for k, _ in STEPS]
        base = keys.index(key) if key in keys else 0
        if total:
            self.bar.set_value(base * 10 + int(done * 10 / total))
        if eta >= 0:
            self.eta.setText(f"{done}/{total} · 预计剩余 {int(eta) // 60} 分 {int(eta) % 60} 秒")
        else:
            self.eta.setText(f"{done}/{total}")

    def finish(self, results: list) -> None:
        self.bar.setVisible(False)
        self.eta.setText("")
        ok = sum(1 for _k, good, _s, _m in results if good)
        self.append(f"结束：{ok}/{len(results)} 步完成")
        for key, good, skipped, message in results:
            if skipped:
                self.append(f"  跳过 {key}：{message}")
            elif not good:
                self.append(f"  失败 {key}：{message}")
        if self._project is not None:
            stem = self._project.stem
            if (self._project.results / f"{stem}.pdf").exists():
                self.load_btn.setEnabled(True)
            figures = list(self._project.work.glob(f"{stem}*.png")) + \
                list(self._project.results.glob(f"{stem}*.png"))
            if figures:
                self.results_btn.setEnabled(True)
                self.append(f"共 {len(figures)} 张结果图，可点「查看结果图」")

    def fail(self, message: str) -> None:
        self.bar.setVisible(False)
        self.append("出错：" + message)

    def _show_results(self) -> None:
        if self._project is not None:
            self.results_requested.emit(str(self._project.root))

    def _load(self) -> None:
        if self._project is not None:
            self.load_requested.emit(str(self._project.root))


def _default_threads() -> int:
    import os

    return max(1, min(8, os.cpu_count() or 4))
