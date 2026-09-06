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
git clone https://github.com/a6y3ap/caasi.git
cd caasi
pip install -e .              # add pytest as well: pip install -e ".[dev]"
```

This installs the `caasi` command. Shell completion is available:

```bash
caasi --install-completion
```

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

Every command supports `--help`. Data commands support `--json` for scripting:

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
| Environment         | `doctor`, `gpu status\|info\|memory\|test`, `system status\|memory\|processes`, `info`, `version`   | [environment.html](https://a6y3ap.github.io/caasi/environment.html)       |
| Configuration       | `config show\|get\|set\|path\|tools`                                                                | [configuration.html](https://a6y3ap.github.io/caasi/configuration.html)   |
| Projects            | `init`, `setup`, `project info\|validate`, `robot`, `scene`, `task`                                 | [projects.html](https://a6y3ap.github.io/caasi/projects.html)             |
| Runs & logs         | `run list\|status\|logs\|stop\|pause\|resume\|delete\|inspect`, `logs`                              | [runs.html](https://a6y3ap.github.io/caasi/runs.html)                     |
| Simulation          | `sim run\|status\|check\|stop\|pause\|resume`, `lab status`                                         | [simulation.html](https://a6y3ap.github.io/caasi/simulation.html)         |
| Training            | `train`, `benchmark start\|report`                                                                  | [training.html](https://a6y3ap.github.io/caasi/training.html)             |
| Data & sensors      | `dataset generate\|inspect\|convert\|validate`, `sensor list\|inspect\|test`, `vision status\|inspect\|test` | [data.html](https://a6y3ap.github.io/caasi/data.html)             |
| Review              | `replay`, `view rviz\|foxglove\|open3d\|attach`                                                     | [review.html](https://a6y3ap.github.io/caasi/review.html)                 |
| ROS ecosystem       | `ros status\|doctor\|list\|launch\|topic\|node\|graph`, `nav status\|launch\|inspect\|test`, `moveit status\|launch\|plan\|test`, `control status\|list\|check` | [ros.html](https://a6y3ap.github.io/caasi/ros.html) |
| Native & shell      | `native run\|sim\|lab\|ros`, `shell`                                                                | [native.html](https://a6y3ap.github.io/caasi/native.html)                 |
| Remote & containers | `remote list\|connect\|run`, `container list\|check\|run`                                           | [remote.html](https://a6y3ap.github.io/caasi/remote.html)                 |

More examples:

```bash
caasi train experiments/ant.yaml --steps 500000 --envs 4096
caasi ros status && caasi nav launch --map maps/warehouse.yaml
caasi container run nvcr.io/nvidia/isaac-sim:5.1.0 ./runheadless.sh
caasi remote run gpu-box python train.py --steps 1000
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
```

Manage it with `caasi config show|get|set|path|tools`.

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
[`docs/index.html`](docs/index.html) directly in a browser.

## License

MIT © [a6y3ap](https://github.com/a6y3ap) — see [LICENSE](LICENSE).
