import sys, os
from pathlib import Path
from loguru import logger
import setuptools
from setuptools import Distribution
import shutil

from .cmake_extension import CMakeExtension
from .extension_builder import ExtensionBuilder

from .activity import get_activity, BuildActivity, DevelopActivity
from .project_base import ProjectBase
from .build_tool import BuildConfig, BuildTool
from .pip_tool import PipConfig, PipTool
from .copyutils import copy_directory_contents

class Project(ProjectBase):
    def __init__(self, path: Path) -> None:
        super().__init__(path)

    def develop(self):
        logger.debug('develop')
        tool = PipTool(PipConfig(env=os.environ, source_dir=self.path))
        tool.install()

    def build(self):
        tool = BuildTool(BuildConfig(env=os.environ, source_dir=self.path))
        tool.build()

    def build_wheel(
        self,
        wheel_directory: str,
        config_settings: dict[str, list[str] | str] | None = None,
        metadata_directory: str | None = None
    ) -> str:
        logger.debug('build_wheel')
        name: str = self.pyproject.tool.cxbuild.extension.name
        logger.debug(name)
        #install_prefix = Path(name.split('.')[0])
        split_name = name.split('.')
        split_name.pop()
        install_prefix = Path(*split_name)
        logger.debug(install_prefix)
        
        activity = get_activity()
        logger.debug(activity.__dict__)

        editable = True if isinstance(activity, DevelopActivity) else False

        dist_dir = self.path / 'dist'
        if dist_dir.exists():
            shutil.rmtree(dist_dir)

        #Note:  This is a hack, but I didn't want to call yet another subprocess
        sys.argv = ["setup.py", "bdist_wheel"]
        dist: Distribution = setuptools.setup(
            ext_modules=[
                CMakeExtension(
                    name=name,
                    source_dir=Path.cwd(),
                    install_prefix=install_prefix,
                    editable=editable
                ),
            ],
            cmdclass=dict(
                build_ext=ExtensionBuilder,
            )
        )

        out_dir = Path(wheel_directory)
        items = list(dist_dir.iterdir())
        dist_name = items[0].name
        logger.debug(dist_name)

        if dist_dir != out_dir:
            copy_directory_contents(dist_dir, out_dir)

        return dist_name

    def write_requirements(self, requirements):
        with open(self.path / 'requirements.txt', 'w') as f:
            f.write('\n'.join(requirements))