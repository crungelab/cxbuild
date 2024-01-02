from __future__ import annotations

import dataclasses
from pathlib import Path

from .tool import Tool
import subprocess


class BuildConfigError(Exception):
    """
    Build is misconfigured.
    """

class BuildError(Exception):
    """
    Build failed.
    """


@dataclasses.dataclass
class BuildConfig:
    env: dict[str, str]
    source_dir: Path


class BuildTool(Tool):
    def __init__(self, config: BuildConfig = None) -> None:
        super().__init__()
        self.config = config

    def build(self):
        cmd = ["python", "-m", "build", "--wheel", "--no-isolation"]
        cwd = self.config.source_dir
        env = self.config.env
        try:
            result = subprocess.run(cmd, cwd=cwd, env=env, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print("Command executed successfully. Output:\n", result.stdout)
        except subprocess.CalledProcessError as e:
            print(f"Command execution failed with error code {e.returncode}. Error message:\n", e.stderr)
            raise BuildError("Build failed.") from e
