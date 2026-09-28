from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Sequence

from .runner import Runner, Step


class Tool:
    """Base for the tools cxbuild drives. Every command goes through the Runner,
    so it is logged, reported, and raises BuildStepError if it fails."""

    def __init__(self, runner: Runner) -> None:
        self.runner = runner

    def run(
        self,
        command: Sequence[str | os.PathLike],
        *,
        cwd: Path | None = None,
        label: str | None = None,
        env: Mapping[str, str] | None = None,
        diag_base: Path | None = None,
    ) -> Step:
        return self.runner.run(list(command), cwd or Path.cwd(), label=label, env=env, diag_base=diag_base)
