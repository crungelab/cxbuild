"""Standalone editable builds: an installer (uv or pip) installs a project editable with no
cxbuild command around it, as a hatch workspace does for its members. cxbuild's backend
then builds the solution itself, under the build lock, stages the module and writes the
editable wheel. Builds run in the environment itself (no build isolation), as with the
workspace setting `[tool.uv] no-build-isolation-package`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import PROJECTS, TIMEOUT, clean_env, installer, run_python

pytestmark = pytest.mark.pipeline

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def install_command(project_dir: Path, distribution: str) -> list[str]:
    name, command = installer("install")
    command = [*command, "--no-build-isolation", "--editable", str(project_dir)]
    if name == "uv":
        command += ["--reinstall-package", distribution]
    return command


def start_install(solution: Path, project: str) -> subprocess.Popen:
    return subprocess.Popen(
        install_command(solution / "pkg" / project, PROJECTS[project]),
        cwd=solution, env=clean_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def finish(proc: subprocess.Popen) -> str:
    output, _ = proc.communicate(timeout=TIMEOUT)
    assert proc.returncode == 0, output
    return output


def test_an_editable_install_builds_the_solution_itself(solution):
    finish(start_install(solution, "second"))

    report = (solution / "_cxbuild" / "second_report.md").read_text()  # beside the CLI's, as usual
    assert report.startswith("# cxbuild build_editable — ✅ passed")
    for label in ("configure", "build", "install", "wheel second"):
        assert f"| {label} |" in report, label
    assert "- **editable wheel second**:" in report
    assert list((solution / "pkg" / "second" / "cxbns" / "second").glob("_core*"))  # staged

    check = run_python("import cxbns.second; print(cxbns.second.greet('ws'))", cwd=solution.parent)
    assert check.returncode == 0, check.stderr
    assert check.stdout.strip() == "hello, ws"


def test_an_install_waits_while_another_build_holds_the_lock(solution):
    from cxbuild.lock import BuildLock

    with BuildLock(solution / "_cxbuild" / "build.lock"):
        proc = start_install(solution, "third")
        time.sleep(3)
        assert proc.poll() is None, "the install should be waiting for the build lock"
    finish(proc)

    report = (solution / "_cxbuild" / "third_report.md").read_text()
    assert "| build lock |" in report  # how long it waited, and for whom, on record


def test_concurrent_installs_share_one_build(solution):
    # What uv does with a workspace: several members built at the same moment.
    procs = [start_install(solution, p) for p in PROJECTS]
    for proc in procs:
        finish(proc)

    check = run_python(
        "import cxb_simple, cxbns.second, cxbns.third; "
        "print(cxb_simple.add(2, 3), cxbns.second.greet('x'), cxbns.third.triple(3))",
        cwd=solution.parent,
    )
    assert check.returncode == 0, check.stderr
    assert check.stdout.strip() == "5 hello, x 9"


def test_a_project_outside_the_solution_is_refused(solution, tmp_path):
    stray = tmp_path / "stray"
    shutil.copytree(solution / "pkg" / "second", stray)
    proc = subprocess.run(
        install_command(stray, "cxbns-second"), cwd=tmp_path, env=clean_env(),
        capture_output=True, text=True, timeout=TIMEOUT,
    )
    assert proc.returncode != 0
    assert "not inside a cxbuild solution" in proc.stdout + proc.stderr


# --- a real hatch workspace -----------------------------------------------------------


def hatch_version() -> tuple[int, ...] | None:
    hatch = shutil.which("hatch")
    if hatch is None:
        return None
    out = subprocess.run([hatch, "--version"], capture_output=True, text=True).stdout
    try:
        return tuple(int(p) for p in out.split()[-1].split(".")[:2])
    except ValueError:
        return None


# cxbuild is a workspace member too, not a `sources` entry: in hatch 1.18.1 a path source
# installs a plain copy even though it is documented as editable by default (the flag is
# lost when hatch rebuilds its dependency list), while members are always installed editable.
WORKSPACE = """
[tool.hatch.envs.default]
python = "{python}"   # the tests' own version: left alone, hatch picks whichever Python it finds first
installer = "uv"
skip-install = true
workspace.members = ["pkg/*", "{cxbuild}"]

[tool.uv]
no-build-isolation-package = [{members}]   # the cxbuild projects build in the environment itself
"""


@pytest.mark.skipif((hatch_version() or (0,)) < (1, 18), reason="needs hatch 1.18+ (workspaces and sources)")
def test_hatch_workspace(solution, tmp_path):
    pyproject = solution / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + WORKSPACE.format(
        cxbuild=REPO_ROOT.as_posix(),
        members=", ".join(f'"{d}"' for d in PROJECTS.values()),
        python=f"{sys.version_info.major}.{sys.version_info.minor}",
    ))
    env = {**clean_env(), "HATCH_DATA_DIR": str(tmp_path / "hatch-data")}  # a throwaway hatch environment
    env.pop("VIRTUAL_ENV", None)

    create = subprocess.run(["hatch", "env", "create"], cwd=solution, env=env,
                            capture_output=True, text=True, timeout=TIMEOUT)
    assert create.returncode == 0, create.stdout + create.stderr

    check = subprocess.run(
        ["hatch", "run", "python", "-c",
         "import cxb_simple, cxbns.second, cxbns.third, cxbuild; "
         "print(cxb_simple.add(2, 3), cxbns.second.greet('ws'), cxbns.third.triple(3)); print(cxbuild.__file__)"],
        cwd=solution, env=env, capture_output=True, text=True, timeout=TIMEOUT,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    first, where = check.stdout.strip().splitlines()[-2:]
    assert first == "5 hello, ws 9"
    assert Path(where).resolve().is_relative_to(REPO_ROOT)  # editable, from the checkout

    for project in PROJECTS:  # each member built standalone, the record in the solution's _cxbuild
        assert (solution / "_cxbuild" / f"{project}_report.md").read_text().startswith(
            "# cxbuild build_editable — ✅ passed")
