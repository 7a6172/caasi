"""Shared fixtures: isolated HOME/config environment and a fake nvidia-smi."""

from __future__ import annotations

import os
import stat
import textwrap

import pytest
from typer.testing import CliRunner

CLEAN_ENV_VARS = (
    "CAASI_CONFIG",
    "CAASI_LANG",
    "ISAACSIM_PATH",
    "ISAACLAB_PATH",
    "ROS_DISTRO",
    "RMW_IMPLEMENTATION",
    "CONDA_DEFAULT_ENV",
)


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Point HOME/XDG at temp dirs and clear tool-detection env vars."""
    home = tmp_path / "home"
    xdg = tmp_path / "xdg"
    home.mkdir()
    xdg.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    # Wide terminal so Rich tables are never truncated in tests.
    monkeypatch.setenv("COLUMNS", "200")
    for var in CLEAN_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    from caasi import state

    state.reset()
    yield tmp_path
    state.reset()


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def all_output(result) -> str:
    """Combined stdout/stderr across click versions."""
    out = result.output
    try:
        out += result.stderr
    except (ValueError, AttributeError):
        pass
    return out


FAKE_NVIDIA_SMI = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    # Fake nvidia-smi used by the test-suite.
    for arg in "$@"; do
      case "$arg" in
        --query-gpu=*)
          fields="${arg#--query-gpu=}"
          case "$fields" in
            index,name)
              echo "0, FakeGPU RTX 9090" ;;
            index,name,memory.total,driver_version)
              echo "0, FakeGPU RTX 9090, 24576, 580.99" ;;
            index,name,driver_version,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,power.draw)
              echo "0, FakeGPU RTX 9090, 580.99, 24576, 4096, 20480, 42, 55, 120.50" ;;
            index,name,uuid,serial,pci.bus_id,compute_cap,ecc.mode.current,driver_version)
              echo "0, FakeGPU RTX 9090, GPU-1234, 0123456789, 00000000:01:00.0, 8.6, Disabled, 580.99" ;;
            *)
              echo "0, FakeGPU RTX 9090" ;;
          esac
          exit 0 ;;
        --query-compute-apps=*)
          echo "GPU-1234, 4242, python, 1024"
          exit 0 ;;
      esac
    done
    echo "+-----------------------------------------+"
    echo "| NVIDIA-SMI 580.99    CUDA Version: 13.0 |"
    echo "+-----------------------------------------+"
    exit 0
    """
)


@pytest.fixture
def fake_nvidia_smi(tmp_path, monkeypatch):
    """Put a fake nvidia-smi first on PATH."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "nvidia-smi"
    script.write_text(FAKE_NVIDIA_SMI)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return bin_dir


@pytest.fixture
def no_nvidia_smi(tmp_path, monkeypatch):
    """PATH without nvidia-smi (keeps other binaries reachable)."""
    empty = tmp_path / "emptybin"
    empty.mkdir(exist_ok=True)
    keep = [
        entry
        for entry in os.environ.get("PATH", "").split(os.pathsep)
        if entry and not os.path.exists(os.path.join(entry, "nvidia-smi"))
    ]
    monkeypatch.setenv("PATH", os.pathsep.join([str(empty), *keep]))
