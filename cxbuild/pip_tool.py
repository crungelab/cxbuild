"""Editable installs of a project into the environment running cxbuild, with uv or pip.

uv is preferred when it can be found, since environments created by uv (and by
hatch with installer = "uv") have no pip at all. It's looked for as the `uv`
package in this environment, then as `uv` on PATH. pip is the fallback.
CXBUILD_INSTALLER=uv or =pip forces the choice.

Either way the install targets the interpreter running cxbuild, builds without
isolation (so the build hooks see this environment, cxbuild included), and goes
through cxbuild's own backend, whose report lands next to the CLI's.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import os
import shutil
import sys
from pathlib import Path

from .runner import CxBuildError, Runner
from .tool import Tool

INSTALLERS = ("uv", "pip")


class PipConfigError(CxBuildError):
    """
    Something is misconfigured.
    """


@dataclasses.dataclass
class PipConfig:
    env: dict[str, str]
    source_dir: Path
    name: str  # the distribution name: uv is told to rebuild exactly this one


def find_uv() -> str | None:
    """The uv executable: the `uv` package in this environment first, then PATH."""
    try:
        from uv import find_uv_bin

        return find_uv_bin()
    except (ImportError, FileNotFoundError):
        return shutil.which("uv")


def installer(env: dict[str, str] | None = None) -> tuple[str, list[str]]:
    """(name, command prefix) for installing into the running interpreter's environment."""
    choice = (env if env is not None else os.environ).get("CXBUILD_INSTALLER", "").strip().lower()
    if choice and choice not in INSTALLERS:
        raise PipConfigError(f"CXBUILD_INSTALLER={choice!r}: use one of {', '.join(INSTALLERS)}")
    if choice != "pip":
        if (uv := find_uv()) is not None:
            return "uv", [uv, "pip", "install", "--python", sys.executable]
        if choice == "uv":
            raise PipConfigError("CXBUILD_INSTALLER=uv, but uv is neither installed in this environment nor on PATH")
    if importlib.util.find_spec("pip") is None:
        raise PipConfigError(
            f"no installer for {sys.executable}: this environment has no pip, and uv is neither "
            "installed in it nor on PATH (add uv to the environment, or install pip)"
        )
    return "pip", [sys.executable, "-m", "pip", "install"]


class PipTool(Tool):
    def __init__(self, config: PipConfig, runner: Runner) -> None:
        super().__init__(runner)
        self.config = config

    def install(self):
        name, command = installer(self.config.env)
        command += ["--no-build-isolation", "--editable", "."]
        if name == "uv":
            # uv caches builds: without this it may reuse the last one and never call the backend.
            command += ["--reinstall-package", self.config.name]
        self.run(
            command,
            cwd=self.config.source_dir,
            label=f"develop {self.config.source_dir.name}",
            env=self.config.env,
        )
