from pathlib import Path

from loguru import logger

from .runner import Runner
from .solution import Solution


class CxBuild:
    """What the CLI drives. Logging is configured by the CLI, not here."""

    def __init__(self, runner: Runner, root: Path, start: Path | None = None) -> None:
        self.solution = Solution(root, runner)
        self.start = Path(start or root)  # where cxbuild was run from

    def clean(self):
        self.solution.clean()

    def configure(self):
        self.solution.configure()

    def develop(self, project_name: str = None):
        if project_name is None and (project := self.solution.project_containing(self.start)) is not None:
            logger.info(f"developing {project.name}: cxbuild was run from inside it")
            project_name = project.name
        self.solution.develop(project_name)

    def build(self):
        self.solution.build()

    def install(self):
        self.solution.install()
