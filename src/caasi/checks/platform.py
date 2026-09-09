"""Doctor section ``platform``: GR00T, Cosmos, NuRec and the teleop stacks.

Probes are catalog capabilities of the ``groot``, ``cosmos``, ``usd`` (NuRec)
and ``teleop`` domains (``plan3.md`` §26, §33-34), so an upstream rename is a
config edit. Teleop rows need the ROS CLI: without it they report ``skip``,
never ``fail`` (plan §6).
"""

from __future__ import annotations

from ..core import adapters, catalog, ros
from ..i18n import _
from . import CheckResult, register

SECTION = "platform"

#: GR00T rows for this section (the scripts appear in `caasi groot status`).
GROOT_CAPS = ("repo", "module")

#: Teleop stacks that belong to the platform section.
TELEOP_CAPS = ("keyboard", "joy")


@register(SECTION)
def check_platform(ctx) -> list[CheckResult]:
    cfg = ctx.config
    results: list[CheckResult] = []

    groot = adapters.adapter_for("groot")
    for key in GROOT_CAPS:
        item = catalog.resolve_capability("groot", key, cfg)
        if item is not None:
            results.append(groot.check_capability(item, cfg))

    cosmos = adapters.adapter_for("cosmos")
    results.extend(cosmos.check(cfg))

    nurec = catalog.resolve_capability("usd", "nurec", cfg)
    if nurec is not None:
        if nurec.found:
            results.append(
                CheckResult(
                    SECTION,
                    _(nurec.capability.label),
                    "ok",
                    nurec.value or "",
                    _("adapters.found_via", how=nurec.how),
                )
            )
        else:
            results.append(
                CheckResult(
                    SECTION,
                    _(nurec.capability.label),
                    "skip",
                    _("adapters.not_found", targets=catalog.targets(nurec.capability)),
                )
            )

    teleop = adapters.adapter_for("teleop")
    ros_available = ros.find_ros2_binary() is not None
    for key in TELEOP_CAPS:
        item = catalog.resolve_capability("teleop", key, cfg)
        if item is None:
            continue
        if not ros_available:
            results.append(
                CheckResult(
                    SECTION,
                    _(item.capability.label),
                    "skip",
                    _("doctor.robotics.no_ros2"),
                    _("doctor.robotics.no_ros2_hint"),
                )
            )
        else:
            results.append(teleop.check_capability(item, cfg))

    return results
