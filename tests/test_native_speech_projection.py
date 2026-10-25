"""Source-faithful native dialogue in the N18328 candidate-only prose route."""

import copy
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import jsonschema

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.native_documents import verify_document
from ocd_kernel.projection.categories.prose import project_prose_document
from ocd_kernel.projection.native_content import SCHEMA, project_content, readable_content
from ocd_kernel.projection.native_content_check import verify_content


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "library/works/convicts-visitor/integration/convicts-n18328-electronic-v1/candidate.tei.xml"
CONTEXT = {
    "identity": {
        "work_id": "convicts-visitor",
        "textual_form_id": "convicts-visitor-tcp-retained",
        "edition_id": "convicts-visitor-tcp-electronic",
    },
    "language": "en",
    "representation_revision": "r1",
    "edition_title": "The Convicts Visitor",
    "_allow_acceptance_metadata": True,
}


def _nodes(node):
    yield node
    for child in node.get("content", []):
        yield from _nodes(child)


def _kind(rows, kind):
    return [node for row in rows for structure in row["structure"]
            for node in _nodes(structure) if node["kind"] == kind]


def test_exact_candidate_dialogue_verse_and_markers_correspond():
    assert hashlib.sha256(CANDIDATE.read_bytes()).hexdigest() == (
        "0d5bc4e091da8b10b26b815a420718ef082d51a3f41c25cde7d8d6b53b26eeef"
    )
    projection = project_prose_document(CANDIDATE, **CONTEXT)
    rows = projection["rows"]
    assert len(rows) == 3
    assert len(_kind(rows, "speech")) == len(_kind(rows, "speaker")) == 115
    assert len(_kind(rows, "verse-group")) == 7
    assert len(_kind(rows, "verse-line")) == 28
    assert len(_kind(rows, "page-break")) == 89
    assert len(_kind(rows, "note")) == 1
    speeches = _kind(rows, "speech")
    assert [node["kind"] for node in speeches[0]["content"] if node["kind"] != "text"] == ["speaker", "paragraph"]
    assert [node["kind"] for node in speeches[1]["content"] if node["kind"] != "text"] == ["speaker", "paragraph"]
    assert sum([node["kind"] for node in speech["content"] if node["kind"] != "text"][0] == "page-break"
               for speech in speeches) == 5
    assert verify_document(CANDIDATE, rows, projection["receipt"], category="prose", **CONTEXT) == []


@pytest.mark.parametrize("mutation", ["speaker-label", "speaker-order", "verse-line", "note", "page-break"])
def test_independent_candidate_check_rejects_structure_mutations(mutation):
    projection = project_prose_document(CANDIDATE, **CONTEXT)
    rows = copy.deepcopy(projection["rows"])
    if mutation == "speaker-label":
        _kind(rows, "speaker")[0]["content"][0]["text"] = "Invented speaker"
    elif mutation == "speaker-order":
        speech = _kind(rows, "speech")[0]
        speaker = next(node for node in speech["content"] if node["kind"] == "speaker")
        paragraph = next(node for node in speech["content"] if node["kind"] == "paragraph")
        speaker_index = speech["content"].index(speaker)
        paragraph_index = speech["content"].index(paragraph)
        speech["content"][speaker_index], speech["content"][paragraph_index] = paragraph, speaker
    elif mutation == "verse-line":
        group = _kind(rows, "verse-group")[0]
        group["content"].remove(next(node for node in group["content"] if node["kind"] == "verse-line"))
    elif mutation == "note":
        for parent in _kind(rows, "paragraph"):
            notes = [node for node in parent["content"] if node["kind"] == "note"]
            if notes:
                parent["content"].remove(notes[0])
                break
        else:
            pytest.fail("candidate note was not found")
    else:
        speech = next(node for node in _kind(rows, "speech")
                      if any(child["kind"] == "page-break" for child in node["content"]))
        speech["content"].remove(next(node for node in speech["content"] if node["kind"] == "page-break"))
    receipt = copy.deepcopy(projection["receipt"])
    receipt["output_sha256"] = hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    errors = verify_document(CANDIDATE, rows, receipt, category="prose", **CONTEXT)
    assert "native sermon rows differ from independent source observations" in errors


@pytest.mark.parametrize("xml", [
    "<sp><p>Words</p></sp>",
    "<sp><speaker>First</speaker><speaker>Second</speaker><p>Words</p></sp>",
    "<sp><p>Words</p><speaker>Late</speaker></sp>",
    "<sp><speaker> </speaker><p>Words</p></sp>",
    "<sp><speaker>First</speaker></sp>",
    "<speaker>Orphan</speaker>",
])
def test_ambiguous_speech_shape_fails_in_producer_and_independent_checker(xml):
    fragment = ('<div xmlns="http://www.tei-c.org/ns/1.0">' + xml + '</div>').encode()
    with pytest.raises(PipelineError):
        project_content(ET.fromstring(fragment))
    assert verify_content(fragment, {}, "")


def test_speech_with_preceding_page_marker_and_verse_is_preserved():
    fragment = (b'<div xmlns="http://www.tei-c.org/ns/1.0"><sp><pb n="12"/>'
                b'<speaker>Minister.</speaker><lg n="2"><l>First</l><l>Second</l></lg>'
                b'</sp></div>')
    content = project_content(ET.fromstring(fragment))
    speech = next(node for node in content["content"] if node["kind"] == "speech")
    assert [node["kind"] for node in speech["content"]] == ["page-break", "speaker", "verse-group"]
    assert speech["content"][2]["attributes"] == {"number": "2"}
    readable = readable_content(content)
    assert "Minister." in readable and "First\nSecond" in readable
    assert verify_content(fragment, content, readable) == []


def test_public_schema_requires_one_speaker_in_each_speech():
    fragment = (b'<sp xmlns="http://www.tei-c.org/ns/1.0">'
                b'<speaker>Minister.</speaker><p>Words.</p></sp>')
    speech = project_content(ET.fromstring(fragment))
    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    assert validator.is_valid(speech)
    no_speaker = copy.deepcopy(speech)
    no_speaker["content"].pop(0)
    assert not validator.is_valid(no_speaker)
    two_speakers = copy.deepcopy(speech)
    two_speakers["content"].insert(1, copy.deepcopy(two_speakers["content"][0]))
    assert not validator.is_valid(two_speakers)


def test_speech_alone_selects_native_prose_route(tmp_path):
    path = tmp_path / "dialogue.tei.xml"
    path.write_text(
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc>'
        '<titleStmt><title>Dialogue</title></titleStmt><publicationStmt><p>Test</p></publicationStmt>'
        '<sourceDesc><p>Test</p></sourceDesc></fileDesc></teiHeader><text><body>'
        '<div><sp><speaker>Minister.</speaker><p>Words.</p></sp></div>'
        '</body></text></TEI>',
        encoding="utf-8",
    )
    context = {**CONTEXT, "_allow_acceptance_metadata": False}
    projection = project_prose_document(path, **context)
    assert len(_kind(projection["rows"], "speech")) == 1
    assert verify_document(path, projection["rows"], projection["receipt"], category="prose", **context) == []
