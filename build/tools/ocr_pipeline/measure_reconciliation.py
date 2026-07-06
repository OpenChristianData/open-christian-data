"""Measure a reconciled page sample against CCEL proposal alignments.

The outputs are measurement artefacts, not architecture decisions. CCEL is always
labelled as an evaluation reference / proposal, never canonical truth.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.atomic_io import write_json_atomic  # noqa: E402
from build.lib.family_independence import DEFAULT_DEPENDENCE_THRESHOLD  # noqa: E402
from build.lib.ocr_store_paths import RECONCILED_ROOT, WCT_ROOT  # noqa: E402
from build.lib.s3_reconciler import _best_candidate  # noqa: E402
from build.tools.ocr_pipeline.drive_reconciliation_chain import page_native_id, volume_label  # noqa: E402

OBJECT_SCHEMA = {"type": "object"}
REFERENCE_LABEL = "CCEL ThML page text aligned to WCT (PROPOSAL_NOT_GOLD)"
MATRIX_REFERENCE_LABEL = "existing S3 degraded reconciler chosen_reading scored against CCEL proposal alignment"
TARGET_CONFIDENCE_FAMILIES = {"kraken", "surya", "tesseract"}


@dataclass(frozen=True)
class CalibrationRow:
    confidence: float
    correct: bool


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _norm(token: str | None) -> str:
    if token is None:
        return ""
    folded = unicodedata.normalize("NFKC", token).casefold()
    return re.sub(r"^\W+|\W+$", "", folded, flags=re.UNICODE)


def _script_code(label: str) -> str:
    return {"greek": "grc", "hebrew": "hbo"}.get(label, "latin")


def levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    prev = list(range(len(right) + 1))
    for i, lch in enumerate(left, start=1):
        cur = [i]
        for j, rch in enumerate(right, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (lch != rch)))
        prev = cur
    return prev[-1]


def calibration_curve(rows: Sequence[CalibrationRow], *, bins: int = 10) -> dict:
    buckets = [
        {"bin": index, "lower": index / bins, "upper": (index + 1) / bins, "n": 0, "avg_confidence": 0.0, "accuracy": 0.0}
        for index in range(bins)
    ]
    for row in rows:
        conf = min(max(row.confidence, 0.0), 1.0)
        index = min(int(conf * bins), bins - 1)
        buckets[index]["n"] += 1
        buckets[index]["avg_confidence"] += conf
        buckets[index]["accuracy"] += 1.0 if row.correct else 0.0
    total = len(rows)
    ece = 0.0
    for bucket in buckets:
        if bucket["n"]:
            bucket["avg_confidence"] = bucket["avg_confidence"] / bucket["n"]
            bucket["accuracy"] = bucket["accuracy"] / bucket["n"]
            ece += (bucket["n"] / total) * abs(bucket["accuracy"] - bucket["avg_confidence"])
        bucket["avg_confidence"] = round(bucket["avg_confidence"], 6)
        bucket["accuracy"] = round(bucket["accuracy"], 6)
    return {"token_count": total, "ece": round(ece, 6), "bins": buckets}


def _confidence_to_unit(value: object) -> float | None:
    if value is None:
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence > 1.0:
        confidence = confidence / 100.0
    return min(max(confidence, 0.0), 1.0)


def independent_agreement_candidates(candidates: Sequence[Mapping], family_blocks: Mapping[str, str]) -> list[Mapping]:
    agreed: list[Mapping] = []
    for candidate in candidates:
        blocks = {
            family_blocks.get(family, family)
            for family in candidate.get("attesting_families", [])
        }
        if len(blocks) >= 2:
            agreed.append(candidate)
    return agreed


def _pair_key(left: str, right: str) -> str:
    low, high = sorted((left, right))
    return f"{low}__{high}"


def _find(parent: dict[str, str], node: str) -> str:
    root = node
    while parent[root] != root:
        root = parent[root]
    while parent[node] != root:
        parent[node], node = root, parent[node]
    return root


def _union(parent: dict[str, str], left: str, right: str) -> None:
    root_left, root_right = _find(parent, left), _find(parent, right)
    if root_left != root_right:
        low, high = sorted((root_left, root_right))
        parent[high] = low


def family_blocks_from_positions(pages: Sequence[dict], refs_by_page: Mapping[str, Mapping[str, str]]) -> dict:
    families = sorted(
        {
            engine["family"]
            for page in pages
            for engine in page.get("available_engines", [])
        }
    )
    if not families:
        return {}
    parent = {family: family for family in families}
    numerator: dict[str, int] = {}
    denominator: dict[str, int] = {}
    for page in pages:
        refs = refs_by_page.get(page["page_id"], {})
        for position in page.get("positions", []):
            gold = refs.get(position["position_id"])
            if gold is None:
                continue
            by_family: dict[str, str] = {}
            for span in position.get("span_records", []):
                if span.get("token_span_type") == "skip":
                    continue
                by_family.setdefault(span["family"], _norm(span.get("raw_text")))
            present = sorted(by_family)
            for i in range(len(present)):
                for j in range(i + 1, len(present)):
                    key = _pair_key(present[i], present[j])
                    denominator[key] = denominator.get(key, 0) + 1
                    if by_family[present[i]] == by_family[present[j]] and by_family[present[i]] != _norm(gold):
                        numerator[key] = numerator.get(key, 0) + 1

    for i in range(len(families)):
        for j in range(i + 1, len(families)):
            key = _pair_key(families[i], families[j])
            if denominator.get(key, 0) == 0:
                _union(parent, families[i], families[j])
                continue
            same_wrong = numerator.get(key, 0) / denominator[key]
            if same_wrong >= DEFAULT_DEPENDENCE_THRESHOLD:
                _union(parent, families[i], families[j])

    roots: dict[str, str] = {}
    block_index = 0
    result: dict[str, str] = {}
    for family in families:
        root = _find(parent, family)
        if root not in roots:
            block_index += 1
            roots[root] = f"family-block-{block_index}"
        result[family] = roots[root]
    return result


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _ccel_refs(alignment: dict) -> dict[str, str]:
    refs: dict[str, str] = {}
    for item in alignment.get("gold_candidates", []):
        if item.get("position_id"):
            refs[item["position_id"]] = item.get("ccel_token")
    for item in alignment.get("reviewer_queue", []):
        if item.get("position_id") and item.get("ccel_token") is not None:
            refs[item["position_id"]] = item.get("ccel_token")
    return refs


def _ccel_strata(alignment: dict) -> dict[str, str]:
    """position_id -> scoring stratum, mirroring _ccel_refs membership exactly.

    The reference bucket is consensus-conditioned: gold_candidates are positions where
    the CCEL token equals the OCR reading after normalization; the surviving
    reviewer_queue refs are ccel_ocr_disagreement positions where it does not. Scoring
    an OCR/reconciler reading against this reference is therefore correct-by-construction
    on the gold stratum and wrong-by-construction on the disagreement stratum, so M2/M3
    must report the two strata separately rather than pool them. Must stay in lock-step
    with _ccel_refs (test_ccel_refs_and_strata_membership_mirror_each_other guards it).
    """
    strata: dict[str, str] = {}
    for item in alignment.get("gold_candidates", []):
        if item.get("position_id"):
            strata[item["position_id"]] = "gold"
    for item in alignment.get("reviewer_queue", []):
        if item.get("position_id") and item.get("ccel_token") is not None:
            strata[item["position_id"]] = "ccel_ocr_disagreement"
    return strata


def _stratify(
    rows: Iterable[dict],
    strata_by_page: Mapping[str, Mapping[str, str]],
    *,
    error_field: str,
    error_label: str,
) -> dict[str, dict]:
    """Tally rows into gold / ccel_ocr_disagreement strata.

    `error_field` is the boolean row key meaning "scored correct" (True == correct);
    `error_label` is the output key for the wrong-count ("errors" for M2, "wrong" for
    M3). The companion rate key is "error_rate" for M2 and "accuracy" for M3.
    """
    buckets = {
        stratum: {"n": 0, error_label: 0}
        for stratum in ("gold", "ccel_ocr_disagreement")
    }
    for row in rows:
        stratum = strata_by_page[row["page_id"]][row["position_id"]]
        bucket = buckets[stratum]
        bucket["n"] += 1
        if not row[error_field]:
            bucket[error_label] += 1
    for bucket in buckets.values():
        if error_label == "wrong":
            bucket["accuracy"] = (
                round((bucket["n"] - bucket["wrong"]) / bucket["n"], 6) if bucket["n"] else None
            )
        else:
            bucket["error_rate"] = round(bucket["errors"] / bucket["n"], 6) if bucket["n"] else None
    return buckets


def _aggregate_quality(rows: Iterable[dict]) -> dict:
    groups: dict[str, dict] = {}
    for row in rows:
        key = f"{row['region_type']}|{row['script']}"
        group = groups.setdefault(
            key,
            {
                "region_type": row["region_type"],
                "script": row["script"],
                "token_count": 0,
                "incorrect_tokens": 0,
                "char_edits": 0,
                "reference_chars": 0,
            },
        )
        group["token_count"] += 1
        group["incorrect_tokens"] += 0 if row["correct"] else 1
        group["char_edits"] += row["char_edits"]
        group["reference_chars"] += row["reference_chars"]
    out: list[dict] = []
    for group in sorted(groups.values(), key=lambda item: (item["region_type"], item["script"])):
        token_count = group["token_count"]
        ref_chars = group["reference_chars"]
        group["wer"] = round(group["incorrect_tokens"] / token_count, 6) if token_count else None
        group["cer"] = round(group["char_edits"] / ref_chars, 6) if ref_chars else None
        out.append(group)
    return {"groups": out}


def build_measurements(
    *,
    volume: int,
    pages: Sequence[int],
    wct_root: Path,
    reconciled_root: Path,
    gold_root: Path,
) -> dict[str, dict]:
    page_docs: list[dict] = []
    refs_by_page: dict[str, dict[str, str]] = {}
    strata_by_page: dict[str, dict[str, str]] = {}
    alignments_by_page: dict[str, dict] = {}
    reviewer_by_page: dict[str, dict[str, dict]] = {}
    for page in pages:
        pid = page_native_id(page)
        vol_label = volume_label(volume)
        wct = _load_json(wct_root / vol_label / f"{pid}.json")
        alignment = _load_json(gold_root / vol_label / f"ccel_wct_alignment_{pid}.json")
        reviewer = _load_json(reconciled_root / vol_label / f"{pid}.reviewer_queue.json")
        page_docs.append(wct)
        refs_by_page[pid] = _ccel_refs(alignment)
        strata_by_page[pid] = _ccel_strata(alignment)
        alignments_by_page[pid] = alignment
        reviewer_by_page[pid] = {
            item["position_id"]: item
            for item in reviewer.get("queue", [])
            if item.get("position_id")
        }

    family_blocks = family_blocks_from_positions(page_docs, refs_by_page)
    generated_at = _utc_now()
    page_ids = [page_native_id(page) for page in pages]

    quality_rows_by_engine: dict[str, list[dict]] = {}
    calibration_rows_by_engine: dict[str, list[CalibrationRow]] = {}
    geometry_engines: set[str] = set()
    auto_accept_rows: list[dict] = []
    circular_auto_accept_rows: list[dict] = []
    disagreement_rows: list[dict] = []
    adjudication_rows: list[dict] = []

    for wct in page_docs:
        page_id = wct["page_id"]
        refs = refs_by_page[page_id]
        source_image = wct.get("source_image", {})
        for position in wct.get("positions", []):
            position_id = position["position_id"]
            reference = refs.get(position_id)
            if reference is None:
                continue
            reference_norm = _norm(reference)
            region_type = position.get("zone", {}).get("zone_type", "unknown")
            script = _script_code(position.get("script", {}).get("text_level", {}).get("label", "latin"))
            candidates = position.get("candidate_set", [])
            for span in position.get("span_records", []):
                if span.get("token_span_type") == "skip":
                    continue
                if any(source_span.get("bbox") for source_span in span.get("source_spans", [])):
                    geometry_engines.add(span["engine_id"])
                raw = span.get("raw_text")
                raw_norm = _norm(raw)
                correct = raw_norm == reference_norm
                quality_rows_by_engine.setdefault(span["engine_id"], []).append(
                    {
                        "region_type": region_type,
                        "script": script,
                        "correct": correct,
                        "char_edits": levenshtein(raw_norm, reference_norm),
                        "reference_chars": len(reference_norm),
                    }
                )
                confidence = _confidence_to_unit(span.get("raw_confidence"))
                if confidence is not None:
                    calibration_rows_by_engine.setdefault(span["engine_id"], []).append(
                        CalibrationRow(confidence=confidence, correct=correct)
                    )

            agreed = independent_agreement_candidates(candidates, family_blocks)
            for candidate in agreed:
                row = {
                    "page_id": page_id,
                    "position_id": position_id,
                    "candidate": candidate.get("raw_reading"),
                    "ccel_proposal": reference,
                    "correct_against_ccel": _norm(candidate.get("raw_reading")) == reference_norm,
                    "attesting_families": candidate.get("attesting_families", []),
                    "independent_blocks": sorted(
                        {
                            family_blocks.get(family, family)
                            for family in candidate.get("attesting_families", [])
                        }
                    ),
                }
                if "ccel" in {str(family).casefold() for family in candidate.get("attesting_families", [])}:
                    circular_auto_accept_rows.append(row)
                else:
                    auto_accept_rows.append(row)

            candidate_block_readings = {
                _norm(candidate.get("raw_reading")): {
                    family_blocks.get(family, family)
                    for family in candidate.get("attesting_families", [])
                }
                for candidate in candidates
            }
            families_disagree = len(candidate_block_readings) > 1
            agreed_but_ccel_dissents = (
                len(candidate_block_readings) == 1
                and reference_norm not in candidate_block_readings
            )
            if families_disagree:
                chosen = reviewer_by_page[page_id].get(position_id, {}).get("chosen_reading")
                if chosen is None and candidates:
                    chosen = _best_candidate(candidates).get("raw_reading")
                disagreement_rows.append(
                    {
                        "page_id": page_id,
                        "position_id": position_id,
                        "matrix_chosen_reading": chosen,
                        "ccel_proposal": reference,
                        "matrix_choice_correct_against_ccel": _norm(chosen) == reference_norm,
                        "candidate_count": len(candidates),
                    }
                )
            if families_disagree or agreed_but_ccel_dissents:
                uncertainty = 1.0 - float(position.get("alignment_confidence", 0.0) or 0.0)
                score = len(candidates) + uncertainty + (1.0 if agreed_but_ccel_dissents else 0.0)
                adjudication_rows.append(
                    {
                        "page_id": page_id,
                        "position_id": position_id,
                        "rank_score": round(score, 6),
                        "reason": "families_disagree" if families_disagree else "engines_agree_ccel_dissents",
                        "image_crop": {
                            "source_image": source_image.get("path"),
                            "reference_bbox": position.get("reference_bbox"),
                        },
                        "candidate_readings": [
                            {
                                "raw_reading": candidate.get("raw_reading"),
                                "attesting_engines": candidate.get("attesting_engines", []),
                                "attesting_families": candidate.get("attesting_families", []),
                                "independent_blocks": sorted(
                                    {
                                        family_blocks.get(family, family)
                                        for family in candidate.get("attesting_families", [])
                                    }
                                ),
                            }
                            for candidate in candidates
                        ],
                        "ccel_proposal": reference,
                    }
                )

    m0_engines = {}
    for engine_id, rows in sorted(quality_rows_by_engine.items()):
        if engine_id not in geometry_engines:
            continue
        total = _aggregate_quality(rows)
        total["overall"] = _quality_overall(rows)
        m0_engines[engine_id] = total

    m1_engines = {}
    for engine_id, rows in sorted(calibration_rows_by_engine.items()):
        family = _engine_family(page_docs, engine_id)
        m1_engines[engine_id] = {
            "engine_family": family,
            "included_in_prompt_target": family in TARGET_CONFIDENCE_FAMILIES,
            **calibration_curve(rows),
        }

    m2_n = len(auto_accept_rows)
    m2_correct = sum(1 for row in auto_accept_rows if row["correct_against_ccel"])
    m2_strata = _stratify(
        auto_accept_rows, strata_by_page, error_field="correct_against_ccel", error_label="errors"
    )
    m3_n = len(disagreement_rows)
    m3_correct = sum(1 for row in disagreement_rows if row["matrix_choice_correct_against_ccel"])
    m3_strata = _stratify(
        disagreement_rows,
        strata_by_page,
        error_field="matrix_choice_correct_against_ccel",
        error_label="wrong",
    )
    adjudication_rows.sort(key=lambda item: item["rank_score"], reverse=True)

    m2_circularity_note = (
        "Pooled rate reflects the gold vs ccel_ocr_disagreement bucket mix, not auto-accept "
        "accuracy. Gold positions are CCEL==OCR-reading by construction (near-zero error) and "
        "disagreement positions are CCEL!=OCR-reading by construction (near-total error), so the "
        "pooled number tracks the bucket split. Read the per-stratum breakdown in `strata`."
    )
    m3_matrix_circularity_note = (
        "Pooled accuracy equals the gold fraction: gold positions score correct by construction and "
        "disagreement positions wrong by construction. NOT a reconciler-quality number. Read the "
        "per-stratum breakdown in `strata`."
    )
    m3_interpretation_note = (
        "Both rules are scored against a CCEL reference whose gold/disagreement buckets are defined "
        "by CCEL==OCR-reading agreement, so this run cannot distinguish matrix-rule quality from "
        "agree->escalate. The matrix-vs-agree->escalate A/B below is NOT interpretable as reconciler "
        "quality under this reference; a non-circular reference is required (see "
        "docs/MEASUREMENT_REFERENCE_OPTIONS.md)."
    )

    return {
        "family_independence": {
            "artifact_kind": "measurement-family-independence",
            "generated_at": generated_at,
            "pages": page_ids,
            "reference": REFERENCE_LABEL,
            "fail_closed_rule": "unmeasured family pairs are collapsed into one independent block",
            "family_blocks": family_blocks,
            "dependence_threshold": DEFAULT_DEPENDENCE_THRESHOLD,
        },
        "m0_single_best_baseline_quality": {
            "artifact_kind": "measurement-m0-single-best-baseline-quality",
            "generated_at": generated_at,
            "pages": page_ids,
            "reference": REFERENCE_LABEL,
            "population": "engine span records with word geometry and a CCEL-aligned WCT position",
            "engines": m0_engines,
        },
        "m1_confidence_calibration": {
            "artifact_kind": "measurement-m1-confidence-calibration",
            "generated_at": generated_at,
            "pages": page_ids,
            "reference": REFERENCE_LABEL,
            "population": "engine span records with raw_confidence and a CCEL-aligned WCT position",
            "bins": 10,
            "engines": m1_engines,
        },
        "m2_auto_accept_audit": {
            "artifact_kind": "measurement-m2-auto-accept-audit",
            "generated_at": generated_at,
            "pages": page_ids,
            "reference": REFERENCE_LABEL,
            "population": "candidate readings attested by at least two independent non-CCEL family blocks",
            "circular_subset_present": bool(circular_auto_accept_rows),
            "circular_subset_excluded_from_headline": True,
            "headline": {
                "n": m2_n,
                "correct": m2_correct,
                "errors": m2_n - m2_correct,
                "pooled_error_rate_circular": round((m2_n - m2_correct) / m2_n, 6) if m2_n else None,
                "circularity_note": m2_circularity_note,
            },
            "strata": m2_strata,
            "circular_subset": {
                "n": len(circular_auto_accept_rows),
                "rows": circular_auto_accept_rows,
            },
        },
        "m3_truth_rule_ab": {
            "artifact_kind": "measurement-m3-truth-rule-ab",
            "generated_at": generated_at,
            "pages": page_ids,
            "reference": MATRIX_REFERENCE_LABEL,
            "population": "CCEL-aligned positions where independent family candidate readings disagree",
            "interpretation_note": m3_interpretation_note,
            "matrix_rule": {
                "n": m3_n,
                "auto_choice_count": sum(1 for row in disagreement_rows if row["matrix_chosen_reading"] is not None),
                "correct_auto_choices": m3_correct,
                "pooled_auto_choice_accuracy_circular": round(m3_correct / m3_n, 6) if m3_n else None,
                "circularity_note": m3_matrix_circularity_note,
                "strata": m3_strata,
                "reviewer_queue_size": sum(
                    len(_load_json(reconciled_root / volume_label(volume) / f"{page_native_id(page)}.reviewer_queue.json").get("queue", []))
                    for page in pages
                ),
            },
            "simple_agree_escalate_rule": {
                "auto_choice_count": 0,
                "reviewer_queue_size_for_disagreements": m3_n,
            },
        },
        "adjudication_queue": {
            "artifact_kind": "measurement-adjudication-queue",
            "generated_at": generated_at,
            "pages": page_ids,
            "reference": REFERENCE_LABEL,
            "population": "every CCEL-aligned position where engine families disagree, or engines agree and CCEL dissents",
            "items": adjudication_rows,
        },
    }


def _quality_overall(rows: Sequence[dict]) -> dict:
    token_count = len(rows)
    incorrect = sum(1 for row in rows if not row["correct"])
    edits = sum(row["char_edits"] for row in rows)
    ref_chars = sum(row["reference_chars"] for row in rows)
    return {
        "token_count": token_count,
        "incorrect_tokens": incorrect,
        "wer": round(incorrect / token_count, 6) if token_count else None,
        "char_edits": edits,
        "reference_chars": ref_chars,
        "cer": round(edits / ref_chars, 6) if ref_chars else None,
    }


def _engine_family(pages: Sequence[dict], engine_id: str) -> str | None:
    for page in pages:
        for engine in page.get("available_engines", []):
            if engine.get("engine_id") == engine_id:
                return engine.get("family")
    return None


def write_measurements(measurements: Mapping[str, dict], output_root: Path) -> dict[str, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, payload in measurements.items():
        path = output_root / f"{name}.json"
        write_json_atomic(path, payload, OBJECT_SCHEMA)
        paths[name] = path
    return paths


def print_population_summary(measurements: Mapping[str, dict]) -> None:
    m0 = measurements["m0_single_best_baseline_quality"]
    for engine_id, payload in m0["engines"].items():
        overall = payload["overall"]
        print(f"M0 reference={m0['reference']} engine={engine_id} N={overall['token_count']} WER={overall['wer']} CER={overall['cer']}")
    m1 = measurements["m1_confidence_calibration"]
    for engine_id, payload in m1["engines"].items():
        print(f"M1 reference={m1['reference']} engine={engine_id} N={payload['token_count']} ECE={payload['ece']}")
    m2 = measurements["m2_auto_accept_audit"]
    m2_gold = m2["strata"]["gold"]
    m2_dis = m2["strata"]["ccel_ocr_disagreement"]
    print(
        f"M2 reference={m2['reference']} N={m2['headline']['n']} "
        f"pooled_error_rate_circular={m2['headline']['pooled_error_rate_circular']} "
        f"(CIRCULAR -- bucket mix); gold[n={m2_gold['n']} err={m2_gold['errors']}] "
        f"disagreement[n={m2_dis['n']} err={m2_dis['errors']}]"
    )
    m3 = measurements["m3_truth_rule_ab"]
    m3_gold = m3["matrix_rule"]["strata"]["gold"]
    m3_dis = m3["matrix_rule"]["strata"]["ccel_ocr_disagreement"]
    print(
        f"M3 reference={m3['reference']} N={m3['matrix_rule']['n']} "
        f"pooled_auto_choice_accuracy_circular={m3['matrix_rule']['pooled_auto_choice_accuracy_circular']} "
        f"(CIRCULAR -- equals gold fraction); gold[n={m3_gold['n']} wrong={m3_gold['wrong']}] "
        f"disagreement[n={m3_dis['n']} wrong={m3_dis['wrong']}]"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--volume", type=int, default=1)
    parser.add_argument("--pages", nargs="+", required=True)
    parser.add_argument("--wct-root", type=Path, default=WCT_ROOT)
    parser.add_argument("--reconciled-root", type=Path, default=RECONCILED_ROOT)
    parser.add_argument("--gold-root", type=Path, default=REPO_ROOT / "reports" / "gold")
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT / "reports" / "measurement" / "vol_01")
    return parser


def _parse_pages(values: Sequence[str]) -> list[int]:
    pages: set[int] = set()
    for token in values:
        if "-" in token:
            lo, hi = token.split("-", 1)
            pages.update(range(int(lo), int(hi) + 1))
        else:
            pages.add(int(token))
    return sorted(pages)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    measurements = build_measurements(
        volume=args.volume,
        pages=_parse_pages(args.pages),
        wct_root=args.wct_root,
        reconciled_root=args.reconciled_root,
        gold_root=args.gold_root,
    )
    paths = write_measurements(measurements, args.output_root)
    print_population_summary(measurements)
    for name, path in paths.items():
        print(f"wrote {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
