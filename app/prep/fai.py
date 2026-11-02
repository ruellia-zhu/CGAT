"""FASTA indexing and `.fai` handling — 64-bit safe by construction.

Lilium genomes break naive readers two ways:

* a chromosome longer than 2**31 (L. regale: 4.3 Gb), so *lengths and offsets*
  overflow a 32-bit int;
* a FASTA written as one sequence per line (L. davidii), so *linebases itself*
  is 4.3e9 and wraps to a negative number.

Everything here uses Python ints (unbounded). `is_int32_unsafe()` flags records a
32-bit tool would misread, so the UI can suggest re-wrapping the FASTA to 60
columns before anything downstream touches it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from ..core.issues import Issue, WgdiError

INT32_MAX = 2**31 - 1
DEFAULT_WIDTH = 60
WIDE_LINE = 100          # >= 100 碱基一行才值得重排
Progress = Callable[[int, int], None] | None


@dataclass(frozen=True)
class FaiRecord:
    name: str
    length: int
    offset: int
    linebases: int
    linewidth: int
    irregular: bool = False

    @property
    def int32_unsafe(self) -> bool:
        return max(self.length, self.offset, self.linebases, self.linewidth) > INT32_MAX

    @property
    def single_line(self) -> bool:
        """True when the whole sequence sits on one line (linebases == length)."""
        return self.linebases >= self.length > 0

    def offset_of(self, pos0: int) -> int:
        """Byte offset of 0-based base `pos0` within the file."""
        return self.offset + (pos0 // self.linebases) * self.linewidth + pos0 % self.linebases


def _iter_lines(path: Path, chunk_size: int = 8 << 20) -> Iterator[tuple[int, bytes, int]]:
    """Yield (start_offset, line_without_eol, eol_bytes) for every line."""
    pos = 0
    buffer = b""
    buffer_pos = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                if buffer:
                    yield buffer_pos, buffer, 0
                return
            buffer += chunk
            start = 0
            while True:
                nl = buffer.find(b"\n", start)
                if nl < 0:
                    break
                line = buffer[start:nl]
                eol = 1
                if line.endswith(b"\r"):
                    line = line[:-1]
                    eol = 2
                yield buffer_pos + start, line, eol
                start = nl + 1
            buffer_pos += start
            buffer = buffer[start:]


def index_fasta(path: Path, progress: Progress = None) -> tuple[list[FaiRecord], list[Issue]]:
    """Build `.fai` records by streaming the file once."""
    path = Path(path)
    if not path.exists():
        raise WgdiError(f"找不到文件：{path}")
    total = path.stat().st_size
    issues: list[Issue] = []
    records: list[FaiRecord] = []
    name: str | None = None
    length = 0
    start = 0
    linebases = 0
    linewidth = 0
    last_report = 0
    ragged = 0
    previous_width: tuple[int, int] | None = None
    irregular = False

    def flush() -> None:
        nonlocal name, length, start, linebases, linewidth, previous_width, irregular
        if name is not None:
            if length == 0:
                issues.append(Issue("warning", name, "序列为空，已跳过"))
            elif linebases == 0:
                issues.append(Issue("error", name, "没有序列行"))
            else:
                records.append(FaiRecord(name, length, start, linebases, linewidth, irregular))
        name, length, linebases, linewidth = None, 0, 0, 0
        previous_width, irregular = None, False

    for pos, line, eol in _iter_lines(path):
        if progress is not None and pos - last_report > (64 << 20):
            last_report = pos
            progress(pos, total)
        if not line:
            continue
        if line[:1] == b">":
            flush()
            token = line[1:].split()[0] if line[1:].strip() else b""
            if not token:
                raise WgdiError(f"{path.name} 第 {pos} 字节处有空的 FASTA 标题行")
            name = token.decode("utf-8", "replace")
            start = pos + len(line) + eol
            continue
        if name is None:
            continue
        bases = len(line)
        length += bases
        if previous_width is not None and previous_width != (linebases, linewidth):
            ragged += 1
            irregular = True
        if linebases == 0:
            linebases, linewidth = bases, bases + eol
        elif bases > linebases or bases + eol > linewidth:
            ragged += 1
            irregular = True
        previous_width = (bases, bases + eol)
    flush()
    if progress is not None:
        progress(total, total)
    if not records:
        raise WgdiError(f"{path.name} 里没有读到任何序列，确认是不是 FASTA")
    if ragged:
        issues.append(Issue(
            "warning", path.name,
            f"{ragged} 行宽度与首行不一致（长短不齐？），建议先重排成每行 60"))
    dupes = {r.name for r in records}
    if len(dupes) != len(records):
        issues.append(Issue("error", path.name, "存在重复的序列名"))
    return records, issues


def parse_fai(path: Path) -> tuple[list[FaiRecord], list[Issue]]:
    """Read a `.fai`, validating fields a 32-bit producer may have corrupted."""
    path = Path(path)
    if not path.exists():
        raise WgdiError(f"找不到文件：{path}")
    records: list[FaiRecord] = []
    issues: list[Issue] = []
    negative = False
    overflow_written = False
    for lineno, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not raw.strip():
            continue
        parts = raw.split("\t")
        if len(parts) < 5:
            issues.append(Issue("error", f"{path.name}:{lineno}", "应有 5 列：名称 长度 偏移 每行碱基 每行字节"))
            continue
        try:
            values = [int(parts[i]) for i in range(1, 5)]
        except ValueError:
            issues.append(Issue("error", f"{path.name}:{lineno}", "数值列不是整数"))
            continue
        length, offset, linebases, linewidth = values
        if min(length, offset, linebases, linewidth) < 0:
            negative = True
            continue
        if linebases <= 0 or linewidth < linebases:
            issues.append(Issue("error", f"{path.name}:{lineno}",
                                f"每行碱基/字节不合法：{linebases}/{linewidth}"))
            continue
        if max(length, offset, linebases, linewidth) > INT32_MAX:
            overflow_written = True
        records.append(FaiRecord(parts[0], length, offset, linebases, linewidth))

    if negative:
        issues.append(Issue(
            "error", path.name,
            "发现负数值——这个 .fai 是 32 位工具写的（百合等超大基因组常见）。"
            "请把基因组 FASTA 重排成每行 60 后再重新索引。"))
    if not records:
        if issues:
            return [], issues
        raise WgdiError(f"{path.name} 里没有可用的记录")
    if not negative:
        for prev, cur in zip(records, records[1:]):
            if cur.offset <= prev.offset:
                issues.append(Issue("warning", cur.name, "偏移没有递增，索引可能已损坏"))
                break
        else:
            issues += [i for i in consistency_issues(records) if i.level == "error"][:3]
    if overflow_written:
        issues.append(Issue(
            "warning", path.name,
            f"{sum(1 for r in records if r.int32_unsafe)} 条记录超过 2^31（大基因组正常），"
            "本程序按 64 位处理；但其他 32 位工具仍会读错"))
    return records, issues


def consistency_issues(records: list[FaiRecord], slack: int = 100_000) -> list[Issue]:
    """Catch a `.fai` that contradicts itself.

    The gap between two records is the previous sequence's bytes (newlines
    included) plus the next header. If the declared line width cannot explain
    that gap, the index was produced by something that got the arithmetic wrong
    — exactly what happens to Lilium files built with 32-bit offsets.
    """
    out: list[Issue] = []
    for prev, cur in zip(records, records[1:]):
        lines = -(-prev.length // prev.linebases)
        last_bases = prev.length - (lines - 1) * prev.linebases
        span = (lines - 1) * prev.linewidth + last_bases + 1   # + newline
        gap = cur.offset - prev.offset
        if span > gap:
            out.append(Issue("error", prev.name,
                             f"按 {prev.linebases} 碱基/行计算需要 {span:,} 字节，"
                             f"但到下一条序列只有 {gap:,} 字节：索引自相矛盾"))
        elif gap - span > slack:
            out.append(Issue("warning", prev.name,
                             f"偏移与声明的换行宽度对不上（差 {gap - span:,} 字节），"
                             "索引可能已损坏，建议重新索引"))
    return out


def write_fai(path: Path, records: list[FaiRecord]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        for r in records:
            handle.write(f"{r.name}\t{r.length}\t{r.offset}\t{r.linebases}\t{r.linewidth}\n")
    return path


def uniform_width(records: list[FaiRecord], width: int = DEFAULT_WIDTH) -> bool:
    return all(r.linebases == width for r in records)


def needs_rewrap(records: list[FaiRecord], width: int = DEFAULT_WIDTH) -> tuple[bool, str]:
    """Should the FASTA be re-wrapped before indexing? (why, in plain words)

    Any line width below `WIDE_LINE` is left alone: 50 or 60 columns both index
    fine, and re-wrapping a 30 GB genome costs minutes for no gain. Only very
    wide lines (which push the .fai offsets past 32 bits) are normalised.
    """
    if not records:
        return False, ""
    if any(r.irregular for r in records):
        return True, "序列内部换行宽度不一致，需先重排后才能随机读取"
    singles = [r for r in records if r.single_line]
    if singles:
        return True, (f"{len(singles)} 条序列整条写在一行（如 {singles[0].name}，"
                      f"{singles[0].length:,} bp），任何 32 位工具都会读成负数")
    widths = {r.linebases for r in records}
    if max(widths) < WIDE_LINE:
        return False, ""
    if len(widths) > 1:
        return True, f"各序列换行宽度不一致：{sorted(widths)[:4]}"
    return True, f"当前每行 {sorted(widths)[0]} 碱基，统一为 {width} 更稳妥"


# --- .fai <-> WGDI .len -----------------------------------------------------
def fai_to_len(records: list[FaiRecord], gene_counts: dict[str, int] | None = None) -> str:
    lines = []
    for r in records:
        count = (gene_counts or {}).get(r.name)
        lines.append(f"{r.name}\t{r.length}" + (f"\t{count}" if count is not None else ""))
    return "\n".join(lines) + "\n"


def len_to_fai(records: list[tuple[str, int]]) -> list[FaiRecord]:
    """Best effort: a `.len` has no byte offsets, so they are unknown (0)."""
    return [FaiRecord(name, length, 0, DEFAULT_WIDTH, DEFAULT_WIDTH + 1)
            for name, length in records]
