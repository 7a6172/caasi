"""Experiment configuration: what `caasi sim run` / `caasi train` execute.

An experiment YAML declares *what* to run and *which backend* runs it::

    name: my-experiment
    backend: sim          # sim | lab | python
    script: experiment.py # relative to the YAML file
    args: ["--steps", "100"]
    env:
      MY_VAR: "1"
    python: /custom/python  # optional override
    headless: true
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..core.config import Config, ResolvedTool
from ..utils import shell

VALID_BACKENDS = ("sim", "lab", "python")


class ExperimentError(ValueError):
    """Raised for invalid experiment configurations."""


@dataclass
class Experiment:
    name: str
    backend: str
    script: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    python: str | None = None
    headless: bool = True
    cwd: str | None = None
    config_path: Path | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def script_path(self) -> Path:
        script = Path(self.script).expanduser()
        if script.is_absolute():
            return script
        base = self.config_path.parent if self.config_path else Path.cwd()
        return (base / script).resolve()

    @property
    def work_dir(self) -> Path:
        if self.cwd:
            return Path(self.cwd).expanduser().resolve()
        base = self.config_path.parent if self.config_path else Path.cwd()
        return base.resolve()


def load_experiment(path: Path | str) -> Experiment:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ExperimentError(f"experiment config not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ExperimentError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ExperimentError(f"experiment config must be a mapping: {path}")

    backend = str(data.get("backend", "sim")).lower()
    if backend not in VALID_BACKENDS:
        raise ExperimentError(
            f"unknown backend '{backend}' (expected one of {', '.join(VALID_BACKENDS)})"
        )
    script = data.get("script")
    if not script:
        raise ExperimentError(f"'script' is required in {path}")

    args = data.get("args") or []
    if not isinstance(args, list):
        raise ExperimentError("'args' must be a list")
    env = data.get("env") or {}
    if not isinstance(env, dict):
        raise ExperimentError("'env' must be a mapping")

    return Experiment(
        name=str(data.get("name") or path.stem),
        backend=backend,
        script=str(script),
        args=[str(a) for a in args],
        env={str(k): str(v) for k, v in env.items()},
        python=data.get("python"),
        headless=bool(data.get("headless", True)),
        cwd=data.get("cwd"),
        config_path=path,
        raw=data,
    )


def _resolve_backend_tool(config: Config, backend: str) -> ResolvedTool | None:
    tool_name = {"sim": "isaacsim", "lab": "isaaclab"}.get(backend)
    if not tool_name:
        return None
    return config.resolve_tool(tool_name)


def _default_python_for(resolved: ResolvedTool | None, backend: str) -> str | None:
    path = resolved.expanded_path if resolved else None
    if not path:
        return None
    if backend == "sim":
        candidate = path / "python.sh"
        return str(candidate) if candidate.is_file() else str(path / "python.sh")
    candidate = path / "isaaclab.sh"
    return str(candidate) if candidate.is_file() else str(path / "isaaclab.sh")


def build_command(
    experiment: Experiment, config: Config, extra_args: list[str] | None = None
) -> tuple[list[str], dict[str, str]]:
    """Build (command, env) for the experiment. Raises ExperimentError."""
    args = [*experiment.args, *(extra_args or [])]
    env: dict[str, str] = {**experiment.env}
    script = str(experiment.script_path)
    if experiment.config_path:
        env.setdefault("CAASI_EXPERIMENT", str(experiment.config_path))

    backend = experiment.backend
    if backend == "python":
        python = experiment.python or sys.executable
        return [python, script, *args], env

    resolved = _resolve_backend_tool(config, backend)
    if not resolved or not resolved.path:
        from ..i18n import _

        tool = "isaacsim" if backend == "sim" else "isaaclab"
        raise ExperimentError(
            _("experiment.backend_missing", backend=backend, tool=tool)
        )

    env.setdefault(
        "ISAACSIM_PATH" if backend == "sim" else "ISAACLAB_PATH", resolved.path
    )

    if experiment.python:
        return [experiment.python, script, *args], env
    if resolved.python:
        return [resolved.python, script, *args], env

    launcher = _default_python_for(resolved, backend)
    if not launcher:
        from ..i18n import _

        raise ExperimentError(
            _("experiment.no_launcher", backend=backend, path=resolved.path)
        )

    if backend == "sim":
        if not Path(launcher).is_file():
            from ..i18n import _

            raise ExperimentError(
                _("experiment.launcher_missing", launcher=launcher)
            )
        return [launcher, script, *args], env

    # Isaac Lab: isaaclab.sh -p script ...
    if Path(launcher).is_file():
        return [launcher, "-p", script, *args], env
    # Fallback: plain python inside the lab repo (./source/... venvs vary)
    if shell.which("python3"):
        return ["python3", script, *args], env
    return [sys.executable, script, *args], env
