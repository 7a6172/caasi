"""Tests for `caasi version`, `caasi info` and `caasi help`."""

from __future__ import annotations

import json

import typer

from caasi import __version__
from caasi.cli.main import CORE_COMMANDS, HELP_PANELS, app

from .conftest import all_output


def test_version(runner):
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert f"caasi {__version__}" in result.output


def test_version_json(runner):
    result = runner.invoke(app, ["version", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {"name": "caasi", "version": __version__}


def test_root_version_flag(runner):
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_info(runner):
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0
    assert "Caasi" in result.output


def test_info_json(runner):
    result = runner.invoke(app, ["info", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert set(data) == {"cli", "config", "tools", "ecosystem"}
    assert data["cli"]["version"] == __version__
    assert data["cli"]["python"]


def test_help(runner):
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    assert "Usage: caasi [OPTIONS] COMMAND [ARGS]..." in result.output
    assert "--verbose" in result.output
    assert "help" in result.output


def test_help_group(runner):
    result = runner.invoke(app, ["help", "gpu"])
    assert result.exit_code == 0
    assert "Usage: caasi gpu [OPTIONS] COMMAND [ARGS]..." in result.output


def test_help_subcommand(runner):
    result = runner.invoke(app, ["help", "gpu", "status"])
    assert result.exit_code == 0
    assert "Usage: caasi gpu status [OPTIONS]" in result.output


def test_help_unknown_command(runner):
    result = runner.invoke(app, ["help", "nope"])
    assert result.exit_code == 1
    assert "Unknown command 'nope'" in all_output(result)


def test_help_leaf_has_no_subcommands(runner):
    result = runner.invoke(app, ["help", "info", "extra"])
    assert result.exit_code == 1
    assert "'info' has no subcommands" in all_output(result)


def _root_listing() -> list[str]:
    group = typer.main.get_command(app)
    return group.list_commands(typer.Context(group, info_name="caasi"))


def test_help_groups_root_commands(runner):
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    for panel in ("Start here", "Projects & runs", "GPU-accelerated"):
        assert panel in result.output


def test_help_panels_cover_every_root_command():
    registered = set(typer.main.get_command(app).commands)
    panelled = [name for names in HELP_PANELS.values() for name in names]
    assert set(panelled) == registered
    assert len(panelled) == len(registered)
    for names in HELP_PANELS.values():
        assert list(names) == sorted(names)


def test_help_order_alpha(runner, monkeypatch):
    monkeypatch.setenv("CAASI_HELP_ORDER", "alpha")
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Start here" not in result.output
    assert _root_listing() == sorted(_root_listing())


def test_help_order_core(runner, monkeypatch):
    monkeypatch.setenv("CAASI_HELP_ORDER", "core")
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    assert "Start here" not in result.output
    listing = _root_listing()
    assert listing[: len(CORE_COMMANDS)] == list(CORE_COMMANDS)
    rest = listing[len(CORE_COMMANDS) :]
    assert rest == sorted(rest)


def test_help_order_unknown_value_is_ignored(runner, monkeypatch):
    monkeypatch.setenv("CAASI_HELP_ORDER", "nope")
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    assert "Start here" in result.output


def test_help_order_env_beats_config(runner, monkeypatch, tmp_path):
    config = tmp_path / "caasi.yaml"
    config.write_text("help_order: alpha\n", encoding="utf-8")
    monkeypatch.setenv("CAASI_CONFIG", str(config))
    monkeypatch.setenv("CAASI_HELP_ORDER", "grouped")
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    assert "Start here" in result.output


def test_help_order_from_config(runner, monkeypatch, tmp_path):
    config = tmp_path / "caasi.yaml"
    config.write_text("help_order: alpha\n", encoding="utf-8")
    monkeypatch.setenv("CAASI_CONFIG", str(config))
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    assert "Start here" not in result.output
    assert _root_listing() == sorted(_root_listing())


def test_subgroup_help_keeps_its_own_order(monkeypatch):
    monkeypatch.setenv("CAASI_HELP_ORDER", "alpha")
    root = typer.main.get_command(app)
    gpu = root.get_command(typer.Context(root, info_name="caasi"), "gpu")
    names = gpu.list_commands(typer.Context(gpu, info_name="caasi gpu"))
    assert names[0] == "status"
    assert names != sorted(names)
