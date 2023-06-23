import os
from pathlib import Path

from setuptools import Extension
from loguru import logger

from .activity import get_activity, BuildActivity, DevelopActivity
from .copyutils import copy_directory_contents

class CMakeExtension(Extension):
    def __init__(self, name, source_dir: Path, install_prefix: Path, editable: bool, **kwargs):
        Extension.__init__(self, name, sources=[], **kwargs)
        self.source_dir: Path = source_dir
        self.install_prefix: Path = install_prefix
        self.editable = editable

    def build(self, ext_path: Path, ext_dir: Path) -> None:
        logger.debug(f'ext_path: {ext_path}')
        logger.debug(f'ext_dir: {ext_dir}')

        activity = get_activity()
        logger.debug(activity.__dict__)

        artifacts_dir = activity.artifacts_dir
        logger.debug(f'artifacts_dir: {artifacts_dir}')
        install_from = artifacts_dir / self.install_prefix
        logger.debug(f'install_from: {install_from}')
        install_to = ext_dir
        logger.debug(f'install_to: {install_to}')
        copy_directory_contents(install_from, install_to)
        if self.editable:
            install_editable_to = self.source_dir / self.install_prefix
            logger.debug(f'install_editable_to: {install_editable_to}')
            copy_directory_contents(install_from, install_editable_to)
