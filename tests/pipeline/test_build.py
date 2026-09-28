"""`cxbuild build`: cmake once for the solution, then one wheel per project in dist/.

What the wheels contain is checked in test_wheel_contents.py, which installs
them; this covers the command: the files it writes, its report, and failing
early on a bad pyproject.toml.
"""

from __future__ import annotations

import re
import sys

import pytest

from conftest import PROJECTS, copy_solution, run_cxbuild

pytestmark = pytest.mark.pipeline

CP = f"cp{sys.version_info.major}{sys.version_info.minor}"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    result = run_cxbuild(copy_solution(tmp_path_factory.mktemp("built")), "build")
    assert result.returncode == 0, result
    return result


def test_one_wheel_per_project(built):
    wheels = sorted(p.name for p in (built.root / "dist").iterdir())
    expected = [re.sub(r"[-_.]+", "_", name).lower() for name in PROJECTS.values()]
    assert [w.split("-")[0] for w in wheels] == sorted(expected), wheels
    for wheel in wheels:
        # name-version-interpreter-abi-platform.whl, for this interpreter, unrepaired
        assert re.fullmatch(rf"[a-z0-9_]+-0\.0\.1-{CP}-{CP}t?-[a-z0-9_]+\.whl", wheel), wheel
        assert "manylinux" not in wheel and "-any." not in wheel


def test_report_records_the_build_and_the_wheels(built):
    report = built.report()
    assert report.startswith("# cxbuild build — ✅ passed")
    for label in ("configure", "build", "install", *(f"wheel {p}" for p in PROJECTS)):
        assert f"| {label} |" in report, f"no summary row for {label!r}"
    for project in PROJECTS:
        assert f"- **wheel {project}**: [dist/" in report  # linked, and it exists


def test_nothing_is_built_inside_the_projects(built):
    # No setuptools anymore on this route: no build/, dist/ or egg-info in the project directories.
    for project in PROJECTS:
        leftovers = [p.name for p in (built.root / "pkg" / project).iterdir() if p.name in ("build", "dist") or p.name.endswith(".egg-info")]
        assert not leftovers, (project, leftovers)


def test_old_wheels_are_cleaned_away(cxbuild, solution):
    stale = solution / "dist" / "cxb_simple-0.0.0-cp30-cp30-linux_x86_64.whl"
    stale.parent.mkdir()
    stale.write_bytes(b"from an older build")
    result = cxbuild("build")
    assert result.returncode == 0, result
    assert not stale.exists()


def test_bad_pyproject_fails_before_cmake(cxbuild, solution):
    pyproject = solution / "pkg" / "cxb_simple" / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('readme = "README.md"', 'readme = "MISSING.md"'))

    result = cxbuild("build")
    assert result.returncode == 1, result
    assert "readme: 'MISSING.md' not found" in result.output
    assert "Traceback" not in result.output
    assert not (result.state_dir / "build" / "CMakeCache.txt").exists()  # failed before configuring
