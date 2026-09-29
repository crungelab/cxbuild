"""Staging built modules into the source tree, and cleaning up after earlier stages.

`develop` copies what cmake installed into each project's package directory, so an
editable install imports it. What was staged is recorded, so a later stage can remove
files the build no longer produces, but never anything that isn't cxbuild's own copy.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from cxbuild.cmake_tool import CMakeConfig, CMakeConfigError, CMakeTool
from cxbuild.project import Project

FIXTURE = Path(__file__).parent.parent / "pipeline" / "solution" / "pkg" / "cxb_simple"
MODULE = "_core.cpython-312-x86_64-linux-gnu.so"


@pytest.fixture
def project(tmp_path) -> Project:
    root = tmp_path / "solution" / "pkg" / "cxb_simple"
    shutil.copytree(FIXTURE, root)
    return Project(root, runner=None)


@pytest.fixture
def artifacts(tmp_path) -> Path:
    return tmp_path / "solution" / "_cxbuild" / "artifacts"


def build_output(artifacts: Path, files: dict[str, bytes]) -> None:
    """Replace the artifacts with exactly these files, as a clean `cmake --install` would."""
    shutil.rmtree(artifacts, ignore_errors=True)
    for name, data in files.items():
        path = artifacts / "cxb_simple" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def stage(project: Project, artifacts: Path) -> None:
    project.stage(project.wheel_builder(artifacts))


def record(artifacts: Path) -> dict:
    return json.loads((artifacts.parent / "staged" / "cxb_simple.json").read_text())["files"]


def test_stage_copies_the_build_output_and_records_it(project, artifacts):
    build_output(artifacts, {MODULE: b"v1", "lib/helper.so": b"helper"})
    stage(project, artifacts)
    package = project.path / "cxb_simple"
    assert (package / MODULE).read_bytes() == b"v1"
    assert (package / "lib" / "helper.so").read_bytes() == b"helper"
    assert set(record(artifacts)) == {f"cxb_simple/{MODULE}", "cxb_simple/lib/helper.so"}


def test_restage_updates_files_the_build_still_produces(project, artifacts):
    build_output(artifacts, {MODULE: b"v1"})
    stage(project, artifacts)
    build_output(artifacts, {MODULE: b"v2"})
    stage(project, artifacts)
    assert (project.path / "cxb_simple" / MODULE).read_bytes() == b"v2"


def test_restage_removes_what_the_build_no_longer_produces(project, artifacts):
    old = "_core.cpython-310-x86_64-linux-gnu.so"
    build_output(artifacts, {old: b"from python 3.10", MODULE: b"v1"})
    stage(project, artifacts)
    build_output(artifacts, {MODULE: b"v2"})
    stage(project, artifacts)
    assert not (project.path / "cxb_simple" / old).exists()
    assert set(record(artifacts)) == {f"cxb_simple/{MODULE}"}


def test_a_changed_leftover_is_kept(project, artifacts):
    build_output(artifacts, {"notes.txt": b"generated", MODULE: b"v1"})
    stage(project, artifacts)
    (project.path / "cxb_simple" / "notes.txt").write_bytes(b"edited by hand")
    build_output(artifacts, {MODULE: b"v2"})
    stage(project, artifacts)
    assert (project.path / "cxb_simple" / "notes.txt").read_bytes() == b"edited by hand"


def test_files_never_staged_are_never_touched(project, artifacts):
    build_output(artifacts, {MODULE: b"v1"})
    stage(project, artifacts)
    sources = sorted(p.relative_to(project.path) for p in project.path.rglob("*.py"))
    build_output(artifacts, {MODULE: b"v2"})
    stage(project, artifacts)
    assert sorted(p.relative_to(project.path) for p in project.path.rglob("*.py")) == sources


def test_an_unreadable_record_is_treated_as_empty(project, artifacts):
    build_output(artifacts, {MODULE: b"v1"})
    (artifacts.parent / "staged").mkdir(parents=True)
    (artifacts.parent / "staged" / "cxb_simple.json").write_text("{not json")
    stage(project, artifacts)
    assert set(record(artifacts)) == {f"cxb_simple/{MODULE}"}


def test_clearing_the_install_prefix(tmp_path):
    prefix = tmp_path / "_cxbuild" / "artifacts"
    (prefix / "pkg").mkdir(parents=True)
    (prefix / "pkg" / "stale.so").write_bytes(b"old")
    tool = CMakeTool(CMakeConfig(tmp_path, tmp_path / "_cxbuild" / "build", "Debug", None, install_dir=prefix), runner=None)
    tool.clear_install_prefix()
    assert not prefix.exists()


def test_an_install_prefix_outside_cxbuild_is_never_cleared(tmp_path):
    prefix = tmp_path / "somewhere" / "important"
    prefix.mkdir(parents=True)
    tool = CMakeTool(CMakeConfig(tmp_path, tmp_path / "_cxbuild" / "build", "Debug", None, install_dir=prefix), runner=None)
    with pytest.raises(CMakeConfigError, match="refusing to clear"):
        tool.clear_install_prefix()
    assert prefix.exists()
