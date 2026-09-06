"""Isaac Sim / Isaac Lab detection.

Detection order per tool: configured tool registry -> environment variables
-> common install locations -> pip metadata. Reused by `caasi info`.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

from ..core.config import Config
from ..i18n import _
from ..utils import pydist
from . import CheckResult, register

Detection = tuple[str, str, str]  # (status, detail, hint)


def _glob_first(patterns: list[str]) -> str | None:
    for pattern in patterns:
        matches = sorted(glob.glob(os.path.expanduser(pattern)))
        if matches:
            return matches[-1]
    return None


def detect_isaac_sim(config: Config) -> Detection:
    tool = config.resolve_tool("isaacsim")
    if tool is not None:
        path = tool.expanded_path
        if path is not None and path.exists():
            label = f" {tool.version}" if tool.version else ""
            return "ok", _("doctor.isaac.sim_found").format(version=label, path=str(path)), ""
        return (
            "warn",
            _("doctor.isaac.sim_configured_missing").format(path=tool.path or "?"),
            _("doctor.isaac.config_hint"),
        )

    env_path = os.environ.get("ISAACSIM_PATH")
    if env_path and Path(env_path).expanduser().exists():
        return "ok", _("doctor.isaac.sim_found").format(version="", path=env_path), ""

    common = _glob_first(
        [
            "~/isaacsim",
            "~/.local/share/ov/pkg/isaac-sim-*",
            "~/.local/share/ov/pkg/isaac_sim-*",
            "/opt/isaac-sim*",
            "/opt/isaacsim*",
        ]
    )
    if common:
        return "ok", _("doctor.isaac.sim_found").format(version="", path=common), ""

    version = pydist.pip_version("isaacsim")
    if version:
        return "ok", _("doctor.isaac.sim_pip").format(version=version), ""

    return "fail", _("doctor.isaac.sim_missing"), _("doctor.isaac.sim_hint")


def detect_isaac_lab(config: Config) -> Detection:
    tool = config.resolve_tool("isaaclab")
    if tool is not None:
        path = tool.expanded_path
        if path is not None and path.exists():
            label = f" {tool.version}" if tool.version else ""
            return "ok", _("doctor.isaac.lab_found").format(version=label, path=str(path)), ""
        return (
            "warn",
            _("doctor.isaac.lab_configured_missing").format(path=tool.path or "?"),
            _("doctor.isaac.config_hint"),
        )

    env_path = os.environ.get("ISAACLAB_PATH")
    if env_path and Path(env_path).expanduser().exists():
        return "ok", _("doctor.isaac.lab_found").format(version="", path=env_path), ""

    common = _glob_first(["~/isaaclab", "~/IsaacLab", "~/workspace/isaaclab", "~/workspace/IsaacLab"])
    if common:
        return "ok", _("doctor.isaac.lab_found").format(version="", path=common), ""

    version = pydist.pip_version("isaaclab")
    if version:
        return "ok", _("doctor.isaac.lab_pip").format(version=version), ""

    return "fail", _("doctor.isaac.lab_missing"), _("doctor.isaac.lab_hint")


@register("isaac")
def check_isaac(ctx) -> list[CheckResult]:
    status, detail, hint = detect_isaac_sim(ctx.config)
    results = [CheckResult("isaac", _("doctor.isaac.sim"), status, detail, hint)]
    status, detail, hint = detect_isaac_lab(ctx.config)
    results.append(CheckResult("isaac", _("doctor.isaac.lab"), status, detail, hint))
    return results
