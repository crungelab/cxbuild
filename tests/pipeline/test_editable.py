"""`cxbuild develop`: editable installs.

An editable install is metadata plus a .pth naming the project directory, so
Python imports straight from the source tree, where develop has copied the
built module. Python edits are live; only C++ changes need another develop.
The metadata must match a regular wheel's exactly (see checks.py).
"""

from __future__ import annotations

from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path

import pytest

from checks import (
    NAMESPACE_PORTIONS,
    PROJECT,
    check_console_script,
    check_core_metadata,
    check_dependencies,
    check_readme,
    check_wheel_is_binary,
    import_namespace,
    inspect,
)
from conftest import PROJECTS, run_python

pytestmark = pytest.mark.pipeline


@pytest.fixture(scope="module")
def installed(developed):
    return inspect(PROJECT, developed)


# --- same metadata as a regular wheel -------------------------------------------


def test_core_metadata_matches_pyproject(installed):
    check_core_metadata(installed["metadata"])


def test_dependencies_and_extras(installed):
    check_dependencies(installed["metadata"])


def test_readme_is_the_long_description(installed):
    check_readme(installed["metadata"])


def test_wheel_is_binary_for_this_interpreter(installed):
    check_wheel_is_binary(installed["wheel"])


def test_console_script_is_installed_and_runs(installed, developed):
    check_console_script(installed, cwd=developed.root.parent)


# --- what makes it editable -----------------------------------------------------


@pytest.mark.parametrize("project, distribution", PROJECTS.items())
def test_install_is_a_pth_naming_the_project(project, distribution, developed):
    found = inspect(distribution, developed)
    package_files = [
        f for f in found["files"]
        if ".dist-info/" not in f and not f.startswith("..") and not f.endswith(".pth")
    ]
    assert not package_files, package_files  # nothing copied into site-packages

    pths = [f for f in found["files"] if f.endswith(".pth")]
    assert len(pths) == 1, found["files"]
    pth = Path(found["located"][pths[0]]).read_text().strip()
    assert Path(pth) == (developed.root / "pkg" / project).resolve()


def test_modules_import_from_the_source_tree(developed):
    result = run_python("import cxb_simple.util; print(cxb_simple.util.__file__)", cwd=developed.root.parent)
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == (developed.root / "pkg" / PROJECT / PROJECT / "util.py").resolve()


def test_built_module_is_copied_into_the_source_tree(developed):
    built = sorted((developed.state_dir / "artifacts" / PROJECT).glob("_core*"))
    copied = [p for p in (developed.root / "pkg" / PROJECT / PROJECT).iterdir() if p.name.endswith(tuple(EXTENSION_SUFFIXES))]
    assert [p.name for p in copied] == [p.name for p in built]
    assert copied[0].read_bytes() == built[0].read_bytes()


def test_namespace_portions_combine_across_projects(developed):
    file, path, greeting, tripled = import_namespace(cwd=developed.root.parent)
    assert (file, greeting, tripled) == (None, "hello, ns", 9)
    expected = {str((developed.root / "pkg" / portion / "cxbns").resolve()) for portion in NAMESPACE_PORTIONS.values()}
    assert expected <= {str(Path(p).resolve()) for p in path}, path


def test_python_edits_are_live(developed):
    # Last in the module: it changes the source tree the other tests read.
    util = developed.root / "pkg" / PROJECT / PROJECT / "util.py"
    util.write_text(util.read_text() + "\n\ndef edited() -> str:\n    return 'live'\n")
    result = run_python("import cxb_simple.util; print(cxb_simple.util.edited())", cwd=developed.root.parent)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "live"
