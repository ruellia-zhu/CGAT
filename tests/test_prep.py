"""Synthetic tests for the preprocessing layer (no real genome needed).

Run:  ..\\circos_dev\\.venv\\Scripts\\python.exe tests\\test_prep.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.issues import WgdiError  # noqa: E402
from app.prep import build  # noqa: E402
from app.prep import gff3 as G  # noqa: E402

PASS = FAIL = 0


def check(name: str, fn) -> None:
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  PASS  {name}")
    except AssertionError as exc:
        FAIL += 1
        print(f"  FAIL  {name}: {exc}")
    except Exception as exc:  # noqa: BLE001
        FAIL += 1
        print(f"  ERROR {name}: {type(exc).__name__}: {exc}")


def write(text: str, suffix: str) -> Path:
    f = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8", newline="")
    f.write(text)
    f.close()
    return Path(f.name)


# a 300 bp chromosome: gene1 at 10-90, gene2 at 110-190
GENOME = (
    ">chr1\n" + "ACGT" * 75 + "\n"
    + ">chr2\n" + "TTGGCC" * 50 + "\n"
)

# gene g1 has two transcripts: t1 (CDS 10-50, 41 bp) and t1long (CDS 10-90, 81 bp)
ANNOT = """##gff-version 3
chr1\tx\tgene\t10\t90\t.\t+\t.\tID=g1
chr1\tx\tmRNA\t10\t90\t.\t+\t.\tID=t1;Parent=g1
chr1\tx\tCDS\t10\t50\t.\t+\t0\tID=c1;Parent=t1
chr1\tx\tmRNA\t10\t90\t.\t+\t.\tID=t1long;Parent=g1
chr1\tx\tCDS\t10\t90\t.\t+\t0\tID=c2;Parent=t1long
chr1\tx\tgene\t110\t190\t.\t-\t.\tID=g2
chr1\tx\tmRNA\t110\t190\t.\t-\t.\tID=t2;Parent=g2
chr1\tx\tCDS\t110\t190\t.\t-\t0\tID=c3;Parent=t2
chr2\tx\tgene\t10\t100\t.\t+\t.\tID=g3
chr2\tx\tmRNA\t10\t100\t.\t+\t.\tID=t3;Parent=g3
chr2\tx\tCDS\t10\t99\t.\t+\t0\tID=c4;Parent=t3
"""

GTF = """chr1\tsrc\tgene\t10\t90\t.\t+\t.\tgene_id "g1";
chr1\tsrc\ttranscript\t10\t90\t.\t+\t.\tgene_id "g1"; transcript_id "t1";
chr1\tsrc\tCDS\t10\t90\t.\t+\t0\tgene_id "g1"; transcript_id "t1";
"""


def tmpdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="circos_prep_test_"))


# --- annotation parsing -----------------------------------------------------
def test_parse_attributes_both_syntaxes() -> None:
    a = G.parse_attributes("ID=t1;Parent=g1")
    b = G.parse_attributes('gene_id "g1"; transcript_id "t1";')
    assert a["ID"] == "t1" and a["Parent"] == "g1", a
    assert b["gene_id"] == "g1" and b["transcript_id"] == "t1", b


def test_read_annotation_gff3() -> None:
    records, issues = G.read_annotation(write(ANNOT, ".gff3"))
    assert set(records) == {"t1", "t1long", "t2", "t3"}, set(records)
    assert records["t1long"].cds_len == 81, records["t1long"].cds_len
    assert records["t1"].cds_len == 41
    assert records["t1"].gene_id == "g1"


def test_read_annotation_gtf() -> None:
    records, _ = G.read_annotation(write(GTF, ".gtf"))
    assert list(records) == ["t1"]
    assert records["t1"].gene_id == "g1"
    assert records["t1"].cds_len == 81


def test_choose_longest() -> None:
    records, _ = G.read_annotation(write(ANNOT, ".gff3"))
    choices, _ = G.choose_longest(records)
    by_gene = {c.gene_id: c.transcript.tx_id for c in choices}
    assert by_gene == {"g1": "t1long", "g2": "t2", "g3": "t3"}, by_gene


def test_cds_only_annotation() -> None:
    ann = "chr1\tx\tCDS\t10\t30\t.\t+\t0\tParent=t9;gene_id=g9\n"
    records, issues = G.read_annotation(write(ann, ".gff3"))
    assert "t9" in records and records["t9"].cds_len == 21
    assert any("反推" in i.message for i in issues), [i.message for i in issues]


# --- auto mode --------------------------------------------------------------
def test_prepare_auto_outputs() -> None:
    d = tmpdir()
    out = d / "out"
    prepared = build.prepare_auto(
        write(GENOME, ".fa"), write(ANNOT, ".gff3"), out, "SYN", exclude=None)
    assert prepared.genes == 3, prepared.genes
    gff = prepared.gff.read_text().splitlines()
    assert gff[0].split("\t")[:2] == ["chr1", "g1"]
    assert len(gff) == 3, len(gff)
    assert [l.split("\t")[5] for l in gff] == ["1", "2", "1"], [l.split("\t")[5] for l in gff]
    assert prepared.len_file.read_text().splitlines()[0].startswith("chr1\t300\t2")
    pep = prepared.pep.read_text()
    assert pep.startswith(">g1"), pep[:40]
    assert prepared.cds is not None and prepared.cds.read_text().startswith(">g1")
    assert (out / "SYN.fai").exists()


def test_auto_picks_longest_cds() -> None:
    d = tmpdir()
    prepared = build.prepare_auto(
        write(GENOME, ".fa"), write(ANNOT, ".gff3"), d / "out", "SYN", exclude=None)
    cds = {k: v for k, v in _fasta(prepared.cds).items()}
    assert len(cds["g1"]) == 81, len(cds["g1"])
    assert all(b in "ACGTN" for b in cds["g1"])


def test_auto_minus_strand_is_reverse_complemented() -> None:
    from app.prep.extract import reverse_complement

    d = tmpdir()
    prepared = build.prepare_auto(
        write(GENOME, ".fa"), write(ANNOT, ".gff3"), d / "out", "SYN", exclude=None)
    genome = {"chr1": "ACGT" * 75, "chr2": "TTGGCC" * 50}
    plus = _fasta(prepared.cds)["g3"]
    minus = _fasta(prepared.cds)["g2"]
    assert plus == genome["chr2"][9:99], plus[:12]
    assert minus == reverse_complement(genome["chr1"][109:190].encode()).decode(), minus[:12]


def test_auto_missing_chrom_alias() -> None:
    d = tmpdir()
    try:
        build.prepare_auto(write(">other\nACGT\n", ".fa"), write(ANNOT, ".gff3"),
                           d / "out", "SYN", exclude=None)
    except WgdiError as exc:
        assert "对不上" in str(exc), exc
        return
    raise AssertionError("应当报染色体名对不上")


# --- manual mode ------------------------------------------------------------
def test_prepare_manual_renames_to_gene_ids() -> None:
    d = tmpdir()
    out = d / "out"
    genome = write(GENOME, ".fa")
    ann = write(ANNOT, ".gff3")
    from app.prep import fai as F
    records, _ = F.index_fasta(genome)
    fai_path = F.write_fai(d / "SYN.fai", records)
    pep = write(">t1long\nMKT\n>t2\nMKK\n>t3\nMK*\n", ".pep.fasta")
    prepared = build.prepare_manual(fai_path, ann, pep, None, out, "SYN", exclude=None)
    text = prepared.pep.read_text()
    assert ">g1 t1long" in text, text[:60]
    assert prepared.genes == 3


def test_manual_rejects_unknown_ids() -> None:
    d = tmpdir()
    genome = write(GENOME, ".fa")
    from app.prep import fai as F
    records, _ = F.index_fasta(genome)
    fai_path = F.write_fai(d / "SYN.fai", records)
    pep = write(">t1long\nMKT\n>nope\nMKK\n", ".pep.fasta")
    try:
        build.prepare_manual(fai_path, write(ANNOT, ".gff3"), pep, None, d / "out", "SYN", exclude=None)
    except WgdiError as exc:
        assert "找不到" in str(exc), exc
        return
    raise AssertionError("应当报 ID 不匹配")


def _fasta(path: Path | None) -> dict[str, str]:
    assert path is not None
    out, name, buf = {}, None, []
    for line in path.read_text().splitlines():
        if line.startswith(">"):
            if name:
                out[name] = "".join(buf)
            name, buf = line[1:].split()[0], []
        elif name:
            buf.append(line.strip())
    if name:
        out[name] = "".join(buf)
    return out


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    print(f"预处理测试：{len(tests)} 项\n")
    for name, fn in tests:
        check(name[5:], fn)
    print(f"\n{PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
