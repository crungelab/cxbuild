from __future__ import annotations

import dataclasses
import sys, os
import shutil
import contextlib
from pathlib import Path

from .tool import Tool
import subprocess


class SetupConfigError(Exception):
    """
    Something is misconfigured.
    """


@dataclasses.dataclass
class SetupConfig:
    env: dict[str, str]
    source_dir: Path


class SetupTool(Tool):
    def __init__(self, config: SetupConfig = None) -> None:
        super().__init__()
        self.config = config

    def develop(self):
        cmd = ["python", "setup.py", "develop"]
        cwd = self.config.source_dir
        env = self.config.env
        try:
            result = subprocess.run(cmd, cwd=cwd, env=env, shell=True, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print("Command executed successfully. Output:\n", result.stdout)
        except subprocess.CalledProcessError as e:
            print(f"Command execution failed with error code {e.returncode}. Error message:\n", e.stderr)

    def build(self):
        #cmd = ["python", "setup.py", "build"]
        cmd = ["python", "setup.py", "bdist_wheel"]
        cwd = self.config.source_dir
        env = self.config.env
        try:
            result = subprocess.run(cmd, cwd=cwd, env=env, shell=True, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print("Command executed successfully. Output:\n", result.stdout)
        except subprocess.CalledProcessError as e:
            print(f"Command execution failed with error code {e.returncode}. Error message:\n", e.stderr)
