"""Doctor section ``physics``: PhysX / Newton / Warp / MuJoCo / Gazebo.

Every probe is a catalog capability in the ``physics`` domain (``plan3.md``
§27-29 surface), so an upstream rename is a config edit. Pure adapter —
nothing to add.
"""

from __future__ import annotations

from ..core import adapters
from . import CheckResult, register

SECTION = "physics"


@register(SECTION)
def check_physics(ctx) -> list[CheckResult]:
    return adapters.adapter_for("physics").check(ctx.config)
