"""Tests for the `caasi dataset` commands."""

from __future__ import annotations

import json
import textwrap
import time

import yaml

from caasi.cli.main import app
from caasi.core import dataset as dataset_core

GENERATE_SCRIPT = textwrap.dedent(
    """\
    import os
    from pathlib import Path

    target = Path(os.environ["CAASI_DATASET_DIR"])
    (target / "episodes").mkdir(exist_ok=True)
    (target / "episodes" / "ep-000.bin").write_bytes(b"episode")
    (target / "observations").mkdir(exist_ok=True)
    (target / "observations" / "obs-000.bin").write_bytes(b"obs")
    print("dataset written to", target)
    """
)


def make_experiment(tmp_path):
    (tmp_path / "gen.py").write_text(GENERATE_SCRIPT, encoding="utf-8")
    config = tmp_path / "experiment.yaml"
    config.write_text(
        yaml.safe_dump(
            {"name": "demo-dataset", "backend": "python", "script": "gen.py"}
        ),
        encoding="utf-8",
    )
    return config


def configure_paths(tmp_path, monkeypatch):
    cfg_file = tmp_path / "caasi-test.yaml"
    cfg_file.write_text(
        yaml.safe_dump(
            {
                "paths": {
                    "runs": str(tmp_path / "runs"),
                    "datasets": str(tmp_path / "datasets"),
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CAASI_CONFIG", str(cfg_file))
    return tmp_path / "runs", tmp_path / "datasets"


def wait_for_run(runs_base, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for run_dir in runs_base.glob("*"):
            if (run_dir / "exit_code").is_file():
                return run_dir
        time.sleep(0.05)
    raise AssertionError("run did not finish in time")


def test_dataset_generate_dry_run(runner, tmp_path, monkeypatch):
    config = make_experiment(tmp_path)
    configure_paths(tmp_path, monkeypatch)
    result = runner.invoke(
        app, ["dataset", "generate", str(config), "--episodes", "10", "--dry-run"]
    )
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert "--dataset-dir <dir>" in result.output
    assert not (tmp_path / "datasets").exists()


def test_dataset_generate_inspect_validate_convert(runner, tmp_path, monkeypatch):
    config = make_experiment(tmp_path)
    runs_base, datasets_base = configure_paths(tmp_path, monkeypatch)

    result = runner.invoke(
        app,
        ["dataset", "generate", str(config), "--episodes", "1", "--record-images"],
    )
    assert result.exit_code == 0, result.output
    assert "Dataset generation started" in result.output

    run_dir = wait_for_run(runs_base)
    assert (run_dir / "exit_code").read_text().strip() == "0"

    datasets = dataset_core.list_datasets(datasets_base)
    assert len(datasets) == 1
    dataset_dir = datasets[0]
    assert (dataset_dir / "episodes" / "ep-000.bin").is_file()
    metadata = dataset_core.read_metadata(dataset_dir)
    assert metadata["name"] == "demo-dataset"
    assert metadata["episodes"] == 1
    assert metadata["record"] == {"images": True, "depth": False, "lidar": False}
    assert metadata["run_id"] == run_dir.name

    # inspect ---------------------------------------------------------------
    result = runner.invoke(app, ["dataset", "inspect", dataset_dir.name, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["path"] == str(dataset_dir)
    assert data["metadata"]["name"] == "demo-dataset"
    assert data["contents"]["dirs"] == {"episodes": 1, "observations": 1}
    assert data["run"]["status"] == "succeeded"

    result = runner.invoke(app, ["dataset", "inspect", dataset_dir.name])
    assert result.exit_code == 0
    assert "demo-dataset" in result.output

    # validate --------------------------------------------------------------
    result = runner.invoke(app, ["dataset", "validate", dataset_dir.name, "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["valid"] is True

    # convert ---------------------------------------------------------------
    result = runner.invoke(app, ["dataset", "convert", dataset_dir.name, "--to", "jsonl"])
    assert result.exit_code == 0, result.output
    index = dataset_dir / "index.jsonl"
    assert index.is_file()
    entries = [json.loads(line) for line in index.read_text().splitlines()]
    paths = {entry["path"] for entry in entries}
    assert paths == {
        "episodes/ep-000.bin",
        "observations/obs-000.bin",
    }

    custom = tmp_path / "custom.csv"
    result = runner.invoke(
        app,
        ["dataset", "convert", dataset_dir.name, "--to", "csv", "--output", str(custom)],
    )
    assert result.exit_code == 0
    assert custom.is_file()
    assert "path,size" in custom.read_text().splitlines()[0]

    result = runner.invoke(app, ["dataset", "convert", dataset_dir.name, "--to", "xml"])
    assert result.exit_code == 1
    assert "unknown index format" in result.output


def test_dataset_not_found(runner, tmp_path, monkeypatch):
    configure_paths(tmp_path, monkeypatch)
    result = runner.invoke(app, ["dataset", "inspect", "nope"])
    assert result.exit_code == 1
    assert "No dataset matching" in result.output


def test_dataset_validate_issues(runner, tmp_path, monkeypatch):
    _runs, datasets_base = configure_paths(tmp_path, monkeypatch)
    dataset_dir = datasets_base / "broken"
    (dataset_dir / "episodes").mkdir(parents=True)
    (dataset_dir / "episodes" / "ep-000.bin").write_bytes(b"x")
    (dataset_dir / "metadata.json").write_text(
        json.dumps({"episodes": 5}), encoding="utf-8"
    )

    result = runner.invoke(app, ["dataset", "validate", "broken"])
    assert result.exit_code == 1
    assert "'name' is missing" in result.output
    assert "declares 5 episode(s) but episodes/ contains 1" in result.output

    result = runner.invoke(app, ["dataset", "validate", "broken", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["valid"] is False


def test_dataset_validate_missing_metadata(runner, tmp_path, monkeypatch):
    _runs, datasets_base = configure_paths(tmp_path, monkeypatch)
    dataset_dir = datasets_base / "empty"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "metadata.json").write_text("{}", encoding="utf-8")

    result = runner.invoke(app, ["dataset", "validate", "empty"])
    assert result.exit_code == 1
    assert "'name' is missing" in result.output


def test_dataset_generate_missing_config(runner, tmp_path, monkeypatch):
    configure_paths(tmp_path, monkeypatch)
    result = runner.invoke(app, ["dataset", "generate", str(tmp_path / "nope.yaml")])
    assert result.exit_code == 1
    assert "not found" in result.output
