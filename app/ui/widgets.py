"""Custom widgets that give the app its own look instead of the native Qt one."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme


class Card(QFrame):
    """Rounded white card with a soft border."""

    def __init__(self, parent: QWidget | None = None, padding: int = 14, spacing: int = 10):
        super().__init__(parent)
        self.setObjectName("card")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(padding, padding, padding, padding)
        self._lay.setSpacing(spacing)

    def body(self) -> QVBoxLayout:
        return self._lay

    def add(self, w: QWidget) -> QWidget:
        self._lay.addWidget(w)
        return w


class SectionHeader(QWidget):
    def __init__(self, index: str, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(8)
        badge = QLabel(index)
        badge.setObjectName("sectionIndex")
        badge.setFixedHeight(18)
        lay.addWidget(badge)
        lbl = QLabel(title)
        lbl.setObjectName("sectionTitle")
        lay.addWidget(lbl)
        lay.addStretch(1)
        self._lay = lay

    def add_right(self, w: QWidget) -> None:
        self._lay.addWidget(w)


class SegmentedControl(QWidget):
    """Pill switcher with a sliding indicator."""

    changed = Signal(int)

    def __init__(self, items: list[str], parent: QWidget | None = None, height: int = 32):
        super().__init__(parent)
        self.setObjectName("segmented")
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        t = theme.theme()
        self._bg = QColor(t["track"])
        self._pill = QColor(t["card"])
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(3, 3, 3, 3)
        self._lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[QPushButton] = []
        for i, text in enumerate(items):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton{background:transparent;border:none;border-radius:6px;"
                f"color:{t['ink2']};font-size:12px;padding:0 10px;}}"
                f"QPushButton:checked{{color:{t['ink']};font-weight:600;}}"
            )
            self._group.addButton(b, i)
            self._lay.addWidget(b, 1)
            self._buttons.append(b)
        self._buttons[0].setChecked(True)
        self._indicator = QRectF()
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self._group.idClicked.connect(self._on_click)

    def current(self) -> int:
        return self._group.checkedId()

    def set_current(self, idx: int) -> None:
        if 0 <= idx < len(self._buttons):
            self._buttons[idx].setChecked(True)
            self._indicator = self._rect_for(idx)
            self.update()

    def _rect_for(self, idx: int) -> QRectF:
        b = self._buttons[idx]
        return QRectF(b.geometry()).adjusted(-2, 0, 2, 0)

    def _on_click(self, idx: int) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._indicator)
        self._anim.setEndValue(self._rect_for(idx))
        self._anim.start()
        self.set_current(idx)
        self.changed.emit(idx)

    def _on_anim(self, v) -> None:
        self._indicator = QRectF(v)
        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(self._bg)
        p.drawRoundedRect(QRectF(self.rect()), 8, 8)
        p.setBrush(self._pill)
        p.drawRoundedRect(self._indicator, 6, 6)
        p.end()
        super().paintEvent(ev)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._indicator = self._rect_for(max(0, self.current()))
        self.update()


class SliderRow(QWidget):
    """Label + live value chip + slider, with a value signal on release."""

    valueChanged = Signal(float)

    def __init__(
        self,
        label: str,
        minimum: float,
        maximum: float,
        value: float,
        step: float = 1.0,
        suffix: str = "",
        decimals: int = 0,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._dec = decimals
        self._suffix = suffix
        self._step = step
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        cap = QLabel(label)
        cap.setObjectName("fieldLabel")
        top.addWidget(cap)
        top.addStretch(1)
        self._chip = QLabel()
        self._chip.setObjectName("valueChip")
        top.addWidget(self._chip)
        lay.addLayout(top)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(int(round((maximum - minimum) / step)) or 1)
        self._slider.setValue(int(round((value - minimum) / step)))
        self._slider.setFixedHeight(18)
        self._slider.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self._slider)

        self._min = minimum
        self._update_chip()
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(260)
        self._debounce.timeout.connect(lambda: self.valueChanged.emit(self.value()))
        self._slider.valueChanged.connect(self._on_move)
        self._slider.sliderReleased.connect(lambda: self.valueChanged.emit(self.value()))

    def _on_move(self, _v: int) -> None:
        self._update_chip()
        self._debounce.start()

    def _update_chip(self) -> None:
        v = self.value()
        txt = f"{v:.{self._dec}f}{self._suffix}"
        self._chip.setText(txt)

    def value(self) -> float:
        return self._min + self._slider.value() * self._step

    def set_value(self, v: float) -> None:
        self._slider.setValue(int(round((v - self._min) / self._step)))


class DropZone(QWidget):
    """Dashed drop target. Accepts real drops and emits the file list."""

    filesDropped = Signal(list)

    def __init__(self, parent: QWidget | None = None, height: int = 108):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(height)
        self._hover = False
        t = theme.theme()
        self._border = QColor(t["border_strong"])
        self._border_hot = QColor(t["accent"])
        self._ink2 = QColor(t["ink2"])
        self._ink3 = QColor(t["ink3"])
        self._soft = QColor(t["accent_soft"])

    def dragEnterEvent(self, ev) -> None:
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()
            self._hover = True
            self.update()

    def dragLeaveEvent(self, ev) -> None:
        self._hover = False
        self.update()

    def dropEvent(self, ev) -> None:
        self._hover = False
        self.update()
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
        ev.acceptProposedAction()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(self._soft)
            p.drawRoundedRect(r, 10, 10)
        pen = QPen(self._border_hot if self._hover else self._border)
        pen.setWidthF(1.2)
        pen.setStyle(Qt.CustomDashLine)
        pen.setDashPattern([4, 3])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 10, 10)

        tint = self._border_hot.name() if self._hover else self._ink2.name()
        compact = self.height() < 88
        if compact:
            ic = icons.pixmap("upload", tint, 18)
            p.drawPixmap(16, int(r.center().y() - 9), ic)
            f = QFont(self.font())
            f.setPointSizeF(9.4)
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            p.setPen(self._ink2)
            p.drawText(QRectF(44, r.top(), r.width() - 54, r.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, "拖文件到这里，自动分配")
        else:
            ic = icons.pixmap("upload", tint, 22)
            p.drawPixmap(int(r.center().x() - 11), int(r.top() + 20), ic)
            f = QFont(self.font())
            f.setPointSizeF(9.6)
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            p.setPen(self._ink2)
            p.drawText(QRectF(r.left(), r.top() + 48, r.width(), 20), Qt.AlignHCenter, "把文件拖到这里")
            f2 = QFont(self.font())
            f2.setPointSizeF(8.6)
            p.setFont(f2)
            p.setPen(self._ink3)
            p.drawText(QRectF(r.left(), r.top() + 68, r.width(), 20), Qt.AlignHCenter,
                       ".gff  .len  block_information .csv")
        p.end()


class FileRow(QWidget):
    """A loaded-file chip: icon, name, meta, remove button."""

    removed = Signal()

    def __init__(self, name: str, meta: str, parent: QWidget | None = None):
        super().__init__(parent)
        t = theme.theme()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 6, 6)
        lay.setSpacing(8)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("file", t["ink3"], 16))
        lay.addWidget(ic)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        n = QLabel(name)
        n.setStyleSheet(f"font-size:12px;color:{t['ink']};")
        n.setMaximumWidth(190)
        n.setToolTip(name)
        m = QLabel(meta)
        m.setObjectName("hint")
        col.addWidget(n)
        col.addWidget(m)
        lay.addLayout(col, 1)
        btn = QToolButton()
        btn.setObjectName("ghostIcon")
        btn.setIcon(icons.icon("x", t["ink3"], 14))
        btn.setFixedSize(22, 22)
        btn.clicked.connect(self.removed.emit)
        lay.addWidget(btn)
        self.setStyleSheet(
            f"FileRow{{background:transparent;border-radius:8px;}}"
            f"FileRow:hover{{background:{t['hover']};}}"
        )


class Check(QAbstractButton):
    """Checkbox with a hand-painted box so the tick is consistent everywhere."""

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(22)
        self._hover = False
        t = theme.theme()
        self._border = QColor(t["border_strong"])
        self._accent = QColor(t["accent"])
        self._ink = QColor(t["ink2"])
        self._ink_on = QColor(t["ink"])
        f = QFont(self.font())
        f.setPointSizeF(8.8)
        self.setFont(f)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self.text()) + 26, 22)

    def enterEvent(self, ev) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, ev) -> None:
        self._hover = False
        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        box = QRectF(0.5, (self.height() - 15) / 2, 15, 15)
        if self.isChecked():
            p.setPen(Qt.NoPen)
            p.setBrush(self._accent)
            p.drawRoundedRect(box, 4, 4)
            pen = QPen(QColor("white"))
            pen.setWidthF(1.7)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            from PySide6.QtCore import QPointF as _P

            p.drawLine(_P(box.left() + 3.6, box.top() + 7.7), _P(box.left() + 6.4, box.top() + 10.5))
            p.drawLine(_P(box.left() + 6.4, box.top() + 10.5), _P(box.left() + 11.4, box.top() + 4.6))
        else:
            pen = QPen(self._accent if self._hover else self._border)
            pen.setWidthF(1.2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box, 4, 4)
        p.setPen(self._ink_on if self.isChecked() else self._ink)
        p.setFont(self.font())
        p.drawText(QRectF(23, 0, self.width() - 23, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()


class ProgressStrip(QWidget):
    """3px indeterminate progress line."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(3)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        t = theme.theme()
        self._track = QColor(t["track"])
        self._accent = QColor(t["accent"])
        self._running = False

    def start(self) -> None:
        self._running = True
        self._phase = 0.0
        self._timer.start()
        self.show()

    def stop(self) -> None:
        self._running = False
        self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.012) % 1.0
        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(self._track)
        p.drawRect(self.rect())
        if self._running:
            w = self.width()
            seg = max(80.0, w * 0.28)
            x = (w + seg) * self._phase - seg
            p.setBrush(self._accent)
            p.drawRoundedRect(QRectF(x, 0, seg, 3), 1.5, 1.5)
        p.end()


class ThemeToggle(QToolButton):
    toggled_theme = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ghostIcon")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(30, 28)
        self.setToolTip("切换深浅色")
        self._mode = "light"
        self._refresh()
        self.clicked.connect(self._flip)

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._refresh()

    def _refresh(self) -> None:
        t = theme.theme(self._mode)
        self.setIcon(icons.icon("moon" if self._mode == "light" else "sun", t["ink2"], 17))

    def _flip(self) -> None:
        self._mode = "dark" if self._mode == "light" else "light"
        self._refresh()
        self.toggled_theme.emit(self._mode)


class ElidedLabel(QLabel):
    """QLabel that shortens the text with an ellipsis instead of clipping it."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        self._full = text
        self.setToolTip(text)
        super().setText(text)
        self._elide()

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._elide()

    def _elide(self) -> None:
        fm = self.fontMetrics()
        super().setText(fm.elidedText(self._full, Qt.ElideMiddle, max(20, self.width())))


class SlotRow(QWidget):
    """One required input file: name, status and a pick button."""

    picked = Signal()

    def __init__(self, title: str, hint: str, required: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self._required = required
        self._path: Path | None = None
        self._hover = False
        t = theme.theme()
        self._ink = QColor(t["ink"])
        self._ink3 = QColor(t["ink3"])
        self._accent = QColor(t["accent"])
        self._border = QColor(t["border_strong"])
        self._bg_hover = QColor(t["hover"])
        self.setFixedHeight(40)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 8, 0)
        lay.setSpacing(10)

        self._dot = _Dot(t)
        lay.addWidget(self._dot, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        top = QLabel(title)
        top.setStyleSheet(f"font-size:12px;color:{t['ink']};background:transparent;")
        self._sub = ElidedLabel(hint)
        self._sub.setStyleSheet(f"font-size:11px;color:{t['ink3']};background:transparent;")
        col.addWidget(top)
        col.addWidget(self._sub)
        self._detail = ElidedLabel("")
        self._detail.setStyleSheet(f"font-size:10.5px;color:{t['ink3']};background:transparent;")
        self._detail.hide()
        col.addWidget(self._detail)
        lay.addLayout(col, 1)

        self._btn = QPushButton("选择")
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setFixedHeight(26)
        self._btn.setStyleSheet(
            "QPushButton{background:transparent;border:1px solid %s;border-radius:7px;"
            "color:%s;font-size:11px;padding:0 10px;}"
            "QPushButton:hover{background:%s;color:%s;}" % (t["border_strong"], t["ink2"], t["hover"], t["ink"])
        )
        self._btn.clicked.connect(self.picked.emit)
        lay.addWidget(self._btn, 0, Qt.AlignVCenter)

        self._hint = hint

    def path(self) -> Path | None:
        return self._path

    def set_path(self, path: Path | None) -> None:
        self._path = path
        if path is None:
            self._sub.setText(self._hint)
            self._sub.setStyleSheet(f"font-size:11px;color:{theme.theme()['ink3']};background:transparent;")
            self._btn.setText("选择")
            self.set_detail("")
        else:
            self._sub.setText(path.name)
            self._sub.setStyleSheet(f"font-size:11px;color:{theme.theme()['ink2']};background:transparent;")
            self._btn.setText("更换")
        self._dot.set_filled(path is not None)
        self.update()

    def set_detail(self, text: str, level: str = "ok") -> None:
        """Second line under the filename: parse result or the reason it failed."""
        t = theme.theme()
        if not text:
            self._detail.hide()
            self.setFixedHeight(40)
            return
        colour = {"ok": t["accent"], "warn": "#B07A2F", "err": t["danger"]}.get(level, t["ink3"])
        self._detail.setStyleSheet(f"font-size:10.5px;color:{colour};background:transparent;")
        self._detail.setText(text)
        self._detail.show()
        self.setFixedHeight(58)
        self._dot.set_filled(level != "err")

    def enterEvent(self, ev) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, ev) -> None:
        self._hover = False
        self.update()

    def paintEvent(self, ev) -> None:
        if self._hover:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(Qt.NoPen)
            p.setBrush(self._bg_hover)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0, 2, 0, -2), 8, 8)
            p.end()


class _Dot(QWidget):
    def __init__(self, t: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._filled = False
        self._on = QColor(t["accent"])
        self._off = QColor(t["border_strong"])

    def set_filled(self, value: bool) -> None:
        self._filled = value
        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        if self._filled:
            p.setPen(Qt.NoPen)
            p.setBrush(self._on)
            p.drawEllipse(QRectF(0, 0, 14, 14))
            pen = QPen(QColor("white"))
            pen.setWidthF(1.6)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(4.0, 7.2), QPointF(6.2, 9.5))
            p.drawLine(QPointF(6.2, 9.5), QPointF(10.0, 4.8))
        else:
            pen = QPen(self._off)
            pen.setWidthF(1.5)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(0.8, 0.8, 12.4, 12.4))
        p.end()
