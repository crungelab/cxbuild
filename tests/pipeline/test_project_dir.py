"""Running cxbuild from inside a project, the way per-package environments and
cxtest do: `cd pkg/second && cxbuild develop` develops just that project into
the active environment, while the build, the reports and the artifacts stay at
the solution root, shared by every project."""

from __future__ import annotations

import pytest

from conftest import run_cxbuild, run_python

pytestmark = pytest.mark.pipeline


def test_develop_from_a_project_develops_that_project(solution):
    result = run_cxbuild(solution, "develop", cwd=solution / "pkg" / "second")
    assert result.returncode == 0, result

    report = result.report()  # at the solution root, not in the project
    assert "| pip second |" in report
    assert "| pip cxb_simple |" not in report and "| pip third |" not in report
    assert not (solution / "pkg" / "second" / "_cxbuild").exists()
    assert (solution / "_cxbuild" / "artifacts" / "cxbns" / "second").is_dir()

    check = run_python("import cxbns.second; print(cxbns.second.greet('here'))", cwd=solution.parent)
    assert check.returncode == 0, check.stderr
    assert check.stdout.strip() == "hello, here"


def test_develop_from_deeper_inside_a_project(solution):
    result = run_cxbuild(solution, "develop", cwd=solution / "pkg" / "second" / "cxbns" / "second")
    assert result.returncode == 0, result
    assert "| pip second |" in result.report()


def test_a_name_still_wins_from_inside_a_project(solution):
    result = run_cxbuild(solution, "develop", "cxb_simple", cwd=solution / "pkg" / "second")
    assert result.returncode == 0, result
    report = result.report()
    assert "| pip cxb_simple |" in report and "| pip second |" not in report


def test_outside_a_solution_is_a_clean_error(tmp_path):
    result = run_cxbuild(tmp_path, "develop")
    assert result.returncode == 1, result
    assert "not inside a cxbuild solution" in result.output
    assert "Traceback" not in result.output
