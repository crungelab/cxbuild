from pathlib import Path

from .runner import Runner
from .solution import Solution


class CxBuild:
    """What the CLI drives. Logging is configured by the CLI, not here."""

    def __init__(self, runner: Runner) -> None:
        self.solution = Solution(Path.cwd(), runner)

    def clean(self):
        self.solution.clean()

    def configure(self):
        self.solution.configure()

    def develop(self, project_name: str = None):
        self.solution.develop(project_name)

    def build(self):
        self.solution.build()

    def install(self):
        self.solution.install()
