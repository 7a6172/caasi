"""Remote GPU machine registry (config-driven) and SSH command builders.

Remotes are declared in the configuration::

    remotes:
      gpu-box:
        host: 192.168.1.50
        user: robot
        port: 22
        identity: ~/.ssh/id_ed25519
        path: ~/experiments

caasi itself only orchestrates ``ssh``; it never implements a protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core.config import Config


@dataclass(frozen=True)
class RemoteMachine:
    name: str
    host: str
    user: str | None = None
    port: int | None = None
    identity: str | None = None
    path: str | None = None

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "name": self.name,
            "host": self.host,
            "user": self.user,
            "port": self.port,
            "identity": self.identity,
            "path": self.path,
        }


def list_remotes(config: Config) -> list[RemoteMachine]:
    """Return configured remotes (entries without a host are skipped)."""
    data = config.get("remotes")
    machines: list[RemoteMachine] = []
    if not isinstance(data, dict):
        return machines
    for name, spec in data.items():
        if not isinstance(spec, dict) or not spec.get("host"):
            continue
        machines.append(
            RemoteMachine(
                name=str(name),
                host=str(spec["host"]),
                user=spec.get("user"),
                port=spec.get("port"),
                identity=spec.get("identity"),
                path=spec.get("path"),
            )
        )
    return machines


def find_remote(config: Config, query: str) -> RemoteMachine | None:
    """Resolve *query*: exact name or unique name prefix."""
    query = query.strip()
    machines = list_remotes(config)
    exact = [m for m in machines if m.name == query]
    if exact:
        return exact[0]
    matches = [m for m in machines if m.name.startswith(query)]
    return matches[0] if len(matches) == 1 else None


def ssh_target(machine: RemoteMachine) -> str:
    return f"{machine.user}@{machine.host}" if machine.user else machine.host


def ssh_prefix(machine: RemoteMachine) -> list[str]:
    """The ssh invocation prefix for a machine (no remote command yet)."""
    args = ["ssh"]
    if machine.port:
        args += ["-p", str(machine.port)]
    if machine.identity:
        args += ["-i", str(Path(machine.identity).expanduser())]
    args.append(ssh_target(machine))
    return args
