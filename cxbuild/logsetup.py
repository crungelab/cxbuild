"""Logging setup for cxbuild's entry points: the PEP 517 hooks and the CLI.

Call configure_logging() once, at the top of an entry point. Library code only
does `from loguru import logger` and never adds or removes sinks.

Set CXBUILD_LOG_UDP=1 (localhost:5005) or CXBUILD_LOG_UDP=host:port to also
send every record as a UDP datagram. Hooks run by pip inherit the variable, so
this is a way to watch a backend live when pip hides its output.
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

from loguru import logger

from .runner import DEFAULT_NAME, STATE_DIR

FILE_FORMAT = "{time:HH:mm:ss.SSS} | {level: <8} | {extra[step]: <10} | {message}"
UDP_DEFAULT = ("localhost", 5005)


def configure_logging(root: Path, *, name: str = DEFAULT_NAME, file: bool = True) -> Path | None:
    """WARNING+ to stderr, and, if `file`, everything to <root>/_cxbuild/<name>.log (overwritten).

    Pass file=False from entry points that should leave the log alone, such as
    the light PEP 517 hooks (requirements, metadata), which run before the build hook.
    """
    handlers: list[dict] = [{"sink": sys.stderr, "level": "WARNING"}]
    path = None
    if file:
        path = Path(root).resolve() / STATE_DIR / f"{name}.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append({"sink": path, "level": "DEBUG", "mode": "w", "encoding": "utf-8", "format": FILE_FORMAT})
    if spec := os.environ.get("CXBUILD_LOG_UDP"):
        handlers.append({"sink": _udp_sink(spec), "level": "DEBUG", "format": FILE_FORMAT})
    logger.configure(handlers=handlers, extra={"step": name})  # runner.run() rebinds step per command
    return path


def _udp_sink(spec: str):
    host, port = UDP_DEFAULT
    if spec.lower() not in {"1", "true", "yes", "on"}:
        host, _, port_text = spec.rpartition(":")
        host, port = host or UDP_DEFAULT[0], int(port_text)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def sink(message) -> None:
        try:
            sock.sendto(str(message).encode("utf-8"), (host, port))
        except OSError:
            pass  # nobody listening, or the record is too big for one datagram

    return sink
