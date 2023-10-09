"""
PEP 517 build hooks
"""


from __future__ import annotations
from typing import Mapping, Any
import os
import setuptools.build_meta as build_meta

__all__ = [
    "_supported_features",
    "build_sdist",
    "build_wheel",
    "build_editable",
    "get_requires_for_build_sdist",
    "get_requires_for_build_wheel",
    "get_requires_for_build_editable",
    "prepare_metadata_for_build_wheel",
    "prepare_metadata_for_build_editable",
]

from pathlib import Path
from loguru import logger

from .project import Project


def _supported_features():
    return ["build_editable"]


def build_sdist(
    sdist_directory: str,
    config_settings: dict[str, list[str] | str] | None = None,
) -> str:
    logger.debug("Build hook: build_sdist")
    return build_meta.build_sdist(sdist_directory, config_settings)


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, list[str] | str] | None = None,
    metadata_directory: str | None = None,
) -> str:
    logger.debug("Build hook: build_wheel")
    logger.debug(f"wheel_directory: {wheel_directory}")
    project = Project(Path.cwd())
    return project.build_wheel(wheel_directory, config_settings, metadata_directory)


def build_editable(
    wheel_directory: str,
    config_settings: dict[str, list[str] | str] | None = None,
    metadata_directory: str | None = None,
) -> str:
    logger.debug("Build hook: build_editable")
    logger.debug(f"wheel_directory: {wheel_directory}")
    # If not invoked indirectly by cxbuild itself do the default action
    if not os.environ.get('CBX_ACTIVITY'):
        return build_meta.build_editable(wheel_directory, config_settings, metadata_directory)
    return build_wheel(wheel_directory, config_settings, metadata_directory)


def get_requires_for_build_sdist(
    config_settings: dict[str, str | list[str]] | None = None  # noqa: ARG001
) -> list[str]:
    logger.debug("Build hook: get_requires_for_build_sdist")
    return build_meta.get_requires_for_build_sdist(config_settings)


def get_requires_for_build_wheel(
    config_settings: Mapping[str, Any] | None = None
) -> list[str]:
    logger.debug("Build hook: get_requires_for_build_wheel")
    #return []
    return build_meta.get_requires_for_build_wheel(config_settings)


def get_requires_for_build_editable(self, config_settings=None):
    logger.debug("Build hook: get_requires_for_build_editable")
    return get_requires_for_build_wheel(config_settings)


def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings: dict[str, list[str] | str] | None = None,
) -> str:
    logger.debug("Build hook: prepare_metadata_for_build_wheel")
    return build_meta.prepare_metadata_for_build_wheel(
        metadata_directory, config_settings
    )


def prepare_metadata_for_build_editable(metadata_directory, config_settings=None):
    logger.debug("Build hook: build_editable")
    return build_meta.prepare_metadata_for_build_wheel(
        metadata_directory, config_settings
    )
