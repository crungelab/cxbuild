"""Stale build output: files an earlier build installed must not outlive it.

`cmake --install` never removes anything, so cxbuild empties the install prefix
before installing, and removes files an earlier `develop` staged into the source
tree once the build stops producing them.
"""

from __future__ import annotations

import zipfile

import pytest

from conftest import run_cxbuild

pytestmark = pytest.mark.pipeline

STALE = "_core.cpython-310-x86_64-linux-gnu.so"  # a module from a build with another Python


def test_a_stale_module_in_the_artifacts_goes_nowhere(solution):
    artifacts = solution / "_cxbuild" / "artifacts" / "cxb_simple"
    artifacts.mkdir(parents=True)
    (artifacts / STALE).write_bytes(b"from an old build")

    result = run_cxbuild(solution, "develop", "cxb_simple")
    assert result.returncode == 0, result
    assert not (artifacts / STALE).exists()
    assert not (solution / "pkg" / "cxb_simple" / "cxb_simple" / STALE).exists()

    (artifacts / STALE).write_bytes(b"from an old build")
    result = run_cxbuild(solution, "build")
    assert result.returncode == 0, result
    [wheel] = (solution / "dist").glob("cxb_simple-*.whl")
    assert not [n for n in zipfile.ZipFile(wheel).namelist() if STALE in n]


def test_a_file_the_build_stops_installing_leaves_the_source_tree(solution):
    project = solution / "pkg" / "cxb_simple"
    cmake = project / "CMakeLists.txt"
    original = cmake.read_text()
    (project / "extra.txt").write_text("installed by the first build only\n")
    cmake.write_text(original + "\ninstall(FILES extra.txt DESTINATION cxb_simple)\n")

    result = run_cxbuild(solution, "develop", "cxb_simple")
    assert result.returncode == 0, result
    staged = project / "cxb_simple" / "extra.txt"
    assert staged.is_file()

    cmake.write_text(original)  # the build no longer installs it
    result = run_cxbuild(solution, "develop", "cxb_simple")
    assert result.returncode == 0, result
    assert not staged.exists()
    assert "no longer built" in result.log()
