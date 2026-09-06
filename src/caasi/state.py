"""Global CLI state populated by the root command callback.

Kept intentionally tiny: commands read verbosity/output preferences and the
loaded configuration from here instead of threading parameters everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .i18n import resolve_locale, set_locale

if TYPE_CHECKING:  # pragma: no cover
    from .core.config import Config


@dataclass
class GlobalState:
    verbose: bool = False
    quiet: bool = False
    json_output: bool = False
    config_path: Optional[Path] = None
    lang: Optional[str] = None
    config: Optional["Config"] = None


_state = GlobalState()


def get() -> GlobalState:
    return _state


def configure(
    *,
    verbose: bool = False,
    quiet: bool = False,
    json_output: bool = False,
    config_path: Path | None = None,
    lang: str | None = None,
) -> None:
    """Store global options and load configuration + locale."""
    from .core.config import Config

    _state.verbose = verbose
    _state.quiet = quiet
    _state.json_output = json_output
    _state.config_path = config_path
    _state.lang = lang
    _state.config = Config.load(config_path_override=config_path)
    set_locale(resolve_locale(lang, _state.config.language))


def cfg() -> "Config":
    """Return the loaded configuration, loading it lazily when needed."""
    if _state.config is None:
        from .core.config import Config

        _state.config = Config.load(config_path_override=_state.config_path)
        set_locale(resolve_locale(_state.lang, _state.config.language))
    return _state.config


def reset() -> None:
    """Reset state (used by tests)."""
    global _state
    _state = GlobalState()
