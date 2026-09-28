"""cxbuild.metadata: a validated [project] table -> METADATA and entry_points.txt.

Input goes through PyProject.parse, the path real projects take; validation
itself is tested in test_pyproject.py. Output is read back with
importlib.metadata, the same reader the pipeline tests use on installed wheels,
so both judge the metadata the same way.
"""

from __future__ import annotations

import tomllib
from importlib.metadata import Distribution
from pathlib import Path

import pytest
from packaging.requirements import Requirement

from cxbuild.metadata import MetadataError, ProjectMetadata
from cxbuild.pyproject import PyProject
from cxbuild.runner import CxBuildError

FIXTURE = Path(__file__).parent.parent / "pipeline" / "solution" / "pkg" / "cxb_simple"


def load(project: dict, root: Path) -> ProjectMetadata:
    return ProjectMetadata.from_project(PyProject.parse({"project": project}).project, root)


def read_back(md: ProjectMetadata, tmp_path: Path) -> Distribution:
    """Write dist-info files the way a wheel carries them, and open them as a distribution."""
    dist_info = tmp_path / md.dist_info
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(md.render(), encoding="utf-8")
    if (entry_points := md.render_entry_points()) is not None:
        (dist_info / "entry_points.txt").write_text(entry_points, encoding="utf-8")
    return Distribution.at(dist_info)


# --- the pipeline fixture --------------------------------------------------


def test_pipeline_fixture_metadata(tmp_path):
    """The same [project] the pipeline tests check after a real install."""
    project = tomllib.loads((FIXTURE / "pyproject.toml").read_text())["project"]
    dist = read_back(load(project, FIXTURE), tmp_path)
    m = dist.metadata.json

    assert m["name"] == "cxb_simple"
    assert m["version"] == "0.0.1"
    assert m["summary"] == project["description"]
    assert m["requires_python"] == ">=3.12"
    assert m["classifier"] == project["classifiers"]
    assert m["keywords"] == ["cxbuild,fixture"]
    assert m["author_email"] == "Fixture Author <fixture@example.com>"
    assert m["project_url"] == ["Homepage, https://example.com/cxb_simple"]
    assert m["requires_dist"] == ["loguru>=0.7", 'pytest; extra == "test"']
    assert m["provides_extra"] == ["test"]
    assert m["description_content_type"] == "text/markdown"
    assert m["description"] == (FIXTURE / "README.md").read_text()

    [ep] = dist.entry_points
    assert (ep.group, ep.name, ep.value) == ("console_scripts", "cxb-simple", "cxb_simple.cli:main")


# --- exact output ----------------------------------------------------------


def test_minimal_project_renders_exactly(tmp_path):
    md = load({"name": "tiny", "version": "1.0"}, tmp_path)
    assert md.render() == "Metadata-Version: 2.4\nName: tiny\nVersion: 1.0\n"
    assert md.render_entry_points() is None


# --- normalization ---------------------------------------------------------


def test_version_is_normalized_and_names_escaped(tmp_path):
    md = load({"name": "My.Fancy-Pkg", "version": "01.0.0-rc1"}, tmp_path)
    assert md.version == "1.0.0rc1"
    assert md.name == "My.Fancy-Pkg"  # Name keeps its spelling; only file names are escaped
    assert md.dist_info == "my_fancy_pkg-1.0.0rc1.dist-info"


def test_extra_names_are_normalized_and_markers_combined(tmp_path):
    md = load(
        {
            "name": "p",
            "version": "1",
            "optional-dependencies": {"Dev_Tools": ['colorama>=0.4; sys_platform == "win32"', "rich"]},
        },
        tmp_path,
    )
    m = read_back(md, tmp_path).metadata.json
    assert m["provides_extra"] == ["dev-tools"]  # PEP 685

    colorama = Requirement(m["requires_dist"][0])
    assert str(colorama.specifier) == ">=0.4"
    # The requirement's own marker still applies, and so does the extra.
    assert colorama.marker.evaluate({"sys_platform": "win32", "extra": "dev-tools"})
    assert not colorama.marker.evaluate({"sys_platform": "linux", "extra": "dev-tools"})
    assert not colorama.marker.evaluate({"sys_platform": "win32", "extra": ""})

    assert Requirement(m["requires_dist"][1]).marker.evaluate({"extra": "dev-tools"})


def test_authors_split_between_author_and_author_email(tmp_path):
    md = load(
        {
            "name": "p",
            "version": "1",
            "authors": [{"name": "Only Name"}, {"email": "only@example.com"}, {"name": "Last, First", "email": "lf@example.com"}],
        },
        tmp_path,
    )
    m = read_back(md, tmp_path).metadata
    assert m["Author"] == "Only Name"
    assert m["Author-email"] == 'only@example.com, "Last, First" <lf@example.com>'  # the comma is quoted


def test_license_expression_and_files(tmp_path):
    (tmp_path / "LICENSE").write_text("MIT License\n")
    (tmp_path / "LICENSES").mkdir()
    (tmp_path / "LICENSES" / "Apache-2.0.txt").write_text("Apache\n")
    md = load(
        {
            "name": "p",
            "version": "1",
            "license": "mit or apache-2.0",
            "license-files": ["LICENSE", "LICENSES/*.txt"],
        },
        tmp_path,
    )
    assert md.project.license == "MIT OR Apache-2.0"  # canonical SPDX casing
    assert md.license_files == (Path("LICENSE"), Path("LICENSES/Apache-2.0.txt"))
    m = read_back(md, tmp_path).metadata
    assert m["License-Expression"] == "MIT OR Apache-2.0"
    assert m.get_all("License-File") == ["LICENSE", "LICENSES/Apache-2.0.txt"]


# --- readme ----------------------------------------------------------------


@pytest.mark.parametrize(
    "readme, files, body, content_type",
    [
        ("README.rst", {"README.rst": "Title\n=====\n"}, "Title\n=====\n", "text/x-rst"),
        ({"file": "NOTES", "content-type": "text/plain"}, {"NOTES": "notes\n"}, "notes\n", "text/plain"),
        ({"text": "# Inline\n", "content-type": "text/markdown"}, {}, "# Inline\n", "text/markdown"),
    ],
)
def test_readme_forms(tmp_path, readme, files, body, content_type):
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    m = read_back(load({"name": "p", "version": "1", "readme": readme}, tmp_path), tmp_path).metadata.json
    assert m["description"] == body
    assert m["description_content_type"] == content_type


def test_no_readme_means_no_body(tmp_path):
    assert "\n\n" not in load({"name": "p", "version": "1", "description": "x"}, tmp_path).render()


# --- entry points ----------------------------------------------------------


def test_entry_points_from_all_three_tables(tmp_path):
    md = load(
        {
            "name": "p",
            "version": "1",
            "scripts": {"p-cli": "p.cli:main"},
            "gui-scripts": {"p-gui": "p.gui:main"},
            "entry-points": {"p.plugins": {"audio": "p.plugins.audio:Plugin"}},
        },
        tmp_path,
    )
    found = {(ep.group, ep.name, ep.value) for ep in read_back(md, tmp_path).entry_points}
    assert found == {
        ("console_scripts", "p-cli", "p.cli:main"),
        ("gui_scripts", "p-gui", "p.gui:main"),
        ("p.plugins", "audio", "p.plugins.audio:Plugin"),
    }


# --- errors: files named in [project] ----------------------------------------
# Field validation (types, names, requirements, SPDX, ...) is in test_pyproject.py.


@pytest.mark.parametrize(
    "project, files, expected",
    [
        ({"name": "p", "version": "1", "license-files": ["COPYING"]}, {}, "matches no files"),
        ({"name": "p", "version": "1", "readme": "README.md"}, {}, "not found"),
        ({"name": "p", "version": "1", "readme": "README"}, {"README": "x"}, "content type"),
    ],
)
def test_missing_or_unusable_files_raise_metadata_error(tmp_path, project, files, expected):
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    with pytest.raises(MetadataError) as excinfo:
        load(project, tmp_path)
    assert expected in str(excinfo.value)


def test_metadata_error_is_a_cxbuild_error():
    # So the CLI prints it as a one-line message instead of a traceback.
    assert issubclass(MetadataError, CxBuildError)
