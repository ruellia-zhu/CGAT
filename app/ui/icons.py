"""Small hand-drawn line icons so the app does not depend on an icon font."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _pen(color: str, width: float = 1.6) -> QPen:
    p = QPen(QColor(color))
    p.setWidthF(width)
    p.setCapStyle(Qt.RoundCap)
    p.setJoinStyle(Qt.RoundJoin)
    return p


def _draw(p: QPainter, name: str, s: float, color: str) -> None:
    p.setPen(_pen(color, max(1.3, s * 0.095)))
    p.setBrush(Qt.NoBrush)
    u = s / 24.0                      # icons are authored on a 24x24 grid

    if name == "minus":
        p.drawLine(QPointF(6 * u, 12 * u), QPointF(18 * u, 12 * u))
    elif name == "square":
        p.drawRoundedRect(QRectF(6 * u, 6 * u, 12 * u, 12 * u), 1.5 * u, 1.5 * u)
    elif name == "x":
        p.drawLine(QPointF(6.5 * u, 6.5 * u), QPointF(17.5 * u, 17.5 * u))
        p.drawLine(QPointF(17.5 * u, 6.5 * u), QPointF(6.5 * u, 17.5 * u))
    elif name == "file":
        path = QPainterPath()
        path.moveTo(7 * u, 3.5 * u)
        path.lineTo(14 * u, 3.5 * u)
        path.lineTo(18 * u, 7.5 * u)
        path.lineTo(18 * u, 20.5 * u)
        path.lineTo(7 * u, 20.5 * u)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(14 * u, 3.5 * u), QPointF(14 * u, 7.5 * u))
        p.drawLine(QPointF(14 * u, 7.5 * u), QPointF(18 * u, 7.5 * u))
    elif name == "upload":
        p.drawLine(QPointF(12 * u, 16 * u), QPointF(12 * u, 5 * u))
        p.drawLine(QPointF(7.5 * u, 9.5 * u), QPointF(12 * u, 5 * u))
        p.drawLine(QPointF(16.5 * u, 9.5 * u), QPointF(12 * u, 5 * u))
        p.drawLine(QPointF(4.5 * u, 15 * u), QPointF(4.5 * u, 19 * u))
        p.drawLine(QPointF(4.5 * u, 19 * u), QPointF(19.5 * u, 19 * u))
        p.drawLine(QPointF(19.5 * u, 19 * u), QPointF(19.5 * u, 15 * u))
    elif name == "download":
        p.drawLine(QPointF(12 * u, 4 * u), QPointF(12 * u, 15 * u))
        p.drawLine(QPointF(7.5 * u, 10.5 * u), QPointF(12 * u, 15 * u))
        p.drawLine(QPointF(16.5 * u, 10.5 * u), QPointF(12 * u, 15 * u))
        p.drawLine(QPointF(4.5 * u, 16 * u), QPointF(4.5 * u, 19.5 * u))
        p.drawLine(QPointF(4.5 * u, 19.5 * u), QPointF(19.5 * u, 19.5 * u))
        p.drawLine(QPointF(19.5 * u, 19.5 * u), QPointF(19.5 * u, 16 * u))
    elif name == "image":
        p.drawRoundedRect(QRectF(4 * u, 5 * u, 16 * u, 14 * u), 2 * u, 2 * u)
        p.drawEllipse(QPointF(9 * u, 10 * u), 1.5 * u, 1.5 * u)
        path = QPainterPath()
        path.moveTo(4.5 * u, 17 * u)
        path.lineTo(10 * u, 12.5 * u)
        path.lineTo(14 * u, 15.5 * u)
        path.lineTo(16.5 * u, 13.5 * u)
        path.lineTo(19.5 * u, 16.5 * u)
        p.drawPath(path)
    elif name == "fit":
        for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            cx = 12 * u + dx * 6.5 * u
            cy = 12 * u + dy * 6.5 * u
            p.drawLine(QPointF(cx, cy), QPointF(cx - dx * 3.5 * u, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy - dy * 3.5 * u))
    elif name == "sun":
        p.drawEllipse(QPointF(12 * u, 12 * u), 4 * u, 4 * u)
        for k in range(8):
            a = k * math.pi / 4
            p.drawLine(QPointF(12 * u + 7 * u * math.cos(a), 12 * u + 7 * u * math.sin(a)),
                       QPointF(12 * u + 9.5 * u * math.cos(a), 12 * u + 9.5 * u * math.sin(a)))
    elif name == "moon":
        path = QPainterPath()
        path.addEllipse(QRectF(6 * u, 4 * u, 14 * u, 16 * u))
        cut = QPainterPath()
        cut.addEllipse(QRectF(9.5 * u, 2.5 * u, 14 * u, 16 * u))
        p.drawPath(path.subtracted(cut))
    elif name == "circle-dot":
        p.drawEllipse(QPointF(12 * u, 12 * u), 8 * u, 8 * u)
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(12 * u, 12 * u), 2.4 * u, 2.4 * u)
        p.setBrush(Qt.NoBrush)
    elif name == "layers":
        for k in range(3):
            y = 5 * u + k * 4.2 * u
            path = QPainterPath()
            path.moveTo(12 * u, y)
            path.lineTo(20 * u, y + 3 * u)
            path.lineTo(12 * u, y + 6 * u)
            path.lineTo(4 * u, y + 3 * u)
            path.closeSubpath()
            p.drawPath(path)
    elif name == "sliders":
        for k, y in enumerate((7, 12, 17)):
            p.drawLine(QPointF(4 * u, y * u), QPointF(20 * u, y * u))
            x = (9, 15, 7)[k] * u
            p.setBrush(QColor(color))
            p.drawEllipse(QPointF(x, y * u), 2 * u, 2 * u)
            p.setBrush(Qt.NoBrush)
    elif name == "check":
        p.drawLine(QPointF(5 * u, 12.5 * u), QPointF(10 * u, 17 * u))
        p.drawLine(QPointF(10 * u, 17 * u), QPointF(19 * u, 7 * u))
    elif name == "chevron-down":
        p.drawLine(QPointF(8 * u, 10 * u), QPointF(12 * u, 14 * u))
        p.drawLine(QPointF(12 * u, 14 * u), QPointF(16 * u, 10 * u))
    else:
        p.drawEllipse(QPointF(12 * u, 12 * u), 6 * u, 6 * u)


def pixmap(name: str, color: str, size: int = 18, dpr: float = 2.0) -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    # setDevicePixelRatio already makes the painter work in logical units,
    # so draw on the `size` grid, not on the device pixel grid.
    _draw(p, name, float(size), color)
    p.end()
    return pm


def icon(name: str, color: str, size: int = 18) -> QIcon:
    return QIcon(pixmap(name, color, size))
