# Changelog

## [Unreleased]

### Added
- `--layout rich|plain` — bordered tables or space-aligned columns, also settable via
  `CAASI_LAYOUT` or `layout:` in `config.yaml`; resolved flag > env > config like `--lang`
- `CAASI_HELP_ORDER` / `help_order:` in `config.yaml` — `grouped` (default), `core`
  (entry points first, then a–z) or `alpha` (flat a–z) ordering for the root command
  listing; resolved env > config, with no flag because `--help` exits before flags are read

### Changed
- Table layout defaults to `rich` (bordered) again — the space-aligned columns introduced
  in 0.2.0 are now opt-in via `--layout plain`
- Root help lists commands in titled groups (Start here, Environment, Projects & runs,
  Simulation & training, Data & teleop, ROS 2, GPU-accelerated, Native/models & remote),
  alphabetical within each group; subcommand listings keep their existing order

## [0.2.0]

### Added
- GPU-accelerated robotics groups: `isaac-ros`, `perception`, `slam`, `mapping`, `motion`,
  `nitros`, `pipeline inspect` — discover Isaac ROS / NITROS / nvblox / cuMotion stacks,
  launch them as tracked runs, verify graphs with `slam test` and per-group doctors
- Synthetic data & teleop: `synth` (Replicator SDG generate/preview/validate) and
  `teleop` (keyboard/joystick drive, rosbag2 record/replay)
- Physics & foundation models: `physics` (run/benchmark experiments on PhysX, Newton,
  Warp, MuJoCo or Gazebo), `warp` (kernel test/benchmark), `groot` (GR00T setup, run,
  train, evaluate via the repo's own interpreter), `cosmos` (Cosmos/NuRec delegation)
- Capability catalog: every upstream probe (packages, binaries, modules, env vars, paths,
  launch files, scripts) is data and fully overridable — `caasi config catalog [domain]`,
  `caasi config set catalog.<domain>.<capability>.<field>`; upstream renames are config edits
- Subcommands: `sim headless|logs|extensions`, `lab run|train|play|evaluate`,
  `ros service`, `nav|moveit|control|gpu|system|container doctor`, `gpu monitor`,
  `run attach`, `container status`, `view run`, `dataset list|download`,
  `robot import|validate`, `scene import|validate|capture|reconstruct`, `config catalog`
- USD tool delegation (`usdcat`, `usdchecker`, `usdconvert`, `usdview`) and URDF/MJCF
  import behind `robot|scene import|validate`
- Doctor: five new sections (accelerated, physics, assets, data, platform; 18 total) and
  a ROS-environment-sourced check
- `caasi help [command …]` — help for the root or any command path (`caasi help gpu
  status`), resolved like `git help`
- Global `--color auto|always|never`, honoring `NO_COLOR`
- Docs: pages for GPU-accelerated robotics, synthetic data/teleop, physics & foundation
  models; capability-catalog configuration guide

### Changed
- Terminal output uses space-aligned columns instead of bordered tables and panels;
  colors and status symbols (`✓ ! ✗ • ↳`) are kept

### Fixed
- `run_ros2` sources the distro `setup.bash` when the shell has not — ROS groups now work
  in unsourced environments
- `sim run` accepts a local `--json` flag like every sibling command

## [0.1.0]

### Added
- Initial release: CLI-first orchestration layer for NVIDIA Isaac Sim, Isaac Lab and the
  robotics ecosystem — discovers and delegates to installed tools, never imports the heavy
  stack (typer, rich, pyyaml only)
- `doctor`: 13-section environment diagnostics (hardware, NVIDIA driver/CUDA, graphics,
  Python, Isaac, ROS 2, Nav2/MoveIt/ros2_control, ML, vision, simulators, containers,
  storage) with `--component`, `--json`, scriptable `--quiet` exit codes
- `sim`, `lab`: launch/monitor Isaac Sim and Isaac Lab through a multi-version tool
  registry, headless-first
- Runs engine: detached tracked processes under `~/.caasi/runs` — `run
  list|status|logs|stop|pause|resume|delete|inspect`, `logs --follow`; jobs survive the
  terminal
- ROS 2 delegation: `ros`, `nav` (Nav2), `moveit`, `control` (ros2_control) —
  status/launch/inspect/test on top of the `ros2` CLI
- `train`, `benchmark start|report`: Isaac Lab workflows driven by a shared YAML
  experiment config
- Data & review: `dataset generate|inspect|convert|validate`, `sensor`, `vision`,
  `replay`, `view rviz|foxglove|open3d|attach`
- Projects: `init`, `setup`, `project`, `robot list|inspect|info|create`, `scene`, `task`
- `remote` (SSH) and `container` (docker/podman, NVIDIA runtime); `native`/`shell`
  escape hatches
- Configuration: `~/.config/caasi/config.yaml` merged with project `./caasi.yaml`,
  multi-version tool registry, env overrides, `config show|get|set|path|tools`
- Global `--verbose/--quiet/--json/--config/--lang` flags, shell completion, i18n-ready
  message layer, static docs site; MIT

[unreleased]: https://github.com/a6y3ap/caasi/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/a6y3ap/caasi/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/a6y3ap/caasi/releases/tag/v0.1.0
