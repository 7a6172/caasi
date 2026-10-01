"""`caasi doctor` — environment diagnostics.

`--details <section>` adds the §19 explanation block (**Problem → Cause →
Evidence → Impact → Suggested action**) for every `fail`/`warn` in that section.
No schema churn: `Evidence` is `CheckResult.detail` and `Suggested action` is
`CheckResult.hint`, the rest comes from i18n.
"""

from __future__ import annotations

from collections import Counter

import typer
from rich.text import Text

from ..checks import SECTION_KEYS, CheckResult, run_checks
from ..i18n import _
from ..utils import output

EXPLAINED_STATUSES = ("fail", "warn")

# §19 block order; each name is both a `doctor.explain.label.*` key and an
# `explanation()` field.
_EXPLAIN_FIELDS = ("problem", "cause", "evidence", "impact", "action")


def explanation(result: CheckResult) -> dict[str, str]:
    """The §19 block for one check, as plain strings (used by both renderers)."""
    status = result.status if result.status in EXPLAINED_STATUSES else "warn"
    return {
        "problem": _(f"doctor.explain.problem.{status}", name=result.name),
        "cause": _(f"doctor.explain.cause.{status}"),
        "evidence": result.detail or _("doctor.explain.no_evidence"),
        "impact": _(f"doctor.explain.impact.{result.section}"),
        "action": result.hint or _("doctor.explain.no_action", section=result.section),
    }


def explained(results: list[CheckResult]) -> list[CheckResult]:
    """The checks worth explaining (`fail`/`warn`), in probe order."""
    return [r for r in results if r.status in EXPLAINED_STATUSES]


def _render_details(results: list[CheckResult], section: str) -> None:
    console = output.console()
    title = _(f"doctor.section.{section}")
    console.print()
    console.print(Text(_("doctor.details.title", section=title), style="bold"))

    problems = explained(results)
    if not problems:
        console.print(Text(_("doctor.details.none", section=title), style="green"))
        return

    for result in problems:
        symbol, style = output.status_symbol(result.status)
        console.print()
        console.print(Text.assemble((f"{symbol} ", style), (result.name, f"bold {style}")))
        block = explanation(result)
        for field in _EXPLAIN_FIELDS:
            label = _(f"doctor.explain.label.{field}")
            console.print(Text.assemble((f"  {label:<16} ", "dim"), (block[field], style)))


def _render_report(results: list[CheckResult], verbose: bool) -> None:
    console = output.console()
    console.print(Text(_("doctor.title"), style="bold"))

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
    details: str | None = typer.Option(
        None, "--details", metavar="SECTION", help=_("doctor.flag.details")
    ),
    verbose: bool = typer.Option(False, "--verbose", help=_("doctor.flag.verbose")),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=_("doctor.flag.quiet")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    for value in (component, details):
        if value is not None and value not in SECTION_KEYS:
            output.fail(
                _("doctor.unknown_component").format(
                    component=value, valid=", ".join(SECTION_KEYS)
                )
            )

    # --details names the section too; it wins when both are given.
    section = details or component
    results = run_checks([section] if section else None)
    exit_code = 1 if any(r.status == "fail" for r in results) else 0

    if quiet:
        raise typer.Exit(exit_code)

    if output.wants_json(json_output):
        counts = Counter(r.status for r in results)
        payload: dict[str, object] = {
            "checks": [r.to_dict() for r in results],
            "summary": dict(counts),
            "exit_code": exit_code,
        }
        if details is not None:
            payload["explanations"] = [
                {"section": r.section, "name": r.name, "status": r.status, **explanation(r)}
                for r in explained(results)
            ]
        output.echo_json(payload)
        raise typer.Exit(exit_code)

    _render_report(results, verbose)
    if details is not None:
        _render_details(results, details)
    raise typer.Exit(exit_code)
