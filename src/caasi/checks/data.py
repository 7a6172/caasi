"""Doctor section ``data``: Replicator, bag storage and dataset CLIs.

Every probe is a catalog capability in the ``data`` domain (``plan3.md``
§30-32 surface: Replicator extension, ``rosbag2_storage_mcap``,
``rosbag2_storage_default_plugins``, ``hf``/``huggingface-cli``, ``ngc``),
so an upstream rename is a config edit. Pure adapter — nothing to add.
"""

from __future__ import annotations

from ..core import adapters
from . import CheckResult, register

SECTION = "data"


@register(SECTION)
def check_data(ctx) -> list[CheckResult]:
    return adapters.adapter_for("data").check(ctx.config)
