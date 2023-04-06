"""
PEP 517 build hooks
"""


from __future__ import annotations

import setuptools.build_meta as build_meta
__all__ = [
    "build_sdist",
    "build_wheel",
    "get_requires_for_build_sdist",
    "get_requires_for_build_wheel",
    "prepare_metadata_for_build_wheel",
]

def build_sdist(
    sdist_directory: str,
    config_settings: dict[str, list[str] | str] | None = None,
) -> str:
    return build_meta.build_sdist(sdist_directory, config_settings)

def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, list[str] | str] | None = None,
    metadata_directory: str | None = None,
) -> str:
    return build_meta.build_wheel(wheel_directory, config_settings, metadata_directory)

def get_requires_for_build_sdist(
    config_settings: dict[str, str | list[str]] | None = None  # noqa: ARG001
) -> list[str]:
    #return ["pathspec", "pyproject_metadata"]
    return build_meta.get_requires_for_build_sdist(config_settings)

def get_requires_for_build_wheel(
    config_settings: dict[str, str | list[str]] | None = None,
) -> list[str]:
    return build_meta.get_requires_for_build_wheel(config_settings)

def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings: dict[str, list[str] | str] | None = None,
) -> str:
    return build_meta.prepare_metadata_for_build_wheel(metadata_directory, config_settings)
