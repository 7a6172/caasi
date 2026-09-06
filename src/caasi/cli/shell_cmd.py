"""`caasi shell` — open a shell inside the Isaac/ROS environment.

Sets ISAACSIM_PATH / ISAACLAB_PATH from the tool registry and prepends the
tools' bin directories to PATH. With ``--command`` a single command is run
inside that environment instead of an interactive shell.
"""

from __future__ import annotations

import os
from typing import Optional

import typer

from .. import state
from ..i18n import _
from ..utils import output, shell


def build_shell_env() -> dict[str, str]:
    cfg = state.cfg()
    env = dict(os.environ)
    for tool, env_var in (("isaacsim", "ISAACSIM_PATH"), ("isaaclab", "ISAACLAB_PATH")):
        resolved = cfg.resolve_tool(tool)
        path = resolved.expanded_path if resolved else None
        if path is None:
            continue
        env[env_var] = str(path)
        bin_dir = path / "bin"
        if bin_dir.is_dir():
            env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    return env


def shell_command(
    command: Optional[str] = typer.Option(None, "--command", "-c", help=_("shell.flag.command")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    env = build_shell_env()
    if command:
        result = shell.run_cmd(["bash", "-c", command], timeout=None, env=env)
        if output.wants_json(json_output):
            output.echo_json(
                {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
            )
            raise typer.Exit(result.returncode if result.returncode >= 0 else 1)
        if result.stdout:
            output.echo(result.stdout.rstrip(), markup=False)
        if result.stderr:
            output.echo(result.stderr.rstrip(), markup=False)
        raise typer.Exit(result.returncode if result.returncode >= 0 else 1)
    # Interactive: replace the CLI process with the shell.
    os.execvpe("bash", ["bash"], env)  # pragma: no cover
