from __future__ import annotations

import sys
from pathlib import Path

from build.lib.evidence_renderer_loader import load_evidence_renderer


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP = REPO_ROOT / "tests" / "_tmp_evidence_renderer_load"


def test_same_evidence_filename_in_different_dirs_loads_without_collision() -> None:
    first = TEST_TMP / "producer_one" / "evidence.py"
    second = TEST_TMP / "producer_two" / "evidence.py"
    first.parent.mkdir(parents=True, exist_ok=True)
    second.parent.mkdir(parents=True, exist_ok=True)
    first.write_text("VALUE = 'first'\n", encoding="utf-8")
    second.write_text("VALUE = 'second'\n", encoding="utf-8")

    first_module = load_evidence_renderer("producer_one", first)
    second_module = load_evidence_renderer("producer_two", second)

    assert first_module.VALUE == "first"
    assert second_module.VALUE == "second"
    assert sys.modules["warning_producer_evidence.producer_one"].VALUE == "first"
    assert sys.modules["warning_producer_evidence.producer_two"].VALUE == "second"
