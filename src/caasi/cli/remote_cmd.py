"""`caasi remote` — run experiments on remote GPU machines over SSH.

caasi only orchestrates the system ``ssh`` client; interactive sessions are
handed over with execvp, batch commands run as tracked local runs.
"""

from __future__ import annotations

import os
import shlex
from typing import Optional

import typer

from .. import state
from ..core import remotes as remotes_core
from ..core import runs
from ..i18n import _
from ..utils import output, shell

app = typer.Typer(no_args_is_help=True)

_EXTRA_SETTINGS = {"allow_extra_args": True, "ignore_unknown_options": True}


def _require_remote(query: str) -> remotes_core.RemoteMachine:
    machine = remotes_core.find_remote(state.cfg(), query)
    if machine is None:
        valid = ", ".join(m.name for m in remotes_core.list_remotes(state.cfg())) or "-"
        output.fail(_("remote.not_found", query=query, valid=valid))
        raise typer.Exit(1)  # unreachable
    return machine


@app.command("list", help=_("remote.list_help"))
def remote_list(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    machines = remotes_core.list_remotes(state.cfg())
    if output.wants_json(json_output):
        output.echo_json([m.to_dict() for m in machines])
        return
    if not machines:
        output.echo(f"[yellow]{_('remote.none')}[/yellow]")
        return
    output.echo(f"[bold]{_('remote.title')}[/bold]")
    for machine in machines:
        target = remotes_core.ssh_target(machine)
        port = f":{machine.port}" if machine.port else ""
        path = f"  [dim]{machine.path}[/dim]" if machine.path else ""
        output.echo(f"  {machine.name:<16} {target}{port}{path}")


@app.command("connect", help=_("remote.connect_help"))
def remote_connect(
    name: str = typer.Argument(..., help=_("remote.arg.name")),
    command: Optional[str] = typer.Option(None, "--command", "-c", help=_("remote.flag.command")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("remote.flag.dry_run")),
) -> None:
    machine = _require_remote(name)
    args = remotes_core.ssh_prefix(machine)
    if command:
        args.append(command)

    if dry_run:
        output.echo(f"[bold]{_('replay.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(args)}")
        return

    if command:
        result = shell.run_cmd(args, timeout=None)
        if result.stdout:
            output.echo(result.stdout.rstrip(), markup=False)
        if result.stderr:
            output.echo(result.stderr.rstrip(), markup=False)
        raise typer.Exit(result.returncode if result.returncode >= 0 else 1)

    # Interactive session: hand the terminal over to ssh.
    output.echo(_("remote.connected", target=remotes_core.ssh_target(machine)))
    os.execvp("ssh", args)  # pragma: no cover


@app.command("run", help=_("remote.run_help"), context_settings=_EXTRA_SETTINGS)
def remote_run(
    ctx: typer.Context,
    name: str = typer.Argument(..., help=_("remote.arg.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("remote.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    machine = _require_remote(name)
    if not ctx.args:
        output.fail(_("remote.no_command"))
        return
    remote_command = shlex.join(str(a) for a in ctx.args)
    payload_command = (
        f"cd {machine.path} && {remote_command}" if machine.path else remote_command
    )
    command = [*remotes_core.ssh_prefix(machine), payload_command]

    if dry_run:
        output.echo(f"[bold]{_('replay.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(command)}")
        return

    run_name = f"{machine.name}-{ctx.args[0]}"
    record = runs.start_run(
        state.cfg(), name=run_name, command=command, backend="ssh", kind="remote",
        extra={"remote": machine.name, "remote_command": remote_command},
    )
    if output.wants_json(json_output):
        output.echo_json(record.to_dict())
        return
    output.echo(f"[green]{_('remote.started', id=record.run_id)}[/green]")
    output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")
