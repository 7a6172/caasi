"""i18n layer tests and catalog consistency (every `_("key")` must exist)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from caasi import i18n
from caasi.checks import SECTION_KEYS
from caasi.i18n import en

SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "caasi"
KEY_USAGE = re.compile(r"\b_\(\s*[\"']([a-zA-Z0-9_.]+)[\"']")


@pytest.fixture(autouse=True)
def restore_locale():
    yield
    i18n.set_locale("en")


def _used_keys() -> set[str]:
    keys: set[str] = set()
    for path in SRC_DIR.rglob("*.py"):
        keys.update(KEY_USAGE.findall(path.read_text(encoding="utf-8")))
    return keys


def test_all_used_keys_exist_in_english_catalog():
    used = _used_keys()
    assert used, "expected to find message keys in the source tree"
    missing = used - set(en.MESSAGES)
    assert not missing, f"keys used in code but missing from en.py: {sorted(missing)}"


def test_doctor_section_titles_exist():
    for key in SECTION_KEYS:
        assert f"doctor.section.{key}" in en.MESSAGES


def test_catalog_values_are_nonempty_strings():
    for key, value in en.MESSAGES.items():
        assert isinstance(value, str) and value.strip(), key


def test_unknown_key_falls_back_to_key():
    assert i18n._("no.such.key") == "no.such.key"


def test_unknown_locale_falls_back_to_english():
    assert i18n.set_locale("xx") == "en"
    assert i18n.get_locale() == "en"


def test_locale_normalization():
    assert i18n.set_locale("EN_us") == "en"


def test_format_kwargs():
    template = en.MESSAGES["config.get.missing"]
    assert i18n._("config.get.missing", key="a.b") == template.format(key="a.b")


def test_resolve_locale_precedence(monkeypatch):
    monkeypatch.setenv("CAASI_LANG", "en")
    assert i18n.resolve_locale(cli_lang=None, config_lang="xx") == "en"
    assert i18n.resolve_locale(cli_lang="xx", config_lang=None) == "en"
    monkeypatch.delenv("CAASI_LANG")
    assert i18n.resolve_locale(cli_lang=None, config_lang=None) == "en"


def test_env_lang_applies_at_resolution(monkeypatch):
    monkeypatch.setenv("CAASI_LANG", "en")
    assert i18n.resolve_locale() == "en"
