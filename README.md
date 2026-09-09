# Caasi

A lightweight, **CLI-first orchestration layer** for NVIDIA Isaac Sim, Isaac Lab and the
wider robotics ecosystem (ROS 2, Nav2, MoveIt 2, ros2\_control, ...).

Headless-first. CLI-first. Process-oriented. Visualization-independent.

**Documentation:** <https://a6y3ap.github.io/caasi/>

> **Note:** Caasi is an independent open-source project. It is not affiliated with,
> endorsed by, or an official product of NVIDIA.

## Philosophy

- **Use existing software. Don't reinvent it.** Caasi discovers, configures, launches,
  connects, monitors and manages tools that already exist.
- **Simulation is not visualization.** Run headless by default; attach a viewer only when needed.
- **Minimum required stack.** The Caasi process itself stays lightweight and never imports the
  heavy Isaac stack, PyTorch or rclpy — it only delegates to them.
- **Don't become another ROS.** ROS orchestration is delegated to the real `ros2` tooling.
- **Unix-friendly.** Small commands, `--json` output, sensible exit codes.

## Install

Requires Python 3.10+ on Linux. The Isaac stack, ROS 2 and PyTorch are *discovered*, not
installed, by Caasi.

```bash
pipx install caasi    # recommended: isolated env, `caasi` linked into ~/.local/bin (on PATH)
pip install caasi     # or into the active environment
```

Both install the `caasi` console script into the environment's `bin/`; pipx additionally
makes it available system-wide for your user (`pipx ensurepath` if `~/.local/bin` is not
on PATH). On PEP 668 distros (Ubuntu 23.04+, Debian 12+, Fedora) a bare system-wide
`pip install` is refused — use pipx or a dedicated venv:

```bash
python3 -m venv ~/.venvs/caasi && ~/.venvs/caasi/bin/pip install caasi
```

From source:

```bash
git clone https://github.com/a6y3ap/caasi.git && cd caasi
pip install -e .              # add pytest as well: pip install -e ".[dev]"
```

Upgrade: `pipx upgrade caasi` / `pip install -U caasi`. Shell completion:
`caasi --install-completion`.

## Quickstart

```bash
caasi doctor                    # diagnose the whole environment
caasi doctor --component nvidia # one section only
caasi gpu status                # GPU overview via nvidia-smi
caasi system status             # OS / CPU / RAM / disk summary
caasi info                      # CLI + configured/detected ecosystem versions
caasi config show               # effective configuration
caasi config set tools.isaacsim.default "6.0"
```

Every command supports `--help` (`caasi help gpu status` works too). The root listing is
grouped by topic; `CAASI_HELP_ORDER=alpha` flattens it to a–z. Data commands
support `--json` for scripting:

```bash
caasi gpu status --json | jq '.gpus[0]["memory.used"]'
if caasi doctor --quiet; then echo "environment ready"; fi
```

Simulations, training jobs and ROS launches start **detached** and are tracked as *runs* —
the CLI returns immediately and the work survives your terminal:

```bash
caasi sim run experiments/wave.yaml
caasi run list
caasi logs latest --follow      # Ctrl+C stops following, the run keeps going
caasi run status latest
```

## Command surface

| Group               | Commands                                                                                            | Reference                                                                        |
| ------------------- | --------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Environment         | `doctor`, `gpu status\|info\|memory\|doctor\|monitor\|test`, `system status\|doctor\|memory\|processes`, `info`, `version`   | [environment.html](https://a6y3ap.github.io/caasi/environment.html)       |
| Configuration       | `config show\|get\|set\|path\|tools\|catalog`                                                       | [configuration.html](https://a6y3ap.github.io/caasi/configuration.html)   |
| Projects            | `init`, `setup`, `project info\|validate`, `robot list\|create\|inspect\|info\|import\|validate`, `scene list\|create\|inspect\|import\|validate\|capture\|reconstruct`, `task` | [projects.html](https://a6y3ap.github.io/caasi/projects.html)             |
| Runs & logs         | `run list\|status\|logs\|attach\|stop\|pause\|resume\|delete\|inspect`, `logs`                      | [runs.html](https://a6y3ap.github.io/caasi/runs.html)                     |
| Simulation          | `sim run\|headless\|status\|check\|logs\|extensions\|stop\|pause\|resume`, `lab status\|run\|train\|play\|evaluate` | [simulation.html](https://a6y3ap.github.io/caasi/simulation.html)         |
| Training            | `train`, `benchmark start\|report`                                                                  | [training.html](https://a6y3ap.github.io/caasi/training.html)             |
| Data & sensors      | `dataset list\|generate\|inspect\|convert\|validate\|download`, `sensor list\|inspect\|test`, `vision status\|inspect\|test` | [data.html](https://a6y3ap.github.io/caasi/data.html)             |
| Review              | `replay`, `view rviz\|foxglove\|open3d\|attach\|run`                                                | [review.html](https://a6y3ap.github.io/caasi/review.html)                 |
| ROS ecosystem       | `ros status\|doctor\|list\|launch\|topic\|node\|graph\|service`, `nav status\|launch\|inspect\|test\|doctor`, `moveit status\|launch\|plan\|test\|doctor`, `control status\|list\|check\|doctor` | [ros.html](https://a6y3ap.github.io/caasi/ros.html) |
| GPU-accelerated robotics | `isaac-ros status\|list\|doctor\|launch`, `perception status\|camera\|pose\|detect\|segment\|inspect`, `slam status\|launch\|test\|benchmark`, `mapping status\|run\|inspect`, `motion status\|serve\|plan\|execute\|benchmark`, `nitros status\|doctor`, `pipeline inspect` | [accelerated.html](https://a6y3ap.github.io/caasi/accelerated.html) |
| Synthetic data & teleop | `synth status\|generate\|preview\|validate`, `teleop start\|record\|stop\|replay`                | [synthetic.html](https://a6y3ap.github.io/caasi/synthetic.html)           |
| Physics & foundation models | `physics status\|list\|run\|benchmark`, `warp status\|test\|benchmark`, `groot status\|setup\|run\|train\|evaluate`, `cosmos status\|run\|dataset` | [platform.html](https://a6y3ap.github.io/caasi/platform.html)     |
| Native & shell      | `native run\|sim\|lab\|ros`, `shell`                                                                | [native.html](https://a6y3ap.github.io/caasi/native.html)                 |
| Remote & containers | `remote list\|connect\|run`, `container list\|status\|check\|doctor\|run`                           | [remote.html](https://a6y3ap.github.io/caasi/remote.html)                 |

More examples:

```bash
caasi train experiments/ant.yaml --steps 500000 --envs 4096
caasi ros status && caasi nav launch --map maps/warehouse.yaml
caasi container run nvcr.io/nvidia/isaac-sim:5.1.0 ./runheadless.sh
caasi remote run gpu-box python train.py --steps 1000
caasi perception status && caasi slam launch --backend toolbox
caasi synth generate experiments/sdg.yaml --episodes 100
caasi teleop record -t /cmd_vel --name demo
caasi physics run experiments/wave.yaml --engine newton
caasi groot train configs/finetune.yaml --epochs 3
```

## Configuration

Global config lives at `~/.config/caasi/config.yaml`; a project-local `./caasi.yaml`
is merged on top. Override the global file with `CAASI_CONFIG` or `--config`;
`CAASI_LANG` overrides the language.

```yaml
language: en
tools:
  isaacsim:
    default: "6.0"
    versions:
      "6.0": { path: /opt/isaac-sim-6.0 }
      "5.1": { path: /opt/isaac-sim-5.1 }
remotes:
  gpu-box:
    host: 10.0.0.5
    user: robot
    port: 2222
    identity: ~/.ssh/id_ed25519
    path: ~/experiments
physics:
  default: newton            # engine used when `--engine` is omitted
catalog:
  slam:
    toolbox:
      packages: [slam_toolbox]   # re-point a capability when upstream renames it
```

Manage it with `caasi config show|get|set|path|tools|catalog`. The `catalog:` section is
how Caasi knows what to look for: each capability lists the packages, binaries, Python
modules, env vars and paths to probe, in that order. Nothing is imported — a new upstream
version is a config change, not a code change.

## Examples

[`examples/navigation.yaml`](examples/navigation.yaml) is a commented experiment config —
the input format shared by `sim run`, `train`, `benchmark start` and `dataset generate`:

```bash
caasi sim run examples/navigation.yaml --dry-run   # print the launch command, start nothing
```

## Tests

```bash
pytest
```

## Documentation

Read it at <https://a6y3ap.github.io/caasi/> or open
[`docs/index.html`](docs/index.html) directly in a browser — the pages are plain HTML in
[`docs/`](docs/) and need no build step.

The reference is split by concern: [environment](docs/environment.html) and
[configuration](docs/configuration.html) for the machine and the capability catalog;
[runs](docs/runs.html), [projects](docs/projects.html), [simulation](docs/simulation.html),
[training](docs/training.html), [data](docs/data.html) and [review](docs/review.html) for the
daily workflow; [ros](docs/ros.html) for ROS 2, Nav2, MoveIt 2 and ros2\_control;
[accelerated](docs/accelerated.html) for Isaac ROS, perception, SLAM, mapping, motion and
NITROS; [synthetic](docs/synthetic.html) for Replicator synthetic data and teleoperation;
[platform](docs/platform.html) for physics engines, Warp, GR00T and Cosmos; and
[native](docs/native.html) plus [remote](docs/remote.html) for the escape hatches.

## License

MIT © [a6y3ap](https://github.com/a6y3ap) — see [LICENSE](LICENSE).