"""What an installed cxbuild wheel contains, checked against the fixture's pyproject.toml.

These pass against the current (setuptools-based) backend and pin down what any
backend must produce: every package file plus the extension, nothing else from
the source tree, a binary wheel tagged for this interpreter, a working console
script, and core metadata carrying every [project] field.

Expected values come from the fixture itself, so the fixture is the only place
they are written down. Assertions compare meaning, not one tool's formatting.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path

import pytest

from conftest import SOLUTION, clean_env, query

pytestmark = pytest.mark.pipeline

PROJECT = "cxb_simple"
PYPROJECT = tomllib.loads((SOLUTION / "pkg" / PROJECT / "pyproject.toml").read_text())["project"]
README = (SOLUTION / "pkg" / PROJECT / PYPROJECT["readme"]).read_text()
PY_MODULES = ["__init__.py", "util.py", "cli.py"]

# Runs in a fresh interpreter, from outside the source tree: importlib.metadata
# must find the installed dist-info, not a *.egg-info lying next to the sources.
INSPECT = f"""
import json, importlib.metadata as md
dist = md.distribution({PROJECT!r})
print(json.dumps({{
    "metadata": dist.metadata.json,
    "files": [str(f) for f in dist.files or []],
    "wheel": dist.read_text("WHEEL"),
    "entry_points": [[ep.group, ep.name, ep.value] for ep in dist.entry_points],
}}))
"""


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()  # PEP 503


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
def installed(developed):
    return query(INSPECT, cwd=developed.root.parent)


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
    wheel = installed["wheel"] or ""
    assert "Root-Is-Purelib: false" in wheel, wheel  # it carries a compiled module
    cp = f"cp{sys.version_info.major}{sys.version_info.minor}"
    tags = [line.removeprefix("Tag: ") for line in wheel.splitlines() if line.startswith("Tag: ")]
    assert tags and all(t.startswith(f"{cp}-{cp}-") and not t.endswith("-any") for t in tags), wheel


def test_core_metadata_matches_pyproject(installed):
    m = installed["metadata"]
    assert normalize_name(m["name"]) == normalize_name(PYPROJECT["name"])
    assert m["version"] == PYPROJECT["version"]
    assert m["summary"] == PYPROJECT["description"]
    assert m["requires_python"] == PYPROJECT["requires-python"]
    assert set(PYPROJECT["classifiers"]) <= set(m.get("classifier", []))

    # One "Keywords" field, comma- or space-separated depending on the writer.
    keywords = {k for field in m.get("keywords", []) for k in re.split(r"[,\s]+", field) if k}
    assert set(PYPROJECT["keywords"]) <= keywords

    author = PYPROJECT["authors"][0]
    assert author["name"] in m["author_email"] and author["email"] in m["author_email"]

    for label, url in PYPROJECT["urls"].items():
        assert any(url in entry for entry in m.get("project_url", [])), m.get("project_url")


def test_dependencies_and_extras(installed):
    m = installed["metadata"]
    requires = [r.replace(" ", "") for r in m.get("requires_dist", [])]
    for dep in PYPROJECT["dependencies"]:
        assert dep.replace(" ", "") in requires, requires
    for extra, deps in PYPROJECT["optional-dependencies"].items():
        assert extra in m.get("provides_extra", [])
        for dep in deps:
            assert f'{dep};extra=="{extra}"' in requires, requires


def test_readme_is_the_long_description(installed):
    m = installed["metadata"]
    assert m.get("description_content_type") == "text/markdown"
    assert README.strip() in m.get("description", "")


def test_console_script_is_installed_and_runs(installed, developed):
    (name, target), = PYPROJECT["scripts"].items()
    assert ["console_scripts", name, target] in installed["entry_points"]

    script = shutil.which(name, path=str(Path(sys.executable).parent))
    assert script, f"{name} not in {Path(sys.executable).parent}"
    proc = subprocess.run(
        [script], cwd=developed.root.parent, env=clean_env(),
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "42"  # double(21), through util.py and the extension
