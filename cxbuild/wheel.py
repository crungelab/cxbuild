"""Write wheels: cxbuild's replacement for setuptools' bdist_wheel.

By the time a wheel is written, cmake has installed the compiled module into
_cxbuild/artifacts/<install prefix>/. A wheel is then a zip of:

* each package directory from the project (default: the install prefix,
  e.g. crunge/imgui), minus caches, excluded paths and stale compiled modules;
* everything cmake installed for the project, which wins over the source tree;
* <name>-<version>.dist-info/: METADATA, WHEEL, entry_points.txt, licenses/,
  and RECORD, last.

An editable wheel holds the dist-info plus a .pth file naming the project
directory, so Python imports straight from the source tree (where `develop`
copies the built module).

Namespace packages need no special handling: packaging crunge/imgui writes
files under crunge/imgui/ and never a crunge/__init__.py.
"""

from __future__ import annotations

import base64
import csv
import fnmatch
import hashlib
import io
import os
import stat
import sysconfig
import time
import zipfile
from dataclasses import dataclass, field
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path, PurePosixPath

from packaging.tags import Tag, sys_tags

from . import __about__
from .metadata import ProjectMetadata, escape_name
from .runner import CxBuildError

SKIPPED_DIRS = {"__pycache__"}
SKIPPED_SUFFIXES = {".pyc", ".pyo"}
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)  # the earliest date a zip can hold


class WheelError(CxBuildError):
    """The wheel can't be written: a package directory or cmake's output is missing."""


def default_packages(extension_name: str) -> list[PurePosixPath]:
    """The package holding the extension: crunge.imgui._imgui -> crunge/imgui."""
    parts = extension_name.split(".")[:-1]
    if not parts:
        raise WheelError(f"extension {extension_name!r} is not inside a package")
    return [PurePosixPath(*parts)]


def wheel_tag() -> Tag:
    """The tag for a binary wheel built by this interpreter, on this platform, unrepaired.

    Interpreter and ABI come from packaging (which knows cp313t and friends); the
    platform is sysconfig's, never a manylinux tag: earning that is a repair
    tool's job, and claiming it here would be false.
    """
    platform = sysconfig.get_platform().replace("-", "_").replace(".", "_")
    tags = list(sys_tags())
    for tag in tags:
        if tag.platform == platform:
            return tag
    return Tag(tags[0].interpreter, tags[0].abi, platform)


@dataclass(frozen=True)
class WheelFile:
    arcname: str  # path inside the wheel, posix
    source: Path | None = None  # file to copy, or
    data: bytes | None = None  # contents written directly
    executable: bool = False

    def read(self) -> bytes:
        return self.data if self.data is not None else self.source.read_bytes()


@dataclass
class WheelBuilder:
    metadata: ProjectMetadata
    project_dir: Path  # holds pyproject.toml and the package directories
    artifacts_dir: Path  # _cxbuild/artifacts: cmake's install prefix
    packages: list[PurePosixPath]  # package directories, relative to project_dir
    exclude: list[str] = field(default_factory=list)  # fnmatch patterns on wheel paths
    tag: Tag = field(default_factory=wheel_tag)

    # --- names -----------------------------------------------------------

    @property
    def filename(self) -> str:
        version = self.metadata.version.replace("-", "_")
        return f"{escape_name(self.metadata.name)}-{version}-{self.tag}.whl"

    # --- building --------------------------------------------------------

    def build(self, out_dir: Path) -> Path:
        """Write the wheel into out_dir and return its path."""
        return self._write(out_dir, self.package_files())

    def build_editable(self, out_dir: Path) -> Path:
        """Write an editable wheel: metadata plus a .pth naming the project directory."""
        pth = WheelFile(
            f"_{escape_name(self.metadata.name)}_cxbuild_editable.pth",
            data=f"{Path(self.project_dir).resolve()}\n".encode(),
        )
        return self._write(out_dir, [pth])

    # --- collecting ------------------------------------------------------

    def package_files(self) -> list[WheelFile]:
        """Package files from the project, overlaid with everything cmake installed for them."""
        files: dict[str, WheelFile] = {}
        for package in self.packages:
            source_dir = Path(self.project_dir) / package
            if not source_dir.is_dir():
                raise WheelError(f"package directory {package} not found in {self.project_dir}")
            for path in _walk(source_dir):
                arcname = (package / path.relative_to(source_dir).as_posix()).as_posix()
                if path.name.endswith(tuple(EXTENSION_SUFFIXES)):
                    continue  # a copy left by an editable install; the build output is below
                files[arcname] = _from_path(arcname, path)

        built = 0
        for package in self.packages:
            artifacts = Path(self.artifacts_dir) / package
            if not artifacts.is_dir():
                continue
            for path in _walk(artifacts):
                arcname = (package / path.relative_to(artifacts).as_posix()).as_posix()
                files[arcname] = _from_path(arcname, path)
                built += 1
        if not built:
            wanted = ", ".join(str(Path(self.artifacts_dir) / p) for p in self.packages)
            raise WheelError(f"no build output in {wanted}: has cmake built and installed this project?")

        return [f for name, f in sorted(files.items()) if not self._excluded(name)]

    def _excluded(self, arcname: str) -> bool:
        return any(fnmatch.fnmatchcase(arcname, pattern) for pattern in self.exclude)

    def dist_info_files(self) -> list[WheelFile]:
        """Everything in dist-info except RECORD."""
        dist_info = self.metadata.dist_info
        wheel = (
            "Wheel-Version: 1.0\n"
            f"Generator: cxbuild {__about__.__version__}\n"
            "Root-Is-Purelib: false\n"  # a compiled module: the wheel goes to platlib
            f"Tag: {self.tag}\n"
        )
        files = [
            WheelFile(f"{dist_info}/METADATA", data=self.metadata.render().encode()),
            WheelFile(f"{dist_info}/WHEEL", data=wheel.encode()),
        ]
        if (entry_points := self.metadata.render_entry_points()) is not None:
            files.append(WheelFile(f"{dist_info}/entry_points.txt", data=entry_points.encode()))
        for license_file in self.metadata.license_files:
            source = Path(self.project_dir) / license_file
            files.append(_from_path(f"{dist_info}/licenses/{license_file.as_posix()}", source))
        return files

    # --- writing ---------------------------------------------------------

    def _write(self, out_dir: Path, contents: list[WheelFile]) -> Path:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / self.filename
        partial = target.with_suffix(".whl.partial")
        record = f"{self.metadata.dist_info}/RECORD"

        rows: list[list[str]] = []
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as whl:
            for f in [*contents, *self.dist_info_files()]:  # dist-info after the package
                data = f.read()
                whl.writestr(_zipinfo(f.arcname, f.executable), data)
                rows.append([f.arcname, _hash(data), str(len(data))])
            rows.append([record, "", ""])  # RECORD can't hash itself
            text = io.StringIO()
            csv.writer(text, lineterminator="\n").writerows(rows)
            whl.writestr(_zipinfo(record, False), text.getvalue().encode())

        partial.replace(target)  # never leave a half-written wheel under the real name
        return target


# --- helpers -------------------------------------------------------------


def _walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIPPED_DIRS)
        for name in sorted(filenames):
            if Path(name).suffix not in SKIPPED_SUFFIXES:
                yield Path(dirpath) / name


def _from_path(arcname: str, path: Path) -> WheelFile:
    executable = bool(path.stat().st_mode & stat.S_IXUSR)
    return WheelFile(arcname, source=path, executable=executable)


def _hash(data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return f"sha256={digest.decode()}"


def _zipinfo(arcname: str, executable: bool) -> zipfile.ZipInfo:
    """Fixed timestamps and permissions: the same tree always gives the same wheel."""
    info = zipfile.ZipInfo(arcname, date_time=_timestamp())
    mode = 0o755 if executable else 0o644
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _timestamp() -> tuple[int, int, int, int, int, int]:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch is None:
        return ZIP_EPOCH
    return max(ZIP_EPOCH, time.gmtime(int(epoch))[:6])