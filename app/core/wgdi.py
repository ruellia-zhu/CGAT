"""Readers for the three WGDI files: `.len`, `.gff` and `block_information.csv`.

The parsers never raise on a single bad line: bad records are skipped and an
`Issue` is recorded, so the UI can show "3 行有问题" instead of a traceback.
Only structural problems (missing file, missing columns) raise `WgdiError`.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from .issues import Issue, WgdiError
from .model import Block, Chromosome, Dataset, Gene, Genome

EXCLUDE_RE = re.compile(r"scaffold|contig|unplaced|unlocalized|random|chrUn|tig", re.I)

__all__ = ["Issue", "WgdiError", "read_len", "read_gff", "read_blocks", "load_dataset",
           "probe_len", "probe_gff", "probe_blocks", "Probe", "EXCLUDE_RE"]


def _open(path: Path):
    return path.open("r", encoding="utf-8", errors="replace")


# --- .len -------------------------------------------------------------------
def read_len(path: Path, name: str, label: str | None = None) -> tuple[Genome, list[Issue]]:
    """Read chromosome lengths. Column 3 (gene count) is optional."""
    path = Path(path)
    if not path.exists():
        raise WgdiError(f"找不到文件：{path}")
    issues: list[Issue] = []
    chroms: list[Chromosome] = []
    for lineno, line in enumerate(_open(path), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) < 2:
            issues.append(Issue("error", f"{path.name}:{lineno}", "至少要有 2 列（染色体名、长度）"))
            continue
        chrom = parts[0]
        try:
            length = int(float(parts[1]))
        except ValueError:
            issues.append(Issue("error", f"{path.name}:{lineno}", f"长度不是数字：{parts[1]!r}"))
            continue
        if length <= 0:
            issues.append(Issue("error", f"{path.name}:{lineno}", f"长度必须为正数：{length}"))
            continue
        count = None
        if len(parts) >= 3:
            try:
                count = int(float(parts[2]))
            except ValueError:
                issues.append(Issue("warning", f"{path.name}:{lineno}", f"基因数不是数字，已忽略：{parts[2]!r}"))
        if any(c.name == chrom for c in chroms):
            issues.append(Issue("warning", f"{path.name}:{lineno}", f"染色体 {chrom} 重复出现，只保留第一条"))
            continue
        chroms.append(Chromosome(chrom, length, count))
    if not chroms:
        raise WgdiError(f"{path.name} 里没有任何可用的染色体")
    return Genome(name=name, label=label or name, chromosomes=chroms), issues


# --- .gff -------------------------------------------------------------------
def read_gff(genome: Genome, path: Path, exclude: re.Pattern | None = EXCLUDE_RE) -> list[Issue]:
    """Fill `genome.genes` / `genome.by_order` from a WGDI gff (7 columns)."""
    path = Path(path)
    if not path.exists():
        raise WgdiError(f"找不到文件：{path}")
    issues: list[Issue] = []
    known = {c.name: c.length for c in genome.chromosomes}
    unknown: set[str] = set()
    bad_coord = dup_id = dup_order = 0
    for lineno, line in enumerate(_open(path), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) < 6:
            bad_coord += 1
            if bad_coord <= 5:
                issues.append(Issue("error", f"{path.name}:{lineno}", "少于 6 列，不是 WGDI gff 格式"))
            continue
        chrom, gene_id = parts[0], parts[1]
        try:
            start, end = int(float(parts[2])), int(float(parts[3]))
            order = int(float(parts[5]))
        except ValueError:
            bad_coord += 1
            if bad_coord <= 5:
                issues.append(Issue("error", f"{path.name}:{lineno}", "坐标或顺序号不是数字"))
            continue
        if start > end:
            start, end = end, start
        length = known.get(chrom)
        if length is None:
            if exclude is not None and exclude.search(chrom):
                continue
            unknown.add(chrom)
            continue
        if start < 1 or end > length:
            bad_coord += 1
            if bad_coord <= 5:
                issues.append(Issue(
                    "error", f"{path.name}:{lineno}",
                    f"{chrom} 坐标 {start}-{end} 超出染色体长度 {length}"))
            continue
        if gene_id in genome.genes:
            dup_id += 1
            if dup_id <= 5:
                issues.append(Issue("warning", f"{path.name}:{lineno}", f"基因 ID 重复：{gene_id}"))
            continue
        if (chrom, order) in genome.by_order:
            dup_order += 1
            if dup_order <= 5:
                issues.append(Issue("warning", f"{path.name}:{lineno}", f"{chrom} 的顺序号 {order} 重复"))
            continue
        gene = Gene(chrom, gene_id, start, end, parts[4], order)
        genome.genes[gene_id] = gene
        genome.by_order[(chrom, order)] = gene

    if unknown:
        shown = "、".join(sorted(unknown)[:5])
        issues.append(Issue(
            "warning", path.name,
            f"{len(unknown)} 条序列不在 .len 里，已跳过（{shown}{'…' if len(unknown) > 5 else ''}）"))
    for label, count in (("坐标非法", bad_coord), ("基因 ID 重复", dup_id), ("顺序号重复", dup_order)):
        if count > 5:
            issues.append(Issue("error" if label == "坐标非法" else "warning", path.name,
                                f"同类问题共 {count} 处，只显示了前 5 条"))
    if not genome.genes:
        raise WgdiError(f"{path.name} 里没有解析出任何基因，检查是不是 WGDI 格式（7 列、空白分隔）")
    return issues


# --- block_information.csv --------------------------------------------------
def _orders(value: object) -> tuple[int, ...]:
    if value is None:
        return ()
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ()
    out: list[int] = []
    for token in re.split(r"[_;,\s]+", text):
        if not token:
            continue
        try:
            out.append(int(float(token)))
        except ValueError:
            continue
    return tuple(out)


def _opt_float(value: object) -> float | None:
    try:
        if value is None or str(value).strip().lower() in ("", "nan"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def read_blocks(path: Path) -> tuple[list[Block], list[Issue]]:
    """Read block_information.csv. Only chr1/chr2/block1/block2 are required."""
    path = Path(path)
    if not path.exists():
        raise WgdiError(f"找不到文件：{path}")
    issues: list[Issue] = []
    with _open(path) as handle:
        sample = handle.readline()
        handle.seek(0)
        if "," not in sample:
            raise WgdiError(f"{path.name} 不是逗号分隔的 CSV，检查是不是 block_information 文件")
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or ())
        missing = {"chr1", "chr2", "block1", "block2"} - fields
        if missing:
            raise WgdiError(
                f"{path.name} 缺少必需列：{'、'.join(sorted(missing))}。"
                f"当前列名：{'、'.join(sorted(fields)) or '（空）'}")
        blocks: list[Block] = []
        for rank, row in enumerate(reader, 1):
            chr1 = (row.get("chr1") or "").strip()
            chr2 = (row.get("chr2") or "").strip()
            o1 = _orders(row.get("block1"))
            o2 = _orders(row.get("block2"))
            if not chr1 or not chr2 or not o1 or not o2:
                issues.append(Issue("error", f"{path.name}:第 {rank + 1} 行", "染色体或锚点列表为空"))
                continue
            if len(o1) != len(o2):
                issues.append(Issue(
                    "warning", f"{path.name}:第 {rank + 1} 行",
                    f"block1 有 {len(o1)} 个锚点、block2 有 {len(o2)} 个，按较短的配对"))
            block_id = (row.get("id") or str(rank)).strip() or str(rank)
            declared = row.get("length")
            try:
                declared_n = int(float(declared)) if declared not in (None, "") else 0
            except ValueError:
                declared_n = 0
            blocks.append(Block(
                block_id=block_id,
                rank=rank,
                chr1=chr1,
                chr2=chr2,
                orders1=o1,
                orders2=o2,
                original_anchors=declared_n or max(len(o1), len(o2)),
                pvalue=_opt_float(row.get("pvalue")),
                ks_median=_opt_float(row.get("ks_median")),
            ))
    if not blocks:
        raise WgdiError(f"{path.name} 里没有任何可用的共线块")
    return blocks, issues


# --- quick probes for the UI ------------------------------------------------
@dataclass(frozen=True)
class Probe:
    """Cheap, non-fatal look at a file so the UI can say what is inside it."""

    ok: bool
    detail: str = ""
    error: str = ""


def probe_len(path: Path) -> Probe:
    try:
        genome, issues = read_len(path, "probe")
    except WgdiError as exc:
        return Probe(False, error=str(exc))
    bp = sum(c.length for c in genome.chromosomes)
    bad = sum(1 for i in issues if i.level == "error")
    detail = f"{len(genome.chromosomes)} 条染色体 · {bp / 1e6:.0f} Mb"
    if bad:
        detail += f"（{bad} 行有问题）"
    return Probe(True, detail)


def probe_gff(path: Path) -> Probe:
    path = Path(path)
    if not path.exists():
        return Probe(False, error=f"找不到文件：{path}")
    genes = 0
    chroms: set[str] = set()
    bad = 0
    for line in _open(path):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) < 6:
            bad += 1
            continue
        chroms.add(parts[0])
        genes += 1
    if genes == 0:
        return Probe(False, error="没有读到任何基因，检查是不是 WGDI 格式（7 列、空白分隔）")
    detail = f"{genes:,} 个基因 · {len(chroms)} 条序列"
    if bad:
        detail += f"（{bad} 行格式不对）"
    return Probe(True, detail)


def probe_blocks(path: Path) -> Probe:
    try:
        blocks, issues = read_blocks(path)
    except WgdiError as exc:
        return Probe(False, error=str(exc))
    anchors = sum(min(len(b.orders1), len(b.orders2)) for b in blocks)
    bad = sum(1 for i in issues if i.level == "error")
    detail = f"{len(blocks):,} 个块 · {anchors:,} 个锚点"
    if bad:
        detail += f"（{bad} 行有问题）"
    return Probe(True, detail)


# --- dataset ----------------------------------------------------------------
def load_dataset(
    gff1: Path, len1: Path, blocks_csv: Path,
    gff2: Path | None = None, len2: Path | None = None,
    layout: str = "self",
    name1: str = "A", name2: str = "B",
    exclude: re.Pattern | None = EXCLUDE_RE,
) -> tuple[Dataset, list[Issue]]:
    """Read everything and cross-check it. Raises `WgdiError` only when unusable."""
    issues: list[Issue] = []
    genome1, i1 = read_len(len1, name1)
    issues += i1
    issues += read_gff(genome1, gff1, exclude)

    if layout == "self":
        genome2 = genome1
    else:
        if gff2 is None or len2 is None:
            raise WgdiError("跨物种布局需要物种 B 的 gff 和 len 文件")
        genome2, i2 = read_len(len2, name2)
        issues += i2
        issues += read_gff(genome2, gff2, exclude)

    blocks, ib = read_blocks(blocks_csv)
    issues += ib

    keep: list[Block] = []
    dropped = 0
    for b in blocks:
        if b.chr1 not in genome1.chromosome_names:
            dropped += 1
            continue
        if b.chr2 not in genome2.chromosome_names:
            dropped += 1
            continue
        keep.append(b)
    if dropped:
        issues.append(Issue("warning", blocks_csv.name,
                            f"{dropped} 个共线块引用了不存在的染色体，已跳过"))
    if not keep:
        raise WgdiError("没有任何共线块同时落在这两个基因组的染色体上")

    return Dataset(genome1, genome2, keep, layout), issues
