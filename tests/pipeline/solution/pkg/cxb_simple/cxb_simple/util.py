"""A pure-Python module next to the extension: the wheel must carry both."""

from ._core import add


def double(x: int) -> int:
    return add(x, x)
