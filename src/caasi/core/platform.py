"""Foundation-model platform discovery (``plan3.md`` §26, §33-34).

GR00T, Cosmos, NuRec and NGC are discovered through the catalog and delegated
to: repo scripts run through the repo's own interpreter, CLIs run directly.
Caasi implements none of them — where nothing is installed every command
fails with the exact config key that would point at it. Script paths come
from the catalog, so an upstream release that moves files is a config edit.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ..i18n import _
from . import adapters, catalog

if TYPE_CHECKING:  # pragma: no cover
    from .config import Config

GROOT = "groot"
COSMOS = "cosmos"

#: Capability ``groot run`` delegates to when nothing else is configured.
GROOT_DEFAULT_CAP = "module"


class PlatformError(RuntimeError):
    """Raised when a platform tool cannot be resolved."""


# -- GR00T ------------------------------------------------------------------


def groot_repo(config: "Config | None" = None) -> catalog.Resolved:
    """The GR00T repository: ``GR00T_PATH`` → ``tools.groot`` → common paths."""
    item = catalog.resolve_capability(GROOT, "repo", config)
    if item is None or not item.found or not item.value:
        targets = catalog.targets(item.capability) if item is not None else "GR00T_PATH"
        raise PlatformError(_("groot.repo_missing", targets=targets))
    return item


def groot_root(config: "Config | None" = None) -> Path:
    return Path(groot_repo(config).value).expanduser()


def groot_python(config: "Config | None" = None) -> str:
    """The repo's own interpreter (falls back to this process' Python)."""
    adapter = adapters.adapter_for(GROOT)
    launcher = getattr(adapter, "launcher", None)
    return (launcher(config) if callable(launcher) else None) or sys.executable


def groot_default(config: "Config | None" = None) -> str:
    return str(catalog.domain_setting(GROOT, "default", config) or GROOT_DEFAULT_CAP)


def groot_script(config: "Config | None", cap_key: str) -> Path:
    """A repo script from the catalog (train/evaluate/data); honest failure."""
    item = catalog.resolve_capability(GROOT, cap_key, config)
    if item is None:
        raise PlatformError(
            _("adapters.unknown_capability", domain=GROOT, cap=cap_key)
        )
    if item.script is not None:
        return item.script
    root = groot_root(config)
    relative = item.capability.script
    candidate = root / relative if relative else None
    if candidate is not None and candidate.is_file():
        return candidate
    raise PlatformError(
        _("groot.script_missing", repo=str(root), script=relative or cap_key, cap=cap_key)
    )


def groot_setup(config: "Config | None" = None) -> tuple[list[str], Path]:
    """The repo's own install steps: ``post_install.sh``, else ``pip install -e .``."""
    root = groot_root(config)
    hook = root / "post_install.sh"
    if hook.is_file():
        return [str(hook)], root
    return [groot_python(config), "-m", "pip", "install", "-e", "."], root


def groot_command(
    config: "Config | None", cap_key: str, extra: list[str] | None = None
) -> tuple[list[str], Path]:
    """(command, cwd) delegating to the repo's own module or script."""
    root = groot_root(config)
    python = groot_python(config)
    args = [str(a) for a in (extra or [])]
    if cap_key == "module":
        item = catalog.resolve_capability(GROOT, "module", config)
        if item is None or not item.found:
            cap = item.capability if item is not None else catalog.capability(GROOT, "module", config)
            targets = catalog.targets(cap) if cap is not None else "gr00t"
            field = catalog.override_field(cap) if cap is not None else "packages"
            raise PlatformError(
                _("adapters.missing", domain=GROOT, cap="module", targets=targets)
                + " "
                + _("adapters.override_hint", domain=GROOT, cap="module", field=field)
            )
        module = item.capability.modules[0] if item.capability.modules else "gr00t"
        return [python, "-m", module, *args], root
    script = groot_script(config, cap_key)
    return [python, str(script), *args], root


def groot_train_command(
    config: "Config | None",
    cap_key: str,
    config_path: Path,
    extra: list[str] | None = None,
) -> tuple[list[str], Path]:
    """(command, cwd) for ``train``/``evaluate``: the repo script plus CONFIG."""
    root = groot_root(config)
    script = groot_script(config, cap_key)
    args = [str(a) for a in (extra or [])]
    return [groot_python(config), str(script), str(config_path), *args], root


# -- Cosmos / NuRec / NGC ----------------------------------------------------


def cosmos_command(
    config: "Config | None" = None, extra: list[str] | None = None
) -> tuple[list[str], str]:
    """(command, backend) for the Cosmos CLI; ``-m`` fallback for the module."""
    args = [str(a) for a in (extra or [])]
    cli = catalog.resolve_capability(COSMOS, "cli", config)
    if cli is not None and cli.found and cli.how == "binary" and cli.value:
        return [cli.value, *args], Path(cli.value).name
    module = catalog.resolve_capability(COSMOS, "module", config)
    if module is not None and module.found and module.capability.modules:
        name = module.capability.modules[0]
        return [sys.executable, "-m", name, *args], name
    raise PlatformError(
        _("ecosystem.nothing_installed", domain=COSMOS)
        + " "
        + _(
            "adapters.override_hint",
            domain=COSMOS,
            cap="cli",
            field=catalog.override_field(cli.capability)
            if cli is not None
            else "binaries",
        )
    )


def nurec(config: "Config | None" = None) -> catalog.Resolved | None:
    """The NuRec/neural-reconstruction CLI (a capability of the ``usd`` domain)."""
    return catalog.resolve_capability("usd", "nurec", config)
