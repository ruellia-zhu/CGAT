"""Locate and validate the WGDI runtime and its companion binaries.

Layout it expects, next to the executable (one-dir build)::

    runtime/python.exe      venv with wgdi 0.75 + pandas/numpy/scipy/biopython
    bin/blastp.exe  bin/makeblastdb.exe  bin/muscle.exe  bin/seqkit.exe
    bin/diamond.exe         optional

In a source checkout the same folders sit next to `app/`. A user-configured
override (a conda environment, say) wins over both.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

BINARIES = {
    "blastp": "blastp.exe",
    "makeblastdb": "makeblastdb.exe",
    "muscle": "muscle.exe",
    "seqkit": "seqkit.exe",
    "diamond": "diamond.exe",
    "mafft": "mafft.exe",
}
REQUIRED = ("blastp", "makeblastdb", "muscle")
# Ks needs Perl + pal2nal + PAML's yn00; without them the ks steps are skipped
KS_TOOLS = ("perl", "pal2nal", "yn00")
_VERSION_CACHE: dict[str, str] = {}
_MAFFT_CACHE: dict[tuple[str, int, int], bool] = {}


def usable_mafft(exe: Path) -> bool:
    stat = exe.stat()
    key = (str(exe), stat.st_size, stat.st_mtime_ns)
    if key not in _MAFFT_CACHE:
        output = _run([str(exe), "--version"], timeout=15)
        _MAFFT_CACHE[key] = bool(re.search(r"(?im)^\s*(?:mafft\s+)?v?\d+\.\d+(?:\.\d+)?(?:\s|$)", output))
    return _MAFFT_CACHE[key]


def app_root() -> Path:
    """Folder that should contain `runtime/` and `bin/`."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _run(cmd: list[str], timeout: int = 20) -> str:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (done.stdout or "") + (done.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return ""


def _version_of(exe: Path, flag: str) -> str:
    key = f"{exe}|{flag}"
    if key in _VERSION_CACHE:
        return _VERSION_CACHE[key]
    text = _run([str(exe), flag])
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    _VERSION_CACHE[key] = first[:80]
    return _VERSION_CACHE[key]


@dataclass
class Runtime:
    root: Path | None = None
    python: Path | None = None
    wgdi: Path | None = None
    bins: dict[str, Path] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def has_ks(self) -> bool:
        """True when the Ks toolchain (perl + pal2nal + yn00) is available."""
        return all(t in self.bins for t in KS_TOOLS)

    def missing(self) -> list[str]:
        return list(self.problems)

    def env(self) -> dict[str, str]:
        """Environment for child processes: our bin/ first on PATH."""
        env = dict(os.environ)
        # wgdi draws with matplotlib.pyplot; without a fixed backend it tries a
        # GUI one and dies in a background process.
        env["MPLBACKEND"] = "Agg"
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
            env[key] = "1"  # Avoid BLAS threads multiplying WGDI worker counts.
        extra = [str(p.parent) for p in self.bins.values()]
        if extra:
            env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
        return env


def discover(override: str | None = None) -> Runtime:
    """Find a usable runtime; `problems` explains whatever is missing."""
    root = app_root()
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    candidates += [root / "runtime", Path(__file__).resolve().parents[2] / "runtime"]

    rt = Runtime()
    for cand in candidates:
        python = cand / ("python.exe" if os.name == "nt" else "bin/python")
        if not python.exists():
            python = cand / "Scripts" / "python.exe"
        if not python.exists():
            continue
        rt.root, rt.python = cand, python
        for name in ("wgdi.exe", "wgdi"):
            exe = cand / "Scripts" / name
            if exe.exists():
                rt.wgdi = exe
                break
        if rt.wgdi is None:
            rt.problems.append(f"{cand} 里没有 wgdi 命令")
        break
    else:
        rt.problems.append("找不到 WGDI 运行时（runtime/python.exe）")

    for key, filename in BINARIES.items():
        for base in (root / "bin", Path(__file__).resolve().parents[2] / "bin"):
            exe = base / filename
            if exe.exists():
                rt.bins[key] = exe
                break
        else:
            found = shutil.which(filename.replace(".exe", ""))
            if found:
                rt.bins[key] = Path(found)

    if "mafft" in rt.bins and not usable_mafft(rt.bins["mafft"]):
        rt.bins.pop("mafft")

    for key in REQUIRED:
        if key not in rt.bins:
            rt.problems.append(f"缺少 {BINARIES[key]}（{key}）")
    # Ks toolchain is optional. Portable Perl lives in its own subtree, so try
    # that first, then a flat bin/perl.exe, then whatever is on PATH.
    for base in (root / "bin", Path(__file__).resolve().parents[2] / "bin"):
        for rel in ("perl/bin/perl.exe", "perl.exe"):
            exe = base / rel
            if exe.exists():
                rt.bins.setdefault("perl", exe)
                break
        for rel in ("yn00.exe", "yn00"):
            exe = base / rel
            if exe.exists():
                rt.bins.setdefault("yn00", exe)
                break
        script = base / "pal2nal.pl"
        if script.exists():
            rt.bins.setdefault("pal2nal", script)
        if "perl" not in rt.bins:
            found = shutil.which("perl")
            if found:
                rt.bins["perl"] = Path(found)
        if "yn00" not in rt.bins:
            found = shutil.which("yn00")
            if found:
                rt.bins["yn00"] = Path(found)
    return rt


def describe_versions() -> list[str]:
    """Short version strings for the About dialog; empty when not installed."""
    out: list[str] = []
    rt = discover()
    if rt.python is not None:
        text = _run([str(rt.python), "-c",
                     "import importlib.metadata as m;print(m.version('wgdi'))"])
        version = text.strip().splitlines()[-1] if text.strip() else "?"
        out.append(f"WGDI {version}")
    for key in ("blastp", "muscle", "seqkit"):
        exe = rt.bins.get(key)
        if exe is None:
            continue
        flag = "-version" if key in ("blastp", "muscle") else "version"
        label = _version_of(exe, flag)
        if label:
            out.append(label.split(",")[0][:40] if key == "blastp" else label[:24])
    return out


def check_tools() -> list[str]:
    """Human-readable list of what is ready and what is not."""
    rt = discover()
    lines = []
    if rt.python:
        lines.append(f"运行时：{rt.python}")
    for key, path in rt.bins.items():
        lines.append(f"{key}: {path}")
    lines.extend(f"✕ {p}" for p in rt.problems)
    return lines
