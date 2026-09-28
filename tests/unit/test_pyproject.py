"""cxbuild.pyproject: loading and validating pyproject.toml.

Every mistake must fail at load time, with the file and the field in the
message, rather than surfacing later as an AttributeError or as silently
missing metadata.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cxbuild.pyproject import PyProject, PyProjectError
from cxbuild.runner import CxBuildError

SOLUTION = Path(__file__).parent.parent / "pipeline" / "solution"


def error_for(data: dict) -> str:
    with pytest.raises(PyProjectError) as excinfo:
        PyProject.parse(data, source="pkg/p/pyproject.toml")
    return str(excinfo.value)


def project(**fields) -> dict:
    return {"project": {"name": "p", "version": "1", **fields}}


# --- the real files -----------------------------------------------------------


@pytest.mark.parametrize("path", [SOLUTION, *sorted((SOLUTION / "pkg").iterdir())], ids=lambda p: p.name)
def test_fixture_pyprojects_load(path):
    PyProject.load(path)


def test_attributes_the_rest_of_cxbuild_uses():
    solution = PyProject.load(SOLUTION)
    assert solution.name == "cxbuild-test-solution"
    assert solution.tool.cxbuild.projects == ["pkg/*"]
    assert solution.tool.cxbuild.plugins == []
    assert solution.tool.cxbuild.extension is None

    simple = PyProject.load(SOLUTION / "pkg" / "cxb_simple")
    assert simple.name == "cxb_simple"
    assert simple.tool.cxbuild.extension.name == "cxb_simple._core"
    assert simple.tool.cxbuild.wheel.packages is None  # default: the extension's install prefix


def test_missing_tables_get_defaults():
    pyproject = PyProject.parse({})
    assert pyproject.project is None
    assert pyproject.tool.cxbuild.projects == []
    with pytest.raises(PyProjectError, match="no \\[project\\] table"):
        pyproject.name


def test_other_tools_and_build_system_pass_through():
    pyproject = PyProject.parse(
        {"build-system": {"requires": ["cxbuild"]}, "tool": {"hatch": {"version": {"path": "x.py"}}}}
    )
    assert pyproject.tool.hatch == {"version": {"path": "x.py"}}


def test_values_are_normalized():
    p = PyProject.parse(
        project(
            version="01.0.0-rc1",
            license="mit or apache-2.0",
            dependencies=["Rich >= 13"],
            **{"requires-python": " >= 3.12 ", "optional-dependencies": {"Dev_Tools": ["pytest"]}},
        )
    ).project
    assert p.version == "1.0.0rc1"
    assert p.license == "MIT OR Apache-2.0"
    assert p.dependencies == ["Rich>=13"]
    assert p.requires_python == ">=3.12"
    assert list(p.optional_dependencies) == ["dev-tools"]  # PEP 685


def test_readme_short_form_is_a_file():
    readme = PyProject.parse(project(readme="README.md")).project.readme
    assert (readme.file, readme.text) == ("README.md", None)


# --- errors -------------------------------------------------------------------


@pytest.mark.parametrize(
    "data, expected",
    [
        # shape: what the old attribute wrapper let through
        (project(dependencies="rich"), "project.dependencies: Input should be a valid list"),
        (project(authors=["me"]), "project.authors[0]: Input should be a valid dictionary"),
        (project(**{"optional-dependancies": {}}), "project.optional-dependancies: unknown key"),
        ({"tool": {"cxbuild": {"projectz": ["pkg/*"]}}}, "tool.cxbuild.projectz: unknown key"),
        ({"tool": {"cxbuild": {"extension": {}}}}, "tool.cxbuild.extension.name: Field required"),
        ({"project": {"name": "p"}}, "project.version: Field required"),
        # meaning: what packaging checks
        (project(name="-bad-"), "not a valid distribution name"),
        (project(version="one"), "not a valid version"),
        (project(description="two\nlines"), "project.description: must be a single line"),
        (project(**{"requires-python": ">>3"}), "project.requires-python"),
        (project(dependencies=["ok", "!!"]), "project.dependencies[1]: invalid requirement '!!'"),
        (
            project(**{"optional-dependencies": {"dev": ["ok", "rich>"]}}),
            "project.optional-dependencies.dev[1]: invalid requirement 'rich>'",
        ),
        (project(**{"optional-dependencies": {"a_b": [], "a-b": []}}), "duplicates 'a-b'"),
        (project(license={"file": "LICENSE"}), "use an SPDX expression"),
        (project(license="Not-A-License"), "project.license"),
        (project(readme={"text": "x"}), "project.readme: text needs a content-type"),
        (project(readme={"file": "a", "text": "b"}), "exactly one of file or text"),
        (project(authors=[{}]), "project.authors[0]: needs a name or an email"),
        (project(**{"entry-points": {"console_scripts": {"a": "b:c"}}}), "[project.scripts]"),
        (project(dynamic=["version"]), "project.dynamic: not supported"),
    ],
)
def test_invalid_pyproject_names_file_and_field(data, expected):
    message = error_for(data)
    assert message.startswith("pkg/p/pyproject.toml: ")
    assert expected in message


def test_every_problem_is_reported_at_once():
    message = error_for(project(dependencies="rich", keywords=[1], extra_key=True))
    assert len(message.splitlines()) == 3


def test_unreadable_files(tmp_path):
    with pytest.raises(PyProjectError, match="not found"):
        PyProject.load(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project\nname = ")
    with pytest.raises(PyProjectError, match="pyproject.toml"):
        PyProject.load(tmp_path)


def test_pyproject_error_is_a_cxbuild_error():
    assert issubclass(PyProjectError, CxBuildError)
