from __future__ import annotations

import re
from typing import Any

from build.lib._generated_enums import NSH_GOLD_POSITION_V1__SCRIPT
from build.lib.gold_free_corrector.protect import protected_class_for_position
from build.tools.ocr_pipeline.abbyy_lineage_value_study import (
    WCT_TO_STUDY_FAMILY,
    stratify,
    triage_position,
)

# WCT_TO_STUDY_FAMILY reconciles the two family vocabularies (WCT long names like
# "azure-ai-vision" -> study short names like "azure"). It is the single source of truth,
# defined in abbyy_lineage_value_study (CC-ARCH-05) -- do not redefine it here. Applied at
# the _baseline_candidates seam below so worksheet records carry short-name keys.
_PAGE_ID_RE = re.compile(r"page_(\d+)$")


def build_worksheet_positions(wct_page: dict, *, volume: int) -> list[dict]:
    positions = list(wct_page["positions"])
    anchor = _page_anchor(wct_page["page_id"])
    has_greek_hebrew = any(_script_label(pos) in {"greek", "hebrew"} for pos in positions)
    # Full degraded/dense stratification needs cross-page distributions; this phase has
    # only one page, so pass the script signal and let stratify return greek_hebrew/clean.
    stratum = stratify({"has_greek_hebrew": has_greek_hebrew})

    records: list[dict] = []
    for index, position in enumerate(positions):
        previous_position = positions[index - 1] if index > 0 else None
        next_position = positions[index + 1] if index + 1 < len(positions) else None
        token_class = protected_class_for_position(
            position,
            previous_position=previous_position,
            next_position=next_position,
        )
        position_id = position["position_id"]
        records.append(
            {
                "schema_version": "nsh-gold-position-v1",
                "page_image_sha256": "sha256:" + wct_page["source_image"]["sha256"],
                "bbox": position["reference_bbox"],
                "edition_page_key": {
                    "section": position["zone"]["zone_type"],
                    "anchor": anchor,
                    "ordinal": 0,
                },
                "volume": volume,
                "canonical_leaf_id": None,
                "position_id": position_id,
                "derived_observation_token_ids": [],
                "script": _worksheet_script(position),
                "token_class": token_class or "none",
                "baseline_candidates": _baseline_candidates(position),
                "alternate_candidates": {},
                "stratum": stratum,
                "crop_ref": (
                    f"crops/{wct_page['volume_id']}/{wct_page['page_id']}/"
                    f"{position_id.replace(':', '_')}.png"
                ),
                "review_status": "pending",
            }
        )
    return records


def select_hard_positions(records: list[dict]) -> list[dict]:
    return [
        record
        for record in records
        if triage_position(record["baseline_candidates"]) == "hard"
    ]


def rejoin_by_geometry(
    gold_records: list[dict],
    wct_page: dict,
    *,
    min_iou: float = 0.5,
) -> list[dict]:
    """Re-attach human-adjudicated gold records to WCT positions by geometry (the durability
    mechanism: old truth joins a rebuilt WCT without a migration map).

    `matched_position_ids` is ordered best-first: index [0] is the highest-IoU position and is
    the PRIMARY match — verified on live JE WCT to be the record's own position at IoU 1.0 for
    100% of records when the page is unchanged (self-rejoin identity). The tail (index 1+) holds
    genuinely-overlapping positions: the WCT can carry near-duplicate positions for one physical
    word (multiple geometry lanes overlapping at IoU ~0.5-0.65) as well as true re-segmentation
    splits — both legitimately map to the same crop, which is why the field is an array. Consumers
    needing a single position should take [0]; those tracking the full span take the whole list.
    `min_iou` defaults to 0.5 so a re-segmentation half (roughly half the original area, so IoU
    ~0.5) is still captured; raise it to suppress the near-duplicate tail at the cost of dropping
    re-segmentation halves.
    """
    page_sha = "sha256:" + wct_page["source_image"]["sha256"]
    positions = list(wct_page["positions"])
    results: list[dict] = []

    for record in gold_records:
        result = {
            "page_image_sha256": record["page_image_sha256"],
            "bbox": record["bbox"],
            "matched_position_ids": [],
            "best_iou": 0.0,
            "reason": None,
        }
        if record["page_image_sha256"] != page_sha:
            result["reason"] = "different_page"
            results.append(result)
            continue

        matches = [
            {
                "position": position,
                "index": index,
                "iou": _iou(record["bbox"], position["reference_bbox"]),
            }
            for index, position in enumerate(positions)
        ]
        matches = [match for match in matches if match["iou"] >= min_iou]
        matches.sort(key=lambda match: match["iou"], reverse=True)

        if matches:
            matches = _reorder_by_context(matches, positions, record.get("context_window"))
            result["matched_position_ids"] = [
                match["position"]["position_id"] for match in matches
            ]
            result["best_iou"] = matches[0]["iou"]
        else:
            result["reason"] = "no_overlap"

        results.append(result)

    return results


def _iou(bbox_a: dict, bbox_b: dict) -> float:
    a_left = bbox_a["x"]
    a_top = bbox_a["y"]
    a_right = a_left + bbox_a["w"]
    a_bottom = a_top + bbox_a["h"]
    b_left = bbox_b["x"]
    b_top = bbox_b["y"]
    b_right = b_left + bbox_b["w"]
    b_bottom = b_top + bbox_b["h"]

    intersection_width = max(0, min(a_right, b_right) - max(a_left, b_left))
    intersection_height = max(0, min(a_bottom, b_bottom) - max(a_top, b_top))
    intersection = intersection_width * intersection_height
    if intersection == 0:
        return 0.0

    area_a = bbox_a["w"] * bbox_a["h"]
    area_b = bbox_b["w"] * bbox_b["h"]
    union = area_a + area_b - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _reorder_by_context(
    matches: list[dict],
    positions: list[dict],
    context_window: dict | None,
) -> list[dict]:
    if not context_window:
        return matches
    if not (context_window.get("left_reading") or context_window.get("right_reading")):
        return matches

    return sorted(
        matches,
        key=lambda match: _context_score(match["index"], positions, context_window),
        reverse=True,
    )


def _context_score(index: int, positions: list[dict], context_window: dict) -> int:
    score = 0
    left = context_window.get("left_reading")
    right = context_window.get("right_reading")
    if left is not None and index > 0:
        score += int(
            _normalise_context_reading(_best_reading(positions[index - 1]))
            == _normalise_context_reading(left)
        )
    if right is not None and index + 1 < len(positions):
        score += int(
            _normalise_context_reading(_best_reading(positions[index + 1]))
            == _normalise_context_reading(right)
        )
    return score


def _best_reading(position: dict) -> str:
    for candidate in position.get("candidate_set", []):
        reading = candidate.get("raw_reading") or candidate.get("candidate_key")
        if reading is not None:
            return str(reading)
    return str(position.get("raw_reading") or position.get("candidate_key") or "")


def _normalise_context_reading(reading: str) -> str:
    return " ".join(reading.casefold().split())


def _page_anchor(page_id: str) -> int:
    match = _PAGE_ID_RE.fullmatch(page_id)
    if not match:
        raise ValueError(f"Cannot parse WCT page_id as page_NNNN: {page_id!r}")
    return int(match.group(1))


def _script_label(position: dict) -> str | None:
    script = position.get("script")
    if isinstance(script, str):
        return script.lower()
    if not isinstance(script, dict):
        return None
    text_level = script.get("text_level")
    if isinstance(text_level, dict) and text_level.get("label"):
        return str(text_level["label"]).lower()
    return None


def _worksheet_script(position: dict) -> str:
    label = _script_label(position)
    if label in NSH_GOLD_POSITION_V1__SCRIPT:
        return label
    return "other"


def _baseline_candidates(position: dict[str, Any]) -> dict[str, str]:
    baseline: dict[str, str] = {}
    for candidate in position.get("candidate_set", []):
        candidate_key = candidate["candidate_key"]
        for family in candidate.get("attesting_families", []):
            study_family = WCT_TO_STUDY_FAMILY.get(family)
            if study_family is not None and study_family not in baseline:
                # If one family attests multiple candidates, preserve WCT candidate_set order.
                baseline[study_family] = candidate_key
    return baseline
