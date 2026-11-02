"""Rewrite a FASTA at a fixed line width.

Lilium genomes are shipped as one sequence per line, which makes `.fai`
``linebases`` exceed 2**31 and breaks every 32-bit reader. Re-wrapping to 60
columns before indexing removes that class of bug at the source.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..core.issues import Issue, WgdiError
from .fai import DEFAULT_WIDTH, _iter_lines

Progress = Callable[[int, int], None] | None


def detect_widths(path: Path, max_lines: int = 400) -> set[int]:
    """Line widths seen in the first few sequence lines of each record."""
    widths: set[int] = set()
    seen_records = 0
    for _pos, line, _eol in _iter_lines(path, chunk_size=1 << 20):
        if not line:
            continue
        if line[:1] == b">":
            seen_records += 1
            if seen_records > 8:
                break
            continue
        widths.add(len(line))
        if len(widths) > 4 or max_lines <= 0:
            break
        max_lines -= 1
    return widths


def rewrap(src: Path, dst: Path, width: int = DEFAULT_WIDTH,
           progress: Progress = None) -> tuple[int, int, list[Issue]]:
    """Stream `src` into `dst` with `width` bases per line. Returns (records, bases)."""
    src, dst = Path(src), Path(dst)
    if not src.exists():
        raise WgdiError(f"找不到文件：{src}")
    if src.resolve() == dst.resolve():
        raise WgdiError("重排的输出不能覆盖原文件")
    total = src.stat().st_size
    issues: list[Issue] = []
    records = 0
    bases = 0
    last_report = 0
    dst.parent.mkdir(parents=True, exist_ok=True)

    with dst.open("wb") as out:
        buf = bytearray()

        def flush(full: bool = True) -> None:
            nonlocal buf
            while len(buf) >= width or (full and buf):
                take = buf[:width]
                out.write(take)
                out.write(b"\n")
                del buf[:len(take)]

        for pos, line, _eol in _iter_lines(src):
            if progress is not None and pos - last_report > (64 << 20):
                last_report = pos
                progress(pos, total)
            if not line:
                continue
            if line[:1] == b">":
                flush(full=True)
                records += 1
                out.write(line.rstrip())
                out.write(b"\n")
                continue
            bases += len(line)
            buf.extend(line)
            flush(full=False)
        flush(full=True)

    if progress is not None:
        progress(total, total)
    if records == 0:
        raise WgdiError(f"{src.name} 里没有读到序列")
    return records, bases, issues
