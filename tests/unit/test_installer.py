"""cxbuild.pip_tool: choosing uv or pip for editable installs.

uv environments (including hatch's with installer = "uv") have no pip, so uv is
preferred whenever it can be found; pip is the fallback; either can be forced.
"""

from __future__ import annotations

import sys

import pytest

from cxbuild import pip_tool
from cxbuild.pip_tool import PipConfigError, installer
from cxbuild.runner import CxBuildError


@pytest.fixture
def uv_available(monkeypatch):
    monkeypatch.setattr(pip_tool, "find_uv", lambda: "/opt/bin/uv")


@pytest.fixture
def no_uv(monkeypatch):
    monkeypatch.setattr(pip_tool, "find_uv", lambda: None)


@pytest.fixture
def pip_available(monkeypatch):
    real = pip_tool.importlib.util.find_spec
    monkeypatch.setattr(pip_tool.importlib.util, "find_spec", lambda name: object() if name == "pip" else real(name))


@pytest.fixture
def no_pip(monkeypatch):
    real = pip_tool.importlib.util.find_spec
    monkeypatch.setattr(pip_tool.importlib.util, "find_spec", lambda name: None if name == "pip" else real(name))


def test_uv_is_preferred_and_targets_this_interpreter(uv_available):
    assert installer({}) == ("uv", ["/opt/bin/uv", "pip", "install", "--python", sys.executable])


def test_pip_is_the_fallback(no_uv, pip_available):
    assert installer({}) == ("pip", [sys.executable, "-m", "pip", "install"])


def test_pip_can_be_forced(uv_available, pip_available):
    assert installer({"CXBUILD_INSTALLER": "pip"})[0] == "pip"


def test_uv_can_be_forced(uv_available):
    assert installer({"CXBUILD_INSTALLER": " UV "})[0] == "uv"


def test_forcing_uv_without_uv_is_an_error(no_uv):
    with pytest.raises(PipConfigError, match="CXBUILD_INSTALLER=uv, but uv is neither"):
        installer({"CXBUILD_INSTALLER": "uv"})


def test_neither_installer_is_an_error(no_uv, no_pip):
    with pytest.raises(PipConfigError, match="no installer .* has no pip"):
        installer({})


def test_unknown_installer_is_an_error():
    with pytest.raises(PipConfigError, match="use one of uv, pip"):
        installer({"CXBUILD_INSTALLER": "poetry"})


def test_installer_errors_are_cxbuild_errors():
    assert issubclass(PipConfigError, CxBuildError)
