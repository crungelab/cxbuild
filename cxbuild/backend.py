"""
PEP 517 build hooks

Every hook runs in a fresh process (pip, build and hatch all call hooks through
pyproject_hooks), so every hook is a logging entry point. Hooks that only
delegate to setuptools log WARNING+ to stderr and leave _cxbuild/ alone: they run
before the build hook, which would overwrite their files anyway. The hooks that
build open the log and the report.

Where the record goes:

* pip (or build, or hatch) on its own: <project>/_cxbuild/cxbuild.log and
  cxbuild_report.md.
* Started by cxbuild's CLI (CBX_ACTIVITY and CXBUILD_ROOT set): the solution's
  _cxbuild/, as <project>.log and <project>_report.md, next to the CLI's own
  report, which links them.

Verbose output: pip's `-C verbose=1`, or CXBUILD_VERBOSE=1 in the environment
(the CLI's --verbose sets it). pip still hides backend output unless it runs with -v.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

import setuptools.build_meta as build_meta
from loguru import logger

from .logsetup import configure_logging
from .project import Project
from .runner import DEFAULT_NAME, Runner

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

TRUE = {"1", "true", "yes", "on"}


def _under_cxbuild() -> bool:
    """True when cxbuild's CLI started the build tool that is calling us."""
    return bool(os.environ.get("CBX_ACTIVITY"))


def _record_location(project_dir: Path) -> tuple[Path, str]:
    """The root whose _cxbuild/ holds this hook's log and report, and their base name."""
    solution_root = os.environ.get("CXBUILD_ROOT")
    if _under_cxbuild() and solution_root:
        return Path(solution_root), project_dir.name
    return project_dir, DEFAULT_NAME


def _flag(settings: Mapping[str, Any] | None, key: str) -> bool:
    value = (settings or {}).get(key)
    if isinstance(value, list):  # repeated -C key=... gives a list
        value = value[-1] if value else None
    return value is not None and str(value).lower() in TRUE


def _delegating() -> None:
    """Setup for hooks that just call setuptools."""
    configure_logging(Path.cwd(), file=False)


def _build(hook: str, wheel_directory: str, config_settings: Mapping[str, Any] | None, editable: bool) -> str:
    project_dir = Path.cwd()
    root, name = _record_location(project_dir)
    configure_logging(root, name=name)
    logger.debug("hook {}: wheel_directory={} config_settings={}", hook, wheel_directory, config_settings)
    verbose = _flag(config_settings, "verbose") or _flag(os.environ, "CXBUILD_VERBOSE")

    with Runner(root, hook, verbose=verbose, name=name) as runner:
        project = Project(project_dir, runner)
        return project.backend_wheel(Path(wheel_directory), editable=editable).name


def _supported_features():
    return ["build_editable"]


def build_sdist(
    sdist_directory: str,
    config_settings: dict[str, list[str] | str] | None = None,
) -> str:
    _delegating()
    return build_meta.build_sdist(sdist_directory, config_settings)


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, list[str] | str] | None = None,
    metadata_directory: str | None = None,
) -> str:
    return _build("build_wheel", wheel_directory, config_settings, editable=False)


def build_editable(
    wheel_directory: str,
    config_settings: dict[str, list[str] | str] | None = None,
    metadata_directory: str | None = None,
) -> str:
    # If not invoked indirectly by cxbuild itself do the default action
    if not _under_cxbuild():
        _delegating()
        return build_meta.build_editable(wheel_directory, config_settings, metadata_directory)
    return _build("build_editable", wheel_directory, config_settings, editable=True)


def get_requires_for_build_sdist(
    config_settings: dict[str, str | list[str]] | None = None,
) -> list[str]:
    _delegating()
    return build_meta.get_requires_for_build_sdist(config_settings)


def get_requires_for_build_wheel(
    config_settings: Mapping[str, Any] | None = None,
) -> list[str]:
    _delegating()
    return build_meta.get_requires_for_build_wheel(config_settings)


def get_requires_for_build_editable(
    config_settings: Mapping[str, Any] | None = None,
) -> list[str]:
    return get_requires_for_build_wheel(config_settings)


def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings: dict[str, list[str] | str] | None = None,
) -> str:
    _delegating()
    return build_meta.prepare_metadata_for_build_wheel(metadata_directory, config_settings)


def prepare_metadata_for_build_editable(
    metadata_directory: str,
    config_settings: dict[str, list[str] | str] | None = None,
) -> str:
    return prepare_metadata_for_build_wheel(metadata_directory, config_settings)
