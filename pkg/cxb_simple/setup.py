from pathlib import Path

import setuptools

from cxbuild.cmake_extension import CMakeExtension
from cxbuild.extension_builder import ExtensionBuilder

setuptools.setup(
    ext_modules=[
        CMakeExtension(
            name="cxb_simple._core",
            source_dir=Path.cwd(),
            install_from=Path('cxb_simple'),
        ),
    ],
    cmdclass=dict(
        build_ext=ExtensionBuilder,
    ),
)
