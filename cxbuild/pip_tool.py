from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

from .runner import CxBuildError, Runner
from .tool import Tool


class PipConfigError(CxBuildError):
    """
    Something is misconfigured.
    """


@dataclasses.dataclass
class PipConfig:
    env: dict[str, str]
    source_dir: Path


class PipTool(Tool):
    def __init__(self, config: PipConfig, runner: Runner) -> None:
        super().__init__(runner)
        self.config = config

    def install(self):
        # sys.executable: the interpreter running cxbuild, not whichever "python" is first on PATH.
        # The build hooks pip calls write their own report next to cxbuild's and it links them.
        cmd = [sys.executable, "-m", "pip", "install", "--no-build-isolation", "--editable", "."]
        self.run(
            cmd,
            cwd=self.config.source_dir,
            label=f"pip {self.config.source_dir.name}",
            env=self.config.env,
        )
