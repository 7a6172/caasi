"""Tests for the `caasi container` commands (fake docker, no daemon needed)."""

from __future__ import annotations

import json
import os
import textwrap
import time

import pytest
import yaml

from caasi.cli.main import app
from caasi.core import containers as containers_core

FAKE_DOCKER = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    cmd="$1"; shift || true
    case "$cmd" in
      info)
        echo "Runtimes: io.containerd.runc.v2 {nvidia_runtime} runc"
        exit {info_rc};;
      image)
        sub="$1"; shift || true
        if [ "$sub" = "ls" ]; then
          echo "nvcr.io/nvidia/isaac-sim:5.1.0"
          echo "nvcr.io/nvidia/isaac-lab:2.2.0"
          echo "ubuntu:22.04"
          echo "<none>:<none>"
        fi
        exit 0;;
      run)
        echo "container started for $*"
        exit 0;;
    esac
    echo "unknown command" >&2
    exit 1
    """
)


@pytest.fixture
def fake_docker(tmp_path, monkeypatch):
    """A fake docker on PATH with a responding daemon and NVIDIA runtime."""
    return _make_fake_docker(tmp_path, monkeypatch, nvidia_runtime="nvidia", info_rc=0)


def _make_fake_docker(tmp_path, monkeypatch, *, nvidia_runtime, info_rc):
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "docker"
    script.write_text(
        FAKE_DOCKER.format(nvidia_runtime=nvidia_runtime, info_rc=info_rc),
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return script


def configure_runs(tmp_path, monkeypatch):
    cfg_file = tmp_path / "caasi-test.yaml"
    cfg_file.write_text(
        yaml.safe_dump({"paths": {"runs": str(tmp_path / "runs")}}), encoding="utf-8"
    )
    monkeypatch.setenv("CAASI_CONFIG", str(cfg_file))
    return tmp_path / "runs"


def wait_for_run(runs_base, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if runs_base.is_dir():
            for run_dir in runs_base.glob("*"):
                if (run_dir / "exit_code").is_file():
                    return run_dir
        time.sleep(0.05)
    raise AssertionError("run did not finish in time")


def test_container_list(runner, fake_docker):
    result = runner.invoke(app, ["container", "list", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["tool"] == str(fake_docker)
    assert "nvcr.io/nvidia/isaac-sim" in data["known"]
    assert data["local"] == [
        "nvcr.io/nvidia/isaac-sim:5.1.0",
        "nvcr.io/nvidia/isaac-lab:2.2.0",
    ]

    result = runner.invoke(app, ["container", "list"])
    assert result.exit_code == 0
    assert "Known images" in result.output
    assert "nvcr.io/nvidia/isaac-sim:5.1.0" in result.output
    assert "ubuntu:22.04" not in result.output


def test_container_list_without_tool(runner, monkeypatch):
    monkeypatch.setattr(containers_core, "find_container_tool", lambda: None)
    result = runner.invoke(app, ["container", "list", "--json"])
    data = json.loads(result.output)
    assert data["tool"] is None and data["local"] == []

    result = runner.invoke(app, ["container", "list"])
    assert result.exit_code == 0
    assert "No container tool found" in result.output


def test_container_check_pass(runner, fake_docker):
    result = runner.invoke(app, ["container", "check", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["ok"] is True
    assert [check["check"] for check in data["checks"]] == ["tool", "daemon", "nvidia-runtime"]

    result = runner.invoke(app, ["container", "check"])
    assert result.exit_code == 0
    assert "Container stack is ready" in result.output


def test_container_check_no_daemon(runner, tmp_path, monkeypatch):
    _make_fake_docker(tmp_path, monkeypatch, nvidia_runtime="nvidia", info_rc=1)
    result = runner.invoke(app, ["container", "check", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["checks"][0]["ok"] is True
    assert data["checks"][1]["ok"] is False
    assert data["checks"][2]["ok"] is False


def test_container_check_no_nvidia(runner, tmp_path, monkeypatch):
    _make_fake_docker(tmp_path, monkeypatch, nvidia_runtime="", info_rc=0)
    result = runner.invoke(app, ["container", "check"])
    assert result.exit_code == 1
    assert "nvidia-container-toolkit" in result.output


def test_container_check_without_tool(runner, monkeypatch):
    monkeypatch.setattr(containers_core, "find_container_tool", lambda: None)
    result = runner.invoke(app, ["container", "check", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["checks"][0]["detail"] == "No container tool found; install Docker or Podman first."


def test_container_run_dry_run(runner, fake_docker):
    result = runner.invoke(
        app,
        [
            "container", "run", "nvcr.io/nvidia/isaac-sim:5.1.0",
            "--dry-run", "python.sh", "train.py", "--steps", "10",
        ],
    )
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert (
        "run --rm --gpus all nvcr.io/nvidia/isaac-sim:5.1.0 python.sh train.py --steps 10"
        in result.output
    )

    result = runner.invoke(
        app, ["container", "run", "img:1", "--gpus", "", "--dry-run", "bash"]
    )
    assert "--gpus" not in result.output


def test_container_run_tracked(runner, fake_docker, tmp_path, monkeypatch):
    runs_base = configure_runs(tmp_path, monkeypatch)
    result = runner.invoke(
        app, ["container", "run", "nvcr.io/nvidia/isaac-sim:5.1.0", "--json", "python.sh"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["kind"] == "container" and data["backend"] == "container"
    assert data["name"] == "isaac-sim-5.1.0"

    run_dir = wait_for_run(runs_base)
    assert (run_dir / "exit_code").read_text().strip() == "0"
    assert "container started" in (run_dir / "stdout.log").read_text()


def test_container_run_without_tool(runner, monkeypatch):
    monkeypatch.setattr(containers_core, "find_container_tool", lambda: None)
    result = runner.invoke(app, ["container", "run", "img:1"])
    assert result.exit_code == 1
    assert "No container tool found" in result.output


def test_container_status(runner, fake_docker):
    result = runner.invoke(app, ["container", "status", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["tool"] == str(fake_docker)
    assert data["daemon"] is True
    assert data["nvidia_runtime"] is True
    assert data["ready"] is True
    assert data["known"] == ["nvcr.io/nvidia/isaac-sim", "nvcr.io/nvidia/isaac-lab"]
    assert data["local"] == [
        "nvcr.io/nvidia/isaac-sim:5.1.0",
        "nvcr.io/nvidia/isaac-lab:2.2.0",
    ]

    result = runner.invoke(app, ["container", "status"])
    assert result.exit_code == 0
    assert "NVIDIA runtime available" in result.output
    assert "nvcr.io/nvidia/isaac-sim:5.1.0" in result.output


def test_container_status_without_daemon(runner, tmp_path, monkeypatch):
    _make_fake_docker(tmp_path, monkeypatch, nvidia_runtime="nvidia", info_rc=1)
    result = runner.invoke(app, ["container", "status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["daemon"] is False and data["ready"] is False
    assert data["nvidia_runtime"] is False and data["local"] == []

    result = runner.invoke(app, ["container", "status"])
    assert "daemon is not responding" in result.output


def test_container_status_without_tool(runner, monkeypatch):
    monkeypatch.setattr(containers_core, "find_container_tool", lambda: None)
    result = runner.invoke(app, ["container", "status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["tool"] is None and data["ready"] is False

    result = runner.invoke(app, ["container", "status"])
    assert result.exit_code == 0
    assert "No container tool found" in result.output


def test_container_doctor(runner, fake_docker, fake_nvidia_smi):
    result = runner.invoke(app, ["container", "doctor", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["group"] == "container"
    assert data["sections"] == ["containers", "nvidia"]
    rows = {check["name"]: check for check in data["checks"]}
    assert "NVIDIA driver" in rows
    assert rows["GPU in containers"]["status"] == "ok"
    assert rows["GPU in containers"]["hint"] == (
        "Expose the GPU with: caasi container run --gpus all <image>"
    )


def test_container_doctor_without_nvidia_runtime(runner, tmp_path, monkeypatch, fake_nvidia_smi):
    _make_fake_docker(tmp_path, monkeypatch, nvidia_runtime="", info_rc=0)
    result = runner.invoke(app, ["container", "doctor", "--json"])
    assert result.exit_code == 0, result.output
    rows = {check["name"]: check for check in json.loads(result.output)["checks"]}
    assert rows["GPU in containers"]["status"] == "warn"
    assert "nvidia-container-toolkit" in rows["GPU in containers"]["detail"]
    assert "nvidia-container-toolkit" in rows["GPU in containers"]["hint"]


def test_container_doctor_without_tool(runner, monkeypatch, fake_nvidia_smi):
    monkeypatch.setattr(containers_core, "find_container_tool", lambda: None)
    result = runner.invoke(app, ["container", "doctor", "--json"])
    assert result.exit_code == 0, result.output
    rows = {check["name"]: check for check in json.loads(result.output)["checks"]}
    assert rows["GPU in containers"]["status"] == "skip"
    assert rows["GPU in containers"]["detail"] == (
        "No container tool found; install Docker or Podman first."
    )

    result = runner.invoke(app, ["container", "doctor"])
    assert "GPU in containers" in result.output
