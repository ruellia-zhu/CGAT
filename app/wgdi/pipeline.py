"""Run the WGDI steps for a project, with resume, logging and cancellation."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..core.issues import WgdiError
from . import conf as conf_mod
from .project import STEP_TITLE, STEPS, Project
from .runtime import Runtime, discover

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


class SkipStep(Exception):
    """Raised when a step cannot run on this machine but the rest still can."""


class Listener:
    """Override the bits you care about; the pipeline only calls these."""

    def log(self, message: str) -> None: ...
    def step(self, key: str, state: str) -> None: ...
    def progress(self, key: str, done: int, total: int, eta: float | None) -> None: ...
    def failed(self, key: str, message: str) -> None: ...


@dataclass
class StepResult:
    key: str
    ok: bool
    skipped: bool = False
    message: str = ""


class Pipeline:
    def __init__(self, project: Project, listener: Listener | None = None,
                 runtime: Runtime | None = None):
        self.project = project
        self.listener = listener or Listener()
        self.runtime = runtime or discover()
        self._proc: subprocess.Popen | None = None
        self._cancel = False
        self._t0 = 0.0
        self._current = ""

    # --- public ---------------------------------------------------------
    LOCAL_STEPS = ("prep", "circos")

    def needs_runtime(self, key: str) -> list[str]:
        """Problems that stop this step; empty when it can run."""
        if key in self.LOCAL_STEPS:
            return []
        if key == "blast" and self.project.blast_input.source == "upload":
            return []
        problems = list(self.runtime.problems)
        if key == "ks" and not self.runtime.has_ks:
            problems.append("Ks 需要 perl + pal2nal.pl + yn00.exe")
        return problems

    def can_run(self, key: str) -> tuple[bool, str]:
        problems = self.needs_runtime(key)
        if problems:
            return False, "；".join(problems)
        return True, ""

    def run_step(self, key: str, *, reset_downstream: bool = True) -> StepResult:
        """Run exactly one step; used by the wizard."""
        if reset_downstream:
            self.project.reset_from(key)
        if key == "blast" and self.project.blast_input.source == "upload":
            # nothing to build when the table is supplied
            self.project.set_step("blastdb", "skipped", reason="使用上传的比对结果")
            self.listener.step("blastdb", "skipped")
        results = self.run(only=[key])
        return results[0] if results else StepResult(key, False, message="未执行")

    def run(self, only: list[str] | None = None, from_step: str | None = None) -> list[StepResult]:
        if only and len(only) == 1 and not self.needs_runtime(only[0]):
            pass
        elif not self.runtime.ok:
            raise WgdiError("WGDI 运行时不完整：" + "；".join(self.runtime.problems))
        keys = [k for k, _ in STEPS]
        if from_step and from_step in keys:
            self.project.reset_from(from_step)
        if only:
            keys = [k for k in keys if k in only]
        self.project.prepare_dirs()
        results: list[StepResult] = []
        for key in keys:
            if self._cancel:
                break
            try:
                results.append(self._run_step(key))
            except WgdiError as exc:
                self.listener.failed(key, str(exc))
                self.project.set_step(key, "failed", error=str(exc))
                self.project.save()
                results.append(StepResult(key, False, message=str(exc)))
                break
            self.project.save()
        return results

    def cancel(self) -> None:
        self._cancel = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, creationflags=CREATE_NO_WINDOW)

    # --- steps ----------------------------------------------------------
    def _run_step(self, key: str) -> StepResult:
        self._current = key
        if self._should_skip(key):
            self.listener.step(key, "skipped")
            return StepResult(key, True, skipped=True)
        self.listener.step(key, "running")
        self._t0 = time.time()
        handler = getattr(self, f"_step_{key}", None)
        if handler is None:
            raise WgdiError(f"未知步骤：{key}")
        try:
            handler()
        except SkipStep as exc:
            self.listener.log(f"跳过 {key}：{exc}")
            self.project.set_step(key, "skipped", reason=str(exc))
            self.listener.step(key, "skipped")
            return StepResult(key, True, skipped=True, message=str(exc))
        duration = time.time() - self._t0
        self.project.set_step(key, "done", duration=round(duration, 1))
        self.listener.step(key, "done")
        return StepResult(key, True)

    def _should_skip(self, key: str) -> bool:
        if not self.project.is_done(key):
            return False
        outputs = self._outputs(key)
        return all(p.exists() for p in outputs) if outputs else True

    def _outputs(self, key: str) -> list[Path]:
        p = self.project
        stem = p.stem
        mapping = {
            "prep": [p.prepared / f"{p.genome_a.prefix}.gff"],
            "blastdb": [p.work / f"{p.genome_a.prefix}.wgdi.pep.fasta.pdb"],
            "blast": [p.work / f"{stem}.blastp.txt"],
            "dotplot": [p.work / f"{stem}.dot.1.png"],
            "collinearity": [p.work / f"{stem}.collinearity.txt"],
            "ks": [p.work / f"{stem}.ks"],
            "blockinfo": [p.work / f"{stem}_block_information.csv"],
            "blockks": [p.work / f"{stem}.ks.dotplot.png"],
            "kspeaks": [p.work / f"{stem}.ks_median_distribution.png"],
            "circos": [p.results / f"{stem}.pdf"],
        }
        return mapping.get(key, [])

    # --- process helpers ------------------------------------------------
    def _run(self, key: str, cmd: list[str], *, cwd: Path | None = None,
             on_line: Callable[[str], None] | None = None) -> int:
        log_path = self.project.logs / f"{self._index(key):02d}_{key}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.listener.log(f"$ {' '.join(str(c) for c in cmd)}")
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            log.write("$ " + " ".join(str(c) for c in cmd) + "\n")
            log.flush()
            try:
                proc = subprocess.Popen(
                    [str(c) for c in cmd], cwd=str(cwd or self.project.work),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    encoding="utf-8", errors="replace", env=self.runtime.env(),
                    creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
                )
            except OSError as exc:
                raise WgdiError(f"无法启动 {cmd[0]}：{exc}") from exc
            self._proc = proc
            assert proc.stdout is not None
            for line in proc.stdout:
                text = line.rstrip()
                log.write(text + "\n")
                if text:
                    self.listener.log(text)
                    if on_line is not None:
                        on_line(text)
                if self._cancel:
                    self.cancel()
                    break
            code = proc.wait()
            self._proc = None
            log.write(f"--- exit {code} ---\n")
        if self._cancel:
            raise WgdiError("已取消")
        return code

    def _wgdi(self, key: str, flag: str) -> None:
        assert self.runtime.wgdi is not None
        conf_path = self._ensure_conf()
        code = self._run(key, [self.runtime.wgdi, flag, conf_path.name])
        if code != 0:
            raise WgdiError(f"wgdi {flag} 退出码 {code}，详见 logs")

    def _index(self, key: str) -> int:
        return [k for k, _ in STEPS].index(key) + 1

    # --- conf ------------------------------------------------------------
    def _ensure_conf(self) -> Path:
        p = self.project
        stem = p.stem
        a = conf_mod.GenomeFiles(
            gff=f"../prepared/{p.genome_a.prefix}.gff",
            len=f"../prepared/{p.genome_a.prefix}.len",
            pep=f"../prepared/{p.genome_a.prefix}.wgdi.pep.fasta",
            cds=f"../prepared/{p.genome_a.prefix}.wgdi.cds.fasta",
        )
        if p.self_compare or p.genome_b is None:
            b = a
            name_b = p.genome_a.display_name or p.genome_a.prefix
        else:
            b = conf_mod.GenomeFiles(
                gff=f"../prepared/{p.genome_b.prefix}.gff",
                len=f"../prepared/{p.genome_b.prefix}.len",
                pep=f"../prepared/{p.genome_b.prefix}.wgdi.pep.fasta",
                cds=f"../prepared/{p.genome_b.prefix}.wgdi.cds.fasta",
            )
            name_b = p.genome_b.display_name or p.genome_b.prefix
        name_a = p.genome_a.display_name or p.genome_a.prefix
        ks_ready = ((p.work / f"{stem}.ks").exists()
                    or ((p.prepared / f"{p.genome_a.prefix}.wgdi.cds.fasta").exists()
                        and self.runtime.has_ks))
        with_ks = ks_ready
        # wgdi joins muscle/pal2nal into a shell string, so those paths must be
        # quoted; Biopython execs yn00 directly, so that one must stay bare.
        muscle = self.runtime.bins.get("muscle")
        pal2nal = self.runtime.bins.get("pal2nal")
        yn00 = self.runtime.bins.get("yn00")
        text = conf_mod.render(
            a, b, stem, name_a, name_b, p.params, with_ks=with_ks,
            muscle_path=f'"{muscle}"' if muscle else None,
            pal2nal_path=f'"{pal2nal}"' if pal2nal else None,
            yn00_path=str(yn00) if yn00 else None)
        return conf_mod.write(p.work / "total.conf", text)

    # --- individual steps ------------------------------------------------
    def _step_prep(self) -> None:
        from ..prep import build as prep

        p = self.project
        self.listener.log("预处理物种 A …")
        self._prepare_genome(p.genome_a, p.prepared)
        if not (p.self_compare or p.genome_b is None):
            self.listener.log("预处理物种 B …")
            self._prepare_genome(p.genome_b, p.prepared)

    def _prepare_genome(self, genome, out_dir: Path) -> None:
        from ..prep import build as prep

        prefix = genome.prefix
        log = self.listener.log

        def progress(stage: str, done: int, total: int) -> None:
            self.listener.progress("prep", done, total, None)

        filters = self.project.filters
        exclude = filters.exclude_pattern()
        if genome.mode == "manual":
            if not genome.fai or not genome.gff or not genome.pep:
                raise WgdiError(f"物种 {prefix} 缺少 fai / gff / 蛋白文件")
            prepared = prep.prepare_manual(
                Path(genome.fai), Path(genome.gff), Path(genome.pep),
                Path(genome.cds) if genome.cds else None,
                out_dir, prefix, exclude=exclude, strip_prefix=filters.strip_prefix,
                progress=progress, log=log)
        else:
            if not genome.genome or not genome.gff:
                raise WgdiError(f"物种 {prefix} 缺少基因组 FASTA 或注释")
            prepared = prep.prepare_auto(
                Path(genome.genome), Path(genome.gff), out_dir, prefix,
                exclude=exclude, strip_prefix=filters.strip_prefix,
                progress=progress, log=log)
            genome.fai = str(prepared.fai)
        for issue in prepared.issues:
            if issue.level == "error":
                raise WgdiError(str(issue))
            log(f"  {issue}")
        log(f"  {prefix}: {prepared.summary()}")
        if prepared.dropped:
            sample = "、".join(prepared.dropped[:5])
            more = f" 等 {len(prepared.dropped)} 条" if len(prepared.dropped) > 5 else ""
            log(f"  已排除非染色体序列：{sample}{more}")
        detail = self.project.step_detail("prep")
        detail[prefix] = {
            "genes": prepared.genes,
            "sequences": prepared.sequences,
            "kept": prepared.kept_names,
            "dropped": prepared.dropped,
        }
        self.project.set_detail("prep", detail)

    def _step_blastdb(self) -> None:
        if self.project.blast_input.source == "upload":
            raise SkipStep("使用上传的比对结果，不需要建库")
        assert self.runtime.bins.get("makeblastdb")
        p = self.project
        fasta = p.prepared / f"{p.genome_a.prefix}.wgdi.pep.fasta"
        # BLAST 2.17 默认写 v5（LMDB）库，路径里有中文时 LMDB 会直接失败；
        # v4 的 .phr/.pin/.psq 是普通文件，中文路径下可用。
        code = self._run("blastdb", [self.runtime.bins["makeblastdb"],
                                     "-in", fasta, "-dbtype", "prot",
                                     "-blastdb_version", "4"])
        if code != 0:
            raise WgdiError(f"makeblastdb 退出码 {code}")

    def _import_blast(self) -> Path:
        """Validate an uploaded m8 table and copy it into the project."""
        p = self.project
        source = p.blast_input.uploaded
        if not source:
            raise WgdiError("还没有选择要比对的文件")
        src = Path(source)
        if not src.exists():
            raise WgdiError(f"找不到文件：{src}")
        if src.stat().st_size == 0:
            raise WgdiError(f"{src.name} 是空文件")

        rows = 0
        queries: set[str] = set()
        with src.open("r", encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 6:
                    parts = line.split()
                if len(parts) < 6:
                    raise WgdiError(
                        f"{src.name} 第 {number} 行只有 {len(parts)} 列，"
                        "应为 outfmt 6 的 12 列（至少 6 列）")
                try:
                    float(parts[10]) if len(parts) > 10 else float(parts[2])
                except ValueError as exc:
                    raise WgdiError(
                        f"{src.name} 第 {number} 行的数值列无法解析：{parts[:3]}") from exc
                queries.add(parts[0])
                rows += 1
                if rows <= 2000:
                    continue
        if rows == 0:
            raise WgdiError(f"{src.name} 里没有比对记录")

        self.listener.log(f"导入比对结果：{rows:,} 行，{len(queries):,} 条查询序列")
        target = p.work / f"{p.stem}.blastp.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        return target

    def _step_blast(self) -> None:
        p = self.project
        stem = p.stem
        if p.blast_input.source == "upload":
            target = self._import_blast()
            self.listener.log(f"已使用上传的比对结果：{target.name}")
            self.project.set_detail("blast", {"source": "upload", "file": str(target)})
            return
        query_source = (p.genome_a if (p.self_compare or p.genome_b is None)
                        else p.genome_b)
        query = p.prepared / f"{query_source.prefix}.wgdi.pep.fasta"
        db = p.prepared / f"{p.genome_a.prefix}.wgdi.pep.fasta"
        out = p.work / f"{stem}.blastp.txt"
        chunks_dir = p.work / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        chunks = self._split_fasta(query, chunks_dir, stem)
        self.listener.log(f"比对分 {len(chunks)} 块，线程 {p.threads}")
        results: list[Path] = []
        started = time.time()
        for index, chunk in enumerate(chunks, 1):
            if self._cancel:
                raise WgdiError("已取消")
            chunk_out = chunk.with_suffix(".m8")
            if chunk_out.exists() and chunk_out.stat().st_size > 0:
                results.append(chunk_out)
                self._report_blast(index, len(chunks), started)
                continue
            cmd = [self.runtime.bins["diamond"] if p.engine == "diamond"
                   else self.runtime.bins["blastp"]]
            if p.engine == "diamond":
                cmd += ["blastp", "-d", str(db), "-q", str(chunk)]
            else:
                cmd += ["-db", str(db), "-query", str(chunk)]
            cmd += ["-out", str(chunk_out), "-outfmt", "6",
                    "-evalue", p.params.evalue, "-num_threads", str(p.threads)]
            if p.engine != "diamond":
                cmd += ["-num_alignments", "20"]
            code = self._run("blast", cmd)
            if code != 0:
                raise WgdiError(f"比对退出码 {code}（第 {index}/{len(chunks)} 块）")
            results.append(chunk_out)
            self._report_blast(index, len(chunks), started)
        with out.open("wb") as merged:
            for path in results:
                with path.open("rb") as part:
                    shutil.copyfileobj(part, merged)
        self.listener.log(f"合并 {len(results)} 块 → {out.name} "
                          f"({out.stat().st_size / 1e6:.1f} MB)")

    def _report_blast(self, done: int, total: int, started: float) -> None:
        elapsed = time.time() - started
        eta = (elapsed / done) * (total - done) if done else None
        self.listener.progress("blast", done, total, eta)

    def _split_fasta(self, source: Path, out_dir: Path, stem: str) -> list[Path]:
        """Split the query into equal-sized chunks so progress is honest."""
        cache = out_dir / f"{stem}.chunks.json"
        chunk_files = sorted(out_dir.glob(f"{stem}.q*.faa"))
        if cache.exists() and chunk_files:
            return chunk_files
        records: list[tuple[str, list[str]]] = []
        with source.open("r", encoding="utf-8", errors="replace") as handle:
            header, buf = None, []
            for line in handle:
                if line.startswith(">"):
                    if header:
                        records.append((header, buf))
                    header, buf = line, []
                elif header:
                    buf.append(line)
            if header:
                records.append((header, buf))
        if not records:
            raise WgdiError(f"{source.name} 里没有序列，无法比对")
        target = max(1, min(40, len(records) // 50))
        per = max(1, -(-len(records) // target))
        chunks: list[Path] = []
        for i in range(0, len(records), per):
            path = out_dir / f"{stem}.q{i // per:03d}.faa"
            with path.open("w", encoding="utf-8", newline="") as handle:
                for header, buf in records[i:i + per]:
                    handle.write(header)
                    handle.writelines(buf)
            chunks.append(path)
        return chunks

    def _step_dotplot(self) -> None:
        self._wgdi("dotplot", "-d")

    def _step_collinearity(self) -> None:
        self._wgdi("collinearity", "-icl")

    def _step_ks(self) -> None:
        if not self.runtime.has_ks:
            raise SkipStep("未安装 Ks 工具链（perl + pal2nal.pl + yn00.exe），"
                           "跳过 Ks；其余步骤与 Circos 不受影响")
        self._wgdi("ks", "-ks")

    def _step_blockinfo(self) -> None:
        self._wgdi("blockinfo", "-bi")

    def _step_blockks(self) -> None:
        if not (self.project.work / f"{self.project.stem}.ks").exists():
            raise SkipStep("没有 Ks 结果，跳过 Ks 点阵图")
        self._wgdi("blockks", "-bk")

    def _step_kspeaks(self) -> None:
        if not (self.project.work / f"{self.project.stem}.ks").exists():
            raise SkipStep("没有 Ks 结果，跳过 Ks 分布图")
        self._wgdi("kspeaks", "-kp")

    def _step_circos(self) -> None:
        from ..core import style as style_mod
        from ..core import wgdi as wgdi_core
        from ..render import export as export_mod
        from ..render import figure as figure_mod

        p = self.project
        stem = p.stem
        dataset, issues = wgdi_core.load_dataset(
            gff1=p.prepared / f"{p.genome_a.prefix}.gff",
            len1=p.prepared / f"{p.genome_a.prefix}.len",
            blocks_csv=p.work / f"{stem}_block_information.csv",
            gff2=None if p.self_compare else p.prepared / f"{p.genome_b.prefix}.gff",
            len2=None if p.self_compare else p.prepared / f"{p.genome_b.prefix}.len",
            layout="self" if p.self_compare else "paired",
            name1=p.genome_a.display_name or p.genome_a.prefix,
            name2=(p.genome_a.display_name or p.genome_a.prefix) if p.self_compare
            else (p.genome_b.display_name or p.genome_b.prefix),
        )
        for issue in issues:
            if issue.level == "error":
                raise WgdiError(str(issue))
        style = style_mod.auto(len(dataset.genome1.chromosomes) * 2 if p.self_compare else
                               len(dataset.genome1.chromosomes) + len(dataset.genome2.chromosomes),
                               len(dataset.anchor_pairs(50)))
        style = style_mod.replace(style, title=f"{p.stem.replace('-', ' – ')}")
        fig = figure_mod.build_figure(dataset, style)
        try:
            for fmt in ("pdf", "png"):
                export_mod.export(fig, p.results / f"{stem}.{fmt}", fmt, 600)
        finally:
            figure_mod.close(fig)
        self.listener.log(f"Circos 已输出到 results/{stem}.pdf")
