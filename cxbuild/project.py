from pathlib import Path

from .project_base import ProjectBase
from .setup_tool import SetupConfig, SetupTool

class Project(ProjectBase):
    def __init__(self, path: Path) -> None:
        super().__init__(path)

    def develop(self, env):
        tool = SetupTool(SetupConfig(env=env, source_dir=self.path))
        tool.develop()

    def build(self, env):
        tool = SetupTool(SetupConfig(env=env, source_dir=self.path))
        tool.build()

    def write_requirements(self, requirements):
        with open(self.path / 'requirements.txt', 'w') as f:
            f.write('\n'.join(requirements))