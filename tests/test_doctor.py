"""Tests for `isaac doctor`."""

from __future__ import annotations

import json

from caasi.checks import SECTION_KEYS
from caasi.cli.main import app

from .conftest import all_output


def test_doctor_runs(runner):
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code in (0, 1)
    assert "Environment Diagnostics" in all_output(result)


def test_doctor_component_system(runner):
    result = runner.invoke(app, ["doctor", "--component", "system"])
    assert result.exit_code == 0
    assert "Kernel" in all_output(result)


def test_doctor_component_nvidia_with_fake(runner, fake_nvidia_smi):
    result = runner.invoke(app, ["doctor", "--component", "nvidia", "--verbose"])
    assert result.exit_code == 0
    output = all_output(result)
    assert "FakeGPU RTX 9090" in output
    assert "CUDA" in output


def test_doctor_component_nvidia_without_gpu(runner, no_nvidia_smi):
    result = runner.invoke(app, ["doctor", "--component", "nvidia"])
    assert result.exit_code == 1
    assert "nvidia-smi" in all_output(result)


def test_doctor_json(runner):
    result = runner.invoke(app, ["doctor", "--component", "system", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["checks"], "expected at least one check"
    assert data["exit_code"] == 0
    assert all(check["section"] == "system" for check in data["checks"])


def test_doctor_quiet(runner):
    result = runner.invoke(app, ["doctor", "--component", "system", "--quiet"])
    assert result.exit_code == 0
    assert result.output.strip() == ""


def test_doctor_unknown_component(runner):
    result = runner.invoke(app, ["doctor", "--component", "bogus"])
    assert result.exit_code == 1
    assert "Unknown component" in all_output(result)


def test_section_keys_cover_registry():
    """Every registered section must have a stable key for --component."""
    assert "nvidia" in SECTION_KEYS
    assert len(SECTION_KEYS) == len(set(SECTION_KEYS))
