import os
import shutil
from pathlib import Path, PurePosixPath

from loguru import logger

from .activity import get_activity
from .copyutils import copy_directory_contents
from .metadata import ProjectMetadata
from .pip_tool import PipConfig, PipTool
from .project_base import ProjectBase
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

    # --- the CLI side ------------------------------------------------------

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

    def write_wheel(self, builder: WheelBuilder, out_dir: Path, editable: bool = False) -> Path:
        kind = "editable wheel" if editable else "wheel"
        with self.runner.capture(f"wheel {self.path.name}", f"write {kind} {builder.filename}", cwd=self.path):
            wheel = builder.build_editable(out_dir) if editable else builder.build(out_dir)
        self.runner.add_artifact(f"{kind} {self.path.name}", wheel)
        return wheel

    def develop(self, builder: WheelBuilder):
        """Editable install: put the built module where Python will import it from, the
        source tree, then let pip install the editable wheel (metadata plus a .pth)."""
        for package in builder.packages:
            built = Path(builder.artifacts_dir) / package
            if not built.is_dir():
                raise CxBuildError(f"no build output in {built}: has cmake built and installed this project?")
            logger.debug(f"copying {built} -> {self.path / package}")
            copy_directory_contents(built, self.path / package)
        tool = PipTool(PipConfig(env=os.environ, source_dir=self.path), self.runner)
        tool.install()

    # --- the PEP 517 backend side ------------------------------------------

    def backend_wheel(self, out_dir: Path, editable: bool) -> Path:
        """A wheel for the build hooks, from what the running cxbuild command built."""
        return self.write_wheel(self.wheel_builder(get_activity().artifacts_dir), out_dir, editable)

    def write_requirements(self, requirements):
        with open(self.path / 'requirements.txt', 'w') as f:
            f.write('\n'.join(requirements))
