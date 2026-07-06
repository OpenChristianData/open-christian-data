"""Track-C adjudication worksheet builder.

Samples stratified WCT positions from Schaff-Herzog vol_01 pages and emits a CSV
worksheet for human adjudication. The human reads each token from the scan image
and fills in gold_text.

NON-CIRCULARITY GUARANTEE: gold_text is ALWAYS written as blank. The emitted
"engine_guesses_do_not_copy" column is for human orientation only — it must never
be copied into gold_text. A single engine-derived gold value silently corrupts the
Track-C transfer measurement with no automated recovery.
"""
from __future__ import annotations

import csv
import json
import pathlib
import random
from typing import TypedDict


class WorksheetRow(TypedDict):
    position_id: str
    page_id: str
    scan_path: str
    bbox_x: int | str
    bbox_y: int | str
    bbox_w: int | str
    bbox_h: int | str
    script_label: str
    gold_text: str  # ALWAYS BLANK on output; human fills from scan
    engine_guesses_do_not_copy: str  # for orientation only; never pre-fill gold_text


WORKSHEET_COLUMNS = [
    "position_id",
    "page_id",
    "scan_path",
    "bbox_x",
    "bbox_y",
    "bbox_w",
    "bbox_h",
    "script_label",
    "gold_text",
    "engine_guesses_do_not_copy",
]


def build_worksheet_row(position: dict, scan_path: str, page_id: str) -> WorksheetRow:
    """Convert one WCT position to a worksheet row with blank gold_text."""
    bbox = position.get("reference_bbox") or {}
    return WorksheetRow(
        position_id=position["position_id"],
        page_id=page_id,
        scan_path=scan_path,
        bbox_x=bbox.get("x", ""),
        bbox_y=bbox.get("y", ""),
        bbox_w=bbox.get("w", ""),
        bbox_h=bbox.get("h", ""),
        script_label=_get_script_label(position),
        gold_text="",  # INVARIANT: never pre-fill; human reads from scan
        engine_guesses_do_not_copy=" | ".join(_get_candidate_readings(position)),
    )


def sample_positions(
    wct_pages: list[dict],
    strategy: dict[str, int],
    *,
    seed: int = 42,
) -> list[WorksheetRow]:
    """Sample positions from WCT pages per the stratification strategy.

    strategy keys:
        latin_disagree   -- candidate_set>1, script=latin
        latin_agree      -- candidate_set==1, script=latin
        greek            -- script=greek (any candidate count)
        hebrew           -- script=hebrew (any candidate count)
        unknown_disagree -- candidate_set>1, script=unknown (optional)

    Caps silently at available count per stratum.
    All returned rows have blank gold_text.
    """
    rng = random.Random(seed)

    buckets: dict[str, list[tuple[dict, str, str]]] = {
        "latin_disagree": [],
        "latin_agree": [],
        "greek": [],
        "hebrew": [],
        "unknown_disagree": [],
    }

    for page in wct_pages:
        page_id = page["page_id"]
        scan_path = page.get("source_image", {}).get("path", "")
        for pos in page.get("positions", []):
            label = _get_script_label(pos)
            n_candidates = len(pos.get("candidate_set", []))
            if label == "latin" and n_candidates > 1:
                buckets["latin_disagree"].append((pos, scan_path, page_id))
            elif label == "latin" and n_candidates <= 1:
                buckets["latin_agree"].append((pos, scan_path, page_id))
            elif label == "greek":
                buckets["greek"].append((pos, scan_path, page_id))
            elif label == "hebrew":
                buckets["hebrew"].append((pos, scan_path, page_id))
            elif label == "unknown" and n_candidates > 1:
                buckets["unknown_disagree"].append((pos, scan_path, page_id))

    rows: list[WorksheetRow] = []
    for stratum, target in strategy.items():
        if target <= 0:
            continue
        pool = buckets.get(stratum, [])
        selected = rng.sample(pool, min(target, len(pool)))
        for pos, scan_path, page_id in selected:
            rows.append(build_worksheet_row(pos, scan_path, page_id))

    return rows


def write_worksheet(rows: list[WorksheetRow], output_path: pathlib.Path) -> None:
    """Write worksheet rows to a UTF-8 CSV file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=WORKSHEET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _get_script_label(position: dict) -> str:
    """Return the script label for a position, lowercased."""
    script = position.get("script")
    if isinstance(script, dict):
        text_label = script.get("text_level", {}).get("label") if isinstance(script.get("text_level"), dict) else None
        image_label = script.get("image_level", {}).get("label") if isinstance(script.get("image_level"), dict) else None
        label = text_label or image_label
        return str(label).lower() if label else "unknown"
    if isinstance(script, str):
        return script.lower()
    return "unknown"


def _get_candidate_readings(position: dict) -> list[str]:
    """Return deduplicated candidate readings, preferring raw_reading over candidate_key."""
    seen: set[str] = set()
    out: list[str] = []
    for candidate in position.get("candidate_set", []):
        reading = candidate.get("raw_reading") or candidate.get("candidate_key")
        if reading is not None:
            text = str(reading)
            if text not in seen:
                seen.add(text)
                out.append(text)
    return out


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build Track-C adjudication worksheet")
    parser.add_argument("--wct-dir", type=pathlib.Path, required=True, help="Directory of WCT page JSON files")
    parser.add_argument("--output", type=pathlib.Path, required=True, help="Output worksheet CSV path")
    parser.add_argument("--latin-disagree", type=int, default=80)
    parser.add_argument("--latin-agree", type=int, default=40)
    parser.add_argument("--greek", type=int, default=40)
    parser.add_argument("--hebrew", type=int, default=20)
    parser.add_argument("--unknown-disagree", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    wct_pages = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(args.wct_dir.glob("*.json"))
    ]
    strategy = {
        "latin_disagree": args.latin_disagree,
        "latin_agree": args.latin_agree,
        "greek": args.greek,
        "hebrew": args.hebrew,
        "unknown_disagree": args.unknown_disagree,
    }
    rows = sample_positions(wct_pages, strategy, seed=args.seed)
    write_worksheet(rows, args.output)

    by_stratum: dict[str, int] = {}
    for row in rows:
        lbl = row["script_label"]
        disagree = "|" in row["engine_guesses_do_not_copy"]
        key = f"{lbl}_{'disagree' if disagree else 'agree'}"
        by_stratum[key] = by_stratum.get(key, 0) + 1

    print(f"Worksheet written: {args.output}")
    print(f"Total rows: {len(rows)}")
    for k, v in sorted(by_stratum.items()):
        print(f"  {k}: {v}")
