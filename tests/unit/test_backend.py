"""cxbuild.backend: the PEP 517 hooks, called directly the way pip calls them.

The wheel hooks are exercised for real by the pipeline tests (pip calls them
during `cxbuild develop`); these cover the light hooks and what happens when a
hook is called without cxbuild having built anything.
"""

from __future__ import annotations

import shutil
from importlib.metadata import Distribution
from pathlib import Path

import pytest

from cxbuild import activity, backend
from cxbuild.metadata import ProjectMetadata
from cxbuild.pyproject import PyProject
from cxbuild.runner import CxBuildError

FIXTURE = Path(__file__).parent.parent / "pipeline" / "solution" / "pkg" / "cxb_simple"


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    """A copy of the fixture project as the current directory, with no cxbuild run in sight."""
    root = tmp_path / "cxb_simple"
    shutil.copytree(FIXTURE, root)
    monkeypatch.chdir(root)
    for name in ("CBX_ACTIVITY", "CXBUILD_ROOT", "CXBUILD_VERBOSE", "CXBUILD_LOG_UDP"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(activity, "_activity", None)
    return root


@pytest.mark.parametrize("hook", ["get_requires_for_build_wheel", "get_requires_for_build_editable", "get_requires_for_build_sdist"])
def test_nothing_else_is_required_to_build(project, hook):
    assert getattr(backend, hook)(None) == []


@pytest.mark.parametrize("hook", ["prepare_metadata_for_build_wheel", "prepare_metadata_for_build_editable"])
def test_prepare_metadata_writes_the_same_metadata_as_the_wheel(project, tmp_path, hook):
    out = tmp_path / "metadata"
    name = getattr(backend, hook)(str(out))
    assert name == "cxb_simple-0.0.1.dist-info"

    expected = ProjectMetadata.from_project(PyProject.load(project).project, project)
    assert (out / name / "METADATA").read_text() == expected.render()
    dist = Distribution.at(out / name)
    assert [(e.group, e.name) for e in dist.entry_points] == [("console_scripts", "cxb-simple")]
    assert not (project / "_cxbuild").exists()  # a light hook: no log or report files


def test_prepare_metadata_reports_a_bad_pyproject(project, tmp_path):
    pyproject = project / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('version = "0.0.1"', 'version = "one"'))
    with pytest.raises(CxBuildError, match="project.version: 'one' is not a valid version"):
        backend.prepare_metadata_for_build_wheel(str(tmp_path / "metadata"))


def test_sdists_are_refused(project, tmp_path):
    with pytest.raises(CxBuildError, match="wheels only"):
        backend.build_sdist(str(tmp_path / "sdist"))
    assert not (tmp_path / "sdist").exists()


def test_build_wheel_needs_a_cxbuild_run(project, tmp_path):
    # Standalone `pip wheel`: release wheels come from `cxbuild build`, which builds the solution once.
    with pytest.raises(CxBuildError, match="run `cxbuild develop`"):
        backend.build_wheel(str(tmp_path / "wheels"))
    report = (project / "_cxbuild" / "cxbuild_report.md").read_text()
    assert report.startswith("# cxbuild build_wheel — ❌ failed")  # and the report says why


def test_standalone_editable_outside_a_solution_says_so(project, tmp_path):
    # A workspace install builds standalone, but only a project inside a cxbuild solution.
    with pytest.raises(CxBuildError, match="not inside a cxbuild solution"):
        backend.build_editable(str(tmp_path / "wheels"))
