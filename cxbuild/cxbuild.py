from pathlib import Path

from .solution import Solution


class CxBuild:
    def __init__(self) -> None:
        self.solution = Solution(Path.cwd())

    def configure(self):
        print('configure')
        self.solution.configure()

    def develop(self):
        print('develop')
        self.solution.develop()

    def build(self):
        print('build')
        self.configure()
        self.solution.build()

    def install(self):
        print('install')
        self.solution.install()
