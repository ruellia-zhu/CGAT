"""Portable fingerprints and preservation of superseded generated files."""
from __future__ import annotations

import hashlib
import json
import shutil
import time
import uuid
from pathlib import Path


def file_stamp(path: Path, *, content: bool = False) -> dict:
    path = Path(path)
    info = {"path": str(path.resolve())}
    if not path.is_file():
        return {**info, "missing": True}
    stat = path.stat()
    info.update(size=stat.st_size, mtime_ns=stat.st_mtime_ns)
    if content:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        info["sha256"] = digest.hexdigest()
    return info


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def preserve(path: Path, root: Path) -> None:
    """Move generated output into history; never delete user/project files."""
    if not path.exists():
        return
    relative = path.resolve().relative_to(root.resolve())
    folder = root / "history" / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    target = folder / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(target))
