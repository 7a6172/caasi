"""Run manager: experiments as tracked, detachable background processes.

Each run lives in ``<paths.runs>/<run-id>/`` containing:

- ``manifest.yaml`` — metadata (command, cwd, pid, backend, timestamps)
- ``run.sh``        — wrapper that records the child's exit code
- ``stdout.log`` / ``stderr.log``

The CLI process never stays attached to a run; status is derived from the
wrapper's ``exit_code`` file plus PID liveness.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import shutil
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..core.config import Config

TERMINAL_OK = "succeeded"
TERMINAL_FAIL = "failed"
STOPPED = "stopped"
RUNNING = "running"
PAUSED = "paused"
LOST = "lost"


@dataclass
class RunRecord:
    run_id: str
    name: str
    backend: str
    kind: str
    command: list[str]
    cwd: str
    created: str
    pid: int | None
    paused: bool = False
    stopped: bool = False
    extra: dict[str, Any] = field(default_factory=dict)
    directory: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.run_id,
            "name": self.name,
            "backend": self.backend,
            "kind": self.kind,
            "command": self.command,
            "cwd": self.cwd,
            "created": self.created,
            "pid": self.pid,
            "paused": self.paused,
            "stopped": self.stopped,
            "directory": str(self.directory) if self.directory else None,
            "status": effective_status(self),
        }


def runs_dir(config: Config) -> Path:
    path = config.expanded_path_for("paths.runs") or Path.home() / ".caasi" / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip()).strip("-").lower()
    return slug or "run"


def new_run_id(name: str) -> str:
    return f"{_dt.datetime.now():%Y%m%d-%H%M%S}-{_slug(name)}"


def _manifest_path(run_dir: Path) -> Path:
    return run_dir / "manifest.yaml"


def _write_manifest(run_dir: Path, data: dict[str, Any]) -> None:
    _manifest_path(run_dir).write_text(
        yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
    )


def _read_manifest(run_dir: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(_manifest_path(run_dir).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _wrapper_path(run_dir: Path) -> Path:
    return run_dir / "run.sh"


def _write_wrapper(run_dir: Path) -> Path:
    wrapper = _wrapper_path(run_dir)
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        '"$@"\n'
        "ec=$?\n"
        f'echo "$ec" > "{run_dir / "exit_code"}"\n'
        'exit "$ec"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper


def _exit_code_of(run_dir: Path) -> int | None:
    try:
        text = (run_dir / "exit_code").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False
    return True


def _reap(pid: int | None) -> None:
    """Reap the run if it is still our child (e.g. same-process tests)."""
    if not pid:
        return
    while True:
        try:
            reaped, _ = os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            return
        if reaped == 0:
            return


def effective_status(record: RunRecord) -> str:
    exit_code = _exit_code_of(record.directory) if record.directory else None
    if exit_code is not None:
        return TERMINAL_OK if exit_code == 0 else TERMINAL_FAIL
    if pid_alive(record.pid):
        return PAUSED if record.paused else RUNNING
    if record.stopped:
        return STOPPED
    return LOST


def start_run(
    config: Config,
    *,
    name: str,
    command: list[str],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    backend: str = "python",
    kind: str = "run",
    extra: dict[str, Any] | None = None,
) -> RunRecord:
    """Launch *command* as a detached, tracked run. Returns the record."""
    base = runs_dir(config)
    run_id = new_run_id(name)
    run_dir = base / run_id
    run_dir.mkdir(parents=True)
    _write_wrapper(run_dir)

    work_dir = str(Path(cwd).expanduser()) if cwd else os.getcwd()
    merged_env = {**os.environ, **(env or {})}

    stdout = open(run_dir / "stdout.log", "w", encoding="utf-8")
    stderr = open(run_dir / "stderr.log", "w", encoding="utf-8")
    try:
        proc = _popen(run_dir, command, work_dir, merged_env, stdout, stderr)
    finally:
        stdout.close()
        stderr.close()

    manifest = {
        "id": run_id,
        "name": name,
        "backend": backend,
        "kind": kind,
        "command": [str(part) for part in command],
        "cwd": work_dir,
        "created": _now(),
        "pid": proc.pid,
        "paused": False,
        "stopped": False,
        "extra": extra or {},
    }
    _write_manifest(run_dir, manifest)
    return load_run(config, run_id)  # type: ignore[return-value]


def _popen(run_dir, command, work_dir, merged_env, stdout, stderr):
    import subprocess

    return subprocess.Popen(
        ["bash", str(_wrapper_path(run_dir)), *[str(part) for part in command]],
        cwd=work_dir,
        env=merged_env,
        stdout=stdout,
        stderr=stderr,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def load_run(config: Config, run_id: str) -> RunRecord | None:
    run_dir = runs_dir(config) / run_id
    if not run_dir.is_dir():
        return None
    data = _read_manifest(run_dir)
    if not data.get("id"):
        return None
    return RunRecord(
        run_id=str(data.get("id")),
        name=str(data.get("name", "")),
        backend=str(data.get("backend", "python")),
        kind=str(data.get("kind", "run")),
        command=list(data.get("command") or []),
        cwd=str(data.get("cwd", "")),
        created=str(data.get("created", "")),
        pid=data.get("pid"),
        paused=bool(data.get("paused", False)),
        stopped=bool(data.get("stopped", False)),
        extra=dict(data.get("extra") or {}),
        directory=run_dir,
    )


def list_runs(config: Config) -> list[RunRecord]:
    base = runs_dir(config)
    records = []
    for child in sorted(base.iterdir(), reverse=True):
        if not child.is_dir() or not _manifest_path(child).is_file():
            continue
        record = load_run(config, child.name)
        if record:
            records.append(record)
    return records


def find_run(config: Config, query: str) -> RunRecord | None:
    """Resolve *query*: exact id, unique id prefix, run name, or 'latest'."""
    query = query.strip()
    if query in ("latest", "last", "newest"):
        runs = list_runs(config)
        return runs[0] if runs else None

    exact = load_run(config, query)
    if exact:
        return exact

    matches = [
        r
        for r in list_runs(config)
        if r.run_id.startswith(query) or r.name == query
    ]
    return matches[0] if len(matches) == 1 else None


def _update_manifest(record: RunRecord, **fields: Any) -> None:
    if not record.directory:
        return
    data = _read_manifest(record.directory)
    data.update(fields)
    _write_manifest(record.directory, data)


def _signal_group(record: RunRecord, sig: int) -> bool:
    if not record.pid:
        return False
    try:
        os.killpg(record.pid, sig)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(record.pid, sig)
            return True
        except OSError:
            return False


def _wait_gone(record: RunRecord, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _reap(record.pid)
        if not pid_alive(record.pid):
            return True
        time.sleep(0.1)
    _reap(record.pid)
    return not pid_alive(record.pid)


def stop_run(record: RunRecord, timeout: float = 5.0) -> bool:
    """Terminate the run's process group. Returns True if it stopped."""
    status = effective_status(record)
    if status in (TERMINAL_OK, TERMINAL_FAIL, STOPPED, LOST):
        return True
    if record.paused:
        _signal_group(record, signal.SIGCONT)
        time.sleep(0.1)
    _signal_group(record, signal.SIGTERM)
    if not _wait_gone(record, timeout):
        _signal_group(record, signal.SIGKILL)
        _wait_gone(record, timeout)
    _update_manifest(record, stopped=True, paused=False)
    record.stopped = True
    record.paused = False
    return not pid_alive(record.pid)


def pause_run(record: RunRecord) -> bool:
    if effective_status(record) != RUNNING:
        return False
    if _signal_group(record, signal.SIGSTOP):
        _update_manifest(record, paused=True)
        record.paused = True
        return True
    return False


def resume_run(record: RunRecord) -> bool:
    if effective_status(record) != PAUSED:
        return False
    if _signal_group(record, signal.SIGCONT):
        _update_manifest(record, paused=False)
        record.paused = False
        return True
    return False


def delete_run(record: RunRecord) -> bool:
    status = effective_status(record)
    if status in (RUNNING, PAUSED):
        return False
    if record.directory and record.directory.is_dir():
        shutil.rmtree(record.directory, ignore_errors=True)
    return True


def log_path(record: RunRecord, stream: str = "stdout") -> Path | None:
    if not record.directory:
        return None
    path = record.directory / f"{stream}.log"
    return path if path.is_file() else None
