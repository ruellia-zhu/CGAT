"""Write a Figure to PDF / SVG / PNG / TIFF at an exact physical size."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

FORMATS = {
    "pdf": "pdf",
    "svg": "svg",
    "png": "png",
    "tif": "tiff",
    "tiff": "tiff",
}


def export(fig, path: Path, fmt: str | None = None, dpi: int = 600) -> Path:
    """Save `fig` to `path`. Vector formats keep the physical page size exactly."""
    path = Path(path)
    fmt = (fmt or path.suffix.lstrip(".") or "pdf").lower()
    if fmt not in FORMATS:
        raise ValueError(f"不支持的格式：{fmt}（可选 {', '.join(sorted(set(FORMATS)))}）")
    path.parent.mkdir(parents=True, exist_ok=True)

    kwargs: dict = {"format": FORMATS[fmt]}
    if fmt in ("png", "tif", "tiff"):
        kwargs["dpi"] = dpi
    if fmt in ("tif", "tiff"):
        kwargs["pil_kwargs"] = {"compression": "tiff_lzw"}
    if fmt == "pdf":
        kwargs["metadata"] = {"Creator": "Circos Studio", "Producer": "matplotlib"}
    fig.savefig(path, **kwargs)
    if fmt != "pdf" and fmt != "svg":
        _flatten(path, dpi, lzw=(fmt in ("tif", "tiff")))
    return path


def _flatten(path: Path, dpi: int, lzw: bool) -> None:
    """Raster backends emit RGBA; the journal wants RGB 8-bit on white."""
    im = Image.open(path)
    if im.mode != "RGB":
        rgba = im.convert("RGBA")
        canvas = Image.new("RGB", im.size, "white")
        canvas.paste(rgba, mask=rgba.split()[-1])
        canvas = canvas.convert("RGB")
    else:
        canvas = im.copy()
    extra = {"compression": "tiff_lzw"} if lzw else {}
    canvas.save(path, dpi=(dpi, dpi), **extra)


def export_all(fig, out_dir: Path, stem: str, formats: list[str], dpi: int = 600) -> list[Path]:
    out: list[Path] = []
    for fmt in formats:
        ext = "tiff" if fmt.lower() in ("tif", "tiff") else fmt.lower()
        out.append(export(fig, out_dir / f"{stem}.{ext}", fmt, dpi))
    return out
