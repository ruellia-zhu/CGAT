"""Core data model. No Qt, no I/O — everything here is plain Python."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Gene:
    """One gene from a WGDI gff. Start/end are 1-based and inclusive."""

    chrom: str
    gene_id: str
    start: int
    end: int
    strand: str
    order: int

    @property
    def midpoint0(self) -> int:
        """0-based midpoint, the coordinate density bins are assigned by."""
        return ((self.start - 1) + (self.end - 1)) // 2

    @property
    def midpoint(self) -> int:
        """1-based inclusive midpoint, the coordinate links attach to."""
        return (self.start + self.end) // 2


@dataclass(frozen=True)
class Chromosome:
    name: str
    length: int
    gene_count: int | None = None


@dataclass
class Genome:
    name: str
    label: str
    chromosomes: list[Chromosome] = field(default_factory=list)
    genes: dict[str, Gene] = field(default_factory=dict)
    by_order: dict[tuple[str, int], Gene] = field(default_factory=dict)

    @property
    def chromosome_names(self) -> list[str]:
        return [c.name for c in self.chromosomes]

    def length_of(self, chrom: str) -> int | None:
        for c in self.chromosomes:
            if c.name == chrom:
                return c.length
        return None

    def chromosome(self, name: str) -> Chromosome | None:
        for c in self.chromosomes:
            if c.name == name:
                return c
        return None

    def gene_count(self, chrom: str) -> int:
        return sum(1 for g in self.genes.values() if g.chrom == chrom)


@dataclass(frozen=True)
class Block:
    """One synteny block from block_information.csv."""

    block_id: str
    rank: int
    chr1: str
    chr2: str
    orders1: tuple[int, ...]
    orders2: tuple[int, ...]
    original_anchors: int = 0
    pvalue: float | None = None
    ks_median: float | None = None


@dataclass(frozen=True)
class AnchorPair:
    """One gene-to-gene link, the actual stroke drawn on the figure."""

    block_id: str
    block_rank: int
    gene1: Gene
    gene2: Gene


@dataclass
class Dataset:
    genome1: Genome
    genome2: Genome
    blocks: list[Block]
    layout: str = "paired"          # "self" | "paired"

    def resolved_counts(self) -> dict[str, int]:
        """Anchors per block that actually resolve to a gene on both sides."""
        counts: dict[str, int] = {}
        for b in self.blocks:
            n = 0
            for o1, o2 in zip(b.orders1, b.orders2):
                if (b.chr1, o1) in self.genome1.by_order and (b.chr2, o2) in self.genome2.by_order:
                    n += 1
            counts[b.block_id] = n
        return counts

    def anchor_pairs(self, min_anchors: int = 1) -> list[AnchorPair]:
        """Pair block1/block2 orders index by index, keeping blocks that pass the threshold."""
        counts = self.resolved_counts()
        out: list[AnchorPair] = []
        for b in self.blocks:
            if counts.get(b.block_id, 0) < min_anchors:
                continue
            for o1, o2 in zip(b.orders1, b.orders2):
                g1 = self.genome1.by_order.get((b.chr1, o1))
                g2 = self.genome2.by_order.get((b.chr2, o2))
                if g1 is None or g2 is None:
                    continue
                out.append(AnchorPair(b.block_id, b.rank, g1, g2))
        out.sort(key=lambda a: (a.block_rank, a.gene1.order, a.gene2.order))
        return out

    def drawable_blocks(self, min_anchors: int = 1) -> list[Block]:
        counts = self.resolved_counts()
        return [b for b in self.blocks if counts.get(b.block_id, 0) >= min_anchors]
