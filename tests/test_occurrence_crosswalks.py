"""WU-07/WU-15 additive sidecars preserve occurrences without ID migration."""
import copy
import json
from pathlib import Path

import pytest

from build.tei.hymnary_crosswalk import build_crosswalk, inventory, verify_crosswalk
from ocd_kernel.release.packaging_crosswalk import build_packaging_crosswalk, read_repackaged_rows
from ocd_kernel.projection.envelope import canonical_row_bytes, project_document
from ocd_kernel.projection.receipt import build_correspondence_receipt
from ocd_kernel.release.verify import verify_document


HEADER = b"title,text,contributor,birth,death,year,language,context\n"
A = b"Same,Identical text,Author,1800,1900,1850,en,Hymnal A\n"
B = b"Same,Identical text,Author,1800,1900,1850,en,Hymnal B\n"


def test_hymnary_reorder_preserves_context_and_all_equal_text_occurrences():
    old, new = HEADER + A + B, HEADER + B + A
    crosswalk = build_crosswalk(old, new)
    assert crosswalk == build_crosswalk(old, new)
    assert len(crosswalk["old"]["occurrences"]) == 2
    assert crosswalk["mappings"][0]["new_source_key"] == crosswalk["new"]["occurrences"][1]["source_key"]
    assert crosswalk["composition_identity"] is None
    verify_crosswalk(old, new, crosswalk)
    wrong = copy.deepcopy(crosswalk)
    wrong["mappings"][0]["new_source_key"] = wrong["new"]["occurrences"][0]["source_key"]
    with pytest.raises(ValueError, match="correspondence"):
        verify_crosswalk(old, new, wrong)


def test_identical_rows_are_separate_and_ambiguous():
    crosswalk = build_crosswalk(HEADER + A + A, HEADER + A + A)
    assert len({row["source_key"] for row in crosswalk["old"]["occurrences"]}) == 2
    assert all(row["disposition"] == "unknown" and row["new_source_key"] is None
               and len(row["candidate_source_keys"]) == 2 for row in crosswalk["mappings"])


def test_missing_and_added_rows_remain_accounted_without_invented_matches():
    crosswalk = build_crosswalk(HEADER + A, HEADER + B)
    assert crosswalk["mappings"][0]["disposition"] == "unknown"
    assert crosswalk["mappings"][0]["candidate_source_keys"] == []
    assert len(crosswalk["new"]["occurrences"]) == 1
    with pytest.raises(ValueError):
        verify_crosswalk(HEADER + A, HEADER + A, crosswalk)


@pytest.mark.parametrize("source", [b"", HEADER + b"missing,fields\n"])
def test_invalid_source_fails_closed(source):
    with pytest.raises(ValueError):
        inventory(source)


def test_packaging_consumer_preserves_ids_and_equal_text_with_changed_line_locators():
    rows = [{"record_id": "edition:unit-000001", "text": "same", "sequence": 1},
            {"record_id": "edition:unit-000002", "text": "same", "sequence": 2}]
    old = ("\n".join(json.dumps(row) for row in rows) + "\n").encode()
    new = b"\n" + old.replace(b"\n", b"\r\n\r\n")
    crosswalk = build_packaging_crosswalk(old, new)
    assert read_repackaged_rows(old, new, crosswalk) == rows
    assert [row["new_line"] for row in crosswalk["occurrences"]] == [2, 4]
    for changed in (rows[::-1], rows[:1], rows + rows[:1]):
        content = "\n".join(json.dumps(row) for row in changed).encode()
        with pytest.raises(ValueError):
            build_packaging_crosswalk(old, content)
    crosswalk["occurrences"][0]["new_line"] = 4
    with pytest.raises(ValueError, match="mismatch"):
        read_repackaged_rows(old, new, crosswalk)


def test_projected_package_crosswalk_passes_independent_release_verifier():
    source = Path(__file__).parent / "fixtures/library-pipeline/correspondence/variation.tei.xml"
    context = {"identity": {"work_id": "work", "textual_form_id": "form", "edition_id": "edition"},
               "language": "en", "representation_revision": "wu07-sidecar-v1", "edition_title": "Fixture"}
    projection = project_document(source, **context)
    receipt = build_correspondence_receipt(projection, identity=context["identity"])
    old = canonical_row_bytes(projection["rows"])
    new = b"\n" + old.replace(b"\n", b"\r\n")
    sidecar = build_packaging_crosswalk(old, new)
    loaded = read_repackaged_rows(old, new, sidecar)
    assert verify_document(source, loaded, receipt, **context) == []
