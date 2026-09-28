"""Checks shared by the wheel tests (test_wheel_contents.py: `cxbuild build`) and the
editable tests (test_editable.py: `cxbuild develop`).

Both installs must carry the same metadata, the same console script and the same
namespace behaviour; only the files installed differ. Expected values come from
the fixture's own pyproject.toml, and assertions compare meaning, not one tool's
formatting.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

from conftest import SOLUTION, clean_env, query

PROJECT = "cxb_simple"
PYPROJECT = tomllib.loads((SOLUTION / "pkg" / PROJECT / "pyproject.toml").read_text())["project"]
README = (SOLUTION / "pkg" / PROJECT / PYPROJECT["readme"]).read_text()
NAMESPACE_PORTIONS = {"cxbns-second": "second", "cxbns-third": "third"}  # distribution -> portion (and pkg/ dir)

# Runs in a fresh interpreter, from outside the source tree: importlib.metadata
# must find the installed dist-info, not a *.egg-info lying next to the sources.
INSPECT = """
import json, importlib.metadata as md
dist = md.distribution({name!r})
print(json.dumps({{
    "metadata": dist.metadata.json,
    "files": [str(f) for f in dist.files or []],
    "wheel": dist.read_text("WHEEL"),
    "entry_points": [[ep.group, ep.name, ep.value] for ep in dist.entry_points],
    # Where the installer put each recorded file: scripts land outside site-packages.
    "located": {{str(f): str(dist.locate_file(f)) for f in dist.files or []}},
}}))
"""


def inspect(distribution: str, installation) -> dict:
    return query(INSPECT.format(name=distribution), cwd=installation.root.parent)


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()  # PEP 503


def check_core_metadata(m: dict) -> None:
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

    for url in PYPROJECT["urls"].values():
        assert any(url in entry for entry in m.get("project_url", [])), m.get("project_url")


def check_dependencies(m: dict) -> None:
    requires = [r.replace(" ", "") for r in m.get("requires_dist", [])]
    for dep in PYPROJECT["dependencies"]:
        assert dep.replace(" ", "") in requires, requires
    for extra, deps in PYPROJECT["optional-dependencies"].items():
        assert extra in m.get("provides_extra", [])
        for dep in deps:
            assert f'{dep};extra=="{extra}"' in requires, requires


def check_readme(m: dict) -> None:
    assert m.get("description_content_type") == "text/markdown"
    assert README.strip() in m.get("description", "")


def check_wheel_is_binary(wheel: str | None) -> None:
    import sys

    wheel = wheel or ""
    assert "Root-Is-Purelib: false" in wheel, wheel  # it carries a compiled module
    cp = f"cp{sys.version_info.major}{sys.version_info.minor}"
    tags = [line.removeprefix("Tag: ") for line in wheel.splitlines() if line.startswith("Tag: ")]
    assert tags and all(t.startswith(f"{cp}-{cp}") and not t.endswith("-any") for t in tags), wheel


def check_console_script(installed: dict, cwd: Path) -> None:
    (name, target), = PYPROJECT["scripts"].items()
    assert ["console_scripts", name, target] in installed["entry_points"]
    # The install records the script (bin/ in a venv, /usr/local/bin for a system Python, Scripts\ on Windows).
    scripts = [path for f, path in installed["located"].items() if f.startswith("..") and Path(f).stem == name]
    assert len(scripts) == 1, installed["files"]
    proc = subprocess.run(scripts, cwd=cwd, env=clean_env(), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "42"  # double(21), through util.py and the extension


def import_namespace(cwd: Path) -> list:
    """Import both portions in a fresh interpreter: [cxbns.__file__, cxbns.__path__, greet(), triple()]."""
    return query(
        "import json, cxbns, cxbns.second, cxbns.third; "
        "print(json.dumps([getattr(cxbns, '__file__', None), list(cxbns.__path__), "
        "cxbns.second.greet('ns'), cxbns.third.triple(3)]))",
        cwd=cwd,
    )
