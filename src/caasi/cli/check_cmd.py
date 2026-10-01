"""Root `caasi check` — the Check Contract's single front door (§4.5, §5.3).

``caasi check``             every relevant scope (project-aware)
``caasi check project``     environment + project requirements
``caasi check run <id>``    pre-flight a stored run

Exit codes: 3 when any report is incompatible, else 0. The specialist
commands (``sim check``, ``container check``, ``control check``) reuse
:func:`render_report` and :func:`exit_code` so every entry point shares one
semantic operation. There is deliberately no ``check sim`` alias.
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.table import Table

from .. import state
from ..core import project as projects
from ..core import runs
from ..core.check import CheckContext, CheckEngine, CheckReport, worst
from ..i18n import _
from ..utils import output

EXIT_INCOMPATIBLE = 3

_LADDER_STYLE: dict[str, tuple[str, str]] = {
    "compatible": ("check.ladder.compatible", "green"),
    "untested": ("check.ladder.untested", "yellow"),
    "missing": ("check.ladder.missing", "red"),
    "incompatible": ("check.ladder.incompatible", "red"),
}

_RESULT_STYLE: dict[str, str] = {"ready": "green", "warning": "yellow", "incompatible": "red"}


def exit_code(result: str) -> int:
    return EXIT_INCOMPATIBLE if result == "incompatible" else 0


def _result_label(result: str) -> str:
    style = _RESULT_STYLE.get(result, "yellow")
    return f"[{style}]{_(f'check.result.{result}')}[/{style}]"


def render_report(report: CheckReport) -> None:
    """One scope as a ladder table plus its Result line (shared rendering)."""
    table = Table(
        title=_(f"check.scope.{report.scope}"),
        header_style="bold",
        **output.table_styles(),
    )
    table.add_column(_("check.col.item"))
    table.add_column(_("check.col.required"))
    table.add_column(_("check.col.detected"))
    table.add_column(_("check.col.status"))
    table.add_column(_("check.col.note"))
    for item in report.items:
        if item.verified:
            label, style = _("check.ladder.verified"), "bright_green"
        else:
            key, style = _LADDER_STYLE.get(item.compatibility, ("check.ladder.untested", "yellow"))
            label = _(key)
        table.add_row(
            item.name,
            item.required or "—",
            item.detected or "—",
            f"[{style}]{label}[/{style}]",
            item.note,
        )
    output.echo(table)
    output.echo(_("check.result.line", result=_result_label(report.result)))


def check_command(
    scope: Optional[str] = typer.Argument(None, help=_("check.arg.scope")),
    query: Optional[str] = typer.Argument(None, help=_("check.arg.query")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    cfg = state.cfg()
    engine = CheckEngine()
    strict = bool(cfg.get("check.strict", False))

    if scope == "run":
        record = runs.find_run(cfg, query or "latest")
        if record is None:
            output.fail(_("check.run.not_found", query=query or "latest"))
            raise typer.Exit(1)  # unreachable
        ctx = CheckContext(config=cfg, run=record, strict=strict)
        reports = engine.orchestrate(ctx, scopes=["run"])
        label = "run"
    elif scope in (None, "project"):
        root = projects.find_project_root()
        if root is None:
            output.fail(_("check.no_project"))
            raise typer.Exit(1)  # unreachable
        ctx = CheckContext(config=cfg, project_root=root, strict=strict)
        reports = engine.orchestrate(
            ctx, scopes=None if scope is None else ["environment", "project"]
        )
        label = "project"
    else:
        output.fail(_("check.unknown_scope", scope=scope, valid="project, run"))
        raise typer.Exit(1)  # unreachable

    overall = worst(reports) if reports else "ready"

    if output.wants_json(json_output):
        output.echo_json(
            {
                "scope": label,
                "result": overall,
                "missing": list(dict.fromkeys(name for r in reports for name in r.missing)),
                "warnings": list(dict.fromkeys(name for r in reports for name in r.warnings)),
                "reports": [report.to_dict() for report in reports],
            }
        )
        raise typer.Exit(exit_code(overall))

    output.echo(f"[bold]{_('check.title')}[/bold]")
    for report in reports:
        render_report(report)
    if len(reports) > 1:
        output.echo(_("check.result.line", result=_result_label(overall)))
    raise typer.Exit(exit_code(overall))
