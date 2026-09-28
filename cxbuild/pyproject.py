"""pyproject.toml, parsed once and validated.

Two tables matter to cxbuild, and both are checked strictly:

* [project] (PEP 621): shape, types and unknown keys by pydantic; the
  packaging-level meaning of each field (names, versions, requirements,
  SPDX expressions) by `packaging`. Values are stored normalized.
* [tool.cxbuild]: cxbuild's own configuration.

Everything else in the file ([build-system], other tools) is kept but not
checked. A mistake fails at load time with the file and field in the message:

    pkg/imgui/pyproject.toml: project.optional-dependencies.dev[0]: invalid requirement 'rich>'
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pydantic
from packaging.licenses import InvalidLicenseExpression, canonicalize_license_expression
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from pydantic import ConfigDict, Field, field_validator, model_validator

from .runner import CxBuildError

# PEP 508 name, as core metadata requires it.
VALID_NAME = re.compile(r"^([A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9])$", re.IGNORECASE)


class PyProjectError(CxBuildError):
    """pyproject.toml is missing, unreadable, or doesn't validate."""


class Strict(pydantic.BaseModel):
    """Tables cxbuild owns or relies on: unknown keys are errors, since a typo would otherwise be ignored."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class Open(pydantic.BaseModel):
    """Tables cxbuild only passes through: other keys are kept as they are."""

    model_config = ConfigDict(extra="allow", frozen=True, populate_by_name=True)


# --- [project] -------------------------------------------------------------


class Person(Strict):
    name: str | None = None
    email: str | None = None

    @model_validator(mode="after")
    def _name_or_email(self) -> "Person":
        if not (self.name or self.email):
            raise ValueError("needs a name or an email")
        return self


class ReadmeTable(Strict):
    file: str | None = None
    text: str | None = None
    content_type: str | None = Field(None, alias="content-type")

    @model_validator(mode="after")
    def _file_or_text(self) -> "ReadmeTable":
        if (self.file is None) == (self.text is None):
            raise ValueError("give exactly one of file or text")
        if self.text is not None and self.content_type is None:
            raise ValueError("text needs a content-type")
        return self


class ProjectTable(Strict):
    name: str
    version: str
    description: str | None = None
    readme: ReadmeTable | None = None
    requires_python: str | None = Field(None, alias="requires-python")
    license: str | None = None
    license_files: list[str] = Field(default_factory=list, alias="license-files")
    authors: list[Person] = Field(default_factory=list)
    maintainers: list[Person] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    classifiers: list[str] = Field(default_factory=list)
    urls: dict[str, str] = Field(default_factory=dict)
    scripts: dict[str, str] = Field(default_factory=dict)
    gui_scripts: dict[str, str] = Field(default_factory=dict, alias="gui-scripts")
    entry_points: dict[str, dict[str, str]] = Field(default_factory=dict, alias="entry-points")
    dependencies: list[str] = Field(default_factory=list)
    optional_dependencies: dict[str, list[str]] = Field(default_factory=dict, alias="optional-dependencies")
    dynamic: list[str] = Field(default_factory=list)

    @field_validator("readme", mode="before")
    @classmethod
    def _readme(cls, value: Any) -> Any:
        return {"file": value} if isinstance(value, str) else value  # readme = "README.md" is the short form

    @field_validator("name")
    @classmethod
    def _name(cls, name: str) -> str:
        if not VALID_NAME.match(name):
            raise ValueError(f"{name!r} is not a valid distribution name")
        return name  # Name keeps its spelling; file names are escaped where they're made

    @field_validator("version")
    @classmethod
    def _version(cls, version: str) -> str:
        try:
            return str(Version(version))
        except InvalidVersion:
            raise ValueError(f"{version!r} is not a valid version") from None

    @field_validator("description")
    @classmethod
    def _single_line(cls, description: str | None) -> str | None:
        if description is not None and ("\n" in description or "\r" in description):
            raise ValueError("must be a single line")
        return description

    @field_validator("requires_python")
    @classmethod
    def _requires_python(cls, spec: str | None) -> str | None:
        if spec is None:
            return None
        try:
            return str(SpecifierSet(spec))
        except InvalidSpecifier:
            raise ValueError(f"{spec!r} is not a valid version specifier") from None

    @field_validator("license", mode="before")
    @classmethod
    def _license(cls, value: Any) -> Any:
        if isinstance(value, dict):
            raise ValueError(
                'a table is not supported: use an SPDX expression (license = "MIT") '
                'and license-files = ["LICENSE"]'
            )
        if isinstance(value, str):
            try:
                return canonicalize_license_expression(value)
            except InvalidLicenseExpression as e:
                raise ValueError(str(e)) from None
        return value

    @field_validator("dependencies")
    @classmethod
    def _dependencies(cls, reqs: list[str]) -> list[str]:
        return [_requirement(r, f"[{i}]") for i, r in enumerate(reqs)]

    @field_validator("optional_dependencies")
    @classmethod
    def _optional_dependencies(cls, extras: dict[str, list[str]]) -> dict[str, list[str]]:
        normalized: dict[str, list[str]] = {}
        for extra, reqs in extras.items():
            name = canonicalize_name(extra)  # PEP 685
            if name in normalized:
                raise ValueError(f"{extra!r} duplicates {name!r} once normalized")
            normalized[name] = [_requirement(r, f".{extra}[{i}]") for i, r in enumerate(reqs)]
        return normalized

    @field_validator("entry_points")
    @classmethod
    def _entry_points(cls, groups: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        for reserved, table in (("console_scripts", "scripts"), ("gui_scripts", "gui-scripts")):
            if reserved in groups:
                raise ValueError(f"{reserved} belongs in [project.{table}]")
        return groups

    @field_validator("dynamic")
    @classmethod
    def _dynamic(cls, dynamic: list[str]) -> list[str]:
        if dynamic:
            raise ValueError(f"not supported by cxbuild: {dynamic}")
        return dynamic


def _requirement(text: str, where: str) -> str:
    try:
        return str(Requirement(text))
    except InvalidRequirement as e:
        reason = str(e).splitlines()[0]  # packaging adds a caret diagram on later lines
        raise ValueError(f"{where}: invalid requirement {text!r}: {reason}") from None


# --- [tool.cxbuild] --------------------------------------------------------


class ExtensionConfig(Strict):
    name: str  # dotted module name, e.g. "cxb_simple._core"; the package part is the install prefix


class WheelConfig(Strict):
    packages: list[str] | None = None  # default: the extension's install prefix
    exclude: list[str] = Field(default_factory=list)


class CxBuildConfig(Strict):
    projects: list[str] = Field(default_factory=list)  # solution: project directories or globs
    plugins: list[str] = Field(default_factory=list)  # solution: modules whose prefix goes on CMAKE_PREFIX_PATH
    extension: ExtensionConfig | None = None  # project
    wheel: WheelConfig = Field(default_factory=WheelConfig)  # project


class ToolTable(Open):
    cxbuild: CxBuildConfig = Field(default_factory=CxBuildConfig)


# --- the file --------------------------------------------------------------


class PyProject(Open):
    project: ProjectTable | None = None
    tool: ToolTable = Field(default_factory=ToolTable)

    @classmethod
    def load(cls, path: Path) -> "PyProject":
        """Load <path>/pyproject.toml."""
        file = Path(path) / "pyproject.toml"
        try:
            with open(file, "rb") as f:
                data = tomllib.load(f)
        except FileNotFoundError:
            raise PyProjectError(f"{file}: not found") from None
        except tomllib.TOMLDecodeError as e:
            raise PyProjectError(f"{file}: {e}") from None
        return cls.parse(data, source=file)

    @classmethod
    def parse(cls, data: dict[str, Any], source: Path | str = "pyproject.toml") -> "PyProject":
        try:
            return cls.model_validate(data)
        except pydantic.ValidationError as e:
            raise PyProjectError(format_errors(e, source)) from None

    @property
    def name(self) -> str:
        if self.project is None:
            raise PyProjectError("pyproject.toml has no [project] table")
        return self.project.name


def format_errors(error: pydantic.ValidationError, source: Path | str) -> str:
    """One line per problem: `<file>: project.optional-dependencies.dev[0]: invalid requirement ...`."""
    lines = []
    for e in error.errors():
        where = ""
        for part in e["loc"]:
            where += f"[{part}]" if isinstance(part, int) else (f".{part}" if where else str(part))
        message = e["msg"].removeprefix("Value error, ")
        message = re.sub(r" or instance of \w+", "", message)  # pydantic's class names mean nothing in TOML
        if e["type"] == "extra_forbidden":
            message = "unknown key"
        if message.startswith((".", "[")):  # a validator's location inside its field (see _requirement)
            inner, message = message.split(": ", 1)
            where += inner
        lines.append(f"{source}: {where}: {message}")
    return "\n".join(lines)