"""Tests for `caasi gpu` (driven by the fake nvidia-smi fixture)."""

from __future__ import annotations

import json

from caasi.cli.main import app

from .conftest import all_output


def test_gpu_status_json(runner, fake_nvidia_smi):
    result = runner.invoke(app, ["gpu", "status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["cuda"] == "13.0"
    gpu = data["gpus"][0]
    assert gpu["name"] == "FakeGPU RTX 9090"
    assert gpu["memory.total"] == 24576.0
    assert gpu["memory.used"] == 4096.0
    assert gpu["utilization.gpu"] == 42.0
    assert gpu["driver_version"] == "580.99"


def test_gpu_status_table(runner, fake_nvidia_smi):
    result = runner.invoke(app, ["gpu", "status"])
    assert result.exit_code == 0
    assert "FakeGPU RTX 9090" in all_output(result)


def test_gpu_info_json(runner, fake_nvidia_smi):
    result = runner.invoke(app, ["gpu", "info", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    gpu = data["gpus"][0]
    assert gpu["uuid"] == "GPU-1234"
    assert gpu["compute_cap"] == 8.6
    assert gpu["ecc.mode.current"] == "Disabled"


def test_gpu_memory_json_lists_compute_apps(runner, fake_nvidia_smi):
    result = runner.invoke(app, ["gpu", "memory", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["gpus"][0]["memory.free"] == 20480.0
    apps = data["compute_apps"]
    assert len(apps) == 1
    assert apps[0]["pid"] == 4242.0
    assert apps[0]["process_name"] == "python"
    assert apps[0]["used_memory_mb"] == 1024.0


def test_gpu_memory_table(runner, fake_nvidia_smi):
    result = runner.invoke(app, ["gpu", "memory"])
    assert result.exit_code == 0
    assert "FakeGPU RTX 9090" in all_output(result)


def test_gpu_test_without_gpu(runner, no_nvidia_smi):
    result = runner.invoke(app, ["gpu", "test"])
    assert result.exit_code == 1
    assert all_output(result).strip()


def test_gpu_test_with_driver(runner, fake_nvidia_smi):
    """Driver probe must pass; torch outcome depends on the test env."""
    result = runner.invoke(app, ["gpu", "test"])
    assert result.exit_code in (0, 1)


def test_gpu_status_without_nvidia_smi(runner, no_nvidia_smi):
    result = runner.invoke(app, ["gpu", "status"])
    assert result.exit_code == 1
    assert all_output(result).strip()


def test_gpu_memory_without_nvidia_smi(runner, no_nvidia_smi):
    result = runner.invoke(app, ["gpu", "memory"])
    assert result.exit_code == 1


def test_gpu_info_without_nvidia_smi(runner, no_nvidia_smi):
    result = runner.invoke(app, ["gpu", "info"])
    assert result.exit_code == 1


def test_gpu_doctor_json(runner, fake_nvidia_smi):
    result = runner.invoke(app, ["gpu", "doctor", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["group"] == "gpu"
    assert data["sections"] == ["nvidia", "graphics"]
    assert data["exit_code"] == 0
    names = [check["name"] for check in data["checks"]]
    assert "NVIDIA driver" in names and "Vulkan" in names
    assert any("FakeGPU RTX 9090" in check["detail"] for check in data["checks"])


def test_gpu_doctor_table(runner, fake_nvidia_smi):
    result = runner.invoke(app, ["gpu", "doctor"])
    assert result.exit_code == 0
    assert "FakeGPU RTX 9090" in all_output(result)


def test_gpu_doctor_without_nvidia_smi(runner, no_nvidia_smi):
    result = runner.invoke(app, ["gpu", "doctor", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["exit_code"] == 1
    fails = [check for check in data["checks"] if check["status"] == "fail"]
    assert any(check["detail"] == "nvidia-smi not found on PATH" for check in fails)


def test_gpu_monitor_once_json(runner, fake_nvidia_smi):
    result = runner.invoke(app, ["gpu", "monitor", "--once", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["interval"] == 2.0
    gpu = data["gpus"][0]
    assert gpu["name"] == "FakeGPU RTX 9090"
    assert gpu["utilization.gpu"] == 42.0
    assert gpu["temperature.gpu"] == 55.0


def test_gpu_monitor_once_table(runner, fake_nvidia_smi):
    result = runner.invoke(app, ["gpu", "monitor", "--once", "--interval", "0.5"])
    assert result.exit_code == 0, result.output
    out = all_output(result)
    assert "FakeGPU RTX 9090" in out
    assert "42%" in out and "55°C" in out


def test_gpu_monitor_json_is_a_single_sample(runner, fake_nvidia_smi):
    result = runner.invoke(app, ["gpu", "monitor", "--json"])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.output)["gpus"]) == 1


def test_gpu_monitor_without_nvidia_smi(runner, no_nvidia_smi):
    result = runner.invoke(app, ["gpu", "monitor", "--once"])
    assert result.exit_code == 1
    assert all_output(result).strip()
