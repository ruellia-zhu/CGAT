# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for 比较基因组分析.

Produces a one-folder build:

    dist/比较基因组分析/
        比较基因组分析.exe
        _internal/            Python + PySide6 + matplotlib
        runtime/              WGDI venv   (copied by build.cmd)
        bin/                  blastp/muscle/seqkit/perl/pal2nal/yn00 (copied by build.cmd)

Build:  build\\build.cmd
"""

# Keep unrelated host DLLs out of the distribution.
import os
import sys
from pathlib import Path
os.environ["PATH"] = os.pathsep.join([str(Path(sys.base_prefix)), str(Path(sys.base_prefix) / "DLLs"),
                                    os.path.join(os.environ["SystemRoot"], "System32"), os.environ["SystemRoot"]])

a = Analysis(
    ["..\\main.py"],
    pathex=[".."],
    binaries=[],
    datas=[("..\\app\\resources\\splash.png", "app\\resources"),
           ("..\\app\\wgdi\\runner.py", "app\\wgdi"),
           ("..\\app\\wgdi\\ks_inputs.py", "app\\wgdi")],
    hiddenimports=[
        "matplotlib.backends.backend_agg",
        "matplotlib.backends.backend_pdf",
        "matplotlib.backends.backend_svg",
        "PIL._tkinter_finder",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "IPython", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="比较基因组分析",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    splash="..\\app\\resources\\splash.png",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="比较基因组分析",
)
