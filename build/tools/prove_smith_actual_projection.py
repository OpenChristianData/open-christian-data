"""Project the whole prepared Smith witness under the unapplied adapter proposal."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

from ocd_kernel.projection.categories import reference_entries as current


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "library/works/smiths-bible-dictionary/integration/smith-current-v1"
OUT = ROOT / "reports/_logs/smiths-bible-dictionary-current-reconciliation-20261002-v1/native-support-proposal"
PROPOSED = OUT / "reference_entries.after.py"
SOURCE = ROOT / "raw/bible_dictionaries/smiths.jsonl"
MASTER_SHA = "c4f3ff3a981f30dd816e6904af014e7eceb619d419f0f4f478fb1dcb34d43d8e"
SOURCE_SHA = "ac91b1c3c359690c2953bd94b9d3dcb34f012a69d734179e82be5f07866cbe0d"
ADAPTER_SHA = "37addf99c4327533995f185d15b3a0b56ce63fb4ea6e2f7a4584e94995e25e08"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def main() -> None:
    candidate = WORK / "candidate.tei.xml"
    if digest(candidate) != MASTER_SHA or digest(SOURCE) != SOURCE_SHA or digest(PROPOSED) != ADAPTER_SHA:
        raise ValueError("Smith proposed projection input drifted")
    spec = importlib.util.spec_from_file_location("smith_actual_proposed_reference", PROPOSED)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load proposed Smith adapter")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    adapter.ROOT, adapter.SCHEMA, adapter.COMMON = current.ROOT, current.SCHEMA, current.COMMON
    accounting = json.loads((WORK / "source-accounting.json").read_text(encoding="utf-8"))
    context = {
        "identity": {"work_id": "smiths-bible-dictionary", "textual_form_id": "smiths-bible-dictionary-retained-electronic", "edition_id": "smiths-bible-dictionary-retained-electronic-witness"},
        "language": "en",
        "representation_revision": "smiths-retained-electronic-technical-v1",
        "edition_title": "JWBickel/BibleDictionaries retained electronic witness",
        "source_url": "https://huggingface.co/datasets/JWBickel/BibleDictionaries",
        "source_sha256": SOURCE_SHA,
        "retained_sha256": SOURCE_SHA,
        "source_path": SOURCE,
        "source_logical_path": "raw/bible_dictionaries/smiths.jsonl",
        **accounting["projection_context"],
    }
    projection = adapter.project_reference_entries(candidate, **context)
    receipt = adapter.build_reference_entries_receipt(projection, identity=context["identity"])
    rows = projection["rows"]
    if len(rows) != 4560 or sum(len(row["definition_blocks"]) for row in rows) != 5362:
        raise ValueError("Smith whole projection counts differ")

    def disabled(*args: object, **kwargs: object) -> None:
        raise AssertionError("Producer or ElementTree lexical renderer called during independent check")

    adapter.project_reference_entries = disabled
    adapter._easton_lexical = disabled
    adapter._render = disabled
    errors = adapter.verify_reference_entries(candidate, rows, receipt, **context)
    if errors:
        raise ValueError(f"Smith independent full projection check failed: {errors[:5]}")
    save(OUT / "actual-projection.json", projection)
    save(OUT / "actual-projection-receipt.json", receipt)
    proof = {
        "contract": "ocd-smith-proposed-whole-projection-v1",
        "status": "pass",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "candidate_sha256": MASTER_SHA,
        "source_sha256": SOURCE_SHA,
        "adapter_proposed_sha256": ADAPTER_SHA,
        "schema_sha256": digest(adapter.SCHEMA),
        "common_schema_sha256": digest(adapter.COMMON),
        "rows": len(rows),
        "definition_blocks": sum(len(row["definition_blocks"]) for row in rows),
        "characters": sum(len(row["text"]) for row in rows),
        "independent_checker": "pass with producer and ElementTree lexical renderer disabled",
        "projection_sha256": digest(OUT / "actual-projection.json"),
        "receipt_sha256": digest(OUT / "actual-projection-receipt.json"),
        "source_body_comparison": "reports/_logs/smith-coordinator-source-review-20261002-v1/review.json",
        "shared_adapter_applied": False,
    }
    save(OUT / "actual-candidate-proof.json", proof)
    print(json.dumps({"status": "pass", "rows": proof["rows"], "definition_blocks": proof["definition_blocks"], "proof_sha256": digest(OUT / "actual-candidate-proof.json")}))


if __name__ == "__main__":
    main()
