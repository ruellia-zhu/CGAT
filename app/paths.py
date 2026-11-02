"""Where the sample datasets live.

The program no longer ships next to the analysis folders, so the regression
tools resolve the data root here: environment variable first, then the known
locations, then a folder beside the project.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV = "CGA_DATA"
CANDIDATES = (
    r"W:\2025槐树基因组组装\共线性分析",
    r"E:\ComparativeGenomicsAnalysisTool\sample_data",
    r"D:\2025槐树基因组组装\共线性分析",
)


def data_root() -> Path:
    """Root that contains `circos_plot_v2/` and `06_guohuai_vs_Medicago/`."""
    env = os.environ.get(ENV)
    if env and Path(env).exists():
        return Path(env)
    for candidate in CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return path
    return Path(__file__).resolve().parents[2].parent / "共线性分析"


def exists() -> bool:
    return data_root().exists()
