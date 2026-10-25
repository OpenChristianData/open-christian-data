"""Focused accepted NPNF1-08 Psalms projection regression."""

from copy import deepcopy
import json
from pathlib import Path

from ocd_kernel.projection.categories.commentary import (
    project_accepted_commentary,
    verify_accepted_commentary,
)
from ocd_kernel.release.public_allowlist import _scan


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = Path(
    "library/works/augustine-expositions-on-psalms/forms/"
    "augustine-expositions-on-psalms-english/editions/"
    "augustine-expositions-on-psalms-retained-electronic-witness/acceptance.json"
)


def test_accepted_psalms_native_divisions_and_comments() -> None:
    projection = project_accepted_commentary(ROOT, acceptance_path=ACCEPTANCE)
    rows = projection["rows"]
    receipt = json.loads(json.dumps(projection["receipt"]))
    assert len(rows) == 153
    assert projection["master_sha256"] == receipt["master_sha256"] == (
        "2baf697d2b1a6630355d1ab037e40aaab24ff36fe83ecdc3b90a71a580f58c84"
    )
    assert receipt["source_division_binding"]["synthetic_sha256"] != receipt["master_sha256"]
    assert [number for number, row in enumerate(rows, 1) if "[4899]" in row["text"]] == [111]
    assert [item["disposition"] for item in receipt["source_division_binding"]["source_comments"]] == [
        "represented-as-xml-comment", "represented-as-xml-comment"
    ]
    assert verify_accepted_commentary(ROOT, acceptance_path=ACCEPTANCE, rows=rows, receipt=receipt) == []
    assert _scan(rows, "Augustine Psalms public rows") == []

    changed_rows = deepcopy(rows)
    changed_rows[110]["text"] = changed_rows[110]["text"].replace("[4899]", "[4900]")
    assert verify_accepted_commentary(
        ROOT, acceptance_path=ACCEPTANCE, rows=changed_rows, receipt=receipt
    )

    changed_receipt = deepcopy(receipt)
    changed_receipt["source_division_binding"]["source_comments"][0]["tail_text"] = "[4900]"
    assert verify_accepted_commentary(
        ROOT, acceptance_path=ACCEPTANCE, rows=rows, receipt=changed_receipt
    )

    changed_master = deepcopy(receipt)
    changed_master["master_sha256"] = receipt["source_division_binding"]["synthetic_sha256"]
    assert verify_accepted_commentary(
        ROOT, acceptance_path=ACCEPTANCE, rows=rows, receipt=changed_master
    )
