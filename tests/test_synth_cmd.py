"""Tests for `caasi synth` — Replicator-backed synthetic data generation."""

from __future__ import annotations

import json
import textwrap

import yaml

from caasi import state
from caasi.cli.main import app
from caasi.core import catalog, dataset as dataset_core

from .conftest import all_output
from .test_ros_cmd import wait_for_run

#: Writes the ``plan3.md`` §30 tree into CAASI_DATASET_DIR / --dataset-dir.
GENERATE_SCRIPT = textwrap.dedent(
    """\
    import argparse
    import os
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=2)
    parser.add_argument("--dataset-dir", default=os.environ.get("CAASI_DATASET_DIR", "."))
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--domain-randomize", action="store_true")
    args = parser.parse_args()

    target = Path(args.dataset_dir)
    for index in range(args.episodes):
        for sub in ("rgb", "depth", "segmentation", "bounding_boxes"):
            folder = target / sub
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"frame-{index:04d}.png").write_bytes(b"frame")
    (target / "metadata").mkdir(parents=True, exist_ok=True)
    (target / "metadata" / "camera.json").write_text("{}", encoding="utf-8")
    print("generated", args.episodes, "episodes into", target)
    """
)


def make_experiment(tmp_path, name="warehouse"):
    (tmp_path / "gen.py").write_text(GENERATE_SCRIPT, encoding="utf-8")
    config = tmp_path / "experiment.yaml"
    config.write_text(
        yaml.safe_dump({"name": name, "backend": "sim", "script": "gen.py"}),
        encoding="utf-8",
    )
    return config


def configure_paths(tmp_path, monkeypatch, root=None):
    """Keep runs/datasets in tmp_path; register *root* as Isaac Sim when given."""
    data = {
        "paths": {
            "runs": str(tmp_path / "runs"),
            "datasets": str(tmp_path / "datasets"),
        }
    }
    if root is not None:
        data["tools"] = {
            "isaacsim": {
                "default": "5.1",
                "versions": {
                    "5.1": {"path": str(root), "python": str(root / "python.sh")}
                },
            }
        }
    cfg_file = tmp_path / "caasi-synth.yaml"
    cfg_file.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setenv("CAASI_CONFIG", str(cfg_file))
    catalog.clear_cache()
    state.reset()
    return tmp_path / "runs", tmp_path / "datasets"


def manifest_of(run_dir):
    return yaml.safe_load((run_dir / "manifest.yaml").read_text(encoding="utf-8"))


# -- status -----------------------------------------------------------------


def test_synth_status_with_replicator(runner, fake_isaac_tree, tmp_path, monkeypatch):
    configure_paths(tmp_path, monkeypatch, fake_isaac_tree)
    result = runner.invoke(app, ["synth", "status", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["domain"] == "sdg"
    assert data["tool"] == "isaacsim"
    assert data["root"] == str(fake_isaac_tree)
    assert (data["installed"], data["total"]) == (1, 2)
    states = {item["key"]: item for item in data["capabilities"]}
    assert states["replicator"]["found"] is True
    assert states["replicator"]["how"] == "path"
    assert states["replicator"]["value"] == str(
        fake_isaac_tree / "exts" / "omni.replicator.core"
    )
    assert states["writer_kit"]["found"] is False

    result = runner.invoke(app, ["synth", "status"])
    assert result.exit_code == 0, all_output(result)
    assert "Synthetic Data Generation" in result.output
    assert "1 of 2 capabilities installed." in result.output


def test_synth_status_without_replicator(runner, tmp_path, monkeypatch):
    configure_paths(tmp_path, monkeypatch)
    result = runner.invoke(app, ["synth", "status", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["installed"] == 0
    assert data["root"] is None
    assert all(item["found"] is False for item in data["capabilities"])


# -- generate ---------------------------------------------------------------


def test_synth_generate_dry_run(runner, fake_isaac_tree, tmp_path, monkeypatch):
    config = make_experiment(tmp_path)
    _runs, datasets_base = configure_paths(tmp_path, monkeypatch, fake_isaac_tree)
    result = runner.invoke(
        app, ["synth", "generate", str(config), "--episodes", "7", "--dry-run"]
    )
    assert result.exit_code == 0, all_output(result)
    flat = " ".join(all_output(result).split())
    assert "Dry run" in flat
    assert str(fake_isaac_tree / "python.sh") in flat
    assert str(tmp_path / "gen.py") in flat
    assert "--episodes 7 --headless --dataset-dir <dir>" in flat
    assert str(tmp_path.resolve()) in flat
    assert not datasets_base.exists()


def test_synth_generate_passes_unknown_flags(runner, fake_isaac_tree, tmp_path, monkeypatch):
    config = make_experiment(tmp_path)
    configure_paths(tmp_path, monkeypatch, fake_isaac_tree)
    result = runner.invoke(
        app,
        ["synth", "generate", str(config), "--dry-run", "--domain-randomize", "--camera", "front"],
    )
    assert result.exit_code == 0, all_output(result)
    flat = " ".join(all_output(result).split())
    assert "--headless --domain-randomize --camera front --dataset-dir <dir>" in flat


def test_synth_generate_requires_replicator(runner, tmp_path, monkeypatch):
    config = make_experiment(tmp_path)
    configure_paths(tmp_path, monkeypatch)
    result = runner.invoke(app, ["synth", "generate", str(config), "--dry-run"])
    assert result.exit_code == 1
    flat = " ".join(all_output(result).split())
    assert "Isaac Sim Replicator was not found (exts/omni.replicator.core)" in flat
    assert "catalog.sdg.replicator.paths" in flat


def test_synth_generate_preview_validate(runner, fake_isaac_tree, tmp_path, monkeypatch):
    config = make_experiment(tmp_path)
    runs_base, datasets_base = configure_paths(tmp_path, monkeypatch, fake_isaac_tree)

    result = runner.invoke(app, ["synth", "generate", str(config), "--episodes", "4"])
    assert result.exit_code == 0, all_output(result)
    assert "Synthetic data generation started" in result.output
    assert "caasi logs" in result.output

    run_dir = wait_for_run(runs_base)
    assert (run_dir / "exit_code").read_text().strip() == "0", (
        run_dir / "stderr.log"
    ).read_text(encoding="utf-8")
    manifest = manifest_of(run_dir)
    assert manifest["kind"] == "dataset"
    assert manifest["backend"] == "sim"
    assert manifest["extra"]["generator"] == "replicator"
    assert manifest["extra"]["episodes"] == 4
    assert manifest["extra"]["experiment"] == str(config.resolve())
    assert "generated 4 episodes" in (run_dir / "stdout.log").read_text(encoding="utf-8")

    datasets = dataset_core.list_datasets(datasets_base)
    assert len(datasets) == 1
    dataset_dir = datasets[0]
    assert dataset_dir.name.startswith("warehouse-")
    assert manifest["extra"]["dataset"] == str(dataset_dir)
    assert manifest["command"][-2:] == ["--dataset-dir", str(dataset_dir)]
    metadata = dataset_core.read_metadata(dataset_dir)
    assert metadata["generator"] == "replicator"
    assert metadata["replicator"] == str(
        fake_isaac_tree / "exts" / "omni.replicator.core"
    )
    assert metadata["backend"] == "sim"
    assert metadata["status"] == "generating"
    assert metadata["episodes"] == 4
    assert metadata["run_id"] == run_dir.name
    assert (dataset_dir / "rgb" / "frame-0003.png").is_file()

    # preview ----------------------------------------------------------------
    result = runner.invoke(app, ["synth", "preview", dataset_dir.name, "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["path"] == str(dataset_dir)
    assert data["name"] == "warehouse"
    assert data["generator"] == "replicator"
    assert data["episodes_declared"] == 4
    assert data["episodes_produced"] == 4
    assert data["counts"] == {
        "rgb": 4,
        "depth": 4,
        "segmentation": 4,
        "bounding_boxes": 4,
        "metadata": 1,
    }
    assert data["files"] == 18  # 16 frames + camera.json + metadata.json
    assert data["run"]["status"] == "succeeded"
    assert isinstance(data["elapsed"], float)

    result = runner.invoke(app, ["synth", "preview", dataset_dir.name])
    assert result.exit_code == 0, all_output(result)
    assert "4 produced, 4 declared" in result.output
    assert "replicator" in result.output

    # validate ---------------------------------------------------------------
    result = runner.invoke(app, ["synth", "validate", dataset_dir.name, "--json"])
    assert result.exit_code == 0, all_output(result)
    payload = json.loads(result.output)
    assert payload["valid"] is True
    assert payload["issues"] == []
    assert payload["counts"]["rgb"] == 4

    result = runner.invoke(app, ["synth", "validate", dataset_dir.name])
    assert result.exit_code == 0, all_output(result)
    assert "is consistent" in result.output


def test_synth_generate_output_dir(runner, fake_isaac_tree, tmp_path, monkeypatch):
    config = make_experiment(tmp_path)
    runs_base, datasets_base = configure_paths(tmp_path, monkeypatch, fake_isaac_tree)
    dest = tmp_path / "out" / "custom-ds"

    result = runner.invoke(
        app, ["synth", "generate", str(config), "--episodes", "1", "--output", str(dest)]
    )
    assert result.exit_code == 0, all_output(result)
    assert str(dest) in result.output

    run_dir = wait_for_run(runs_base)
    assert (run_dir / "exit_code").read_text().strip() == "0"
    manifest = manifest_of(run_dir)
    assert manifest["name"] == "custom-ds"
    assert manifest["command"][-2:] == ["--dataset-dir", str(dest)]
    assert manifest["extra"]["dataset"] == str(dest)
    assert list(datasets_base.glob("*")) == []

    metadata = dataset_core.read_metadata(dest)
    assert metadata["name"] == "custom-ds"
    assert metadata["generator"] == "replicator"
    assert (dest / "rgb" / "frame-0000.png").is_file()

    result = runner.invoke(app, ["synth", "preview", str(dest), "--json"])
    assert result.exit_code == 0, all_output(result)
    assert json.loads(result.output)["episodes_produced"] == 1


# -- preview / validate on hand-made datasets --------------------------------


def test_synth_preview_counts(runner, tmp_path, monkeypatch):
    _runs, datasets_base = configure_paths(tmp_path, monkeypatch)
    dataset_dir = datasets_base / "counts-20260101-000000"
    for sub, count in (("rgb", 3), ("depth", 3), ("metadata", 1)):
        folder = dataset_dir / sub
        folder.mkdir(parents=True)
        for index in range(count):
            (folder / f"frame-{index:04d}.png").write_bytes(b"x")
    dataset_core.write_metadata(dataset_dir, {"name": "counts", "episodes": 3})

    result = runner.invoke(app, ["synth", "preview", "counts", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["counts"] == {
        "rgb": 3,
        "depth": 3,
        "segmentation": 0,
        "bounding_boxes": 0,
        "metadata": 1,
    }
    assert data["episodes_produced"] == 3
    assert data["episodes_declared"] == 3
    assert data["run"] is None
    assert data["elapsed"] is None

    result = runner.invoke(app, ["synth", "preview", "counts"])
    assert result.exit_code == 0, all_output(result)
    assert "bounding_boxes" in result.output
    assert "3 produced, 3 declared" in result.output

    result = runner.invoke(app, ["synth", "validate", "counts"])
    assert result.exit_code == 0, all_output(result)


def test_synth_validate_reports_issues(runner, tmp_path, monkeypatch):
    _runs, datasets_base = configure_paths(tmp_path, monkeypatch)
    dataset_dir = datasets_base / "broken"
    (dataset_dir / "rgb").mkdir(parents=True)
    for index in (0, 1):
        (dataset_dir / "rgb" / f"frame-{index:04d}.png").write_bytes(b"x")
    (dataset_dir / "segmentation").mkdir()
    (dataset_dir / "segmentation" / "frame-0000.png").write_bytes(b"x")
    (dataset_dir / "metadata.json").write_text(
        json.dumps({"name": "broken", "episodes": 5}), encoding="utf-8"
    )

    result = runner.invoke(app, ["synth", "validate", "broken"])
    assert result.exit_code == 1
    flat = " ".join(all_output(result).split())
    assert "2 issue(s) found:" in flat
    assert "metadata declares 5 episode(s) but rgb/ holds 2" in flat
    assert "segmentation/ holds 1 file(s) but rgb/ holds 2" in flat
    assert "depth/" not in flat  # absent directories are not reported

    result = runner.invoke(app, ["synth", "validate", "broken", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["valid"] is False
    assert data["counts"]["rgb"] == 2
    assert len(data["issues"]) == 2


def test_synth_preview_unknown_dataset(runner, tmp_path, monkeypatch):
    configure_paths(tmp_path, monkeypatch)
    result = runner.invoke(app, ["synth", "preview", "nope"])
    assert result.exit_code == 1
    assert "No dataset matching 'nope'." in all_output(result)


# -- registration -----------------------------------------------------------


def test_synth_group_is_registered(runner):
    result = runner.invoke(app, ["synth", "--help"])
    assert result.exit_code == 0, all_output(result)
    for verb in ("status", "generate", "preview", "validate"):
        assert verb in result.output

    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, all_output(result)
    assert "synth" in result.output
    assert "teleop" in result.output
