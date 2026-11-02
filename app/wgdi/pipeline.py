"""Run the WGDI steps for a project, with resume, logging and cancellation."""
from __future__ import annotations

import os
import json
import uuid
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
from .cache import file_stamp, fingerprint, preserve

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
        if key == "blast":
            if self.project.blast_input.source == "upload":
                return []
            wanted = ("diamond",) if self.project.engine == "diamond" \
                else ("blastp", "makeblastdb")
            return [f"缺少 {name}" for name in wanted if name not in self.runtime.bins]
        problems = [] if self.runtime.wgdi else ["缺少 WGDI 运行时"]
        if key == "ks" and not self.runtime.has_ks:
            problems.append("Ks 需要 perl + pal2nal.pl + yn00.exe")
        if key == "ks" and self.project.params.align_software not in self.runtime.bins:
            problems.append(f"找不到可用的 {self.project.params.align_software}")
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
        results = self.run(only=[key])
        return results[0] if results else StepResult(key, False, message="未执行")

    def run(self, only: list[str] | None = None, from_step: str | None = None) -> list[StepResult]:
        self.project.validate()
        self.project.reconcile()
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
            except (WgdiError, OSError, ValueError) as exc:
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
        dependencies = {"blast": ["prep"], "dotplot": ["prep", "blast"],
                        "collinearity": ["prep", "blast"], "ks": ["prep", "collinearity"],
                        "blockinfo": ["prep", "blast", "collinearity"],
                        "blockks": ["blockinfo", "ks"], "kspeaks": ["blockinfo", "ks"],
                        "circos": ["prep", "blockinfo"]}
        for dependency in dependencies.get(key, []):
            entry = self.project.steps.get(dependency, {})
            if entry and entry.get("state") not in ("done", "skipped"):
                raise WgdiError(f"请先完成 {STEP_TITLE[dependency]}；其旧结果已失效或尚未完成")
        self.listener.step(key, "running")
        if key != "ks":
            problems = self.needs_runtime(key)
            if problems:
                raise WgdiError("；".join(problems))
        signature = self.project.input_signature(key)
        self.project.set_step(key, "running")
        protected = {Path(g.genome).resolve() for g in self.project.genomes if g.genome}
        if self.project.blast_input.uploaded:
            protected.add(Path(self.project.blast_input.uploaded).resolve())
        for output in self._outputs(key):
            if output.resolve() not in protected:
                preserve(output, self.project.root)
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
        if any(not path.is_file() or path.stat().st_size == 0 for path in self._outputs(key)):
            raise WgdiError(f"{STEP_TITLE[key]} 未生成完整、非空的结果，请检查日志")
        duration = time.time() - self._t0
        self.project.set_step(key, "done", duration=round(duration, 1), signature=signature,
                              output_stamps=[file_stamp(f) for f in self._outputs(key)])
        self.listener.step(key, "done")
        return StepResult(key, True)

    def _should_skip(self, key: str) -> bool:
        if not self.project.is_done(key):
            return False
        outputs = self._outputs(key)
        return bool(outputs) and all(p.is_file() and p.stat().st_size > 0 for p in outputs)

    def _outputs(self, key: str) -> list[Path]:
        return self.project.outputs(key)

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
        conf_path = self._ensure_conf(require_blast=key in ("dotplot", "collinearity", "blockinfo"))
        stopped: list[str] = []

        def inspect_line(line: str) -> None:
            if "Stoped!" in line or "does not correspond" in line:
                stopped.append(line)

        cmd = [self.runtime.wgdi, flag, conf_path.name]
        if flag in ("-ks", "-bk"):
            if not self.runtime.python:
                raise WgdiError("WGDI 兼容运行需要 runtime Python")
            cmd = [self.runtime.python, Path(__file__).with_name("runner.py"), flag, conf_path.name]
        code = self._run(key, cmd, on_line=inspect_line)
        if code != 0:
            raise WgdiError(f"wgdi {flag} 退出码 {code}，详见 logs")
        if stopped:
            raise WgdiError(f"wgdi {flag} 提前停止：{'；'.join(stopped)}，详见 logs")
        missing = [path.name for path in self._outputs(key) if not path.exists()]
        if missing:
            raise WgdiError(f"wgdi {flag} 未生成预期结果：{'、'.join(missing)}，详见 logs")

    def _index(self, key: str) -> int:
        return [k for k, _ in STEPS].index(key) + 1

    # --- conf ------------------------------------------------------------
    def _ensure_conf(self, *, require_blast: bool = False) -> Path:
        p = self.project
        stem = p.stem
        blast_file = None
        # Every regenerated total.conf must retain the canonical direction,
        # including when a later Ks step rewrites the shared configuration.
        if require_blast or (p.work / f"{stem}.blastp.txt").exists():
            from .blast import for_wgdi

            b = p.genome_a if p.self_compare or p.genome_b is None else p.genome_b
            blast_file = for_wgdi(
                p.work / f"{p.stem}.blastp.txt",
                p.prepared / f"{p.genome_a.prefix}.gff",
                p.prepared / f"{b.prefix}.gff",
                p.work / f"{p.stem}.wgdi.blastp.txt",
                score=float(p.params.score), evalue=float(p.params.evalue),
                log=self.listener.log).name
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
        valid_ks = p.is_done("ks") and (p.work / f"{stem}.ks").is_file()
        inputs_ready = all((p.prepared / f"{g.prefix}.wgdi.cds.fasta").is_file() for g in p.genomes)
        with_ks = valid_ks or inputs_ready
        if inputs_ready:
            from .ks_inputs import merge_inputs
            merged_pep, merged_cds = merge_inputs(p)
            a = conf_mod.GenomeFiles(a.gff, a.len, merged_pep, merged_cds)
            b = conf_mod.GenomeFiles(b.gff, b.len, merged_pep, merged_cds)
        else:
            a = conf_mod.GenomeFiles(a.gff, a.len)
            b = conf_mod.GenomeFiles(b.gff, b.len)
        # wgdi joins muscle/pal2nal into a shell string, so those paths must be
        # quoted; Biopython execs yn00 directly, so that one must stay bare.
        muscle = self.runtime.bins.get("muscle")
        pal2nal = self.runtime.bins.get("pal2nal")
        yn00 = self.runtime.bins.get("yn00")
        text = conf_mod.render(
            a, b, stem, name_a, name_b, p.params, with_ks=with_ks,
            ks_available=valid_ks,
            align_threads=p.threads,
            blast_file=blast_file,
            muscle_path=f'"{muscle}"' if muscle else None,
            pal2nal_path=f'"{pal2nal}"' if pal2nal else None,
            yn00_path=str(yn00) if yn00 else None,
            mafft_path=str(self.runtime.bins["mafft"]) if "mafft" in self.runtime.bins else None,
            perl_path=str(self.runtime.bins["perl"]) if "perl" in self.runtime.bins else None)
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
            if self._cancel:
                raise WgdiError("已取消")
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

    def _build_index(self) -> Path:
        """Create the searchable protein database; returns the -db argument."""
        p = self.project
        fasta = p.prepared / f"{p.genome_a.prefix}.wgdi.pep.fasta"
        if p.engine == "diamond":
            prefix = p.work / f"{p.genome_a.prefix}.pep"
            code = self._run("blast", [self.runtime.bins["diamond"], "makedb",
                                       "--in", fasta, "-d", prefix,
                                       "--threads", str(p.threads)])
            if code != 0:
                raise WgdiError(f"diamond makedb 退出码 {code}")
            self.listener.log(f"已建 diamond 库：{prefix.name}.dmnd")
            return prefix
        # BLAST 2.17 默认写 v5（LMDB）库，路径里有中文时 LMDB 会直接失败；
        # v4 的 .phr/.pin/.psq 是普通文件，中文路径下可用。
        code = self._run("blast", [self.runtime.bins["makeblastdb"],
                                     "-in", fasta, "-dbtype", "prot",
                                     "-blastdb_version", "4"])
        if code != 0:
            raise WgdiError(f"makeblastdb 退出码 {code}")
        return fasta

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

        from .blast import validate_table
        validate_table(src)
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
        if src.resolve() == target.resolve():
            return target
        staged = target.with_name(f"{target.name}.{uuid.uuid4().hex}.part")
        with src.open(encoding="utf-8-sig") as handle, staged.open("w", encoding="utf-8", newline="") as out:
            for line in handle:
                if line.strip() and not line.startswith("#"):
                    out.write("\t".join(line.split()[:12]) + "\n")
        preserve(target, p.root)
        staged.replace(target)
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
        out = p.work / f"{stem}.blastp.txt"
        from .blast import validate_table
        cache_key = fingerprint({
            "logic": 3, "engine": p.engine, "evalue": p.params.evalue,
            "tools": {k: file_stamp(v) for k, v in self.runtime.bins.items()
                      if k in (p.engine, "makeblastdb")},
            "query": file_stamp(query, content=True),
            "db": file_stamp(p.prepared / f"{p.genome_a.prefix}.wgdi.pep.fasta", content=True),
        })
        chunks_dir = p.work / "chunks" / cache_key
        chunks_dir.mkdir(parents=True, exist_ok=True)

        self.project.set_detail("blast", {"engine": p.engine, "cache": cache_key})

        db = self._build_index()
        self.listener.log(f"比对引擎 {p.engine}，线程 {p.threads}")
        chunks = self._split_fasta(query, chunks_dir, stem)
        self.listener.log(f"比对分 {len(chunks)} 块，线程 {p.threads}")
        results: list[Path] = []
        started = time.time()
        for index, chunk in enumerate(chunks, 1):
            if self._cancel:
                raise WgdiError("已取消")
            chunk_out = chunk.with_suffix(".m8")
            marker = chunk_out.with_suffix(".done.json")
            reusable = False
            if chunk_out.exists() and marker.exists():
                try:
                    reusable = json.loads(marker.read_text(encoding="utf-8")) == file_stamp(chunk_out, content=True)
                except (OSError, ValueError):
                    pass
            if reusable:
                results.append(chunk_out)
                self._report_blast(index, len(chunks), started)
                continue
            staged = chunk_out.with_name(f"{chunk_out.name}.{uuid.uuid4().hex}.part")
            if p.engine == "diamond":
                # diamond 只认短选项：-o / -f / -e / -p，且库必须是它自己建的 .dmnd
                cmd = [self.runtime.bins["diamond"], "blastp",
                       "-d", str(db), "-q", str(chunk), "-o", str(staged),
                       "-f", "6", "-e", p.params.evalue, "-p", str(p.threads)]
            else:
                cmd = [self.runtime.bins["blastp"], "-db", str(db),
                       "-query", str(chunk), "-out", str(staged),
                       "-outfmt", "6", "-evalue", p.params.evalue,
                       "-num_threads", str(p.threads), "-num_alignments", "20"]
            code = self._run("blast", cmd)
            if code != 0:
                raise WgdiError(f"比对退出码 {code}（第 {index}/{len(chunks)} 块）")
            validate_table(staged, allow_empty=True)
            preserve(chunk_out, p.root)
            staged.replace(chunk_out)
            marker.write_text(json.dumps(file_stamp(chunk_out, content=True)), encoding="utf-8")
            results.append(chunk_out)
            self._report_blast(index, len(chunks), started)
        staged_out = out.with_name(f"{out.name}.{uuid.uuid4().hex}.part")
        with staged_out.open("wb") as merged:
            for path in results:
                with path.open("rb") as part:
                    shutil.copyfileobj(part, merged)
        validate_table(staged_out)
        preserve(out, p.root)
        staged_out.replace(out)
        self.listener.log(f"合并 {len(results)} 块 → {out.name} "
                          f"({out.stat().st_size / 1e6:.1f} MB)")

    def _report_blast(self, done: int, total: int, started: float) -> None:
        elapsed = time.time() - started
        eta = (elapsed / done) * (total - done) if done else None
        self.listener.progress("blast", done, total, eta)

    def _split_fasta(self, source: Path, out_dir: Path, stem: str) -> list[Path]:
        """Split the query into equal-sized chunks so progress is honest."""
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
        p = self.project
        align = p.params.align_software
        if align not in self.runtime.bins:
            raise WgdiError(f"未找到 {align}，请选择已安装的比对软件")
        for g in p.genomes:
            if not (p.prepared / f"{g.prefix}.wgdi.cds.fasta").is_file():
                raise SkipStep("没有对应的 CDS，跳过 Ks；共线性与 Circos 可继续")
        import configparser
        from .ks_inputs import read_valid_ks

        key = fingerprint({"logic": 3, "input": p.input_signature("ks"),
                           "files": [file_stamp(p.prepared / f"{g.prefix}.wgdi.{s}.fasta", content=True)
                                     for g in p.genomes for s in ("pep", "cds")],
                           "tools": {k: file_stamp(self.runtime.bins[k]) for k in (align, "pal2nal", "yn00", "perl")}})
        cache_dir = p.work / "ks_cache" / key
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached = cache_dir / f"{p.stem}.ks"
        conf_path = self._ensure_conf()
        config = configparser.ConfigParser()
        config.read(conf_path, encoding="utf-8")
        config["ks"]["ks_file"] = str(cached)
        with conf_path.open("w", encoding="utf-8") as handle:
            config.write(handle)
        if not self.runtime.python:
            raise WgdiError("找不到 Ks 运行时 Python")
        code = self._run("ks", [self.runtime.python, Path(__file__).with_name("runner.py"), "-ks", conf_path.name])
        if code != 0:
            raise WgdiError(f"Ks 计算未完成（退出码 {code}），详见 logs；成功的基因对已保留供重试")
        valid = read_valid_ks(cached)
        if not valid:
            raise WgdiError("没有任何有效的 Ks 结果，未标记成功；请检查序列和工具日志")
        shutil.copy2(cached, p.work / f"{p.stem}.ks")
        summary = cached.with_suffix(".summary.json")
        detail = json.loads(summary.read_text(encoding="utf-8")) if summary.exists() else {"valid": len(valid)}
        self.project.set_detail("ks", detail)

    def _step_blockinfo(self) -> None:
        self._wgdi("blockinfo", "-bi")

    def _step_blockks(self) -> None:
        if not self.project.is_done("ks"):
            raise SkipStep("没有 Ks 结果，跳过 Ks 点阵图")
        self._wgdi("blockks", "-bk")

    def _step_kspeaks(self) -> None:
        if not self.project.is_done("ks"):
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
            for fmt in p.formats:
                export_mod.export(fig, p.results / f"{stem}.{fmt}", fmt, 600)
        finally:
            figure_mod.close(fig)
        self.listener.log(f"Circos 已输出到 {p.results}（{'、'.join(p.formats)}）")
