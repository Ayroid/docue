"""Shared output helper for the smoke-test scripts.

These scripts exist so a human can open the result in real Excel -- which means
the previous run's output is usually still open when the next one starts, and
Windows locks it. Failing the whole run on that is misleading: the compile and
the QA already passed. So fall back to a sibling filename and say which one
was written.
"""

from pathlib import Path


def write_artifact(path: Path, data: bytes) -> Path:
    path.parent.mkdir(exist_ok=True)
    try:
        path.write_bytes(data)
        return path
    except PermissionError:
        fallback = path.with_name(f"{path.stem}_new{path.suffix}")
        fallback.write_bytes(data)
        return fallback
