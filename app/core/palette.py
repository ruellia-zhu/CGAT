"""Colour palette registry for the Circos figure.

Every palette is a plain list of hex strings.  Palettes with fewer colours than
there are sectors are extended by blending successive cycles toward white, so a
14-chromosome genome still gets 14 distinguishable swatches.

Sources are cited per palette; do not "improve" a published palette in place —
add a new key instead, so old figures stay reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    key: str
    label: str
    colors: tuple[str, ...]
    source: str
    note: str = ""
    colorblind_safe: bool = False
    for_links: bool = True          # suitable for thin link strokes


# --- the paper's own boards -------------------------------------------------
PAPER_1 = ("4F587D", "C68DC0", "C2E0EE", "A89CC9", "D8C6EA", "4A6FD3", "6EA8E6",
           "FFE5A3", "FFB07A", "FF7F7A", "B7D8F7", "A7E1F7", "FFE0EC", "FF9BC5")
PAPER_2 = ("FFD6E7", "FFB6D5", "F7A1C4", "E6F3FF", "CDEBFA", "B3E5FC", "9EDBF5",
           "81D4FA", "90CAF9", "B0BEC5", "A7C7E7", "7FB3F0", "4D90FE", "E8F0FB",
           "FCE4EC")
PAPER_3 = ("D9F0FA", "EDE7F6", "C7D6E6", "8FB7E3", "FFD1E1", "BDBDBD", "D0D0D0",
           "E5E5E5", "F8BBD0", "90A4AE", "B3E5FC")


PALETTES: dict[str, Palette] = {
    "paper1": Palette(
        "paper1", "论文配色板 1", PAPER_1,
        "论文排版与格式约定.md §1.2.1",
        "论文默认，柔和；其中 5 个颜色很浅，细线不醒目",
    ),
    "paper2": Palette(
        "paper2", "论文配色板 2", PAPER_2,
        "论文排版与格式约定.md §1.2.2",
        "约定里是给热图用的，粉蓝渐层，慎用于离散染色体",
        for_links=False,
    ),
    "paper1_cvd": Palette(
        "paper1_cvd", "论文配色板 1 · 色盲加固", (
            "4F587D", "C68DC0", "C2E0EE", "A89CC9", "D8C6EA", "4A6FD3", "6EA8E6",
            "FFE5A3", "FFB07A", "FF7F7A", "B7D8F7", "5FB8D8", "FFE0EC", "FF9BC5",
        ),
        "论文配色板 1，仅把 12 号 #A7E1F7 换成 #5FB8D8",
        "与已发表图差异最小（只改 1 色）；相邻 ΔE 色盲 1.7 → 13.2",
        colorblind_safe=True,
    ),
    "paper3": Palette(
        "paper3", "论文配色板 3", PAPER_3,
        "论文排版与格式约定.md §1.2.2",
        "备用板，含较多灰阶；只适合点缀",
        for_links=False,
    ),
    "okabe_ito": Palette(
        "okabe_ito", "Okabe–Ito 色盲安全", (
            "0072B2", "D55E00", "009E73", "CC79A7",
            "E69F00", "56B4E9", "F0E442",
        ),
        "Okabe & Ito, 2008, Color Universal Design",
        "色盲友好的事实标准；黑色留给文字轴，出图时跳过",
        colorblind_safe=True,
    ),
    "tol_muted": Palette(
        "tol_muted", "Paul Tol Muted", (
            "332288", "88CCEE", "44AA99", "117733", "999933",
            "DDCC77", "CC6677", "882255", "AA4499",
        ),
        "Paul Tol, SRON, Technical Note 2012",
        "低饱和但分得开，Nature/Science 图里常见",
        colorblind_safe=True,
    ),
    "tol_bright": Palette(
        "tol_bright", "Paul Tol Bright", (
            "4477AA", "EE6677", "228833", "CCBB44", "66CCEE", "AA3377", "BBBBBB",
        ),
        "Paul Tol, SRON, Technical Note 2012",
        "亮度更均匀，适合黑白打印",
        colorblind_safe=True,
    ),
    "brewer_paired": Palette(
        "brewer_paired", "ColorBrewer Paired", (
            "A6CEE3", "1F78B4", "B2DF8A", "33A02C", "FB9A99", "E31A1C",
            "FDBF6F", "FF7F00", "CAB2D6", "6A3D9A", "FFFF99", "B15928",
        ),
        "ColorBrewer 2.0, Cynthia Brewer",
        "成对深浅，天然契合「自比较」L/R 两套扇区",
    ),
    "brewer_set3": Palette(
        "brewer_set3", "ColorBrewer Set3", (
            "8DD3C7", "FFFFB3", "BEBADA", "FB8072", "80B1D3", "FDB462",
            "B3DE69", "FCCDE5", "D9D9D9", "BC80BD", "CCEBC5", "FFED6F",
        ),
        "ColorBrewer 2.0, Cynthia Brewer",
        "柔和的 12 色，气质最接近论文板 1",
    ),
    "npg": Palette(
        "npg", "Nature (ggsci NPG)", (
            "E64B35", "4DBBD5", "00A087", "3C5488", "F39B7F",
            "8491B4", "91D1C2", "DC0000", "7E6148", "B09C85",
        ),
        "ggsci::pal_npg, 源自 Nature 期刊插图",
        "饱和、对比强，色盲友好度一般",
    ),
    "tableau20": Palette(
        "tableau20", "Tableau 20", (
            "4E79A7", "A0CBE8", "F28E2B", "FFBE7D", "59A14F", "8CD17D",
            "B6992D", "F1CE63", "499894", "86BCB6", "E15759", "FF9D9A",
            "79706E", "BAB0AC", "D37295", "FABFD2", "B07AA1", "D4A6C8",
            "9D7660", "D7B5A6",
        ),
        "Tableau 10/20 分类色（Tableau 官方）",
        "深浅交替，20 类也不挤；通用性最好",
    ),
    "kelly": Palette(
        "kelly", "Kelly 最大对比 22 色", (
            "F3C300", "875692", "F38400", "A1CAF1", "BE0032", "C2B280",
            "848482", "008856", "E68FAC", "0067A5", "F99379", "604E97",
            "F6A600", "B3446C", "DCD300", "882D17", "8DB600", "654522",
            "E25822", "2B3D26",
        ),
        "Kelly, 1965, Color Eng. 3(6):22-25",
        "为「尽可能多类别」设计；色相跳跃大，近看略刺眼",
    ),
}

DEFAULT = "paper1"

# Presentation order in the UI: the paper boards first, then the alternatives.
ORDER = ("paper1", "paper1_cvd", "paper2", "paper3", "okabe_ito", "tol_muted",
         "tol_bright", "brewer_paired", "brewer_set3", "npg", "tableau20", "kelly")


def get(key: str) -> Palette:
    return PALETTES.get(key, PALETTES[DEFAULT])


def all_palettes() -> list[Palette]:
    return [PALETTES[k] for k in ORDER if k in PALETTES]


# --- helpers ----------------------------------------------------------------
def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def blend(color: str, target: str, t: float) -> str:
    """Mix `color` toward `target`; t=0 keeps color, t=1 gives target."""
    a, b = hex_to_rgb(color), hex_to_rgb(target)
    return rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def luminance(color: str) -> float:
    """Relative luminance per WCAG 2.1."""
    def lin(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = hex_to_rgb(color)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast_with_white(color: str) -> float:
    return (1.05) / (luminance(color) + 0.05)


def expand(palette: Palette | str, n: int) -> list[str]:
    """Return exactly `n` colours, cycling and lightening when the board is short."""
    p = get(palette) if isinstance(palette, str) else palette
    colors = list(p.colors)
    if n <= len(colors):
        return colors[:n]
    out = list(colors)
    cycle = 1
    while len(out) < n:
        for c in colors:
            if len(out) >= n:
                break
            out.append(blend(c, "FFFFFF", min(0.55, 0.26 * cycle)))
        cycle += 1
    return out


def link_colors(palette: Palette | str, n: int) -> list[str]:
    """Colours for thin link strokes.

    Very pale boards are darkened toward the ink colour so a 0.34 px stroke
    still reads; the hue relationship between chromosomes is preserved.
    """
    p = get(palette) if isinstance(palette, str) else palette
    base = expand(p, n)
    if p.for_links:
        return base
    return [blend(c, "1C1C1E", 0.28) for c in base]
