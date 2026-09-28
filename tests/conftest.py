"""Session-wide checks for cxbuild's tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def pytest_sessionstart(session: pytest.Session) -> None:
    spec = importlib.util.find_spec("cxbuild")
    if spec is None or spec.origin is None:
        pytest.exit(
            f"cxbuild is not installed for {sys.executable}.\n"
            "Install it editable from the repo root: `python -m pip install -e ..` "
            "(under hatch: `hatch env prune`, then rerun, so post-install-commands run).",
            returncode=4,
        )
    installed = Path(spec.origin).resolve()
    if not installed.is_relative_to(REPO_ROOT):
        pytest.exit(
            f"{sys.executable} imports cxbuild from {installed.parent}, not this checkout ({REPO_ROOT}).\n"
            "The tests would run stale code: reinstall it editable with `python -m pip install -e ..`.",
            returncode=4,
        )
