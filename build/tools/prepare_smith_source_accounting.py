"""Bind Smith's exact retained JSONL unit order for accepted projection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "raw/bible_dictionaries/smiths.jsonl"
BASE = ROOT / "library/works/smiths-bible-dictionary/integration/smith-current-v1"
ACQUISITION = ROOT / "library/works/smiths-bible-dictionary/forms/smiths-bible-dictionary-retained-electronic/editions/smiths-bible-dictionary-retained-electronic-witness/acquisitions/smiths-bible-dictionary-retained-source.json"
ROOT_REVIEW = ROOT / "reports/_logs/smith-coordinator-source-review-20261002-v1/review.json"
HISTORICAL = Path("D:/Library/Open Christian Data/candidate-reviews/jwbickel-dictionaries-20260928-v1/smiths-bible-dictionary/package/source-accountability.json")
SOURCE_SHA = "ac91b1c3c359690c2953bd94b9d3dcb34f012a69d734179e82be5f07866cbe0d"
MASTER_SHA = "c4f3ff3a981f30dd816e6904af014e7eceb619d419f0f4f478fb1dcb34d43d8e"
ROOT_REVIEW_SHA = "67872b5d84a9dcaf43a8c5aaf3d23bdf37bd990727be6edd82b23c761d0d288a"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Smith source JSONL duplicate field: {key}")
        result[key] = value
    return result


def put(path: Path, value: dict) -> None:
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(payload)


def main() -> None:
    if digest(SOURCE) != SOURCE_SHA or digest(BASE / "candidate.tei.xml") != MASTER_SHA or digest(ROOT_REVIEW) != ROOT_REVIEW_SHA:
        raise ValueError("Smith source, header-only candidate, or root source review drifted")
    acquisition = json.loads(ACQUISITION.read_text(encoding="utf-8"))
    scope = acquisition["source_scope"]
    if scope != acquisition["retained_files"][0]["scope"]:
        raise ValueError("Smith acquisition scope differs")
    census: list[dict] = []
    definitions = 0
    with SOURCE.open("rb") as stream:
        for order, line in enumerate(stream, 1):
            if not line.strip():
                raise ValueError(f"Smith blank source line: {order}")
            record = json.loads(line.decode("utf-8"), object_pairs_hook=unique_object)
            blocks = record.get("definitions")
            if set(record) != {"term", "definitions"} or not isinstance(record["term"], str) or not isinstance(blocks, list) or not blocks or any(not isinstance(value, str) for value in blocks):
                raise ValueError(f"Smith source shape differs at record {order}")
            census.append({"id": f"smiths-bible-dictionary-entry-{order:05d}", "source_order": order, "source_record_sha256": hashlib.sha256(line).hexdigest(), "definition_count": len(blocks)})
            definitions += len(blocks)
    if len(census) != 4560 or definitions != 5362:
        raise ValueError("Smith complete source census differs")
    accounting = {
        "contract": "ocd-smith-current-source-accounting-v1",
        "entry_kind": "dictionary-entry",
        "projection_context": {
            "entry_kind": "dictionary-entry",
            "source_selector": {"tei_entry_profile": "smith-native-lexical-v1"},
            "source_scope": scope,
            "source_unit_count": len(census),
            "source_selected_units": [item["id"] for item in census],
            "source_census": census,
            "source_excerpt_sha256": SOURCE_SHA,
        },
        "source_path": "raw/bible_dictionaries/smiths.jsonl",
        "source_sha256": SOURCE_SHA,
        "candidate_master_sha256": MASTER_SHA,
        "definition_count": definitions,
        "historical_crosswalk": {"path": HISTORICAL.as_posix(), "sha256": digest(HISTORICAL)},
        "coordinator_source_review": {"path": ROOT_REVIEW.relative_to(ROOT).as_posix(), "sha256": ROOT_REVIEW_SHA},
        "technical_scope": "Exact retained electronic JSONL line order, literal term, and ordered definitions; no print-edition or rights claim.",
    }
    put(BASE / "source-accounting.json", accounting)
    print(json.dumps({"source_accounting_sha256": digest(BASE / "source-accounting.json"), "records": len(census), "definitions": definitions}, sort_keys=True))


if __name__ == "__main__":
    main()
