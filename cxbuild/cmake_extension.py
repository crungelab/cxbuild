from pathlib import Path

from setuptools import Extension

class CMakeExtension(Extension):
    def __init__(self, name, source_dir: Path, install_from: Path, **kwargs):
        Extension.__init__(self, name, sources=[], **kwargs)
        self.source_dir: Path = source_dir
        self.install_from: Path = install_from
