"""Subprocess helpers.

Every external probe in the CLI goes through this module so timeouts and
failure handling stay consistent. The CLI never raises on a failing probe;
callers decide how to report problems.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

DEFAULT_TIMEOUT = 10.0


@dataclass(frozen=True)
class ShellResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def which(name: str) -> str | None:
    """Locate an executable on PATH."""
    return shutil.which(name)


def run_cmd(
    args: list[str],
    timeout: float | None = DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> ShellResult:
    """Run a command capturing stdout/stderr.

    Never raises for non-zero exits. Timeouts and spawn errors are reported
    with returncode -1 and a message in stderr. ``timeout=None`` waits
    indefinitely (used by the `caasi native` / `caasi shell` escape hatches).
    """
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
        return ShellResult(proc.returncode, proc.stdout or "", proc.stderr or "")
    except subprocess.TimeoutExpired:
        return ShellResult(-1, "", f"timed out after {timeout}s")
    except (OSError, ValueError) as exc:
        return ShellResult(-1, "", str(exc))
