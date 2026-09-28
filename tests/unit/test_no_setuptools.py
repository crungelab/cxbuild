"""cxbuild builds without setuptools.

Two checks: no cxbuild module imports setuptools, even with it blocked; and the
test environment doesn't have it installed, so a green pipeline run proves the
builds work without it rather than merely not calling it.
"""

from __future__ import annotations

import importlib.util
import pkgutil
import subprocess
import sys

import cxbuild

MODULES = sorted(f"cxbuild.{m.name}" for m in pkgutil.iter_modules(cxbuild.__path__))


def test_every_module_imports_with_setuptools_blocked():
    # None in sys.modules makes `import setuptools` raise ImportError, installed or not.
    code = (
        "import sys, importlib\n"
        "sys.modules['setuptools'] = None\n"
        f"for name in {MODULES!r}:\n"
        "    importlib.import_module(name)\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "cxbuild.backend" in MODULES and "cxbuild.wheel" in MODULES


def test_the_test_environment_has_no_setuptools():
    # If this fails, something in the environment pulls setuptools in (check
    # `pip show setuptools` for "Required-by"); the pipeline tests would then no
    # longer prove that cxbuild builds without it.
    assert importlib.util.find_spec("setuptools") is None
