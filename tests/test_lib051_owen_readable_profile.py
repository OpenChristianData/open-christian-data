"""Source-bound native view checks for six readable LIB-051 Owen witnesses."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import unquote

from lxml import etree
import pytest

from build.tei.john_owen_lib050_oracle import _parse_source, _records, _verify_readable_transcription
from ocd_kernel.projection.categories.lib051_owen import NS, WORKS, _native_view
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = Path(r"D:\Library\Open Christian Data\candidate-reviews\lib051-seven-readable-candidates-20260927-v1")
PROFILE = ROOT / "sources/structured-text/lib051-john-owen/john-owen-lib051.reconstruction-profile.json"


def _inputs(work_id: str):
    row = next(item for item in json.loads(PROFILE.read_bytes())["works"] if item["work_id"] == work_id)
    raw = (ROOT / row["path"]).read_bytes()
    candidate_path = CANDIDATES / work_id / "candidate.tei.xml"
    original = candidate_path.read_bytes()
    master = etree.fromstring(original)
    body = master.find(NS + "text/" + NS + "body")
    assert body is not None and len(body) == 1
    source = _parse_source(raw)
    records = _records(source, row["member_id"])
    return row, original, master, body, source, records


@pytest.mark.parametrize("work_id", sorted(WORKS))
def test_native_view_has_one_verified_row_and_keeps_source_oracle(tmp_path: Path, work_id: str) -> None:
    row, original, master, body, source, records = _inputs(work_id)
    _verify_readable_transcription(source, records, body, work_id)
    view = _native_view(master, body[0], row["title"])
    path = tmp_path / "native-view.tei.xml"
    path.write_bytes(view)
    assert validate_file(path) == []
    work = json.loads((ROOT / "library/works" / work_id / "work.json").read_bytes())
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    context = {
        "identity": {"work_id": work_id, "textual_form_id": form["textual_form_id"],
                     "edition_id": edition["edition_id"]},
        "language": "en", "representation_revision": "lib051-readable-profile-fixture-v1",
        "edition_title": row["title"], "category": "prose", "_allow_acceptance_metadata": True,
    }
    projection = project_document(path, **context)
    assert len(projection["rows"]) == 1
    assert projection["receipt"]["unsupported"] == []
    assert verify_document(path, projection["rows"], projection["receipt"], **context) == []
    assert sha256((CANDIDATES / work_id / "candidate.tei.xml").read_bytes()).digest() == sha256(original).digest()


def test_psalm130_note_attributes_are_reversible_view_only_and_oracle_rejects_mutation() -> None:
    work_id = "john-owen-psalm130"
    row, original, master, body, source, records = _inputs(work_id)
    original_digest = sha256(original).hexdigest()
    view = etree.fromstring(_native_view(master, body[0], row["title"]))
    original_notes = [node for node in master.iter(NS + "note") if "subtype" in node.attrib or "target" in node.attrib]
    normalized_notes = [node for node in view.iter(NS + "note") if "urn:ocd:tei-note-" in (node.get("ana") or "")]
    assert original_notes and len(original_notes) == len(normalized_notes)
    for original_note, normalized_note in zip(original_notes, normalized_notes, strict=True):
        for name in ("subtype", "target"):
            value = original_note.get(name)
            if value is not None:
                assert normalized_note.get(name) is None
                tokens = (normalized_note.get("ana") or "").split()
                encoded = next(token.partition(f"urn:ocd:tei-note-{name}:")[2]
                               for token in tokens if token.startswith(f"urn:ocd:tei-note-{name}:"))
                assert unquote(encoded) == value
    assert sha256((CANDIDATES / work_id / "candidate.tei.xml").read_bytes()).hexdigest() == original_digest
    mutated = etree.fromstring(original)
    note = next(node for node in mutated.iter(NS + "note") if "subtype" in node.attrib)
    note.set("subtype", "wrong-source-role")
    mutated_body = mutated.find(NS + "text/" + NS + "body")
    with pytest.raises(ValueError, match="drift"):
        _verify_readable_transcription(source, records, mutated_body, work_id)
