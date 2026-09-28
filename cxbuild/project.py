import sys, os
from pathlib import Path, PurePosixPath
from loguru import logger
import setuptools
from setuptools import Distribution
import shutil

from .cmake_extension import CMakeExtension
from .extension_builder import ExtensionBuilder

from .activity import get_activity, BuildActivity, DevelopActivity
from .project_base import ProjectBase
from .metadata import ProjectMetadata
from .pip_tool import PipConfig, PipTool
from .runner import CxBuildError, Runner
from .wheel import WheelBuilder, default_packages


class Project(ProjectBase):
    def __init__(self, path: Path, runner: Runner) -> None:
        super().__init__(path)
        self.runner = runner

    def clean(self):
        logger.debug('clean')
        dist_dir = self.path / 'dist'
        if dist_dir.exists():
            logger.debug(f"removing {dist_dir}")
            shutil.rmtree(dist_dir)

        build_dir = self.path / 'build'
        if build_dir.exists():
            logger.debug(f"removing {build_dir}")
            shutil.rmtree(build_dir)

        for egginfo_dir in self.path.rglob('*.egg-info'):
            if egginfo_dir.is_dir():
                logger.debug(f"removing {egginfo_dir}")
                shutil.rmtree(egginfo_dir)

    def develop(self):
        logger.debug('develop')
        tool = PipTool(PipConfig(env=os.environ, source_dir=self.path), self.runner)
        tool.install()

    def wheel_builder(self, artifacts_dir: Path) -> WheelBuilder:
        """Everything needed to write this project's wheel, validated now: a bad readme or
        license glob fails here, before anyone waits for cmake."""
        config = self.pyproject.tool.cxbuild
        if config.extension is None:
            raise CxBuildError(f"{self.path / 'pyproject.toml'}: [tool.cxbuild.extension] is missing")
        if config.wheel.packages is not None:
            packages = [PurePosixPath(*name.split(".")) for name in config.wheel.packages]
        else:
            packages = default_packages(config.extension.name)
        metadata = ProjectMetadata.from_project(self.pyproject.project, self.path)
        return WheelBuilder(metadata, self.path, artifacts_dir, packages, exclude=config.wheel.exclude)

    def write_wheel(self, builder: WheelBuilder, out_dir: Path) -> Path:
        with self.runner.capture(f"wheel {self.path.name}", f"write {builder.filename}", cwd=self.path):
            wheel = builder.build(out_dir)
        self.runner.add_artifact(f"wheel {self.path.name}", wheel)
        return wheel

    def build_wheel(
        self,
        wheel_directory: str,
        config_settings: dict[str, list[str] | str] | None = None,
        metadata_directory: str | None = None
    ) -> str:
        logger.debug('build_wheel')
        name: str = self.pyproject.tool.cxbuild.extension.name
        logger.debug(f'extension name: {name}')
        split_name = name.split('.')
        split_name.pop()
        install_prefix = Path(*split_name)
        logger.debug(f'install prefix {install_prefix}')

        activity = get_activity()
        logger.debug(f'activity: {activity.__dict__}')

        editable = True if isinstance(activity, DevelopActivity) else False

        dist_dir = self.path / 'dist'

        #Note:  This is a hack, but I didn't want to call yet another subprocess
        sys.argv = ["setup.py", "bdist_wheel"]
        with self.runner.capture("setuptools", "setup.py bdist_wheel", cwd=self.path):
            dist: Distribution = setuptools.setup(
                ext_modules=[
                    CMakeExtension(
                        name=name,
                        source_dir=Path.cwd(),
                        install_prefix=install_prefix,
                        editable=editable,
                    ),
                ],
                cmdclass=dict(
                    build_ext=ExtensionBuilder,
                )
            )

        # dist/ isn't cleaned on this path, so it can hold wheels from earlier builds.
        wheels = sorted(dist_dir.glob('*.whl'), key=lambda p: p.stat().st_mtime)
        if not wheels:
            raise CxBuildError(f"setuptools produced no wheel in {dist_dir}")
        wheel = wheels[-1]
        logger.debug(f'wheel: {wheel}')

        out_dir = Path(wheel_directory)
        if out_dir.resolve() != dist_dir.resolve():
            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(wheel, out_dir / wheel.name)

        return wheel.name

    def write_requirements(self, requirements):
        with open(self.path / 'requirements.txt', 'w') as f:
            f.write('\n'.join(requirements))
