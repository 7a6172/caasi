"""i18n-ready message layer.

All user-facing strings go through ``_()``. English is the only bundled
language today; adding a language means adding ``caasi/i18n/<code>.py``
with a ``MESSAGES`` dict and registering it in ``CATALOGS``.

Locale resolution order: ``--lang`` flag > ``CAASI_LANG`` env var >
config ``language`` key > ``en``.
"""

from __future__ import annotations

import os
from typing import Any

from . import en

DEFAULT_LOCALE = "en"
ENV_LANG = "CAASI_LANG"

CATALOGS: dict[str, dict[str, str]] = {
    "en": en.MESSAGES,
}

_active_locale: str = DEFAULT_LOCALE


def _normalize(code: str | None) -> str | None:
    if not code:
        return None
    candidate = code.strip().lower().replace("_", "-")
    if candidate in CATALOGS:
        return candidate
    base = candidate.split("-")[0]
    if base in CATALOGS:
        return base
    return None


def resolve_locale(cli_lang: str | None = None, config_lang: str | None = None) -> str:
    """Resolve the effective locale from flag > env > config > default."""
    for candidate in (cli_lang, os.environ.get(ENV_LANG), config_lang):
        code = _normalize(candidate)
        if code:
            return code
    return DEFAULT_LOCALE


def set_locale(code: str | None) -> str:
    """Activate a locale; unknown codes fall back to English."""
    global _active_locale
    _active_locale = _normalize(code) or DEFAULT_LOCALE
    return _active_locale


def get_locale() -> str:
    return _active_locale


def _(_message_key: str, **kwargs: Any) -> str:
    """Look up a message in the active catalog, falling back to English, then the key."""
    catalog = CATALOGS.get(_active_locale, CATALOGS[DEFAULT_LOCALE])
    template = catalog.get(_message_key)
    if template is None and _active_locale != DEFAULT_LOCALE:
        template = CATALOGS[DEFAULT_LOCALE].get(_message_key)
    if template is None:
        return _message_key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return template
    return template


# Initialize from the environment at import time so Typer help texts
# (captured at decoration time) respect CAASI_LANG.
set_locale(resolve_locale())
