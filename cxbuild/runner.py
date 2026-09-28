"""Run cxbuild's commands (cmake configure/build) with their output recorded.

cxbuild usually runs as a PEP 517 backend inside pip or hatch, which hide the
backend's output unless the build fails (and sometimes even then). So the
files in <root>/_cxbuild/ are the record of a build:

* <name>_report.md: grows a section per command while the run is in
  progress (so `tail -f` works). When the run ends it is rewritten as a
  report: a summary table, artifacts, compiler diagnostics grouped by file,
  any Python error that aborted the build, then each command's output in a
  collapsible block. Failed commands are expanded. Reports that other
  processes wrote into _cxbuild/ during the run (the backend's, when the CLI
  runs pip) are linked from the header.
* <name>.log: loguru at DEBUG, including every line of command output,
  tagged with its step. Configured by logsetup.configure_logging().

The terminal gets a line per command and a warning count. On failure it
also gets the tail of that command's output. With verbose=True, output is
also streamed live.

In-process work (setuptools.setup() in the build hooks) is recorded the same
way with capture().

Errors raise BuildStepError. Nothing here exits; that is the CLI's job.
"""

from __future__ import annotations

import html
import os
import re
import shlex
import io
import subprocess
import sys
import time
import traceback
from collections import Counter, defaultdict, deque
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, Mapping

from loguru import logger
from rich.panel import Panel
from rich.text import Text

from .console import console

STATE_DIR = "_cxbuild"  # per-run state, gitignored (like _cxbind/ and _cxtest/)
DEFAULT_NAME = "cxbuild"  # -> cxbuild.log, cxbuild_report.md
TAIL_LINES = 60
LIVE_FENCE = "``````"  # while streaming; the final rewrite sizes each fence exactly

# loguru's default line format, from tools (e.g. cxbind) that cmake runs.
WARNING_MARKERS = (" | WARNING ", " | ERROR ", " | CRITICAL ")

# Compilers colour their output when CLICOLOR_FORCE or CMAKE_COLOR_DIAGNOSTICS say so.
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# GCC / Clang:  path:line[:col]: warning: message [-Wflag]
GNU_DIAG = re.compile(
    r"^(?P<file>(?:[A-Za-z]:)?[^:\n]+):(?P<line>\d+):(?:(?P<col>\d+):)?\s"
    r"(?P<kind>warning|error|fatal error): (?P<msg>.*?)"
    r"(?: \[(?P<code>-W[^\],]+)[^\]]*\])?$"
)
# MSVC:  path(line[,col]): warning C4244: message [project.vcxproj]
MSVC_DIAG = re.compile(
    r"^\s*(?P<file>.+?)\((?P<line>\d+)(?:,(?P<col>\d+))?\)\s?: "
    r"(?P<kind>warning|error|fatal error) (?P<code>[A-Z]+\d+): (?P<msg>.*?)"
    r"(?: \[[^\]]*\])?$"
)
# CMake:  "CMake Warning (dev) at CMakeLists.txt:12 (foo):" then the message, indented.
CMAKE_DIAG = re.compile(
    r"^CMake (?:Deprecation )?(?P<kind>Warning|Error)(?: \(dev\))?"
    r"(?: at (?P<file>.+?):(?P<line>\d+))?"
)


@dataclass(frozen=True)
class Diagnostic:
    file: Path | None
    line: int
    col: int | None
    kind: str  # "warning" or "error"
    code: str  # "-Wunused-parameter", "C4244", "cmake", or ""
    message: str


class DiagnosticScanner:
    """Recognises compiler and CMake diagnostics, one output line at a time."""

    def __init__(self, base: Path) -> None:
        self.base = base  # relative paths in diagnostics are relative to this
        self.pending_cmake: tuple[str, str | None, int] | None = None

    def feed(self, line: str) -> Diagnostic | None:
        text = line.rstrip()
        if self.pending_cmake is not None:
            if not text:
                return None  # CMake puts a blank line between header and message
            kind, file, lineno = self.pending_cmake
            self.pending_cmake = None
            return self.make(file, lineno, None, kind, "cmake", text.strip())
        if m := CMAKE_DIAG.match(text):
            self.pending_cmake = (m["kind"].lower(), m["file"], int(m["line"] or 0))
            return None
        if m := GNU_DIAG.match(text) or MSVC_DIAG.match(text):
            col = int(m["col"]) if m["col"] else None
            return self.make(m["file"], int(m["line"]), col, m["kind"], m["code"] or "", m["msg"])
        return None

    def make(self, file: str | None, line: int, col: int | None, kind: str, code: str, msg: str) -> Diagnostic:
        path = None
        if file:
            path = Path(file.strip())
            if not path.is_absolute():
                path = self.base / path
            path = path.resolve()
        kind = "error" if kind.endswith("error") else "warning"
        return Diagnostic(path, line, col, kind, code, msg)


@dataclass
class Step:
    command: list[str]
    cwd: Path
    label: str
    shown: str  # the command as displayed: shell-quoted, or "(in process) ..."
    lines: list[str] = field(default_factory=list)
    code: int | None = None
    elapsed: float = 0.0
    diagnostics: set[Diagnostic] = field(default_factory=set)
    tool_warnings: int = 0  # loguru WARNING+ lines from tools cmake ran

    @property
    def ok(self) -> bool:
        return self.code == 0

    @property
    def warnings(self) -> int:
        return self.tool_warnings + sum(d.kind == "warning" for d in self.diagnostics)

    @property
    def errors(self) -> int:
        return sum(d.kind == "error" for d in self.diagnostics)


class CxBuildError(Exception):
    """An error cxbuild reports to the user: the CLI prints the message, not a traceback."""


class BuildStepError(CxBuildError):
    """A command failed. The message names the report and log, since pip may show nothing else."""

    def __init__(self, step: Step, report: Path, log: Path) -> None:
        self.step = step
        super().__init__(
            f"{step.label} failed (exit {step.code}): {step.shown}\n"
            f"  cwd:    {step.cwd}\n"
            f"  report: {report}\n"
            f"  log:    {log}"
        )


class _LineWriter(io.TextIOBase):
    """A text stream that hands complete lines to a callback."""

    def __init__(self, consume: Callable[[str], None]) -> None:
        self.consume = consume
        self.pending = ""

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        *lines, self.pending = (self.pending + s).split("\n")
        for line in lines:
            self.consume(line + "\n")
        return len(s)

    def close(self) -> None:
        if self.pending:
            self.consume(self.pending + "\n")
            self.pending = ""
        super().close()


def fence_for(text: str) -> str:
    """A code fence longer than any backtick run inside `text`."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}" if n else ""


def table_cell(text: str) -> str:
    return html.escape(text).replace("|", "\\|")


class Runner:
    def __init__(
        self, root: Path, label: str = "build", verbose: bool = False, name: str = DEFAULT_NAME
    ) -> None:
        self.root = Path(root).resolve()
        self.label = label  # the CLI command or PEP 517 hook: "build", "build_wheel", ...
        self.verbose = verbose
        self.path = self.root / STATE_DIR / f"{name}_report.md"
        self.log_path = self.root / STATE_DIR / f"{name}.log"
        self.steps: list[Step] = []
        self.diagnostics: Counter[Diagnostic] = Counter()  # occurrences, across translation units
        self.artifacts: list[tuple[str, Path]] = []
        self.error: BaseException | None = None
        self.terminal = None  # the real stderr while capture() redirects sys.stderr

    # --- lifecycle -------------------------------------------------------

    def __enter__(self) -> "Runner":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.started = datetime.now()
        self.start_time = time.monotonic()
        self.file = open(self.path, "w", buffering=1, encoding="utf-8")  # line-buffered: readable mid-run
        self.file.write(f"# cxbuild {self.label} (running)\n\n_Started {self.started:%Y-%m-%d %H:%M:%S}_\n")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.file.close()
        if exc is not None and not isinstance(exc, BuildStepError):
            # Not a failed command: a bug or bad config. The report is where it gets seen.
            self.error = exc
            logger.opt(exception=(exc_type, exc, tb)).debug("{} aborted", self.label)
        try:
            self.path.write_text(self.render(), encoding="utf-8")
        except Exception:
            logger.exception("could not write {}", self.path)  # never mask the original error

    def add_artifact(self, label: str, path: Path) -> None:
        self.artifacts.append((label, Path(path)))

    # --- running ---------------------------------------------------------

    def run(
        self,
        command: list[str],
        cwd: Path,
        *,
        label: str | None = None,
        diag_base: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Step:
        """Run `command`. Relative paths in its diagnostics resolve against
        `diag_base`, which defaults to `cwd`. For `cmake --build`, pass the
        build directory, because that is where the compiler runs."""
        command = [os.fspath(part) for part in command]  # callers pass Paths
        cwd = Path(cwd)
        step, consume, tail, start = self._start(
            command, shlex.join(command), cwd, label or Path(command[0]).name, diag_base
        )
        try:
            with subprocess.Popen(
                command,
                cwd=cwd,
                env=None if env is None else dict(env),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # one stream, in the order it happened
                text=True,
                errors="replace",
                bufsize=1,
            ) as proc:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    consume(raw)
            step.code = proc.returncode
        except OSError as e:  # typically: cmake not on PATH
            consume(f"cxbuild: could not run {command[0]}: {e}\n")
            step.code = -1
        self._finish(step, tail, start)
        return step

    @contextmanager
    def capture(self, label: str, description: str = "", cwd: Path | None = None) -> Iterator[Step]:
        """Record in-process work, such as setuptools.setup(), as a step.

        Python-level output (sys.stdout, sys.stderr) is captured like a
        command's. Child processes write to the real file descriptors and
        bypass the capture, so start those with run(); a run() inside a
        capture() is recorded as its own step.
        """
        cwd = Path(cwd or Path.cwd())
        shown = f"(in process) {description or label}"
        step, consume, tail, start = self._start([label], shown, cwd, label, None)
        writer = _LineWriter(consume)
        outer = self.terminal
        self.terminal = console.file = outer or sys.stderr  # nested steps print to the terminal
        try:
            # contextualize: log records from the work itself are tagged with this step too
            with redirect_stdout(writer), redirect_stderr(writer), logger.contextualize(step=label):
                yield step
        except BuildStepError:  # a run() inside failed and already reported
            self._restore_terminal(outer)
            writer.close()
            step.code = 1
            self._finish(step, tail, start, quiet=True)
            raise
        except (Exception, SystemExit) as e:
            self._restore_terminal(outer)
            writer.close()
            if isinstance(e, SystemExit):  # distutils/setuptools report errors this way
                step.code = e.code if isinstance(e.code, int) and e.code else 1
                consume(f"{e.code}\n" if e.code not in (None, 0) else "SystemExit\n")
            else:
                step.code = 1
                consume("".join(traceback.format_exception(type(e), e, e.__traceback__)))
            self._finish(step, tail, start, cause=e)
        else:
            self._restore_terminal(outer)
            writer.close()
            step.code = 0
            self._finish(step, tail, start)

    def _restore_terminal(self, outer) -> None:
        self.terminal = outer
        console.file = outer  # None: back to following sys.stderr

    def _start(
        self, command: list[str], shown: str, cwd: Path, label: str, diag_base: Path | None
    ) -> tuple[Step, Callable[[str], None], deque[str], float]:
        step = Step(command, cwd, label, shown)
        self.steps.append(step)
        out = logger.bind(step=step.label)
        out.info("$ {}  (cwd {})", shown, cwd)
        console.print(f"[bold cyan]{step.label}[/] {shown}  [dim]{cwd}[/]")
        self.file.write(f"\n## {step.label} — {self.where(cwd)}\n\n`$ {shown}`\n\n{LIVE_FENCE}text\n")

        scanner = DiagnosticScanner(Path(diag_base or cwd))
        tail: deque[str] = deque(maxlen=TAIL_LINES)
        echo = self.terminal or sys.stderr  # never a capture()'s redirected stream

        def consume(raw: str) -> None:
            line = ANSI.sub("", raw)
            self.file.write(line)
            step.lines.append(line)
            tail.append(line)
            out.debug(line.rstrip("\n"))
            if (diag := scanner.feed(line)) is not None:
                step.diagnostics.add(diag)
                self.diagnostics[diag] += 1
            elif any(marker in line for marker in WARNING_MARKERS):
                step.tool_warnings += 1
            if self.verbose:
                echo.write(line)

        return step, consume, tail, time.monotonic()

    def _finish(
        self, step: Step, tail: deque[str], start: float, *, cause: BaseException | None = None, quiet: bool = False
    ) -> None:
        step.elapsed = time.monotonic() - start
        self.file.write(f"{LIVE_FENCE}\n\n_exit {step.code} · {step.elapsed:.1f}s_\n")
        logger.bind(step=step.label).info(
            "exit {} in {:.1f}s, {} warning(s), {} error(s)", step.code, step.elapsed, step.warnings, step.errors
        )
        if not step.ok:
            if quiet:
                return
            if not self.verbose:
                console.print(Panel(Text("".join(tail)), title=f"last {len(tail)} lines of {step.label}"))
            error = BuildStepError(step, self.path, self.log_path)
            console.print(Panel(f"[red]{error}[/]", title="cxbuild error"))
            raise error from cause

        note = f", [yellow]{plural(step.warnings, 'warning')}[/yellow] in {self.path.name}" if step.warnings else ""
        console.print(f"  [green]ok[/] [dim]{step.elapsed:.1f}s[/]{note}")

    # --- rendering -------------------------------------------------------

    def where(self, path: Path | None) -> str:
        if path is None:
            return "(no location)"
        try:
            rel = path.resolve().relative_to(self.root)
        except ValueError:
            return str(path)
        return rel.as_posix() if rel.parts else "."

    def link(self, path: Path) -> str:
        """A link target relative to the report, so it works in the preview."""
        try:
            return Path(os.path.relpath(path.resolve(), self.path.parent)).as_posix()
        except ValueError:  # Windows, different drive
            return path.resolve().as_uri()

    def render(self) -> str:
        passed = self.error is None and all(s.ok for s in self.steps)
        total = time.monotonic() - self.start_time
        links = [self.log_path] if self.log_path.exists() else []
        links += self.sibling_reports()
        log = "".join(f" · [{p.name}]({self.link(p)})" for p in links)
        out = [
            f"# cxbuild {self.label} — {'✅ passed' if passed else '❌ failed'}\n",
            f"_{self.started:%Y-%m-%d %H:%M:%S} · {total:.1f}s · root `{self.root}`_{log}\n",
            self.render_summary(),
            self.render_error(),
            self.render_artifacts(),
            self.render_diagnostics(),
            "## Steps\n" if self.steps else "",
            *(self.render_step(i, s) for i, s in enumerate(self.steps, start=1)),
        ]
        return "\n".join(part for part in out if part)

    def sibling_reports(self) -> list[Path]:
        """Other reports in _cxbuild/ written since this run started."""
        started = self.started.timestamp()
        return sorted(
            p for p in self.path.parent.glob("*_report.md")
            if p != self.path and p.stat().st_mtime >= started
        )

    def render_summary(self) -> str:
        if not self.steps:
            return ""
        rows = [
            "## Summary\n",
            "| # | Step | Where | Result | Time | Warnings |",
            "|--:|------|-------|--------|-----:|---------:|",
        ]
        for i, s in enumerate(self.steps, start=1):
            result = "✅ ok" if s.ok else f"❌ exit {s.code}"
            if s.errors:
                result += f" · {plural(s.errors, 'error')}"
            rows.append(
                f"| {i} | {s.label} | {self.where(s.cwd)} | {result} | "
                f"{s.elapsed:.1f}s | {s.warnings or ''} |"
            )
        return "\n".join(rows) + "\n"

    def render_error(self) -> str:
        if self.error is None:
            return ""
        text = "".join(traceback.format_exception(type(self.error), self.error, self.error.__traceback__))
        fence = fence_for(text)
        return f"## Error\n\n{fence}text\n{text}{fence}\n"

    def render_artifacts(self) -> str:
        if not self.artifacts:
            return ""
        rows = ["## Artifacts\n"]
        for label, path in self.artifacts:
            name = self.where(path)
            target = f"[{name}]({self.link(path)})" if path.exists() else f"`{name}` (missing)"
            rows.append(f"- **{label}**: {target}")
        return "\n".join(rows) + "\n"

    def render_diagnostics(self) -> str:
        if not self.diagnostics:
            return ""
        by_file: dict[Path | None, list[Diagnostic]] = defaultdict(list)
        for diag in self.diagnostics:
            by_file[diag.file].append(diag)
        warnings = sum(d.kind == "warning" for d in self.diagnostics)
        errors = len(self.diagnostics) - warnings
        codes = Counter(d.code for d in self.diagnostics if d.kind == "warning" and d.code)

        summary = ", ".join(p for p in (plural(errors, "error"), plural(warnings, "warning")) if p)
        out = ["## Diagnostics\n", f"{summary} in {plural(len(by_file), 'file')}; repeats merged (× column).\n"]
        if codes:
            out.append("Most frequent: " + ", ".join(f"`{c}` ×{n}" for c, n in codes.most_common(5)) + "\n")

        def order(item: tuple[Path | None, list[Diagnostic]]):
            file, diags = item
            return (-sum(d.kind == "error" for d in diags), -len(diags), str(file))

        for file, diags in sorted(by_file.items(), key=order):
            errs = sum(d.kind == "error" for d in diags)
            counts = ", ".join(p for p in (plural(errs, "error"), plural(len(diags) - errs, "warning")) if p)
            out += [
                f"<details{' open' if errs else ''}>\n"
                f"<summary>{html.escape(self.where(file))} — {counts}</summary>\n",
                "| Line | Kind | Code | Message | × |",
                "|-----:|------|------|---------|--:|",
            ]
            for d in sorted(diags, key=lambda d: (d.line, d.col or 0, d.message)):
                if file is not None and file.exists() and d.line:
                    line = f"[{d.line}]({self.link(file)}#L{d.line})"
                else:
                    line = str(d.line or "")
                kind = "❌ error" if d.kind == "error" else "⚠️ warning"
                code = f"`{d.code}`" if d.code else ""
                n = self.diagnostics[d]
                out.append(f"| {line} | {kind} | {code} | {table_cell(d.message)} | {n if n > 1 else ''} |")
            out.append("\n</details>\n")
        return "\n".join(out)

    def render_step(self, index: int, step: Step) -> str:
        text = "".join(step.lines)
        fence = fence_for(text)
        result = "exit 0" if step.ok else f"exit {step.code}"
        extra = "".join(
            f" · {p}" for p in (plural(step.warnings, "warning"), plural(step.errors, "error")) if p
        )
        summary = html.escape(f"Output — {len(step.lines)} lines · {result} · {step.elapsed:.1f}s{extra}")
        body = text if text.endswith("\n") or not text else text + "\n"
        return (
            f"### {index}. {step.label} — {self.where(step.cwd)}\n\n"
            f"`$ {step.shown}`\n\n"
            f"<details{'' if step.ok else ' open'}>\n<summary>{summary}</summary>\n\n"
            f"{fence}text\n{body}{fence}\n\n"
            "</details>\n"
        )
