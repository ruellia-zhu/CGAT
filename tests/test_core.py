"""Edge-case tests for the data layer (no pytest needed).

Run:  ..\\circos_dev\\.venv\\Scripts\\python.exe tests\\test_core.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.paths import data_root  # noqa: E402
sys.path.insert(0, str(ROOT))

from app.core import density as D  # noqa: E402
from app.core import wgdi  # noqa: E402
from app.core.model import Block, Chromosome, Gene, Genome  # noqa: E402

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


def tmp(text: str, suffix: str) -> Path:
    f = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8", newline="")
    f.write(text)
    f.close()
    return Path(f.name)


def expect_error(fn, needle: str = "") -> None:
    try:
        fn()
    except wgdi.WgdiError as exc:
        if needle:
            assert needle in str(exc), f"报错信息里没有 {needle!r}：{exc}"
        return
    raise AssertionError("本应抛出 WgdiError，但没有")


# --- .len -------------------------------------------------------------------
def test_len_basic() -> None:
    p = tmp("chr1\t1000\t10\nchr2 2000 20\n\n# comment\n", ".len")
    g, issues = wgdi.read_len(p, "A")
    assert [c.name for c in g.chromosomes] == ["chr1", "chr2"]
    assert g.chromosomes[1].length == 2000
    assert g.chromosomes[0].gene_count == 10
    assert not issues


def test_len_bad_rows() -> None:
    p = tmp("chr1\tnotanumber\nchr2\t500\nchr3\t-5\n", ".len")
    g, issues = wgdi.read_len(p, "A")
    assert [c.name for c in g.chromosomes] == ["chr2"]
    assert len(issues) == 2


def test_len_empty_is_fatal() -> None:
    p = tmp("# nothing here\n", ".len")
    expect_error(lambda: wgdi.read_len(p, "A"), "没有任何可用")


# --- .gff -------------------------------------------------------------------
LEN = "chr1\t100000\nchr2\t50000\n"


def _genome_with(chroms=("chr1", "chr2")) -> Genome:
    return Genome(name="A", label="A",
                  chromosomes=[Chromosome(c, 100000 if c == "chr1" else 50000) for c in chroms])


def test_gff_parses_and_keeps_order() -> None:
    p = tmp("chr1\tg1\t100\t200\t+\t1\tt1\nchr1\tg2\t300\t400\t-\t2\tt2\n", ".gff")
    g = _genome_with()
    issues = wgdi.read_gff(g, p)
    assert not issues
    assert g.by_order[("chr1", 2)].gene_id == "g2"
    assert g.genes["g1"].start == 100


def test_gff_out_of_range_is_skipped() -> None:
    p = tmp("chr1\tg1\t100\t200\t+\t1\tt1\nchr1\tg2\t99000\t120000\t+\t2\tt2\n", ".gff")
    g = _genome_with()
    issues = wgdi.read_gff(g, p)
    assert len(g.genes) == 1
    assert any("超出染色体长度" in i.message for i in issues)


def test_gff_swapped_coordinates_are_fixed() -> None:
    p = tmp("chr1\tg1\t300\t100\t+\t1\tt1\n", ".gff")
    g = _genome_with()
    wgdi.read_gff(g, p)
    assert g.genes["g1"].start == 100 and g.genes["g1"].end == 300


def test_gff_duplicates_are_warned() -> None:
    p = tmp("chr1\tg1\t100\t200\t+\t1\nchr1\tg1\t300\t400\t+\t2\nchr1\tg2\t500\t600\t+\t1\n", ".gff")
    g = _genome_with()
    issues = wgdi.read_gff(g, p)
    assert len(g.genes) == 1, f"重复 ID / 重复顺序号都应被拒收，实际留下 {list(g.genes)}"
    assert sum(1 for i in issues if i.level == "warning") >= 2


def test_gff_too_few_columns() -> None:
    p = tmp("chr1\tg1\t100\t200\t+\nchr1\tg2\t300\t400\t-\t1\n", ".gff")
    g = _genome_with()
    issues = wgdi.read_gff(g, p)
    assert len(g.genes) == 1
    assert any("少于 6 列" in i.message for i in issues)


def test_gff_scaffold_is_skipped_silently() -> None:
    p = tmp("chr1\tg1\t100\t200\t+\t1\nscaffold_9\tg9\t100\t200\t+\t1\n", ".gff")
    g = _genome_with()
    issues = wgdi.read_gff(g, p)
    assert len(g.genes) == 1
    assert not any("scaffold" in i.message for i in issues)


def test_gff_no_genes_is_fatal() -> None:
    p = tmp("chrZ\tg1\t100\t200\t+\t1\n", ".gff")
    g = _genome_with(("chr1",))
    expect_error(lambda: wgdi.read_gff(g, p), "没有解析出任何基因")


# --- block_information.csv --------------------------------------------------
CSV_OK = "id,chr1,chr2,block1,block2,length\n1,chr1,chr2,1_2_3,4_5_6,3\n2,chr1,chr1,7_8,9_10,2\n"


def test_blocks_basic() -> None:
    blocks, issues = wgdi.read_blocks(tmp(CSV_OK, ".csv"))
    assert len(blocks) == 2
    assert blocks[0].orders1 == (1, 2, 3)
    assert blocks[0].chr2 == "chr2"
    assert not issues


def test_blocks_missing_column_is_fatal() -> None:
    p = tmp("id,chr1,chr2,anchors\n1,chr1,chr2,x\n", ".csv")
    expect_error(lambda: wgdi.read_blocks(p), "缺少必需列")


def test_blocks_length_mismatch_warns() -> None:
    p = tmp("id,chr1,chr2,block1,block2\n1,chr1,chr2,1_2_3,4_5\n", ".csv")
    blocks, issues = wgdi.read_blocks(p)
    assert any("按较短的配对" in i.message for i in issues)
    assert blocks[0].orders2 == (4, 5)


def test_blocks_reject_tab_separated() -> None:
    p = tmp("id\tchr1\tchr2\tblock1\tblock2\n1\tchr1\tchr2\t1\t2\n", ".csv")
    expect_error(lambda: wgdi.read_blocks(p), "不是逗号分隔")


# --- density ----------------------------------------------------------------
def test_density_large_and_fast() -> None:
    g = Genome(name="A", label="A", chromosomes=[Chromosome("chr1", 1_500_000)])
    for i in range(3):
        g.genes[f"g{i}"] = Gene("chr1", f"g{i}", 100 + i * 10, 110 + i * 10, "+", i + 1)
    g.genes["g3"] = Gene("chr1", "g3", 1_100_000, 1_100_010, "+", 99)
    g.by_order = {(v.chrom, v.order): v for v in g.genes.values()}
    bins = D.gene_density(g)
    assert len(bins) == 2, bins
    assert bins[0].genes == 3 and abs(bins[0].per_mb - 3.0) < 1e-9
    assert bins[1].end == 1_500_000
    # last window is only 500 kb wide: 1 gene must be scaled to 2 genes/Mb
    assert bins[1].genes == 1 and abs(bins[1].per_mb - 2.0) < 1e-9


def test_density_matches_reference_peak() -> None:
    """The published maximum was 706 genes/Mb in dataset 03."""
    data = data_root() / "circos_plot_v2" / "data" / "03_Cwilsonii_vs_Cwilsonii"
    ds, _ = wgdi.load_dataset(data / "genome1.gff", data / "genome1.len",
                              data / "original_block_information.csv", layout="self")
    peak = D.density_max(D.gene_density(ds.genome1))
    assert abs(peak - 706.0) < 0.5, f"峰值应为 706，实际 {peak}"


def test_density_nice_max() -> None:
    assert D.nice_max(706.0) == 710.0
    assert D.nice_max(0.0) == 10.0
    assert D.nice_max(700.0) == 700.0


# --- pairing semantics ------------------------------------------------------
def test_anchor_pairing_uses_min_length_and_skips_missing() -> None:
    g1 = Genome(name="A", label="A", chromosomes=[Chromosome("chr1", 1000)])
    g2 = Genome(name="B", label="B", chromosomes=[Chromosome("chr2", 1000)])
    for o in (1, 2, 3):
        gene = Gene("chr1", f"a{o}", o * 10, o * 10 + 5, "+", o)
        g1.genes[gene.gene_id] = gene
        g1.by_order[("chr1", o)] = gene
    for o in (5, 6):
        gene = Gene("chr2", f"b{o}", o * 10, o * 10 + 5, "+", o)
        g2.genes[gene.gene_id] = gene
        g2.by_order[("chr2", o)] = gene
    block = Block("1", 1, "chr1", "chr2", (1, 2, 3), (5, 6), original_anchors=3)
    from app.core.model import Dataset

    ds = Dataset(g1, g2, [block], "paired")
    pairs = ds.anchor_pairs(1)
    assert len(pairs) == 2, pairs
    assert [p.gene1.order for p in pairs] == [1, 2]
    assert ds.resolved_counts()["1"] == 2


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    print(f"数据层测试：{len(tests)} 项\n")
    for name, fn in tests:
        check(name[5:], fn)
    print(f"\n{PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
