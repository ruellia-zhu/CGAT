"""Figure style: every knob the renderer needs, plus the default and auto presets."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace

# --- geometry constants recovered from the shipped Circos figure -------------
# All radii are multiples of R (the circle radius); R itself is page_width * RATIO.
RATIO = 0.39972
BAND_R = (0.865, 0.918)
DENSITY_R = (0.928, 0.995)
LINK_R = 0.850
LABEL_R = 1.0257
LINK_CTRL = 0.372            # control-point radius, x link radius
LINK_TWIST = 2.0             # degrees added/subtracted at each end
START_DEG = 0.0              # first sector starts at 3 o'clock
TITLE_BAND_PX = 130.0        # of a 3200 px wide design canvas
TITLE_Y_PX = 100.0

REFERENCE_WIDTH_MM = 50.0    # the page size all point sizes were tuned against


@dataclass(frozen=True)
class Style:
    """A frozen bag of drawing parameters. Use `replace()` to derive variants."""

    page_w_mm: float = 50.0
    page_h_mm: float = 52.03125
    dpi: int = 600

    palette: str = "paper1"
    background: str = "white"

    gap_deg: float = 2.16
    link_width_px: float = 0.7      # in 3200-px design units, like Circos' "0.7p"
    link_alpha: float = 1.0
    label_pt: float = 2.126
    title_pt: float = 4.43
    band_stroke_px: float = 2.25

    show_title: bool = True
    show_labels: bool = True
    show_density: bool = True
    title: str = ""

    density_window: int = 1_000_000
    density_max: float | None = None   # None = derive from data
    min_anchors: int = 50

    # --- derived geometry ---------------------------------------------------
    @property
    def px_per_mm(self) -> float:
        return 3200.0 / self.page_w_mm

    @property
    def scale(self) -> float:
        """Convert a reference point size (tuned at 50 mm) to this page width."""
        return self.page_w_mm / REFERENCE_WIDTH_MM

    @property
    def title_band_mm(self) -> float:
        return TITLE_BAND_PX / self.px_per_mm

    @property
    def center(self) -> tuple[float, float]:
        return self.page_w_mm / 2.0, (self.page_h_mm + self.title_band_mm) / 2.0

    @property
    def radius_mm(self) -> float:
        return self.page_w_mm * RATIO

    def mm(self, px: float) -> float:
        """Design pixels (3200-wide canvas) to millimetres."""
        return px / self.px_per_mm

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Style":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def default() -> Style:
    """The published look: 50 × 52.03 mm, paper palette 1, 2.126 pt labels."""
    return Style()


def auto(n_sectors: int, n_links: int, palette: str = "paper1") -> Style:
    """Fit the styling to the data instead of asking the user to tune it.

    Three rules, all monotone and clamped so nothing degenerates:

    * labels shrink as sectors multiply  (28 sectors -> 2.126 pt)
    * gaps shrink as sectors multiply    (so chromosomes keep their arc length)
    * links thin out as links multiply   (46k lines otherwise flood the centre)
    """
    n_sectors = max(1, n_sectors)
    n_links = max(1, n_links)
    label_pt = 2.126 * math.sqrt(28.0 / n_sectors)
    gap_deg = 2.16 * (28.0 / n_sectors)
    width_px = 0.7 * (15_000.0 / n_links) ** 0.25
    return replace(
        default(),
        palette=palette,
        label_pt=round(min(3.2, max(1.5, label_pt)), 3),
        gap_deg=round(min(4.0, max(1.1, gap_deg)), 3),
        link_width_px=round(min(1.2, max(0.45, width_px)), 3),
    )
