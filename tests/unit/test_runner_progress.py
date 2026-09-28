"""cxbuild.runner: the live progress display.

On a terminal the runner shows a bar per running step (a real one for Ninja and
Make builds) and one for the whole command. Anywhere else, inside pip for
instance, it shows nothing, and the reports never contain bar redraws.
"""

from __future__ import annotations

import io
import sys

import pytest
from rich.console import Console

from cxbuild import runner as runner_module
from cxbuild.runner import Runner, parse_progress

NINJA_BUILD = "import time\nfor i in range(1, 5):\n    print(f'[{i}/4] Building CXX object f{i}.o', flush=True)\n    time.sleep(0.05)\n"


@pytest.mark.parametrize(
    "line, expected",
    [
        ("[123/1456] Building CXX object src/skia.cpp.o", (123, 1456)),
        ("[1/1] Linking CXX shared module _core.so", (1, 1)),
        ("[ 45%] Building CXX object CMakeFiles/x.dir/a.cpp.o", (45, 100)),
        ("[100%] Built target cxb_simple_core", (100, 100)),
        ("-- Configuring done", None),
        ("  main.cpp", None),  # MSBuild: no progress to show
        ("warning: [123/456] inside a message", None),  # only a prefix counts
    ],
)
def test_parse_progress(line, expected):
    assert parse_progress(line) == expected


@pytest.fixture
def terminal(monkeypatch) -> io.StringIO:
    """Make the runner believe it is writing to a terminal, and capture what it draws."""
    out = io.StringIO()
    monkeypatch.setattr(runner_module, "console", Console(file=out, force_terminal=True, width=120))
    return out


def test_progress_runs_on_a_terminal(tmp_path, terminal):
    with Runner(tmp_path, "build") as runner:
        assert runner.progress is not None
        runner.expect(2)
        runner.run([sys.executable, "-c", NINJA_BUILD], tmp_path, label="build")
        with runner.capture("wheel", cwd=tmp_path):
            runner.run([sys.executable, "-c", "print('[1/1] nested')"], tmp_path, label="nested")
        overall = runner.progress.tasks[0]
        assert (overall.completed, overall.total) == (3, 2)  # a nested step counts too
        assert [t.description for t in runner.progress.tasks] == ["cxbuild build"]  # step bars removed when done
    drawn = terminal.getvalue()
    assert drawn.count("ok") == 3  # the step lines survive the live display


def test_progress_bar_follows_ninja(tmp_path, terminal, monkeypatch):
    seen = []
    with Runner(tmp_path, "build") as runner:
        original = runner._show
        monkeypatch.setattr(runner, "_show", lambda task, line: (original(task, line), seen.append(
            (runner.progress._tasks[task].completed, runner.progress._tasks[task].total))))
        runner.run([sys.executable, "-c", NINJA_BUILD], tmp_path, label="build")
    assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_no_progress_off_a_terminal(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_module, "console", Console(file=io.StringIO(), force_terminal=False))
    with Runner(tmp_path, "build") as runner:
        assert runner.progress is None
        runner.run([sys.executable, "-c", NINJA_BUILD], tmp_path, label="build")


def test_no_progress_when_verbose(tmp_path, terminal):
    with Runner(tmp_path, "build", verbose=True) as runner:
        assert runner.progress is None  # verbose streams the output; a live display would tear it


def test_report_has_no_progress_drawing(tmp_path, terminal):
    with Runner(tmp_path, "build") as runner:
        runner.run([sys.executable, "-c", NINJA_BUILD], tmp_path, label="build")
    report = (tmp_path / "_cxbuild" / "cxbuild_report.md").read_text()
    assert "\x1b[" not in report and "━" not in report
    assert "[4/4] Building CXX object f4.o" in report  # the output itself is all there
