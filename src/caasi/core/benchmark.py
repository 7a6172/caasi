"""Benchmark metric parsing.

Benchmark scripts report metrics to stdout using either convention::

    caasi_metric simulation_fps=241.0        # explicit
    Simulation FPS: 241                      # common label (aliased)

`caasi benchmark report` turns those lines into a table.
"""

from __future__ import annotations

import re

# Lower-cased label (without trailing colon) -> canonical metric name.
_ALIASES: dict[str, str] = {
    "simulation fps": "simulation_fps",
    "fps": "simulation_fps",
    "steps/sec": "steps_per_sec",
    "steps per second": "steps_per_sec",
    "real-time factor": "real_time_factor",
    "gpu utilization": "gpu_utilization",
    "gpu memory": "gpu_memory",
}

_METRIC_RE = re.compile(
    r"caasi_metric\s+([A-Za-z0-9_.-]+)\s*=\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
)
_LABEL_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z /-]*[A-Za-z])\s*:\s*(-?\d+(?:\.\d+)?)\s*[%x]?\s*$"
)


def parse_metrics(log_text: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for line in log_text.splitlines():
        explicit = _METRIC_RE.search(line)
        if explicit:
            metrics[explicit.group(1)] = float(explicit.group(2))
            continue
        labelled = _LABEL_RE.match(line)
        if labelled:
            key = _ALIASES.get(labelled.group(1).strip().lower())
            if key:
                metrics[key] = float(labelled.group(2))
    return metrics
