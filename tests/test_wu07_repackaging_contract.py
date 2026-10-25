"""Bounded WU-07 checks for public occurrence identity across packaging."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from ocd_kernel.projection.envelope import canonical_row_bytes, project_document
from ocd_kernel.projection.receipt import build_correspondence_receipt
from ocd_kernel.release.verify import verify_document


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/fixtures/library-pipeline/correspondence/variation.tei.xml"
CONTEXT = {
    "identity": {
        "work_id": "work",
        "textual_form_id": "form",
        "edition_id": "edition",
    },
    "language": "en",
    "representation_revision": "wu07-test-v1",
    "edition_title": "Example edition",
}


def _projection() -> tuple[list[dict], dict]:
    projection = project_document(SOURCE, **CONTEXT)
    return projection["rows"], build_correspondence_receipt(
        projection, identity=CONTEXT["identity"]
    )


def test_packaging_round_trip_preserves_public_occurrences_and_ids():
    rows, receipt = _projection()
    packaged = canonical_row_bytes(rows)
    unpackaged = [json.loads(line) for line in packaged.decode().splitlines()]

    assert [(row["record_id"], row["text"], row["sequence"]) for row in unpackaged] == [
        (row["record_id"], row["text"], row["sequence"]) for row in rows
    ]
    assert verify_document(SOURCE, unpackaged, receipt, **CONTEXT) == []


def test_repackaging_cannot_hide_reordered_or_duplicated_occurrences():
    rows, receipt = _projection()

    reordered = copy.deepcopy(rows)
    reordered.reverse()
    assert verify_document(SOURCE, reordered, receipt, **CONTEXT)

    duplicated = copy.deepcopy(rows)
    duplicated.append(copy.deepcopy(duplicated[0]))
    assert verify_document(SOURCE, duplicated, receipt, **CONTEXT)
