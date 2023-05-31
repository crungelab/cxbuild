from __future__ import annotations

import dataclasses
from pathlib import Path

from .tool import Tool
import subprocess


class PipConfigError(Exception):
    """
    Something is misconfigured.
    """


@dataclasses.dataclass
class PipConfig:
    env: dict[str, str]
    source_dir: Path


class PipTool(Tool):
    def __init__(self, config: PipConfig = None) -> None:
        super().__init__()
        self.config = config

    def install(self):
        cmd = ["python", "-m", "pip", "install", "--no-build-isolation", "--editable", "."]
        cwd = self.config.source_dir
        env = self.config.env
        try:
            result = subprocess.run(cmd, cwd=cwd, env=env, shell=True, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print("Command executed successfully. Output:\n", result.stdout)
        except subprocess.CalledProcessError as e:
            print(f"Command execution failed with error code {e.returncode}. Error message:\n", e.stderr)
