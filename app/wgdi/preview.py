"""Per-step preview data for the wizard. Pure functions, no Qt."""
from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from .project import Project

MAX_ROWS = 20


@dataclass
class Preview:
    kind: str = "none"                      # stats | table | image | text | none
    title: str = ""
    stats: list[tuple[str, str]] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    image: Path | None = None
    text: str = ""
    hint: str = ""
    warn: str = ""

    @property
    def empty(self) -> bool:
        return self.kind == "none"


def _human(value: float) -> str:
    if value >= 1e9:
        return f"{value / 1e9:,.2f} Gb"
    if value >= 1e6:
        return f"{value / 1e6:,.2f} Mb"
    if value >= 1e3:
        return f"{value / 1e3:,.1f} kb"
    return f"{value:,.0f}"


def _count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return sum(1 for line in handle if line.strip() and not line.startswith("#"))


def _read_len(path: Path) -> list[list[str]]:
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parts = line.split()
            if len(parts) < 2:
                continue
            length = parts[1]
            try:
                shown = _human(float(length))
            except ValueError:
                shown = length
            rows.append([parts[0], shown, parts[2] if len(parts) > 2 else "—"])
    return rows


def _alignment_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return sum(1 for line in handle if line.startswith("# Alignment"))


def _read_alignments(path: Path, limit: int = MAX_ROWS) -> list[list[str]]:
    rows: list[list[str]] = []
    header = ""
    members = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("# Alignment"):
                if header:
                    rows.append(_alignment_row(header, members))
                header = line.strip()
                members = 0
                continue
            if header and line.strip() and not line.startswith("#"):
                members += 1
            if len(rows) >= limit:
                break
    if header and len(rows) < limit:
        rows.append(_alignment_row(header, members))
    return rows


def _alignment_row(header: str, members: int) -> list[str]:
    number = re.search(r"#\s*Alignment\s+(\d+)", header)
    score = re.search(r"score=([\d.]+)", header)
    pvalue = re.search(r"pvalue=([\d.eE-]+)", header)
    pair = re.search(r"(\S+&\S+)", header)
    return [
        number.group(1) if number else "—",
        pair.group(1) if pair else "—",
        score.group(1) if score else "—",
        pvalue.group(1) if pvalue else "—",
        str(members),
    ]


def _read_ks(path: Path) -> tuple[int, list[float], list[list[str]]]:
    values: list[float] = []
    rows: list[list[str]] = []
    total = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader, None)
        if not header:
            return 0, [], []
        column = header.index("ks_YN00") if "ks_YN00" in header else len(header) - 1
        for parts in reader:
            if len(parts) <= column:
                continue
            total += 1
            try:
                ks = float(parts[column])
            except ValueError:
                continue
            if ks != ks or ks < 0:
                continue
            values.append(ks)
            if len(rows) < MAX_ROWS:
                rows.append([parts[0], parts[1], f"{ks:.4f}"])
    return total, values, rows


def _read_blocks(path: Path) -> tuple[list[str], list[list[str]], int]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None) or []
        rows: list[list[str]] = []
        total = 0
        for parts in reader:
            if not parts:
                continue
            total += 1
            if len(rows) < MAX_ROWS:
                rows.append(parts)
    return header, rows, total


def _pick(header: list[str], row: list[str], names: list[str]) -> list[str]:
    out = []
    for name in names:
        if name in header:
            index = header.index(name)
            out.append(row[index] if index < len(row) else "—")
        else:
            out.append("—")
    return out


def _ks_histogram(project: Project, values: list[float]) -> Path:
    """Draw a small Ks histogram; cached until the .ks file changes."""
    target = project.work / f"{project.stem}.ks.hist.png"
    source = project.work / f"{project.stem}.ks"
    if target.exists() and source.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return target
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(6.2, 2.6), dpi=110)
    axes.hist(values, bins=min(60, max(10, int(len(values) ** 0.5))),
              color="#2f6f5e", edgecolor="white", linewidth=0.3)
    axes.set_xlabel("Ks", fontsize=9)
    axes.tick_params(labelsize=8)
    for spine in ("top", "right"):
        axes.spines[spine].set_visible(False)
    figure.tight_layout()
    figure.savefig(target)
    plt.close(figure)
    return target


# --- public -------------------------------------------------------------
def build(project: Project, key: str) -> Preview:
    if project.steps.get(key, {}).get("invalidated"):
        return Preview(hint="输入、参数或上游结果已变化，请重新运行本步；旧结果保留在项目中。")
    stem = project.stem
    work = project.work
    prepared = project.prepared

    if key == "prep":
        detail = project.step_detail("prep")
        if not detail:
            return Preview(hint="本步还没运行。设置好物种与过滤条件后点「运行本步」。")
        stats: list[tuple[str, str]] = []
        rows: list[list[str]] = []
        dropped_total = 0
        for side in ("A", "B") if not project.self_compare else ("A",):
            genome = project.genome_a if side == "A" else project.genome_b
            if genome is None:
                continue
            info = detail.get(genome.prefix, {})
            if not info:
                continue
            tag = side if info else side
            stats.append((f"物种 {side}", genome.display_name or genome.prefix))
            stats.append((f"基因数（{tag}）", f"{info.get('genes', 0):,}"))
            stats.append((f"保留序列（{tag}）", f"{info.get('sequences', 0):,}"))
            dropped_total += len(info.get("dropped", []))
        stats.append(("排除序列", f"{dropped_total:,}"))
        rows: list[list[str]] = []
        for side in ("A", "B") if not project.self_compare else ("A",):
            genome = project.genome_a if side == "A" else project.genome_b
            if genome is None:
                continue
            for item in _read_len(prepared / f"{genome.prefix}.len")[:10]:
                rows.append([side, *item])
        preview = Preview(kind="table", title="保留的序列", stats=stats,
                          headers=["物种", "染色体", "长度", "基因数"],
                          rows=rows[:MAX_ROWS])
        if detail.get(project.genome_a.prefix, {}).get("dropped"):
            preview.text = "已排除：" + "、".join(
                detail[project.genome_a.prefix]["dropped"][:12])
        if not project.filters.chromosomes_only:
            preview.warn = "未开启「只保留染色体」，contig/scaffold 会进入后续所有图"
        elif project.step_detail("prep").get(project.genome_a.prefix, {}).get("sequences", 0) < 5:
            preview.warn = "保留的序列少于 5 条，可能是 scaffold 级组装，建议放宽过滤"
        return preview

    if key == "blast":
        target = work / f"{stem}.blastp.txt"
        if not target.exists():
            return Preview(hint="本步还没运行。可以现在开始比对，也可以上传已有的比对结果。")
        hits = _count_lines(target)
        queries: set[str] = set()
        rows: list[list[str]] = []
        with target.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parts = line.split("\t")
                if len(parts) < 12:
                    parts = line.split()
                if len(parts) < 12:
                    continue
                queries.add(parts[0])
                if len(rows) < MAX_ROWS:
                    rows.append([parts[0], parts[1], parts[2], parts[10]])
        source = "上传" if project.blast_input.source == "upload" else project.engine
        db = sorted(project.work.glob("*.dmnd")) + sorted(
            prepared.glob(f"{project.genome_a.prefix}.wgdi.pep.fasta.p*"))
        db_size = sum(p.stat().st_size for p in db) / 1e6
        stats = [("来源", source), ("命中", f"{hits:,}"),
                 ("查询序列", f"{len(queries):,}")]
        if db:
            stats.append(("比对库", f"{db_size:,.0f} MB"))
        return Preview(kind="table", title="比对结果", stats=stats,
                       headers=["query", "subject", "identity", "evalue"], rows=rows)

    if key == "dotplot":
        image = work / f"{stem}.dot.1.png"
        return (Preview(kind="image", title="点阵图", image=image)
                if image.exists() else Preview(hint="本步还没运行。"))

    if key == "collinearity":
        target = work / f"{stem}.collinearity.txt"
        if not target.exists():
            return Preview(hint="本步还没运行。")
        count = _alignment_count(target)
        rows = _read_alignments(target)
        return Preview(kind="table", title="共线块",
                       stats=[("共线块", f"{count:,}")],
                       headers=["#", "染色体对", "score", "pvalue", "锚点数"], rows=rows)

    if key == "ks":
        target = work / f"{stem}.ks"
        if not target.exists():
            return Preview(hint="本步还没运行。")
        total, values, rows = _read_ks(target)
        if not values:
            return Preview(kind="stats", title="Ks 结果",
                           stats=[("配对数", f"{total:,}")],
                           warn="没有可用的 Ks 值，检查序列质量或比对参数")
        ordered = sorted(values)
        median = ordered[len(ordered) // 2]
        mean = sum(ordered) / len(ordered)
        image = _ks_histogram(project, values)
        return Preview(kind="image", title="Ks 分布", image=image,
                       stats=[("配对数", f"{total:,}"), ("有效 Ks", f"{len(values):,}"),
                              ("中位数", f"{median:.3f}"), ("均值", f"{mean:.3f}")],
                       headers=["id1", "id2", "ks"], rows=rows)

    if key == "blockinfo":
        target = work / f"{stem}_block_information.csv"
        if not target.exists():
            return Preview(hint="本步还没运行。")
        header, rows, total = _read_blocks(target)
        anchors = 0
        with target.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            for record in reader:
                try:
                    anchors += int(float(record.get("length") or 0))
                except ValueError:
                    continue
        trimmed = [[r[0]] + _pick(header, r, ["chr1", "chr2", "length", "pvalue", "ks_median"])
                   for r in rows]
        return Preview(kind="table", title="共线块汇总",
                       stats=[("块数", f"{total:,}"), ("锚点总数", f"{anchors:,}")],
                       headers=["id", "chr1", "chr2", "长度", "pvalue", "ks_median"],
                       rows=trimmed)

    if key == "blockks":
        image = work / f"{stem}.ks.dotplot.png"
        return (Preview(kind="image", title="Ks 点阵", image=image)
                if image.exists() else Preview(hint="本步还没运行或已跳过。"))

    if key == "kspeaks":
        image = work / f"{stem}.ks_median_distribution.png"
        if not image.exists():
            return Preview(hint="本步还没运行或已跳过。")
        return Preview(kind="image", title="Ks 分布", image=image)

    if key == "circos":
        image = project.results / f"{stem}.png"
        pdf = project.results / f"{stem}.pdf"
        files = [p for p in project.outputs("circos") if p.exists()]
        if not files:
            return Preview(hint="本步还没运行。")
        size = pdf.stat().st_size / 1024 if pdf.exists() else 0
        return Preview(kind="image" if image.exists() else "stats", title="Circos",
                       image=image if image.exists() else None,
                       stats=[(p.suffix[1:].upper(), f"{p.stat().st_size / 1024:,.0f} KB") for p in files])

    return Preview(hint="未知步骤")
