# Changelog

## [Unreleased]

## [0.3.0]

### Changed — information architecture

The command surface is reorganized around the invariant *"a command may have many entry
points, but one underlying semantic operation"* — each root node owns a concept and never
wraps an upstream product.

* `robot`, `scene` and `task` move **under `project`** (`caasi project robot create …`).
  The root nodes are removed; the same functions are now reachable one level down.
* `sim status|stop|pause|resume|logs` move into the generic run controls
  (`caasi run --backend sim`). `sim` keeps `run|headless|check|extensions`.
* `run list|status|stop|pause|resume` gain a `--backend B` flag: `list` filters, while
  action verbs guard against operating on a run from a different backend.
* `lab train` moves to the root `train` launcher; `lab` keeps `status|run|play|evaluate`.
* `synth` moves to `dataset generate`; the standalone `synth` node is removed.
* `project init` is now **canonical**; root `caasi init` remains as a thin alias.
* Root `caasi logs` remains as a thin alias of `run logs`.
* The previously planned root `status` node is dropped.

### Added — Layer 1: project core

`caasi project` becomes the project namespace on top of a component-driven tree.

* **Flat manifest** (`caasi.yaml`) keyed by an integer `schema` marker, replacing the
  overloaded `version: 1`. Legacy `{kind, name, version: 1}` files are bridged on read
  (`schema=1`, `version="0.0.0"`); reads never rewrite the file.
* **Components** define capability subtrees for `isaac.sim`, `isaac.lab`, `ros2`, `nav2`,
  `moveit`, `robot`, `navigation`, and `manipulation`. `project init` creates only the
  base directories; `project add` materializes a component's directories and requirements.
* New commands: `project add <component>`, `project remove <component> [--purge]`,
  `project list`, `project inspect`, `project add-file <domain> <kind> <FILE>`, and
  `project config show|get|set`.
* `project validate` is now **component-aware**, checking the schema, name, base directories,
  and registered component directories.
* New `doctor project` diagnostics validate the manifest, schema, name, and registered
  component directories; the check is skipped outside a project.
* The singular `robot/` component subtree (asset descriptions) coexists with the base
  `robots/` definitions directory.

### Added — Layer 2: environment fingerprint

A new root group, `caasi env`, provides a "CPU-Z for the robotics environment". It delegates
to existing detectors and lightweight version probes without importing the heavy robotics
stack.

* Environment fingerprints cover system, hardware, GPU, drivers, compilers, Python, ROS,
  Isaac, Docker, and Git.
* Fingerprints have a stable SHA-256 identity that excludes volatile fields such as
  timestamps, PIDs, load average, and free memory.
* Fingerprints can be stored per project under `.caasi/environment/` or globally under
  `~/.caasi/environment/`.
* `env inspect` shows the live environment.
* `env fingerprint [--save]` collects the environment and prints its stable hash, optionally
  saving it.
* `env compare [A] [B]` compares stored fingerprints, or a stored fingerprint with the
  current environment.
* `env show` displays a stored fingerprint without re-collecting the environment.
* `env lock` records the resolved environment baseline and project requirements in
  `caasi.lock`.

### Added — Layer 3: requirements + check contract

A single compatibility model now backs root `caasi check`, `sim check`, `container check`,
and `control check`.

* Version requirements support common PEP 440 operators, comma-separated constraints,
  `1.2.x`/`1.2.*` wildcards, and string equality for non-numeric versions.
* Checks distinguish **verified**, **compatible**, **untested**, **missing**, and
  **incompatible** evidence without inventing a verdict when something cannot be verified.
* A detected version outside a required range is reported as **untested** with an
  explanatory warning; `incompatible` is reserved for failed functional probes or
  missing required components.
* `caasi check [project]` preflights a project using its environment and requirements.
  `caasi check run <id>` checks a stored run's command, working directory, and experiment
  configuration.
* Incompatible checks exit with **3**; warnings do not fail a build.
* `caasi.lock` records resolved versions and required dependencies as a reproduction
  baseline, not as a package or environment freeze.
* `check.strict` is an opt-in mode that escalates untested results to incompatible in
  the root orchestrator.

### Changed — check exit codes

`sim check`, `container check`, and `control check` now use the common check contract,
including the same result ladder, JSON structure, and exit policy.

* Incompatible results now exit **3** instead of 1.
* `--json` emits the common `CheckReport` format instead of the previous doctor envelope.

### Added — Layer 4: diagnostics that explain themselves

A failing check now explains what is wrong, why it matters, what proves it, its impact,
and what to do next.

* `caasi doctor --details <section>` renders a **Problem → Cause → Evidence → Impact →
  Suggested action** explanation for each `fail` or `warn`.
* `--details` runs only the selected section, like `--component`.
* Existing doctor output, JSON behavior, and exit codes remain unchanged except that
  `--json --details` adds an `explanations` array.
* Sections with nothing to explain explicitly say so.

### Added — Layers 5–6: canonical run launcher + provenance

Starting a tracked run is now a single operation shared by all supported launch paths.

* **`run start CONFIG`** is the canonical launcher, with `--backend`, `--name`,
  `--dry-run`, and pass-through script arguments.
* Root **`caasi start`** remains a thin alias.
* `sim run`, `sim headless`, `train`, `lab run/play/evaluate`, and `dataset generate`
  now use the same tracked-run and provenance path.
* **`run restart QUERY`** stops the source run when necessary and launches a new run from
  its recorded command, working directory, backend, and kind, preserving the relationship
  through `restarted_from`.
* Every started run receives a provenance bundle containing its manifest, environment,
  hardware, dependencies, configuration, Git state, and process information.
* Secrets in recorded configuration are redacted.
* Provenance collection degrades without blocking a run when information such as Git,
  project context, or individual files is unavailable.
* **Log aggregation** adds `--component`, `--errors`, `--since`, and `--json` to
  `run logs` and `caasi logs`, with the same filters available while following logs.

### Added — Layer 7: monitoring

A new monitoring operation samples resources exposed by the machine and tracked run
without importing the monitored robotics stack.

* `caasi monitor [<run>] [--interval N] [--once]` monitors run status, CPU, RAM, GPU,
  VRAM, throughput, runtime, and top processes.
* `--once` and `--json` provide a single machine-readable snapshot.
* Monitoring stops following a run once it leaves its active states.
* With no recorded runs, monitoring falls back to machine resources.
* `gpu monitor` remains GPU-only, while `system status|memory|processes` remain
  machine-only.

### Added — Layer 8: audit

The new `audit` command answers whether a project can be accounted for and reproduced,
distinct from `doctor` (machine diagnostics), `check` (compatibility), and `validate`
(structure).

* **`caasi audit [scope] [--fix]`** audits `project`, `dependencies`, `environment`,
  `files`, `runs`, and `reproducibility`, or all scopes by default.
* Reports use ✓/⚠/✗ groups and return an overall warning/error result.
* Warnings do not fail an audit; errors exit with **1**.
* `--json` provides structured audit results.
* `--fix` performs only CAASI-owned safe fixes. It currently creates missing CAASI
  directories and does not rewrite manifests, delete records, kill processes, or modify
  user source, packages, drivers, ROS, or Isaac installations.
* `audit.fix` can enable the fix behavior by default; it is disabled by default.

### Changed — documentation & version

The static documentation site and README are updated for the v0.3.0 command surface.
Page badges and footers now read `v0.3.0`, and the package version is bumped from `0.2.0`
to `0.3.0`.

* Added `docs/observability.html` covering monitoring, aggregated logs, audit, and
  provenance.
* Updated the documentation command map and project, environment, run, and README pages
  for the reorganized command surface and check contract.

### Fixed

* Two runs started within the same second no longer collide: run IDs now gain a `-2`,
  `-3`, … suffix when the directory already exists. This fixes fast `run restart` failures
  caused by `FileExistsError`.

## [0.2.0]

### Added

* GPU-accelerated robotics groups: `isaac-ros`, `perception`, `slam`, `mapping`, `motion`,
  `nitros`, `pipeline inspect` — discover Isaac ROS / NITROS / nvblox / cuMotion stacks,
  launch them as tracked runs, verify graphs with `slam test` and per-group doctors.
* Synthetic data & teleop: `synth` (Replicator SDG generate/preview/validate) and
  `teleop` (keyboard/joystick drive, rosbag2 record/replay).
* Physics & foundation models: `physics` (run/benchmark experiments on PhysX, Newton,
  Warp, MuJoCo or Gazebo), `warp` (kernel test/benchmark), `groot` (GR00T setup, run,
  train, evaluate via the repo's own interpreter), `cosmos` (Cosmos/NuRec delegation).
* Capability catalog: upstream probes are data and fully overridable through
  `caasi config catalog [domain]` and `caasi config set catalog.<domain>.<capability>.<field>`.
* Subcommands: `sim headless|logs|extensions`, `lab run|train|play|evaluate`,
  `ros service`, `nav|moveit|control|gpu|system|container doctor`, `gpu monitor`,
  `run attach`, `container status`, `view run`, `dataset list|download`,
  `robot import|validate`, `scene import|validate|capture|reconstruct`, `config catalog`.
* USD tool delegation (`usdcat`, `usdchecker`, `usdconvert`, `usdview`) and URDF/MJCF
  import behind `robot|scene import|validate`.
* Doctor: five new sections (accelerated, physics, assets, data, platform; 18 total) and
  a ROS-environment-sourced check.
* `caasi help [command …]` — help for the root or any command path (`caasi help gpu
  status`), resolved like `git help`.
* Global `--color auto|always|never`, honoring `NO_COLOR`.
* Documentation pages for GPU-accelerated robotics, synthetic data/teleop, physics &
  foundation models, and capability-catalog configuration.
* `--layout rich|plain` — bordered tables or space-aligned columns, also settable via
  `CAASI_LAYOUT` or `layout:` in `config.yaml`.
* `CAASI_HELP_ORDER` / `help_order:` in `config.yaml` — `grouped` (default), `core`
  (entry points first, then a–z), or `alpha` (flat a–z) ordering for the root command
  listing.
* Root help lists commands in titled groups, alphabetical within each group; subcommand
  listings keep their existing order.

### Fixed

* `run_ros2` sources the distro `setup.bash` when the shell has not, allowing ROS groups
  to work in unsourced environments.
* `sim run` accepts a local `--json` flag like its sibling commands.

## [0.1.0]

### Added

* Initial release: CLI-first orchestration layer for NVIDIA Isaac Sim, Isaac Lab and the
  robotics ecosystem — discovers and delegates to installed tools without importing the
  heavy stack (Typer, Rich, PyYAML only).
* `doctor`: 13-section environment diagnostics covering hardware, NVIDIA driver/CUDA,
  graphics, Python, Isaac, ROS 2, Nav2/MoveIt/ros2_control, ML, vision, simulators,
  containers, and storage, with `--component`, `--json`, and scriptable `--quiet` exit codes.
* `sim`, `lab`: launch/monitor Isaac Sim and Isaac Lab through a multi-version tool
  registry, headless-first.
* Runs engine: detached tracked processes under `~/.caasi/runs` — `run
  list|status|logs|stop|pause|resume|delete|inspect`, with `logs --follow`; jobs survive
  the terminal.
* ROS 2 delegation: `ros`, `nav` (Nav2), `moveit`, `control` (ros2_control) —
  status/launch/inspect/test on top of the `ros2` CLI.
* `train`, `benchmark start|report`: Isaac Lab workflows driven by a shared YAML experiment
  config.
* Data & review: `dataset generate|inspect|convert|validate`, `sensor`, `vision`, `replay`,
  `view rviz|foxglove|open3d|attach`.
* Projects: `init`, `setup`, `project`, `robot list|inspect|info|create`, `scene`, `task`.
* `remote` (SSH) and `container` (Docker/Podman, NVIDIA runtime); `native`/`shell` escape
  hatches.
* Configuration: `~/.config/caasi/config.yaml` merged with project `./caasi.yaml`,
  multi-version tool registry, environment overrides, `config show|get|set|path|tools`.
* Global `--verbose/--quiet/--json/--config/--lang` flags, shell completion, i18n-ready
  message layer, static documentation site; MIT.

[unreleased]: https://github.com/7a6172/caasi/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/7a6172/caasi/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/7a6172/caasi/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/7a6172/caasi/releases/tag/v0.1.0