"""`cxbuild develop` end to end: cmake configure/build/install, then pip -e per
project through cxbuild's backend, with the report and log as the record."""

from __future__ import annotations

import pytest

from conftest import PROJECTS, run_python

pytestmark = pytest.mark.pipeline


def test_develop_builds_and_installs_every_project(cxbuild, solution):
    result = cxbuild("develop")
    assert result.returncode == 0, result

    check = run_python(
        "import cxb_simple, cxbns.second, cxbns.third; "
        "print(cxb_simple.add(2, 3), cxbns.second.greet('cxbuild'), cxbns.third.triple(3))",
        cwd=solution.parent,  # not the solution: import what pip installed, not the source tree
    )
    assert check.returncode == 0, check.stderr
    assert check.stdout.strip() == "5 hello, cxbuild 9"


def test_develop_report_records_every_step(cxbuild):
    result = cxbuild("develop")
    assert result.returncode == 0, result

    report = result.report()
    assert report.startswith("# cxbuild develop — ✅ passed")
    for label in ("configure", "build", "install", *(f"develop {p}" for p in PROJECTS)):
        assert f"| {label} |" in report, f"no summary row for {label!r}"
    assert "[cxbuild.log](cxbuild.log)" in report

    log = result.log()
    assert "| configure  |" in log  # command output is tagged with its step


def test_develop_backend_reports_sit_beside_the_cli_report(cxbuild):
    result = cxbuild("develop")
    assert result.returncode == 0, result

    header = result.report().splitlines()[2]
    for project in PROJECTS:
        # The hooks pip ran wrote their record into the solution's _cxbuild/, not the project's.
        assert f"[{project}_report.md]({project}_report.md)" in header
        backend = result.report(project)
        assert backend.startswith("# cxbuild build_editable — ✅ passed")
        assert f"- **editable wheel {project}**:" in backend
        assert not (result.root / "pkg" / project / "_cxbuild").exists()


def test_develop_selects_one_project(cxbuild):
    result = cxbuild("develop", "cxbns-second")  # by distribution name
    assert result.returncode == 0, result

    report = result.report()
    assert "| develop second |" in report  # steps and reports are named by project directory
    for other in ("cxb_simple", "third"):
        assert f"| develop {other} |" not in report
        assert not (result.state_dir / f"{other}_report.md").exists()


def test_develop_unknown_project_is_a_clean_error(cxbuild):
    result = cxbuild("develop", "nosuchproject")
    assert result.returncode == 1, result
    assert "project not found: nosuchproject" in result.output
    assert "Traceback" not in result.output  # a message for the user, not a crash
    # Checked before any work: cmake never configured.
    assert not (result.state_dir / "build" / "CMakeCache.txt").exists()


def test_develop_compile_error_fails_with_diagnostics(cxbuild, solution):
    source = solution / "pkg" / "cxb_simple" / "src" / "main.cpp"
    text = source.read_text()
    assert "a + b" in text
    source.write_text(text.replace("a + b", "a + undeclared_name"))

    result = cxbuild("develop")
    assert result.returncode == 1, result
    assert "build failed" in result.output          # the error panel on the terminal
    assert "cxbuild_report.md" in result.output     # ...which says where the record is

    report = result.report()
    assert report.startswith("# cxbuild develop — ❌ failed")
    assert "## Diagnostics" in report
    assert "pkg/cxb_simple/src/main.cpp" in report  # grouped under the file, relative to the root
    assert "undeclared_name" in report              # GCC, Clang and MSVC all name the identifier
    assert "| develop " not in report                   # nothing after the failed build ran
