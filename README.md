# CxBuild :bricks:

Crunge Extension Builder

cxbuild builds Python packages with C++ extensions, many at a time, from a single
CMake build. It is a [PEP 517](https://peps.python.org/pep-0517/) build backend and a
command-line tool, made for [crunge](https://github.com/crungelab/crunge): a dozen
binding packages sharing one CMake build. It suits any monorepo of that shape.

- **One CMake build for many packages.** Projects share one build directory and their
  dependencies. The build is incremental, and every package's module comes out of it.
- **No setuptools.** cxbuild writes wheels and their metadata itself, straight from
  `[project]` in each `pyproject.toml`.
- **Editable installs that work.** Python edits take effect immediately; C++ changes
  need one `cxbuild develop`.
- **A record of every build.** A log and a Markdown report for every run, including
  runs inside pip, which hides the build's output.

## Requirements

- Python 3.12 or newer
- CMake 3.15 or newer, and a C++ compiler
- uv or pip, for installs (uv is preferred when available)

## A solution and its projects

cxbuild builds a *solution*: a root directory with one CMake build, and the *projects*
under it, each a Python package with one compiled extension.

```
my-solution/
├── pyproject.toml          # lists the projects
├── CMakeLists.txt          # add_subdirectory() for each project
└── pkg/
    └── imgui/
        ├── pyproject.toml  # the package, and which extension cxbuild builds for it
        ├── CMakeLists.txt  # builds and installs the extension module
        └── crunge/imgui/   # the Python package
```

The solution's `pyproject.toml`:

```toml
[project]
name = "my-solution"
version = "0.1.0"

[tool.cxbuild]
projects = ["pkg/*"]
# Modules whose location (two levels above their __init__.py) goes on
# CMAKE_PREFIX_PATH, so CMake finds their config files even when they are
# installed editable.
plugins = ["cxbind"]
```

A project's `pyproject.toml`:

```toml
[build-system]
requires = ["cxbuild>=0.4"]
build-backend = "cxbuild.backend"

[project]
name = "crunge-imgui"
version = "0.1.0"
description = "Crunge ImGui Extension"
readme = "README.md"
requires-python = ">=3.12"
license = "MIT"
license-files = ["LICENSE"]

[tool.cxbuild.extension]
name = "crunge.imgui._imgui"
```

The extension's package, `crunge/imgui` here, is where the project's CMake installs
the module:

```cmake
install(TARGETS imgui_module DESTINATION crunge/imgui)
```

A wheel contains that package directory from the project, plus everything CMake
installed into it; the build output always wins over a stale copy in the source tree.
Namespace packages need nothing special: packaging `crunge/imgui` never adds a
`crunge/__init__.py`. To package other directories, or leave files out:

```toml
[tool.cxbuild.wheel]
packages = ["crunge.imgui", "crunge.imgui_extras"]   # default: the extension's package
exclude = ["*/tests/*"]                                # fnmatch patterns on wheel paths
```

## Commands

Run from anywhere inside a solution; cxbuild finds the root.

| Command | What it does |
| --- | --- |
| `cxbuild develop [project]` | Debug build, then an editable install of every project, or just the one named. From inside a project's directory, just that project. |
| `cxbuild build` | Release build, then one wheel per project in `<solution>/dist/` |
| `cxbuild configure` | CMake configure only |
| `cxbuild install` | CMake install only |
| `cxbuild clean` | Remove build leftovers in the projects, and `dist/` |

`-v`/`--verbose` streams the build output to the terminal.

**Editable installs.** `develop` installs each project editable: the installed package
points at the source tree, and the built module is copied next to the Python code.
Python edits are live; after C++ changes, run `cxbuild develop` again, which only
rebuilds what changed.

**Wheels.** `build` tags wheels for the interpreter and platform that built them, for
example `cp312-cp312-linux_x86_64`, never `manylinux`. Before publishing, repair them
with auditwheel (Linux), delocate (macOS) or delvewheel (Windows), which bundles
shared libraries and applies the right platform tag.

## Hatch and uv workspaces

cxbuild works as the backend for [hatch](https://hatch.pypa.io/) workspace members.
Creating the environment builds the solution once, and every member is installed
editable. Several members can build at once: they share the build under a lock, and
the first one to get it does the work.

```toml
[tool.hatch.envs.default]
python = "3.12"
installer = "uv"
skip-install = true
workspace.members = [
  "pkg/imgui", "pkg/implot",
  "../cxbuild",   # the toolchain, editable from a checkout
]

[tool.uv]
# Members build inside the hatch environment, where cxbuild is installed.
no-build-isolation-package = ["crunge-imgui", "crunge-implot"]
```

Two notes:

- **`no-build-isolation-package`** is what lets members build inside the environment,
  where cxbuild and the tools it imports while configuring are installed. Only the
  listed packages lose isolation; everything else builds as usual.
- **List local checkouts as members, not `sources`.** In hatch 1.18.1, a `sources` path
  installs a plain copy although it is documented as editable; members are always
  editable.

## Logs and reports

Every run writes to `_cxbuild/` at the solution root:

- **`cxbuild.log`** has everything at DEBUG level, including each command's output
  tagged with its step. It's the file to search.
- **`cxbuild_report.md`** has a summary table, compiler and CMake diagnostics grouped
  by file, each step's output (expanded when it failed), and links to what was built.
  Open it in a Markdown viewer, such as VS Code's preview.
- **`<project>_report.md`** is the report of the build backend, when pip or uv ran it
  for that project.

On a terminal, cxbuild shows a progress bar for the running step (a counted one for
Ninja and Make builds) and one for the whole command.

## Environment variables

| Variable | Effect |
| --- | --- |
| `CXBUILD_INSTALLER` | `uv` or `pip`: force the installer `develop` uses |
| `CXBUILD_VERBOSE` | `1`: stream build output, like `--verbose`; also reaches the backend inside pip or uv |
| `CXBUILD_LOG_UDP` | `1` (localhost:5005) or `host:port`: also send every log record as a UDP datagram, to watch a build pip is hiding |

## Limitations

- Wheels only: `build_sdist` refuses.
- The backend packages what cxbuild built. A standalone `pip wheel` of a project
  refuses and says to use `cxbuild build`.
- `dynamic` fields in `[project]` aren't supported, and `license` must be an SPDX
  expression.

## License

MIT