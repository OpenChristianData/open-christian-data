"""Canonical CPU-throttle modes shared across the NSH OCR pipeline.

Single source of truth (CC-ARCH-05): the five S1 engine runners, the S1+S2
pipeline orchestrator, the reconciliation-chain driver, and the GUI all use these
names and settings, so a rename or tuning change lands in exactly one place.

Names encode BOTH the priority class and the parallelism count (threads for the
S1 engines, worker processes for the reconciliation driver -- the same value in
both roles):

  full-speed   -- no priority limit / cpu_count workers. The default.
  background-8 -- below-normal priority; 8 engine threads, or 8 chain workers.
                  The correct mode for CPU-bound engines and at-desk runs.
  minimal-4    -- idle priority; 4 engine threads, or 4 chain workers. Only
                  sensible for the GPU-bound Surya lane or fully-unattended runs;
                  collapses CPU engines to 3+ min/page.

These three are the only accepted names (the earlier none/test/overnight and
driver 8/4 aliases were removed 2026-06-21).
"""

from __future__ import annotations

import os

IDLE_PRIORITY_CLASS = 0x00000040
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000

# Per-mode environment overrides for the S1 engine subprocesses.
# ``full-speed`` has no entry (no override).
THROTTLE_ENV: dict[str, dict[str, str]] = {
    "minimal-4": {
        "OMP_NUM_THREADS": "4",
        "MKL_NUM_THREADS": "4",
        "OPENBLAS_NUM_THREADS": "4",
        "TF_NUM_INTRAOP_THREADS": "4",
        "TF_NUM_INTEROP_THREADS": "2",
        "OPENBLAS_CORETYPE": "VORTEX",  # prevents OpenBLAS from re-detecting cores
    },
    "background-8": {
        "OMP_NUM_THREADS": "8",
        "MKL_NUM_THREADS": "8",
        "OPENBLAS_NUM_THREADS": "8",
        "TF_NUM_INTRAOP_THREADS": "8",
        "TF_NUM_INTEROP_THREADS": "4",
    },
}

# Per-mode Windows process-priority class. ``full-speed`` -> normal (no flag).
THROTTLE_PRIORITY: dict[str, int] = {
    "minimal-4": IDLE_PRIORITY_CLASS,
    "background-8": BELOW_NORMAL_PRIORITY_CLASS,
}

# Per-mode worker count for the reconciliation-chain ProcessPoolExecutor.
# ``full-speed`` -> cpu_count (see workers_for_throttle).
THROTTLE_WORKERS: dict[str, int] = {
    "minimal-4": 4,
    "background-8": 8,
}

# The complete set of accepted throttle names (argparse choices).
THROTTLE_CHOICES: list[str] = ["full-speed", "background-8", "minimal-4"]


def subprocess_kwargs_for_throttle(throttle_mode: str) -> dict:
    """subprocess.run kwargs (env + creationflags) for an S1 engine subprocess."""
    kwargs: dict = {}
    if throttle_mode in THROTTLE_ENV:
        kwargs["env"] = {**os.environ, **THROTTLE_ENV[throttle_mode]}
    if throttle_mode in THROTTLE_PRIORITY:
        kwargs["creationflags"] = THROTTLE_PRIORITY[throttle_mode]
    return kwargs


def priority_for_throttle(throttle_mode: str) -> int | None:
    """Windows priority-class creationflag for a mode, or None for full-speed."""
    return THROTTLE_PRIORITY.get(throttle_mode)


def workers_for_throttle(throttle_mode: str) -> int:
    """ProcessPoolExecutor max_workers for the reconciliation chain."""
    return THROTTLE_WORKERS.get(throttle_mode, os.cpu_count() or 4)
