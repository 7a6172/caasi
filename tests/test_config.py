"""Tests for `isaac config` and the configuration/tool-registry engine."""

from __future__ import annotations

import json

from caasi.cli.main import app
from caasi.core.config import Config, global_config_path

from .conftest import all_output


def _write_global(text: str) -> None:
    path = global_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_show_defaults(runner):
    result = runner.invoke(app, ["config", "show", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["language"] == "en"
    assert data["paths"]["runs"] == "~/.caasi/runs"
    assert data["tools"] == {}


def test_set_get_roundtrip(runner):
    result = runner.invoke(app, ["config", "set", "defaults.output", "json"])
    assert result.exit_code == 0
    assert global_config_path().is_file()

    result = runner.invoke(app, ["config", "get", "defaults.output"])
    assert result.exit_code == 0
    assert result.output.strip() == "json"


def test_get_missing_key(runner):
    result = runner.invoke(app, ["config", "get", "does.not.exist"])
    assert result.exit_code == 1


def test_precedence_chain(runner, tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)

    _write_global("defaults:\n  output: global\n")
    (project / "caasi.yaml").write_text("defaults:\n  output: project\n", encoding="utf-8")

    result = runner.invoke(app, ["config", "get", "defaults.output"])
    assert result.output.strip() == "project"

    (project / "caasi.yaml").unlink()
    result = runner.invoke(app, ["config", "get", "defaults.output"])
    assert result.output.strip() == "global"

    env_file = tmp_path / "env.yaml"
    env_file.write_text("defaults:\n  output: envfile\n", encoding="utf-8")
    monkeypatch.setenv("CAASI_CONFIG", str(env_file))
    result = runner.invoke(app, ["config", "get", "defaults.output"])
    assert result.output.strip() == "envfile"

    flag_file = tmp_path / "flag.yaml"
    flag_file.write_text("defaults:\n  output: flagfile\n", encoding="utf-8")
    result = runner.invoke(app, ["--config", str(flag_file), "config", "get", "defaults.output"])
    assert result.output.strip() == "flagfile"


def test_config_path(runner):
    result = runner.invoke(app, ["config", "path"])
    assert result.exit_code == 0
    output = all_output(result)
    assert "CAASI_CONFIG" in output
    assert "caasi/config.yaml" in output


REGISTRY_YAML = """\
tools:
  isaacsim:
    default: "5.1"
    versions:
      "6.0":
        path: /opt/isaac-sim-6.0
      "5.1":
        path: /opt/isaac-sim-5.1
        python: /opt/isaac-sim-5.1/python.sh
"""


def test_tools_registry(runner, tmp_path):
    cfg_file = tmp_path / "tools.yaml"
    cfg_file.write_text(REGISTRY_YAML, encoding="utf-8")

    result = runner.invoke(app, ["--config", str(cfg_file), "config", "tools", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    sim = data["isaacsim"]
    assert sim["default"] == "5.1"
    assert set(sim["versions"]) == {"6.0", "5.1"}
    assert sim["resolved"]["version"] == "5.1"
    assert sim["resolved"]["path"] == "/opt/isaac-sim-5.1"
    assert sim["resolved"]["python"] == "/opt/isaac-sim-5.1/python.sh"


def test_tools_empty(runner):
    result = runner.invoke(app, ["config", "tools"])
    assert result.exit_code == 0
    assert "No tools are registered yet." in all_output(result)


def test_tools_float_default_coercion(runner, tmp_path):
    """`config set ... 6.0` stores a float; the registry must still resolve it."""
    cfg_file = tmp_path / "tools.yaml"
    cfg_file.write_text(REGISTRY_YAML, encoding="utf-8")

    result = runner.invoke(
        app, ["--config", str(cfg_file), "config", "set", "tools.isaacsim.default", "6.0"]
    )
    assert result.exit_code == 0

    result = runner.invoke(app, ["config", "tools", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["isaacsim"]["resolved"]["version"] == "6.0"
    assert data["isaacsim"]["resolved"]["path"] == "/opt/isaac-sim-6.0"


def test_quoted_dotted_keys(runner):
    """Version keys contain dots; quoting must keep them as one segment."""
    result = runner.invoke(
        app, ["config", "set", 'tools.isaacsim.versions."6.0".path', "/opt/isaac-sim-6.0"]
    )
    assert result.exit_code == 0
    result = runner.invoke(app, ["config", "get", 'tools.isaacsim.versions."6.0".path'])
    assert result.exit_code == 0
    assert result.output.strip() == "/opt/isaac-sim-6.0"


def test_resolve_tool_units():
    cfg = Config.load()
    cfg.set("tools.demo.path", "/opt/demo")
    resolved = cfg.resolve_tool("demo")
    assert resolved is not None
    assert resolved.version is None
    assert resolved.path == "/opt/demo"

    cfg.set(
        "tools.multi",
        {"versions": {"a": {"path": "/a"}, "b": {"path": "/b"}}},
    )
    resolved = cfg.resolve_tool("multi")
    assert resolved is not None and resolved.version == "a"  # first when no default

    resolved = cfg.resolve_tool("multi", version="b")
    assert resolved is not None and resolved.path == "/b"

    assert cfg.resolve_tool("multi", version="missing") is None
    assert cfg.resolve_tool("unknown-tool") is None
