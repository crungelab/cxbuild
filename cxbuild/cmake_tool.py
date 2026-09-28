from __future__ import annotations

import dataclasses
import sys, os
import shutil
from pathlib import Path

from loguru import logger

from .runner import CxBuildError, Runner
from .tool import Tool


class CMakeConfigError(CxBuildError):
    """
    Something is misconfigured.
    """

@dataclasses.dataclass
class CMakeConfig:
    source_dir: Path
    build_dir: Path
    build_type: str
    generator: str

    module_dirs: list[Path] = dataclasses.field(default_factory=list)
    prefix_dirs: list[Path] = dataclasses.field(default_factory=list)
    install_dir: Path | None = None  # CMAKE_INSTALL_PREFIX; default <source_dir>/_cxbuild/artifacts
    init_cache_file: Path = dataclasses.field(init=False, default=Path())
    env: dict[str, str] = dataclasses.field(init=False, default_factory=os.environ.copy)
    single_config: bool = not sys.platform.startswith("win32")

    def __post_init__(self) -> None:
        self.init_cache_file = self.build_dir / "CMakeInit.txt"

        if not self.source_dir.is_dir():
            msg = f"source directory {self.source_dir} does not exist"
            raise CMakeConfigError(msg)

        self.build_dir.mkdir(parents=True, exist_ok=True)
        if not self.build_dir.is_dir():
            msg = f"build directory {self.build_dir} must be a (creatable) directory"
            raise CMakeConfigError(msg)

def join_posix_paths(paths: list[Path]):
    return ";".join(str(path.as_posix()) for path in paths)

class CMakeTool(Tool):
    def __init__(self, config: CMakeConfig, runner: Runner) -> None:
        super().__init__(runner)
        self.config = config

    def configure(self):
        # Initialize the CMake configuration arguments
        configure_args = []

        # Select the appropriate generator and accompanying settings
        if self.config.generator is not None:
            configure_args += ["-G", self.config.generator]  # no shell: quotes would reach cmake

            if self.config.generator == "Ninja":
                configure_args += [f"-DCMAKE_MAKE_PROGRAM={shutil.which('ninja')}"]

        # CMake configure arguments
        cmake_install_prefix = self.config.install_dir or self.config.source_dir / '_cxbuild/artifacts'

        cmake_prefix_path = join_posix_paths(self.config.prefix_dirs)
        logger.debug(f'cmake_prefix_path: {cmake_prefix_path}')

        configure_args += [
            f'-DPython_EXECUTABLE={Path(sys.executable).as_posix()}',  # the interpreter running cxbuild
            f'-DCMAKE_BUILD_TYPE={self.config.build_type}',
            f'-DCMAKE_INSTALL_PREFIX:PATH={cmake_install_prefix}',
            f'-DCMAKE_PREFIX_PATH:PATH={cmake_prefix_path}',
        ]

        command = [
            "cmake",
            "-S",
            self.config.source_dir,
            "-B",
            self.config.build_dir,
        ] + configure_args

        self.run(command, cwd=self.config.source_dir, label="configure", env=self.config.env)

    def build(self):
        build_args = ["--config", self.config.build_type, "--parallel", str(os.cpu_count() or 1)]
        command = ["cmake", "--build", self.config.build_dir] + build_args
        # The compiler runs in the build dir: relative paths in its diagnostics start there.
        self.run(command, cwd=self.config.source_dir, label="build", env=self.config.env, diag_base=self.config.build_dir)

    def install(self):
        # Multi-config generators (Visual Studio) install Release unless told otherwise.
        command = ["cmake", "--install", self.config.build_dir, "--config", self.config.build_type]
        self.run(command, cwd=self.config.source_dir, label="install", env=self.config.env)
