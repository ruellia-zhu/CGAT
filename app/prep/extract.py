"""Random access into an indexed FASTA, plus translation.

Uses the `.fai` byte math so a 35 GB Lilium genome never gets loaded into RAM.
"""
from __future__ import annotations

from pathlib import Path

from ..core.issues import WgdiError
from .fai import FaiRecord

CODON_TABLE = {
    "TTT": "F", "TTC": "F", "TTA": "L", "TTG": "L", "CTT": "L", "CTC": "L", "CTA": "L",
    "CTG": "L", "ATT": "I", "ATC": "I", "ATA": "I", "ATG": "M", "GTT": "V", "GTC": "V",
    "GTA": "V", "GTG": "V", "TCT": "S", "TCC": "S", "TCA": "S", "TCG": "S", "CCT": "P",
    "CCC": "P", "CCA": "P", "CCG": "P", "ACT": "T", "ACC": "T", "ACA": "T", "ACG": "T",
    "GCT": "A", "GCC": "A", "GCA": "A", "GCG": "A", "TAT": "Y", "TAC": "Y", "TAA": "*",
    "TAG": "*", "CAT": "H", "CAC": "H", "CAA": "Q", "CAG": "Q", "AAT": "N", "AAC": "N",
    "AAA": "K", "AAG": "K", "GAT": "D", "GAC": "D", "GAA": "E", "GAG": "E", "TGT": "C",
    "TGC": "C", "TGA": "*", "TGG": "W", "CGT": "R", "CGC": "R", "CGA": "R", "CGG": "R",
    "AGT": "S", "AGC": "S", "AGA": "R", "AGG": "R", "GGT": "G", "GGC": "G", "GGA": "G",
    "GGG": "G",
}
_COMPLEMENT = bytes.maketrans(b"ACGTNacgtn", b"TGCANtgcan")


def reverse_complement(seq: bytes) -> bytes:
    return seq.translate(_COMPLEMENT)[::-1]


def translate(seq: bytes) -> str:
    """Standard code; incomplete trailing codon dropped, ambiguity -> X."""
    out = []
    usable = len(seq) - len(seq) % 3
    for i in range(0, usable, 3):
        codon = seq[i:i + 3].decode("ascii", "replace").upper()
        out.append(CODON_TABLE.get(codon, "X"))
    return "".join(out)


class FastaReader:
    """Seek-based reader over an indexed FASTA."""

    def __init__(self, path: Path, records: list[FaiRecord]):
        self.path = Path(path)
        if any(r.irregular for r in records):
            raise WgdiError("FASTA 换行宽度不一致，请先重排后重新索引")
        self.by_name = {r.name: r for r in records}
        if not self.path.exists():
            raise WgdiError(f"找不到基因组文件：{self.path}")
        self._handle = open(self.path, "rb")

    def close(self) -> None:
        try:
            self._handle.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "FastaReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def names(self) -> list[str]:
        return list(self.by_name)

    def length(self, name: str) -> int:
        return self.by_name[name].length

    def fetch(self, name: str, start: int, end: int) -> bytes:
        """1-based inclusive interval."""
        rec = self.by_name.get(name)
        if rec is None:
            raise WgdiError(f"序列 {name} 不在索引里")
        start = max(1, start)
        end = min(rec.length, end)
        if end < start:
            return b""
        begin_byte = rec.offset_of(start - 1)
        end_byte = rec.offset_of(end - 1) + 1
        self._handle.seek(begin_byte)
        raw = self._handle.read(end_byte - begin_byte)
        seq = raw.replace(b"\n", b"").replace(b"\r", b"")
        if len(seq) != end - start + 1 or b">" in seq:
            raise WgdiError(f"{name} 提取长度与坐标不一致，请检查 FASTA 换行和索引")
        return seq

    def fetch_segments(self, name: str, segments: list[tuple[int, int]], strand: str) -> bytes:
        chunks = [self.fetch(name, s, e) for s, e in sorted(segments)]
        seq = b"".join(chunks)
        return reverse_complement(seq) if strand == "-" else seq
