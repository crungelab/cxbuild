import os
import shutil
from pathlib import Path

from setuptools.command.build_ext import build_ext

from .cmake_extension import CMakeExtension
from .copyutils import copy_directory_contents

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
        print('ext_path: ', ext_path)
        ext_dir = Path(ext_path).parent.absolute()
        print('ext_dir: ', ext_dir)

        CX_INSTALL_DIR = Path(os.environ.get('CX_INSTALL_DIR'))
        print('CX_INSTALL_DIR: ', CX_INSTALL_DIR)
        install_from = CX_INSTALL_DIR / ext.install_from
        print('install_from: ', install_from)
        install_to = ext_dir
        print('install_to: ', install_to)
        copy_directory_contents(install_from, install_to)
