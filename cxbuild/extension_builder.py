import os
import shutil
from pathlib import Path

from setuptools.command.build_ext import build_ext

from .cmake_extension import CMakeExtension

class ExtensionBuilder(build_ext):

    def initialize_options(self):
        build_ext.initialize_options(self)


    def finalize_options(self):
        build_ext.finalize_options(self)

    def run(self) -> None:
        cmake_extensions = [e for e in self.extensions if isinstance(e, CMakeExtension)]

        if len(cmake_extensions) == 0:
            raise ValueError("No CMakeExtension objects found")

        for ext in cmake_extensions:
            self.build_extension(ext)

    def build_extension(self, ext: CMakeExtension) -> None:
        ext_path = self.get_ext_fullpath(ext.name)
        ext_dir = Path(ext_path).parent.absolute()
        ext.build(ext_path, ext_dir)