"""Source-specific readable and native checks for LIB-051's final three works."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree
import pytest

from build.tei.john_owen_lib050_oracle import _parse_source, _records, _verify_readable_transcription
from ocd_kernel.projection.categories.lib051_owen import NS, _native_view
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = Path(r"D:\Library\Open Christian Data\candidate-reviews\lib051-final-three-readable-candidates-20260927-v1")
PROFILE = ROOT / "sources/structured-text/lib051-john-owen/john-owen-lib051.reconstruction-profile.json"
WORK_IDS = ("john-owen-glory", "john-owen-justification", "john-owen-pneumatologia")
ACCEPTED_WORK = "john-owen-grotius"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _inputs(work_id: str):
    row = next(item for item in json.loads(PROFILE.read_bytes())["works"] if item["work_id"] == work_id)
    source_raw = (ROOT / row["path"]).read_bytes()
    assert sha256(source_raw).hexdigest() == row["sha256"]
    source = _parse_source(source_raw)
    records = _records(source, row["member_id"])
    original_path = CANDIDATES / work_id / "candidate.tei.xml"
    master = etree.fromstring(original_path.read_bytes())
    body = master.find(NS + "text/" + NS + "body")
    assert body is not None and len(body) == 1
    return row, source, records, original_path, master, body


def test_accepted_projection_aliases_private_annotations_before_public_scan() -> None:
    work_root = ROOT / "library/works" / ACCEPTED_WORK
    acceptance = next(work_root.rglob("acceptance.json"))
    projection = project_accepted_prose(ROOT, acceptance_path=acceptance)
    assert _scan(projection["rows"], "LIB-051 Owen regression") == []
    assert verify_accepted_prose(ROOT, acceptance_path=acceptance,
                                 rows=projection["rows"], receipt=projection["receipt"]) == []


@pytest.mark.parametrize("work_id", WORK_IDS)
def test_complete_readable_source_and_native_view(tmp_path: Path, work_id: str) -> None:
    row, source, records, original_path, master, body = _inputs(work_id)
    assert validate_file(original_path) == []
    _verify_readable_transcription(source, records, body, work_id)
    view = tmp_path / "native-view.xml"
    view.write_bytes(_native_view(master, body[0], row["title"]))
    assert validate_file(view) == []
    work = json.loads((ROOT / "library/works" / work_id / "work.json").read_bytes())
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    context = {
        "identity": {"work_id": work_id, "textual_form_id": form["textual_form_id"],
                     "edition_id": edition["edition_id"]},
        "language": "en", "representation_revision": "lib051-final-three-fixture-v1",
        "edition_title": row["title"], "category": "prose", "_allow_acceptance_metadata": True,
    }
    projection = project_document(view, **context)
    assert len(projection["rows"]) == 1
    assert projection["receipt"]["unsupported"] == []
    assert verify_document(view, projection["rows"], projection["receipt"], **context) == []


def test_glory_heading_and_blockquote_mutations_are_rejected() -> None:
    _, source, records, _, master, body = _inputs("john-owen-glory")
    assert len([node for node in source.getroot().iter("h4")]) == 6
    assert len([node for node in source.getroot().iter("blockquote")]) == 1
    headings = [node for node in body.iter(NS + "ab") if node.get("subtype") == "h4"]
    quotes = [node for node in body.iter(NS + "quote") if node.get("type") == "source-blockquote"]
    assert len(headings) == 6 and len(quotes) == 1
    headings[0].set("subtype", "h3")
    with pytest.raises(ValueError, match="attribute mapping drift"):
        _verify_readable_transcription(source, records, body, "john-owen-glory")
    headings[0].set("subtype", "h4")
    quotes[0].attrib.pop("type")
    with pytest.raises(ValueError, match="attribute mapping drift"):
        _verify_readable_transcription(source, records, body, "john-owen-glory")


def test_justification_literal_passages_have_no_invented_targets() -> None:
    _, source, records, _, master, body = _inputs("john-owen-justification")
    literal = ("Ps. xxii. 8, [margin,] xxxvii. 5", "Chap. iii. [iv. v. x.")
    source_refs = [node for node in source.getroot().iter("scripRef") if node.get("passage") in literal]
    assert len(source_refs) == 2 and all(node.get("osisRef") is None for node in source_refs)
    refs = [node for node in body.iter(NS + "ref") if node.get("n") in literal]
    assert len(refs) == 2 and {node.get("n") for node in refs} == set(literal)
    assert all(node.get("target") is None for node in refs)
    refs[0].set("target", "urn:osis:invented")
    with pytest.raises(ValueError, match="attribute mapping drift"):
        _verify_readable_transcription(source, records, body, "john-owen-justification")
    refs[0].attrib.pop("target")
    refs[0].set("n", "edited passage")
    with pytest.raises(ValueError, match="attribute mapping drift"):
        _verify_readable_transcription(source, records, body, "john-owen-justification")


def test_pneumatologia_foreign_language_and_private_annotations_are_bound() -> None:
    row, source, records, original_path, master, body = _inputs("john-owen-pneumatologia")
    source_foreign = list(source.getroot().iter("foreign"))
    master_foreign = list(body.iter(NS + "foreign"))
    assert len(source_foreign) == len(master_foreign) == 419
    assert all(node.get("lang") == "LA" for node in source_foreign)
    assert all(node.get(XML_LANG) == "LA" and node.get("ana") for node in master_foreign)
    original_digest = sha256(original_path.read_bytes()).hexdigest()
    view = etree.fromstring(_native_view(master, body[0], row["title"]))
    view_foreign = list(view.iter(NS + "foreign"))
    assert len(view_foreign) == 419
    assert all(node.get("ana") is None and node.get(XML_LANG) == "LA" for node in view_foreign)
    assert sha256(original_path.read_bytes()).hexdigest() == original_digest
    master_foreign[0].set(XML_LANG, "en")
    with pytest.raises(ValueError, match="attribute mapping drift"):
        _verify_readable_transcription(source, records, body, "john-owen-pneumatologia")
