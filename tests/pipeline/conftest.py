"""Pipeline-test fixtures: build a fresh copy of solution/ with the real cxbuild CLI.

Every test works on its own copy under tmp_path, so runs start from an empty
_cxbuild/ and nothing left in the source tree (a stale wheel, a built module)
can make a test pass. cxbuild runs as a subprocess, the way a user runs it,
from the test environment's interpreter.

These tests install the fixture projects into the test environment (that is
what `develop` does); they are uninstalled when the session ends.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

SOLUTION = Path(__file__).parent / "solution"
PROJECTS = ["cxb_simple", "cxb_second"]
TIMEOUT = 600  # seconds; a cold cmake configure + build of both projects is well under this

# Leaking these from the shell that started pytest would change what cxbuild does.
CXBUILD_ENV = ("CBX_ACTIVITY", "CXBUILD_ROOT", "CXBUILD_VERBOSE", "CXBUILD_LOG_UDP")


@dataclass
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

    def __str__(self) -> str:  # what pytest shows when an assert on the result fails
        return f"exit {self.returncode} in {self.root}\n{self.output}"


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


@pytest.fixture(scope="session", autouse=True)
def uninstall_fixture_projects():
    yield
    subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", "-y", *PROJECTS],
        capture_output=True, text=True, env=clean_env(),
    )


@pytest.fixture
def solution(tmp_path: Path) -> Path:
    if shutil.which("cmake") is None:
        pytest.skip("cmake not found on PATH")
    root = tmp_path / "solution"
    shutil.copytree(
        SOLUTION, root,
        ignore=shutil.ignore_patterns(
            "_cxbuild", "build", "dist", "*.egg-info", "__pycache__", "*.so", "*.pyd"
        ),
    )
    return root


@pytest.fixture
def cxbuild(solution: Path) -> Callable[..., CxbuildResult]:
    """Run the cxbuild CLI in the solution copy: cxbuild("develop", "cxb_second")."""

    def run(*args: str) -> CxbuildResult:
        proc = subprocess.run(
            [sys.executable, "-c", "from cxbuild.cli import cli; cli()", *args],
            cwd=solution, env=clean_env(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=TIMEOUT,
        )
        return CxbuildResult(proc.returncode, proc.stdout, solution)

    return run
