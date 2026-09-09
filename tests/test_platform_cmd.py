"""Tests for the Tier-4 platform groups: physics, warp, groot, cosmos.

Plan §10 row ``test_platform_cmd.py``: physics list/status/run --engine newton
(using ``fake_isaac_tree``'s ``isaac-sim.newton.sh``) and benchmark; warp
status/test with a fake interpreter; groot status/setup/train against a fake
repo; cosmos status/run against a fake CLI. Every command delegates — the
assertions are about *which* upstream command Caasi builds, never about
physics, GPU compute or foundation-model behaviour.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import textwrap

import yaml

from caasi import state
from caasi.cli.main import app
from caasi.core import catalog

from .conftest import all_output
from .test_ros_cmd import no_ros2, wait_for_run
from .test_synth_cmd import manifest_of

#: Experiment script: reports the engine env var Caasi exported to it.
GEN_SCRIPT = textwrap.dedent(
    """\
    import argparse
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true")
    args, unknown = parser.parse_known_args()
    print("engine:", os.environ.get("CAASI_PHYSICS_ENGINE"))
    print("headless:", args.headless, "unknown:", unknown)
    """
)

FINETUNE_SCRIPT = textwrap.dedent(
    """\
    import sys

    print("finetune", sys.argv[1])
    print("extra", sys.argv[2:])
    """
)

EVAL_SCRIPT = textwrap.dedent(
    """\
    import sys

    print("eval", sys.argv[1])
    """
)


def configure(tmp_path, monkeypatch, root=None, extra=None):
    """CAASI_CONFIG with tmp runs, an optional Isaac Sim root and extra keys."""
    data = {"paths": {"runs": str(tmp_path / "runs")}}
    if root is not None:
        data["tools"] = {
            "isaacsim": {
                "default": "5.1",
                "versions": {
                    "5.1": {"path": str(root), "python": str(root / "python.sh")}
                },
            }
        }
    data.update(extra or {})
    cfg_file = tmp_path / "caasi-platform.yaml"
    cfg_file.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setenv("CAASI_CONFIG", str(cfg_file))
    catalog.clear_cache()
    state.reset()
    return tmp_path / "runs"


def make_experiment(tmp_path, name="physics-exp"):
    (tmp_path / "gen.py").write_text(GEN_SCRIPT, encoding="utf-8")
    config = tmp_path / "experiment.yaml"
    config.write_text(
        yaml.safe_dump({"name": name, "backend": "sim", "script": "gen.py"}),
        encoding="utf-8",
    )
    return config


def write_script(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def fake_module_versions(monkeypatch, mapping):
    """Make the catalog's python-distribution probe report *mapping*."""
    from caasi.utils import pydist

    def pip_version(*names):
        for name in names:
            if name in mapping:
                return mapping[name]
        return None

    monkeypatch.setattr(pydist, "pip_version", pip_version)


def make_groot_repo(tmp_path, monkeypatch, *, scripts=True, post_install=True, interpreter=False):
    """A fake Isaac-GR00T checkout discovered through ``GR00T_PATH``."""
    repo = tmp_path / "Isaac-GR00T"
    (repo / "scripts").mkdir(parents=True)
    if post_install:
        write_script(
            repo / "post_install.sh",
            """\
            #!/usr/bin/env bash
            echo "post install done"
            """,
        )
    if interpreter:
        write_script(
            repo / "python.sh",
            """\
            #!/usr/bin/env bash
            exec "${CAASI_FAKE_ISAAC_PYTHON:-python3}" "$@"
            """,
        )
    if scripts:
        (repo / "scripts" / "finetune.py").write_text(FINETUNE_SCRIPT, encoding="utf-8")
        (repo / "scripts" / "eval.py").write_text(EVAL_SCRIPT, encoding="utf-8")
    monkeypatch.setenv("GR00T_PATH", str(repo))
    catalog.clear_cache()
    state.reset()
    return repo


def fake_binary(tmp_path, monkeypatch, name, body):
    """Put a fake executable first on PATH (the catalog probes binaries there)."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    write_script(bin_dir / name, body)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    catalog.clear_cache()
    return bin_dir / name


# -- caasi physics ----------------------------------------------------------


def test_physics_status(runner, fake_isaac_tree, tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, fake_isaac_tree)
    result = runner.invoke(app, ["physics", "status", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["domain"] == "physics"
    assert data["tool"] == "isaacsim"
    assert data["root"] == str(fake_isaac_tree)
    assert data["launcher"] == str(fake_isaac_tree / "python.sh")
    assert data["engine"] == "physx"
    caps = {item["key"]: item for item in data["capabilities"]}
    assert caps["physx"]["found"] is True
    assert caps["physx"]["how"] == "path"
    assert caps["newton"]["found"] is True
    assert caps["newton"]["value"] == str(fake_isaac_tree / "isaac-sim.newton.sh")

    result = runner.invoke(app, ["physics", "status"])
    assert result.exit_code == 0, all_output(result)
    assert "Physics Engines" in result.output
    assert "physx" in result.output


def test_physics_list(runner, fake_isaac_tree, tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, fake_isaac_tree)
    result = runner.invoke(app, ["physics", "list", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["domain"] == "physics"
    assert data["default"] == "physx"
    assert [row["engine"] for row in data["engines"]] == [
        "physx",
        "newton",
        "warp",
        "mujoco",
        "gazebo",
    ]
    rows = {row["engine"]: row for row in data["engines"]}
    assert rows["physx"]["installed"] is True
    assert rows["physx"]["how"] == "path"
    assert rows["physx"]["value"] == str(fake_isaac_tree / "extsPhysics" / "omni.physx")
    assert rows["physx"]["launcher"] is None  # a directory, not a launcher script
    assert rows["newton"]["installed"] is True
    assert rows["newton"]["launcher"] == str(fake_isaac_tree / "isaac-sim.newton.sh")
    assert rows["warp"]["installed"] is False
    assert rows["mujoco"]["installed"] is False

    result = runner.invoke(app, ["physics", "list"])
    assert result.exit_code == 0, all_output(result)
    assert "Engine" in result.output
    assert "Found via" in result.output
    assert "newton" in result.output
    assert "Default engine: physx" in " ".join(result.output.split())


def test_physics_run_dry_run_newton(runner, fake_isaac_tree, tmp_path, monkeypatch):
    config = make_experiment(tmp_path)
    runs_base = configure(tmp_path, monkeypatch, fake_isaac_tree)
    result = runner.invoke(
        app, ["physics", "run", str(config), "--engine", "newton", "--dry-run"]
    )
    assert result.exit_code == 0, all_output(result)
    flat = " ".join(all_output(result).split())
    assert "Dry run — nothing was started:" in flat
    assert str(fake_isaac_tree / "isaac-sim.newton.sh") in flat
    assert str(tmp_path / "gen.py") in flat
    assert "--headless" in flat
    assert "engine: newton (CAASI_PHYSICS_ENGINE)" in flat
    assert not runs_base.exists()


def test_physics_run_dry_run_default_engine(runner, fake_isaac_tree, tmp_path, monkeypatch):
    config = make_experiment(tmp_path)
    configure(tmp_path, monkeypatch, fake_isaac_tree)
    result = runner.invoke(app, ["physics", "run", str(config), "--dry-run"])
    assert result.exit_code == 0, all_output(result)
    flat = " ".join(all_output(result).split())
    # physx resolves no launcher script, so the experiment's python.sh stays.
    assert str(fake_isaac_tree / "python.sh") in flat
    assert "isaac-sim.newton.sh" not in flat
    assert "engine: physx (CAASI_PHYSICS_ENGINE)" in flat


def test_physics_run_tracked_newton(runner, fake_isaac_tree, tmp_path, monkeypatch):
    config = make_experiment(tmp_path)
    runs_base = configure(tmp_path, monkeypatch, fake_isaac_tree)
    # The launcher reports the engine env var Caasi exports to it.
    write_script(
        fake_isaac_tree / "isaac-sim.newton.sh",
        """\
        #!/usr/bin/env bash
        echo "newton launcher engine=$CAASI_PHYSICS_ENGINE args=$*"
        """,
    )

    result = runner.invoke(
        app, ["physics", "run", str(config), "--engine", "newton", "--name", "newton-run"]
    )
    assert result.exit_code == 0, all_output(result)
    assert "Started run" in result.output

    run_dir = wait_for_run(runs_base)
    assert (run_dir / "exit_code").read_text().strip() == "0", (
        run_dir / "stderr.log"
    ).read_text(encoding="utf-8")
    manifest = manifest_of(run_dir)
    assert manifest["name"] == "newton-run"
    assert manifest["kind"] == "run"
    assert manifest["backend"] == "sim"
    assert manifest["command"][0] == str(fake_isaac_tree / "isaac-sim.newton.sh")
    assert manifest["extra"]["engine"] == "newton"
    assert manifest["extra"]["experiment"] == str(config.resolve())
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    assert "newton launcher engine=newton" in stdout
    assert "--headless" in stdout


def test_physics_run_tracked_default_engine(runner, fake_isaac_tree, tmp_path, monkeypatch):
    config = make_experiment(tmp_path)
    runs_base = configure(tmp_path, monkeypatch, fake_isaac_tree)

    result = runner.invoke(app, ["physics", "run", str(config)])
    assert result.exit_code == 0, all_output(result)

    run_dir = wait_for_run(runs_base)
    assert (run_dir / "exit_code").read_text().strip() == "0", (
        run_dir / "stderr.log"
    ).read_text(encoding="utf-8")
    manifest = manifest_of(run_dir)
    assert manifest["name"] == "physics-exp"
    assert manifest["command"][0] == str(fake_isaac_tree / "python.sh")
    assert manifest["extra"]["engine"] == "physx"
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    assert "engine: physx" in stdout  # CAASI_PHYSICS_ENGINE reached the script
    assert "headless: True" in stdout


def test_physics_run_unknown_engine(runner, fake_isaac_tree, tmp_path, monkeypatch):
    config = make_experiment(tmp_path)
    configure(tmp_path, monkeypatch, fake_isaac_tree)
    result = runner.invoke(
        app, ["physics", "run", str(config), "--engine", "bullet", "--dry-run"]
    )
    assert result.exit_code == 1
    flat = " ".join(all_output(result).split())
    assert "Unknown physics engine 'bullet'." in flat
    assert "Known: physx, newton, warp, mujoco, gazebo" in flat


def test_physics_run_engine_not_installed(runner, fake_isaac_tree, tmp_path, monkeypatch):
    config = make_experiment(tmp_path)
    configure(tmp_path, monkeypatch, fake_isaac_tree)
    result = runner.invoke(
        app, ["physics", "run", str(config), "--engine", "mujoco", "--dry-run"]
    )
    assert result.exit_code == 1
    flat = " ".join(all_output(result).split())
    assert "'mujoco' is not available (mujoco)." in flat
    assert "caasi config set catalog.physics.mujoco.modules" in flat


def test_physics_run_missing_experiment(runner, fake_isaac_tree, tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, fake_isaac_tree)
    result = runner.invoke(
        app, ["physics", "run", str(tmp_path / "nope.yaml"), "--dry-run"]
    )
    assert result.exit_code == 1
    assert "experiment config not found" in " ".join(all_output(result).split())


def test_physics_benchmark_tracked(runner, fake_isaac_tree, tmp_path, monkeypatch):
    config = make_experiment(tmp_path)
    runs_base = configure(tmp_path, monkeypatch, fake_isaac_tree)

    result = runner.invoke(
        app, ["physics", "benchmark", str(config), "--engine", "newton", "--steps", "10"]
    )
    assert result.exit_code == 0, all_output(result)
    assert "Started run" in result.output
    flat = " ".join(result.output.split())
    assert "caasi benchmark report" in flat

    run_dir = wait_for_run(runs_base)
    assert (run_dir / "exit_code").read_text().strip() == "0"
    manifest = manifest_of(run_dir)
    assert manifest["kind"] == "benchmark"
    assert manifest["backend"] == "sim"
    assert manifest["extra"]["engine"] == "newton"
    assert manifest["command"][-2:] == ["--steps", "10"]  # pass-through arguments


def test_physics_configured_launcher(runner, fake_isaac_tree, tmp_path, monkeypatch):
    """`physics.engines.<key>.launcher` wins over the catalog-resolved one."""
    config = make_experiment(tmp_path)
    configure(
        tmp_path,
        monkeypatch,
        fake_isaac_tree,
        extra={"physics": {"engines": {"newton": {"launcher": "isaac-sim.sh"}}}},
    )
    result = runner.invoke(
        app, ["physics", "run", str(config), "--engine", "newton", "--dry-run"]
    )
    assert result.exit_code == 0, all_output(result)
    flat = " ".join(all_output(result).split())
    assert str(fake_isaac_tree / "isaac-sim.sh") in flat
    assert "isaac-sim.newton.sh" not in flat


def test_physics_default_engine_from_config(runner, fake_isaac_tree, tmp_path, monkeypatch):
    config = make_experiment(tmp_path)
    configure(
        tmp_path, monkeypatch, fake_isaac_tree, extra={"physics": {"default": "newton"}}
    )

    result = runner.invoke(app, ["physics", "status", "--json"])
    assert result.exit_code == 0, all_output(result)
    assert json.loads(result.output)["engine"] == "newton"

    result = runner.invoke(app, ["physics", "run", str(config), "--dry-run"])
    assert result.exit_code == 0, all_output(result)
    flat = " ".join(all_output(result).split())
    assert str(fake_isaac_tree / "isaac-sim.newton.sh") in flat
    assert "engine: newton (CAASI_PHYSICS_ENGINE)" in flat


# -- caasi warp -------------------------------------------------------------


def test_warp_status(runner, fake_isaac_tree, tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, fake_isaac_tree)
    result = runner.invoke(app, ["warp", "status", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["domain"] == "warp"
    # Isaac Sim's interpreter is the one that can see the Warp it ships.
    assert data["launcher"] == str(fake_isaac_tree / "python.sh")
    assert [item["key"] for item in data["capabilities"]] == ["warp"]
    assert data["capabilities"][0]["found"] is False  # not a caasi dependency

    result = runner.invoke(app, ["warp", "status"])
    assert result.exit_code == 0, all_output(result)
    assert "NVIDIA Warp" in result.output


def test_warp_status_without_isaac(runner, tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    result = runner.invoke(app, ["warp", "status", "--json"])
    assert result.exit_code == 0, all_output(result)
    assert json.loads(result.output)["launcher"] == sys.executable


def test_warp_test_reports_devices(runner, fake_isaac_tree, tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, fake_isaac_tree)
    fake_module_versions(monkeypatch, {"warp": "1.4.0"})
    monkeypatch.setenv(
        "CAASI_FAKE_ISAAC_PYTHON",
        str(
            write_script(
                tmp_path / "fake-warp-python",
                """\
                #!/usr/bin/env bash
                echo "cpu"
                echo "cuda:0 (NVIDIA FakeGPU)"
                """,
            )
        ),
    )

    result = runner.invoke(app, ["warp", "test"])
    assert result.exit_code == 0, all_output(result)
    assert "Warp initialized. Devices:" in result.output
    assert "cuda:0 (NVIDIA FakeGPU)" in result.output

    result = runner.invoke(app, ["warp", "test", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["domain"] == "warp"
    assert data["python"] == str(fake_isaac_tree / "python.sh")
    assert data["returncode"] == 0
    assert data["devices"] == ["cpu", "cuda:0 (NVIDIA FakeGPU)"]


def test_warp_test_failure(runner, fake_isaac_tree, tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, fake_isaac_tree)
    fake_module_versions(monkeypatch, {"warp": "1.4.0"})
    monkeypatch.setenv(
        "CAASI_FAKE_ISAAC_PYTHON",
        str(
            write_script(
                tmp_path / "broken-warp-python",
                """\
                #!/usr/bin/env bash
                echo "RuntimeError: no CUDA device" >&2
                exit 1
                """,
            )
        ),
    )

    result = runner.invoke(app, ["warp", "test"])
    assert result.exit_code == 1
    flat = " ".join(all_output(result).split())
    assert "Warp test failed:" in flat
    assert "RuntimeError: no CUDA device" in flat

    result = runner.invoke(app, ["warp", "test", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["returncode"] == 1
    assert data["devices"] == []


def test_warp_test_requires_warp(runner, tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    result = runner.invoke(app, ["warp", "test"])
    assert result.exit_code == 1
    flat = " ".join(all_output(result).split())
    assert "No warp capability is installed." in flat
    assert "caasi config set catalog.warp.<capability>.<field>" in flat


def test_warp_benchmark_no_args(runner, tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    result = runner.invoke(app, ["warp", "benchmark"])
    assert result.exit_code == 1
    flat = " ".join(all_output(result).split())
    assert "Nothing to benchmark" in flat
    assert "caasi warp benchmark bench.py" in flat


def test_warp_benchmark_dry_run_and_tracked(runner, tmp_path, monkeypatch):
    runs_base = configure(tmp_path, monkeypatch)
    bench = tmp_path / "bench.py"
    bench.write_text("print('bench ok')\n", encoding="utf-8")

    result = runner.invoke(app, ["warp", "benchmark", str(bench), "--dry-run"])
    assert result.exit_code == 0, all_output(result)
    flat = " ".join(all_output(result).split())
    assert "Dry run — nothing was launched:" in flat
    assert f"command: {sys.executable} {bench}" in flat

    result = runner.invoke(app, ["warp", "benchmark", str(bench)])
    assert result.exit_code == 0, all_output(result)
    assert "caasi benchmark report" in " ".join(result.output.split())

    run_dir = wait_for_run(runs_base)
    assert (run_dir / "exit_code").read_text().strip() == "0"
    manifest = manifest_of(run_dir)
    assert manifest["name"] == "warp"
    assert manifest["kind"] == "benchmark"
    assert manifest["backend"] == "python"
    assert manifest["extra"] == {"domain": "warp"}
    assert "bench ok" in (run_dir / "stdout.log").read_text(encoding="utf-8")


# -- caasi groot ------------------------------------------------------------


def test_groot_status(runner, tmp_path, monkeypatch):
    repo = make_groot_repo(tmp_path, monkeypatch)
    runs_base = configure(tmp_path, monkeypatch)
    result = runner.invoke(app, ["groot", "status", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["domain"] == "groot"
    assert data["tool"] == "groot"
    assert data["root"] == str(repo)
    assert data["launcher"] == sys.executable  # the repo ships no python.sh here
    assert (data["installed"], data["total"]) == (1, 5)
    caps = {item["key"]: item for item in data["capabilities"]}
    assert caps["repo"]["found"] is True
    assert caps["repo"]["how"] == "env"
    assert caps["repo"]["value"] == str(repo)
    assert caps["module"]["found"] is False
    # Script capabilities resolve their path but are never "found" by probing.
    assert caps["train"]["found"] is False
    assert caps["train"]["script"] == str(repo / "scripts" / "finetune.py")

    result = runner.invoke(app, ["groot", "status"])
    assert result.exit_code == 0, all_output(result)
    assert "Isaac GR00T" in result.output
    assert "1 of 5 capabilities installed." in result.output
    assert not runs_base.exists()


def test_groot_setup_prints_steps(runner, tmp_path, monkeypatch):
    repo = make_groot_repo(tmp_path, monkeypatch)
    runs_base = configure(tmp_path, monkeypatch)

    result = runner.invoke(app, ["groot", "setup"])
    assert result.exit_code == 0, all_output(result)
    flat = " ".join(all_output(result).split())
    assert f"GR00T install steps ({repo}) — not executed:" in flat
    assert f"command: {repo / 'post_install.sh'}" in flat
    assert f"cwd: {repo}" in flat
    assert "caasi groot setup --execute" in flat
    assert not runs_base.exists()  # printing never starts a run

    result = runner.invoke(app, ["groot", "setup", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data == {
        "domain": "groot",
        "executed": False,
        "command": [str(repo / "post_install.sh")],
        "cwd": str(repo),
    }


def test_groot_setup_executes(runner, tmp_path, monkeypatch):
    repo = make_groot_repo(tmp_path, monkeypatch)
    runs_base = configure(tmp_path, monkeypatch)

    result = runner.invoke(app, ["groot", "setup", "--execute"])
    assert result.exit_code == 0, all_output(result)
    assert "Started run" in result.output

    run_dir = wait_for_run(runs_base)
    assert (run_dir / "exit_code").read_text().strip() == "0", (
        run_dir / "stderr.log"
    ).read_text(encoding="utf-8")
    manifest = manifest_of(run_dir)
    assert manifest["name"] == "groot-setup"
    assert manifest["kind"] == "setup"
    assert manifest["backend"] == "python"
    assert manifest["command"] == [str(repo / "post_install.sh")]
    assert manifest["cwd"] == str(repo)
    assert manifest["extra"] == {"domain": "groot", "repo": str(repo)}
    assert "post install done" in (run_dir / "stdout.log").read_text(encoding="utf-8")


def test_groot_setup_pip_fallback(runner, tmp_path, monkeypatch):
    """No post_install.sh → the repo's own editable install, through its python."""
    repo = make_groot_repo(tmp_path, monkeypatch, post_install=False)
    configure(tmp_path, monkeypatch)
    result = runner.invoke(app, ["groot", "setup", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["executed"] is False
    assert data["command"] == [sys.executable, "-m", "pip", "install", "-e", "."]
    assert data["cwd"] == str(repo)


def test_groot_setup_without_repo(runner, tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    result = runner.invoke(app, ["groot", "setup"])
    assert result.exit_code == 1
    flat = " ".join(all_output(result).split())
    assert "The GR00T repository was not found (GR00T_PATH, ~/Isaac-GR00T" in flat
    assert "caasi config set catalog.groot.repo.paths" in flat


def test_groot_train_dry_run(runner, tmp_path, monkeypatch):
    repo = make_groot_repo(tmp_path, monkeypatch)
    runs_base = configure(tmp_path, monkeypatch)
    policy = tmp_path / "policy.yaml"
    policy.write_text("model: gr00t\n", encoding="utf-8")

    result = runner.invoke(
        app, ["groot", "train", str(policy), "--dry-run", "--epochs", "3"]
    )
    assert result.exit_code == 0, all_output(result)
    flat = " ".join(all_output(result).split())
    assert "Dry run — nothing was launched:" in flat
    assert f"command: {sys.executable} {repo / 'scripts' / 'finetune.py'} {policy} --epochs 3" in flat
    assert f"cwd: {repo}" in flat
    assert not runs_base.exists()


def test_groot_train_tracked(runner, tmp_path, monkeypatch):
    """The repo's own interpreter runs the repo's own script."""
    repo = make_groot_repo(tmp_path, monkeypatch, interpreter=True)
    runs_base = configure(tmp_path, monkeypatch)
    policy = tmp_path / "policy.yaml"
    policy.write_text("model: gr00t\n", encoding="utf-8")

    result = runner.invoke(app, ["groot", "train", str(policy), "--epochs", "3"])
    assert result.exit_code == 0, all_output(result)

    run_dir = wait_for_run(runs_base)
    assert (run_dir / "exit_code").read_text().strip() == "0", (
        run_dir / "stderr.log"
    ).read_text(encoding="utf-8")
    manifest = manifest_of(run_dir)
    assert manifest["name"] == "policy"
    assert manifest["kind"] == "train"
    assert manifest["backend"] == "groot"
    assert manifest["command"] == [
        str(repo / "python.sh"),
        str(repo / "scripts" / "finetune.py"),
        str(policy),
        "--epochs",
        "3",
    ]
    assert manifest["cwd"] == str(repo)
    assert manifest["extra"] == {
        "domain": "groot",
        "capability": "train",
        "config": str(policy),
    }
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    assert f"finetune {policy}" in stdout
    assert "extra ['--epochs', '3']" in stdout


def test_groot_train_missing_script(runner, tmp_path, monkeypatch):
    repo = make_groot_repo(tmp_path, monkeypatch, scripts=False)
    configure(tmp_path, monkeypatch)
    policy = tmp_path / "policy.yaml"
    policy.write_text("model: gr00t\n", encoding="utf-8")

    result = runner.invoke(app, ["groot", "train", str(policy), "--dry-run"])
    assert result.exit_code == 1
    flat = " ".join(all_output(result).split())
    assert f"{repo} has no scripts/finetune.py." in flat
    assert "caasi config set catalog.groot.train.script" in flat


def test_groot_train_missing_config(runner, tmp_path, monkeypatch):
    make_groot_repo(tmp_path, monkeypatch)
    configure(tmp_path, monkeypatch)
    result = runner.invoke(
        app, ["groot", "train", str(tmp_path / "nope.yaml"), "--dry-run"]
    )
    assert result.exit_code == 1
    assert "config not found:" in " ".join(all_output(result).split())


def test_groot_evaluate_dry_run(runner, tmp_path, monkeypatch):
    repo = make_groot_repo(tmp_path, monkeypatch)
    configure(tmp_path, monkeypatch)
    policy = tmp_path / "policy.yaml"
    policy.write_text("model: gr00t\n", encoding="utf-8")

    result = runner.invoke(app, ["groot", "evaluate", str(policy), "--dry-run"])
    assert result.exit_code == 0, all_output(result)
    flat = " ".join(all_output(result).split())
    assert f"command: {sys.executable} {repo / 'scripts' / 'eval.py'} {policy}" in flat
    assert f"cwd: {repo}" in flat


def test_groot_run_module_absent(runner, tmp_path, monkeypatch):
    make_groot_repo(tmp_path, monkeypatch)
    configure(tmp_path, monkeypatch)
    result = runner.invoke(app, ["groot", "run", "--dry-run"])
    assert result.exit_code == 1
    flat = " ".join(all_output(result).split())
    assert "'module' is not available (gr00t)." in flat
    assert "caasi config set catalog.groot.module.modules" in flat


def test_groot_run_module_and_script_backends(runner, tmp_path, monkeypatch):
    repo = make_groot_repo(tmp_path, monkeypatch)
    configure(tmp_path, monkeypatch)

    fake_module_versions(monkeypatch, {"gr00t": "0.2.0"})
    catalog.clear_cache()
    result = runner.invoke(app, ["groot", "run", "--dry-run", "demo"])
    assert result.exit_code == 0, all_output(result)
    flat = " ".join(all_output(result).split())
    assert f"command: {sys.executable} -m gr00t demo" in flat
    assert f"cwd: {repo}" in flat

    # A catalog script works without the module installed.
    result = runner.invoke(app, ["groot", "run", "--backend", "train", "--dry-run"])
    assert result.exit_code == 0, all_output(result)
    flat = " ".join(all_output(result).split())
    assert f"command: {sys.executable} {repo / 'scripts' / 'finetune.py'}" in flat


# -- caasi cosmos -----------------------------------------------------------


def test_cosmos_status_nothing_installed(runner, tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    monkeypatch.setattr("caasi.utils.shell.which", lambda name: None)
    fake_module_versions(monkeypatch, {})

    result = runner.invoke(app, ["cosmos", "status", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["domain"] == "cosmos"
    assert (data["installed"], data["total"]) == (0, 2)
    assert [item["key"] for item in data["capabilities"]] == ["module", "cli"]
    assert all(item["found"] is False for item in data["capabilities"])

    result = runner.invoke(app, ["cosmos", "status"])
    assert result.exit_code == 0, all_output(result)
    assert "NVIDIA Cosmos" in result.output
    assert "0 of 2 capabilities installed." in result.output


def test_cosmos_run_dry_run_and_tracked(runner, tmp_path, monkeypatch):
    runs_base = configure(tmp_path, monkeypatch)
    binary = fake_binary(
        tmp_path,
        monkeypatch,
        "cosmos",
        """\
        #!/usr/bin/env bash
        echo "cosmos $*"
        """,
    )

    result = runner.invoke(
        app, ["cosmos", "run", "predict", "--checkpoint", "model", "--dry-run"]
    )
    assert result.exit_code == 0, all_output(result)
    flat = " ".join(all_output(result).split())
    assert "Dry run — nothing was launched:" in flat
    assert f"command: {binary} predict --checkpoint model" in flat
    assert not runs_base.exists()

    result = runner.invoke(app, ["cosmos", "run", "predict", "--checkpoint", "model"])
    assert result.exit_code == 0, all_output(result)
    assert "Started run" in result.output

    run_dir = wait_for_run(runs_base)
    assert (run_dir / "exit_code").read_text().strip() == "0", (
        run_dir / "stderr.log"
    ).read_text(encoding="utf-8")
    manifest = manifest_of(run_dir)
    assert manifest["name"] == "cosmos"
    assert manifest["kind"] == "cosmos"
    assert manifest["backend"] == "cosmos"
    assert manifest["command"] == [str(binary), "predict", "--checkpoint", "model"]
    assert manifest["extra"] == {"domain": "cosmos"}
    assert "cosmos predict --checkpoint model" in (run_dir / "stdout.log").read_text(
        encoding="utf-8"
    )


def test_cosmos_dataset_tracked(runner, tmp_path, monkeypatch):
    runs_base = configure(tmp_path, monkeypatch)
    fake_binary(
        tmp_path,
        monkeypatch,
        "cosmos",
        """\
        #!/usr/bin/env bash
        echo "cosmos $*"
        """,
    )

    result = runner.invoke(app, ["cosmos", "dataset", "prepare", "clips/"])
    assert result.exit_code == 0, all_output(result)

    run_dir = wait_for_run(runs_base)
    assert (run_dir / "exit_code").read_text().strip() == "0"
    manifest = manifest_of(run_dir)
    assert manifest["name"] == "cosmos-dataset"
    assert manifest["kind"] == "dataset"
    assert manifest["command"][-2:] == ["prepare", "clips/"]
    assert "cosmos prepare clips/" in (run_dir / "stdout.log").read_text(encoding="utf-8")


def test_cosmos_run_no_args(runner, tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    result = runner.invoke(app, ["cosmos", "run"])
    assert result.exit_code == 1
    flat = " ".join(all_output(result).split())
    assert "Nothing to forward" in flat
    assert "caasi cosmos run <args>" in flat


def test_cosmos_run_nothing_installed(runner, tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    monkeypatch.setattr("caasi.utils.shell.which", lambda name: None)
    fake_module_versions(monkeypatch, {})
    result = runner.invoke(app, ["cosmos", "run", "predict", "--dry-run"])
    assert result.exit_code == 1
    flat = " ".join(all_output(result).split())
    assert "No cosmos capability is installed." in flat
    assert "caasi config set catalog.cosmos.cli.binaries" in flat


# -- registration and doctor ------------------------------------------------


def test_platform_groups_are_registered(runner):
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, all_output(result)
    for group in ("physics", "warp", "groot", "cosmos"):
        assert group in result.output

    verbs = {
        "physics": ("status", "list", "run", "benchmark"),
        "warp": ("status", "test", "benchmark"),
        "groot": ("status", "setup", "run", "train", "evaluate"),
        "cosmos": ("status", "run", "dataset"),
    }
    for group, expected in verbs.items():
        result = runner.invoke(app, [group, "--help"])
        assert result.exit_code == 0, all_output(result)
        for verb in expected:
            assert verb in result.output


def test_doctor_component_physics(runner, fake_isaac_tree, tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, fake_isaac_tree)
    result = runner.invoke(app, ["doctor", "--component", "physics", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    rows = {row["name"]: row for row in data["checks"]}
    assert rows["PhysX"]["status"] == "ok"
    assert rows["PhysX"]["section"] == "physics"
    assert rows["Newton"]["status"] == "ok"
    assert str(fake_isaac_tree / "isaac-sim.newton.sh") in rows["Newton"]["detail"]
    assert rows["MuJoCo"]["status"] == "skip"  # optional engines never fail doctor


def test_doctor_component_platform(runner, tmp_path, monkeypatch):
    repo = make_groot_repo(tmp_path, monkeypatch)
    configure(tmp_path, monkeypatch)
    no_ros2(monkeypatch, tmp_path)

    result = runner.invoke(app, ["doctor", "--component", "platform", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    rows = {row["name"]: row for row in data["checks"]}
    assert rows["GR00T repository"]["status"] == "ok"
    assert rows["GR00T repository"]["detail"] == str(repo)
    assert rows["gr00t package"]["status"] == "skip"
    assert rows["Cosmos package"]["status"] == "skip"
    assert rows["Cosmos CLI"]["status"] == "skip"
    assert rows["NuRec (neural reconstruction)"]["status"] == "skip"
    # Teleop needs the ROS CLI: without it the rows skip, they never fail.
    assert rows["Keyboard teleop"]["status"] == "skip"
    assert rows["Keyboard teleop"]["detail"] == "skipped (ROS 2 CLI unavailable)"
    assert rows["Joystick teleop"]["status"] == "skip"
