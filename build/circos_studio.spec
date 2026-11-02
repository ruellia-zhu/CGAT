# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for Circos Studio.

Build:  ..\circos_dev\.venv\Scripts\pyinstaller.exe build\circos_studio.spec
"""

a = Analysis(
    ["..\\main.py"],
    pathex=[".."],
    binaries=[],
    datas=[("..\\app\\resources\\splash.png", "app\\resources")],
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
    a.binaries,
    a.datas,
    [],
    name="CircosStudio",
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
