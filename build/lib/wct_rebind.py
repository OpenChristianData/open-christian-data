"""Rebind WCT token anchors across two builds of the same page set."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from build.lib.canonical_token import canonical_token_id
from build.lib.edition_page_key import body_edition_key

_WORD_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class TokenAnchor:
    canonical_token_id: str
    position_id: str
    ordinal: int
    text_key: str
    bbox: dict[str, float]


def load_page_num_by_sha(manifest_path: Path) -> dict[str, int]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mapping: dict[str, int] = {}
    for page in manifest.get("pages", []):
        sha = str(page.get("sha256", ""))
        if sha.startswith("sha256:"):
            sha = sha[7:]
        page_num = page.get("page_num")
        if sha and isinstance(page_num, int):
            mapping[sha] = page_num
    return mapping


def edition_page_key_for_wct(page: dict[str, Any], page_num_by_sha: dict[str, int]) -> dict[str, int | str]:
    key = page.get("edition_page_key")
    if key is not None:
        return dict(key)
    sha = str(page.get("source_image", {}).get("sha256", ""))
    page_num = page_num_by_sha.get(sha)
    if page_num is None:
        page_num = int(str(page["page_id"]).removeprefix("page_"))
    return body_edition_key(page_num)


def anchors_for_page(page: dict[str, Any], page_num_by_sha: dict[str, int]) -> list[TokenAnchor]:
    key = edition_page_key_for_wct(page, page_num_by_sha)
    position_by_id = {position["position_id"]: position for position in page["positions"]}
    anchors: list[TokenAnchor] = []
    for ordinal, position_id in enumerate(page["reading_order"]):
        position = position_by_id[position_id]
        anchors.append(
            TokenAnchor(
                canonical_token_id=canonical_token_id(
                    page["work_id"],
                    page["volume_id"],
                    key,
                    ordinal,
                ),
                position_id=position_id,
                ordinal=ordinal,
                text_key=_position_text_key(position),
                bbox=_bbox(position.get("reference_bbox", {})),
            )
        )
    return anchors


def compare_pages(
    old_page: dict[str, Any],
    new_page: dict[str, Any],
    *,
    page_num_by_sha: dict[str, int],
) -> dict[str, Any]:
    old_anchors = anchors_for_page(old_page, page_num_by_sha)
    new_anchors = anchors_for_page(new_page, page_num_by_sha)
    new_by_ct = {anchor.canonical_token_id: anchor for anchor in new_anchors}
    unmatched_new = {anchor.canonical_token_id: anchor for anchor in new_anchors}

    identical: list[dict[str, Any]] = []
    needs_match: list[TokenAnchor] = []
    for old in old_anchors:
        new = new_by_ct.get(old.canonical_token_id)
        if new is not None and _same_anchor(old, new):
            identical.append(_pair_record(old, new, "same_canonical_token_id"))
            unmatched_new.pop(new.canonical_token_id, None)
        else:
            needs_match.append(old)

    rebound: list[dict[str, Any]] = []
    orphaned: list[dict[str, Any]] = []
    for old in needs_match:
        candidates = [
            (_match_score(old, new), new)
            for new in unmatched_new.values()
        ]
        candidates = [
            (score, new)
            for score, new in candidates
            if score["match_method"] != "no_match"
        ]
        candidates.sort(
            key=lambda item: (
                -item[0]["score"],
                -item[0]["bbox_iou"],
                abs(old.ordinal - item[1].ordinal),
                item[1].canonical_token_id,
            )
        )
        if not candidates:
            orphaned.append(_orphan_record(old, [], "no_anchor_match"))
            continue
        best_score, best = candidates[0]
        if len(candidates) > 1 and abs(best_score["score"] - candidates[1][0]["score"]) < 0.0001:
            orphaned.append(
                _orphan_record(
                    old,
                    [candidate.canonical_token_id for _, candidate in candidates[:5]],
                    "ambiguous_rebind",
                )
            )
            continue
        rebound.append(_pair_record(old, best, best_score["match_method"], best_score))
        unmatched_new.pop(best.canonical_token_id, None)

    additions = [
        {
            "canonical_token_id": anchor.canonical_token_id,
            "position_id": anchor.position_id,
            "ordinal": anchor.ordinal,
            "text_key": anchor.text_key,
        }
        for anchor in sorted(unmatched_new.values(), key=lambda item: item.ordinal)
    ]
    total = len(old_anchors)
    identical_count = len(identical)
    return {
        "page_id": old_page["page_id"],
        "old_token_count": len(old_anchors),
        "new_token_count": len(new_anchors),
        "identical_count": identical_count,
        "rebound_count": len(rebound),
        "orphaned_count": len(orphaned),
        "addition_count": len(additions),
        "identity_rate": identical_count / total if total else 1.0,
        "identical_samples": identical[:10],
        "rebound": rebound,
        "orphaned": orphaned,
        "additions": additions[:50],
    }


def dry_run_events(page_result: dict[str, Any], *, volume: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in page_result["rebound"]:
        payload = {
            "schema_version": "decision-event-v1",
            "event_type": "auto_rebind_system",
            "event_category": "workflow_event",
            "volume": volume,
            "actor_id": "system:auto_rebind",
            "timestamp": "2026-07-04T00:00:00Z",
            "measurement_eligible": False,
            "canonical_token_id": item["to_canonical_token_id"],
            "prior_canonical_token_id": item["from_canonical_token_id"],
            "prior_decision_event_id": _synthetic_event_id("prior", item["from_canonical_token_id"]),
            "match_method": item["match_method"],
            "decision_extras_carried": {
                "dry_run": True,
                "page_id": page_result["page_id"],
                "from_position_id": item["from_position_id"],
                "to_position_id": item["to_position_id"],
                "bbox_iou": item.get("bbox_iou"),
                "text_key": item.get("text_key"),
            },
        }
        payload["event_id"] = _synthetic_event_id("rebind", payload)
        events.append(payload)
    for item in page_result["orphaned"]:
        payload = {
            "schema_version": "decision-event-v1",
            "event_type": "orphan_decision",
            "event_category": "workflow_event",
            "volume": volume,
            "actor_id": "system:auto_rebind",
            "timestamp": "2026-07-04T00:00:00Z",
            "measurement_eligible": False,
            "canonical_token_id": item["canonical_token_id"],
            "orphaned_event_id": _synthetic_event_id("prior", item["canonical_token_id"]),
            "orphan_reason": item["orphan_reason"],
            "match_method_attempted": item["match_method_attempted"],
            "candidate_canonical_token_ids": item["candidate_canonical_token_ids"],
            "decision_extras_carried": {
                "dry_run": True,
                "page_id": page_result["page_id"],
                "position_id": item["position_id"],
                "text_key": item["text_key"],
            },
        }
        payload["event_id"] = _synthetic_event_id("orphan", payload)
        events.append(payload)
    return events


def corpus_summary(page_results: list[dict[str, Any]]) -> dict[str, Any]:
    old_total = sum(page["old_token_count"] for page in page_results)
    identical_total = sum(page["identical_count"] for page in page_results)
    return {
        "pages": len(page_results),
        "old_token_count": old_total,
        "new_token_count": sum(page["new_token_count"] for page in page_results),
        "identical_count": identical_total,
        "rebound_count": sum(page["rebound_count"] for page in page_results),
        "orphaned_count": sum(page["orphaned_count"] for page in page_results),
        "addition_count": sum(page["addition_count"] for page in page_results),
        "identity_rate": identical_total / old_total if old_total else 1.0,
    }


def _position_text_key(position: dict[str, Any]) -> str:
    readings = [
        str(candidate.get("candidate_key") or candidate.get("raw_reading") or "")
        for candidate in position.get("candidate_set", [])
    ]
    words = [
        "".join(_WORD_RE.findall(reading.lower()))
        for reading in readings
    ]
    words = [word for word in words if word]
    return min(words) if words else ""


def _bbox(value: dict[str, Any]) -> dict[str, float]:
    return {
        "x": float(value.get("x", 0.0)),
        "y": float(value.get("y", 0.0)),
        "w": float(value.get("w", 0.0)),
        "h": float(value.get("h", 0.0)),
    }


def _same_anchor(old: TokenAnchor, new: TokenAnchor) -> bool:
    return old.text_key == new.text_key and _bbox_iou(old.bbox, new.bbox) >= 0.50


def _match_score(old: TokenAnchor, new: TokenAnchor) -> dict[str, Any]:
    text_match = old.text_key and old.text_key == new.text_key
    iou = _bbox_iou(old.bbox, new.bbox)
    ordinal_distance = abs(old.ordinal - new.ordinal)
    if text_match and iou >= 0.50:
        return {
            "score": 1.0 + iou,
            "bbox_iou": iou,
            "match_method": "anchor_high_confidence" if ordinal_distance <= 3 else "anchor_partial",
        }
    if text_match and iou >= 0.20 and ordinal_distance <= 3:
        return {"score": 0.75 + iou, "bbox_iou": iou, "match_method": "anchor_partial"}
    return {"score": 0.0, "bbox_iou": iou, "match_method": "no_match"}


def _bbox_iou(a: dict[str, float], b: dict[str, float]) -> float:
    ax2 = a["x"] + max(a["w"], 0.0)
    ay2 = a["y"] + max(a["h"], 0.0)
    bx2 = b["x"] + max(b["w"], 0.0)
    by2 = b["y"] + max(b["h"], 0.0)
    ix1 = max(a["x"], b["x"])
    iy1 = max(a["y"], b["y"])
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    intersection = iw * ih
    union = max(a["w"], 0.0) * max(a["h"], 0.0) + max(b["w"], 0.0) * max(b["h"], 0.0) - intersection
    return intersection / union if union > 0 else 0.0


def _pair_record(
    old: TokenAnchor,
    new: TokenAnchor,
    match_method: str,
    score: dict[str, Any] | None = None,
) -> dict[str, Any]:
    score = score or {"bbox_iou": _bbox_iou(old.bbox, new.bbox)}
    return {
        "from_canonical_token_id": old.canonical_token_id,
        "to_canonical_token_id": new.canonical_token_id,
        "from_position_id": old.position_id,
        "to_position_id": new.position_id,
        "from_ordinal": old.ordinal,
        "to_ordinal": new.ordinal,
        "text_key": old.text_key,
        "bbox_iou": round(float(score.get("bbox_iou", 0.0)), 6),
        "match_method": match_method,
    }


def _orphan_record(old: TokenAnchor, candidates: list[str], reason: str) -> dict[str, Any]:
    return {
        "canonical_token_id": old.canonical_token_id,
        "position_id": old.position_id,
        "ordinal": old.ordinal,
        "text_key": old.text_key,
        "orphan_reason": reason,
        "match_method_attempted": "no_match" if not candidates else "ambiguous_target",
        "candidate_canonical_token_ids": candidates,
    }


def _synthetic_event_id(kind: str, payload: Any) -> str:
    encoded = json.dumps([kind, payload], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "de-sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
