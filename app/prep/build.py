"""Turn a genome into the four WGDI-ready artefacts.

Outputs, per genome::

    PREFIX.gff              7 columns: chrom gene start end strand order transcript
    PREFIX.len              chrom length gene_count
    PREFIX.wgdi.pep.fasta   longest transcript per gene, header = gene ID
    PREFIX.wgdi.cds.fasta   same choice, CDS nucleotides

Two entry points:

* :func:`prepare_auto`   – genome FASTA + GFF3/GTF; picks the longest transcript
  per gene and pulls sequences out of the genome.
* :func:`prepare_manual` – user already supplies `.fai` + CDS + protein; the
  annotation is only used for coordinates, and the user's ID set decides which
  transcript is kept.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..core.issues import Issue, WgdiError
from . import fai as fai_mod
from . import gff3 as gff3_mod
from . import rewrap as rewrap_mod
from .extract import FastaReader, translate
from .fai import FaiRecord

Progress = Callable[[str, int, int], None] | None
DEFAULT_EXCLUDE = re.compile(r"scaffold|contig|unplaced|unlocalized|random|chrUn|tig", re.I)


@dataclass
class PreparedGenome:
    prefix: str
    gff: Path
    len_file: Path
    pep: Path
    cds: Path | None
    fai: Path
    genome_fa: Path | None
    genes: int = 0
    sequences: int = 0
    issues: list[Issue] = field(default_factory=list)

    def summary(self) -> str:
        return f"{self.genes:,} 个基因 · {self.sequences:,} 条序列"


def _report(progress: Progress, stage: str, done: int, total: int) -> None:
    if progress is not None:
        progress(stage, done, total)


def _filter_records(records: list[FaiRecord], exclude: re.Pattern | None,
                    keep: re.Pattern | None, alias: Callable[[str], str]) -> list[FaiRecord]:
    out: list[FaiRecord] = []
    for rec in records:
        name = alias(rec.name)
        if keep is not None and not keep.search(name):
            continue
        if exclude is not None and exclude.search(name):
            continue
        out.append(FaiRecord(name, rec.length, rec.offset, rec.linebases, rec.linewidth))
    return out


def write_gff(choices: list[gff3_mod.GeneChoice], path: Path, alias: Callable[[str], str]) -> int:
    rows = sorted(
        ((alias(c.transcript.chrom), c.transcript.start, c.transcript.end,
          c.transcript.strand, c.gene_id, c.transcript.tx_id) for c in choices),
        key=lambda r: (r[0], r[1], -r[2], r[4]),
    )
    order = 0
    last_chrom = None
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        for chrom, start, end, strand, gene_id, tx_id in rows:
            order = order + 1 if chrom == last_chrom else 1
            last_chrom = chrom
            handle.write(f"{chrom}\t{gene_id}\t{start}\t{end}\t{strand}\t{order}\t{tx_id}\n")
    return len(rows)


def write_len(records: list[FaiRecord], counts: dict[str, int], path: Path) -> int:
    kept = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        for rec in records:
            if counts.get(rec.name, 0) <= 0:
                continue
            handle.write(f"{rec.name}\t{rec.length}\t{counts[rec.name]}\n")
            kept += 1
    return kept


def _write_fasta(path: Path, items: list[tuple[str, str]], width: int = 60) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        for name, seq in items:
            handle.write(f">{name}\n")
            for i in range(0, len(seq), width):
                handle.write(seq[i:i + width] + "\n")


def _alias_fn(strip_prefix: str) -> Callable[[str], str]:
    if not strip_prefix:
        return lambda name: name
    return lambda name: name[len(strip_prefix):] if name.startswith(strip_prefix) else name


def prepare_auto(
    genome_fa: Path, annotation: Path, out_dir: Path, prefix: str,
    *, width: int = 60, strip_prefix: str = "", exclude: re.Pattern | None = DEFAULT_EXCLUDE,
    keep: re.Pattern | None = None, progress: Progress = None,
    log: Callable[[str], None] | None = None,
) -> PreparedGenome:
    """Genome FASTA + annotation -> WGDI artefacts."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    alias = _alias_fn(strip_prefix)
    issues: list[Issue] = []
    speak = log or (lambda _msg: None)

    speak("建立索引…")
    records, idx_issues = fai_mod.index_fasta(
        genome_fa, progress=lambda d, t: _report(progress, "建立索引", d, t))
    issues += idx_issues

    need, why = fai_mod.needs_rewrap(records, width)
    if need:
        speak(f"重排 FASTA 为每行 {width} 碱基（{why}）…")
        target = out_dir / f"{prefix}.fa"
        _n, _b, rw_issues = rewrap_mod.rewrap(
            genome_fa, target, width,
            progress=lambda d, t: _report(progress, "重排 FASTA", d, t))
        issues += rw_issues
        records, _ = fai_mod.index_fasta(target, progress=lambda d, t: _report(progress, "重新索引", d, t))
        genome_fa = target
        issues.append(Issue("info", Path(genome_fa).name, f"已重排为 {width} 列：{why}"))

    records = _filter_records(records, exclude, keep, alias)
    if not records:
        raise WgdiError("过滤后没有剩下任何序列，检查排除规则 / 染色体命名")
    fai_path = fai_mod.write_fai(out_dir / f"{prefix}.fai", records)
    speak(f"索引完成：{len(records)} 条序列")

    speak("解析注释…")
    transcripts, ann_issues = gff3_mod.read_annotation(annotation)
    issues += ann_issues
    allowed = {r.name for r in records}
    transcripts = {k: v for k, v in transcripts.items() if alias(v.chrom) in allowed}
    if not transcripts:
        raise WgdiError("注释里的染色体与基因组的序列名对不上（检查是否需剥离前缀）")
    choices, pick_issues = gff3_mod.choose_longest(transcripts)
    issues += pick_issues
    speak(f"选出 {len(choices):,} 个基因（每基因 1 个转录本）")

    speak("提取 CDS 并翻译…")
    cds_items: list[tuple[str, str]] = []
    pep_items: list[tuple[str, str]] = []
    missing_cds = 0
    with FastaReader(genome_fa, records) as reader:
        for i, choice in enumerate(choices, 1):
            tx = choice.transcript
            if not tx.cds:
                missing_cds += 1
                continue
            raw = reader.fetch_segments(alias(tx.chrom), tx.cds, tx.strand)
            cds_items.append((choice.gene_id, raw.decode("ascii", "replace")))
            pep_items.append((choice.gene_id, translate(raw)))
            if i % 2000 == 0:
                _report(progress, "提取 CDS", i, len(choices))
    _report(progress, "提取 CDS", len(choices), len(choices))
    if missing_cds:
        issues.append(Issue("warning", annotation.name, f"{missing_cds} 个基因没有 CDS 坐标，已跳过"))
    if not pep_items:
        raise WgdiError("没有提取到任何 CDS，检查注释的 CDS 特征")

    gff_path = out_dir / f"{prefix}.gff"
    counts: dict[str, int] = {}
    for choice in choices:
        key = alias(choice.transcript.chrom)
        counts[key] = counts.get(key, 0) + 1
    write_gff(choices, gff_path, alias)
    sequences = write_len(records, counts, out_dir / f"{prefix}.len")
    cds_path = out_dir / f"{prefix}.wgdi.cds.fasta"
    pep_path = out_dir / f"{prefix}.wgdi.pep.fasta"
    _write_fasta(cds_path, cds_items)
    _write_fasta(pep_path, pep_items)
    speak(f"完成：{len(pep_items):,} 个基因，{sequences} 条染色体")

    return PreparedGenome(prefix, gff_path, out_dir / f"{prefix}.len", pep_path, cds_path,
                          fai_path, Path(genome_fa), len(pep_items), sequences, issues)


def prepare_manual(
    fai_path: Path, annotation: Path, pep_path: Path, cds_path: Path | None,
    out_dir: Path, prefix: str, *, strip_prefix: str = "",
    exclude: re.Pattern | None = DEFAULT_EXCLUDE,
    progress: Progress = None, log: Callable[[str], None] | None = None,
) -> PreparedGenome:
    """User-supplied .fai + longest-transcript CDS/protein + annotation."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    alias = _alias_fn(strip_prefix)
    issues: list[Issue] = []
    speak = log or (lambda _msg: None)

    speak("读取 .fai…")
    records, fai_issues = fai_mod.parse_fai(fai_path)
    issues += fai_issues
    bad = [i for i in fai_issues if i.level == "error"]
    if bad:
        raise WgdiError(str(bad[0]))
    records = _filter_records(records, exclude, None, alias)

    speak("读取注释…")
    transcripts, ann_issues = gff3_mod.read_annotation(annotation)
    issues += ann_issues
    by_tx = transcripts
    by_gene = {t.gene_id: t for t in transcripts.values()}

    speak("校验基因 ID…")
    ids, seqs = _read_fasta_ids(pep_path, progress, "校验蛋白")
    if not ids:
        raise WgdiError(f"{Path(pep_path).name} 里没有序列")
    if len(ids) != len(set(ids)):
        issues.append(Issue("error", Path(pep_path).name, "蛋白 FASTA 有重复 ID"))

    matched: dict[str, gff3_mod.Transcript] = {}
    ident_to_gene: dict[str, str] = {}
    missing: list[str] = []
    by_transcript = 0
    for ident in ids:
        tx = by_gene.get(ident)
        if tx is not None:
            matched[tx.gene_id] = tx
            ident_to_gene[ident] = tx.gene_id
            continue
        tx = by_tx.get(ident)
        if tx is not None:
            matched[tx.gene_id] = tx
            ident_to_gene[ident] = tx.gene_id
            by_transcript += 1
            continue
        missing.append(ident)
    if missing:
        preview = "、".join(missing[:8])
        raise WgdiError(
            f"蛋白文件里有 {len(missing)} 个 ID 在注释中找不到（例如 {preview}）。"
            "请确认注释与蛋白来自同一版本的基因组。")
    if by_transcript:
        issues.append(Issue("info", Path(pep_path).name,
                            f"{by_transcript} 个 ID 是转录本 ID，已按所属基因改名"))

    choices = [gff3_mod.GeneChoice(gene_id, tx, 0) for gene_id, tx in matched.items()]

    gff_path = out_dir / f"{prefix}.gff"
    counts: dict[str, int] = {}
    for choice in choices:
        key = alias(choice.transcript.chrom)
        counts[key] = counts.get(key, 0) + 1
    write_gff(choices, gff_path, alias)
    sequences = write_len(records, counts, out_dir / f"{prefix}.len")
    out_fai = fai_mod.write_fai(out_dir / f"{prefix}.fai", records)

    # Normalise the FASTA headers to gene IDs; WGDI's -ks matches them against
    # column 2 of the gff, so transcript-style headers would silently break Ks.
    pep_out = out_dir / f"{prefix}.wgdi.pep.fasta"
    cds_out = out_dir / f"{prefix}.wgdi.cds.fasta" if cds_path else None
    _rewrite_fasta(Path(pep_path), pep_out, ident_to_gene, progress, "整理蛋白")
    if cds_path:
        _rewrite_fasta(Path(cds_path), cds_out, ident_to_gene, progress, "整理 CDS")
        cds_ids, _ = _read_fasta_ids(Path(cds_path), None, "")
        if set(cds_ids) != set(ids):
            issues.append(Issue("warning", Path(cds_path).name,
                                "蛋白与 CDS 的 ID 集合不一致，Ks 计算可能受影响"))
    speak(f"完成：{len(choices):,} 个基因，{sequences} 条染色体")
    return PreparedGenome(prefix, gff_path, out_dir / f"{prefix}.len",
                          pep_out, cds_out, out_fai, None,
                          len(choices), sequences, issues)


def _rewrite_fasta(src: Path, dst: Path, id_map: dict[str, str],
                   progress: Progress, stage: str) -> int:
    """Copy `src`, renaming each header to `<gene_id> <original_id>`.

    Kept records are written as whole blocks, so a skipped record never leaves a
    header without its sequence.
    """
    written = 0
    size = src.stat().st_size
    dst.parent.mkdir(parents=True, exist_ok=True)
    header = ""
    seq: list[str] = []
    keep = False
    with src.open("r", encoding="utf-8", errors="replace") as fin, \
            dst.open("w", encoding="utf-8", newline="") as fout:
        for line in fin:
            if line.startswith(">"):
                if keep:
                    fout.write(header)
                    fout.writelines(seq)
                ident = line[1:].split()[0] if line[1:].strip() else ""
                gene = id_map.get(ident)
                keep = gene is not None
                header = f">{gene} {ident}\n" if keep else ""
                seq = []
                if keep:
                    written += 1
            elif keep:
                seq.append(line)
        if keep:
            fout.write(header)
            fout.writelines(seq)
    if progress is not None:
        progress(stage, size, size)
    return written


def _read_fasta_ids(path: Path, progress: Progress, stage: str) -> tuple[list[str], int]:
    ids: list[str] = []
    size = Path(path).stat().st_size
    with open(path, "rb") as handle:
        for line in handle:
            if line[:1] == b">":
                ids.append(line[1:].split()[0].decode("utf-8", "replace"))
        if progress is not None:
            progress(stage, size, size)
    return ids, size
