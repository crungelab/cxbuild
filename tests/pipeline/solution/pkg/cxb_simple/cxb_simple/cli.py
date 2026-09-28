"""Target of the fixture's console script."""

from .util import double


def main() -> None:
    print(double(21))
