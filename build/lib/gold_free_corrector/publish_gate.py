"""M15 publish gate: the corrector's publication policy layer.

Reads an immutable corrected-page-v1 sidecar and emits a publish-projection-v1
sidecar. It never overwrites the corrected page, so re-certifying a threshold
means re-running the gate rather than mutating the corrector output.

Policy (BUILD_SPEC F1 + DESIGN_gold_free_corrector_locked.md §6):
  - L0 and human-reviewed readings publish unflagged.
  - L1-L3 publish *flagged* until their (region_class, level) cell is certified
    (auto_accept_enabled) -- the route-until-measured embargo, re-enforced here
    as defense in depth even when a release_accepted slipped through decide().
  - The public origin label for L1-L3 is always machine_composed, never observed
    (invariant #7): a composed word can be character-traceable yet never
    witnessed whole by any source.
  - Any released token at derivation_level >= L1 with missing/malformed
    character_provenance is demoted to routed (F2 ship-blocking gate).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from build.lib.corrected_page_semantic_validator import (
    CorrectedPageSemanticError,
    validate_reading_provenance,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

_ROUTE_ACTIONS = {"route_human_review", "defer"}

_UNFLAGGED = "unflagged"
_FLAGGED = "flagged"
_ROUTED = "routed"


def publish_gate(
    corrected_page: dict,
    thresholds: dict,
    *,
    region_class: str = "body",
    source_path: Path | str | None = None,
) -> dict:
    """Return a publish-projection-v1 dict for one corrected page."""
    positions = [
        _project_position(position, thresholds, region_class)
        for position in corrected_page.get("positions", [])
    ]

    summary = {_UNFLAGGED: 0, _FLAGGED: 0, _ROUTED: 0}
    for projected in positions:
        summary[projected["publish_status"]] += 1

    source = {"path": _relative_path(source_path)}

    return {
        "schema_type": "publish_projection",
        "schema_version": "publish-projection-v1",
        "work_id": corrected_page["work_id"],
        "volume_id": corrected_page["volume_id"],
        "page_id": corrected_page["page_id"],
        "region_class": region_class,
        "source_corrected_page": source,
        "positions": positions,
        "summary": summary,
    }


def write_publish_projection(projection: dict, path: Path | str) -> None:
    """Atomically write a publish-projection sidecar (OUT-02)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(projection, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp_path.replace(path)


def _project_position(position: dict, thresholds: dict, region_class: str) -> dict:
    pid = position["position_id"]
    action = position.get("chosen_action")

    # Route-only actions and protected classes never publish (HR5 routes before
    # any threshold read).
    if action in _ROUTE_ACTIONS:
        return _routed(pid, "chosen_action")
    if position.get("protected_class", "none") != "none":
        return _routed(pid, "protected_class")

    reading = _chosen_reading(position)
    if reading is None:
        return _routed(pid, "no_chosen_reading")

    # F2 ship-blocking gate: a released L>=1 token with malformed provenance is
    # demoted to routed, never published flagged.
    try:
        validate_reading_provenance(reading, label=f"position {pid}")
    except CorrectedPageSemanticError:
        return _routed(pid, "malformed_provenance")

    level = str(reading["derivation_level"])
    origin = _published_origin(reading, level)
    status = _publish_status(action, level, origin, thresholds, region_class)

    projected: dict[str, Any] = {
        "position_id": pid,
        "publish_status": status,
        "origin_kind": origin,
        "derivation_level": level,
        "text": reading.get("text"),
    }
    provenance = reading.get("character_provenance")
    if provenance is not None:
        projected["character_provenance"] = copy.deepcopy(provenance)
    return projected


def _publish_status(
    action: str,
    level: str,
    origin: str,
    thresholds: dict,
    region_class: str,
) -> str:
    # Human amendments publish unflagged regardless of the machine embargo.
    if origin == "human_amended":
        return _UNFLAGGED
    if action == "release_flagged":
        return _FLAGGED
    # release_observed / release_accepted below.
    if level == "L0":
        return _UNFLAGGED
    # L1-L3: unflagged only when this cell is certified; else the embargo flags it.
    if _cell_certified(thresholds, region_class, level):
        return _UNFLAGGED
    return _FLAGGED


def _published_origin(reading: dict, level: str) -> str:
    if reading.get("origin_kind") == "human_amended":
        return "human_amended"
    if level == "L0":
        return "observed"
    # Invariant #7: L1-L3 are machine_composed, never "attested"/observed.
    return "machine_composed"


def _cell_certified(thresholds: dict, region_class: str, level: str) -> bool:
    entry = thresholds.get(region_class, {}).get(level, {})
    return entry.get("auto_accept_enabled", False) is True


def _chosen_reading(position: dict) -> dict | None:
    idx = position.get("chosen_reading_index")
    readings = position.get("derivable_readings", [])
    if idx is None or not 0 <= idx < len(readings):
        return None
    return readings[idx]


def _routed(position_id: str, reason: str) -> dict:
    return {
        "position_id": position_id,
        "publish_status": _ROUTED,
        "origin_kind": None,
        "derivation_level": None,
        "text": None,
        "route_reason": reason,
    }


def _relative_path(source_path: Path | str | None) -> str:
    if source_path is None:
        return ""
    path = Path(source_path)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        # Path outside the repo (e.g. a tmp dir in tests) -- store the bare name
        # rather than leak an absolute identity path.
        return path.name
