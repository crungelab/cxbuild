from pathlib import Path

from .pyproject import PyProject

class ProjectBase:
    def __init__(self, path: Path) -> None:
        self.path: Path = path
        self.pyproject:PyProject = PyProject.load(path)
        self.name: str = self.pyproject.name