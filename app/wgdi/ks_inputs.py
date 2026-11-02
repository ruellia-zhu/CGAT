"""Validated sequence merging and successful Ks records (also used by runner)."""
from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path

KS_COLUMNS = ["id1", "id2", "ka_NG86", "ks_NG86", "ka_YN00", "ks_YN00"]


def read_fasta(path: Path) -> dict[str, str]:
    records = {}
    ident, sequence = None, []

    def flush():
        if ident is not None:
            if ident in records:
                raise ValueError(f"{path.name} 有重复 ID：{ident}")
            if not sequence:
                raise ValueError(f"{path.name} 的 {ident} 序列为空")
            records[ident] = "".join(sequence)

    with path.open(encoding="utf-8-sig") as handle:
        for line in handle:
            if line.startswith(">"):
                flush()
                if not line[1:].strip():
                    raise ValueError(f"{path.name} 有空的序列标题")
                ident, sequence = line[1:].split()[0], []
            elif line.strip():
                if ident is None:
                    raise ValueError(f"{path.name} 的序列缺少标题")
                sequence.append(line.strip())
        flush()
    if not records:
        raise ValueError(f"{path.name} 没有序列")
    return records


def merge_inputs(project) -> tuple[str, str]:
    proteins, cds = {}, {}
    digest = hashlib.sha256()
    for genome in project.genomes:
        pep_path = project.prepared / f"{genome.prefix}.wgdi.pep.fasta"
        cds_path = project.prepared / f"{genome.prefix}.wgdi.cds.fasta"
        pep, dna = read_fasta(pep_path), read_fasta(cds_path)
        if pep.keys() != dna.keys():
            raise ValueError(f"物种 {genome.prefix} 的蛋白与 CDS ID 不完全对应")
        duplicate = proteins.keys() & pep.keys()
        if duplicate:
            raise ValueError(f"两个物种有重复基因 ID（{sorted(duplicate)[0]}），请为不同物种使用唯一基因 ID")
        proteins.update(pep)
        cds.update(dna)
        for ident in pep:
            digest.update(f"{ident}\0{pep[ident]}\0{dna[ident]}\0".encode())
    directory = project.work / "ks_inputs" / digest.hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for suffix, records in (("pep", proteins), ("cds", cds)):
        target = directory / f"combined.{suffix}.fasta"
        if not target.exists():
            with target.open("w", encoding="utf-8", newline="") as handle:
                for ident, seq in records.items():
                    handle.write(f">{ident}\n{seq}\n")
        paths.append(target.relative_to(project.work).as_posix())
    return tuple(paths)


def read_valid_ks(path: Path) -> dict[tuple[str, str], list[str]]:
    result = {}
    if not path.exists():
        return result
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not set(KS_COLUMNS).issubset(reader.fieldnames or []):
            return result
        for row in reader:
            try:
                values = [float(row[k]) for k in KS_COLUMNS[2:]]
                if not all(math.isfinite(v) and v >= 0 for v in values):
                    continue
                if not row["id1"] or not row["id2"]:
                    continue
            except (ValueError, TypeError):
                continue
            pair = tuple(sorted((row["id1"], row["id2"])))
            result[pair] = [row[k] for k in KS_COLUMNS]
    return result
