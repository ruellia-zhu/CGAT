"""Generate the WGDI `total.conf` from parameters.

Defaults are the ones this project used for the published figures (see
共线性分析/01_guohuai_vs_guohuai/total.conf and 06/Sjap-Mtrun.conf).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class WgdiParams:
    """Every knob exposed in the advanced panel. Defaults = the paper's run."""

    # --- search / collinearity ---
    evalue: str = "1e-5"
    score: int = 100
    grading: str = "50,40,25"
    mg: str = "40,40"
    pvalue: float = 0.2
    repeat_number_icl: int = 10
    process: int = 8

    # --- dotplot ---
    dot_repeat_number: int = 5
    dot_markersize: float = 0.5
    dot_figsize: str = "20,20"

    # --- ks ---
    align_software: str = "muscle"

    # --- blockinfo ---
    repeat_number_bi: int = 20
    ks_col: str = "ks_YN00"

    # --- blockks ---
    bk_pvalue: float = 0.05
    bk_tandem: bool = True
    bk_tandem_length: int = 200
    bk_markersize: float = 1.0
    bk_area: str = "0,3"
    bk_block_length: int = 5
    bk_figsize: str = "24,24"

    # --- kspeaks ---
    kp_pvalue: float = 0.05
    kp_block_length: int = 5
    kp_ks_area: str = "0,10"
    kp_area: str = "0,3"
    kp_homo: str = "-1,1"
    kp_fontsize: int = 9
    kp_figsize: str = "10,6.18"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "WgdiParams":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass(frozen=True)
class GenomeFiles:
    """File names inside the work directory (relative, so the folder is portable)."""

    gff: str
    len: str
    pep: str | None = None
    cds: str | None = None


def _b(value: bool) -> str:
    return "true" if value else "false"


def render(files1: GenomeFiles, files2: GenomeFiles, stem: str,
           name1: str, name2: str, params: WgdiParams, *,
           with_ks: bool = True, blast_file: str | None = None,
           muscle_path: str | None = None) -> str:
    """Return the text of total.conf.

    `stem` prefixes every output file, e.g. ``Sjap-Mtrun``.
    """
    blast = blast_file or f"{stem}.blastp.txt"
    dot = f"{stem}.dot.1.png"
    collinearity = f"{stem}.collinearity.txt"
    ks = f"{stem}.ks"
    block_info = f"{stem}_block_information.csv"
    ks_dot = f"{stem}.ks.dotplot.png"
    ks_dist = f"{stem}.ks_median_distribution.png"
    ks_csv = f"{stem}.ks_median_distribution.csv"

    parts: list[str] = []
    parts.append(f"""[dotplot]
blast = {blast}
gff1 = {files1.gff}
gff2 = {files2.gff}
lens1 = {files1.len}
lens2 = {files2.len}
genome1_name = {name1}
genome2_name = {name2}
multiple = 1
score = {params.score}
evalue = {params.evalue}
repeat_number = {params.dot_repeat_number}
position = order
blast_reverse = false
ancestor_left = none
ancestor_top = none
markersize = {params.dot_markersize}
figsize = {params.dot_figsize}
savefig = {dot}
""")

    parts.append(f"""[collinearity]
gff1 = {files1.gff}
gff2 = {files2.gff}
lens1 = {files1.len}
lens2 = {files2.len}
blast = {blast}
blast_reverse = false
comparison = genomes
multiple = 1
process = {params.process}
evalue = {params.evalue}
score = {params.score}
grading = {params.grading}
mg = {params.mg}
pvalue = {params.pvalue}
repeat_number = {params.repeat_number_icl}
position = order
savefile = {collinearity}
""")

    if with_ks and files1.pep and files2.pep and files1.cds and files2.cds:
        pep = files1.pep if files1.pep == files2.pep else f"{files1.pep};{files2.pep}"
        cds = files1.cds if files1.cds == files2.cds else f"{files1.cds};{files2.cds}"
        tool = f"muscle_path = {muscle_path}\n" if muscle_path else ""
        parts.append(f"""[ks]
cds_file = {cds}
pep_file = {pep}
align_software = {params.align_software}
{tool}pairs_file = {collinearity}
ks_file = {ks}
""")

    info = f"""[blockinfo]
blast = {blast}
gff1 = {files1.gff}
gff2 = {files2.gff}
lens1 = {files1.len}
lens2 = {files2.len}
collinearity = {collinearity}
score = {params.score}
evalue = {params.evalue}
repeat_number = {params.repeat_number_bi}
position = order
"""
    # wgdi's block_info reads self.ks before checking hasattr, so the key must
    # be present even when no Ks file is used.
    if with_ks:
        info += f"ks = {ks}\nks_col = {params.ks_col}\n"
    else:
        info += "ks = none\n"
    info += f"savefile = {block_info}\n"
    parts.append(info)

    if with_ks:
        parts.append(f"""[blockks]
lens1 = {files1.len}
lens2 = {files2.len}
genome1_name = {name1}
genome2_name = {name2}
blockinfo = {block_info}
pvalue = {params.bk_pvalue}
tandem = {_b(params.bk_tandem)}
tandem_length = {params.bk_tandem_length}
markersize = {params.bk_markersize}
area = {params.bk_area}
block_length = {params.bk_block_length}
figsize = {params.bk_figsize}
savefig = {ks_dot}
""")
        parts.append(f"""[kspeaks]
blockinfo = {block_info}
pvalue = {params.kp_pvalue}
tandem = {_b(params.bk_tandem)}
block_length = {params.kp_block_length}
ks_area = {params.kp_ks_area}
multiple = 1
homo = {params.kp_homo}
fontsize = {params.kp_fontsize}
area = {params.kp_area}
figsize = {params.kp_figsize}
savefig = {ks_dist}
savefile = {ks_csv}
""")

    return "\n".join(parts)


def write(path: Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def for_self(files: GenomeFiles, stem: str, name: str, params: WgdiParams,
             with_ks: bool = True, blast_file: str | None = None,
             muscle_path: str | None = None) -> str:
    """Self comparison: both sides point at the same files."""
    return render(files, files, stem, name, name, params,
                  with_ks=with_ks, blast_file=blast_file, muscle_path=muscle_path)


def with_overrides(params: WgdiParams, **kwargs) -> WgdiParams:
    return replace(params, **kwargs)
