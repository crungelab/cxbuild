"""Pipeline-test fixtures: build a fresh copy of solution/ with the real cxbuild CLI.

Every test works on its own copy under tmp_path, so runs start from an empty
_cxbuild/ and nothing left in the source tree (a stale wheel, a built module)
can make a test pass. cxbuild runs as a subprocess, the way a user runs it,
from the test environment's interpreter.

These tests install the fixture projects into the test environment (that is
what `develop` does); they are uninstalled when the session ends.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

SOLUTION = Path(__file__).parent / "solution"
# Project directory under pkg/ -> distribution name. They differ for the namespace
# portions, as in crunge (pkg/imgui holds crunge-imgui).
PROJECTS = {"cxb_simple": "cxb_simple", "second": "cxbns-second", "third": "cxbns-third"}
RETIRED = ["cxb_second"]  # fixture projects that no longer exist, in case an old run installed them
TIMEOUT = 600  # seconds; a cold cmake configure + build of both projects is well under this

# Leaking these from the shell that started pytest would change what cxbuild does.
CXBUILD_ENV = ("CBX_ACTIVITY", "CXBUILD_ROOT", "CXBUILD_VERBOSE", "CXBUILD_LOG_UDP")


@dataclass(repr=False)
class CxbuildResult:
    returncode: int
    output: str  # stdout and stderr, interleaved
    root: Path

    @property
    def state_dir(self) -> Path:
        return self.root / "_cxbuild"

    def report(self, name: str = "cxbuild") -> str:
        return (self.state_dir / f"{name}_report.md").read_text(encoding="utf-8")

    def log(self, name: str = "cxbuild") -> str:
        return (self.state_dir / f"{name}.log").read_text(encoding="utf-8")

    def __repr__(self) -> str:  # pytest shows the repr when an assert on the result fails
        return f"cxbuild exited {self.returncode} in {self.root}\n--- output ---\n{self.output}"


def clean_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in CXBUILD_ENV}
    env["PYTHONUNBUFFERED"] = "1"
    env["COLUMNS"] = "500"  # rich wraps panels at 80 columns off a terminal: keep paths on one line
    return env


def run_python(code: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run code in a fresh interpreter: imports must see what pip just installed."""
    return subprocess.run(
        [sys.executable, "-c", code], cwd=cwd, env=clean_env(),
        capture_output=True, text=True, timeout=60,
    )


def query(code: str, cwd: Path) -> Any:
    """Run code in a fresh interpreter that prints one JSON value, and return it."""
    proc = run_python(code, cwd)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def copy_solution(dest: Path) -> Path:
    if shutil.which("cmake") is None:
        pytest.skip("cmake not found on PATH")
    root = dest / "solution"
    shutil.copytree(
        SOLUTION, root,
        ignore=shutil.ignore_patterns(
            "_cxbuild", "build", "dist", "*.egg-info", "__pycache__", "*.so", "*.pyd"
        ),
    )
    return root


def run_cxbuild(root: Path, *args: str, cwd: Path | None = None) -> CxbuildResult:
    """Run the cxbuild CLI for the solution at `root`, from `cwd` (default: the root itself)."""
    proc = subprocess.run(
        [sys.executable, "-c", "from cxbuild.cli import cli; cli()", *args],
        cwd=cwd or root, env=clean_env(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        timeout=TIMEOUT,
    )
    return CxbuildResult(proc.returncode, proc.stdout, root)


def pip_install(*wheels: Path) -> None:
    """Install built wheels into the test environment, replacing any earlier install."""
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--force-reinstall", *map(str, wheels)],
        capture_output=True, text=True, env=clean_env(), timeout=TIMEOUT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.fixture(scope="session", autouse=True)
def uninstall_fixture_projects():
    yield
    subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", "-y", *PROJECTS.values(), *RETIRED],
        capture_output=True, text=True, env=clean_env(),
    )


@pytest.fixture
def solution(tmp_path: Path) -> Path:
    return copy_solution(tmp_path)


@pytest.fixture
def cxbuild(solution: Path) -> Callable[..., CxbuildResult]:
    """Run the cxbuild CLI in the solution copy: cxbuild("develop", "cxbns-second")."""

    def run(*args: str) -> CxbuildResult:
        return run_cxbuild(solution, *args)

    return run


@pytest.fixture(scope="module")
def developed(tmp_path_factory: pytest.TempPathFactory) -> CxbuildResult:
    """One `cxbuild develop`, shared by a module's read-only tests."""
    result = run_cxbuild(copy_solution(tmp_path_factory.mktemp("developed")), "develop")
    assert result.returncode == 0, result
    return result
