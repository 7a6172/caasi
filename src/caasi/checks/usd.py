"""Doctor section ``assets``: the USD / URDF toolchain (``plan3.md`` §39).

Every probe is a catalog capability in the ``usd`` domain, so an upstream
rename is a config edit. The section is pure adapter — nothing asset-specific
to add on top.
"""

from __future__ import annotations

from ..core import adapters
from . import CheckResult, register

SECTION = "assets"


@register(SECTION)
def check_assets(ctx) -> list[CheckResult]:
    return adapters.adapter_for("usd").check(ctx.config)
