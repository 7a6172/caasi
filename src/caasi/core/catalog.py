"""Capability catalog — every upstream name lives here as *data*.

Caasi is a layer on top of tools it does not own, so nothing about an
Isaac ROS / Nav2 / MoveIt / USD release may be hardcoded in CLI logic.
Package names, binaries, python distributions, environment variables,
filesystem globs, launch files and scripts are all rows in this table, and
every row can be replaced from ``config.yaml`` under the ``catalog:`` key.

An upstream rename is therefore a config edit, not a Caasi release::

    caasi config set catalog.slam.visual.packages "[isaac_ros_visual_slam_v4]"
    caasi config catalog slam

Override rule (deliberately the only one): ``catalog.<domain>.<capability>.<field>``
*replaces* that field wholesale — lists are not appended to. An override may
also add a capability or a whole domain that the built-ins do not know about.

Probing is subprocess / metadata / filesystem only: the CLI never imports the
ecosystem it detects.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields as dataclass_fields, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..utils import pydist, shell
from . import ros

if TYPE_CHECKING:  # pragma: no cover
    from .config import Config

#: Timeout for a single ``ros2 pkg prefix`` probe (matches checks/robotics.py).
PKG_TIMEOUT = 8.0

#: Capability fields whose override value is a list.
LIST_FIELDS = ("packages", "binaries", "modules", "env", "paths", "topics")

#: Domain-level keys that are settings rather than capabilities.
RESERVED_DOMAIN_KEYS = ("default",)

#: Environment variables used as a fallback for a tool root.
TOOL_ENV = {
    "isaacsim": "ISAACSIM_PATH",
    "isaaclab": "ISAACLAB_PATH",
    "groot": "GR00T_PATH",
}


@dataclass(frozen=True)
class Capability:
    """One upstream thing Caasi can detect and delegate to."""

    key: str
    label: str
    packages: tuple[str, ...] = ()
    binaries: tuple[str, ...] = ()
    modules: tuple[str, ...] = ()
    env: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    launch: tuple[str, str] | None = None
    script: str | None = None
    topics: tuple[str, ...] = ()
    group: str | None = None
    tool: str | None = None
    core: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "packages": list(self.packages),
            "binaries": list(self.binaries),
            "modules": list(self.modules),
            "env": list(self.env),
            "paths": list(self.paths),
            "launch": list(self.launch) if self.launch else None,
            "script": self.script,
            "topics": list(self.topics),
            "group": self.group,
            "tool": self.tool,
            "core": self.core,
        }


@dataclass(frozen=True)
class Domain:
    """A catalog domain; usually (but not always) one ``caasi`` group."""

    key: str
    title: str
    kind: str  # "ros" | "sim" | "lab" | "python" | "mixed"
    verbs: tuple[str, ...] = ()
    capabilities: tuple[Capability, ...] = ()
    tool: str | None = None

    def capability(self, key: str) -> Capability | None:
        return next((c for c in self.capabilities if c.key == key), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "kind": self.kind,
            "verbs": list(self.verbs),
            "tool": self.tool,
            "capabilities": [c.to_dict() for c in self.capabilities],
        }


@dataclass(frozen=True)
class Resolved:
    """A capability after probing the machine."""

    capability: Capability
    found: bool
    how: str = ""  # "package" | "binary" | "module" | "env" | "path"
    value: str | None = None
    launch: tuple[str, str] | None = None
    script: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.capability.key,
            "label": self.capability.label,
            "group": self.capability.group,
            "core": self.capability.core,
            "found": self.found,
            "how": self.how or None,
            "value": self.value,
            "launch": list(self.launch) if self.launch else None,
            "script": str(self.script) if self.script else None,
        }


def targets(cap: Capability) -> str:
    """Every upstream name a capability can be found by (for messages)."""
    names = [
        *cap.packages,
        *cap.binaries,
        *cap.modules,
        *cap.env,
        *cap.paths,
        *([cap.script] if cap.script else []),
    ]
    return ", ".join(names) or cap.key


def override_field(cap: Capability) -> str:
    """The catalog field to edit when re-pointing a capability at a new upstream."""
    for field in ("packages", "binaries", "modules", "env", "paths"):
        if getattr(cap, field):
            return field
    return "packages"


# -- builders (keep the table readable) ---------------------------------


def _c(domain: str, key: str, **kwargs: Any) -> Capability:
    kwargs.setdefault("label", f"catalog.{domain}.{key}")
    for field_name in LIST_FIELDS:
        if kwargs.get(field_name):
            kwargs[field_name] = tuple(kwargs[field_name])
    if kwargs.get("launch"):
        kwargs["launch"] = tuple(kwargs["launch"])
    return Capability(key=key, **kwargs)


def _d(
    key: str,
    kind: str,
    verbs: tuple[str, ...] = (),
    tool: str | None = None,
    capabilities: tuple[Capability, ...] = (),
) -> Domain:
    return Domain(
        key=key,
        title=f"catalog.domain.{key}",
        kind=kind,
        verbs=tuple(verbs),
        tool=tool,
        capabilities=tuple(capabilities),
    )


DOMAINS: dict[str, Domain] = {
    d.key: d
    for d in (
        _d(
            "isaacros",
            "ros",
            ("status", "doctor", "list", "launch"),
            capabilities=(
                _c("isaacros", "nitros", packages=["isaac_ros_nitros"], group="nitros", core=True),
                _c(
                    "isaacros",
                    "slam",
                    packages=["isaac_ros_visual_slam"],
                    launch=["isaac_ros_visual_slam", "visual_slam.launch.py"],
                    group="slam",
                    core=True,
                ),
                _c(
                    "isaacros",
                    "mapping",
                    packages=["isaac_ros_nvblox"],
                    launch=["isaac_ros_nvblox", "nvblox.launch.py"],
                    group="mapping",
                    core=True,
                ),
                _c(
                    "isaacros",
                    "motion",
                    packages=["isaac_ros_cumotion"],
                    launch=["isaac_ros_cumotion", "isaac_ros_cumotion.launch.py"],
                    group="motion",
                    core=True,
                ),
                _c(
                    "isaacros",
                    "detection",
                    packages=["isaac_ros_object_detection"],
                    launch=["isaac_ros_object_detection", "object_detection.launch.py"],
                    group="perception",
                ),
                _c(
                    "isaacros",
                    "segmentation",
                    packages=["isaac_ros_image_segmentation"],
                    launch=["isaac_ros_image_segmentation", "image_segmentation.launch.py"],
                    group="perception",
                ),
                _c(
                    "isaacros",
                    "depth",
                    packages=["isaac_ros_depth_estimation", "isaac_ros_disparity_filters"],
                    group="perception",
                ),
                _c(
                    "isaacros",
                    "apriltag",
                    packages=["isaac_ros_apriltag"],
                    launch=["isaac_ros_apriltag", "apriltag.launch.py"],
                    group="perception",
                ),
                _c(
                    "isaacros",
                    "image_pipeline",
                    packages=["isaac_ros_image_pipeline"],
                    group="perception",
                ),
                _c("isaacros", "tensor_rt", packages=["isaac_ros_tensor_rt"]),
            ),
        ),
        _d(
            "perception",
            "mixed",
            ("status", "camera", "pose", "detect", "segment", "inspect"),
            tool="isaacsim",
            capabilities=(
                _c("perception", "camera", paths=["/dev/video*"], core=True),
                _c(
                    "perception",
                    "detection",
                    packages=["isaac_ros_object_detection"],
                    launch=["isaac_ros_object_detection", "object_detection.launch.py"],
                    core=True,
                ),
                _c(
                    "perception",
                    "segmentation",
                    packages=["isaac_ros_image_segmentation"],
                    launch=["isaac_ros_image_segmentation", "image_segmentation.launch.py"],
                ),
                _c(
                    "perception",
                    "depth",
                    packages=["isaac_ros_depth_estimation", "isaac_ros_disparity_filters"],
                ),
                _c(
                    "perception",
                    "pose",
                    packages=["isaac_ros_apriltag", "foundationalpose"],
                    launch=["isaac_ros_apriltag", "apriltag.launch.py"],
                    topics=["/tf", "/apriltag/detections"],
                ),
            ),
        ),
        _d(
            "slam",
            "ros",
            ("status", "launch", "test", "benchmark"),
            capabilities=(
                _c(
                    "slam",
                    "visual",
                    packages=["isaac_ros_visual_slam"],
                    launch=["isaac_ros_visual_slam", "visual_slam.launch.py"],
                    topics=["/tf", "/map", "/visual_slam/tracking/odometry"],
                    core=True,
                ),
                _c(
                    "slam",
                    "toolbox",
                    packages=["slam_toolbox"],
                    launch=["slam_toolbox", "online_async_launch.py"],
                    topics=["/tf", "/map", "/scan"],
                    core=True,
                ),
                _c(
                    "slam",
                    "cartographer",
                    packages=["cartographer_ros"],
                    launch=["cartographer_ros", "cartographer.launch.py"],
                    topics=["/tf", "/map"],
                ),
            ),
        ),
        _d(
            "mapping",
            "ros",
            ("status", "run", "inspect"),
            capabilities=(
                _c(
                    "mapping",
                    "nvblox",
                    packages=["isaac_ros_nvblox"],
                    launch=["isaac_ros_nvblox", "nvblox.launch.py"],
                    core=True,
                ),
                _c(
                    "mapping",
                    "map_saver",
                    packages=["nav2_map_server"],
                    binaries=["map_saver_cli"],
                    core=True,
                ),
                _c(
                    "mapping",
                    "occupancy",
                    packages=["slam_toolbox"],
                    launch=["slam_toolbox", "online_async_launch.py"],
                ),
            ),
        ),
        _d(
            "motion",
            "ros",
            ("status", "serve", "plan", "execute", "benchmark"),
            capabilities=(
                _c(
                    "motion",
                    "cumotion",
                    packages=["isaac_ros_cumotion"],
                    launch=["isaac_ros_cumotion", "isaac_ros_cumotion.launch.py"],
                    core=True,
                ),
                _c("motion", "curobo", modules=["curobo", "nvidia-curobo"]),
                _c("motion", "moveit", packages=["moveit_core", "moveit_ros_planning"], core=True),
                _c("motion", "ompl", packages=["moveit_planners_ompl"], core=True),
                _c("motion", "pilz", packages=["pilz_industrial_motion_planner"]),
                _c("motion", "stomp", packages=["moveit_planners_stomp"]),
                _c("motion", "chomp", packages=["moveit_planners_chomp"]),
            ),
        ),
        _d(
            "nitros",
            "ros",
            ("status", "doctor"),
            capabilities=(
                _c("nitros", "core", packages=["isaac_ros_nitros"], core=True),
                _c("nitros", "types", packages=["isaac_ros_nitros_type_interfaces"]),
                _c("nitros", "bridge", packages=["isaac_ros_nitros_bridge"]),
                _c("nitros", "disable", env=["ROS_DISABLE_NITROS"]),
            ),
        ),
        _d(
            "physics",
            "sim",
            ("status", "list", "run", "benchmark"),
            tool="isaacsim",
            capabilities=(
                _c(
                    "physics",
                    "physx",
                    paths=["extsPhysics/*physx*", "exts/omni.physx*"],
                    core=True,
                ),
                _c(
                    "physics",
                    "newton",
                    paths=["isaac-sim.newton.sh"],
                    modules=["newton-physics", "newton"],
                ),
                _c("physics", "warp", modules=["warp", "warp-lang"]),
                _c("physics", "mujoco", modules=["mujoco"]),
                _c("physics", "gazebo", binaries=["gz", "gazebo"]),
            ),
        ),
        _d(
            "warp",
            "python",
            ("status", "test", "benchmark"),
            capabilities=(_c("warp", "warp", modules=["warp", "warp-lang"], core=True),),
        ),
        _d(
            "groot",
            "python",
            ("status", "setup", "run", "train", "evaluate"),
            tool="groot",
            capabilities=(
                _c(
                    "groot",
                    "repo",
                    env=["GR00T_PATH"],
                    paths=["~/Isaac-GR00T", "~/gr00t", "~/workspaces/Isaac-GR00T"],
                    core=True,
                ),
                _c("groot", "module", modules=["gr00t"]),
                _c("groot", "train", script="scripts/finetune.py"),
                _c("groot", "evaluate", script="scripts/eval.py"),
                _c("groot", "data", script="scripts/data.py"),
            ),
        ),
        _d(
            "cosmos",
            "python",
            ("status", "run", "dataset"),
            capabilities=(
                _c("cosmos", "module", modules=["cosmos_predict1", "cosmos1"]),
                _c("cosmos", "cli", binaries=["cosmos", "ngc"]),
            ),
        ),
        _d(
            "usd",
            "sim",
            (),
            tool="isaacsim",
            capabilities=(
                _c("usd", "usdcat", binaries=["usdcat"], core=True),
                _c("usd", "usdchecker", binaries=["usdchecker"], core=True),
                _c("usd", "usdview", binaries=["usdview"]),
                _c("usd", "usdrecord", binaries=["usdrecord"]),
                _c("usd", "urdf_importer", paths=["exts/omni.importer.urdf"]),
                _c("usd", "check_urdf", binaries=["check_urdf"]),
                _c("usd", "xacro", binaries=["xacro"]),
                _c("usd", "nurec", binaries=["nurec"]),
            ),
        ),
        _d(
            "data",
            "mixed",
            (),
            tool="isaacsim",
            capabilities=(
                _c("data", "replicator", paths=["exts/omni.replicator.core"], core=True),
                _c("data", "mcap", packages=["rosbag2_storage_mcap"]),
                _c("data", "sqlite3", packages=["rosbag2_storage_default_plugins"]),
                _c("data", "hf", binaries=["hf", "huggingface-cli"]),
                _c("data", "ngc", binaries=["ngc"]),
            ),
        ),
        _d(
            "teleop",
            "ros",
            ("start", "record", "stop", "replay"),
            tool="isaacsim",
            capabilities=(
                _c(
                    "teleop",
                    "keyboard",
                    packages=["teleop_twist_keyboard"],
                    launch=["teleop_twist_keyboard", "teleop-launch.py"],
                    core=True,
                ),
                _c(
                    "teleop",
                    "joy",
                    packages=["teleop_twist_joy", "joy"],
                    launch=["teleop_twist_joy", "teleop-launch.py"],
                ),
                _c("teleop", "xr", paths=["isaac-sim.xr.vr.sh"]),
                _c("teleop", "record", packages=["rosbag2"], core=True),
            ),
        ),
        _d(
            "sdg",
            "sim",
            (),
            tool="isaacsim",
            capabilities=(
                _c("sdg", "replicator", paths=["exts/omni.replicator.core"], core=True),
                _c("sdg", "writer_kit", paths=["exts/omni.replicator.writer.kit"]),
            ),
        ),
    )
}


# -- overrides ------------------------------------------------------------


def overrides_from(config: "Config | None") -> dict[str, Any]:
    """Raw ``catalog:`` mapping from the effective configuration."""
    if config is None:
        return {}
    value = config.get("catalog")
    return value if isinstance(value, dict) else {}


def _coerce(field_name: str, value: Any) -> Any:
    if field_name in LIST_FIELDS:
        if isinstance(value, (list, tuple)):
            return tuple(str(v) for v in value)
        if isinstance(value, str):
            return (value,)
        return ()
    if field_name == "launch":
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return (str(value[0]), str(value[1]))
        return None
    if field_name == "core":
        return bool(value)
    if value is None:
        return None
    return str(value)


def _apply_override(cap: Capability, override: dict[str, Any]) -> Capability:
    known = {f.name for f in dataclass_fields(Capability)}
    changes: dict[str, Any] = {}
    for field_name, value in override.items():
        if field_name == "key" or field_name not in known:
            continue
        changes[field_name] = _coerce(field_name, value)
    if not changes:
        return cap
    return replace(cap, **changes)


def _capability_from_override(domain_key: str, key: str, data: dict[str, Any]) -> Capability:
    fields = {k: _coerce(k, v) for k, v in data.items() if k != "key"}
    fields.setdefault("label", f"catalog.{domain_key}.{key}")
    known = {f.name for f in dataclass_fields(Capability)}
    return Capability(key=key, **{k: v for k, v in fields.items() if k in known})


def _with_tool(cap: Capability, tool: str | None) -> Capability:
    """Inherit the domain's tool root when the capability does not name one."""
    if tool is None or cap.tool == tool:
        return cap
    return replace(cap, tool=tool)


def _merge_domain(base: Domain, overrides: dict[str, Any]) -> Domain:
    caps: dict[str, Capability] = {c.key: c for c in base.capabilities}
    for key, value in overrides.items():
        if key in RESERVED_DOMAIN_KEYS or not isinstance(value, dict):
            continue
        existing = caps.get(key)
        caps[key] = (
            _apply_override(existing, value)
            if existing is not None
            else _capability_from_override(base.key, key, value)
        )
    return replace(
        base, capabilities=tuple(_with_tool(c, base.tool) for c in caps.values())
    )


def _merged_domains(config: "Config | None") -> dict[str, Domain]:
    overrides = overrides_from(config)
    result: dict[str, Domain] = {key: _merge_domain(d, {}) for key, d in DOMAINS.items()}
    for key, value in overrides.items():
        if not isinstance(value, dict):
            continue
        if key in result:
            result[key] = _merge_domain(result[key], value)
        else:
            caps = tuple(
                _capability_from_override(key, cap_key, cap_value)
                for cap_key, cap_value in value.items()
                if cap_key not in RESERVED_DOMAIN_KEYS and isinstance(cap_value, dict)
            )
            result[key] = Domain(
                key=key,
                title=f"catalog.domain.{key}",
                kind="mixed",
                capabilities=caps,
            )
    return result


# -- public API -----------------------------------------------------------


def domains(config: "Config | None" = None) -> tuple[Domain, ...]:
    """All domains, built-ins merged with ``catalog:`` overrides."""
    return tuple(_merged_domains(config).values())


def domain(key: str, config: "Config | None" = None) -> Domain | None:
    return _merged_domains(config).get(key)


def capabilities(domain_key: str, config: "Config | None" = None) -> tuple[Capability, ...]:
    found = domain(domain_key, config)
    return found.capabilities if found else ()


def capability(
    domain_key: str, cap_key: str, config: "Config | None" = None
) -> Capability | None:
    found = domain(domain_key, config)
    return found.capability(cap_key) if found else None


def domain_setting(
    domain_key: str, name: str, config: "Config | None" = None, default: Any = None
) -> Any:
    """Read a domain-level setting (currently only ``default``)."""
    entry = overrides_from(config).get(domain_key)
    if isinstance(entry, dict) and name in entry:
        return entry[name]
    return default


# -- probing --------------------------------------------------------------

_prefix_cache: dict[str, Path | None] = {}


def clear_cache() -> None:
    """Drop memoised probe results (used by the test-suite)."""
    _prefix_cache.clear()


def _pkg_prefix(name: str) -> Path | None:
    if ros.find_ros2_binary() is None:
        return None
    if name not in _prefix_cache:
        _prefix_cache[name] = ros.pkg_prefix(name)
    return _prefix_cache[name]


def tool_root(config: "Config | None", name: str | None) -> Path | None:
    """Filesystem root for a tool: registry first, then its env var."""
    if not name:
        return None
    if config is not None:
        resolved = config.resolve_tool(name)
        if resolved is not None and resolved.expanded_path is not None:
            return resolved.expanded_path
    env_value = os.environ.get(TOOL_ENV.get(name, ""))
    if env_value:
        candidate = Path(env_value).expanduser()
        if candidate.is_dir():
            return candidate
    return None


def _match_paths(patterns: tuple[str, ...], config: "Config | None", tool: str | None) -> str | None:
    root = tool_root(config, tool)
    for pattern in patterns:
        if pattern.startswith("~") or pattern.startswith("/"):
            base = Path(pattern).expanduser()
            parent, glob = base.parent, base.name
            if parent.is_dir():
                hit = next(iter(sorted(parent.glob(glob))), None)
                if hit is not None:
                    return str(hit)
            continue
        if root is not None and root.is_dir():
            hit = next(iter(sorted(root.glob(pattern))), None)
            if hit is not None:
                return str(hit)
    return None


def _resolve_script(cap: Capability, config: "Config | None") -> Path | None:
    if not cap.script:
        return None
    script = Path(cap.script).expanduser()
    if script.is_absolute():
        return script if script.exists() else None
    root = tool_root(config, cap.tool)
    if root is None:
        return None
    candidate = root / script
    return candidate if candidate.exists() else None


def resolve(cap: Capability, config: "Config | None" = None) -> Resolved:
    """Probe a capability: package → binary → module → env → path, first hit wins."""
    tool = cap.tool
    launch = cap.launch
    script = _resolve_script(cap, config)

    for package in cap.packages:
        prefix = _pkg_prefix(package)
        if prefix is not None:
            return Resolved(cap, True, "package", str(prefix), launch, script)

    for binary in cap.binaries:
        path = shell.which(binary)
        if path:
            return Resolved(cap, True, "binary", path, launch, script)

    if cap.modules:
        version = pydist.pip_version(*cap.modules)
        if version:
            return Resolved(cap, True, "module", version, launch, script)

    for variable in cap.env:
        value = os.environ.get(variable)
        if value:
            return Resolved(cap, True, "env", value, launch, script)

    matched = _match_paths(cap.paths, config, tool)
    if matched:
        return Resolved(cap, True, "path", matched, launch, script)

    return Resolved(cap, False, "", None, launch, script)


def resolve_domain(domain_key: str, config: "Config | None" = None) -> tuple[Resolved, ...]:
    """Resolve every capability of a domain, keeping catalog order."""
    found = domain(domain_key, config)
    if found is None:
        return ()
    return tuple(resolve(cap, config) for cap in found.capabilities)


def resolve_capability(
    domain_key: str, cap_key: str, config: "Config | None" = None
) -> Resolved | None:
    found = domain(domain_key, config)
    if found is None:
        return None
    cap = found.capability(cap_key)
    if cap is None:
        return None
    return resolve(cap, config)
