"""Results gallery: the WGDI figures plus the Circos export, with the file list."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..wgdi.project import Project
from . import icons, theme

FIGURES = [
    ("点阵图", "{stem}.dot.1.png"),
    ("Ks 点阵图", "{stem}.ks.dotplot.png"),
    ("Ks 分布", "{stem}.ks_median_distribution.png"),
    ("Circos", "{stem}.png"),
]
EXTRAS = [
    ("块信息", "{stem}_block_information.csv"),
    ("共线性", "{stem}.collinearity.txt"),
    ("Ks 结果", "{stem}.ks"),
    ("blastp 结果", "{stem}.blastp.txt"),
    ("Circos PDF", "{stem}.pdf"),
    ("Circos SVG", "{stem}.svg"),
    ("Circos PNG", "{stem}.png"),
]


class _Thumb(QFrame):
    """One preview tile: image above, caption below."""

    def __init__(self, title: str, path: Path, t: dict, parent=None):
        super().__init__(parent)
        self.path = path
        self.setObjectName("tile")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        image = QLabel()
        image.setAlignment(Qt.AlignCenter)
        image.setFixedHeight(190)
        image.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        if path.suffix.lower() == ".pdf":
            image.setText("PDF")
            image.setStyleSheet(f"font-size:22px;color:{t['ink3']};")
        else:
            pix = QPixmap(str(path))
            if pix.isNull():
                image.setText("无法预览")
                image.setStyleSheet(f"font-size:11px;color:{t['ink3']};")
            else:
                image.setPixmap(pix.scaled(300, 186, Qt.KeepAspectRatio,
                                           Qt.SmoothTransformation))
        lay.addWidget(image)

        caption = QLabel(title)
        caption.setStyleSheet(f"font-size:12px;color:{t['ink']};font-weight:600;")
        lay.addWidget(caption)
        sub = QLabel(f"{path.stat().st_size / 1024:.0f} KB")
        sub.setStyleSheet(f"font-size:10px;color:{t['ink3']};")
        lay.addWidget(sub)

        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, ev) -> None:  # noqa: D102
        open_path(self.path)


def open_path(path: Path) -> None:
    try:
        os.startfile(str(path))  # noqa: S606 - deliberate: hand it to the shell
    except OSError:
        subprocess.Popen(["explorer", str(path)])


class ResultsDialog(QDialog):
    def __init__(self, root: Path, mode: str = "light", parent=None):
        super().__init__(parent)
        self.project = Project.load(Path(root))
        self.setWindowTitle(f"结果 · {self.project.name}")
        self.resize(760, 640)
        t = theme.theme(mode)
        stem = self.project.stem

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        title = QLabel(f"{self.project.name}")
        title.setStyleSheet(f"font-size:17px;font-weight:700;color:{t['ink']};")
        lay.addWidget(title)
        genes = self.project.steps.get("prep", {}).get("detail", "")
        sub = QLabel(f"对比 {stem} · 项目目录 {self.project.root}")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"font-size:11px;color:{t['ink3']};")
        lay.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        grid.setAlignment(Qt.AlignTop)

        found = 0
        for label, pattern in FIGURES:
            key = {"点阵图": "dotplot", "Ks 点阵图": "blockks", "Ks 分布": "kspeaks", "Circos": "circos"}[label]
            if not self.project.is_done(key):
                continue
            folder = self.project.results if label == "Circos" else self.project.work
            path = folder / pattern.format(stem=stem)
            if label == "Circos" and not path.exists():
                path = next((f for f in self.project.outputs("circos") if f.exists()), path)
            if not path.exists():
                continue
            grid.addWidget(_Thumb(label, path, t), found // 2, found % 2)
            found += 1
        if not found:
            empty = QLabel("还没有结果图，先跑一次全流程分析")
            empty.setStyleSheet(f"font-size:12px;color:{t['ink3']};padding:24px;")
            grid.addWidget(empty, 0, 0)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)

        files = QListWidget()
        files.setFixedHeight(110)
        for label, pattern in EXTRAS:
            key = {"块信息": "blockinfo", "共线性": "collinearity", "Ks 结果": "ks", "blastp 结果": "blast"}.get(label, "circos")
            if not self.project.is_done(key):
                continue
            path = self.project.work / pattern.format(stem=stem)
            if not path.exists():
                path = self.project.results / pattern.format(stem=stem)
            if not path.exists():
                continue
            item = QListWidgetItem(f"{label}    {path.name}    {path.stat().st_size / 1024:.0f} KB")
            item.setData(Qt.UserRole, str(path))
            files.addItem(item)
        files.itemDoubleClicked.connect(
            lambda item: open_path(Path(item.data(Qt.UserRole))))
        files.setToolTip("双击用系统程序打开")
        lay.addWidget(files)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        folder = QPushButton("打开结果文件夹")
        folder.setIcon(icons.icon("file", t["ink2"], 15))
        folder.setFixedHeight(34)
        folder.setCursor(Qt.PointingHandCursor)
        folder.clicked.connect(lambda: open_path(self.project.results))
        close = QPushButton("关闭")
        close.setObjectName("primary")
        close.setFixedHeight(34)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.accept)
        buttons.addWidget(folder)
        buttons.addStretch(1)
        buttons.addWidget(close)
        lay.addLayout(buttons)

        self.setStyleSheet(f"""
            QDialog {{ background: {t['bg']}; }}
            QFrame#tile {{ background: {t['card']}; border: 1px solid {t['border']};
                          border-radius: 10px; }}
            QListWidget {{ background: {t['card']}; border: 1px solid {t['border']};
                          border-radius: 8px; font-size: 11px; color: {t['ink2']}; }}
            QPushButton {{ background: {t['card']}; border: 1px solid {t['border']};
                          border-radius: 8px; padding: 0 14px; color: {t['ink']};
                          font-size: 12px; }}
            QPushButton#primary {{ background: {t['accent']}; color: white; border: none;
                          font-weight: 600; }}
        """)
