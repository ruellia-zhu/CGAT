"""Render one dataset from its three WGDI inputs.

python tools/render_cli.py --gff1 A.gff --len1 A.len --blocks B.csv \
       [--gff2 B.gff --len2 B.len] [--layout self|paired] [--auto] \
       --out out.pdf [--palette paper1] [--format pdf]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import style as style_mod  # noqa: E402
from app.core import wgdi  # noqa: E402
from app.render import export as export_mod  # noqa: E402
from app.render import figure as figure_mod  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="用 WGDI 结果渲染一张共线性 Circos 图")
    ap.add_argument("--gff1", type=Path, required=True)
    ap.add_argument("--len1", type=Path, required=True)
    ap.add_argument("--gff2", type=Path)
    ap.add_argument("--len2", type=Path)
    ap.add_argument("--blocks", type=Path, required=True)
    ap.add_argument("--layout", choices=("self", "paired"), default="self")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--format", default=None)
    ap.add_argument("--palette", default="paper1")
    ap.add_argument("--dpi", type=int, default=600)
    ap.add_argument("--auto", action="store_true", help="按数据规模自动调整样式")
    ap.add_argument("--min-anchors", type=int, default=50)
    ap.add_argument("--title", default="")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    t0 = time.perf_counter()
    dataset, issues = wgdi.load_dataset(
        gff1=args.gff1, len1=args.len1, blocks_csv=args.blocks,
        gff2=args.gff2, len2=args.len2, layout=args.layout,
    )
    t_parse = time.perf_counter() - t0

    pairs = dataset.anchor_pairs(args.min_anchors)
    sectors = len(dataset.genome1.chromosomes) * (2 if args.layout == "self" else 1)
    if args.layout == "paired":
        sectors += len(dataset.genome2.chromosomes)

    style = (style_mod.auto(sectors, len(pairs), args.palette) if args.auto
             else style_mod.default())
    style = style_mod.replace(style, min_anchors=args.min_anchors, title=args.title)

    t1 = time.perf_counter()
    fig = figure_mod.build_figure(dataset, style)
    t_draw = time.perf_counter() - t1

    t2 = time.perf_counter()
    path = export_mod.export(fig, args.out, args.format, args.dpi)
    t_save = time.perf_counter() - t2
    figure_mod.close(fig)

    if not args.quiet:
        stats = dict(genes1=len(dataset.genome1.genes), genes2=len(dataset.genome2.genes),
                     blocks=len(dataset.blocks), kept=len(dataset.drawable_blocks(args.min_anchors)),
                     sectors=sectors, links=len(pairs), issues=len(issues))
        print(f"解析 {t_parse:.2f}s  绘制 {t_draw:.2f}s  导出 {t_save:.2f}s")
        print(f"基因 {stats['genes1']:,}/{stats['genes2']:,}  块 {stats['blocks']:,}"
              f"（保留 {stats['kept']:,}）扇区 {stats['sectors']}  连线 {stats['links']:,}")
        print(f"样式: 标签 {style.label_pt}pt 间隙 {style.gap_deg}° 线宽 {style.link_width_px}"
              f" 配色 {style.palette}")
        for i in issues[:5]:
            print("  ", i)
        size = path.stat().st_size
        print(f"-> {path}  {size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
