"""The full-pipeline analysis window: inputs → WGDI steps → results."""
from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QRectF, QThread, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
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
from ..wgdi import runtime as runtime_mod
from ..wgdi.pipeline import Listener, Pipeline
from ..wgdi.project import STEPS, GenomeInput, Project, default_projects_dir
from . import icons, theme
from .widgets import Check, SegmentedControl

KINDS_AUTO = [("genome", "基因组 FASTA"), ("gff", "注释 GFF3 / GTF")]
KINDS_ALL = [("genome", "基因组 FASTA"), ("fai", "基因组 .fai"),
             ("gff", "注释 GFF3 / GTF"), ("pep", "蛋白 FASTA"), ("cds", "CDS FASTA")]
FILTERS = {
    "genome": "序列文件 (*.fa *.fasta *.fna *.fa.gz);;所有文件 (*)",
    "gff": "注释文件 (*.gff3 *.gff *.gtf *.gff.gz);;所有文件 (*)",
    "fai": "索引文件 (*.fai);;所有文件 (*)",
    "pep": "蛋白序列 (*.fasta *.fa *.pep *.faa);;所有文件 (*)",
    "cds": "CDS 序列 (*.fasta *.fa *.cds *.fna);;所有文件 (*)",
}


class DeterminateBar(QWidget):
    """Thin progress bar with a known percentage."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
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
            width = rect.width() * self._value / 100.0
            p.setBrush(self._fill)
            p.drawRoundedRect(QRectF(0, 0, max(6.0, width), rect.height()), 3, 3)
        p.end()


class _Bridge(Listener):
    """Turn pipeline callbacks into queued Qt signals."""

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


def _pick(widget: QWidget, key: str, label: str, value: QLineEdit) -> QWidget:
    row = QWidget(widget)
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    edit = value
    edit.setReadOnly(True)
    edit.setPlaceholderText(f"选择{label}")
    edit.setFixedHeight(30)
    lay.addWidget(edit, 1)

    button = QPushButton("选择")
    button.setFixedWidth(56)
    button.setFixedHeight(30)
    button.setCursor(Qt.PointingHandCursor)

    def browse() -> None:
        start = str(Path(edit.text()).parent) if edit.text() else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(widget, f"选择{label}", start, FILTERS[key])
        if path:
            edit.setText(path)
            edit.setToolTip(path)

    button.clicked.connect(browse)
    lay.addWidget(button)
    return row


class GenomeBox(QFrame):
    """One side of the comparison: mode switch + file pickers."""

    changed = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.fields: dict[str, QLineEdit] = {}
        self._rows: dict[str, QWidget] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        name = QLabel(title)
        name.setObjectName("cardTitle")
        head.addWidget(name)
        head.addStretch(1)
        lay.addLayout(head)

        self.mode = SegmentedControl(["自动解析", "手动上传"])
        self.mode.changed.connect(self._on_mode)
        lay.addWidget(self.mode)

        self.hint = QLabel("给基因组 FASTA + 注释，程序自己取最长转录本、生成 CDS 与蛋白")
        self.hint.setWordWrap(True)
        self.hint.setObjectName("hint")
        lay.addWidget(self.hint)

        for key, label in KINDS_ALL:
            edit = QLineEdit()
            self.fields[key] = edit
            row = _pick(self, key, label, edit)
            self._rows[key] = row
            lay.addWidget(row)

        self.display = QLineEdit()
        self.display.setPlaceholderText("显示名称（可留空，见图上的物种名）")
        self.display.setFixedHeight(30)
        lay.addWidget(self.display)
        self._on_mode(0)

    def _on_mode(self, index: int) -> None:
        auto = index == 0
        self._rows["genome"].setVisible(auto)
        self._rows["fai"].setVisible(not auto)
        self._rows["pep"].setVisible(not auto)
        self._rows["cds"].setVisible(not auto)
        self.hint.setText(
            "给基因组 FASTA + 注释，程序自己取最长转录本、生成 CDS 与蛋白"
            if auto else
            "请上传「最长转录本」的 CDS 与蛋白（ID 用基因 ID），程序只管坐标与校验")

    def to_input(self, prefix: str) -> GenomeInput:
        mode = "auto" if self.mode.current() == 0 else "manual"
        data = {k: (v.text().strip() or None) for k, v in self.fields.items()}
        return GenomeInput(prefix=prefix, mode=mode,
                           genome=data.get("genome"), gff=data.get("gff"),
                           pep=data.get("pep"), cds=data.get("cds"), fai=data.get("fai"),
                           display_name=self.display.text().strip())

    def missing(self) -> list[str]:
        auto = self.mode.current() == 0
        keys = ["genome", "gff"] if auto else ["fai", "gff", "pep"]
        return [k for k in keys if not self.fields[k].text().strip()]

    def preset(self, other: "GenomeBox") -> None:
        for key, edit in self.fields.items():
            edit.setText(other.fields[key].text())


class StepList(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._rows: dict[str, tuple[QLabel, QLabel]] = {}
        for key, title in STEPS:
            row = QHBoxLayout()
            row.setSpacing(8)
            name = QLabel(f"{len(self._rows) + 1:02d}  {title}")
            name.setObjectName("stepName")
            state = QLabel("等待")
            state.setObjectName("stepState")
            state.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(name, 1)
            row.addWidget(state, 0)
            lay.addLayout(row)
            self._rows[key] = (name, state)

    def set_state(self, key: str, state: str) -> None:
        if key not in self._rows:
            return
        name, label = self._rows[key]
        text = {"pending": "等待", "running": "进行中…", "done": "完成",
                "skipped": "跳过", "failed": "失败"}.get(state, state)
        label.setText(text)
        label.setProperty("state", state)
        name.setProperty("state", state)
        for widget in (label, name):
            widget.style().unpolish(widget)
            widget.style().polish(widget)


class AnalysisDialog(QDialog):
    """Collect inputs, run the pipeline, report progress."""

    load_requested = Signal(str)

    def __init__(self, parent=None, mode: str = "light"):
        super().__init__(parent)
        self.setWindowTitle("全流程分析")
        self.setModal(True)
        self.resize(760, 820)
        t = theme.theme(mode)
        self._mode = mode
        self._worker: PipelineWorker | None = None
        self._project: Project | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        title = QLabel("全流程分析")
        title.setObjectName("dlgTitle")
        sub = QLabel("预处理 → blastp → 共线性 → Ks → 块汇总 → Circos，中断后可续跑")
        sub.setObjectName("hint")
        root.addWidget(title)
        root.addWidget(sub)

        # --- project ---
        proj = QFrame()
        proj.setObjectName("card")
        pl = QVBoxLayout(proj)
        pl.setContentsMargins(14, 12, 14, 12)
        pl.setSpacing(8)
        ph = QLabel("项目目录")
        ph.setObjectName("cardTitle")
        pl.addWidget(ph)
        prow = QHBoxLayout()
        prow.setSpacing(8)
        self.dir_edit = QLineEdit(str(default_projects_dir()))
        self.dir_edit.setFixedHeight(30)
        prow.addWidget(self.dir_edit, 1)
        browse = QPushButton("浏览")
        browse.setFixedWidth(56)
        browse.setFixedHeight(30)
        browse.setCursor(Qt.PointingHandCursor)

        def choose_dir() -> None:
            path = QFileDialog.getExistingDirectory(self, "选择项目所在目录", self.dir_edit.text())
            if path:
                self.dir_edit.setText(path)

        browse.clicked.connect(choose_dir)
        prow.addWidget(browse)
        pl.addLayout(prow)
        self.name_edit = QLineEdit("analysis")
        self.name_edit.setFixedHeight(30)
        self.name_edit.setPlaceholderText("项目名（用物种名，会自动生成 SJchr-Mtrun 这样的前缀）")
        pl.addWidget(self.name_edit)
        root.addWidget(proj)

        # --- genomes ---
        self.self_check = Check("自比较（只用物种 A，B 自动沿用 A）")
        self.self_check.setChecked(True)
        self.self_check.toggled.connect(self._on_self)
        root.addWidget(self.self_check)

        self.box_a = GenomeBox("物种 A")
        self.box_b = GenomeBox("物种 B")
        root.addWidget(self.box_a)
        root.addWidget(self.box_b)
        self.box_b.setVisible(False)

        # --- parameters ---
        params = QFrame()
        params.setObjectName("card")
        ql = QVBoxLayout(params)
        ql.setContentsMargins(14, 12, 14, 12)
        ql.setSpacing(8)
        qh = QLabel("参数")
        qh.setObjectName("cardTitle")
        ql.addWidget(qh)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(QLabel("线程"))
        self.threads = QSpinBox()
        self.threads.setRange(1, 64)
        self.threads.setValue(_default_threads())
        self.threads.setFixedWidth(64)
        row.addWidget(self.threads)
        row.addWidget(QLabel("引擎"))
        self.engine = QComboBox()
        self.engine.addItems(["blastp（灵敏）", "diamond（快）"])
        self.engine.setFixedWidth(150)
        row.addWidget(self.engine)
        row.addWidget(QLabel("E 值"))
        self.evalue = QLineEdit("1e-5")
        self.evalue.setFixedWidth(80)
        row.addWidget(self.evalue)
        row.addWidget(QLabel("score"))
        self.score = QSpinBox()
        self.score.setRange(0, 10000)
        self.score.setValue(100)
        self.score.setFixedWidth(72)
        row.addWidget(self.score)
        row.addStretch(1)
        ql.addLayout(row)
        self.engine.setToolTip("diamond 比 blastp 快 10–50 倍，但灵敏度略低、默认参数下结果会有差异；追求质量请用 blastp。")
        self.hint = QLabel("diamond 比 blastp 快 10–50 倍，但灵敏度略低、默认参数下结果会有差异；追求质量请用 blastp。")
        self.hint.setWordWrap(True)
        self.hint.setObjectName("hint")
        ql.addWidget(self.hint)
        root.addWidget(params)

        # --- actions ---
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.start_btn = QPushButton("开始分析")
        self.start_btn.setObjectName("primary")
        self.start_btn.setFixedHeight(36)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedHeight(36)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        self.open_btn = QPushButton("载入 Circos")
        self.open_btn.setFixedHeight(36)
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._load_results)
        actions.addWidget(self.start_btn, 1)
        actions.addWidget(self.open_btn)
        actions.addWidget(self.cancel_btn)
        root.addLayout(actions)

        # --- progress + steps ---
        self.bar = DeterminateBar()
        self.bar.setVisible(False)
        self.eta = QLabel("")
        self.eta.setObjectName("hint")
        root.addWidget(self.bar)
        root.addWidget(self.eta)

        self.steps = StepList()
        root.addWidget(self.steps)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        self.log.setFixedHeight(150)
        self.log.setObjectName("logView")
        root.addWidget(self.log)

        self.setStyleSheet(f"""
            QDialog {{ background: {t['bg']}; }}
            QLabel#dlgTitle {{ font-size:17px; font-weight:700; color:{t['ink']}; }}
            QLabel#cardTitle {{ font-size:12px; font-weight:600; color:{t['ink']}; }}
            QLabel#hint {{ font-size:11px; color:{t['ink3']}; }}
            QLabel#stepName {{ font-size:12px; color:{t['ink2']}; }}
            QLabel#stepState {{ font-size:11px; color:{t['ink3']}; }}
            QLabel#stepState[state="running"] {{ color:{t['accent']}; font-weight:600; }}
            QLabel#stepState[state="done"] {{ color:{t['accent']}; }}
            QLabel#stepName[state="running"] {{ color:{t['ink']}; font-weight:600; }}
            QFrame#card {{ background:{t['card']}; border:1px solid {t['border']}; border-radius:10px; }}
            QPushButton {{ background:{t['card']}; border:1px solid {t['border']}; border-radius:8px;
                          padding:0 14px; color:{t['ink']}; font-size:12px; }}
            QPushButton:hover {{ border-color:{t['accent']}; }}
            QPushButton:disabled {{ color:{t['ink3']}; border-color:{t['border']}; }}
            QPushButton#primary {{ background:{t['accent']}; color:white; border:none; font-weight:600; }}
            QPushButton#primary:disabled {{ background:{t['border']}; color:{t['ink3']}; }}
            QLineEdit, QSpinBox, QComboBox {{ background:{t['card']}; border:1px solid {t['border']};
                          border-radius:7px; padding:0 8px; color:{t['ink']}; font-size:12px; }}
            QPlainTextEdit#logView {{ background:{t['card']}; border:1px solid {t['border']};
                          border-radius:8px; color:{t['ink2']}; font-size:11px;
                          font-family:Consolas, monospace; }}
        """)
        self._check_runtime()

    # --- state --------------------------------------------------------
    def _on_self(self, checked: bool) -> None:
        self.box_b.setVisible(not checked)

    def _check_runtime(self) -> None:
        rt = runtime_mod.discover()
        if rt.ok:
            self._log("运行时就绪：" + "、".join(
                f"{k}={v.name}" for k, v in rt.bins.items() if k in
                ("blastp", "makeblastdb", "muscle", "seqkit")))
            if not rt.has_ks:
                self._log("未检测到 Ks 工具链（perl + pal2nal.pl + yn00.exe），Ks 步骤会跳过")
        else:
            for problem in rt.problems:
                self._log("✕ " + problem)

    def _log(self, message: str) -> None:
        self.log.appendPlainText(message)

    # --- actions ------------------------------------------------------
    def _start(self) -> None:
        missing = self.box_a.missing()
        if missing:
            self._log("物种 A 还缺：" + "、".join(missing))
            return
        if not self.self_check.isChecked() and self.box_b.missing():
            self._log("物种 B 还缺：" + "、".join(self.box_b.missing()))
            return
        for box in (self.box_a, self.box_b):
            for key, edit in box.fields.items():
                text = edit.text().strip()
                if text and not Path(text).exists():
                    self._log(f"文件不存在：{text}")
                    return

        base = Path(self.dir_edit.text().strip() or str(default_projects_dir()))
        name = self.name_edit.text().strip() or "analysis"
        self_compare = self.self_check.isChecked()
        a = self.box_a.to_input("A")
        if not a.display_name:
            a.prefix = _prefix_from(a.genome or a.fai or a.pep or "A")
        b = None
        if not self_compare:
            b = self.box_b.to_input("B")
            if not b.display_name:
                b.prefix = _prefix_from(b.genome or b.fai or b.pep or "B")

        try:
            project = Project.create(
                base, name, self_compare=self_compare, genome_a=a, genome_b=b,
                engine="diamond" if self.engine.currentIndex() == 1 else "blastp",
                threads=self.threads.value(), app_version=info.VERSION)
        except Exception as exc:  # noqa: BLE001
            self._log(f"无法创建项目：{exc}")
            return
        params = project.params
        project.params = type(params)(
            **{**params.to_dict(), "evalue": self.evalue.text().strip() or params.evalue,
               "score": self.score.value()})
        project.save()
        self._project = project
        self._log(f"项目：{project.root}")
        self._log(f"对比：{project.stem}（{'自比较' if self_compare else '两物种'}）")

        rt = runtime_mod.discover()
        if not rt.ok:
            self._log("运行时不可用，无法开始")
            return

        for key, _ in STEPS:
            self.steps.set_state(key, "pending")
        self.bar.setVisible(True)
        self.bar.set_value(0)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.open_btn.setEnabled(False)

        worker = PipelineWorker(project, rt, self)
        worker.signals.log.connect(self._log)
        worker.signals.step.connect(self._on_step)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.done.connect(self._on_done)
        worker.signals.failed.connect(self._on_failed)
        self._worker = worker
        worker.start()

    def _cancel(self) -> None:
        if self._worker is not None:
            self._log("正在取消…")
            if self._worker.pipeline is not None:
                self._worker.pipeline.cancel()
            self.cancel_btn.setEnabled(False)

    def _on_step(self, key: str, state: str) -> None:
        self.steps.set_state(key, state)
        keys = [k for k, _ in STEPS]
        if key in keys:
            index = keys.index(key)
            if state in ("done", "skipped"):
                self.bar.set_value((index + 1) * 10)
            elif state == "running":
                self.bar.set_value(index * 10)

    def _on_progress(self, key: str, done: int, total: int, eta: float) -> None:
        if total:
            base = [k for k, _ in STEPS].index(key) if key in [k for k, _ in STEPS] else 0
            self.bar.set_value(base * 10 + int(done * 10 / total))
        if eta >= 0:
            minutes, seconds = divmod(int(eta), 60)
            self.eta.setText(f"{done}/{total} · 预计剩余 {minutes} 分 {seconds} 秒")
        else:
            self.eta.setText(f"{done}/{total}")

    def _on_done(self, results: list) -> None:
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.bar.setVisible(False)
        self.eta.setText("")
        ok = sum(1 for _k, good, _s, _m in results if good)
        self._log(f"结束：{ok}/{len(results)} 步完成")
        for key, good, skipped, message in results:
            if skipped:
                self._log(f"  跳过 {key}：{message}")
            elif not good:
                self._log(f"  失败 {key}：{message}")
        if self._project is not None and (self._project.results / f"{self._project.stem}.pdf").exists():
            self.open_btn.setEnabled(True)
            self._log("Circos 已生成，可点「载入 Circos」查看")

    def _on_failed(self, message: str) -> None:
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.bar.setVisible(False)
        self._log("出错：" + message)

    def _load_results(self) -> None:
        if self._project is not None:
            self.load_requested.emit(str(self._project.root))
            self.accept()

    def closeEvent(self, event) -> None:  # noqa: D102
        if self._worker is not None and self._worker.isRunning():
            self._worker.pipeline and self._worker.pipeline.cancel()
            self._worker.wait(3000)
        super().closeEvent(event)


def _default_threads() -> int:
    import os

    return max(1, min(8, os.cpu_count() or 4))


def _prefix_from(path: str) -> str:
    import re

    stem = Path(path).name.split(".")[0]
    stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "", stem) or "genome"
    return stem[:12]
