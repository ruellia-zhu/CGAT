"""Entry point: ``python -m app`` (from the circos_studio folder)."""
from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .ui import theme
from .ui.main_window import MainWindow


def _selftest() -> int:
    """Render a tiny synthetic figure. Proves a frozen build works end to end."""
    import tempfile
    from pathlib import Path

    from PIL import Image

    from .core.model import Block, Chromosome, Dataset, Gene, Genome
    from .core.style import default as default_style
    from .render import export as export_mod
    from .render import figure as figure_mod

    def genome(name: str) -> Genome:
        g = Genome(name=name, label=name,
                   chromosomes=[Chromosome("chr1", 3_000_000), Chromosome("chr2", 2_000_000)])
        order = 1
        for chrom, count in (("chr1", 12), ("chr2", 8)):
            for i in range(count):
                gene = Gene(chrom, f"{name}_{chrom}_{i}", 10_000 + i * 150_000,
                            10_050 + i * 150_000, "+", order)
                g.genes[gene.gene_id] = gene
                g.by_order[(chrom, order)] = gene
                order += 1
        return g

    dataset = Dataset(genome("A"), genome("B"),
                      [Block("1", 1, "chr1", "chr1", tuple(range(1, 9)), tuple(range(1, 9)))],
                      "paired")
    out_dir = Path(tempfile.mkdtemp(prefix="circos_selftest_"))
    fig = figure_mod.build_figure(dataset, default_style())
    paths = export_mod.export_all(fig, out_dir, "selftest", ["pdf", "png"], 150)
    figure_mod.close(fig)

    ok = True
    for path in paths:
        size = path.stat().st_size // 1024 if path.exists() else 0
        good = path.exists() and size > 1
        print(f"  {path.name:<18}{size:>6} KB  {'ok' if good else 'FAIL'}")
        ok = ok and good
    png = next((p for p in paths if p.suffix == ".png"), None)
    if png:
        im = Image.open(png)
        print(f"  png mode={im.mode} size={im.width}x{im.height}")
        ok = ok and im.mode == "RGB"
    print("SELFTEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


def _selftest_ui() -> int:
    """Show the window and check the hit test over its title-bar buttons.

    Runs inside the frozen build too, so the DPI fix for WM_NCHITTEST is
    verified on the shipped binary rather than only from source.
    """
    import ctypes
    from ctypes import wintypes

    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication

    from .ui import theme
    from .ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    theme.apply(app, "light")
    win = MainWindow("light")
    win.show()
    app.processEvents()
    QTimer.singleShot(400, app.quit)
    app.exec()

    hwnd = wintypes.HWND(int(win.winId()))
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    dpr = win.devicePixelRatioF()
    ok = True
    print(f"  window {win.width()}x{win.height()} @ {dpr:.2f}x")
    for name, widget in (("theme", win.title_bar.theme_toggle), ("close", win.title_bar.close_btn)):
        pos = widget.mapTo(win, widget.rect().center())
        x = rect.left + int(round(pos.x() * dpr))
        y = rect.top + int(round(pos.y() * dpr))
        code = int(ctypes.windll.user32.SendMessageW(
            hwnd, 0x0084, 0, (y << 16) | (x & 0xFFFF)))
        print(f"  {name:<6} hit={code} (1 = HTCLIENT)")
        ok = ok and code == 1
    print("SELFTEST-UI", "OK" if ok else "FAILED")
    return 0 if ok else 1


def _check_runtime() -> int:
    """Report the external tools found next to the executable."""
    from . import build_info
    from .paths import data_root
    from .wgdi.runtime import discover

    rt = discover()
    print(f"{build_info.APP_NAME} {build_info.VERSION} ({build_info.BUILD_DATE})")
    print(f"program   {sys.executable}")
    print(f"frozen    {getattr(sys, 'frozen', False)}")
    for key, path in rt.bins.items():
        print(f"  {key:<12}{path}")
    print(f"ks        {'yes' if rt.has_ks else 'no'}")
    print(f"data      {data_root()}")
    for problem in rt.problems:
        print(f"problem   {problem}")
    return 0 if rt.ok else 1


def main(argv: list[str] | None = None) -> int:
    from . import build_info as info

    argv = list(sys.argv if argv is None else argv)
    ap = argparse.ArgumentParser(prog="circos-studio")
    ap.add_argument("--theme", default="light", choices=("light", "dark"))
    ap.add_argument("--screenshot", metavar="PNG", help="save the window to a PNG and exit")
    ap.add_argument("--selftest", action="store_true", help="render a synthetic figure and exit")
    ap.add_argument("--selftest-ui", action="store_true", help="check window hit testing and exit")
    ap.add_argument("--check-runtime", action="store_true", help="print the external tools and exit")
    args, rest = ap.parse_known_args(argv[1:])

    if args.check_runtime:
        return _check_runtime()
    if args.selftest:
        return _selftest()
    if args.selftest_ui:
        return _selftest_ui()

    app = QApplication([argv[0]] + rest)
    app.setApplicationName(info.APP_NAME)
    theme.apply(app, args.theme)

    win = MainWindow(args.theme)
    win.show()
    app._main = win  # type: ignore[attr-defined]

    # The frozen one-file build unpacks for a few seconds; close its splash now.
    try:
        import pyi_splash  # type: ignore[import-not-found]

        pyi_splash.close()
    except Exception:  # noqa: BLE001 - only exists inside the PyInstaller bundle
        pass

    if args.screenshot:
        def _shot() -> None:
            win.grab().save(args.screenshot)
            app.quit()

        QTimer.singleShot(900, _shot)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
