"""Tests for the project component catalog (core/components.py)."""

from __future__ import annotations

from caasi.core import components


def test_catalog_is_complete():
    expected = {
        "isaac_sim",
        "isaac_lab",
        "ros2",
        "nav2",
        "moveit",
        "robot",
        "navigation",
        "manipulation",
    }
    assert expected == set(components.COMPONENTS)


def test_every_component_has_key_cli_and_dirs():
    for key, comp in components.COMPONENTS.items():
        assert comp.key == key
        assert comp.cli
        assert isinstance(comp.dirs, tuple)
        assert comp.dirs, f"{key} must create at least one directory"


def test_normalize_dotted_and_underscore_are_equivalent():
    assert components.normalize("isaac.lab") == "isaac_lab"
    assert components.normalize("isaac_lab") == "isaac_lab"
    assert components.normalize("ISAAC.SIM") == "isaac_sim"
    # cli form round-trips through get()
    assert components.get("isaac.lab") is components.COMPONENTS["isaac_lab"]
    assert components.get("isaac_lab") is components.COMPONENTS["isaac_lab"]


def test_normalize_unknown_returns_none():
    assert components.normalize("bogus") is None
    assert components.normalize("") is None
    assert components.get("nope.nope") is None


def test_dirs_for_and_requires_for():
    assert "isaac/lab/tasks" in components.dirs_for("isaac.lab")
    assert components.requires_for("isaac_sim") == {"isaac_sim": {"version": ">=5.0"}}
    # unknown -> empty
    assert components.dirs_for("bogus") == ()
    assert components.requires_for("bogus") == {}


def test_base_dirs_include_the_internal_and_definition_dirs():
    for sub in ("robots", "scenes", "tasks", "experiments", "datasets", "runs", ".caasi"):
        assert sub in components.BASE_DIRS


def test_all_returns_every_component():
    assert len(components.all()) == len(components.COMPONENTS)
