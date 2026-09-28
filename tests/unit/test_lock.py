"""cxbuild.lock: one cmake build at a time in the shared build directory, across processes."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from cxbuild.lock import BuildLock
from cxbuild.runner import Runner


def hold_in_child(lock_path: Path, seconds: float) -> subprocess.Popen:
    """Another process takes the lock and keeps it; returns once it has it."""
    code = textwrap.dedent(f"""
        import sys, time
        from cxbuild.lock import BuildLock
        with BuildLock({str(lock_path)!r}):
            print("held", flush=True)
            time.sleep({seconds})
    """)
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == "held"
    return child


def test_uncontended_lock_is_just_taken(tmp_path):
    lock = BuildLock(tmp_path / "_cxbuild" / "build.lock")
    with lock:
        assert "process" in lock.holder()  # who holds it is recorded while held
    assert not lock.owner_path.exists()  # and cleared when released


def test_a_second_process_waits_and_the_report_says_so(tmp_path):
    lock_path = tmp_path / "_cxbuild" / "build.lock"
    child = hold_in_child(lock_path, 1.5)
    start = time.monotonic()
    with Runner(tmp_path, "develop") as runner:
        with BuildLock(lock_path, runner):
            waited = time.monotonic() - start
    child.wait()
    assert waited >= 1.0
    report = (tmp_path / "_cxbuild" / "cxbuild_report.md").read_text()
    assert "| build lock |" in report
    assert f"held by process {child.pid}" in report


def test_no_step_when_nobody_else_holds_it(tmp_path):
    with Runner(tmp_path, "develop") as runner:
        with BuildLock(tmp_path / "_cxbuild" / "build.lock", runner):
            pass
    assert "build lock" not in (tmp_path / "_cxbuild" / "cxbuild_report.md").read_text()


def test_released_when_the_build_fails(tmp_path):
    lock_path = tmp_path / "build.lock"
    with pytest.raises(RuntimeError):
        with BuildLock(lock_path):
            raise RuntimeError("cmake failed")
    hold_in_child(lock_path, 0).wait()  # another process gets it straight away


def test_released_when_the_holder_dies(tmp_path):
    # An OS lock: a killed build never leaves a stale lock behind.
    lock_path = tmp_path / "build.lock"
    child = hold_in_child(lock_path, 60)
    child.kill()
    child.wait()
    start = time.monotonic()
    with BuildLock(lock_path):
        assert time.monotonic() - start < 1.0
