"""Tests for the experiment configuration loader and command builder."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from caasi.core import experiment
from caasi.core.config import Config


def _write_config(tmp_path, text: str):
    path = tmp_path / "experiment.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_minimal(tmp_path):
    path = _write_config(tmp_path, "backend: python\nscript: main.py\n")
    exp = experiment.load_experiment(path)
    assert exp.name == "experiment"
    assert exp.backend == "python"
    assert exp.script == "main.py"
    assert exp.args == []
    assert exp.env == {}
    assert exp.headless is True
    assert exp.script_path == (tmp_path / "main.py").resolve()
    assert exp.work_dir == tmp_path.resolve()


def test_load_full(tmp_path):
    path = _write_config(
        tmp_path,
        "name: demo\n"
        "backend: sim\n"
        "script: train.py\n"
        "args: ['--steps', '10']\n"
        "env:\n  FOO: bar\n"
        "headless: false\n"
        "cwd: /tmp\n",
    )
    exp = experiment.load_experiment(path)
    assert exp.name == "demo"
    assert exp.backend == "sim"
    assert exp.args == ["--steps", "10"]
    assert exp.env == {"FOO": "bar"}
    assert exp.headless is False
    assert exp.work_dir == Path("/tmp")


def test_missing_file(tmp_path):
    with pytest.raises(experiment.ExperimentError, match="not found"):
        experiment.load_experiment(tmp_path / "nope.yaml")


def test_invalid_yaml(tmp_path):
    path = _write_config(tmp_path, "backend: [unclosed")
    with pytest.raises(experiment.ExperimentError, match="invalid YAML"):
        experiment.load_experiment(path)


def test_not_a_mapping(tmp_path):
    path = _write_config(tmp_path, "- just\n- a list\n")
    with pytest.raises(experiment.ExperimentError, match="mapping"):
        experiment.load_experiment(path)


def test_unknown_backend(tmp_path):
    path = _write_config(tmp_path, "backend: gazebo\nscript: a.py\n")
    with pytest.raises(experiment.ExperimentError, match="unknown backend"):
        experiment.load_experiment(path)


def test_missing_script(tmp_path):
    path = _write_config(tmp_path, "backend: python\n")
    with pytest.raises(experiment.ExperimentError, match="'script' is required"):
        experiment.load_experiment(path)


def test_bad_args(tmp_path):
    path = _write_config(tmp_path, "backend: python\nscript: a.py\nargs: nope\n")
    with pytest.raises(experiment.ExperimentError, match="'args' must be a list"):
        experiment.load_experiment(path)


def test_bad_env(tmp_path):
    path = _write_config(tmp_path, "backend: python\nscript: a.py\nenv: [1]\n")
    with pytest.raises(experiment.ExperimentError, match="'env' must be a mapping"):
        experiment.load_experiment(path)


def _python_experiment(tmp_path):
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")
    return experiment.load_experiment(
        _write_config(tmp_path, "name: demo\nbackend: python\nscript: main.py\nargs: ['--flag']\n")
    )


def test_build_command_python(tmp_path):
    exp = _python_experiment(tmp_path)
    command, env = experiment.build_command(exp, Config({}, []))
    assert command[0] == sys.executable
    assert command[1] == str(exp.script_path)
    assert command[2:] == ["--flag"]
    assert env["CAASI_EXPERIMENT"] == str(exp.config_path)


def test_build_command_extra_args(tmp_path):
    exp = _python_experiment(tmp_path)
    command, _ = experiment.build_command(exp, Config({}, []), extra_args=["--more", "1"])
    assert command[-2:] == ["--more", "1"]


def test_build_command_python_override(tmp_path):
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    exp = experiment.load_experiment(
        _write_config(tmp_path, "backend: python\nscript: main.py\npython: /custom/py\n")
    )
    command, _ = experiment.build_command(exp, Config({}, []))
    assert command[0] == "/custom/py"


def test_build_command_sim_missing_tool(tmp_path):
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    exp = experiment.load_experiment(
        _write_config(tmp_path, "backend: sim\nscript: main.py\n")
    )
    with pytest.raises(experiment.ExperimentError, match="isaacsim"):
        experiment.build_command(exp, Config({}, []))


def test_build_command_lab_missing_tool(tmp_path):
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    exp = experiment.load_experiment(
        _write_config(tmp_path, "backend: lab\nscript: main.py\n")
    )
    with pytest.raises(experiment.ExperimentError, match="isaaclab"):
        experiment.build_command(exp, Config({}, []))


def _config_with_tool(tool: str, path) -> Config:
    cfg = Config({}, [])
    cfg.set(f"tools.{tool}.default", "1.0")
    cfg.set(f'tools.{tool}.versions."1.0".path', str(path))
    return cfg


def test_build_command_sim_launcher(tmp_path):
    simdir = tmp_path / "sim"
    simdir.mkdir()
    launcher = simdir / "python.sh"
    launcher.write_text("#!/bin/sh\n")
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    exp = experiment.load_experiment(
        _write_config(tmp_path, "backend: sim\nscript: main.py\n")
    )
    command, env = experiment.build_command(exp, _config_with_tool("isaacsim", simdir))
    assert command[0] == str(launcher)
    assert command[1] == str(exp.script_path)
    assert env["ISAACSIM_PATH"] == str(simdir)


def test_build_command_sim_launcher_missing(tmp_path):
    simdir = tmp_path / "sim"
    simdir.mkdir()
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    exp = experiment.load_experiment(
        _write_config(tmp_path, "backend: sim\nscript: main.py\n")
    )
    with pytest.raises(experiment.ExperimentError, match="does not exist"):
        experiment.build_command(exp, _config_with_tool("isaacsim", simdir))


def test_build_command_lab_launcher(tmp_path):
    labdir = tmp_path / "lab"
    labdir.mkdir()
    launcher = labdir / "isaaclab.sh"
    launcher.write_text("#!/bin/sh\n")
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    exp = experiment.load_experiment(
        _write_config(tmp_path, "backend: lab\nscript: main.py\nargs: ['--num_envs', '2']\n")
    )
    command, env = experiment.build_command(exp, _config_with_tool("isaaclab", labdir))
    assert command[:2] == [str(launcher), "-p"]
    assert command[2] == str(exp.script_path)
    assert command[3:] == ["--num_envs", "2"]
    assert env["ISAACLAB_PATH"] == str(labdir)
