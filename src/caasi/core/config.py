"""Configuration loading, merging, persistence and the multi-version tool registry.

Precedence (lowest to highest):
    built-in defaults
    < global config   ~/.config/caasi/config.yaml (XDG aware)
    < project config  ./caasi.yaml
    < CAASI_CONFIG env file
    < --config flag file
    < individual env vars (CAASI_LANG, CAASI_LAYOUT, CAASI_HELP_ORDER)

The tool registry lets users register custom install paths and multiple
versions of each tool (Isaac Sim, Isaac Lab, ROS 2, ...) with a selectable
default, e.g.::

    tools:
      isaacsim:
        default: "6.0"
        versions:
          "6.0": { path: /opt/isaac-sim-6.0 }
          "5.1": { path: /opt/isaac-sim-5.1 }
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

APP_DIR_NAME = "caasi"
CONFIG_FILE_NAME = "config.yaml"
PROJECT_FILE_NAME = "caasi.yaml"
ENV_CONFIG = "CAASI_CONFIG"
ENV_LANG = "CAASI_LANG"

DEFAULTS: dict[str, Any] = {
    "language": "en",
    "layout": "rich",
    "help_order": "grouped",
    "defaults": {"output": "table"},
    "paths": {
        "runs": "~/.caasi/runs",
        "datasets": "~/.caasi/datasets",
    },
    "tools": {},
}


def global_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / APP_DIR_NAME / CONFIG_FILE_NAME


def project_config_path(start: Path | None = None) -> Path:
    return (start or Path.cwd()) / PROJECT_FILE_NAME


def load_yaml_file(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def split_dotted(dotted: str) -> list[str]:
    """Split a dotted key, honouring quoted segments (e.g. versions."6.0".path)."""
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for ch in dotted:
        if quote:
            if ch == quote:
                quote = None
            else:
                current.append(ch)
        elif ch in ("'", '"'):
            quote = ch
        elif ch == ".":
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


def get_dotted(data: dict, dotted: str) -> Any:
    node: Any = data
    for part in split_dotted(dotted):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def set_dotted(data: dict, dotted: str, value: Any) -> None:
    parts = split_dotted(dotted)
    node = data
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value


@dataclass(frozen=True)
class ResolvedTool:
    name: str
    version: str | None
    path: str | None
    python: str | None
    source: str  # currently always "config"

    @property
    def expanded_path(self) -> Path | None:
        return Path(self.path).expanduser() if self.path else None


class Config:
    """Effective (merged) configuration."""

    def __init__(self, data: dict[str, Any], sources: list[Path]):
        self.data = data
        self.sources = sources

    @classmethod
    def load(
        cls,
        config_path_override: Path | str | None = None,
        project_dir: Path | None = None,
    ) -> "Config":
        data = copy.deepcopy(DEFAULTS)
        sources: list[Path] = []

        for path in (
            global_config_path(),
            project_config_path(project_dir),
            *(
                [Path(os.environ[ENV_CONFIG]).expanduser()]
                if os.environ.get(ENV_CONFIG)
                else []
            ),
            *(
                [Path(config_path_override).expanduser()]
                if config_path_override is not None
                else []
            ),
        ):
            if path.is_file():
                data = deep_merge(data, load_yaml_file(path))
                sources.append(path)

        lang_env = os.environ.get(ENV_LANG)
        if lang_env:
            data["language"] = lang_env

        return cls(data, sources)

    # -- accessors ---------------------------------------------------
    @property
    def language(self) -> str:
        value = self.data.get("language")
        return str(value) if value else "en"

    @property
    def layout(self) -> str | None:
        """Configured table layout, or None to let the caller apply its default."""
        value = self.data.get("layout")
        return str(value) if value else None

    @property
    def help_order(self) -> str | None:
        """Configured root help order, or None to let the caller apply its default."""
        value = self.data.get("help_order")
        return str(value) if value else None

    def get(self, dotted: str, default: Any = None) -> Any:
        value = get_dotted(self.data, dotted)
        return default if value is None else value

    def set(self, dotted: str, value: Any) -> None:
        set_dotted(self.data, dotted, value)

    def expanded_path_for(self, dotted: str) -> Path | None:
        value = self.get(dotted)
        if not value:
            return None
        return Path(str(value)).expanduser()

    def save(self, path: Path | None = None) -> Path:
        """Write the current configuration to the global config file."""
        target = Path(path) if path else global_config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            yaml.safe_dump(self.data, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        return target

    # -- tool registry -----------------------------------------------
    def tools(self) -> dict[str, Any]:
        tools = self.data.get("tools")
        return tools if isinstance(tools, dict) else {}

    def resolve_tool(self, name: str, version: str | None = None) -> ResolvedTool | None:
        """Resolve a tool (default or named version) from the registry."""
        entry = self.tools().get(name)
        if not isinstance(entry, dict):
            return None

        versions = entry.get("versions")
        if not isinstance(versions, dict) or not versions:
            if entry.get("path") or entry.get("python"):
                return ResolvedTool(name, None, entry.get("path"), entry.get("python"), "config")
            return None

        if version is None:
            default = entry.get("default")
            version = None
            if default is not None:
                version = next((k for k in versions if str(k) == str(default)), None)
            if version is None:
                version = next(iter(versions))

        if version not in versions:
            version = next((k for k in versions if str(k) == str(version)), None)
            if version is None:
                return None

        spec = versions.get(version)
        if not isinstance(spec, dict):
            return None
        return ResolvedTool(name, str(version), spec.get("path"), spec.get("python"), "config")
