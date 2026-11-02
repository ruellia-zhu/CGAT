"""Gene density along each chromosome, the ring of bars outside the ideograms."""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from .model import Genome

DEFAULT_WINDOW = 1_000_000


@dataclass(frozen=True)
class DensityBin:
    chrom: str
    start: int          # 0-based
    end: int            # exclusive
    genes: int
    per_mb: float

    @property
    def width(self) -> int:
        return self.end - self.start


def gene_density(genome: Genome, window: int = DEFAULT_WINDOW) -> list[DensityBin]:
    """Non-overlapping windows; the last one is shortened and scaled to its real width."""
    if window <= 0:
        raise ValueError("窗口长度必须为正数")
    midpoints: dict[str, list[int]] = {c.name: [] for c in genome.chromosomes}
    for gene in genome.genes.values():
        bucket = midpoints.get(gene.chrom)
        if bucket is not None:
            bucket.append(gene.midpoint0)
    for bucket in midpoints.values():
        bucket.sort()

    out: list[DensityBin] = []
    for chrom in genome.chromosomes:
        points = midpoints.get(chrom.name) or []
        pos = 0
        while pos < chrom.length:
            end = min(pos + window, chrom.length)
            n = bisect_right(points, end - 1) - bisect_left(points, pos)
            out.append(DensityBin(chrom.name, pos, end, n, n * 1_000_000 / (end - pos)))
            pos = end
    return out


def density_max(bins: list[DensityBin]) -> float:
    return max((b.per_mb for b in bins), default=0.0)


def nice_max(value: float, step: float = 10.0) -> float:
    """Round a maximum up to a friendly axis limit, so every figure shares one scale."""
    if value <= 0:
        return step
    return math.ceil(value / step) * step
