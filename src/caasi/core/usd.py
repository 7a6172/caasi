"""Asset tooling discovery + command builders (``plan3.md`` §35-36).

Caasi never parses, converts or validates assets itself — it builds command
lines for tools that already exist (the Isaac Sim URDF importer,
``check_urdf``, ``usdchecker``) and lets the catalog decide where they live,
so an upstream rename is a config edit rather than a Caasi release.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..i18n import _
from . import adapters, catalog

if TYPE_CHECKING:  # pragma: no cover
    from .config import Config

DOMAIN = "usd"

#: Extensions routed to the URDF importer / check_urdf.
URDF_EXTS = (".urdf", ".xacro")
#: Extensions only the Isaac Sim importer can handle.
MJCF_EXTS = (".mjcf",)
#: Extensions validated with usdchecker.
USD_EXTS = (".usd", ".usda", ".usdc", ".usdz")


class UsdError(RuntimeError):
    """Raised when no available tool can handle the requested operation."""


@dataclass(frozen=True)
class Converter:
    """A resolved way to handle an asset file."""

    mode: str  # "convert" | "validate"
    tool: str  # catalog capability key that produced the command
    command: list[str]


def resolve(cap_key: str, config: "Config | None" = None) -> catalog.Resolved | None:
    return catalog.resolve_capability(DOMAIN, cap_key, config)


def binary(cap_key: str, config: "Config | None" = None) -> str | None:
    """Path of a capability resolved as a command-line binary, if any."""
    item = resolve(cap_key, config)
    if item is not None and item.found and item.how == "binary" and item.value:
        return item.value
    return None


def usdchecker_command(source: Path, config: "Config | None" = None) -> list[str] | None:
    tool = binary("usdchecker", config)
    return [tool, str(source)] if tool else None


def check_urdf_command(source: Path, config: "Config | None" = None) -> list[str] | None:
    tool = binary("check_urdf", config)
    return [tool, str(source)] if tool else None


def importer_command(
    source: Path, dest: Path, config: "Config | None" = None
) -> list[str] | None:
    """Isaac Sim's ``omni.importer.urdf`` driven through the resolved launcher."""
    item = resolve("urdf_importer", config)
    if item is None or not item.found:
        return None
    adapter = adapters.adapter_for(DOMAIN, config)
    if not isinstance(adapter, adapters.SimAdapter):
        return None
    launcher = adapter.launcher(config)
    if not launcher:
        return None
    return [launcher, "-m", "omni.importer.urdf", str(source), str(dest)]


def default_dest(source: Path) -> Path:
    """USD path a conversion of *source* produces next to it."""
    return source.with_suffix(".usd")


def converter_for(
    source: Path,
    config: "Config | None" = None,
    *,
    dest: Path | None = None,
    extra: list[str] | None = None,
) -> Converter:
    """Best available tool for *source*; raises :class:`UsdError` when none.

    URDF/XACRO/MJCF convert through the Isaac Sim importer when it resolves;
    plain URDF falls back to ``check_urdf`` validation; USD files validate
    through ``usdchecker``.
    """
    suffix = source.suffix.lower()
    argv = [str(part) for part in (extra or [])]
    if suffix in USD_EXTS:
        command = usdchecker_command(source, config)
        if command is None:
            raise UsdError(_("usd.no_usdchecker"))
        return Converter("validate", "usdchecker", [*command, *argv])
    if suffix in URDF_EXTS + MJCF_EXTS:
        command = importer_command(source, dest or default_dest(source), config)
        if command is not None:
            return Converter("convert", "urdf_importer", [*command, *argv])
        if suffix in URDF_EXTS:
            command = check_urdf_command(source, config)
            if command is not None:
                return Converter("validate", "check_urdf", [*command, *argv])
        raise UsdError(_("usd.no_converter", name=source.name))
    raise UsdError(_("usd.bad_format", suffix=suffix or source.name))
