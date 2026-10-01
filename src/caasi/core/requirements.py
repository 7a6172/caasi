"""Zero-dependency version-requirement matching (a small PEP 440 subset).

``caasi.yaml`` records requirements like ``isaac_sim: {version: ">=5.0"}`` or
``ros2: {version: "==jazzy"}``. CAASI must never crash — and never invent a
verdict — when comparing detected environment versions against them, so
:func:`satisfies` returns ``True`` / ``False`` / ``None``, where **None means
UNVERIFIED** (§16: absence of evidence is not evidence of incompatibility).

Supported: ``>= <= > < == != ~=``, comma conjunctions, ``.x`` wildcards and a
string-equality fallback for non-numeric versions (ROS distro names). No
packaging dependency; anything unparseable degrades to None.
"""

from __future__ import annotations

import re
from typing import Any

_OPERATORS = ("~=", "==", "!=", ">=", "<=", ">", "<")
_VERSION_RE = re.compile(r"(\d+(?:\.\d+)*)")
_WILDCARD_RE = re.compile(r"^[vV]?(\d+(?:\.\d+)*)\.(?:x|X|\*)$")


def parse_version(value: Any) -> tuple[int, ...] | None:
    """Extract the leading numeric segments of *value*, or None."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().lstrip("vV")
    match = _VERSION_RE.search(text)
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.group(1).split("."))
    except ValueError:  # pragma: no cover - regex guarantees digits
        return None


def _compare(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    """Zero-padded tuple comparison: -1, 0 or 1."""
    size = max(len(left), len(right))
    padded_left = left + (0,) * (size - len(left))
    padded_right = right + (0,) * (size - len(right))
    if padded_left < padded_right:
        return -1
    if padded_left > padded_right:
        return 1
    return 0


def wildcards_match(detected: Any, spec: Any) -> bool | None:
    """``==1.2.x``-style comparison; None when *spec* is not a wildcard form."""
    match = _WILDCARD_RE.match(str(spec).strip())
    if not match:
        return None
    prefix = parse_version(match.group(1))
    left = parse_version(detected)
    if prefix is None or left is None:
        return None
    return left[: len(prefix)] == prefix


def _split_specifier(specifier: str) -> tuple[str, str]:
    """``">=5.0"`` → ``(">=", "5.0")``; a bare version implies ``==``."""
    text = str(specifier).strip()
    for op in _OPERATORS:
        if text.startswith(op):
            return op, text[len(op) :].strip()
    return "==", text


def _satisfies_one(detected: str, op: str, spec: str) -> bool | None:
    if op in ("==", "!="):
        wildcard = wildcards_match(detected, spec)
        if wildcard is not None:
            return wildcard if op == "==" else not wildcard
    left = parse_version(detected)
    right = parse_version(spec)
    if left is None or right is None:
        # Non-numeric versions (e.g. ROS distro names) compare as strings, but
        # only when *both* sides are non-numeric; a name against a number (or a
        # wildcard) is meaningless and degrades to UNVERIFIED.
        if op in ("==", "!=") and left is None and right is None:
            same = str(detected).strip() == str(spec).strip()
            return same if op == "==" else not same
        return None
    if op == "==":
        return _compare(left, right) == 0
    if op == "!=":
        return _compare(left, right) != 0
    if op == ">=":
        return _compare(left, right) >= 0
    if op == "<=":
        return _compare(left, right) <= 0
    if op == ">":
        return _compare(left, right) > 0
    if op == "<":
        return _compare(left, right) < 0
    if op == "~=":
        # Compatible release: ~=2.3 → >=2.3,<3.0; ~=2.3.1 → >=2.3.1,<2.4.
        if len(right) < 2:
            return None
        upper = right[:-2] + (right[-2] + 1,)
        return _compare(left, right) >= 0 and _compare(left, upper) < 0
    return None  # pragma: no cover - _split_specifier only yields known ops


def satisfies(detected: Any, specifier: Any) -> bool | None:
    """Does *detected* satisfy *specifier*? None means UNVERIFIED.

    Comma conjunctions: any False → False; otherwise any None → None;
    all True → True. Never raises for malformed input.
    """
    if detected is None or specifier is None:
        return None
    detected_text = str(detected).strip()
    specifier_text = str(specifier).strip()
    if not detected_text or not specifier_text:
        return None
    verdicts: list[bool | None] = []
    for part in specifier_text.split(","):
        part = part.strip()
        if not part:
            continue
        op, spec = _split_specifier(part)
        verdict = _satisfies_one(detected_text, op, spec)
        if verdict is False:
            return False
        verdicts.append(verdict)
    if not verdicts:
        return None
    if any(verdict is None for verdict in verdicts):
        return None
    return all(verdicts)
