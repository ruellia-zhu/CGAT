"""The preview pane the wizard shows on the right for the current step."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..wgdi.preview import Preview
from . import theme


class PreviewPane(QWidget):
    """Stats + an optional table or image, or a friendly empty state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        t = theme.theme()
        self._t = t
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.stats = QGridLayout()
        self.stats.setHorizontalSpacing(18)
        self.stats.setVerticalSpacing(4)
        stats_holder = QWidget()
        stats_holder.setLayout(self.stats)
        lay.addWidget(stats_holder)

        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(
            "font-size:11px;color:#b26a00;background:#fff6e5;border:1px solid #f0d9a8;"
            "border-radius:8px;padding:6px 10px;")
        self.warn.hide()
        lay.addWidget(self.warn)

        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)

        # page 0: empty hint
        empty = QWidget()
        el = QVBoxLayout(empty)
        el.setAlignment(Qt.AlignCenter)
        self.hint = QLabel("")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"font-size:12px;color:{t['ink3']};")
        el.addWidget(self.hint)
        self.stack.addWidget(empty)

        # page 1: table
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setShowGrid(False)
        self.table.setStyleSheet(
            f"QTableWidget{{background:{t['card']};border:1px solid {t['border']};"
            f"border-radius:10px;color:{t['ink2']};font-size:11px;"
            f"gridline-color:transparent;}}"
            f"QHeaderView::section{{background:{t['card']};color:{t['ink3']};"
            f"border:none;border-bottom:1px solid {t['border']};padding:6px 8px;"
            f"font-size:11px;font-weight:600;}}"
            f"QTableWidget::item{{padding:4px 8px;"
            f"border-bottom:1px solid {t['border']};}}")
        self.stack.addWidget(self.table)

        # page 2: image
        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setFrameShape(QFrame.NoFrame)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet(f"background:{t['card']};border-radius:10px;")
        self.image_scroll.setWidget(self.image_label)
        self.stack.addWidget(self.image_scroll)

        # page 3: text
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.text.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.text.setStyleSheet(f"font-size:11px;color:{t['ink2']};")
        text_holder = QWidget()
        tl = QVBoxLayout(text_holder)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(self.text)
        tl.addStretch(1)
        self.stack.addWidget(text_holder)

    # --- api ----------------------------------------------------------
    def clear(self) -> None:
        self._clear_stats()
        self.warn.hide()
        self.hint.setText("")
        self.stack.setCurrentIndex(0)

    def show_preview(self, preview: Preview) -> None:
        self._clear_stats()
        row = 0
        for label, value in preview.stats:
            key = QLabel(label)
            key.setStyleSheet(f"font-size:10px;color:{self._t['ink3']};")
            val = QLabel(value)
            val.setStyleSheet(f"font-size:13px;color:{self._t['ink']};font-weight:600;")
            self.stats.addWidget(key, 0, row)
            self.stats.addWidget(val, 1, row)
            row += 1

        if preview.warn:
            self.warn.setText("⚠ " + preview.warn)
            self.warn.show()
        else:
            self.warn.hide()

        if preview.image is not None and preview.image.exists():
            pix = QPixmap(str(preview.image))
            if not pix.isNull():
                limit_w, limit_h = 640, 380
                scaled = pix.scaled(limit_w, limit_h, Qt.KeepAspectRatio,
                                    Qt.SmoothTransformation)
                self.image_label.setPixmap(scaled)
                self.stack.setCurrentIndex(2)
                if preview.text:
                    self.hint.setText(preview.text)
                return

        if preview.rows:
            self._fill_table(preview)
            self.stack.setCurrentIndex(1)
            return

        if preview.text:
            self.text.setText(preview.text)
            self.stack.setCurrentIndex(3)
            return

        self.hint.setText(preview.hint or "本步还没有可预览的结果")
        self.stack.setCurrentIndex(0)

    def _fill_table(self, preview: Preview) -> None:
        self.table.clear()
        self.table.setColumnCount(len(preview.headers))
        self.table.setHorizontalHeaderLabels(preview.headers)
        self.table.setRowCount(len(preview.rows))
        for r, row in enumerate(preview.rows):
            for c, value in enumerate(row[:len(preview.headers)]):
                item = QTableWidgetItem(str(value))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()

    def _clear_stats(self) -> None:
        while self.stats.count():
            item = self.stats.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
