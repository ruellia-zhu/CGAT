"""Sector layout: how chromosome lengths become angles and positions."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .model import Dataset
from .style import LINK_CTRL, LINK_R, LINK_TWIST, START_DEG, Style

_SAFE = re.compile(r"[^A-Za-z0-9_]+")
_DIGITS = re.compile(r"(\d+)$")


def safe_id(value: str) -> str:
    return _SAFE.sub("_", value.strip()).strip("_") or "x"


def chrom_index(name: str, fallback: int) -> int:
    """1-based colour index taken from the trailing digits of a chromosome name."""
    m = _DIGITS.search(name)
    return int(m.group(1)) if m else fallback


@dataclass(frozen=True)
class Sector:
    sid: str
    genome: int
    chrom: str
    length: int
    start_deg: float
    end_deg: float
    color: str            # hex without '#'

    @property
    def mid_deg(self) -> float:
        return (self.start_deg + self.end_deg) / 2.0

    @property
    def label_rotation(self) -> float:
        """Measured from the shipped SVG: svg_rotate = fold(mid - 90)."""
        return 90.0 - (self.mid_deg % 180.0)

    def angle_at(self, bp: int) -> float:
        """Angle for a base-pair position, 0..length."""
        frac = 0.0 if self.length <= 0 else max(0.0, min(1.0, bp / self.length))
        return self.start_deg + (self.end_deg - self.start_deg) * frac

    def angle_of(self, gene_start: int, gene_end: int) -> float:
        """Angle for the midpoint of a 1-based inclusive gene interval."""
        return self.angle_at((gene_start + gene_end) // 2)


def _prefixes(dataset: Dataset) -> tuple[str, str]:
    if dataset.layout == "self":
        return f"{dataset.genome1.name}L", f"{dataset.genome1.name}R"
    return dataset.genome1.name, dataset.genome2.name


def build_sectors(dataset: Dataset, style: Style, colors: list[str]) -> list[Sector]:
    """Lay the genomes around the circle, clockwise from three o'clock."""
    g1, g2 = dataset.genome1, dataset.genome2
    p1, p2 = _prefixes(dataset)
    rows: list[tuple[int, str, str, int]] = []
    for i, c in enumerate(g1.chromosomes):
        rows.append((1, p1, c.name, c.length))
    if dataset.layout == "self":
        for c in g2.chromosomes:
            rows.append((2, p2, c.name, c.length))
    else:
        for c in g2.chromosomes:
            rows.append((2, p2, c.name, c.length))

    n = len(rows)
    total = sum(r[3] for r in rows) or 1
    free = 360.0 - n * style.gap_deg
    if free <= 0:
        raise ValueError("扇区太多、间隙太大，画不下：请调小扇区间隙")

    sectors: list[Sector] = []
    cursor = START_DEG
    for idx, (genome, prefix, chrom, length) in enumerate(rows):
        width = free * length / total
        color = colors[(chrom_index(chrom, idx + 1) - 1) % len(colors)]
        sectors.append(Sector(
            sid=f"{safe_id(prefix)}_{safe_id(chrom)}",
            genome=genome, chrom=chrom, length=length,
            start_deg=cursor, end_deg=cursor + width, color=color,
        ))
        cursor += width + style.gap_deg
    return sectors


def polar(center: tuple[float, float], r: float, deg: float) -> tuple[float, float]:
    """Position at radius `r` and screen angle `deg` (y grows downwards)."""
    t = math.radians(deg)
    return center[0] + r * math.cos(t), center[1] + r * math.sin(t)


def arc_wedge(center, a0, a1, r0, r1, steps: int = 8):
    """Polygon for an annulus wedge, adaptive to its angular width."""
    span = abs(a1 - a0)
    n = max(2, int(min(240, max(steps, span / 1.5))))
    angles = [a0 + (a1 - a0) * i / n for i in range(n + 1)]
    outer = [polar(center, r1, a) for a in angles]
    inner = [polar(center, r0, a) for a in reversed(angles)]
    return outer + inner


def link_controls(center, start_deg, end_deg, radius_mm, slot_radius_mm=None):
    """Four cubic-Bezier control points matching the original figure."""
    r_link = radius_mm * LINK_R
    r_ctrl = (slot_radius_mm if slot_radius_mm is not None else r_link) * LINK_CTRL
    p0 = polar(center, r_link, start_deg)
    p3 = polar(center, r_link, end_deg)
    p1 = polar(center, r_ctrl, start_deg + LINK_TWIST)
    p2 = polar(center, r_ctrl, end_deg - LINK_TWIST)
    return p0, p1, p2, p3
