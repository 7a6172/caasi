"""Tests for `isaac version` and `isaac info`."""

from __future__ import annotations

import json

from caasi import __version__
from caasi.cli.main import app


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
