"""Assemble the one-folder distribution after PyInstaller has run.

PyInstaller produces `dist/比较基因组分析/` with the exe and `_internal/`; this
script copies the external runtime pieces next to it and runs the self-test.

python build/assemble.py [--skip-selftest]
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "比较基因组分析"
DIST = ROOT / "dist" / NAME
EXE = DIST / f"{NAME}.exe"
EXTRAS = ("runtime", "bin")


def copy_tree(src: Path, dst: Path) -> int:
    if not src.exists():
        print(f"   跳过 {src.name}（不存在）")
        return 0
    count = 0
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        target = dst / path.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        count += 1
    return count


def size_of(path: Path) -> float:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 1e6


def main(argv: list[str]) -> int:
    if not EXE.exists():
        print(f"找不到 {EXE}，先运行 PyInstaller")
        return 1
    print(f"[2/3] 附加运行时与外部程序 → {DIST.name}")
    for name in EXTRAS:
        copied = copy_tree(ROOT / name, DIST / name)
        print(f"   {name}: {copied} 个文件")

    print(f"   总大小 {size_of(DIST):,.0f} MB")

    if "--skip-selftest" in argv:
        print("[3/3] 跳过自检")
        return 0
    print("[3/3] 自检 …")
    done = subprocess.run([str(EXE), "--selftest"], cwd=str(DIST),
                          capture_output=True, text=True, timeout=300)
    print("   exit:", done.returncode)
    out = (done.stdout or "") + (done.stderr or "")
    for line in out.strip().splitlines()[-5:]:
        print("   ", line[:120])
    return 0 if done.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
