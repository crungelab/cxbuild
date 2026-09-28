"""A lock on the solution's build directory, shared by every process that builds it.

Only one cmake configure/build/install may run in _cxbuild/build at a time, but
several processes can want to: a `cxbuild develop` in one terminal and a hatch
workspace install in another, or uv building several workspace members at once
(it builds concurrently by default). Each takes this lock first; the others wait.

The lock is an OS file lock (fcntl on Linux and macOS, msvcrt on Windows), so it
is released when the process exits, however it exits: a crashed build never
leaves a stale lock behind. Who holds it is written to a separate owner file,
so a waiting process can say what it is waiting for.
"""

from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path

from loguru import logger

from .runner import Runner

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

POLL_INTERVAL = 0.2  # seconds between attempts on Windows, which has no blocking lock


class BuildLock:
    def __init__(self, path: Path, runner: Runner | None = None) -> None:
        self.path = Path(path)
        self.owner_path = self.path.with_name(self.path.name + ".owner")
        self.runner = runner
        self.file = None

    def __enter__(self) -> "BuildLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(self.path, "a+b")
        if not self._try_lock():
            holder = self.holder()
            logger.info("waiting for the build lock, held by {}", holder)
            if self.runner is not None:
                # A step of its own: the report shows how long this process waited, and for whom.
                with self.runner.capture("build lock", f"wait for the build lock (held by {holder})", cwd=self.path.parent):
                    self._lock()
            else:
                self._lock()
        self.owner_path.write_text(f"process {os.getpid()} on {socket.gethostname()}: {' '.join(sys.argv)}\n")
        logger.debug("build lock acquired: {}", self.path)
        return self

    def __exit__(self, *exc) -> None:
        try:
            self.owner_path.unlink(missing_ok=True)
        finally:
            self._unlock()
            self.file.close()
            self.file = None
            logger.debug("build lock released: {}", self.path)

    def holder(self) -> str:
        try:
            return self.owner_path.read_text().strip() or "another process"
        except OSError:
            return "another process"

    # --- platform --------------------------------------------------------------

    def _try_lock(self) -> bool:
        try:
            if sys.platform == "win32":
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:  # BlockingIOError on POSIX, PermissionError on Windows
            return False

    def _lock(self) -> None:
        if sys.platform == "win32":
            while not self._try_lock():
                time.sleep(POLL_INTERVAL)
        else:
            fcntl.flock(self.file.fileno(), fcntl.LOCK_EX)

    def _unlock(self) -> None:
        if sys.platform == "win32":
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
