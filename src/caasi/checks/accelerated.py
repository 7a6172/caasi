"""Doctor section ``accelerated``: Isaac ROS, NITROS and motion planning.

Every probe is a catalog capability, so an upstream rename is a config edit
(``caasi config set catalog.<domain>.<capability>.packages [...]``) rather than
a code change. Like ``checks/robotics.py``, the whole section degrades to a
single ``skip`` when the ros2 CLI itself is unavailable.
"""

from __future__ import annotations

import os

from ..core import adapters, catalog, nvidia, ros as ros_core
from ..i18n import _
from ..utils import pydist
from . import CheckResult, register

SECTION = "accelerated"

#: Catalog domains whose capabilities make up this section.
DOMAINS = ("isaacros", "nitros", "motion")

#: Distribution names TensorRT is published under.
TENSORRT_DISTS = ("tensorrt", "tensorrt-cu12", "tensorrt-cu11", "tensorrt_cu12")


def _prerequisites() -> list[CheckResult]:
    """NITROS prerequisites: CUDA, TensorRT and the DDS configuration."""
    cuda = nvidia.cuda_version()
    tensorrt = pydist.pip_version(*TENSORRT_DISTS)
    rmw = os.environ.get("RMW_IMPLEMENTATION")
    domain_id = os.environ.get("ROS_DOMAIN_ID")
    return [
        CheckResult(
            SECTION,
            _("doctor.accelerated.cuda"),
            "ok" if cuda else "fail",
            cuda or _("doctor.accelerated.no_cuda"),
            "" if cuda else _("doctor.accelerated.cuda_hint"),
        ),
        CheckResult(
            SECTION,
            _("doctor.accelerated.tensorrt"),
            "ok" if tensorrt else "warn",
            tensorrt or _("doctor.accelerated.no_tensorrt"),
            "" if tensorrt else _("doctor.accelerated.tensorrt_hint"),
        ),
        CheckResult(
            SECTION,
            _("doctor.accelerated.rmw"),
            "ok" if rmw else "skip",
            rmw or _("doctor.accelerated.rmw_default"),
            _("doctor.accelerated.rmw_hint"),
        ),
        CheckResult(
            SECTION,
            _("doctor.accelerated.domain_id"),
            "ok" if domain_id else "skip",
            domain_id or _("doctor.accelerated.domain_id_default"),
        ),
    ]


@register(SECTION)
def check_accelerated(ctx) -> list[CheckResult]:
    if not ros_core.find_ros2_binary():
        return [
            CheckResult(
                SECTION,
                _("doctor.section.accelerated"),
                "skip",
                _("doctor.robotics.no_ros2"),
                _("doctor.robotics.no_ros2_hint"),
            )
        ]

    results: list[CheckResult] = []
    seen: set[str] = set()
    for domain_key in DOMAINS:
        found = adapters.adapter_for(domain_key)
        for item in found.detect(ctx.config):
            # `isaacros` lists the same upstream packages as `nitros`/`motion`.
            probe = catalog.targets(item.capability)
            if probe in seen:
                continue
            seen.add(probe)
            results.append(found.check_capability(item, ctx.config))
    results.extend(_prerequisites())
    return results
