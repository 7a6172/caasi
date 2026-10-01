"""Tests for the `caasi sim` commands."""

from __future__ import annotations

import json
import time

from caasi import state
from caasi.cli.main import app
from caasi.core import runs

from .conftest import all_output

FINISHED = (runs.TERMINAL_OK, runs.TERMINAL_FAIL)


def _make_experiment(tmp_path, backend: str = "python", name: str = "demo"):
    (tmp_path / "main.py").write_text("print('experiment-work')\n", encoding="utf-8")
    config = tmp_path / "experiment.yaml"
    config.write_text(
        f"name: {name}\nbackend: {backend}\nscript: main.py\nargs: ['--flag']\n",
        encoding="utf-8",
    )
    return config


def _wait_finished(record, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if runs.effective_status(record) in FINISHED:
            return
        time.sleep(0.05)


def test_sim_run_dry_run_starts_nothing(runner, tmp_path):
    config = _make_experiment(tmp_path)
    result = runner.invoke(app, ["sim", "run", str(config), "--dry-run"])
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert "main.py" in result.output
    assert "--flag" in result.output
    assert runs.list_runs(state.cfg()) == []


def test_sim_run_dry_run_shows_backend_note(runner, tmp_path):
    config = _make_experiment(tmp_path, backend="python")
    result = runner.invoke(app, ["sim", "run", str(config), "--dry-run"])
    assert result.exit_code == 0
    assert "backend is 'python'" in result.output


def test_sim_run_missing_config(runner):
    result = runner.invoke(app, ["sim", "run", "nope.yaml"])
    assert result.exit_code == 1
    assert "not found" in all_output(result)


def test_sim_run_missing_backend_tool(runner, tmp_path):
    config = _make_experiment(tmp_path, backend="sim")
    result = runner.invoke(app, ["sim", "run", str(config)])
    assert result.exit_code == 1
    assert "isaacsim" in all_output(result)


def test_sim_run_starts_and_finishes(runner, tmp_path):
    config = _make_experiment(tmp_path)
    result = runner.invoke(app, ["sim", "run", str(config), "--name", "demo-run"])
    assert result.exit_code == 0
    assert "started in the background" in result.output
    assert "caasi logs" in result.output

    record = runs.find_run(state.cfg(), "demo-run")
    assert record is not None
    assert record.kind == "experiment"
    _wait_finished(record)
    assert runs.effective_status(record) == runs.TERMINAL_OK
    assert "experiment-work" in (record.directory / "stdout.log").read_text()


def test_sim_check_fails_without_isaac(runner):
    result = runner.invoke(app, ["sim", "check"])
    assert result.exit_code == 3  # Check Contract: incompatible → exit 3
    assert "Isaac Sim" in result.output


def test_sim_folded_verbs_removed(runner):
    # v0.3.0 IA: sim status/stop/pause/resume/logs fold into `run --backend sim`.
    result = runner.invoke(app, ["sim", "--help"])
    assert result.exit_code == 0
    for verb in ("status", "stop", "pause", "resume", "logs"):
        assert verb not in result.output
        assert runner.invoke(app, ["sim", verb, "latest"]).exit_code != 0


def test_sim_run_json_flag_prints_pure_json(runner, tmp_path):
    config = _make_experiment(tmp_path, name="json-demo")
    result = runner.invoke(app, ["sim", "run", str(config), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "json-demo"
    assert data["backend"] == "python"
    assert data["kind"] == "experiment"
    record = runs.find_run(state.cfg(), "json-demo")
    _wait_finished(record)
    assert runs.effective_status(record) == runs.TERMINAL_OK


def test_sim_extensions_lists_tree(runner, fake_isaac_tree):
    result = runner.invoke(app, ["sim", "extensions", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert {entry["name"] for entry in data} == {
        "omni.replicator.core",
        "omni.importer.urdf",
        "omni.physx",
    }
    sources = {entry["name"]: entry["source"] for entry in data}
    assert sources["omni.physx"] == "extsPhysics"
    assert sources["omni.replicator.core"] == "exts"
    assert all(entry["enabled"] is False for entry in data)


def test_sim_extensions_table(runner, fake_isaac_tree):
    result = runner.invoke(app, ["sim", "extensions"])
    assert result.exit_code == 0
    assert "omni.replicator.core" in result.output


def test_sim_extensions_enabled_filter(runner, fake_isaac_tree):
    toml = fake_isaac_tree / "exts" / "omni.replicator.core" / "config" / "extension.toml"
    toml.write_text(
        '[package]\nname = "omni.replicator.core"\n\n[core]\npreload = true\n',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["sim", "extensions", "--enabled", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert [entry["name"] for entry in data] == ["omni.replicator.core"]
    assert data[0]["enabled"] is True


def test_sim_extensions_user_dir(runner, fake_isaac_tree):
    result = runner.invoke(app, ["sim", "extensions", "--user"])
    assert result.exit_code == 0
    assert "No extensions found." in result.output
    result = runner.invoke(app, ["sim", "extensions", "--user", "--json"])
    assert json.loads(result.output) == []


def test_sim_extensions_without_tool(runner):
    result = runner.invoke(app, ["sim", "extensions"])
    assert result.exit_code == 1
    assert "not registered" in all_output(result)


def test_sim_headless_dry_run_forces_flags(runner, tmp_path, fake_isaac_tree):
    config = _make_experiment(tmp_path, backend="sim")
    result = runner.invoke(app, ["sim", "headless", str(config), "--dry-run"])
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert "--headless" in result.output
    assert "--no-window" in result.output
    assert runs.list_runs(state.cfg()) == []


def test_sim_headless_starts_tracked_run(runner, tmp_path):
    (tmp_path / "main.py").write_text(
        "import sys\nprint(' '.join(sys.argv[1:]))\n", encoding="utf-8"
    )
    config = tmp_path / "experiment.yaml"
    config.write_text(
        "name: headless-demo\nbackend: python\nscript: main.py\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["sim", "headless", str(config), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["backend"] == "python"
    record = runs.find_run(state.cfg(), "headless-demo")
    assert record.extra["headless"] is True
    _wait_finished(record)
    assert runs.effective_status(record) == runs.TERMINAL_OK
    stdout = (record.directory / "stdout.log").read_text()
    assert "--headless" in stdout
    assert "--no-window" in stdout
