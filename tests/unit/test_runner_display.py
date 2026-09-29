"""cxbuild.runner: what the terminal shows. Short, safe step lines, and a closing summary.

The report and log keep every command whole; only the terminal abbreviates.
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest
from rich.console import Console

from cxbuild import runner as runner_module
from cxbuild.runner import BuildStepError, CxBuildError, Runner


@pytest.fixture
def screen(monkeypatch) -> io.StringIO:
    out = io.StringIO()
    monkeypatch.setattr(runner_module, "console", Console(file=out, force_terminal=False, width=400))
    return out


def plain(out: io.StringIO) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\]8;[^\x1b]*\x1b\\\\", "", out.getvalue())


def test_step_lines_abbreviate_paths(tmp_path, screen):
    root = tmp_path / "solution"
    (root / "pkg" / "imgui").mkdir(parents=True)
    with Runner(root, "develop") as runner:
        runner.run([sys.executable, "-c", f"print({str(root / 'pkg')!r})"], root / "pkg" / "imgui", label="develop imgui")
    first = plain(screen).splitlines()[0]
    assert first.startswith(f"develop imgui {Path(sys.executable).name} -c")  # the program by name
    assert str(root) not in first  # solution paths relative
    assert first.endswith("(pkg/imgui)")  # the working directory, relative, only when not the root
    # ... while the report keeps the exact command
    report = (root / "_cxbuild" / "cxbuild_report.md").read_text()
    assert sys.executable in report


def test_markup_in_a_command_is_printed_literally(tmp_path, screen):
    with Runner(tmp_path, "build") as runner:
        runner.run([sys.executable, "-c", "print('[bold]not markup[/bold]')"], tmp_path, label="build")
    assert "[bold]not markup[/bold]" in plain(screen)


def test_a_successful_run_ends_with_a_summary(tmp_path, screen):
    (tmp_path / "_cxbuild").mkdir()
    (tmp_path / "_cxbuild" / "cxbuild.log").write_text("log\n")
    with Runner(tmp_path, "develop") as runner:
        runner.run([sys.executable, "-c", "print('src/a.cpp:1:1: warning: w [-Wx]')"], tmp_path, label="build")
    lines = plain(screen).splitlines()
    assert re.fullmatch(r"👍 cxbuild develop finished in \d+\.\ds · 1 step · 1 warning", lines[-2]), lines[-2]
    assert lines[-1].strip() == "report: _cxbuild/cxbuild_report.md · log: _cxbuild/cxbuild.log"


def test_the_summary_links_the_files(tmp_path, monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(runner_module, "console", Console(file=out, force_terminal=True, width=200))
    with Runner(tmp_path, "build"):
        pass
    assert (tmp_path / "_cxbuild" / "cxbuild_report.md").resolve().as_uri() in out.getvalue()


def test_a_failed_step_adds_no_summary(tmp_path, screen):
    with pytest.raises(BuildStepError):
        with Runner(tmp_path, "build") as runner:
            runner.run([sys.executable, "-c", "raise SystemExit(3)"], tmp_path, label="build")
    text = plain(screen)
    assert "finished" not in text
    assert text.count("cxbuild_report.md") == 1  # named once, in the error panel


def test_other_errors_still_point_at_the_report(tmp_path, screen):
    with pytest.raises(CxBuildError):
        with Runner(tmp_path, "develop"):
            raise CxBuildError("project not found: nope")
    text = plain(screen)
    assert "finished" not in text
    assert "report: _cxbuild/cxbuild_report.md" in text
