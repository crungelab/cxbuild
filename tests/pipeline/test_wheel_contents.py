"""What a wheel from `cxbuild build` contains, once pip has installed it.

Pins down what cxbuild's wheels must hold: every package file plus the
extension, nothing else from the source tree, a binary wheel tagged for this
interpreter, a working console script, core metadata carrying every [project]
field, and namespace portions that ship only their own package. Editable
installs (`cxbuild develop`) are covered in test_editable.py.
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
from conftest import copy_solution, pip_install, run_cxbuild

pytestmark = pytest.mark.pipeline

PY_MODULES = ["__init__.py", "util.py", "cli.py"]


def is_extension(path: str) -> bool:
    return path.startswith(f"{PROJECT}/_core") and path.endswith(tuple(EXTENSION_SUFFIXES))


def is_expected_file(path: str) -> bool:
    """Everything an installed wheel may legitimately record."""
    return (
        path in {f"{PROJECT}/{m}" for m in PY_MODULES}
        or is_extension(path)
        or path.startswith(f"{PROJECT}/__pycache__/")  # pip compiles and records .pyc files
        or ".dist-info/" in path
        or (path.startswith("..") and Path(path).stem == "cxb-simple")  # the console script, in bin/
    )


@pytest.fixture(scope="module")
def installation(tmp_path_factory):
    """`cxbuild build`, then pip installs the wheels from dist/."""
    root = copy_solution(tmp_path_factory.mktemp("build"))
    result = run_cxbuild(root, "build")
    assert result.returncode == 0, result
    pip_install(*sorted((root / "dist").glob("*.whl")))
    return result


@pytest.fixture(scope="module")
def installed(installation):
    return inspect(PROJECT, installation)


def test_python_modules_are_installed(installed):
    missing = [m for m in PY_MODULES if f"{PROJECT}/{m}" not in installed["files"]]
    assert not missing, installed["files"]


def test_extension_module_is_installed(installed):
    extensions = [f for f in installed["files"] if is_extension(f)]
    assert len(extensions) == 1, installed["files"]


def test_nothing_else_from_the_source_tree(installed):
    # A backend that packs the wrong directory would ship CMakeLists.txt, src/, README.md, ...
    stray = [f for f in installed["files"] if not is_expected_file(f)]
    assert not stray, stray


def test_wheel_is_binary_for_this_interpreter(installed):
    check_wheel_is_binary(installed["wheel"])


def test_core_metadata_matches_pyproject(installed):
    check_core_metadata(installed["metadata"])


def test_dependencies_and_extras(installed):
    check_dependencies(installed["metadata"])


def test_readme_is_the_long_description(installed):
    check_readme(installed["metadata"])


def test_console_script_is_installed_and_runs(installed, installation):
    check_console_script(installed, cwd=installation.root.parent)


@pytest.mark.parametrize("distribution, portion", NAMESPACE_PORTIONS.items())
def test_namespace_portion_ships_only_its_own_package(distribution, portion, installation):
    files = inspect(distribution, installation)["files"]
    # An __init__.py here would turn the namespace into an ordinary package: every
    # portion would install the same file, and uninstalling one would break the rest.
    assert "cxbns/__init__.py" not in files, files
    package = [f for f in files if ".dist-info/" not in f]
    assert package and all(f.startswith(f"cxbns/{portion}/") for f in package), package


def test_namespace_portions_import_together(installation):
    file, _, greeting, tripled = import_namespace(cwd=installation.root.parent)
    assert (file, greeting, tripled) == (None, "hello, ns", 9)  # __file__ None: a namespace, not a module
