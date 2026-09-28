"""
PEP 517 build hooks

cxbuild builds wheels from what a cxbuild command has just built with cmake: the
CLI saves an activity and points CBX_ACTIVITY at it, then runs pip or uv, which
call these hooks. Two cases have no activity:

* build_editable for a project inside a cxbuild solution, as when a hatch
  workspace installs its members: the hook builds the solution itself (under
  the build lock, since uv builds members concurrently), stages the module and
  writes the editable wheel. See Solution.prepare_editable.
* build_wheel: refused with a message saying to run `cxbuild build`. Release
  wheels come from the CLI, which builds the whole solution once.

sdists are not supported at all. setuptools is not involved.

Every hook runs in a fresh process (pip, build and hatch all call hooks through
pyproject_hooks), so every hook is a logging entry point. The light hooks
(requirements, metadata, sdist) log WARNING+ to stderr and leave _cxbuild/
alone: they run before the build hook, which would overwrite their files anyway.
The wheel hooks open the log and the report.

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

from loguru import logger

from .logsetup import configure_logging
from .metadata import ProjectMetadata
from .project import Project
from .pyproject import PyProject
from .runner import DEFAULT_NAME, CxBuildError, Runner
from .solution import Solution, find_solution_root

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


def _light() -> None:
    """Setup for the hooks that write no files of their own: warnings to stderr only."""
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


def _standalone_editable(wheel_directory: str, config_settings: Mapping[str, Any] | None) -> str:
    """build_editable with no cxbuild command around it: build the solution, stage this
    project's module, write the editable wheel. The record goes where `cxbuild develop`'s
    would: the solution's _cxbuild/, as <project>.log and <project>_report.md."""
    project_dir = Path.cwd().resolve()
    root = find_solution_root(project_dir)  # outside a solution: a CxBuildError that says so
    name = project_dir.name
    configure_logging(root, name=name)
    logger.debug("hook build_editable (standalone): project {}, solution {}", project_dir, root)
    verbose = _flag(config_settings, "verbose") or _flag(os.environ, "CXBUILD_VERBOSE")

    with Runner(root, "build_editable", verbose=verbose, name=name) as runner:
        solution = Solution(root, runner)
        project = solution.project_containing(project_dir)
        if project is None or project.path != project_dir:
            raise CxBuildError(f"{project_dir} is not one of the projects of the solution at {root}")
        builder = solution.prepare_editable(project)
        return project.write_wheel(builder, Path(wheel_directory), editable=True).name


def _prepare_metadata(metadata_directory: str) -> str:
    """Write <name>-<version>.dist-info with METADATA (and entry_points.txt): what pip reads
    to resolve dependencies. Only pyproject.toml is needed; nothing is built."""
    _light()
    project_dir = Path.cwd()
    metadata = ProjectMetadata.from_project(PyProject.load(project_dir).project, project_dir)
    dist_info = Path(metadata_directory) / metadata.dist_info
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(metadata.render(), encoding="utf-8")
    if (entry_points := metadata.render_entry_points()) is not None:
        (dist_info / "entry_points.txt").write_text(entry_points, encoding="utf-8")
    return metadata.dist_info


def _supported_features():
    return ["build_editable"]


def build_sdist(
    sdist_directory: str,
    config_settings: dict[str, list[str] | str] | None = None,
) -> str:
    # PEP 517 requires the hook, not success. An sdist cxbuild can't build from
    # would only give users a confusing cmake failure later.
    _light()
    raise CxBuildError("cxbuild builds wheels only: sdists are not supported")


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
    if _under_cxbuild():  # `cxbuild develop` has already built and staged: just the wheel
        return _build("build_editable", wheel_directory, config_settings, editable=True)
    return _standalone_editable(wheel_directory, config_settings)


def get_requires_for_build_sdist(
    config_settings: dict[str, str | list[str]] | None = None,
) -> list[str]:
    return []


def get_requires_for_build_wheel(
    config_settings: Mapping[str, Any] | None = None,
) -> list[str]:
    return []  # nothing beyond cxbuild itself


def get_requires_for_build_editable(
    config_settings: Mapping[str, Any] | None = None,
) -> list[str]:
    return []


def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings: dict[str, list[str] | str] | None = None,
) -> str:
    return _prepare_metadata(metadata_directory)


def prepare_metadata_for_build_editable(
    metadata_directory: str,
    config_settings: dict[str, list[str] | str] | None = None,
) -> str:
    return _prepare_metadata(metadata_directory)
