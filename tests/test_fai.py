"""FASTA indexing / .fai tests, including the Lilium overflow cases.

Run:  ..\\circos_dev\\.venv\\Scripts\\python.exe tests\\test_fai.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.issues import WgdiError  # noqa: E402
from app.prep import fai as F  # noqa: E402
from app.prep import rewrap as R  # noqa: E402
from app.prep.extract import FastaReader  # noqa: E402

PASS = FAIL = 0
INT32 = 2**31


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


def tmpfile(text: str, suffix: str = ".fa", newline: str = "\n") -> Path:
    f = tempfile.NamedTemporaryFile("wb", suffix=suffix, delete=False)
    f.write(text.replace("\n", newline).encode())
    f.close()
    return Path(f.name)


def wrap(seq: str, width: int = 60) -> str:
    return "\n".join(seq[i:i + width] for i in range(0, len(seq), width))


SEQ_A = "ACGT" * 40          # 160 bp
SEQ_B = "TTGGCC" * 30        # 180 bp


# --- indexing ---------------------------------------------------------------
def test_index_wrapped() -> None:
    p = tmpfile(f">chr1 desc\n{wrap(SEQ_A)}\n>chr2\n{wrap(SEQ_B)}\n")
    recs, issues = F.index_fasta(p)
    assert [r.name for r in recs] == ["chr1", "chr2"], [r.name for r in recs]
    assert recs[0].length == 160 and recs[1].length == 180
    assert recs[0].linebases == 60 and recs[0].linewidth == 61
    assert not issues
    # chr2's sequence starts after chr1's header (11) + 3 lines (61+61+41) + ">chr2\n"
    expected = len(">chr1 desc\n") + (61 + 61 + 41) + len(">chr2\n")
    assert recs[1].offset == expected, (recs[1].offset, expected)


def test_index_crlf() -> None:
    p = tmpfile(f">chr1\n{wrap(SEQ_A)}\n", newline="\r\n")
    recs, _ = F.index_fasta(p)
    assert recs[0].length == 160
    assert recs[0].linewidth == 62, recs[0].linewidth   # 60 bases + CRLF


def test_index_single_line() -> None:
    p = tmpfile(f">chr1\n{SEQ_A}\n")
    recs, _ = F.index_fasta(p)
    assert recs[0].linebases == 160 and recs[0].single_line
    need, why = F.needs_rewrap(recs)
    assert need and "一行" in why, why


def test_giant_single_line_flags_rewrap() -> None:
    """Mimics L. davidii: linebases == whole chromosome, i.e. > 2^31."""
    rec = F.FaiRecord("LG01", 4_336_260_641, 6, 4_336_260_641, 4_336_260_642)
    need, why = F.needs_rewrap([rec])
    assert need and rec.int32_unsafe and rec.single_line, why


def test_rewrap_threshold() -> None:
    """每行 <100 碱基不重排；>=100 才重排。"""
    narrow = F.FaiRecord("chr1", 1000, 0, 50, 51)
    wide = F.FaiRecord("chr1", 1000, 0, 120, 121)
    sixty = F.FaiRecord("chr1", 1000, 0, 60, 61)
    assert F.needs_rewrap([narrow])[0] is False, "50 列不该重排"
    assert F.needs_rewrap([sixty])[0] is False, "60 列不该重排"
    assert F.needs_rewrap([wide])[0] is True, "120 列应重排"
    assert F.needs_rewrap([narrow, sixty])[0] is False, "50/60 混用也不必重排"


def test_index_missing_file() -> None:
    try:
        F.index_fasta(Path("no_such_file.fa"))
    except WgdiError:
        return
    raise AssertionError("应当抛出 WgdiError")


# --- .fai parsing -----------------------------------------------------------
def test_parse_fai_large_values() -> None:
    p = tmpfile(
        "Chr01\t4300821514\t7\t60\t61\n"
        "Chr02\t3979246691\t4372501887\t60\t61\n", ".fai")
    recs, issues = F.parse_fai(p)
    assert len(recs) == 2
    assert recs[0].length == 4_300_821_514
    assert recs[1].offset == 4_372_501_887
    assert all(r.int32_unsafe for r in recs)
    assert any("2^31" in i.message for i in issues), [i.message for i in issues]
    assert not any(i.level == "error" for i in issues)


def test_parse_fai_rejects_negative() -> None:
    p = tmpfile("LG01\t-13730527\t-2147483648\t60\t61\n", ".fai")
    recs, issues = F.parse_fai(p)
    assert not recs
    assert any("负数值" in i.message and i.level == "error" for i in issues), [i.message for i in issues]


def test_parse_fai_bad_columns() -> None:
    p = tmpfile("chr1\t1000\n", ".fai")
    _recs, issues = F.parse_fai(p)
    assert any("5 列" in i.message for i in issues)


def test_offset_of_math() -> None:
    rec = F.FaiRecord("chr1", 200, 7, 60, 61)
    assert rec.offset_of(0) == 7
    assert rec.offset_of(59) == 66
    assert rec.offset_of(60) == 7 + 61          # second line starts after the newline
    assert rec.offset_of(199) == 7 + 3 * 61 + 19


# --- fetching ---------------------------------------------------------------
def test_fetch_roundtrip() -> None:
    p = tmpfile(f">chr1\n{wrap(SEQ_A)}\n>chr2\n{wrap(SEQ_B)}\n")
    recs, _ = F.index_fasta(p)
    with FastaReader(p, recs) as reader:
        assert reader.fetch("chr1", 1, 60).decode() == SEQ_A[:60]
        assert reader.fetch("chr1", 61, 120).decode() == SEQ_A[60:120]
        assert reader.fetch("chr2", 1, 180).decode() == SEQ_B
        assert reader.fetch("chr2", 100, 200).decode() == SEQ_B[99:180]
        assert reader.fetch("chr1", 1, 160).decode() == SEQ_A


def test_fetch_across_many_lines() -> None:
    seq = "ACGT" * 300                          # 1200 bp -> 20 lines
    p = tmpfile(f">c\n{wrap(seq)}\n")
    recs, _ = F.index_fasta(p)
    with FastaReader(p, recs) as reader:
        for start in (1, 59, 61, 500, 1150):
            got = reader.fetch("c", start, start + 39).decode()
            assert got == seq[start - 1:start - 1 + 40], (start, got)


def test_fetch_segments_minus_strand() -> None:
    p = tmpfile(f">c\n{wrap(SEQ_A)}\n")
    recs, _ = F.index_fasta(p)
    with FastaReader(p, recs) as reader:
        plus = reader.fetch_segments("c", [(1, 10), (21, 30)], "+")
        assert plus.decode() == SEQ_A[:10] + SEQ_A[20:30]
        from app.prep.extract import reverse_complement
        minus = reader.fetch_segments("c", [(1, 10), (21, 30)], "-")
        assert minus == reverse_complement((SEQ_A[:10] + SEQ_A[20:30]).encode())


# --- rewrap -----------------------------------------------------------------
def test_rewrap_single_line_to_60() -> None:
    src = tmpfile(f">chr1\n{SEQ_A}\n>chr2\n{SEQ_B}\n")
    dst = src.with_suffix(".wrapped.fa")
    records, bases, issues = R.rewrap(src, dst, 60)
    assert records == 2 and bases == 340
    text = dst.read_text().splitlines()
    assert text[0] == ">chr1"
    assert [len(x) for x in text[1:4]] == [60, 60, 40], [len(x) for x in text[1:4]]
    assert text[4] == ">chr2"
    recs, _ = F.index_fasta(dst)
    assert recs[0].linebases == 60 and recs[0].length == 160


def test_rewrap_preserves_sequence() -> None:
    src = tmpfile(f">c\n{SEQ_B}\n")
    dst = src.with_suffix(".wrapped.fa")
    R.rewrap(src, dst, 60)
    a, _ = F.index_fasta(src)
    b, _ = F.index_fasta(dst)
    with FastaReader(src, a) as ra, FastaReader(dst, b) as rb:
        assert ra.fetch("c", 1, 180) == rb.fetch("c", 1, 180)


def test_rewrap_rejects_overwrite() -> None:
    src = tmpfile(f">c\n{SEQ_A}\n")
    try:
        R.rewrap(src, src, 60)
    except WgdiError:
        return
    raise AssertionError("应当拒绝覆盖源文件")


# --- .len conversion --------------------------------------------------------
def test_fai_to_len() -> None:
    recs = [F.FaiRecord("chr1", 1000, 0, 60, 61), F.FaiRecord("chr2", 2000, 0, 60, 61)]
    text = F.fai_to_len(recs, {"chr1": 12})
    assert text.splitlines()[0] == "chr1\t1000\t12"
    assert text.splitlines()[1] == "chr2\t2000"


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    print(f"FAI 测试：{len(tests)} 项\n")
    for name, fn in tests:
        check(name[5:], fn)
    print(f"\n{PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
