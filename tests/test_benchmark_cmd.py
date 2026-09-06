"""Tests for `caasi benchmark` and its metric parsing."""

from __future__ import annotations

import json
import time

from caasi import state
from caasi.cli.main import app
from caasi.core import runs
from caasi.core.benchmark import parse_metrics

from .conftest import all_output

FINISHED = (runs.TERMINAL_OK, runs.TERMINAL_FAIL)

BENCH_LOG = (
    "caasi_metric simulation_fps=241.5\n"
    "Steps/sec: 61696\n"
    "Real-time factor: 12.3x\n"
    "GPU utilization: 94%\n"
    "some unrelated log line\n"
)
BENCH_SCRIPT = "".join(
    f"print({line!r})\n" for line in BENCH_LOG.splitlines()
)


def test_parse_metrics():
    metrics = parse_metrics(BENCH_LOG)
    assert metrics == {
        "simulation_fps": 241.5,
        "steps_per_sec": 61696.0,
        "real_time_factor": 12.3,
        "gpu_utilization": 94.0,
    }


def test_parse_metrics_empty():
    assert parse_metrics("") == {}
    assert parse_metrics("no metrics here\n") == {}


def _experiment(tmp_path):
    (tmp_path / "bench.py").write_text(BENCH_SCRIPT, encoding="utf-8")
    config = tmp_path / "benchmark.yaml"
    config.write_text("name: bench\nbackend: python\nscript: bench.py\n", encoding="utf-8")
    return config


def _wait_finished(record, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if runs.effective_status(record) in FINISHED:
            return
        time.sleep(0.05)


def test_benchmark_start_dry_run(runner, tmp_path):
    config = _experiment(tmp_path)
    result = runner.invoke(app, ["benchmark", "start", str(config), "--envs", "8", "--dry-run"])
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert "--envs" in result.output
    assert runs.list_runs(state.cfg()) == []


def test_benchmark_start_and_report(runner, tmp_path):
    config = _experiment(tmp_path)
    result = runner.invoke(app, ["benchmark", "start", str(config), "--envs", "8"])
    assert result.exit_code == 0
    assert "started in the background" in result.output
    assert "caasi benchmark report" in result.output

    record = runs.find_run(state.cfg(), "latest")
    assert record.kind == "benchmark"
    _wait_finished(record)

    result = runner.invoke(app, ["benchmark", "report", "latest"])
    assert result.exit_code == 0
    assert "simulation_fps" in result.output
    assert "241.5" in result.output
    assert "steps_per_sec" in result.output

    result = runner.invoke(app, ["benchmark", "report", "latest", "--json"])
    data = json.loads(result.output)
    assert data["status"] == "succeeded"
    assert data["metrics"]["real_time_factor"] == 12.3


def test_benchmark_report_no_metrics(runner, tmp_path):
    (tmp_path / "plain.py").write_text("print('nothing useful')\n", encoding="utf-8")
    config = tmp_path / "plain.yaml"
    config.write_text("name: plain\nbackend: python\nscript: plain.py\n", encoding="utf-8")
    runner.invoke(app, ["benchmark", "start", str(config)])
    record = runs.find_run(state.cfg(), "latest")
    _wait_finished(record)

    result = runner.invoke(app, ["benchmark", "report", "latest"])
    assert result.exit_code == 0
    assert "No metrics found" in result.output


def test_benchmark_report_not_found(runner):
    result = runner.invoke(app, ["benchmark", "report", "nope"])
    assert result.exit_code == 1
    assert "No run matching" in all_output(result)
