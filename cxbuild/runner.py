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

The terminal gets a line per command and a warning count, and on a terminal
live progress: a bar for the running step (a real one for Ninja and Make
builds, which count their own progress) and one for the whole command. On failure it
also gets the tail of that command's output. With verbose=True, output is
also streamed live.

In-process work (writing a wheel) is recorded the same
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
from rich.markup import escape
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Column
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
    task: TaskID | None = field(default=None, repr=False)  # its live progress bar, if any

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


# Build tools report their own progress: Ninja "[123/1456] ...", Make "[ 45%] ...".
# MSBuild reports none, so its step shows a spinner and the elapsed time only.
NINJA_PROGRESS = re.compile(r"^\[(\d+)/(\d+)\]")
MAKE_PROGRESS = re.compile(r"^\[\s*(\d+)%\]")


def parse_progress(line: str) -> tuple[int, int] | None:
    """(completed, total) from a build tool's progress prefix, or None."""
    if m := NINJA_PROGRESS.match(line):
        return int(m[1]), int(m[2])
    if m := MAKE_PROGRESS.match(line):
        return int(m[1]), 100
    return None


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
        self.progress: Progress | None = None  # live bars, on a terminal only
        self.overall: TaskID | None = None

    # --- lifecycle -------------------------------------------------------

    def __enter__(self) -> "Runner":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.started = datetime.now()
        self.start_time = time.monotonic()
        self.file = open(self.path, "w", buffering=1, encoding="utf-8")  # line-buffered: readable mid-run
        self.file.write(f"# cxbuild {self.label} (running)\n\n_Started {self.started:%Y-%m-%d %H:%M:%S}_\n")
        # Live progress only on a terminal: inside pip (the backend) output is captured,
        # and --verbose streams the output itself, which a live display would tear.
        if console.is_terminal and not self.verbose:
            self.progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.description}", table_column=Column(no_wrap=True)),
                BarColumn(bar_width=30),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                TextColumn("[dim]{task.fields[line]}", table_column=Column(ratio=1, no_wrap=True, overflow="ellipsis")),
                console=console,
                expand=True,
                transient=True,  # the bars vanish at the end; the step lines above them stay
                redirect_stdout=False,  # capture() redirects the streams itself
                redirect_stderr=False,
            )
            self.progress.start()
            self.overall = self.progress.add_task(f"cxbuild {self.label}", total=None, line="")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.progress is not None:
            self.progress.stop()
        self.file.close()
        if exc is not None and not isinstance(exc, BuildStepError):
            # Not a failed command: a bug or bad config. The report is where it gets seen.
            self.error = exc
            logger.opt(exception=(exc_type, exc, tb)).debug("{} aborted", self.label)
        try:
            self.path.write_text(self.render(), encoding="utf-8")
        except Exception:
            logger.exception("could not write {}", self.path)  # never mask the original error
        self._summarize(exc)

    # --- terminal --------------------------------------------------------

    def display(self, command: list[str], shown: str) -> str:
        """The command as the terminal shows it: the program by name rather than full path."""
        if len(command) > 1 and os.path.isabs(command[0]):
            return shlex.join([Path(command[0]).name, *command[1:]])
        return shown

    def abbreviate(self, text: str) -> str:
        """Shorter paths for the terminal; the report and log keep every command whole.

        The environment's prefix becomes <env>, the solution root becomes relative,
        and the home directory becomes ~, in that order: the environment and the
        solution usually live under home.
        """
        replacements = []
        if sys.prefix != sys.base_prefix:  # in a virtual environment
            replacements.append((str(Path(sys.prefix).resolve()), "<env>"))
        root = str(self.root)
        replacements += [(root + os.sep, ""), (root, "."), (str(Path.home()), "~")]
        for old, new in replacements:
            text = text.replace(old, new)
        return text

    def _link(self, path: Path) -> str:
        """A path the terminal can open: rich emits it as a hyperlink where supported."""
        return f"[link={path.resolve().as_uri()}]{escape(self.where(path))}[/link]"

    def _summarize(self, exc: BaseException | None) -> None:
        records = [p for p in (self.path, self.log_path) if p.exists()]
        where = " · ".join(f"{'report' if p == self.path else 'log'}: {self._link(p)}" for p in records)
        if exc is None:
            total = time.monotonic() - self.start_time
            steps = f"{len(self.steps)} step{'' if len(self.steps) == 1 else 's'}"
            warnings = sum(s.warnings for s in self.steps)
            note = f" · [yellow]{plural(warnings, 'warning')}[/yellow]" if warnings else ""
            failed = [s for s in self.steps if not s.ok]  # tolerated, e.g. by an editable install
            if failed:
                console.print(
                    f"⚠️  [bold yellow]cxbuild {escape(self.label)} finished, but "
                    f"{plural(len(failed), 'step')} failed[/] ({escape(', '.join(s.label for s in failed))})"
                    f" in {total:.1f}s{note}"
                )
            else:
                console.print(f"👍 [bold green]cxbuild {escape(self.label)} finished[/] in {total:.1f}s · {steps}{note}")
        elif isinstance(exc, BuildStepError):
            return  # its panel already names the report and the log
        if where:
            console.print(f"   {where}")

    def expect(self, steps: int) -> None:
        """How many steps this run will take, so the overall bar can show how far along it is."""
        if self.progress is not None and self.overall is not None:
            self.progress.update(self.overall, total=steps)

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
        """Record in-process work, such as writing a wheel, as a step.

        Python-level output (sys.stdout, sys.stderr) is captured like a
        command's. Child processes write to the real file descriptors and
        bypass the capture, so start those with run(); a run() inside a
        capture() is recorded as its own step.
        """
        cwd = Path(cwd or Path.cwd())
        shown = f"(in process) {description or label}"
        step, consume, tail, start = self._start([label], shown, cwd, label, None)
        writer = _LineWriter(consume)
        # Nested steps must keep printing where the console prints now, not into the capture.
        outer = (self.terminal, console._file)  # rich keeps None there to mean "follow sys.stderr"
        self.terminal = console.file = console.file
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
            elif isinstance(e, CxBuildError):  # a problem in the project, not in cxbuild: the message says it all
                step.code = 1
                consume(f"{e}\n")
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
        self.terminal, console.file = outer

    def _start(
        self, command: list[str], shown: str, cwd: Path, label: str, diag_base: Path | None
    ) -> tuple[Step, Callable[[str], None], deque[str], float]:
        step = Step(command, cwd, label, shown)
        self.steps.append(step)
        out = logger.bind(step=step.label)
        out.info("$ {}  (cwd {})", shown, cwd)
        where = self.where(cwd)
        location = "" if where == "." else f"  [dim]({escape(where)})[/]"
        console.print(f"[bold cyan]{escape(step.label)}[/] {escape(self.abbreviate(self.display(command, shown)))}{location}")
        self.file.write(f"\n## {step.label} — {self.where(cwd)}\n\n`$ {shown}`\n\n{LIVE_FENCE}text\n")

        scanner = DiagnosticScanner(Path(diag_base or cwd))
        tail: deque[str] = deque(maxlen=TAIL_LINES)
        echo = self.terminal or sys.stderr  # never a capture()'s redirected stream
        task = self.progress.add_task(step.label, total=None, line="") if self.progress else None

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
            if task is not None:
                self._show(task, line)

        step.task = task
        return step, consume, tail, time.monotonic()

    def _show(self, task: TaskID, line: str) -> None:
        text = line.strip()
        if not text:
            return
        if (done := parse_progress(text)) is not None:
            completed, total = done
            self.progress.update(task, completed=completed, total=total, line=text)
        else:
            self.progress.update(task, line=text)

    def _finish(
        self, step: Step, tail: deque[str], start: float, *, cause: BaseException | None = None, quiet: bool = False
    ) -> None:
        step.elapsed = time.monotonic() - start
        if step.task is not None:
            self.progress.remove_task(step.task)
            if step.ok and self.overall is not None:
                self.progress.advance(self.overall)
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
            console.print(Panel(f"[red]{escape(str(error))}[/]", title="cxbuild error"))
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
