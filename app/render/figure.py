"""Build a matplotlib Figure for a Dataset. Pure drawing, no Qt."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
# Journals want embeddable TrueType fonts, and an editable SVG should keep text
# as text instead of converting every label to outlines.
matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42
matplotlib.rcParams["svg.fonttype"] = "none"
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import PathCollection, PolyCollection  # noqa: E402
from matplotlib.path import Path  # noqa: E402

from ..core import density as density_mod  # noqa: E402
from ..core import palette as palette_mod  # noqa: E402
from ..core.layout import (  # noqa: E402
    Sector, arc_wedge, build_sectors, link_controls, polar,
)
from ..core.model import Dataset  # noqa: E402
from ..core.style import BAND_R, DENSITY_R, LABEL_R, Style  # noqa: E402

MOVE, CURVE = Path.MOVETO, Path.CURVE4


def _colour_count(dataset: Dataset) -> int:
    from ..core.layout import chrom_index

    best = 1
    for genome in (dataset.genome1, dataset.genome2):
        for i, c in enumerate(genome.chromosomes):
            best = max(best, chrom_index(c.name, i + 1))
    return best


def prepare(dataset: Dataset, style: Style):
    """Resolve colours, sectors and density once; cheap to reuse across redraws."""
    n_colours = _colour_count(dataset)
    pal = palette_mod.get(style.palette)
    colors = palette_mod.expand(pal, n_colours)
    link_colors = palette_mod.link_colors(pal, n_colours)

    sectors = build_sectors(dataset, style, colors)
    by_key = {(s.genome, s.chrom): s for s in sectors}

    # density: compute once per distinct genome object
    bins_by_genome: dict[int, dict[str, list]] = {}
    all_bins = []
    for idx, genome in ((1, dataset.genome1), (2, dataset.genome2)):
        if idx == 2 and genome is dataset.genome1:
            bins_by_genome[2] = bins_by_genome[1]
            continue
        grouped: dict[str, list] = {}
        for b in density_mod.gene_density(genome, style.density_window):
            grouped.setdefault(b.chrom, []).append(b)
        bins_by_genome[idx] = grouped
        all_bins.extend(b for buckets in grouped.values() for b in buckets)

    peak = density_mod.density_max(all_bins)
    top = style.density_max if style.density_max else density_mod.nice_max(peak)
    return dict(colors=colors, link_colors=link_colors, sectors=sectors, by_key=by_key,
                bins=bins_by_genome, peak=peak, top=max(1.0, top))


def build_figure(dataset: Dataset, style: Style, *, dpi: int | None = None,
                 subsample: int = 1, title: str | None = None) -> plt.Figure:
    """Draw everything. `subsample` > 1 draws only every Nth link (for previews)."""
    prepared = prepare(dataset, style)
    sectors: list[Sector] = prepared["sectors"]
    by_key = prepared["by_key"]
    colors = prepared["colors"]
    link_colors = prepared["link_colors"]
    bins = prepared["bins"]
    top = prepared["top"]

    fig = plt.figure(figsize=(style.page_w_mm / 25.4, style.page_h_mm / 25.4),
                     dpi=dpi or style.dpi)
    ax = fig.add_axes([0, 0, 1, 1], frameon=False)
    ax.set_facecolor(style.background)
    fig.patch.set_facecolor(style.background)
    ax.set_xlim(0, style.page_w_mm)
    ax.set_ylim(style.page_h_mm, 0)          # image coordinates: y grows downwards
    ax.set_aspect("equal")
    ax.set_axis_off()

    cx, cy = style.center
    R = style.radius_mm

    # --- chromosome bands ---------------------------------------------------
    polys, faces = [], []
    for s in sectors:
        polys.append(arc_wedge((cx, cy), s.start_deg, s.end_deg,
                               BAND_R[0] * R, BAND_R[1] * R))
        faces.append("#" + s.color)
    if polys:
        ax.add_collection(PolyCollection(
            polys, facecolors=faces, edgecolors="white",
            linewidths=style.mm(style.band_stroke_px) * 72 / 25.4, antialiaseds=True))

    # --- gene density ring --------------------------------------------------
    if style.show_density:
        polys, faces = [], []
        r0 = DENSITY_R[0] * R
        for s in sectors:
            for b in bins.get(s.genome, {}).get(s.chrom, ()):  # type: ignore[union-attr]
                a0 = s.angle_at(b.start)
                a1 = s.angle_at(b.end)
                if a1 <= a0:
                    continue
                h = min(b.per_mb, top) / top
                polys.append(arc_wedge((cx, cy), a0, a1, r0, r0 + (DENSITY_R[1] - DENSITY_R[0]) * R * h, steps=3))
                faces.append("#" + s.color)
        if polys:
            ax.add_collection(PolyCollection(polys, facecolors=faces, edgecolors="none",
                                             linewidths=0, antialiaseds=True))

    # --- links --------------------------------------------------------------
    pairs = dataset.anchor_pairs(style.min_anchors)
    if subsample > 1:
        pairs = pairs[::subsample]
    buckets: dict[str, list[list[float]]] = {}
    skipped = 0
    for p in pairs:
        s1 = by_key.get((1, p.gene1.chrom))
        s2 = by_key.get((2, p.gene2.chrom))
        if s1 is None or s2 is None:
            skipped += 1
            continue
        a1 = s1.angle_of(p.gene1.start, p.gene1.end)
        a2 = s2.angle_of(p.gene2.start, p.gene2.end)
        p0, p1, p2, p3 = link_controls((cx, cy), a1, a2, R)
        buckets.setdefault(s2.color, []).extend(
            (p0[0], p0[1], p1[0], p1[1], p2[0], p2[1], p3[0], p3[1]))

    width_pt = style.mm(style.link_width_px) * 72 / 25.4
    for color, flat in buckets.items():
        verts = np.asarray(flat, dtype=float).reshape(-1, 2)
        codes = np.zeros(len(verts), dtype=np.uint8)
        codes[0::4] = MOVE
        codes[1::4] = CURVE
        codes[2::4] = CURVE
        codes[3::4] = CURVE
        idx = _colour_index(colors, color)
        rgb = palette_mod.hex_to_rgb(link_colors[idx % len(link_colors)])
        ax.add_collection(PathCollection(
            [Path(verts, codes)], facecolors="none",
            edgecolors=[(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, style.link_alpha)],
            linewidths=width_pt, antialiaseds=True))

    # --- labels -------------------------------------------------------------
    if style.show_labels:
        for s in sectors:
            x, y = polar((cx, cy), LABEL_R * R, s.mid_deg)
            ax.text(x, y, s.chrom, fontsize=style.label_pt * style.scale,
                    family="Arial", ha="center", va="center",
                    rotation=s.label_rotation, rotation_mode="anchor", color="black")

    # --- title --------------------------------------------------------------
    text = title if title is not None else (style.title or _default_title(dataset))
    if style.show_title and text:
        ax.text(cx, style.mm(100.0), text, fontsize=style.title_pt * style.scale,
                family="Arial", ha="center", va="center", color="#222222")

    fig._circos_stats = {  # type: ignore[attr-defined]
        "sectors": len(sectors),
        "links": len(pairs) - skipped,
        "skipped": skipped,
        "density_peak": prepared["peak"],
        "density_top": top,
        "palette": style.palette,
    }
    return fig


def _colour_index(colors: list[str], color: str) -> int:
    try:
        return colors.index(color)
    except ValueError:
        return 0


def _default_title(dataset: Dataset) -> str:
    if dataset.layout == "self":
        return f"{dataset.genome1.name} \u2013 {dataset.genome1.name}"
    return f"{dataset.genome1.name} \u2013 {dataset.genome2.name}"


def close(fig) -> None:
    plt.close(fig)
