"""`caasi doctor` — environment diagnostics."""

from __future__ import annotations

from collections import Counter

import typer
from rich.text import Text

from ..checks import SECTION_KEYS, CheckResult, run_checks
from ..i18n import _
from ..utils import output


def _render_report(results: list[CheckResult], verbose: bool) -> None:
    console = output.console()
    console.print(Text(_("doctor.title"), style="bold"))
    console.print(Text("─" * 34, style="dim"))

    current_section: str | None = None
    for result in results:
        if result.section != current_section:
            current_section = result.section
            console.print()
            console.print(Text(_(f"doctor.section.{result.section}"), style="bold cyan"))

        symbol, style = output.status_symbol(result.status)
        line = Text.assemble(
            (f"  {symbol} ", style),
            (result.name, style),
        )
        if result.detail:
            detail = result.detail
            if not verbose and result.status == "ok" and len(detail) > 64:
                detail = detail[:64] + "…"
            line.append(f" — {detail}", style="dim" if result.status in ("ok", "skip") else style)
        console.print(line)
        if result.hint and (verbose or result.status in ("fail", "warn")):
            console.print(Text(f"      ↳ {result.hint}", style="dim italic"))

    counts = Counter(r.status for r in results)
    console.print()
    if counts.get("fail"):
        console.print(
            Text(
                _("doctor.summary_issues").format(
                    fails=counts["fail"], warns=counts.get("warn", 0)
                ),
                style="bold red",
            )
        )
    elif counts.get("warn"):
        console.print(
            Text(
                _("doctor.summary_warnings").format(warns=counts["warn"]), style="bold yellow"
            )
        )
    else:
        console.print(Text(_("doctor.summary_ready"), style="bold green"))


def doctor_command(
    component: str | None = typer.Option(
        None, "--component", "-c", help=_("doctor.flag.component")
    ),
    verbose: bool = typer.Option(False, "--verbose", help=_("doctor.flag.verbose")),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=_("doctor.flag.quiet")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    sections = None
    if component is not None:
        if component not in SECTION_KEYS:
            output.fail(
                _("doctor.unknown_component").format(
                    component=component, valid=", ".join(SECTION_KEYS)
                )
            )
        sections = [component]

    results = run_checks(sections)
    exit_code = 1 if any(r.status == "fail" for r in results) else 0

    if quiet:
        raise typer.Exit(exit_code)

    if output.wants_json(json_output):
        counts = Counter(r.status for r in results)
        output.echo_json(
            {
                "checks": [r.to_dict() for r in results],
                "summary": dict(counts),
                "exit_code": exit_code,
            }
        )
        raise typer.Exit(exit_code)

    _render_report(results, verbose)
    raise typer.Exit(exit_code)
