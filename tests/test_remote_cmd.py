"""Tests for the `caasi remote` commands (fake ssh, no network needed)."""

from __future__ import annotations

import json
import os
import time

import pytest
import yaml

from caasi.cli.main import app


def configure_remotes(tmp_path, monkeypatch):
    identity = tmp_path / "fake_key"
    identity.write_text("key", encoding="utf-8")
    cfg_file = tmp_path / "caasi-test.yaml"
    cfg_file.write_text(
        yaml.safe_dump(
            {
                "remotes": {
                    "gpu-box": {
                        "host": "10.0.0.5",
                        "user": "robot",
                        "port": 2222,
                        "identity": str(identity),
                        "path": "~/experiments",
                    },
                    "bare": {"host": "10.0.0.6"},
                },
                "paths": {"runs": str(tmp_path / "runs")},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CAASI_CONFIG", str(cfg_file))
    return tmp_path / "runs", identity


@pytest.fixture
def fake_ssh(tmp_path, monkeypatch):
    """A fake ssh on PATH that records its arguments and exits 0."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    marker = tmp_path / "ssh-args.txt"
    script = bin_dir / "ssh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$@" > "{marker}"\n'
        "echo ok-ssh\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return marker


def wait_for_run(runs_base, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if runs_base.is_dir():
            for run_dir in runs_base.glob("*"):
                if (run_dir / "exit_code").is_file():
                    return run_dir
        time.sleep(0.05)
    raise AssertionError("run did not finish in time")


def test_remote_list(runner, tmp_path, monkeypatch):
    _runs, _identity = configure_remotes(tmp_path, monkeypatch)
    result = runner.invoke(app, ["remote", "list", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    by_name = {m["name"]: m for m in data}
    assert sorted(by_name) == ["bare", "gpu-box"]
    assert by_name["gpu-box"]["host"] == "10.0.0.5"
    assert by_name["gpu-box"]["port"] == 2222

    result = runner.invoke(app, ["remote", "list"])
    assert result.exit_code == 0
    assert "robot@10.0.0.5:2222" in result.output
    assert "~/experiments" in result.output


def test_remote_list_empty(runner):
    result = runner.invoke(app, ["remote", "list"])
    assert result.exit_code == 0
    assert "No remote machines configured" in result.output


def test_remote_connect_dry_run(runner, tmp_path, monkeypatch):
    _runs, identity = configure_remotes(tmp_path, monkeypatch)
    result = runner.invoke(app, ["remote", "connect", "gpu-box", "--dry-run"])
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert f"ssh -p 2222 -i {identity} robot@10.0.0.5" in result.output

    result = runner.invoke(
        app, ["remote", "connect", "gpu", "--dry-run", "--command", "nvidia-smi"]
    )
    assert result.exit_code == 0  # unique prefix resolves to gpu-box
    assert "nvidia-smi" in result.output


def test_remote_connect_command(runner, tmp_path, monkeypatch, fake_ssh):
    _runs, _identity = configure_remotes(tmp_path, monkeypatch)
    result = runner.invoke(app, ["remote", "connect", "gpu-box", "--command", "nvidia-smi"])
    assert result.exit_code == 0, result.output
    assert "ok-ssh" in result.output
    assert fake_ssh.read_text().strip() == (
        "-p 2222 -i {} robot@10.0.0.5 nvidia-smi".format(_identity)
    )


def test_remote_connect_not_found(runner, tmp_path, monkeypatch):
    _runs, _identity = configure_remotes(tmp_path, monkeypatch)
    result = runner.invoke(app, ["remote", "connect", "ghost"])
    assert result.exit_code == 1
    assert "No remote machine matching 'ghost'" in result.output
    assert "bare, gpu-box" in result.output


def test_remote_run_tracked(runner, tmp_path, monkeypatch, fake_ssh):
    runs_base, identity = configure_remotes(tmp_path, monkeypatch)
    result = runner.invoke(
        app,
        ["remote", "run", "gpu-box", "python", "train.py", "--steps", "10", "--json"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["kind"] == "remote" and data["backend"] == "ssh"
    assert data["name"] == "gpu-box-python"

    run_dir = wait_for_run(runs_base)
    assert (run_dir / "exit_code").read_text().strip() == "0"
    stdout = (run_dir / "stdout.log").read_text()
    assert "ok-ssh" in stdout
    ssh_args = fake_ssh.read_text().strip()
    assert ssh_args.startswith(f"-p 2222 -i {identity} robot@10.0.0.5")
    assert "cd ~/experiments && python train.py --steps 10" in ssh_args


def test_remote_run_dry_run(runner, tmp_path, monkeypatch):
    configure_remotes(tmp_path, monkeypatch)
    result = runner.invoke(
        app, ["remote", "run", "bare", "python", "train.py", "--dry-run"]
    )
    assert result.exit_code == 0
    assert "Dry run" in result.output
    # 'bare' has no user/port/path configured
    assert "ssh 10.0.0.6 python train.py" in result.output


def test_remote_run_requires_command(runner, tmp_path, monkeypatch):
    configure_remotes(tmp_path, monkeypatch)
    result = runner.invoke(app, ["remote", "run", "gpu-box"])
    assert result.exit_code == 1
    assert "Provide a command to run" in result.output
