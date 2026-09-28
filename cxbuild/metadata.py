"""Core metadata for a wheel, from a validated [project] table.

pyproject.py has already checked every field. This module adds what needs the
project directory (the readme text, the license files) and writes the text of
dist-info/METADATA (core metadata 2.4) and dist-info/entry_points.txt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from email.utils import formataddr
from pathlib import Path

from packaging.markers import Marker
from packaging.requirements import Requirement

from .pyproject import Person, ProjectTable, ReadmeTable
from .runner import CxBuildError

METADATA_VERSION = "2.4"  # License-Expression and License-File need 2.4

README_TYPES = {".md": "text/markdown", ".rst": "text/x-rst", ".txt": "text/plain"}


class MetadataError(CxBuildError):
    """A file named in [project] (readme, license-files) is missing or unusable."""


def escape_name(name: str) -> str:
    """Name as it appears in wheel and dist-info file names: cxb-simple -> cxb_simple."""
    return re.sub(r"[-_.]+", "_", name).lower()


@dataclass(frozen=True)
class ProjectMetadata:
    project: ProjectTable
    license_files: tuple[Path, ...] = ()  # relative to the project directory
    readme: str | None = None
    readme_type: str | None = None
    entry_points: dict[str, dict[str, str]] = field(default_factory=dict)  # group -> name -> target

    @classmethod
    def from_project(cls, project: ProjectTable, root: Path) -> "ProjectMetadata":
        """`root` is the directory holding pyproject.toml; readme and license paths are relative to it."""
        root = Path(root)
        readme, readme_type = _readme(project.readme, root)
        entry_points: dict[str, dict[str, str]] = {}
        if project.scripts:
            entry_points["console_scripts"] = dict(project.scripts)
        if project.gui_scripts:
            entry_points["gui_scripts"] = dict(project.gui_scripts)
        entry_points.update({group: dict(points) for group, points in project.entry_points.items()})
        return cls(project, _license_files(project.license_files, root), readme, readme_type, entry_points)

    @property
    def name(self) -> str:
        return self.project.name

    @property
    def version(self) -> str:
        return self.project.version

    @property
    def dist_info(self) -> str:
        """The dist-info directory name: cxb_simple-0.0.1.dist-info."""
        return f"{escape_name(self.name)}-{self.version.replace('-', '_')}.dist-info"

    def render(self) -> str:
        """The text of dist-info/METADATA."""
        p = self.project
        headers: list[tuple[str, str]] = [
            ("Metadata-Version", METADATA_VERSION),
            ("Name", p.name),
            ("Version", p.version),
        ]
        if p.description:
            headers.append(("Summary", p.description))
        if p.keywords:
            headers.append(("Keywords", ",".join(p.keywords)))
        headers += _people("Author", p.authors)
        headers += _people("Maintainer", p.maintainers)
        if p.license:
            headers.append(("License-Expression", p.license))
        headers += [("License-File", path.as_posix()) for path in self.license_files]
        headers += [("Project-URL", f"{label}, {url}") for label, url in p.urls.items()]
        headers += [("Classifier", c) for c in p.classifiers]
        if p.requires_python:
            headers.append(("Requires-Python", p.requires_python))
        headers += [("Requires-Dist", r) for r in p.dependencies]
        for extra, reqs in p.optional_dependencies.items():
            headers.append(("Provides-Extra", extra))
            headers += [("Requires-Dist", _with_extra(r, extra)) for r in reqs]
        if self.readme_type:
            headers.append(("Description-Content-Type", self.readme_type))

        text = "".join(f"{key}: {value}\n" for key, value in headers)
        if self.readme is not None:
            text += "\n" + self.readme  # the body: core metadata 2.1+ puts the long description here
        return text

    def render_entry_points(self) -> str | None:
        """The text of dist-info/entry_points.txt, or None when there are none."""
        if not self.entry_points:
            return None
        sections = []
        for group, points in self.entry_points.items():
            lines = [f"[{group}]"] + [f"{name} = {target}" for name, target in points.items()]
            sections.append("\n".join(lines) + "\n")
        return "\n".join(sections)


def _with_extra(requirement: str, extra: str) -> str:
    """Keep the requirement's own marker, and require the extra as well."""
    req = Requirement(requirement)
    condition = f'extra == "{extra}"'
    req.marker = Marker(f"({req.marker}) and {condition}" if req.marker else condition)
    return str(req)


def _people(role: str, people: list[Person]) -> list[tuple[str, str]]:
    """PEP 621: names alone go in Author; anyone with an email goes in Author-email."""
    names = [p.name for p in people if p.name and not p.email]
    emails = [formataddr((p.name or "", p.email)) for p in people if p.email]
    headers = []
    if names:
        headers.append((role, ", ".join(names)))
    if emails:
        headers.append((f"{role}-email", ", ".join(emails)))
    return headers


def _license_files(patterns: list[str], root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for pattern in patterns:
        matches = sorted(p.relative_to(root) for p in root.glob(pattern) if p.is_file())
        if not matches:
            raise MetadataError(f"[project] license-files: {pattern!r} matches no files in {root}")
        files += [m for m in matches if m not in files]
    return tuple(files)


def _readme(readme: str | ReadmeTable | None, root: Path) -> tuple[str | None, str | None]:
    if readme is None:
        return None, None
    if isinstance(readme, str):
        readme = ReadmeTable(file=readme)
    if readme.text is not None:
        return readme.text, readme.content_type
    path = root / readme.file
    if not path.is_file():
        raise MetadataError(f"[project] readme: {readme.file!r} not found in {root}")
    content_type = readme.content_type or README_TYPES.get(path.suffix.lower())
    if content_type is None:
        raise MetadataError(
            f"[project] readme: can't tell the content type of {readme.file!r}; "
            'use readme = {file = "...", content-type = "text/markdown"}'
        )
    return path.read_text(encoding="utf-8"), content_type