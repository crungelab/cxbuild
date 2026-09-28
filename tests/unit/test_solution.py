"""cxbuild.solution: finding the solution, and the project cxbuild was started in."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cxbuild.runner import CxBuildError
from cxbuild.solution import Solution, find_solution_root

SOLUTION = Path(__file__).parent.parent / "pipeline" / "solution"


@pytest.fixture
def solution(tmp_path) -> Path:
    root = tmp_path / "solution"
    shutil.copytree(SOLUTION, root)
    return root.resolve()


@pytest.mark.parametrize("start", [".", "pkg", "pkg/second", "pkg/second/cxbns/second", "pkg/cxb_simple/src"])
def test_the_solution_is_found_from_anywhere_inside_it(solution, start):
    assert find_solution_root(solution / start) == solution


def test_a_project_pyproject_is_not_mistaken_for_the_solution(solution):
    # pkg/second has a pyproject.toml too, with [tool.cxbuild] but no `projects`.
    assert (solution / "pkg/second/pyproject.toml").is_file()
    assert find_solution_root(solution / "pkg/second") == solution


def test_an_unreadable_pyproject_on_the_way_up_is_skipped(solution):
    (solution / "pkg" / "pyproject.toml").write_text("[not toml")
    assert find_solution_root(solution / "pkg/second") == solution


def test_outside_a_solution_is_an_error(tmp_path):
    with pytest.raises(CxBuildError, match="not inside a cxbuild solution"):
        find_solution_root(tmp_path)


@pytest.mark.parametrize(
    "start, expected",
    [
        ("pkg/second", "cxbns-second"),
        ("pkg/second/cxbns/second", "cxbns-second"),
        ("pkg/cxb_simple/src", "cxb_simple"),
        (".", None),
        ("pkg", None),
    ],
)
def test_project_containing(solution, start, expected):
    project = Solution(solution, runner=None).project_containing(solution / start)
    assert (project.name if project else None) == expected
