"""Tests for M15 the corrector publish gate (build/lib/gold_free_corrector/publish_gate.py).

The gate reads an immutable corrected-page-v1 sidecar and emits a
publish-projection-v1 sidecar. It enforces the publication policy from
BUILD_SPEC F1 + DESIGN_gold_free_corrector_locked §6:
  - L0 + human-reviewed publish unflagged; L1-L3 publish flagged until certified.
  - Public label for L1-L3 is machine_composed, never observed/attested.
  - Any released L>=1 token with malformed provenance is demoted to routed (F2).
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from build.lib.gold_free_corrector.publish_gate import (
    publish_gate,
    write_publish_projection,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "publish-projection-v1.schema.json"

# Embargo default: nothing L1-L3 is certified.
_EMBARGO = {
    "body": {level: {"auto_accept_enabled": False, "max_real_word_error_rate": None}
             for level in ("L0", "L1", "L2", "L3")},
}
# L1 certified in body only.
_CERTIFIED_L1 = {
    "body": {"L1": {"auto_accept_enabled": True, "max_real_word_error_rate": None}},
}


def _l0(text: str = "the", origin: str = "observed") -> dict:
    return {
        "derivation_level": "L0",
        "origin_kind": origin,
        "text": text,
        "scores": {"confidence": 1.0},
    }


def _l1(text: str = "cat") -> dict:
    """An L1 composed reading with complete per-grapheme provenance (engine_family only)."""
    return {
        "derivation_level": "L1",
        "origin_kind": "machine_composed",
        "text": text,
        "scores": {"confidence": 0.9},
        "character_provenance": [
            {"grapheme": ch, "source_type": "engine_family", "source_id": "tesseract"}
            for ch in text
        ],
    }


def _position(pid: str, reading: dict, *, action: str,
              protected_class: str = "none", chosen_index: int | None = 0) -> dict:
    return {
        "position_id": pid,
        "protected_class": protected_class,
        "derivable_readings": [reading],
        "chosen_reading_index": chosen_index,
        "chosen_action": action,
        "derivation_method": reading.get("derivation_level"),
    }


def _page(positions: list[dict]) -> dict:
    return {
        "schema_type": "corrected_page",
        "schema_version": "corrected-page-v1",
        "work_id": "jewish-encyclopedia",
        "volume_id": "vol_01",
        "page_id": "page_0010",
        "source_wct_page": {"path": "reports/reconciled/vol_01/page_0010.wct.json"},
        "positions": positions,
    }


def _status(projection: dict, pid: str) -> dict:
    return next(p for p in projection["positions"] if p["position_id"] == pid)


def test_route_action_routes() -> None:
    page = _page([_position("p1", _l1(), action="route_human_review")])
    proj = publish_gate(page, _EMBARGO, region_class="body")
    assert _status(proj, "p1")["publish_status"] == "routed"


def test_defer_action_routes() -> None:
    page = _page([_position("p1", _l1(), action="defer")])
    proj = publish_gate(page, _EMBARGO, region_class="body")
    assert _status(proj, "p1")["publish_status"] == "routed"


def test_protected_class_routes_even_when_accepted() -> None:
    # HR5: protected classes route before any threshold read, even if a stray
    # release_accepted slipped through upstream.
    page = _page([_position("p1", _l1(), action="release_accepted",
                            protected_class="proper_name")])
    proj = publish_gate(page, _CERTIFIED_L1, region_class="body")
    assert _status(proj, "p1")["publish_status"] == "routed"


def test_l0_observed_is_unflagged_observed() -> None:
    page = _page([_position("p1", _l0(), action="release_observed")])
    proj = publish_gate(page, _EMBARGO, region_class="body")
    pos = _status(proj, "p1")
    assert pos["publish_status"] == "unflagged"
    assert pos["origin_kind"] == "observed"


def test_l1_accepted_certified_is_unflagged_machine_composed() -> None:
    page = _page([_position("p1", _l1(), action="release_accepted")])
    proj = publish_gate(page, _CERTIFIED_L1, region_class="body")
    pos = _status(proj, "p1")
    assert pos["publish_status"] == "unflagged"
    assert pos["origin_kind"] == "machine_composed"


def test_l1_accepted_uncertified_demoted_to_flagged() -> None:
    # Defense in depth: even a release_accepted L1 must publish flagged when the
    # gate's own thresholds say the cell is not certified (route-until-measured).
    page = _page([_position("p1", _l1(), action="release_accepted")])
    proj = publish_gate(page, _EMBARGO, region_class="body")
    pos = _status(proj, "p1")
    assert pos["publish_status"] == "flagged"
    assert pos["origin_kind"] == "machine_composed"


def test_l1_flagged_is_flagged_machine_composed() -> None:
    page = _page([_position("p1", _l1(), action="release_flagged")])
    proj = publish_gate(page, _EMBARGO, region_class="body")
    pos = _status(proj, "p1")
    assert pos["publish_status"] == "flagged"
    assert pos["origin_kind"] == "machine_composed"


def test_l1_missing_provenance_is_routed() -> None:
    # F2 ship-blocking gate: an L1 released token with no character_provenance
    # must never publish, flagged or otherwise.
    bad = _l1()
    del bad["character_provenance"]
    page = _page([_position("p1", bad, action="release_flagged")])
    proj = publish_gate(page, _EMBARGO, region_class="body")
    assert _status(proj, "p1")["publish_status"] == "routed"


def test_l1_provenance_length_mismatch_is_routed() -> None:
    bad = _l1("cat")
    bad["character_provenance"] = bad["character_provenance"][:2]  # 2 entries, 3 graphemes
    page = _page([_position("p1", bad, action="release_accepted")])
    proj = publish_gate(page, _CERTIFIED_L1, region_class="body")
    assert _status(proj, "p1")["publish_status"] == "routed"


def test_human_amended_is_unflagged() -> None:
    # Human-reviewed path: an L0 human amendment publishes unflagged regardless
    # of embargo, labelled human_amended.
    page = _page([_position("p1", _l0("corrected", origin="human_amended"),
                            action="release_accepted")])
    proj = publish_gate(page, _EMBARGO, region_class="body")
    pos = _status(proj, "p1")
    assert pos["publish_status"] == "unflagged"
    assert pos["origin_kind"] == "human_amended"


def test_l1_origin_is_never_observed() -> None:
    # Invariant #7 / F1: L1-L3 are machine_composed, never observed/attested.
    for action, thresholds in (("release_flagged", _EMBARGO),
                               ("release_accepted", _CERTIFIED_L1)):
        page = _page([_position("p1", _l1(), action=action)])
        proj = publish_gate(page, thresholds, region_class="body")
        assert _status(proj, "p1")["origin_kind"] == "machine_composed"


def test_summary_tallies_statuses() -> None:
    page = _page([
        _position("p1", _l0(), action="release_observed"),          # unflagged
        _position("p2", _l1(), action="release_flagged"),           # flagged
        _position("p3", _l1(), action="route_human_review"),        # routed
    ])
    proj = publish_gate(page, _EMBARGO, region_class="body")
    assert proj["summary"] == {"unflagged": 1, "flagged": 1, "routed": 1}


def test_projection_validates_against_schema() -> None:
    page = _page([
        _position("p1", _l0(), action="release_observed"),
        _position("p2", _l1(), action="release_flagged"),
        _position("p3", _l1(), action="route_human_review"),
    ])
    proj = publish_gate(page, _EMBARGO, region_class="body",
                        source_path="reports/corrected/vol_01/page_0010.corrected.json")
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(proj, schema)  # raises on any violation


def test_write_publish_projection_is_atomic_and_path_relative(tmp_path: Path) -> None:
    page = _page([_position("p1", _l0(), action="release_observed")])
    proj = publish_gate(page, _EMBARGO, region_class="body")
    out = tmp_path / "page_0010.publish.json"
    write_publish_projection(proj, out)
    assert out.exists()
    reloaded = json.loads(out.read_text(encoding="utf-8"))
    assert reloaded["schema_version"] == "publish-projection-v1"
    # No absolute-path identity leak in the written sidecar (OUT-03).
    assert "Users" not in out.read_text(encoding="utf-8")
