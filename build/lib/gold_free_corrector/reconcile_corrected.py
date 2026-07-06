"""Reconcile WCT pages using accepted gold-free corrector decisions."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from build.lib.gold_free_corrector.column_vote import ColumnVoteResult
from build.lib.gold_free_corrector.supersession import make_decision_event_id
from build.lib.s3_reconciler import (
    DEFAULT_MATRIX_POLICY_VERSION,
    ReconcileResult,
    reconcile_degraded,
)

_ACCEPT = "release_accepted"


def reconcile_corrected(
    wct_page: dict,
    work_meta: dict,
    corrected_positions: list[ColumnVoteResult],
    *,
    sidecar_path: Path,
    occurred_at: str,
    wct_page_path: Path | str | None = None,
    dictionary_signals: dict[str, dict] | None = None,
    matrix_policy_version: str = DEFAULT_MATRIX_POLICY_VERSION,
) -> ReconcileResult:
    """Reconcile one WCT page and emit a corrected-page-v1 sidecar."""
    corrected_by_pid: dict[str, ColumnVoteResult] = {
        cvr.corrected_position["position_id"]: cvr
        for cvr in corrected_positions
    }

    patched_page = copy.deepcopy(wct_page)
    for position in patched_page["positions"]:
        pid = position["position_id"]
        cvr = corrected_by_pid.get(pid)
        if cvr is None:
            continue

        cp = cvr.corrected_position
        if cp.get("chosen_action") != _ACCEPT:
            continue

        idx = cp.get("chosen_reading_index")
        readings = cp.get("derivable_readings", [])
        if idx is None or not 0 <= idx < len(readings):
            continue

        chosen_text = readings[idx]["text"]
        position["candidate_set"] = [
            {
                "candidate_id": f"corrector-accepted-{pid}",
                "raw_reading": chosen_text,
                "candidate_key": chosen_text,
                "attesting_families": [],
                "attesting_engines": [],
            }
        ]

    result = reconcile_degraded(
        patched_page,
        work_meta,
        occurred_at=occurred_at,
        dictionary_signals=dictionary_signals,
        matrix_policy_version=matrix_policy_version,
    )

    _write_sidecar(
        wct_page=wct_page,
        corrected_positions=corrected_positions,
        sidecar_path=sidecar_path,
        wct_page_path=wct_page_path,
        work_meta=work_meta,
        policy_version=matrix_policy_version,
    )

    return result


def _write_sidecar(
    *,
    wct_page: dict,
    corrected_positions: list[ColumnVoteResult],
    sidecar_path: Path,
    wct_page_path: Path | str | None,
    work_meta: dict,
    policy_version: str = "",
) -> None:
    corrected_by_pid = {
        cvr.corrected_position["position_id"]: cvr.corrected_position
        for cvr in corrected_positions
    }

    sidecar_positions = []
    for position in wct_page["positions"]:
        pid = position["position_id"]
        cp = corrected_by_pid.get(pid)
        if cp is None:
            sidecar_positions.append(
                {
                    "position_id": pid,
                    "protected_class": "none",
                    "derivable_readings": [],
                    "chosen_action": "route_human_review",
                }
            )
            continue

        cp = dict(cp)
        cp["decision_event_id"] = make_decision_event_id(
            work_meta["id"],
            wct_page["volume_id"],
            wct_page["page_id"],
            pid,
            policy_version,
        )
        cp["derivation_policy_version"] = policy_version
        sidecar_positions.append(_sidecar_position(cp))

    sidecar = {
        "schema_type": "corrected_page",
        "schema_version": "corrected-page-v1",
        "work_id": work_meta["id"],
        "volume_id": wct_page["volume_id"],
        "page_id": wct_page["page_id"],
        "source_wct_page": {
            "path": str(wct_page_path) if wct_page_path is not None else "",
        },
        "positions": sidecar_positions,
    }

    sidecar_path = Path(sidecar_path)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = sidecar_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(sidecar_path)


def _sidecar_position(corrected_position: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "position_id",
        "protected_class",
        "derivable_readings",
        "chosen_reading_index",
        "chosen_action",
        "derivation_method",
        "decision_event_id",
        "derivation_policy_version",
        "validation_report_id",
        "supersedes",
        "superseded_by",
    }
    return {
        key: value
        for key, value in corrected_position.items()
        if key in allowed
    }
