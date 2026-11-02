"""Render the results dialog against a finished project. Dev-only."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.ui import theme
from app.ui.results import ResultsDialog
from app.wgdi.pipeline import Listener, Pipeline
from app.wgdi.project import Project
from app.wgdi.runtime import discover

root = Path(sys.argv[1])
app = QApplication(sys.argv[:1])
theme.apply(app, "light")

project = Project.load(root)
if "--make-figures" in sys.argv:
    pipe = Pipeline(project, Listener(), discover())
    for step in ("dotplot",):
        try:
            pipe.run(only=[step])
            print("ran", step)
        except Exception as exc:  # noqa: BLE001
            print("skip", step, exc)

dialog = ResultsDialog(root, "light")
dialog.show()
QTest.qWait(400)
app.processEvents()
out = ROOT / "build" / "ui_results.png"
dialog.grab().save(str(out))
print("saved", out, dialog.width(), "x", dialog.height())
