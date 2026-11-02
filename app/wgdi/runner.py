"""Small compatibility adapter for the bundled WGDI 0.75.

Runs under the WGDI Python, not the UI Python. WGDI/Biopython/PAML still
perform the scientific calculations; this adapter validates results and fixes
tool invocation, failure recovery and the block_ks boolean/method collision.
"""
from __future__ import annotations

import configparser
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import types
import uuid
from pathlib import Path

try:
    from .ks_inputs import KS_COLUMNS, read_fasta, read_valid_ks
except ImportError:
    from ks_inputs import KS_COLUMNS, read_fasta, read_valid_ks


def run_ks(options):
    import wgdi.ks as module
    obj = module.ks(options)
    proteins, dna = read_fasta(Path(obj.pep_file)), read_fasta(Path(obj.cds_file))
    expected = {tuple(sorted(map(str, row))) for row in obj.auto_file()[[0, 1]].values}
    if not expected:
        raise ValueError("共线性文件中没有可计算的基因对")
    missing = {gene for pair in expected for gene in pair if gene not in proteins or gene not in dna}
    if missing:
        raise ValueError(f"{len(missing)} 个共线性基因缺少蛋白或 CDS，例如 {sorted(missing)[0]}")
    target = Path(obj.ks_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    valid = {k: v for k, v in read_valid_ks(target).items() if k in expected}
    if target.exists():
        backup = target.with_name(f"{target.name}.{uuid.uuid4().hex}.previous")
        shutil.copy2(target, backup)
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            writer.writerow(KS_COLUMNS)
            writer.writerows(valid.values())

    # Keep intermediate files in the project. Do not invoke WGDI's cleanup.
    original_os = module.os
    module.os = types.SimpleNamespace(path=os.path, remove=lambda *args: None)

    def align():
        software = obj.align_software
        exe = getattr(obj, f"{software}_path", "").strip('"')
        if not Path(exe).is_file():
            raise ValueError(f"找不到比对软件 {software}：{exe}")
        if software == "muscle":
            subprocess.run([exe, "-align", obj.pair_pep_file, "-output", obj.prot_align_file,
                            "-threads", str(max(1, min(8, int(obj.align_threads)))), "-quiet"], check=True)
        elif software == "mafft":
            with open(obj.prot_align_file, "w") as output:
                subprocess.run([exe, "--quiet", "--thread", str(max(1, min(8, int(obj.align_threads)))),
                                obj.pair_pep_file], stdout=output, check=True)
        else:
            raise ValueError(f"不支持的比对软件：{software}")

    def pal2nal():
        with open(obj.mrtrans, "w") as output:
            subprocess.run([obj.perl_path.strip('"'), obj.pal2nal_path.strip('"'), obj.prot_align_file,
                            obj.pair_cds_file, "-output", "paml", "-nogap"], stdout=output, check=True)
        return Path(obj.mrtrans).stat().st_size > 0

    original_pair = obj.pair_kaks
    attempted = failures = 0

    def pair_kaks(pair):
        nonlocal attempted, failures
        attempted += 1
        try:
            values = original_pair(pair)
            if values is not None and len(values) == 4 and all(math.isfinite(v) and v >= 0 for v in values):
                return values
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            print(f"Ks pair failed: {exc}", flush=True)
        failures += 1
        return None

    obj.align, obj.pal2nal, obj.pair_kaks = align, pal2nal, pair_kaks
    try:
        obj.run()
    finally:
        module.os = original_os
    valid = read_valid_ks(target)
    summary = {"expected": len(expected), "valid": len(valid), "attempted": attempted,
               "failed_this_run": failures, "remaining": len(expected - valid.keys())}
    target.with_suffix(".summary.json").write_text(json.dumps(summary), encoding="utf-8")
    print("Ks summary: " + json.dumps(summary), flush=True)
    if not valid:
        raise ValueError("没有任何有效 Ks 数值；失败的基因对可在重试时重新计算")
    if summary["remaining"]:
        print(f"WARNING: {summary['remaining']} 对未得到有效 Ks，后续仅使用成功结果；重新运行本步可重试。", flush=True)


def run_blockks(options):
    import matplotlib
    import matplotlib.pyplot as plt
    from wgdi.block_ks import block_ks
    from wgdi.base import str_to_bool
    obj = block_ks(options)
    obj.tandem = str_to_bool(obj.tandem)
    obj.remove_tandem = types.MethodType(block_ks.remove_tandem, obj)
    if not hasattr(plt.cm, "get_cmap"):
        plt.cm.get_cmap = matplotlib.colormaps.get_cmap
    obj.run()


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    config = configparser.ConfigParser()
    config.read(args[1], encoding="utf-8")
    if args[0] == "-ks":
        run_ks(list(config["ks"].items()))
    elif args[0] == "-bk":
        run_blockks(list(config["blockks"].items()))
    else:
        raise ValueError("兼容运行器只支持 -ks 和 -bk")


if __name__ == "__main__":
    main()
