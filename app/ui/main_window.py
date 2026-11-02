"""M0.5 shell: explicit input slots, a generate action, and the result stage."""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QPoint, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme
from . import about as about_dialog
from .. import build_info as info
from ..paths import data_root
from ..core import palette as palette_mod
from ..core import style as style_mod
from ..core import wgdi
from ..core.model import Dataset
from ..core.style import Style
from .worker import ExportWorker, RenderWorker
from .widgets import (
    Card,
    Check,
    DropZone,
    ProgressStrip,
    SectionHeader,
    SliderRow,
    SlotRow,
    ThemeToggle,
)

if getattr(sys, "frozen", False):
    # Inside a PyInstaller bundle the code folder is read-only: keep runtime
    # artefacts (preview renders) in the user's temp directory instead.
    RES = Path(tempfile.gettempdir()) / "CircosStudio"
else:
    RES = Path(__file__).resolve().parent.parent / "resources"
RES.mkdir(parents=True, exist_ok=True)
PROJECT = Path(__file__).resolve().parents[2] if getattr(sys, "frozen", False) \
    else Path(__file__).resolve().parents[3]
DEMO = data_root() / "circos_plot_v2" / "data" / "01_Sjap_vs_Sjap"

SLOTS_SELF = ("a_gff", "a_len", "blocks")
SLOTS_PAIRED = ("a_gff", "a_len", "b_gff", "b_len", "blocks")


# ---------------------------------------------------------------- title bar
class TitleBar(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.setObjectName("titleBar")
        self.setFixedHeight(46)
        self._win = window
        self._press_pos: QPoint | None = None
        self._dragging = False
        t = theme.theme()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 10, 0)
        lay.setSpacing(10)

        mark = QLabel()
        mark.setPixmap(icons.pixmap("circle-dot", t["accent"], 18))
        lay.addWidget(mark)
        name = QLabel(info.APP_NAME)
        name.setObjectName("appName")
        lay.addWidget(name)
        tag = QLabel(f"作者：{info.DEVELOPER}；版本：{info.VERSION}")
        tag.setObjectName("appTag")
        lay.addWidget(tag)
        lay.addStretch(1)

        about = QToolButton()
        about.setObjectName("winBtn")
        about.setCursor(Qt.PointingHandCursor)
        about.setIcon(icons.icon("circle-dot", t["ink2"], 15))
        about.setToolTip(f"关于 {info.APP_NAME}")
        about.clicked.connect(lambda: about_dialog.show(self._win, self._win._mode))
        lay.addWidget(about)

        self.theme_toggle = ThemeToggle(self)
        self.theme_toggle.set_mode(window._mode)
        self.theme_toggle.toggled_theme.connect(window.switch_theme)
        lay.addWidget(self.theme_toggle)

        for name_, tip, slot in (
            ("minus", "最小化", window.showMinimized),
            ("square", "最大化", window.toggle_max),
            ("x", "关闭", window.close),
        ):
            b = QToolButton()
            b.setObjectName("winClose" if name_ == "x" else "winBtn")
            if name_ == "x":
                self.close_btn = b
            b.setCursor(Qt.PointingHandCursor)
            b.setIcon(icons.icon(name_, t["ink2"], 15))
            b.setToolTip(tip)
            b.clicked.connect(slot)
            lay.addWidget(b)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._press_pos = ev.globalPosition().toPoint()
            self._dragging = False
            ev.accept()

    def mouseMoveEvent(self, ev) -> None:
        """Hand the move to Windows once the pointer actually starts dragging.

        Moving the window from Python desynchronises Qt's hit testing, which
        made the window buttons unclickable after a drag; startSystemMove keeps
        the OS in charge and also gives proper snap layouts.
        """
        if self._press_pos is None or self._dragging or not (ev.buttons() & Qt.LeftButton):
            return
        if (ev.globalPosition().toPoint() - self._press_pos).manhattanLength() < 5:
            return
        handle = self._win.windowHandle()
        if handle is None:
            return
        self._dragging = True
        if self._win.isMaximized():
            self._win.showNormal()
            self._win.move(ev.globalPosition().toPoint() - QPoint(self._win.width() // 2, 20))
        handle.startSystemMove()
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:
        self._press_pos = None
        self._dragging = False

    def mouseDoubleClickEvent(self, ev) -> None:
        self._press_pos = None
        self._win.toggle_max()


# ---------------------------------------------------------------- canvas
class CanvasView(QGraphicsView):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("canvas")
        self.setFrameShape(QFrame.NoFrame)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item: QGraphicsPixmapItem | None = None
        self._base_scale = 1.0

    def set_pixmap(self, pm: QPixmap, fit: bool = True) -> None:
        transform = None if fit else self.transform()
        center = None if fit else self.mapToScene(self.viewport().rect().center())
        self._scene.clear()
        self._item = self._scene.addPixmap(pm)
        self._item.setTransformationMode(Qt.SmoothTransformation)
        self._scene.setSceneRect(self._item.boundingRect())
        if fit:
            self.fit()
        elif transform is not None:
            self.setTransform(transform)
            self.centerOn(center)

    def clear(self) -> None:
        self._scene.clear()
        self._item = None

    def fit(self) -> None:
        if not self._item:
            return
        self.resetTransform()
        r = self._item.boundingRect()
        vw, vh = self.viewport().width() - 40, self.viewport().height() - 40
        s = min(vw / r.width(), vh / r.height()) if r.width() and r.height() else 1.0
        self._base_scale = s
        self.scale(s, s)
        self.centerOn(self._item)

    def wheelEvent(self, ev) -> None:
        if not self._item:
            return
        f = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
        cur = self.transform().m11()
        if 0.15 * self._base_scale < cur * f < 12 * self._base_scale:
            self.scale(f, f)

    def mouseDoubleClickEvent(self, ev) -> None:
        self.fit()


# ---------------------------------------------------------------- empty state
class EmptyStage(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        t = theme.theme()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addStretch(1)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("image", t["border_strong"], 44))
        ic.setAlignment(Qt.AlignCenter)
        lay.addWidget(ic)
        a = QLabel("还没有生成图片")
        a.setAlignment(Qt.AlignCenter)
        a.setStyleSheet(f"font-size:13px;font-weight:600;color:{t['ink2']};")
        lay.addWidget(a)
        b = QLabel("在左侧填好输入文件，然后点「生成图片」")
        b.setAlignment(Qt.AlignCenter)
        b.setObjectName("hint")
        lay.addWidget(b)
        lay.addStretch(1)


# ---------------------------------------------------------------- window
class MainWindow(QWidget):
    def __init__(self, mode: str = "light"):
        super().__init__()
        self._mode = mode
        self._generated = False
        self._base_style = style_mod.default()
        self._worker = None
        self._export_worker = None
        self._dataset: Dataset | None = None
        self._slots: dict[str, SlotRow] = {}
        self._pending: tuple[Style, bool] | None = None
        self._rendering_draft = False
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(220)
        self._draft_timer.timeout.connect(lambda: self._queue_render(self._current_style(), True))
        self._full_timer = QTimer(self)
        self._full_timer.setSingleShot(True)
        self._full_timer.setInterval(260)
        self._full_timer.timeout.connect(self._upgrade_to_full)
        self._settings = QSettings("CircosStudio", "CircosStudio")
        t = theme.theme(mode)
        self.setWindowTitle(info.APP_NAME)
        self.setObjectName("root")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.resize(1600, 900)
        self.setMinimumSize(1280, 720)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = TitleBar(self)
        root.addWidget(self.title_bar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_panel(t))
        body.addWidget(self._build_stage(t), 1)
        root.addLayout(body, 1)
        root.addWidget(self._build_status(t))

        geo = self._settings.value("geometry_v2")
        if geo is not None:
            self.restoreGeometry(geo)
        self._load_demo()
        self._refresh_state()
        if geo is None:
            self._center()

    # -- left panel ------------------------------------------------------
    def _build_panel(self, t: dict) -> QWidget:
        panel = QWidget()
        panel.setObjectName("panel")
        panel.setFixedWidth(360)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(16, 6, 16, 6)
        v.setSpacing(6)

        # ---- 1. data ----------------------------------------------------
        c1 = Card(padding=9, spacing=6)
        head = SectionHeader("1", "数据")
        self._ready = QLabel("0 / 3 已就绪")
        self._ready.setObjectName("valueChip")
        head.add_right(self._ready)
        c1.add(head)

        self._drop = DropZone(height=40)
        self._drop.filesDropped.connect(self._assign_files)
        c1.add(self._drop)

        self._self_cmp = Check("自比较（只用物种 A，B 自动沿用 A）")
        self._self_cmp.setChecked(True)
        self._self_cmp.toggled.connect(self._on_mode_changed)
        c1.add(self._self_cmp)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet(f"font-size:11px;color:{t['ink2']};background:transparent;")
        self._summary.hide()
        c1.add(self._summary)

        spec = [
            ("a_gff", "物种 A · GFF 基因坐标", "必填"),
            ("a_len", "物种 A · LEN 染色体长度", "必填"),
            ("b_gff", "物种 B · GFF 基因坐标", "必填"),
            ("b_len", "物种 B · LEN 染色体长度", "必填"),
            ("blocks", "共线块 · block_information.csv", "必填"),
        ]
        for key, title, hint in spec:
            row = SlotRow(title, hint)
            row.picked.connect(lambda _=False, k=key: self._pick(k))
            self._slots[key] = row
            c1.add(row)
        v.addWidget(c1)

        # ---- 2. style ---------------------------------------------------
        c2 = Card(padding=9, spacing=6)
        head2 = SectionHeader("2", "样式")
        tools_row = QWidget()
        tl = QHBoxLayout(tools_row)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(6)
        self._btn_auto = QPushButton("自动设置")
        self._btn_auto.setObjectName("ghost")
        self._btn_auto.setFixedHeight(24)
        self._btn_auto.setCursor(Qt.PointingHandCursor)
        self._btn_auto.setToolTip("按扇区数和连线数自动定字号、间隙和线宽")
        self._btn_auto.clicked.connect(self._on_auto_style)
        tl.addWidget(self._btn_auto)
        self._btn_default = QPushButton("默认")
        self._btn_default.setObjectName("ghost")
        self._btn_default.setFixedHeight(24)
        self._btn_default.setCursor(Qt.PointingHandCursor)
        self._btn_default.setToolTip("回到论文默认样式")
        self._btn_default.clicked.connect(self._on_default_style)
        tl.addWidget(self._btn_default)
        head2.add_right(tools_row)
        c2.add(head2)

        pal_row = QHBoxLayout()
        pal_row.setContentsMargins(0, 0, 0, 0)
        pal_row.setSpacing(8)
        pal_lbl = QLabel("配色板")
        pal_lbl.setObjectName("fieldLabel")
        pal_row.addWidget(pal_lbl)
        self._palette = QComboBox()
        self._palette.setCursor(Qt.PointingHandCursor)
        for p in palette_mod.all_palettes():
            self._palette.addItem(p.label, p.key)
        self._palette.currentIndexChanged.connect(self._on_style_changed)
        pal_row.addWidget(self._palette, 1)
        c2.body().addLayout(pal_row)

        self._sliders = {}
        for key, label, lo, hi, val, step, dec, suf in (
            ("anchors", "最少锚点数", 5, 300, 50, 5, 0, ""),
            ("width", "连线线宽", 0.2, 2.0, 0.7, 0.05, 2, ""),
            ("font", "标签字号", 1.0, 8.0, 2.126, 0.002, 3, " pt"),
            ("gap", "扇区间隙", 0.2, 6.0, 2.16, 0.02, 2, "°"),
        ):
            s = SliderRow(label, lo, hi, val, step=step, decimals=dec, suffix=suf)
            s.valueChanged.connect(self._on_style_changed)
            self._sliders[key] = s
            c2.add(s)
        v.addWidget(c2)

        # ---- 3. output --------------------------------------------------
        c3 = Card(padding=9, spacing=6)
        c3.add(SectionHeader("3", "输出"))
        meta = QLabel("50 × 52 mm　·　600 dpi　·　Arial")
        meta.setObjectName("hint")
        c3.add(meta)

        fmts = QHBoxLayout()
        fmts.setSpacing(12)
        self._format_checks: dict[str, Check] = {}
        for name, checked in (("PDF", True), ("SVG", True), ("PNG", False), ("TIFF", False)):
            cb = Check(name)
            cb.setChecked(checked)
            self._format_checks[name] = cb
            fmts.addWidget(cb)
        fmts.addStretch(1)
        c3.body().addLayout(fmts)
        self._open_after = Check("导出后打开文件夹")
        self._open_after.setChecked(True)
        c3.add(self._open_after)
        v.addWidget(c3)
        v.addStretch(1)

        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        # ---- fixed action bar ------------------------------------------
        foot = QWidget()
        foot.setObjectName("panelFooter")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(16, 12, 16, 12)
        fl.setSpacing(8)

        self.btn_analysis = QPushButton("全流程分析")
        self.btn_analysis.setObjectName("ghost")
        self.btn_analysis.setCursor(Qt.PointingHandCursor)
        self.btn_analysis.setIcon(icons.icon("circle-dot", t["ink2"], 15))
        self.btn_analysis.setIconSize(QSize(15, 15))
        self.btn_analysis.setMinimumHeight(38)
        self.btn_analysis.setToolTip(
            "上传基因组与注释，自动完成 blastp、共线性、Ks、块汇总，并直接出 Circos")
        self.btn_analysis.clicked.connect(self._on_open_analysis)
        fl.addWidget(self.btn_analysis, 1)

        self.btn_generate = QPushButton("生成图片")
        self.btn_generate.setObjectName("primary")
        self.btn_generate.setToolTip("按当前数据与样式出图；改样式后会自动刷新预览")
        self.btn_generate.setCursor(Qt.PointingHandCursor)
        self.btn_generate.setIcon(icons.icon("layers", t["accent_ink"], 16))
        self.btn_generate.setIconSize(QSize(16, 16))
        self.btn_generate.setMinimumHeight(38)
        self.btn_generate.clicked.connect(self._on_generate)
        fl.addWidget(self.btn_generate, 2)

        self.btn_export = QPushButton("导出")
        self.btn_export.setObjectName("ghost")
        self.btn_export.setToolTip("导出勾选的格式到指定文件夹（600 dpi）")
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.setIcon(icons.icon("download", t["ink2"], 15))
        self.btn_export.setIconSize(QSize(15, 15))
        self.btn_export.setMinimumHeight(38)
        self.btn_export.clicked.connect(self._on_export)
        fl.addWidget(self.btn_export, 1)

        outer.addWidget(foot)
        return panel

    # -- right stage -----------------------------------------------------
    def _build_stage(self, t: dict) -> QWidget:
        stage = QWidget()
        stage.setObjectName("stage")
        lay = QVBoxLayout(stage)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        dot = QLabel()
        dot.setPixmap(icons.pixmap("circle-dot", t["accent"], 14))
        bar.addWidget(dot)
        self._stage_title = QLabel("未生成")
        self._stage_title.setStyleSheet(
            f"font-family:{theme.FONT_DISPLAY};font-size:13px;font-weight:600;color:{t['ink']};"
        )
        bar.addWidget(self._stage_title)
        self._stage_meta = QLabel("")
        self._stage_meta.setObjectName("hint")
        bar.addWidget(self._stage_meta)
        bar.addStretch(1)

        self._btn_fit = QToolButton()
        self._btn_fit.setObjectName("ghostIcon")
        self._btn_fit.setIcon(icons.icon("fit", t["ink2"], 16))
        self._btn_fit.setToolTip("适应窗口（双击画布）")
        self._btn_fit.setCursor(Qt.PointingHandCursor)
        self._btn_fit.setFixedSize(28, 26)
        bar.addWidget(self._btn_fit)

        self.canvas = CanvasView()
        self._btn_fit.clicked.connect(self.canvas.fit)

        self._empty = EmptyStage()

        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 10, 10, 10)
        cl.setSpacing(6)
        cl.addLayout(bar)
        stack = QWidget()
        sl = QVBoxLayout(stack)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        sl.addWidget(self._empty)
        sl.addWidget(self.canvas)
        self.canvas.hide()
        cl.addWidget(stack, 1)
        lay.addWidget(card, 1)

        QTimer.singleShot(60, self.canvas.fit)
        return stage

    # -- status ----------------------------------------------------------
    def _build_status(self, t: dict) -> QWidget:
        wrap = QWidget()
        wrap.setObjectName("statusBar")
        wrap.setFixedHeight(46)
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.progress = ProgressStrip()
        self.progress.hide()
        v.addWidget(self.progress)

        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(16, 0, 12, 0)
        h.setSpacing(8)
        self.status_text = QLabel("就绪")
        self.status_text.setObjectName("statusText")
        h.addWidget(self.status_text)
        h.addStretch(1)
        self._status_meta = QLabel("密度窗口 1 Mb · 配色 14 色")
        self._status_meta.setObjectName("statusMeta")
        h.addWidget(self._status_meta)
        grip = QSizeGrip(row)
        grip.setFixedSize(14, 14)
        h.addWidget(grip, 0, Qt.AlignBottom)
        v.addWidget(row, 1)
        return wrap

    # -- demo data -------------------------------------------------------
    def _on_open_analysis(self) -> None:
        from .analysis import AnalysisDialog

        dialog = AnalysisDialog(self, self._mode)
        dialog.load_requested.connect(self._load_project)
        dialog.exec()

    def _load_project(self, root: str) -> None:
        """Point the plotting slots at a finished project's results."""
        from PySide6.QtWidgets import QMessageBox

        from ..wgdi.project import Project

        try:
            project = Project.load(Path(root))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "无法载入项目", str(exc))
            return
        self._self_cmp.setChecked(project.self_compare)
        pairs = [
            ("a_gff", project.prepared / f"{project.genome_a.prefix}.gff"),
            ("a_len", project.prepared / f"{project.genome_a.prefix}.len"),
            ("blocks", project.work / f"{project.stem}_block_information.csv"),
        ]
        if not project.self_compare and project.genome_b is not None:
            pairs += [
                ("b_gff", project.prepared / f"{project.genome_b.prefix}.gff"),
                ("b_len", project.prepared / f"{project.genome_b.prefix}.len"),
            ]
        for key, path in pairs:
            self._slots[key].set_path(path if path.exists() else None)
        self._refresh_state()
        self._on_generate()

    def _load_demo(self) -> None:
        """Open the real dataset 01 so the first screen shows real numbers."""
        demo = {
            "a_gff": DEMO / "genome1.gff",
            "a_len": DEMO / "genome1.len",
            "blocks": DEMO / "original_block_information.csv",
        }
        for k, path in demo.items():
            if path.exists():
                self._slots[k].set_path(path)
                self._probe_slot(k)

    # -- state -----------------------------------------------------------
    def _required(self) -> tuple[str, ...]:
        return SLOTS_SELF if self._self_cmp.isChecked() else SLOTS_PAIRED

    def _probe_slot(self, key: str) -> None:
        """Cheap per-file look so the user sees what is inside before generating."""
        row = self._slots[key]
        path = row.path()
        if path is None:
            row.set_detail("")
            return
        if key.endswith("gff"):
            probe = wgdi.probe_gff(path)
        elif key.endswith("len"):
            probe = wgdi.probe_len(path)
        else:
            probe = wgdi.probe_blocks(path)
        if probe.ok:
            row.set_detail(probe.detail, "ok")
        else:
            row.set_detail(probe.error, "err")

    def _set_slot(self, key: str, path: Path | None) -> None:
        self._slots[key].set_path(path)
        if path is None:
            self._slots[key].set_detail("")
        else:
            self._probe_slot(key)
        self._refresh_state()

    def _refresh_state(self) -> None:
        req = self._required()
        paired = not self._self_cmp.isChecked()
        for key in ("b_gff", "b_len"):
            self._slots[key].setVisible(paired)
        have = sum(1 for k in req if (p := self._slots[k].path()) is not None and p.exists())
        self._ready.setText(f"{have} / {len(req)} 已就绪")
        ready = have == len(req)
        self._dataset = None
        if ready:
            self._dataset = self._validate_full(req, paired)
        self.btn_generate.setEnabled(self._dataset is not None)
        self.btn_export.setEnabled(self._dataset is not None and self._generated)
        if not ready:
            self._summary.hide()
            self.btn_generate.setToolTip("还缺少输入文件")
        elif self._dataset is None:
            self.btn_generate.setToolTip("输入文件有错误，见上方红字")

    def _validate_full(self, req: tuple[str, ...], paired: bool) -> Dataset | None:
        """Parse everything together; show the real block / link counts."""
        g = {k: self._slots[k].path() for k in req}
        try:
            dataset, issues = wgdi.load_dataset(
                gff1=g["a_gff"], len1=g["a_len"], blocks_csv=g["blocks"],
                gff2=g["b_gff"] if paired else None,
                len2=g["b_len"] if paired else None,
                layout="paired" if paired else "self",
                name1="A", name2="B",
            )
        except wgdi.WgdiError as exc:
            self._summary.setText(f"✕ {exc}")
            self._summary.setStyleSheet(
                f"font-size:11px;color:{theme.theme()['danger']};background:transparent;")
            self._summary.show()
            self.status_text.setText("输入文件有问题")
            return None
        pairs = dataset.anchor_pairs(50)
        kept = len(dataset.drawable_blocks(50))
        errors = [i for i in issues if i.level == "error"]
        warnings = [i for i in issues if i.level == "warning"]
        self._pending_pairs = len(pairs)
        self._pending_blocks = kept
        self._pending_sectors = (
            len(dataset.genome1.chromosomes) if not paired
            else len(dataset.genome1.chromosomes) + len(dataset.genome2.chromosomes)
        ) * (2 if not paired else 1)
        bits = [f"✓ {len(dataset.blocks):,} 个共线块，保留 {kept:,} 个，{len(pairs):,} 条连线"]
        if warnings:
            bits.append(f"{len(warnings)} 条警告")
        if errors:
            bits.append(f"{len(errors)} 条错误")
        self._summary.setText("；".join(bits))
        self._summary.setStyleSheet(
            f"font-size:11px;color:{theme.theme()['ink2']};background:transparent;")
        self._summary.show()
        if paired:
            self.status_text.setText(
                f"已读取 · {len(dataset.genome1.genes):,} + {len(dataset.genome2.genes):,} 个基因")
        else:
            self.status_text.setText(f"已读取 · {len(dataset.genome1.genes):,} 个基因")
        return dataset

    def _on_mode_changed(self, *_args) -> None:
        self._refresh_state()

    def _on_style_changed(self, *_args) -> None:
        self._schedule_draft()

    def _schedule_draft(self) -> None:
        """Debounced draft redraw; only after the first figure exists."""
        if self._generated:
            self._draft_timer.start()

    # -- style -----------------------------------------------------------
    def _current_style(self) -> Style:
        return style_mod.replace(
            self._base_style,
            min_anchors=int(self._sliders["anchors"].value()),
            link_width_px=round(self._sliders["width"].value(), 3),
            label_pt=round(self._sliders["font"].value(), 3),
            gap_deg=round(self._sliders["gap"].value(), 3),
            palette=self._palette.currentData() or "paper1",
            title="" if self._dataset_title() == "自比较" else self._dataset_title(),
        )

    def _apply_style(self, style: Style) -> None:
        self._base_style = style
        for key, val in (("anchors", style.min_anchors), ("width", style.link_width_px),
                         ("font", style.label_pt), ("gap", style.gap_deg)):
            s = self._sliders[key]
            s.blockSignals(True)
            s.set_value(val)
            s.blockSignals(False)
        idx = self._palette.findData(style.palette)
        if idx >= 0:
            self._palette.blockSignals(True)
            self._palette.setCurrentIndex(idx)
            self._palette.blockSignals(False)
        self._schedule_draft()

    def _on_auto_style(self) -> None:
        if self._dataset is None:
            self.status_text.setText("先选好输入文件，才能按数据规模自动设置")
            return
        sectors = getattr(self, "_pending_sectors", 28)
        links = getattr(self, "_pending_pairs", 15_000)
        self._apply_style(style_mod.auto(sectors, links, self._palette.currentData() or "paper1"))
        self.status_text.setText(
            f"已自动适配 {sectors} 扇区 / {links:,} 条连线：标签 "
            f"{self._sliders['font'].value():.2f} pt，间隙 {self._sliders['gap'].value():.2f}°，"
            f"线宽 {self._sliders['width'].value():.2f}")

    def _on_default_style(self) -> None:
        self._apply_style(style_mod.default())
        self.status_text.setText("已恢复论文默认样式")

    def _pick(self, key: str) -> None:
        patterns = {
            "a_gff": "基因坐标 (*.gff *.gff3 *.txt)",
            "b_gff": "基因坐标 (*.gff *.gff3 *.txt)",
            "a_len": "染色体长度 (*.len *.txt)",
            "b_len": "染色体长度 (*.len *.txt)",
            "blocks": "共线块 (*.csv)",
        }
        start = self._settings.value("last_input_dir", str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(self, "选择文件", str(start), patterns[key])
        if path:
            self._settings.setValue("last_input_dir", str(Path(path).parent))
            self._set_slot(key, Path(path))

    def _assign_files(self, paths: list[str]) -> None:
        """Drop handler: place each file into the first empty slot it fits."""
        order = list(self._required())
        for raw in paths:
            p = Path(raw)
            suf = p.suffix.lower()
            if suf in (".gff", ".gff3"):
                targets = ["a_gff", "b_gff"]
            elif suf == ".len":
                targets = ["a_len", "b_len"]
            elif suf in (".csv", ".tsv"):
                targets = ["blocks"]
            else:
                continue
            for t in targets:
                if t in order and self._slots[t].path() is None:
                    self._slots[t].set_path(p)
                    self._probe_slot(t)
                    break
        self._refresh_state()

    # -- rendering -------------------------------------------------------
    def _preview_dpi(self) -> int:
        style = self._current_style()
        width_px = max(320, self.canvas.viewport().width() - 40)
        return int(max(150, min(600, round(width_px / (style.page_w_mm / 25.4)))))

    def _draft_settings(self) -> tuple[int, int]:
        """Low resolution plus a subsampled link set, for a sub-second draft."""
        dpi = max(110, self._preview_dpi() // 2)
        n = max(1, getattr(self, "_pending_pairs", 15_000))
        return dpi, max(1, n // 6000)

    def _busy(self, on: bool, text: str = "", progress: bool = True) -> None:
        if on:
            if progress:
                self.progress.show()
                self.progress.start()
            self.btn_generate.setEnabled(False)
            self.btn_export.setEnabled(False)
            if text:
                self.status_text.setText(text)
        else:
            self.progress.stop()
            self.progress.hide()
            self.btn_generate.setEnabled(self._dataset is not None)
            self.btn_export.setEnabled(self._dataset is not None and self._generated)

    def _queue_render(self, style: Style, draft: bool) -> None:
        """One render at a time; a newer request replaces the one waiting."""
        if self._dataset is None:
            return
        self._pending = (style, draft)
        if self._worker is None:
            self._start_queued()

    def _start_queued(self) -> None:
        if self._pending is None or self._dataset is None:
            return
        style, draft = self._pending
        self._pending = None
        self._rendering_draft = draft
        if draft:
            dpi, subsample = self._draft_settings()
            style = style_mod.replace(style, show_labels=False, title="")
            self._busy(True, "正在更新预览…", progress=False)
            out = RES / "draft.png"
        else:
            dpi, subsample = self._preview_dpi(), 1
            self._busy(True, "正在生成…")
            out = RES / "preview_live.png"
        self._worker = RenderWorker(self._dataset, style, out, dpi, subsample)
        self._worker.progress.connect(self.status_text.setText)
        self._worker.done.connect(lambda p, st, d=draft: self._render_done(p, st, d))
        self._worker.failed.connect(self._render_failed)
        self._worker.finished.connect(self._worker_finished)
        self._worker.start()

    def _worker_finished(self) -> None:
        self._worker = None
        if self._pending is not None:
            QTimer.singleShot(0, self._start_queued)
        elif not self._rendering_draft:
            self._busy(False)

    def _on_generate(self) -> None:
        self._draft_timer.stop()
        self._full_timer.stop()
        self._queue_render(self._current_style(), False)

    def _upgrade_to_full(self) -> None:
        if self._generated and self._worker is None:
            self._queue_render(self._current_style(), False)

    def _render_done(self, path: str, stats: dict, draft: bool = False) -> None:
        pm = QPixmap(path)
        if pm.isNull():
            self._render_failed("渲染结果无法读取")
            return
        self.canvas.set_pixmap(pm, fit=not draft)
        self._empty.hide()
        self.canvas.show()
        first = not self._generated
        self._generated = True
        if draft:
            self._full_timer.start()
            return
        self._stage_title.setText(self._dataset_title())
        self._stage_meta.setText(
            f"{stats.get('sectors', 0)} 扇区 · {int(stats.get('links', 0)):,} 条连线")
        self.status_text.setText("已生成 · 可继续调样式或导出")
        self.btn_generate.setText("重新生成")
        self.btn_export.setEnabled(True)
        if first:
            QTimer.singleShot(60, self.canvas.fit)

    def _render_failed(self, message: str) -> None:
        self._busy(False)
        self.status_text.setText(f"渲染失败：{message}")
        self._summary.setText(f"✕ 渲染失败：{message}")
        self._summary.setStyleSheet(
            f"font-size:11px;color:{theme.theme()['danger']};background:transparent;")
        self._summary.show()

    def _dataset_title(self) -> str:
        """Best-effort readable name; the renderer draws its own title."""
        blocks = self._slots["blocks"].path()
        stem = blocks.stem if blocks else ""
        m = re.match(r"^(.+?)-(.+?)_block", stem)
        if m:
            return f"{m.group(1)} \u2013 {m.group(2)}"
        if self._self_cmp.isChecked():
            return "自比较"
        a = self._slots["a_gff"].path()
        b = self._slots["b_gff"].path()
        return f"{a.stem if a else 'A'} \u2013 {b.stem if b else 'B'}"

    def _on_export(self) -> None:
        if self._dataset is None or self._export_worker is not None:
            return
        formats = [k for k, cb in self._format_checks.items() if cb.isChecked()]
        if not formats:
            self.status_text.setText("至少勾选一种导出格式")
            return
        last = self._settings.value("last_export_dir", str(Path.home()))
        out_dir = QFileDialog.getExistingDirectory(self, "选择导出文件夹", str(last))
        if not out_dir:
            return
        self._settings.setValue("last_export_dir", out_dir)
        self._busy(True, "正在导出…")
        stem = self._dataset_title().replace(" \u2013 ", "-").replace(" ", "_")
        self._export_worker = ExportWorker(self._dataset, self._current_style(),
                                           Path(out_dir), stem, formats, 600)
        self._export_worker.progress.connect(self.status_text.setText)
        self._export_worker.done.connect(self._export_done)
        self._export_worker.failed.connect(self._render_failed)
        self._export_worker.finished.connect(self._export_finished)
        self._export_worker.start()

    def _export_finished(self) -> None:
        self._export_worker = None

    def _export_done(self, paths: list) -> None:
        self._busy(False)
        names = "、".join(Path(x).name for x in paths)
        self.status_text.setText(f"已导出 {len(paths)} 个文件：{names}")
        if paths and self._open_after.isChecked():
            try:
                os.startfile(str(Path(paths[0]).parent))
            except OSError:
                pass

    # -- window chrome ---------------------------------------------------
    def nativeEvent(self, event_type, message):  # noqa: N802 (Qt naming)
        """Edge resize for the frameless window.

        WM_NCHITTEST reports **physical** pixels while Qt's coordinate system is
        logical, so the hit test is done entirely in physical pixels using
        GetWindowRect. Mixing the two made the whole right-hand side of the
        window behave like a resize edge at 150% display scaling.
        """
        if event_type == b"windows_generic_MSG":
            try:
                import ctypes
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084 and not self.isMaximized():   # WM_NCHITTEST
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    rect = wintypes.RECT()
                    ctypes.windll.user32.GetWindowRect(
                        wintypes.HWND(int(self.winId())), ctypes.byref(rect))
                    w = rect.right - rect.left
                    h = rect.bottom - rect.top
                    if w <= 0 or h <= 0:
                        return super().nativeEvent(event_type, message)
                    px, py = x - rect.left, y - rect.top
                    band = max(4, int(round(5 * self.devicePixelRatioF())))
                    left, right = px < band, px >= w - band
                    top, bottom = py < band, py >= h - band
                    if top and left:
                        return True, 13
                    if top and right:
                        return True, 14
                    if bottom and left:
                        return True, 16
                    if bottom and right:
                        return True, 17
                    if left:
                        return True, 10
                    if right:
                        return True, 11
                    if top:
                        return True, 12
                    if bottom:
                        return True, 15
            except Exception:  # noqa: BLE001 - never break the window over a hit test
                pass
        return super().nativeEvent(event_type, message)

    def closeEvent(self, ev) -> None:  # noqa: N802
        self._settings.setValue("geometry_v2", self.saveGeometry())
        self._settings.setValue("theme", self._mode)
        super().closeEvent(ev)

    def switch_theme(self, mode: str) -> None:
        app = QApplication.instance()
        theme.apply(app, mode)
        self._reopen(mode)

    def _reopen(self, mode: str) -> None:
        new = MainWindow(mode)
        new.move(self.pos())
        new.resize(self.size())
        new.show()
        self.close()
        QApplication.instance()._main = new  # type: ignore[attr-defined]

    def toggle_max(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def _center(self) -> None:
        scr = QApplication.primaryScreen().availableGeometry()
        self.move(scr.center() - self.rect().center())
