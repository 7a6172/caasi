"""Installed Python distribution helpers (metadata only, never imports targets)."""

from __future__ import annotations


def pip_version(*candidates: str) -> str | None:
    """Return the installed version of the first matching distribution.

    Uses importlib.metadata so heavy packages are never imported by the CLI.
    """
    from importlib.metadata import PackageNotFoundError, version

    for name in candidates:
        try:
            return version(name)
        except PackageNotFoundError:
            continue
    return None
