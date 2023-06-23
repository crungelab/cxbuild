from __future__ import annotations

import dataclasses
import sys, os
import shutil
from pathlib import Path

from .tool import Tool


class CMakeConfigError(Exception):
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
    posix_paths = ";".join(str(path.as_posix()) for path in paths)
    print(posix_paths)
    return posix_paths

class CMakeTool(Tool):
    def __init__(self, config: CMakeConfig) -> None:
        super().__init__()
        self.config = config

    def configure(self):
        print('configure')
        # Initialize the CMake configuration arguments
        configure_args = []

        # Select the appropriate generator and accompanying settings
        if self.config.generator is not None:
            configure_args += [f'-G "{self.config.generator}"']

            if self.config.generator == "Ninja":
                configure_args += [f"-DCMAKE_MAKE_PROGRAM={shutil.which('ninja')}"]

        # CMake configure arguments
        cmake_install_prefix = Path.cwd() / '_cxbuild/artifacts'

        cmake_prefix_path = join_posix_paths(self.config.prefix_dirs)
        print('cmake_prefix_path: ', cmake_prefix_path)

        configure_args += [
            f'-DCMAKE_BUILD_TYPE={self.config.build_type}',
            f'-DCMAKE_INSTALL_PREFIX:PATH={cmake_install_prefix}',
            #f"-DCMAKE_MODULE_PATH:PATH={cmake_module_path}",
            f'-DCMAKE_PREFIX_PATH:PATH={cmake_prefix_path}',
        ]

        command = [
            "cmake",
            "-S",
            self.config.source_dir,
            "-B",
            self.config.build_dir,
        ] + configure_args

        self.run(command)

    def build(self):
        print('build')
        build_args = ["--config", self.config.build_type]
        command = ["cmake", "--build", self.config.build_dir] + build_args
        self.run(command)

    def install(self):
        print('install')
        command = ["cmake", "--install", self.config.build_dir]
        self.run(command)