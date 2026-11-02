"""Check m8 IDs and provide an A-to-B table for every WGDI consumer."""
from __future__ import annotations

from pathlib import Path
from typing import Callable
import math

from ..core.issues import WgdiError


def validate_table(path: Path, *, allow_empty: bool = False) -> int:
    rows = 0
    with path.open(encoding="utf-8-sig") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 12:
                raise WgdiError(f"{path.name} 第 {number} 行不足 12 列；需要完整 outfmt 6 比对表")
            try:
                values = [float(x) for x in parts[2:12]]
                if not all(math.isfinite(x) for x in values):
                    raise ValueError("non-finite")
                if values[8] < 0 or values[9] < 0:
                    raise ValueError("negative score/evalue")
            except ValueError as exc:
                raise WgdiError(f"{path.name} 第 {number} 行的数值列不是合法有限数值") from exc
            rows += 1
    if not rows and not allow_empty:
        raise WgdiError(f"{path.name} 没有比对记录，不能继续 WGDI 分析")
    return rows


def _gene_ids(path: Path) -> set[str]:
    with path.open(encoding="utf-8-sig") as handle:
        return {parts[1] for line in handle
                if not line.startswith("#") and len(parts := line.split()) >= 6}


def for_wgdi(source: Path, gff1: Path, gff2: Path, target: Path, *,
             score: float, evalue: float,
             log: Callable[[str], None]) -> Path:
    """Keep the original search result; reverse a separate copy when B queries A.

    Detect direction from paired IDs, including for uploaded and legacy tables.
    A single canonical file avoids WGDI 0.75's inconsistent blast_reverse
    handling between dotplot, collinearity and blockinfo.
    """
    for path in (source, gff1, gff2):
        if not path.is_file():
            raise WgdiError(f"找不到文件：{path}")
    ids1, ids2 = _gene_ids(gff1), _gene_ids(gff2)
    forward = reverse = usable_forward = usable_reverse = rows = 0
    normalize = False
    with source.open(encoding="utf-8-sig") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip() or line.startswith("#"):
                normalize = True
                continue
            parts = line.split()
            normalize = normalize or len(line.rstrip("\r\n").split("\t")) < 12
            if len(parts) < 12:
                raise WgdiError(f"{source.name} 第 {number} 行不足 12 列；WGDI 需要完整的 outfmt 6 比对表")
            try:
                hit_score, hit_evalue = float(parts[11]), float(parts[10])
                passes = hit_score >= score and hit_evalue < evalue
            except ValueError as exc:
                raise WgdiError(f"{source.name} 第 {number} 行的 evalue 或得分不是数字") from exc
            q, s = parts[:2]
            f = q in ids1 and s in ids2
            r = q in ids2 and s in ids1
            forward += f
            reverse += r
            usable_forward += f and passes and q != s
            usable_reverse += r and passes and q != s
            rows += 1
    if not rows:
        raise WgdiError(f"{source.name} 里没有比对记录")
    log(f"比对 ID 核对：{rows:,} 行，A→B 匹配 {forward:,} 行，B→A 匹配 {reverse:,} 行")
    if not (forward or reverse):
        raise WgdiError("比对表前两列的基因 ID 与两个预处理 GFF 均不对应；请确认比对结果与预处理数据来自同一批文件")
    reversed_order = reverse > forward
    if not (usable_reverse if reversed_order else usable_forward):
        raise WgdiError("基因 ID 能对应，但按当前 score / evalue 过滤并排除同名自身命中后没有可用记录；请检查比对结果或调整阈值")
    if not reversed_order and not normalize:
        return source

    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open(encoding="utf-8-sig") as src, target.open("w", encoding="utf-8", newline="") as dst:
        for line in src:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split()
            if reversed_order:
                parts[0], parts[1] = parts[1], parts[0]
                parts[6:10] = parts[8:10] + parts[6:8]
            dst.write("\t".join(parts) + "\n")
    log(f"已整理为 WGDI 所需的 A→B 比对表：{target.name}（原始比对表保留）")
    return target
