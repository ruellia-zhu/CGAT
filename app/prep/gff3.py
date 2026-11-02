"""GFF3 / GTF parsing and longest-transcript selection.

AGAT does this well but is slow; this is a single streaming pass with no third
party parser. It handles both syntaxes, attribute quoting, and annotations that
carry no mRNA/transcript features at all (CDS-only).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..core.issues import Issue, WgdiError

_ATTR_SPLIT = re.compile(r";\s*")
_KEY_VALUE = re.compile(r"^\s*([A-Za-z0-9_.:-]+)\s*[= ]\s*\"?([^\";]*)\"?")

TRANSCRIPT_TYPES = {"mrna", "transcript", "ncrna", "trna", "rrna"}
GENE_TYPES = {"gene", "pseudogene"}


def parse_attributes(text: str) -> dict[str, str]:
    """`ID=x;Parent=y` and `gene_id "x"; transcript_id "y";` both land here."""
    out: dict[str, str] = {}
    for part in _ATTR_SPLIT.split(text.strip().rstrip(";")):
        if not part:
            continue
        match = _KEY_VALUE.match(part)
        if match:
            out.setdefault(match.group(1), match.group(2).strip())
        elif "=" in part:
            key, value = part.split("=", 1)
            out.setdefault(key.strip(), value.strip())
    return out


@dataclass
class Transcript:
    tx_id: str
    gene_id: str
    chrom: str
    start: int
    end: int
    strand: str
    cds_len: int = 0
    cds: list[tuple[int, int]] = field(default_factory=list)

    def finalize(self) -> None:
        if self.cds:
            self.cds.sort()
            self.cds_len = sum(e - s + 1 for s, e in self.cds)
            self.start = min(self.start, self.cds[0][0])
            self.end = max(self.end, self.cds[-1][1])


@dataclass(frozen=True)
class GeneChoice:
    gene_id: str
    transcript: Transcript
    alternatives: int


def _tx_key(attrs: dict[str, str], ftype: str) -> tuple[str, str] | None:
    """(transcript_id, gene_id) for a feature, or None when unusable."""
    tx = attrs.get("transcript_id") or attrs.get("ID") if ftype in TRANSCRIPT_TYPES else None
    if ftype == "cds":
        tx = attrs.get("transcript_id") or attrs.get("Parent") or attrs.get("ID")
    if not tx:
        return None
    tx = tx.split(",")[0].strip()
    gene = attrs.get("gene_id") or attrs.get("Parent") or attrs.get("gene") or tx
    gene = gene.split(",")[0].strip()
    return tx, gene


def read_annotation(path: Path) -> tuple[dict[str, Transcript], list[Issue]]:
    """One pass; returns every transcript keyed by transcript id."""
    path = Path(path)
    if not path.exists():
        raise WgdiError(f"找不到文件：{path}")
    issues: list[Issue] = []
    transcripts: dict[str, Transcript] = {}
    cds_only: dict[str, dict] = {}
    bad_lines = 0
    gene_rows = 0

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for lineno, raw in enumerate(handle, 1):
            if not raw or raw[0] == "#":
                continue
            parts = raw.rstrip("\n").split("\t")
            if len(parts) < 9:
                bad_lines += 1
                continue
            chrom, _source, ftype, start, end, _score, strand, _phase, attrs_raw = parts[:9]
            ftype_l = ftype.lower()
            attrs = parse_attributes(attrs_raw)
            try:
                begin, finish = int(start), int(end)
            except ValueError:
                bad_lines += 1
                continue
            if begin > finish:
                begin, finish = finish, begin

            if ftype_l in GENE_TYPES:
                gene_rows += 1
                continue

            if ftype_l in TRANSCRIPT_TYPES:
                tx, gene = _tx_key(attrs, ftype_l) or (None, None)
                if not tx:
                    continue
                existing = transcripts.get(tx)
                if existing is None:
                    transcripts[tx] = Transcript(tx, gene or tx, chrom, begin, finish, strand)
                continue

            if ftype_l != "cds":
                continue
            tx, gene = _tx_key(attrs, "cds") or (None, None)
            if not tx:
                continue
            record = transcripts.get(tx)
            if record is None:
                stash = cds_only.setdefault(tx, {"gene": gene or tx, "chrom": chrom,
                                                 "strand": strand, "segs": []})
                stash["segs"].append((begin, finish))
                continue
            record.cds.append((begin, finish))

    for tx, stash in cds_only.items():
        record = Transcript(tx, stash["gene"], stash["chrom"], 0, 0, stash["strand"])
        record.cds = list(stash["segs"])
        record.finalize()
        transcripts[tx] = record

    for record in transcripts.values():
        if record.cds_len == 0 and record.cds:
            record.finalize()
        elif record.cds:
            record.finalize()

    if bad_lines:
        issues.append(Issue("warning", path.name, f"{bad_lines} 行不是合法的 9 列注释，已跳过"))
    if not transcripts:
        raise WgdiError(f"{path.name} 里没有解析出任何转录本（检查是否为 GFF3/GTF）")
    if gene_rows == 0 and cds_only:
        issues.append(Issue("warning", path.name, "注释里没有 gene/mRNA 层，已从 CDS 反推转录本"))
    return transcripts, issues


def choose_longest(transcripts: dict[str, Transcript]) -> tuple[list[GeneChoice], list[Issue]]:
    """Pick one transcript per gene: longest CDS, ties broken by transcript id."""
    by_gene: dict[str, list[Transcript]] = {}
    for record in transcripts.values():
        by_gene.setdefault(record.gene_id, []).append(record)

    issues: list[Issue] = []
    no_cds = [t for group in by_gene.values() for t in group if t.cds_len == 0]
    if no_cds:
        issues.append(Issue(
            "warning", "注释",
            f"{len(no_cds)} 个转录本没有 CDS 长度（缺 CDS 特征），按外显子/整体长度兜底"))

    choices: list[GeneChoice] = []
    for gene_id, group in by_gene.items():
        def rank(t: Transcript) -> tuple[int, int, str]:
            span = t.end - t.start + 1
            return (-t.cds_len if t.cds_len else -span, len(t.cds), t.tx_id)

        best = min(group, key=rank)
        choices.append(GeneChoice(gene_id, best, len(group) - 1))

    duplicated = sum(1 for c in choices if c.alternatives > 0)
    if duplicated:
        issues.append(Issue("info", "注释", f"{duplicated} 个基因有多转录本，已各取最长的一个"))
    return choices, issues


def chrom_aliases(choices: list[GeneChoice]) -> set[str]:
    return {c.transcript.chrom for c in choices}
