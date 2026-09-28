"""cxbuild.wheel: writing binary and editable wheels.

Every test builds a real wheel from a small fake project and a fake cmake
install, then opens the zip and checks it. No compiler needed: a "compiled
module" here is just bytes with the platform's extension suffix.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import stat
import sys
import sysconfig
import zipfile
from importlib.machinery import EXTENSION_SUFFIXES
from importlib.metadata import Distribution
from pathlib import Path, PurePosixPath

import pytest

from cxbuild.metadata import ProjectMetadata
from cxbuild.pyproject import PyProject
from cxbuild.runner import CxBuildError
from cxbuild.wheel import WheelBuilder, WheelError, default_packages, wheel_tag

EXT = f"_core{EXTENSION_SUFFIXES[0]}"  # e.g. _core.cpython-312-x86_64-linux-gnu.so
PACKAGE = PurePosixPath("cxbns/second")


def write(path: Path, text: str | bytes = "", executable: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if isinstance(text, bytes) else text.encode())
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def project(tmp_path) -> Path:
    """A namespace-portion project, like the crunge ones, with some things that must not ship."""
    root = tmp_path / "pkg" / "second"
    write(root / "cxbns/second/__init__.py", "from ._core import greet\n")
    write(root / "cxbns/second/util.py", "X = 1\n")
    write(root / "cxbns/second/_core.pyi", "def greet(name: str) -> str: ...\n")
    write(root / "cxbns/second/py.typed")
    write(root / "cxbns/second/tools/run.sh", "#!/bin/sh\n", executable=True)
    write(root / "cxbns/second/__pycache__/util.cpython-312.pyc", b"cache")
    write(root / "cxbns/second" / EXT, b"stale copy from an old editable install")
    write(root / "src/main.cpp", "// source, not package\n")
    write(root / "CMakeLists.txt", "# build file, not package\n")
    write(root / "LICENSE", "MIT License\n")
    return root


@pytest.fixture
def artifacts(tmp_path) -> Path:
    """What `cmake --install` put in _cxbuild/artifacts."""
    root = tmp_path / "_cxbuild" / "artifacts"
    write(root / "cxbns/second" / EXT, b"fresh build output")
    return root


def metadata(project: Path, **extra) -> ProjectMetadata:
    table = {"name": "cxbns-second", "version": "0.1.0", **extra}
    return ProjectMetadata.from_project(PyProject.parse({"project": table}).project, project)


def builder(project: Path, artifacts: Path, **kwargs) -> WheelBuilder:
    md = kwargs.pop("md", None) or metadata(project)
    return WheelBuilder(md, project, artifacts, [PACKAGE], **kwargs)


def names(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as z:
        return z.namelist()


# --- layout ---------------------------------------------------------------------


def test_wheel_contains_the_package_the_build_output_and_dist_info(project, artifacts, tmp_path):
    wheel = builder(project, artifacts).build(tmp_path / "dist")
    assert names(wheel) == [
        "cxbns/second/__init__.py",
        f"cxbns/second/{EXT}",
        "cxbns/second/_core.pyi",  # package data ships without being listed
        "cxbns/second/py.typed",
        "cxbns/second/tools/run.sh",
        "cxbns/second/util.py",
        "cxbns_second-0.1.0.dist-info/METADATA",
        "cxbns_second-0.1.0.dist-info/WHEEL",
        "cxbns_second-0.1.0.dist-info/RECORD",  # last of all
    ]
    # Never: __pycache__, src/, CMakeLists.txt, and never a cxbns/__init__.py.


def test_build_output_replaces_the_stale_copy_in_the_source_tree(project, artifacts, tmp_path):
    wheel = builder(project, artifacts).build(tmp_path / "dist")
    with zipfile.ZipFile(wheel) as z:
        assert z.read(f"cxbns/second/{EXT}") == b"fresh build output"


def test_everything_cmake_installed_ships(project, artifacts, tmp_path):
    write(artifacts / "cxbns/second/libhelper.so.1", b"a shared library cmake installed next to the module")
    assert "cxbns/second/libhelper.so.1" in names(builder(project, artifacts).build(tmp_path / "dist"))


def test_exclude_patterns(project, artifacts, tmp_path):
    wheel = builder(project, artifacts, exclude=["*/tools/*", "*.pyi"]).build(tmp_path / "dist")
    assert not [n for n in names(wheel) if "/tools/" in n or n.endswith(".pyi")]


def test_several_packages(project, artifacts, tmp_path):
    write(project / "cxbns_extras/__init__.py")
    b = WheelBuilder(metadata(project), project, artifacts, [PACKAGE, PurePosixPath("cxbns_extras")])
    assert "cxbns_extras/__init__.py" in names(b.build(tmp_path / "dist"))


def test_default_packages_come_from_the_extension_name():
    assert default_packages("crunge.imgui._imgui") == [PurePosixPath("crunge/imgui")]
    assert default_packages("cxb_simple._core") == [PurePosixPath("cxb_simple")]
    with pytest.raises(WheelError, match="not inside a package"):
        default_packages("_core")


# --- dist-info ------------------------------------------------------------------


def test_record_lists_every_file_with_a_correct_hash(project, artifacts, tmp_path):
    wheel = builder(project, artifacts).build(tmp_path / "dist")
    with zipfile.ZipFile(wheel) as z:
        record = z.read("cxbns_second-0.1.0.dist-info/RECORD").decode()
        rows = list(csv.reader(io.StringIO(record)))
        assert [r[0] for r in rows] == z.namelist()
        for path, digest, size in rows:
            if path.endswith("/RECORD"):
                assert (digest, size) == ("", "")
                continue
            data = z.read(path)
            expected = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            assert digest == f"sha256={expected}", path
            assert int(size) == len(data), path


def test_importlib_metadata_reads_the_dist_info(project, artifacts, tmp_path):
    """The reader the pipeline tests use on installed wheels, applied to an unpacked one."""
    (project / "README.md").write_text("# second\n")
    md = metadata(project, readme="README.md", license="MIT", **{"license-files": ["LICENSE"], "scripts": {"second": "cxbns.second:main"}})
    wheel = builder(project, artifacts, md=md).build(tmp_path / "dist")
    unpacked = tmp_path / "unpacked"
    zipfile.ZipFile(wheel).extractall(unpacked)
    dist = Distribution.at(unpacked / "cxbns_second-0.1.0.dist-info")

    assert dist.metadata["Name"] == "cxbns-second"
    assert dist.metadata["License-Expression"] == "MIT"
    assert dist.metadata.get_payload() == "# second\n"
    assert [(e.group, e.name) for e in dist.entry_points] == [("console_scripts", "second")]
    assert "cxbns_second-0.1.0.dist-info/licenses/LICENSE" in {str(f) for f in dist.files}
    assert (unpacked / "cxbns_second-0.1.0.dist-info/licenses/LICENSE").read_text() == "MIT License\n"


def test_wheel_file_describes_a_binary_wheel(project, artifacts, tmp_path):
    wheel = builder(project, artifacts).build(tmp_path / "dist")
    text = zipfile.ZipFile(wheel).read("cxbns_second-0.1.0.dist-info/WHEEL").decode()
    lines = text.splitlines()
    assert "Wheel-Version: 1.0" in lines
    assert "Root-Is-Purelib: false" in lines
    assert f"Tag: {wheel_tag()}" in lines
    assert any(line.startswith("Generator: cxbuild ") for line in lines)


# --- tag and filename -----------------------------------------------------------


def test_tag_is_this_interpreter_on_this_platform_unrepaired():
    tag = wheel_tag()
    cp = f"cp{sys.version_info.major}{sys.version_info.minor}"
    assert tag.interpreter == cp
    assert tag.abi.startswith(cp)  # cp312, or cp313t on a free-threaded build
    assert tag.platform == sysconfig.get_platform().replace("-", "_").replace(".", "_")
    assert "manylinux" not in tag.platform  # that tag is earned by repair, not claimed here


def test_filename(project, artifacts, tmp_path):
    md = ProjectMetadata.from_project(PyProject.parse({"project": {"name": "My.Pkg", "version": "1.0-rc1"}}).project, project)
    b = builder(project, artifacts, md=md)
    assert b.filename == f"my_pkg-1.0rc1-{wheel_tag()}.whl"
    assert b.build(tmp_path / "dist").name == b.filename


# --- zip details ----------------------------------------------------------------


def test_builds_are_reproducible(project, artifacts, tmp_path):
    first = builder(project, artifacts).build(tmp_path / "a").read_bytes()
    second = builder(project, artifacts).build(tmp_path / "b").read_bytes()
    assert first == second


def test_source_date_epoch_sets_the_timestamps(project, artifacts, tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")  # 2023-11-14 22:13:20 UTC
    wheel = builder(project, artifacts).build(tmp_path / "dist")
    assert {i.date_time for i in zipfile.ZipFile(wheel).infolist()} == {(2023, 11, 14, 22, 13, 20)}


def test_executable_bit_is_kept(project, artifacts, tmp_path):
    with zipfile.ZipFile(builder(project, artifacts).build(tmp_path / "dist")) as z:
        mode = lambda name: (z.getinfo(name).external_attr >> 16) & 0o777
        assert mode("cxbns/second/tools/run.sh") == 0o755
        assert mode("cxbns/second/util.py") == 0o644


def test_no_partial_file_is_left_behind(project, artifacts, tmp_path):
    builder(project, artifacts).build(tmp_path / "dist")
    assert [p.suffix for p in (tmp_path / "dist").iterdir()] == [".whl"]


# --- editable -------------------------------------------------------------------


def test_editable_wheel_is_metadata_and_a_pth(project, artifacts, tmp_path):
    wheel = builder(project, artifacts).build_editable(tmp_path / "dist")
    assert names(wheel) == [
        "_cxbns_second_cxbuild_editable.pth",
        "cxbns_second-0.1.0.dist-info/METADATA",
        "cxbns_second-0.1.0.dist-info/WHEEL",
        "cxbns_second-0.1.0.dist-info/RECORD",
    ]
    pth = zipfile.ZipFile(wheel).read("_cxbns_second_cxbuild_editable.pth").decode()
    assert pth == f"{project.resolve()}\n"


def test_editable_needs_no_build_output(project, tmp_path):
    # The module reaches the source tree through develop, not through the wheel.
    builder(project, tmp_path / "nothing-built").build_editable(tmp_path / "dist")


# --- errors ---------------------------------------------------------------------


def test_missing_build_output_is_an_error(project, tmp_path):
    with pytest.raises(WheelError, match="has cmake built and installed this project"):
        builder(project, tmp_path / "nothing-built").build(tmp_path / "dist")


def test_missing_package_directory_is_an_error(project, artifacts, tmp_path):
    b = WheelBuilder(metadata(project), project, artifacts, [PurePosixPath("cxbns/nope")])
    with pytest.raises(WheelError, match="package directory cxbns/nope not found"):
        b.build(tmp_path / "dist")


def test_wheel_error_is_a_cxbuild_error():
    assert issubclass(WheelError, CxBuildError)