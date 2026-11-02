"""Background rendering so the window never freezes."""
from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..core.style import Style
from ..render import export as export_mod
from ..render import figure as figure_mod


class RenderWorker(QThread):
    """Build a figure and write a PNG; runs off the GUI thread."""

    progress = Signal(str)
    done = Signal(str, dict)
    failed = Signal(str)

    def __init__(self, dataset, style: Style, out_png: Path, dpi: int, subsample: int = 1):
        super().__init__()
        self._dataset = dataset
        self._style = style
        self._out = Path(out_png)
        self._dpi = dpi
        self._subsample = subsample

    def run(self) -> None:  # noqa: D102
        try:
            self.progress.emit("正在计算扇区与连线…")
            fig = figure_mod.build_figure(self._dataset, self._style,
                                          dpi=self._dpi, subsample=self._subsample)
            self.progress.emit("正在渲染…")
            export_mod.export(fig, self._out, "png", self._dpi)
            stats = dict(getattr(fig, "_circos_stats", {}))
            figure_mod.close(fig)
            self.done.emit(str(self._out), stats)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.failed.emit(str(exc))


class ExportWorker(QThread):
    """Render at full resolution and write the requested formats."""

    progress = Signal(str)
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, dataset, style: Style, out_dir: Path, stem: str,
                 formats: list[str], dpi: int):
        super().__init__()
        self._dataset = dataset
        self._style = style
        self._out_dir = Path(out_dir)
        self._stem = stem
        self._formats = formats
        self._dpi = dpi

    def run(self) -> None:  # noqa: D102
        try:
            self.progress.emit(f"正在渲染 {self._dpi} dpi…")
            fig = figure_mod.build_figure(self._dataset, self._style, dpi=self._dpi)
            written = []
            for fmt in self._formats:
                ext = "tiff" if fmt.lower() in ("tif", "tiff") else fmt.lower()
                self.progress.emit(f"正在写入 {ext.upper()}…")
                written.append(str(export_mod.export(
                    fig, self._out_dir / f"{self._stem}.{ext}", fmt, self._dpi)))
            figure_mod.close(fig)
            self.done.emit(written)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.failed.emit(str(exc))
