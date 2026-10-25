"""Check City of God source accounting against the retained text witnesses."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from build.tools import prepare_city_of_god_sidecars as city
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[1]


def test_distinct_sources_and_print_controls_are_accounted_for() -> None:
    packet = city._evidence(ROOT)
    ordered = packet["standard_ebooks"]["ordered_text_members"]
    assert len(ordered) == 31
    assert [Path(item["path"]).stem for item in ordered if Path(item["path"]).stem.startswith("book-")] == [
        f"book-{n}" for n in range(1, 23)
    ]
    assert len(packet["standard_ebooks"]["support_members"]) == 15
    assert len(packet["print_controls"]["members"]) == 15
    source_paths = {item["path"] for item in ordered} | {packet["ccel"]["source"]["path"]}
    assert not source_paths.intersection(item["path"] for item in packet["print_controls"]["members"])
    assert all(not path.casefold().endswith(".zip") for path in source_paths)
    assert packet["ccel"]["work_locator"].endswith("#iv")


def test_changed_ccel_source_binding_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    real_load = city._repo_json

    def changed(root: Path, rel: str) -> dict:
        value = real_load(root, rel)
        if rel == city.PROFILE_REL:
            value = copy.deepcopy(value)
            value["ccel_scope"]["sha256"] = "0" * 64
        return value

    monkeypatch.setattr(city, "_repo_json", changed)
    with pytest.raises(PipelineError, match="CCEL source differs"):
        city._evidence(ROOT)

