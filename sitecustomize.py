"""Trade Brain process-wide UTF-8 safety for local Python runtimes.

Python imports ``sitecustomize`` automatically when it is available on ``sys.path``.
Trade Brain is installed editable on Windows, so this provides a second line of defense
behind the BAT launchers for direct script/module runs as well. It never changes model
text; it only ensures stdout/stderr can emit Unicode without falling back to a Windows
``charmap`` codec.
"""

from __future__ import annotations

import sys


def _configure_stream(stream) -> None:
    if stream is None or not hasattr(stream, "reconfigure"):
        return
    try:
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, OSError, ValueError):
        # Some embedded/test streams intentionally do not allow reconfiguration.
        pass


_configure_stream(sys.stdout)
_configure_stream(sys.stderr)
