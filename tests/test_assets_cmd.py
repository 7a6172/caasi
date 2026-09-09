"""Tests for the assets surface: robot/scene import|validate, scene capture|reconstruct.

Covers plan row `test_assets_cmd.py`: robot import dry-run + converter
resolution, robot validate pass/fail, scene import|validate, scene capture
tracked bag run, scene reconstruct with and without a resolved tool.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from caasi.cli.main import app
from caasi.core import catalog

from .conftest import all_output
from .test_ros_cmd import configure_runs, no_ros2, wait_for_run


def flat(result) -> str:
    return " ".join(all_output(result).split())


@pytest.fixture
def toolbin(tmp_path, monkeypatch):
    """A bin dir first on PATH; tests add fake tools to it."""
    bin_dir = tmp_path / "toolbin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    catalog.clear_cache()
    yield bin_dir
    catalog.clear_cache()


@pytest.fixture
def bare_path(tmp_path, monkeypatch):
    """PATH with no tools at all (usdcat/check_urdf/nurec undiscoverable)."""
    empty = tmp_path / "barebin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    catalog.clear_cache()
    yield empty
    catalog.clear_cache()


def make_tool(bin_dir, name: str, script: str | None = None) -> Path:
    path = Path(bin_dir) / name
    path.write_text(
        script or f'#!/usr/bin/env bash\necho "{name}-args $*"\n', encoding="utf-8"
    )
    path.chmod(0o755)
    return path


def make_project(runner, tmp_path, monkeypatch) -> Path:
    target = tmp_path / "proj"
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 0, result.output
    monkeypatch.chdir(target)
    return target


def set_definition(root: Path, kind: str, name: str, **fields) -> None:
    path = root / f"{kind}s" / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data.update(fields)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


# -- robot import ----------------------------------------------------------


def test_robot_import_dry_run_uses_the_isaac_importer(runner, tmp_path, fake_isaac_tree):
    source = tmp_path / "robot.urdf"
    source.write_text("<robot name='go2'/>", encoding="utf-8")
    result = runner.invoke(app, ["robot", "import", str(source), "--dry-run"])
    assert result.exit_code == 0, result.output
    text = flat(result)
    assert "Dry run" in text
    assert "python.sh" in text
    assert "-m omni.importer.urdf" in text
    assert str(source) in text
    assert str(tmp_path / "robot.usd") in text


def test_robot_import_dry_run_falls_back_to_check_urdf(runner, tmp_path, fake_usd_tools):
    source = tmp_path / "robot.urdf"
    source.write_text("<robot name='go2'/>", encoding="utf-8")
    result = runner.invoke(app, ["robot", "import", str(source), "--dry-run"])
    assert result.exit_code == 0, result.output
    text = flat(result)
    assert str(fake_usd_tools / "check_urdf") in text
    assert str(source) in text


def test_robot_import_without_any_converter(runner, tmp_path, bare_path):
    source = tmp_path / "robot.urdf"
    source.write_text("<robot name='go2'/>", encoding="utf-8")
    result = runner.invoke(app, ["robot", "import", str(source)])
    assert result.exit_code == 1
    assert "No converter found for 'robot.urdf'" in flat(result)


def test_robot_import_mjcf_needs_the_importer(runner, tmp_path, fake_usd_tools):
    source = tmp_path / "robot.mjcf"
    source.write_text("<mujoco/>", encoding="utf-8")
    result = runner.invoke(app, ["robot", "import", str(source)])
    assert result.exit_code == 1
    assert "No converter found" in flat(result)


def test_robot_import_bad_format(runner, tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("hi", encoding="utf-8")
    result = runner.invoke(app, ["robot", "import", str(source)])
    assert result.exit_code == 1
    assert "Unsupported asset format '.txt'" in flat(result)


def test_robot_import_missing_file(runner, tmp_path):
    result = runner.invoke(app, ["robot", "import", str(tmp_path / "ghost.urdf")])
    assert result.exit_code == 1
    assert "not found" in flat(result)


def test_robot_import_tracked_run(runner, tmp_path, monkeypatch, toolbin):
    make_tool(toolbin, "check_urdf")
    runs_base = configure_runs(tmp_path, monkeypatch)
    source = tmp_path / "robot.urdf"
    source.write_text("<robot name='go2'/>", encoding="utf-8")
    result = runner.invoke(app, ["robot", "import", str(source)])
    assert result.exit_code == 0, result.output
    assert "Import started (validate via check_urdf)" in flat(result)
    run_dir = wait_for_run(runs_base)
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    assert f"check_urdf-args {source}" in stdout


# -- robot validate ----------------------------------------------------------


def test_robot_validate_pass(runner, tmp_path, monkeypatch, fake_usd_tools):
    root = make_project(runner, tmp_path, monkeypatch)
    assert runner.invoke(app, ["robot", "create", "go2"]).exit_code == 0
    (root / "robots" / "go2.urdf").write_text("<robot name='go2'/>", encoding="utf-8")
    set_definition(root, "robot", "go2", urdf="robots/go2.urdf")

    result = runner.invoke(app, ["robot", "validate", "go2"])
    assert result.exit_code == 0, result.output
    assert "is valid" in result.output

    result = runner.invoke(app, ["robot", "validate", "go2", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["valid"] is True
    assert data["name"] == "go2"
    assert len(data["files"]) == 1
    entry = data["files"][0]
    assert entry["key"] == "urdf"
    assert entry["tool"] == "check_urdf"
    assert entry["ok"] is True


def test_robot_validate_missing_file(runner, tmp_path, monkeypatch, fake_usd_tools):
    root = make_project(runner, tmp_path, monkeypatch)
    runner.invoke(app, ["robot", "create", "go2"])
    set_definition(root, "robot", "go2", urdf="robots/nope.urdf")

    result = runner.invoke(app, ["robot", "validate", "go2"])
    assert result.exit_code == 1
    assert "does not exist" in flat(result)

    result = runner.invoke(app, ["robot", "validate", "go2", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["valid"] is False
    assert len(data["issues"]) == 1
    assert data["files"][0]["exists"] is False


def test_robot_validate_checker_fails(runner, tmp_path, monkeypatch, toolbin):
    make_tool(
        toolbin,
        "check_urdf",
        '#!/usr/bin/env bash\necho "broken joint" >&2\nexit 1\n',
    )
    root = make_project(runner, tmp_path, monkeypatch)
    runner.invoke(app, ["robot", "create", "go2"])
    (root / "robots" / "go2.urdf").write_text("<robot name='go2'/>", encoding="utf-8")
    set_definition(root, "robot", "go2", urdf="robots/go2.urdf")

    result = runner.invoke(app, ["robot", "validate", "go2"])
    assert result.exit_code == 1
    assert "check_urdf reported errors" in flat(result)

    result = runner.invoke(app, ["robot", "validate", "go2", "--json"])
    data = json.loads(result.output)
    assert data["valid"] is False
    assert data["files"][0]["detail"] == "broken joint"


def test_robot_validate_without_tools_checks_existence(
    runner, tmp_path, monkeypatch, bare_path
):
    root = make_project(runner, tmp_path, monkeypatch)
    runner.invoke(app, ["robot", "create", "go2"])
    (root / "robots" / "go2.urdf").write_text("<robot name='go2'/>", encoding="utf-8")
    set_definition(root, "robot", "go2", urdf="robots/go2.urdf")

    result = runner.invoke(app, ["robot", "validate", "go2", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["valid"] is True
    assert data["files"][0]["tool"] is None
    assert "existence checked only" in data["files"][0]["detail"]


def test_robot_validate_unknown_definition(runner, tmp_path, monkeypatch):
    make_project(runner, tmp_path, monkeypatch)
    result = runner.invoke(app, ["robot", "validate", "ghost"])
    assert result.exit_code == 1
    assert "No robot named 'ghost'" in flat(result)


# -- scene import / validate -------------------------------------------------


def test_scene_import_dry_run_validates_usd(runner, tmp_path, fake_usd_tools):
    source = tmp_path / "stage.usda"
    source.write_text("#usda 1.0\n", encoding="utf-8")
    result = runner.invoke(app, ["scene", "import", str(source), "--dry-run"])
    assert result.exit_code == 0, result.output
    text = flat(result)
    assert str(fake_usd_tools / "usdchecker") in text
    assert str(source) in text


def test_scene_validate(runner, tmp_path, monkeypatch, fake_usd_tools):
    root = make_project(runner, tmp_path, monkeypatch)
    runner.invoke(app, ["scene", "create", "warehouse"])
    (root / "scenes" / "warehouse.usd").write_text("#usda 1.0\n", encoding="utf-8")
    set_definition(root, "scene", "warehouse", usd="scenes/warehouse.usd")

    result = runner.invoke(app, ["scene", "validate", "warehouse", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["valid"] is True
    assert data["files"][0]["key"] == "usd"
    assert data["files"][0]["tool"] == "usdchecker"

    result = runner.invoke(app, ["scene", "validate", "warehouse"])
    assert result.exit_code == 0
    assert "is valid" in result.output


# -- scene capture -----------------------------------------------------------


def test_scene_capture_dry_run(runner, tmp_path, monkeypatch, fake_ros_sourced):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["scene", "capture", "--dry-run", "/camera/image_raw"])
    assert result.exit_code == 0, result.output
    text = flat(result)
    assert "Dry run" in text
    assert "bag record /camera/image_raw -o" in text
    assert "capture-" in text
    datasets = tmp_path / "home" / ".caasi" / "datasets"
    assert list(datasets.iterdir()) == []


def test_scene_capture_tracked_run(runner, tmp_path, monkeypatch, fake_ros_sourced):
    root = make_project(runner, tmp_path, monkeypatch)
    runs_base = configure_runs(tmp_path, monkeypatch)
    result = runner.invoke(app, ["scene", "capture", "/scan", "--name", "kitchen"])
    assert result.exit_code == 0, result.output
    assert "Capture started:" in flat(result)

    dest = next(iter((root / "datasets").glob("kitchen-*")))
    metadata = json.loads((dest / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["kind"] == "capture"
    assert metadata["status"] == "capturing"
    assert metadata["topics"] == ["/scan"]
    assert metadata["run_id"]

    run_dir = wait_for_run(runs_base)
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    assert f"bag record /scan -o {dest}" in stdout


def test_scene_capture_defaults_to_all_topics(
    runner, tmp_path, monkeypatch, fake_ros_sourced
):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["scene", "capture", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "bag record -a -o" in flat(result)


def test_scene_capture_requires_ros2(runner, tmp_path, monkeypatch):
    no_ros2(monkeypatch, tmp_path)
    result = runner.invoke(app, ["scene", "capture"])
    assert result.exit_code == 1
    assert "ros2 CLI not found" in flat(result)


# -- scene reconstruct -------------------------------------------------------


def test_scene_reconstruct_without_a_tool(runner, tmp_path, bare_path):
    bag = tmp_path / "bag"
    bag.mkdir()
    result = runner.invoke(app, ["scene", "reconstruct", str(bag)])
    assert result.exit_code == 1
    text = flat(result)
    assert "No neural reconstruction tool detected" in text
    assert "catalog.usd.nurec.binaries" in text


def test_scene_reconstruct_missing_capture(runner, tmp_path):
    result = runner.invoke(app, ["scene", "reconstruct", str(tmp_path / "ghost")])
    assert result.exit_code == 1
    assert "not found" in flat(result)


def test_scene_reconstruct_dry_run_and_tracked(runner, tmp_path, monkeypatch, toolbin):
    make_tool(toolbin, "nurec")
    runs_base = configure_runs(tmp_path, monkeypatch)
    bag = tmp_path / "bag"
    bag.mkdir()

    result = runner.invoke(app, ["scene", "reconstruct", str(bag), "--dry-run"])
    assert result.exit_code == 0, result.output
    text = flat(result)
    assert str(toolbin / "nurec") in text
    assert str(bag) in text

    result = runner.invoke(app, ["scene", "reconstruct", str(bag), "--format", "usd"])
    assert result.exit_code == 0, result.output
    assert "Reconstruction started" in flat(result)

    run_dir = wait_for_run(runs_base)
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    assert f"nurec-args {bag} --format usd" in stdout


# -- doctor assets + help surface --------------------------------------------


def test_doctor_component_assets(runner, fake_usd_tools):
    result = runner.invoke(app, ["doctor", "--component", "assets", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    by_name = {check["name"]: check for check in data["checks"]}
    assert by_name["usdcat"]["status"] == "ok"
    assert by_name["usdchecker"]["status"] == "ok"
    assert by_name["NuRec (neural reconstruction)"]["status"] == "skip"
    assert all(check["section"] == "assets" for check in data["checks"])


def test_doctor_component_assets_fails_without_core_tools(runner, bare_path):
    result = runner.invoke(app, ["doctor", "--component", "assets", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    by_name = {check["name"]: check for check in data["checks"]}
    assert by_name["usdcat"]["status"] == "fail"
    assert "catalog.usd.usdcat.binaries" in flat(result)


def test_help_lists_the_new_commands(runner):
    result = runner.invoke(app, ["robot", "--help"])
    assert "import" in result.output
    assert "validate" in result.output

    result = runner.invoke(app, ["scene", "--help"])
    for command in ("import", "validate", "capture", "reconstruct"):
        assert command in result.output

    result = runner.invoke(app, ["task", "--help"])
    assert "import" not in result.output
    assert "capture" not in result.output
