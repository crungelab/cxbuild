# cxbuild backend without setuptools — design note

Sep 28, 2026 · @Kurtis Fields

## Context and goal

cxbuild will write wheels itself, with no setuptools anywhere in the build path, the way scikit-build-core does. By the time the backend runs, cmake has already built and installed every extension into `_cxbuild/artifacts`. What remains is packaging: zip the Python package and the compiled module together with metadata from `[project]`.

Today that last step goes through setuptools, and most of the machinery exists only to drive it:

- `Project.build_wheel` sets `sys.argv = ["setup.py", "bdist_wheel"]` and calls `setuptools.setup()` in-process, which is also the source of the `setup.py install is deprecated` warning.
- `ExtensionBuilder` (a `build_ext` subclass) and `CMakeExtension` exist so setuptools will copy prebuilt artifacts into its build tree.
- The wheel is then found by scanning `dist/` for the newest `*.whl` and copied to pip's output directory.
- `build_sdist`, `prepare_metadata_*` and `get_requires_*` all delegate to `setuptools.build_meta`.

**Acceptance bar:** the 14 pipeline tests that pass today. `test_develop.py` covers the CLI, the backend reports and the failure paths. `test_wheel_contents.py` pins what an installed wheel must contain: every package file plus exactly one extension, nothing else from the source tree, a `cpXY-cpXY-<platform>` tag, a working console script, and metadata matching every `[project]` field. The rewrite is done when those pass without setuptools installed.

## Decision 1: package discovery

**Recommendation:** by default, package the directory named by the extension's install prefix, with an optional explicit list in `[tool.cxbuild]` for anything else.

cxbuild already derives the install prefix from the extension name: `cxb_simple._core` gives `cxb_simple`, and a namespaced `crunge.imgui._imgui` gives `crunge/imgui`. That directory is where cmake installs the module and where the Python sources live, so it is the natural default. No new configuration is needed for any current project.

```toml
[tool.cxbuild.wheel]
packages = ["cxb_simple", "cxb_simple_extras"]   # optional; default = the install prefix
exclude = ["**/tests/**"]                        # optional glob patterns
```

Rules for what goes in:

- Every file under each package directory, minus `__pycache__`, `*.pyc` and the exclude patterns. Package data (`.pyi`, `py.typed`, shaders, JSON) comes along without a separate setting.
- The compiled module is taken from `_cxbuild/artifacts/<prefix>/`, never from the source tree, even when an older copy sits there from an editable install.
- Namespace packages work without special cases: packaging `crunge/imgui` writes files under `crunge/imgui/` and never adds a `crunge/__init__.py`, so projects sharing the `crunge` namespace don't collide.

`[tool.setuptools] packages` stops being read. Its projects keep working through the default, and the fixture's copy of it can be deleted once the tests pass without it.

## Decision 2: editable installs

**Recommendation:** a real editable install. The editable wheel holds metadata and a `.pth` file pointing at the project directory; `develop` keeps copying the built module into the source tree, as it does today.

Today `build_editable` returns an ordinary wheel, so the installed package is a copy. Edits to `.py` files only take effect after another `cxbuild develop`, and the module copied into the source tree is used only if you happen to run from there.

| Approach | Python edits | Module after rebuild | Cost |
| --- | --- | --- | --- |
| Copy (today) | Need a reinstall | Reinstall | None to build, but slow to iterate |
| `.pth` to the project dir | Live | Live once `develop` copies it | Whole project dir on `sys.path` |
| Import hook (setuptools style) | Live | Live | A finder module in site-packages, much more code |

The `.pth` approach wins on simplicity. Its cost is that anything else at the project's top level becomes importable, which is harmless for a development install. It also suits namespace packages: several crunge projects each add their own directory, and PEP 420 merges `crunge` across them.

What the editable wheel contains: `dist-info` (METADATA, WHEEL, RECORD, `entry_points.txt`) plus `_cxbuild_<name>.pth` with one line, the absolute project path. No package files. Console scripts still work, because pip generates them from the entry points.

**Test change:** `test_wheel_contents.py` checks installed files. For `develop` it will need an editable variant: the `.pth` is present, the modules resolve to the project directory, and an edit to `util.py` shows up without reinstalling. The current file checks move to a `cxbuild build` wheel instead (Decision 3).

## Decision 3: standalone builds

**Recommendation:** not in the first version. The PEP 517 backend keeps requiring a cxbuild activity, and `cxbuild build` writes wheels itself, in-process, instead of going through `python -m build`.

A crunge project cannot be built on its own. Its `CMakeLists.txt` relies on the solution root for `find_package(Python)`, the vendored dependencies and the shared build tree. Standalone `pip wheel pkg/imgui` would therefore have to configure the whole solution and build just one target: real work, for a path nobody uses yet.

What changes instead:

- **`cxbuild build`** runs cmake once for the solution (as now), then calls the wheel writer for each project and puts the wheels in `<solution>/dist/`. No pip, no `python -m build`, no subprocess per project. That also retires `BuildTool`, which fixes the command that has been broken.
- **`cxbuild develop`** still installs through pip, because pip owns installation, uninstallation and the RECORD bookkeeping. pip calls `build_editable`, which calls the same writer in editable mode.
- **Standalone `pip wheel`** keeps failing with the clear `CxBuildError` added in `activity.py`, which names `cxbuild build` as the way to get a wheel.

**Publishing is cxwheel's job, not cxbuild's.** cxbuild stops at honest wheels in `<solution>/dist/`: a Linux build is tagged `linux_x86_64`, never `manylinux`, which PyPI rejects as intended. A separate tool, cxwheel, takes over from there. It repairs each wheel (auditwheel on Linux, delocate on macOS, delvewheel on Windows), which bundles shared libraries such as SDL and earns the `manylinux` tag, then verifies and uploads. The honest tag is the contract between the two tools: cxwheel can tell what needs repair from the filename alone. Keeping repair tools and upload credentials out of the build keeps cxbuild fast, and safe to run inside pip.

Standalone builds become worth doing if you want sdists on PyPI that users can build themselves. Revisit then.

## Decision 4: the other PEP 517 hooks

**Recommendation:** implement only what PEP 517 requires plus what the metadata writer gives for free. `build_sdist` refuses clearly until standalone builds exist.

| Hook | Today | Proposed |
| --- | --- | --- |
| `build_wheel` | setuptools `setup()` via `sys.argv` | The wheel writer |
| `build_editable` | setuptools, or `build_wheel` under cxbuild | The wheel writer, editable mode |
| `get_requires_for_build_*` | setuptools' list (setuptools, wheel) | `[]`: nothing beyond cxbuild itself |
| `prepare_metadata_for_build_*` | setuptools | Write `dist-info/METADATA` with the same writer; no cmake needed |
| `build_sdist` | setuptools | Raise `CxBuildError`: sdists need standalone builds (Decision 3) |

The `prepare_metadata` hooks are optional in PEP 517. They are worth keeping because they cost nothing once the metadata writer exists, and they let pip read dependencies without a full build.

`build_sdist` is required by PEP 517 but may fail. No sdists are planned, so the hook raises a \`CxBuildError\` saying cxbuild publishes wheels only. That beats shipping an sdist that can't be built, which would give users a confusing cmake failure.

## Decision 5: metadata and wheel writing

**Recommendation:** cxbuild writes the wheel and its metadata itself, and uses `packaging` only to parse and validate: requirement strings, versions, name normalization and tags. `packaging` is small, stable, and already installed wherever pip is. The writer should come to roughly 200 to 300 lines.

A wheel is a zip with this layout, for `cxb_simple` 0.0.1 on CPython 3.12 Linux:

| Path in the wheel | Contents | Written by |
| --- | --- | --- |
| `cxb_simple/*.py`, data files | The package directory (Decision 1) | Copied |
| `cxb_simple/_core.cpython-312-x86_64-linux-gnu.so` | The module from `_cxbuild/artifacts` | Copied |
| `cxb_simple-0.0.1.dist-info/METADATA` | Core metadata 2.4, from `[project]` | Metadata writer |
| `…dist-info/WHEEL` | `Wheel-Version: 1.0`, `Generator: cxbuild`, `Root-Is-Purelib: false`, `Tag: cp312-cp312-linux_x86_64` | Wheel writer |
| `…dist-info/entry_points.txt` | `[project.scripts]`, `gui-scripts`, `entry-points` | Metadata writer |
| `…dist-info/licenses/…` | Files from `license-files` | Copied |
| `…dist-info/RECORD` | One line per file: path, `sha256=` urlsafe base64 without padding, size; its own line has empty hash and size | Wheel writer, last |

**Field mapping.** `name`, `version`, `description` (Summary), `requires-python`, `dependencies` (Requires-Dist), `optional-dependencies` (Provides-Extra, plus Requires-Dist with an `extra ==` marker), `authors` and `maintainers` (Author/Author-email), `keywords` (comma-joined), `classifiers`, `urls` (Project-URL `Label, url`), `license` as an SPDX expression (License-Expression), and `readme` as the message body, with Description-Content-Type taken from the file suffix. `dynamic` fields are rejected with a clear error in the first version.

**Getting the tag right.** Interpreter and ABI come from `packaging.tags`, which knows about free-threaded builds (`cp313t`). The platform comes from `sysconfig.get_platform()`, normalized (`linux_x86_64`, `win_amd64`, `macosx_11_0_arm64`). The rule is the first entry of `packaging.tags.sys_tags()` whose platform matches that value. Taking the plain first entry would stamp an unrepaired Linux wheel `manylinux`, which is a false claim of compatibility.

**Details that bite.**

- The dist-info directory name is the escaped name: runs of `-_.` become `_`, lowercased, so `cxb-simple` becomes `cxb_simple-0.0.1.dist-info`.
- The dist-info entries go last in the zip, with RECORD last of all.
- Keep the executable bit in the zip's external attributes.
- Use fixed timestamps (1980-01-01, or `SOURCE_DATE_EPOCH` when set) so rebuilding the same tree gives an identical wheel.

If metadata edge cases pile up (license tables, dynamic fields, readme tables), `pyproject-metadata`, which scikit-build-core uses, can replace the metadata writer without touching the wheel writer.

## Module layout and what gets deleted

Two new modules replace five pieces of setuptools plumbing, and cxbuild's dependencies lose `setuptools` and `build` and gain `packaging`.

| Module | Role |
| --- | --- |
| `metadata.py` (new) | Reads `[project]`, validates with `packaging`, produces METADATA and `entry_points.txt` text. Pure functions, no file system beyond the readme and license files. |
| `wheel.py` (new) | `WheelBuilder`: collects files (Decision 1), computes the tag, writes the zip and RECORD. `editable=True` writes metadata plus the `.pth` instead of package files. |
| `project.py` | `build_wheel(out_dir, editable)` runs `WheelBuilder` inside `runner.capture("wheel", …)`, so the report shows a `wheel` step. `build()` calls it too, for `cxbuild build`. |
| `backend.py` | Each hook calls `Project`; no `setuptools.build_meta` import anywhere. |
| `solution.py` | `build()` writes every project's wheel to `<solution>/dist/`. |

Deleted:

- `extension_builder.py` and `cmake_extension.py`. The artifact copy moves into `WheelBuilder`, and the editable copy into the source tree moves into `Project.develop`.
- `build_tool.py`, since `cxbuild build` no longer shells out to `python -m build`.
- `Project.build_wheel`'s current body: the `sys.argv` hack, `setuptools.setup()`, the `dist/` scan and the copy.
- `[tool.setuptools]` from the fixture projects, once nothing reads it.

## Test plan and order of work

Build from the inside out: the pure pieces first, with fast unit tests, then swap them in behind the pipeline tests one command at a time. Every step leaves all tests green.

1. **`metadata.py`**, with `tests/unit/test_metadata.py`. Feed it the fixture's `pyproject.toml` and check METADATA field by field, including the tricky ones: extras markers, keyword joining, URL labels, the readme body. No cmake needed, so these run in milliseconds.
2. **`wheel.py`**, with `tests/unit/test_wheel.py`. Build from a fake artifacts directory into `tmp_path`, then open the zip and check the layout, the tag, that dist-info comes last, and that every RECORD hash matches the file's bytes.
3. **`cxbuild build`** on the new writer, with a new `tests/pipeline/test_build.py`. `build` produces one wheel per project in `dist/`, pip installs them, and the checks in `test_wheel_contents.py` run against that install. This fixes the broken command before anything else changes.
4. **`develop`** switched to editable mode. `test_wheel_contents.py` gains the editable variant from Decision 2: the `.pth` is installed, modules import from the project, and an edit to `util.py` is live without reinstalling.
5. **Remove setuptools.** Delete the old modules, drop `setuptools` and `build` from cxbuild's dependencies, add `packaging`, and recreate the tests environment. Python 3.12 virtualenvs don't come with setuptools, so a green run in that environment proves the claim. A one-line unit test asserting `importlib.util.find_spec("setuptools") is None` keeps it that way.

Steps 1 and 2 can be reviewed and committed before any existing behaviour changes. Step 3 is the first user-visible change.

## Settled questions

Kurt's answers confirm the first version as designed; one of them adds a fixture change.

| Question | Answer | Effect on the design |
| --- | --- | --- |
| `dynamic` fields in crunge? | None | Rejecting `dynamic` with a clear error is enough |
| More than one extension per project, or one outside its package? | Never | Decision 1's default covers every project |
| Platforms | All, eventually | The tag logic is cross-platform now; repair and upload belong to cxwheel, a separate tool |
| Does anything rely on the module in the source tree? | Yes: editable installs | The copy stays in `develop`; with `.pth` editables it is required, since Python imports from the source tree |
| sdists | Probably never | `build_sdist` refuses (Decision 4); standalone builds stay deferred |
| `license` and `readme` | Commented out in crunge after earlier problems | Supported by the new writer; see below |

**License and readme.** Those problems were most likely setuptools-version issues: an SPDX `license` string needs setuptools 77 or newer, and older versions expected a table. The new writer supports `readme` (already covered by the fixture) and an SPDX `license` string with `license-files`. Step 1 of the test plan adds `license = "MIT"` and a `LICENSE` file to `cxb_simple`, so both are pinned before crunge turns them back on.
