"""Project folder: inputs, parameters, step state and intermediate files.

One folder per analysis, everything relative to it so it can be moved or copied::

    <root>/project.json
    <root>/prepared/   A.gff A.len A.fai A.wgdi.pep.fasta A.wgdi.cds.fasta [A.fa]
    <root>/work/       total.conf, *.blastp.txt, chunks, *.collinearity.txt, *.ks, *.png
    <root>/logs/       01_prep.log ...
    <root>/results/    Circos PDF/SVG/PNG/TIFF
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..core.issues import WgdiError
from .conf import WgdiParams

SCHEMA = 2
STEPS = (
    ("prep", "预处理"),
    ("blastdb", "建库"),
    ("blast", "序列比对"),
    ("dotplot", "点阵图"),
    ("collinearity", "共线性"),
    ("ks", "Ks 计算"),
    ("blockinfo", "块汇总"),
    ("blockks", "Ks 点阵"),
    ("kspeaks", "Ks 分布"),
    ("circos", "Circos 图"),
)
STEP_TITLE = dict(STEPS)


def default_threads() -> int:
    import os

    cpu = os.cpu_count() or 4
    return max(1, min(8, cpu))


@dataclass
class Filters:
    """How sequences are kept when the WGDI inputs are built."""

    chromosomes_only: bool = True
    extra_exclude: str = ""
    strip_prefix: str = ""

    def exclude_pattern(self):
        """Compiled regex of what to drop, or None to keep everything."""
        import re

        if not self.chromosomes_only and not self.extra_exclude.strip():
            return None
        from ..prep.build import DEFAULT_EXCLUDE

        parts = []
        if self.chromosomes_only:
            parts.append(DEFAULT_EXCLUDE.pattern)
        if self.extra_exclude.strip():
            parts.append(self.extra_exclude.strip())
        return re.compile("|".join(f"(?:{p})" for p in parts), re.I)


@dataclass
class BlastInput:
    """Where the alignment table comes from."""

    source: str = "run"          # "run" | "upload"
    uploaded: str | None = None  # original path, kept for the log



@dataclass
class GenomeInput:
    """One side of the comparison."""

    prefix: str = "A"
    mode: str = "auto"          # "auto" = genome+GFF, "manual" = fai+CDS+protein+GFF
    genome: str | None = None   # auto only
    gff: str | None = None
    pep: str | None = None
    cds: str | None = None
    fai: str | None = None
    display_name: str = ""

    def files(self) -> dict[str, str]:
        return {k: v for k, v in asdict(self).items() if isinstance(v, str) and v}


@dataclass
class Project:
    root: Path
    name: str = ""
    genome_a: GenomeInput = field(default_factory=lambda: GenomeInput("A"))
    genome_b: GenomeInput | None = None
    self_compare: bool = True
    engine: str = "blastp"                 # "blastp" | "diamond"
    threads: int = field(default_factory=default_threads)
    params: WgdiParams = field(default_factory=WgdiParams)
    filters: Filters = field(default_factory=Filters)
    blast_input: BlastInput = field(default_factory=BlastInput)
    steps: dict[str, dict] = field(default_factory=dict)
    app_version: str = ""
    created: float = field(default_factory=time.time)

    # --- paths ----------------------------------------------------------
    @property
    def prepared(self) -> Path:
        return self.root / "prepared"

    @property
    def work(self) -> Path:
        return self.root / "work"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def results(self) -> Path:
        return self.root / "results"

    @property
    def stem(self) -> str:
        a = self.genome_a.prefix or "A"
        b = a if self.self_compare or self.genome_b is None else (self.genome_b.prefix or "B")
        return f"{a}-{b}"

    def prepare_dirs(self) -> None:
        for d in (self.prepared, self.work, self.logs, self.results):
            d.mkdir(parents=True, exist_ok=True)

    # --- state ----------------------------------------------------------
    def step_state(self, key: str) -> str:
        return self.steps.get(key, {}).get("state", "pending")

    def set_step(self, key: str, state: str, **extra) -> None:
        entry = self.steps.setdefault(key, {})
        entry.update(extra)
        entry["state"] = state
        entry["updated"] = time.time()

    def reset_from(self, key: str) -> None:
        keys = [k for k, _ in STEPS]
        if key in keys:
            for k in keys[keys.index(key):]:
                self.steps.pop(k, None)

    def is_done(self, key: str) -> bool:
        return self.step_state(key) == "done"

    def step_detail(self, key: str) -> dict:
        return dict(self.steps.get(key, {}).get("detail", {}))

    def set_detail(self, key: str, detail: dict) -> None:
        self.steps.setdefault(key, {})["detail"] = detail

    def downstream_dirty(self, key: str) -> list[str]:
        """Steps after `key` that already have a result and would go stale."""
        keys = [k for k, _ in STEPS]
        if key not in keys:
            return []
        return [k for k in keys[keys.index(key) + 1:] if self.step_state(k) != "pending"]

    # --- persistence ----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA,
            "name": self.name,
            "app_version": self.app_version,
            "created": self.created,
            "self_compare": self.self_compare,
            "engine": self.engine,
            "threads": self.threads,
            "params": self.params.to_dict(),
            "filters": asdict(self.filters),
            "blast_input": asdict(self.blast_input),
            "genome_a": asdict(self.genome_a),
            "genome_b": asdict(self.genome_b) if self.genome_b else None,
            "steps": self.steps,
        }

    def save(self) -> Path:
        self.prepare_dirs()
        path = self.root / "project.json"
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path

    @classmethod
    def load(cls, root: Path) -> "Project":
        root = Path(root)
        path = root / "project.json"
        if not path.exists():
            raise WgdiError(f"{root} 不是有效项目（缺少 project.json）")
        data = json.loads(path.read_text(encoding="utf-8"))
        project = cls(
            root=root,
            name=data.get("name", root.name),
            genome_a=GenomeInput(**data.get("genome_a", {})),
            genome_b=GenomeInput(**data["genome_b"]) if data.get("genome_b") else None,
            self_compare=bool(data.get("self_compare", True)),
            engine=data.get("engine", "blastp"),
            threads=int(data.get("threads", default_threads())),
            params=WgdiParams.from_dict(data.get("params", {})),
            filters=Filters(**(data.get("filters") or {})),
            blast_input=BlastInput(**(data.get("blast_input") or {})),
            steps=data.get("steps", {}),
            app_version=data.get("app_version", ""),
            created=float(data.get("created", time.time())),
        )
        return project

    # --- factory --------------------------------------------------------
    @classmethod
    def create(cls, base_dir: Path, name: str, **kwargs) -> "Project":
        safe = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", name).strip("_") or "project"
        root = Path(base_dir) / safe
        if root.exists() and any(root.iterdir()):
            root = Path(base_dir) / f"{safe}-{time.strftime('%Y%m%d-%H%M%S')}"
        project = cls(root=root, name=safe, **kwargs)
        project.prepare_dirs()
        project.save()
        return project

    def recent_key(self) -> str:
        return str(self.root)


def default_projects_dir() -> Path:
    home = Path.home()
    for candidate in (home / "Documents" / "比较基因组分析", home / "比较基因组分析"):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    return Path.cwd()
