"""The About dialog."""
from __future__ import annotations

import platform
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import build_info as info
from . import icons, theme


def _row(label: str, value: str, t: dict) -> QWidget:
    widget = QWidget()
    lay = QHBoxLayout(widget)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    key = QLabel(label)
    key.setFixedWidth(96)
    key.setStyleSheet(f"font-size:12px;color:{t['ink3']};")
    val = QLabel(value)
    val.setWordWrap(True)
    val.setStyleSheet(f"font-size:12px;color:{t['ink']};")
    lay.addWidget(key, 0, Qt.AlignTop)
    lay.addWidget(val, 1)
    return widget


def _dep_versions() -> str:
    parts = [f"Python {platform.python_version()}"]
    try:
        from PySide6 import __version__ as pyside  # type: ignore

        parts.append(f"PySide6 {pyside}")
    except Exception:  # noqa: BLE001
        pass
    for mod, label in (("matplotlib", "matplotlib"), ("numpy", "numpy")):
        try:
            module = __import__(mod)
            parts.append(f"{label} {module.__version__}")
        except Exception:  # noqa: BLE001
            pass
    try:
        from ..wgdi import runtime

        parts.extend(runtime.describe_versions())
    except Exception:  # noqa: BLE001
        parts.append("WGDI 运行时未安装")
    return " · ".join(parts)


class AboutDialog(QDialog):
    def __init__(self, parent=None, mode: str = "light"):
        super().__init__(parent)
        self.setWindowTitle(f"关于 {info.APP_NAME}")
        self.setModal(True)
        self.setFixedWidth(460)
        t = theme.theme(mode)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(12)
        mark = QLabel()
        mark.setPixmap(icons.pixmap("circle-dot", t["accent"], 34))
        head.addWidget(mark, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        name = QLabel(info.APP_NAME)
        name.setStyleSheet(f"font-size:18px;font-weight:700;color:{t['ink']};")
        sub = QLabel(info.APP_NAME_EN)
        sub.setStyleSheet(f"font-size:11px;color:{t['ink3']};")
        col.addWidget(name)
        col.addWidget(sub)
        head.addLayout(col, 1)
        lay.addLayout(head)

        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{t['border']};")
        lay.addWidget(line)

        lay.addWidget(_row("版本号", info.VERSION, t))
        lay.addWidget(_row("更新时间", info.BUILD_DATE, t))
        lay.addWidget(_row("开发者", info.DEVELOPER, t))
        lay.addWidget(_row("运行环境", _dep_versions(), t))
        lay.addWidget(_row("引用", info.CITATION, t))

        note = QLabel("内置 WGDI 全流程：预处理 → blastp/diamond → 共线性 → Ks → Circos")
        note.setWordWrap(True)
        note.setStyleSheet(f"font-size:11px;color:{t['ink3']};padding-top:4px;")
        lay.addWidget(note)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("关闭")
        close.setObjectName("primary")
        close.setFixedHeight(32)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        lay.addLayout(buttons)

        self.setStyleSheet(f"QDialog{{background:{t['card']};}}")


def show(parent, mode: str) -> None:
    AboutDialog(parent, mode).exec()
