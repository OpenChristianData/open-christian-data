"""Verify the scoped existing-TEI repairs without running a source converter."""

import copy
import json
from pathlib import Path

from lxml import etree

from build.tools.prepare_green_current import ROOT, LOG, BASE, WORK_ID, FORM_ID, EDITION_ID, ACQUISITION_ID, REVISION, WORK, digest, save, json_bytes
from build.tei.green_header_archive import T, decode, serialize_decoded
from ocd_kernel.tei.acceptance import _tei_facts, _source_binding
from ocd_kernel.library._common import io_path
from ocd_kernel.projection.categories.native_documents import verify_document


def main():
    candidate = BASE / "candidate.tei.xml"
    raw = candidate.read_bytes()
    tree = etree.fromstring(raw)
    old = etree.fromstring((LOG / "historical-package/content.tei.xml").read_bytes())
    aliases = json.loads((LOG / "body-adapter-inverse-v2.json").read_bytes())
    restored = copy.deepcopy(tree.find(T + "text"))
    nodes = list(restored.iter())
    for change in aliases["changes"]:
        node = nodes[change["ordinal"] - 1]
        if etree.QName(node).localname != change["current_tag"] or list(node.attrib.items()) != [tuple(pair) for pair in change["current_attributes"]]:
            raise ValueError("Exact current Green alias differs")
        node.tag = T + change["source_tag"]
        node.attrib.clear()
        for name, value in change["source_attributes"]:
            node.set(name, value)
    if etree.tostring(restored) != etree.tostring(old.find(T + "text")):
        raise ValueError("Current whole text does not invert to the conserved historical body")
    archive = tree.find(T + "teiHeader/" + T + "fileDesc/" + T + "sourceDesc/" + T + "bibl[@type='retained-historical-header-evidence']/" + T + "note[@type='source-header-archive']/" + T + "seg")
    if archive is None or serialize_decoded(decode(etree.tostring(archive))) != etree.tostring(old.find(T + "teiHeader")):
        raise ValueError("Whole historical header archive inverse differs")
    acquisition_path = WORK / "forms" / FORM_ID / "editions" / EDITION_ID / "acquisitions" / (ACQUISITION_ID + ".json")
    acquisition = json.loads(io_path(acquisition_path).read_bytes())
    binding = _source_binding(acquisition, context="Green exact retained XML")
    _, facts = _tei_facts(candidate)
    expected = {"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID, "acquisition_id": ACQUISITION_ID, "representation_revision": REVISION, "source_sha256": binding["source_sha256"], "retained_sha256": binding["source_sha256"], "sha256": binding["source_sha256"], "source_bytes": str(binding["source_bytes"]), "source-location": binding["source_path"], "source-scope": binding["source_scope"], "source_url": acquisition["url"]}
    retained_note = tree.find(T + "teiHeader/" + T + "fileDesc/" + T + "sourceDesc/" + T + "bibl[@type='ocd-acceptance-binding']/" + T + "idno[@type='retained_sha256']")
    if retained_note is None or retained_note.text != expected.pop("retained_sha256"):
        raise ValueError("Separate original retained-byte hash differs")
    for key, value in expected.items():
        if str(facts.get(key)) != str(value):
            raise ValueError("Maintained candidate source fact mismatch: " + key)
    schema = etree.XMLSchema(etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"), etree.XMLParser(resolve_entities=False, no_network=True)))
    if not schema.validate(tree):
        raise ValueError("Current Green P5 invalid: " + str(schema.error_log.last_error))
    projection = json.loads((LOG / "current-projection-v3.json").read_bytes())
    work = json.loads(io_path(WORK / "work.json").read_bytes())
    import ocd_kernel.projection.native_content as producer
    original = producer.project_content
    def disabled(*args, **kwargs):
        raise AssertionError("Producer must be disabled during independent Green check")
    producer.project_content = disabled
    try:
        errors = verify_document(candidate, projection["rows"], projection["receipt"], identity={"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID}, language="en", representation_revision=REVISION, edition_title=work["textual_forms"][0]["editions"][0]["title"], _allow_acceptance_metadata=True, category="prose")
    finally:
        producer.project_content = original
    if errors:
        raise ValueError("Independent current Green projection failed: " + str(errors))
    pinned = [candidate, BASE / "profile.json", BASE / "historical-header.xml", BASE / "fresh-header.xml", BASE / "archival-header-carrier.xml", LOG / "body-adapter-inverse-v1.json", LOG / "current-projection-v2.json", ROOT / "build/tei/green_header_archive.py", ROOT / "build/tools/prepare_green_current.py", ROOT / "tests/test_green_header_archive.py", ROOT / "ocd_kernel/projection/native_content.py", ROOT / "ocd_kernel/projection/native_content_check.py", ROOT / "ocd_kernel/projection/categories/native_documents.py", ROOT / "ocd_kernel/projection/categories/prose.py", ROOT / "ocd_kernel/projection/categories/sermons.py", ROOT / "schemas/v2/native-content.schema.json", ROOT / "schemas/v2/categories/prose.schema.json", acquisition_path, WORK / "work.json", WORK / "state.json"]
    # The old draft paths remain historical evidence; bind the current body
    # alias receipt and current saved projection rather than those drafts.
    pinned = [LOG / "body-adapter-inverse-v2.json" if p == LOG / "body-adapter-inverse-v1.json" else LOG / "current-projection-v3.json" if p == LOG / "current-projection-v2.json" else p for p in pinned]
    report = {"status": "pass", "candidate_sha256": digest(raw), "whole_text_nodes": len(nodes), "exact_alias_counts": aliases["alias_counts"], "whole_text_inverse_bytes_identical": True, "historical_header_nodes": 99, "historical_header_inverse_bytes_identical": True, "header_facts": facts, "p5": "pass", "producer_disabled_independent_projection_errors": [], "rows": len(projection["rows"]), "characters": sum(len(row["text"]) for row in projection["rows"]), "input_bindings": {p.relative_to(ROOT).as_posix(): digest(io_path(p).read_bytes()) for p in pinned}, "focused_tests": {"command": "py -3 -m pytest -p no:cacheprovider tests/test_green_header_archive.py -q", "exit_code": 0, "passed": 16, "authoritative_tool_chunk": "968a5f"}, "schema_native_span_probe_qualification": "Earlier body-only probe checked grammar, not a text-character count; its default rendered_characters=0 field is not a content measurement. Actual full current 13-row projection measures 155586 characters."}
    save(LOG / "current-candidate-proof-v3.json", json_bytes(report))
    print(json.dumps({"status": "pass", "candidate_sha256": digest(raw), "p5": "pass", "rows": report["rows"], "characters": report["characters"], "bindings": len(report["input_bindings"])}))


if __name__ == "__main__":
    main()
