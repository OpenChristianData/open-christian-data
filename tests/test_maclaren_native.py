"""Exact accepted Maclaren fifteen-member source-line projection regression."""

from copy import deepcopy
import json
from pathlib import Path

from ocd_kernel.projection.categories.sermons import (
    project_accepted_sermons,
    verify_accepted_sermons,
)
from ocd_kernel.release.public_allowlist import _scan


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = Path(
    "library/works/maclaren-expositions/forms/"
    "maclaren-expositions-pg-retained-en/editions/"
    "maclaren-expositions-pg-fifteen-volume-cohort/acceptance.json"
)


def test_accepted_maclaren_source_members_and_lines() -> None:
    projected = project_accepted_sermons(ROOT, acceptance_path=ACCEPTANCE)
    rows = projected["rows"]
    receipt = json.loads(json.dumps(projected["receipt"]))
    binding = receipt["source_member_binding"]
    assert len(rows) == 1503
    assert receipt["master_sha256"] == (
        "50a0967ed3b0918a32d151bb18541805d381419e17c4435218e0d0e69bf5ff7f"
    )
    assert [row["locator"]["document"] for row in rows] == [
        unit["member"] for unit in binding["units"]
    ]
    assert set(row["locator"]["document"] for row in rows) == set(range(1, 16))
    assert sum(binding["source_line_counts"][key] for key in ("seg", "ab", "milestone")) == 339526
    assert binding["source_region_counts"]["book-section-heading"] == 43
    assert verify_accepted_sermons(ROOT, acceptance_path=ACCEPTANCE, rows=rows, receipt=receipt) == []
    assert _scan(rows, "Maclaren accepted public rows") == []

    changed = deepcopy(receipt)
    changed["source_member_binding"]["units"][0]["member_id"] = "member-forged"
    assert verify_accepted_sermons(ROOT, acceptance_path=ACCEPTANCE, rows=rows, receipt=changed)


def test_verification_copies_only_the_modified_locators(monkeypatch):
    from ocd_kernel.projection.categories import maclaren_native as route

    rows = [{"locator": {"document": 1}, "structure": {"content": ["unchanged"]}}]
    before = deepcopy(rows)
    binding = {"units": [{"member": 1}], "synthetic_sha256": route._sha(b"<TEI/>")}
    context = {"authority": {}, "identity": {}, "representation_revision": "1", "edition_title": "Sample"}
    receipt = {"scope": "accepted Maclaren fifteen-member source lines",
               "master_sha256": route.MASTER_SHA256, "authority": {},
               "source_member_binding": binding, "output_sha256": route._sha(route.native_documents._json(rows))}
    monkeypatch.setattr(route, "_synthetic", lambda context: (b"<TEI/>", binding))

    def observer(path, native_rows, native_receipt, **kwargs):
        assert path.read_bytes() == b"<TEI/>"
        assert native_rows[0] is not rows[0]
        assert native_rows[0]["locator"] is not rows[0]["locator"]
        assert native_rows[0]["locator"] == {}
        assert native_rows[0]["structure"] is rows[0]["structure"]
        return []

    monkeypatch.setattr(route.native_documents, "verify_document", observer)
    assert route.verify(context, rows, receipt) == []
    assert rows == before
    assert receipt["source_member_binding"] == binding
