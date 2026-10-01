"""Tests for the zero-dependency PEP 440 subset (core/requirements.py)."""

from __future__ import annotations

import pytest

from caasi.core import requirements


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("5.1.0", (5, 1, 0)),
        ("v2.3", (2, 3)),
        ("V6.0.1", (6, 0, 1)),
        ("3.12.3 (main)", (3, 12, 3)),
        ("13", (13,)),
        ("jazzy", None),
        ("", None),
        (None, None),
        (True, None),
        (5, (5,)),
    ],
)
def test_parse_version(value, expected):
    assert requirements.parse_version(value) == expected


def test_ge_and_le():
    assert requirements.satisfies("6.0.1", ">=5.0") is True
    assert requirements.satisfies("5.0", ">=5.0") is True
    assert requirements.satisfies("4.9.9", ">=5.0") is False
    assert requirements.satisfies("2.2", "<=2.3") is True
    assert requirements.satisfies("2.4", "<=2.3") is False
    # zero-padded comparison: 5.0 == 5.0.0
    assert requirements.satisfies("5.0", ">=5.0.0") is True


def test_gt_and_lt():
    assert requirements.satisfies("2.4", ">2.3") is True
    assert requirements.satisfies("2.3", ">2.3") is False
    assert requirements.satisfies("2.2", "<2.3") is True
    assert requirements.satisfies("2.3", "<2.3") is False


def test_eq_and_ne():
    assert requirements.satisfies("3.12.3", "==3.12.3") is True
    assert requirements.satisfies("3.12", "==3.12.0") is True
    assert requirements.satisfies("3.12.4", "==3.12.3") is False
    assert requirements.satisfies("3.12.4", "!=3.12.3") is True
    assert requirements.satisfies("3.12.3", "!=3.12.3") is False


def test_bare_version_implies_equality():
    assert requirements.satisfies("5.1.0", "5.1.0") is True
    assert requirements.satisfies("5.1.1", "5.1.0") is False


def test_compatible_release():
    assert requirements.satisfies("2.5", "~=2.3") is True
    assert requirements.satisfies("3.0", "~=2.3") is False
    assert requirements.satisfies("2.2", "~=2.3") is False
    assert requirements.satisfies("2.3.5", "~=2.3.1") is True
    assert requirements.satisfies("2.4.0", "~=2.3.1") is False
    # a single-segment ~= is uninterpretable in this subset → UNVERIFIED
    assert requirements.satisfies("2.0", "~=2") is None


def test_conjunctions():
    assert requirements.satisfies("2.4", ">=2.0,<3.0") is True
    assert requirements.satisfies("3.1", ">=2.0,<3.0") is False
    assert requirements.satisfies("1.9", ">=2.0,<3.0") is False
    # False short-circuits even when another clause is unverifiable
    assert requirements.satisfies("3.0", "<2.0,>=jazzy") is False
    # mixed True + None → None (never invent a verdict)
    assert requirements.satisfies("1.0", "<2.0,>=jazzy") is None
    assert requirements.satisfies("2.5", ">=2.0,==jazzy") is None


def test_wildcards():
    assert requirements.satisfies("1.2.7", "==1.2.x") is True
    assert requirements.satisfies("1.2", "==1.2.*") is True
    assert requirements.satisfies("1.3.0", "==1.2.x") is False
    assert requirements.satisfies("1.3.0", "!=1.2.x") is True
    # unparseable against a wildcard → UNVERIFIED
    assert requirements.satisfies("jazzy", "==1.2.x") is None


def test_string_fallback_for_non_numeric_versions():
    assert requirements.satisfies("jazzy", "==jazzy") is True
    assert requirements.satisfies("jazzy", "==rolling") is False
    assert requirements.satisfies("jazzy", "!=rolling") is True
    # ordering comparisons against names are UNVERIFIED, never a crash
    assert requirements.satisfies("jazzy", ">=humble") is None
    assert requirements.satisfies("jazzy", "<rolling") is None
    # a number against a name is just as uncomparable
    assert requirements.satisfies("6.0.1", "==jazzy") is None


@pytest.mark.parametrize("specifier", ["", "   ", ",,", ">=5.0" ])
@pytest.mark.parametrize("detected", ["", "   "])
def test_blank_inputs_are_unverified(detected, specifier):
    assert requirements.satisfies(detected, specifier) is None


def test_none_inputs_are_unverified():
    assert requirements.satisfies(None, ">=1.0") is None
    assert requirements.satisfies("1.0", None) is None
    assert requirements.satisfies(None, None) is None


def test_malformed_input_never_crashes():
    # both sides unparseable → plain string equality, no crash
    assert requirements.satisfies("!!!", "@@@") is False
    assert requirements.satisfies("!!!", ">=@@@") is None
    assert requirements.satisfies("1.0", ">=") is None
    assert requirements.satisfies(object(), ">=1.0") in (True, False, None)
