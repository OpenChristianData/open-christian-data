"""Tests for the centralized CPU-throttle modes (build/lib/ocr_throttle.py)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib import ocr_throttle as t  # noqa: E402


def test_subprocess_kwargs_env_and_priority():
    bg = t.subprocess_kwargs_for_throttle("background-8")
    assert bg["env"]["OMP_NUM_THREADS"] == "8"
    assert bg["creationflags"] == t.BELOW_NORMAL_PRIORITY_CLASS
    mn = t.subprocess_kwargs_for_throttle("minimal-4")
    assert mn["env"]["OMP_NUM_THREADS"] == "4"
    assert mn["creationflags"] == t.IDLE_PRIORITY_CLASS
    # full-speed -> no override
    assert t.subprocess_kwargs_for_throttle("full-speed") == {}


def test_priority_for_throttle():
    assert t.priority_for_throttle("background-8") == t.BELOW_NORMAL_PRIORITY_CLASS
    assert t.priority_for_throttle("minimal-4") == t.IDLE_PRIORITY_CLASS
    assert t.priority_for_throttle("full-speed") is None


def test_workers_for_throttle():
    assert t.workers_for_throttle("minimal-4") == 4
    assert t.workers_for_throttle("background-8") == 8
    # full-speed -> cpu_count (some positive integer)
    assert t.workers_for_throttle("full-speed") >= 1


def test_choices_are_exactly_the_three_canonical_names():
    assert t.THROTTLE_CHOICES == ["full-speed", "background-8", "minimal-4"]
    # the removed legacy aliases are no longer accepted
    for legacy in ("none", "test", "overnight", "8", "4", "background", "minimal"):
        assert legacy not in t.THROTTLE_CHOICES
