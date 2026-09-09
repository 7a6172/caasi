"""Tests for `caasi teleop` — start a stack, record demonstrations, replay bags."""

from __future__ import annotations

import yaml

from caasi import state
from caasi.cli.main import app
from caasi.core import catalog, dataset as dataset_core, runs

from .conftest import all_output
from .test_ros_cmd import no_ros2, wait_for_run


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
    cfg_file = tmp_path / "caasi-teleop.yaml"
    cfg_file.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setenv("CAASI_CONFIG", str(cfg_file))
    catalog.clear_cache()
    state.reset()
    return tmp_path / "runs", tmp_path / "datasets"


def flat(result) -> str:
    return " ".join(all_output(result).split())


def manifest_of(run_dir):
    return yaml.safe_load((run_dir / "manifest.yaml").read_text(encoding="utf-8"))


# -- start ------------------------------------------------------------------


def test_teleop_start_keyboard_dry_run(runner, fake_ros_world):
    fake_ros_world.packages("teleop_twist_keyboard")
    result = runner.invoke(app, ["teleop", "start", "--dry-run"])
    assert result.exit_code == 0, all_output(result)
    text = flat(result)
    assert "Dry run" in text
    assert text.endswith("ros2 launch teleop_twist_keyboard teleop-launch.py")


def test_teleop_start_device_and_pass_through(runner, fake_ros_world):
    fake_ros_world.packages("teleop_twist_keyboard")
    result = runner.invoke(
        app,
        ["teleop", "start", "--dry-run", "--device", "/dev/input/js0", "--use-sim-time"],
    )
    assert result.exit_code == 0, all_output(result)
    assert "teleop-launch.py device:=/dev/input/js0 --use-sim-time" in flat(result)


def test_teleop_start_bare_launch_args_without_config(runner, fake_ros_world):
    # Only a `.yaml`/`.yml` first argument is read as an experiment config;
    # anything else is passed through to the resolved stack.
    fake_ros_world.packages("teleop_twist_keyboard")
    result = runner.invoke(app, ["teleop", "start", "--dry-run", "use_sim_time:=true"])
    assert result.exit_code == 0, all_output(result)
    assert flat(result).endswith("teleop-launch.py use_sim_time:=true")


def test_teleop_start_honours_backend(runner, fake_ros_world):
    fake_ros_world.packages("teleop_twist_keyboard", "teleop_twist_joy", "joy")
    result = runner.invoke(app, ["teleop", "start", "--dry-run", "--backend", "joy"])
    assert result.exit_code == 0, all_output(result)
    assert "launch teleop_twist_joy teleop-launch.py" in flat(result)

    # without --backend the first installed stack wins (keyboard before joy)
    result = runner.invoke(app, ["teleop", "start", "--dry-run"])
    assert result.exit_code == 0, all_output(result)
    assert "launch teleop_twist_keyboard teleop-launch.py" in flat(result)


def test_teleop_start_defaults_to_first_installed(runner, fake_ros_world):
    fake_ros_world.packages("teleop_twist_joy", "joy")
    result = runner.invoke(app, ["teleop", "start", "--dry-run"])
    assert result.exit_code == 0, all_output(result)
    assert "launch teleop_twist_joy teleop-launch.py" in flat(result)


def test_teleop_start_xr_script(runner, fake_isaac_tree, tmp_path):
    result = runner.invoke(app, ["teleop", "start", "--dry-run", "--backend", "xr"])
    assert result.exit_code == 0, all_output(result)
    assert str(fake_isaac_tree / "isaac-sim.xr.vr.sh") in flat(result)

    runs_base = tmp_path / "home" / ".caasi" / "runs"
    result = runner.invoke(app, ["teleop", "start", "--backend", "xr"])
    assert result.exit_code == 0, all_output(result)
    run_dir = wait_for_run(runs_base)
    manifest = manifest_of(run_dir)
    assert manifest["kind"] == "teleop"
    assert manifest["backend"] == "isaacsim"
    assert manifest["name"] == "xr"
    assert manifest["command"] == [str(fake_isaac_tree / "isaac-sim.xr.vr.sh")]
    assert (run_dir / "stdout.log").read_text(encoding="utf-8").strip() == "isaac-sim.xr.vr.sh"


def test_teleop_start_missing_backend(runner, fake_ros_world):
    fake_ros_world.packages("teleop_twist_joy", "joy")
    result = runner.invoke(app, ["teleop", "start", "--dry-run", "--backend", "keyboard"])
    assert result.exit_code == 1
    text = flat(result)
    assert "'keyboard' is not available (teleop_twist_keyboard)." in text
    assert "catalog.teleop.keyboard.packages" in text


def test_teleop_start_unknown_backend(runner, fake_ros_world):
    fake_ros_world.packages("teleop_twist_keyboard")
    result = runner.invoke(app, ["teleop", "start", "--dry-run", "--backend", "nope"])
    assert result.exit_code == 1
    text = flat(result)
    assert "Unknown teleop capability 'nope'." in text
    assert "keyboard, joy, xr, record" in text


def test_teleop_start_nothing_installed(runner, fake_ros_world):
    fake_ros_world.packages()
    result = runner.invoke(app, ["teleop", "start", "--dry-run"])
    assert result.exit_code == 1
    assert "No teleop capability is installed." in all_output(result)


def test_teleop_start_tracked_run(runner, fake_ros_world, tmp_path, monkeypatch):
    runs_base, _datasets = configure_paths(tmp_path, monkeypatch)
    fake_ros_world.packages("teleop_twist_keyboard")
    result = runner.invoke(app, ["teleop", "start", "--name", "drive"])
    assert result.exit_code == 0, all_output(result)
    assert "Teleop started" in result.output
    assert "caasi logs" in result.output

    run_dir = wait_for_run(runs_base)
    manifest = manifest_of(run_dir)
    assert manifest["kind"] == "teleop"
    assert manifest["backend"] == "ros"
    assert manifest["name"] == "drive"
    assert manifest["command"][0].endswith("ros2")
    assert manifest["command"][-2:] == ["teleop_twist_keyboard", "teleop-launch.py"]
    assert manifest["extra"] == {"domain": "teleop", "capability": "keyboard"}
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    assert stdout.strip() == "launch teleop_twist_keyboard teleop-launch.py"


def test_teleop_start_with_experiment(runner, fake_isaac_tree, tmp_path, monkeypatch):
    runs_base, _datasets = configure_paths(tmp_path, monkeypatch, fake_isaac_tree)
    (tmp_path / "robot.py").write_text("print('robot sim up')\n", encoding="utf-8")
    config = tmp_path / "robot.yaml"
    config.write_text(
        yaml.safe_dump({"name": "arm", "backend": "sim", "script": "robot.py"}),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["teleop", "start", str(config), "--dry-run"])
    assert result.exit_code == 0, all_output(result)
    text = flat(result)
    assert str(fake_isaac_tree / "python.sh") in text
    assert str(tmp_path / "robot.py") in text

    result = runner.invoke(app, ["teleop", "start", str(config)])
    assert result.exit_code == 0, all_output(result)
    run_dir = wait_for_run(runs_base)
    manifest = manifest_of(run_dir)
    assert manifest["kind"] == "teleop"
    assert manifest["backend"] == "sim"
    assert manifest["name"] == "arm"
    assert manifest["extra"]["experiment"].endswith("robot.yaml")
    assert manifest["cwd"] == str(tmp_path.resolve())
    assert "robot sim up" in (run_dir / "stdout.log").read_text(encoding="utf-8")

    # native pass-through arguments go after the experiment YAML
    result = runner.invoke(app, ["teleop", "start", str(config), "--dry-run", "use_sim_time:=true"])
    assert result.exit_code == 0, all_output(result)
    assert flat(result).endswith("robot.py use_sim_time:=true")


def test_teleop_start_missing_experiment(runner, fake_ros_world, tmp_path, monkeypatch):
    configure_paths(tmp_path, monkeypatch)
    result = runner.invoke(app, ["teleop", "start", str(tmp_path / "nope.yaml")])
    assert result.exit_code == 1
    assert "experiment config not found" in all_output(result)


# -- record -----------------------------------------------------------------


def test_teleop_record_writes_dataset(runner, fake_ros_world, tmp_path, monkeypatch):
    runs_base, datasets_base = configure_paths(tmp_path, monkeypatch)
    result = runner.invoke(
        app, ["teleop", "record", "-t", "/cmd_vel", "-t", "/tf", "--name", "demo"]
    )
    assert result.exit_code == 0, all_output(result)
    assert "Recording demonstrations" in result.output

    run_dir = wait_for_run(runs_base)
    datasets = dataset_core.list_datasets(datasets_base)
    assert len(datasets) == 1
    dest = datasets[0]
    assert dest.name.startswith("demo-")

    manifest = manifest_of(run_dir)
    assert manifest["kind"] == "bag"
    assert manifest["backend"] == "ros2"
    assert manifest["name"] == "demo"
    assert manifest["command"][0].endswith("ros2")
    assert manifest["command"][1:] == ["bag", "record", "/cmd_vel", "/tf", "-o", str(dest)]
    assert manifest["extra"] == {"topics": ["/cmd_vel", "/tf"], "dataset": str(dest)}
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    assert stdout.strip() == f"bag record /cmd_vel /tf -o {dest}"

    metadata = dataset_core.read_metadata(dest)
    assert metadata["name"] == "demo"
    assert metadata["kind"] == "teleop"
    assert metadata["topics"] == ["/cmd_vel", "/tf"]
    assert metadata["status"] == "recording"
    assert metadata["run_id"] == run_dir.name
    assert metadata["created"] == manifest["created"]


def test_teleop_record_dry_run_records_everything(runner, fake_ros_world, tmp_path, monkeypatch):
    _runs, datasets_base = configure_paths(tmp_path, monkeypatch)
    result = runner.invoke(app, ["teleop", "record", "--dry-run"])
    assert result.exit_code == 0, all_output(result)
    text = flat(result)
    assert "bag record -a -o" in text
    assert str(datasets_base) in text
    assert "teleop-" in text
    assert list(datasets_base.glob("*")) == []  # a dry run leaves nothing behind


def test_teleop_record_requires_ros2(runner, tmp_path, monkeypatch):
    no_ros2(monkeypatch, tmp_path)
    result = runner.invoke(app, ["teleop", "record", "--dry-run"])
    assert result.exit_code == 1
    assert "ros2 CLI not found" in all_output(result)


# -- stop -------------------------------------------------------------------


def test_teleop_stop_stops_teleop_and_bag_runs(runner, tmp_path, monkeypatch):
    configure_paths(tmp_path, monkeypatch)
    cfg = state.cfg()
    teleop_run = runs.start_run(cfg, name="drive", command=["sleep", "30"], kind="teleop")
    bag_run = runs.start_run(cfg, name="demo", command=["sleep", "30"], kind="bag")
    other = runs.start_run(cfg, name="other", command=["sleep", "30"], kind="run")
    try:
        result = runner.invoke(app, ["teleop", "stop"])
        assert result.exit_code == 0, all_output(result)
        assert f"Stopped {teleop_run.run_id} (teleop)." in result.output
        assert f"Stopped {bag_run.run_id} (bag)." in result.output
        assert other.run_id not in result.output

        assert runs.effective_status(runs.load_run(cfg, teleop_run.run_id)) == runs.STOPPED
        assert runs.effective_status(runs.load_run(cfg, bag_run.run_id)) == runs.STOPPED
        assert runs.effective_status(runs.load_run(cfg, other.run_id)) == runs.RUNNING
    finally:
        runs.stop_run(other)


def test_teleop_stop_without_active_runs(runner, tmp_path, monkeypatch):
    configure_paths(tmp_path, monkeypatch)
    result = runner.invoke(app, ["teleop", "stop"])
    assert result.exit_code == 0, all_output(result)
    assert "No active teleop or recording runs." in result.output


# -- replay -----------------------------------------------------------------


def test_teleop_replay_dry_run(runner, fake_ros_world, tmp_path, monkeypatch):
    configure_paths(tmp_path, monkeypatch)
    bag = tmp_path / "demo-bag"
    bag.mkdir()
    result = runner.invoke(app, ["teleop", "replay", str(bag), "--dry-run", "--loop"])
    assert result.exit_code == 0, all_output(result)
    assert f"bag play {bag} --loop" in flat(result)


def test_teleop_replay_tracked_run(runner, fake_ros_world, tmp_path, monkeypatch):
    runs_base, _datasets = configure_paths(tmp_path, monkeypatch)
    bag = tmp_path / "demo-bag"
    bag.mkdir()
    result = runner.invoke(app, ["teleop", "replay", str(bag)])
    assert result.exit_code == 0, all_output(result)
    assert "Replay started" in result.output
    assert "caasi logs" in result.output

    run_dir = wait_for_run(runs_base)
    manifest = manifest_of(run_dir)
    assert manifest["kind"] == "replay"
    assert manifest["backend"] == "ros2"
    assert manifest["name"] == "demo-bag"
    assert manifest["extra"] == {"bag": str(bag)}
    assert manifest["command"][1:] == ["bag", "play", str(bag)]
    assert (run_dir / "stdout.log").read_text(encoding="utf-8").strip() == f"bag play {bag}"


def test_teleop_replay_missing_bag(runner, fake_ros_world, tmp_path, monkeypatch):
    configure_paths(tmp_path, monkeypatch)
    result = runner.invoke(app, ["teleop", "replay", str(tmp_path / "nope")])
    assert result.exit_code == 1
    assert "not found" in all_output(result)


# -- registration -----------------------------------------------------------


def test_teleop_group_is_registered(runner):
    result = runner.invoke(app, ["teleop", "--help"])
    assert result.exit_code == 0, all_output(result)
    for verb in ("start", "record", "stop", "replay"):
        assert verb in result.output

    result = runner.invoke(app, ["teleop", "replay", "--help"])
    assert result.exit_code == 0, all_output(result)
    assert "Distinct from `caasi replay`" in flat(result)
