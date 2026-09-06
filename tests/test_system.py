"""Tests for `isaac system` (Linux /proc based)."""

from __future__ import annotations

import json

from caasi.cli.main import app

from .conftest import all_output


def test_system_status_json(runner):
    result = runner.invoke(app, ["system", "status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    for key in (
        "os",
        "kernel",
        "arch",
        "cpu",
        "cores",
        "load",
        "ram_total_gib",
        "ram_available_gib",
        "gpu_count",
        "disk_free_home",
    ):
        assert key in data
    assert data["ram_total_gib"] > 0
    assert data["cores"] >= 1


def test_system_status_table(runner):
    result = runner.invoke(app, ["system", "status"])
    assert result.exit_code == 0
    assert all_output(result).strip()


def test_system_memory_json(runner):
    result = runner.invoke(app, ["system", "memory", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["total_gib"] > 0
    assert 0 <= data["available_gib"] <= data["total_gib"]
    assert "swap_total_gib" in data


def test_system_memory_table(runner):
    result = runner.invoke(app, ["system", "memory"])
    assert result.exit_code == 0
    assert "GiB" in all_output(result)


def test_system_processes_json(runner):
    result = runner.invoke(app, ["system", "processes", "--limit", "3", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert 0 < len(data) <= 3
    for row in data:
        assert {"pid", "user", "mem_percent", "rss", "command"} <= set(row)


def test_system_processes_table(runner):
    result = runner.invoke(app, ["system", "processes", "--limit", "2"])
    assert result.exit_code == 0
    assert all_output(result).strip()
