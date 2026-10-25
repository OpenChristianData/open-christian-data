"""PIPE-011 source-bound BCP 1662 service-step projection checks."""

from __future__ import annotations

import copy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import sys

from lxml import etree as E
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.liturgies import (
    project_liturgies_document as project,
    verify_liturgies_document as verify,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/library-pipeline/categories/liturgies"
MANIFEST = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
PATH = FIXTURE / "master.tei.xml"
CONTEXT = MANIFEST["context"]
NS = {"t": "http://www.tei-c.org/ns/1.0"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def public_token(value: str) -> str:
    """Mirror the documented stable token boundary for source XML IDs."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


class VisibleHTML(HTMLParser):
    """Independent source text reader that restores image drop-cap ALT text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "img":
            alt = dict(attrs).get("alt")
            if alt:
                self.parts.append(alt)


class OpeningSentenceHTML(HTMLParser):
    """Independently recover the source opening sentences and citations."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_paragraph = False
        self.italic_depth = 0
        self.lines: list[list[tuple[str, bool]]] = []
        self.current: list[tuple[str, bool]] = []
        self.candidate_lines: list[list[tuple[str, bool]]] = []
        self.paragraph_text: list[str] = []

    def _finish_paragraph(self) -> None:
        if self.current:
            self.candidate_lines.append(self.current)
        visible = "".join(text for line in self.candidate_lines for text, _ in line)
        if " ".join(visible.split()).startswith("WHEN the wicked man turneth away"):
            self.lines = self.candidate_lines
        self.in_paragraph = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag == "p":
            if self.in_paragraph:
                self._finish_paragraph()
            self.in_paragraph = True
            self.current = []
            self.candidate_lines = []
            self.paragraph_text = []
        elif self.in_paragraph and tag == "br":
            self.candidate_lines.append(self.current)
            self.current = []
        elif self.in_paragraph and tag == "i":
            self.italic_depth += 1
        elif self.in_paragraph and tag == "img":
            alt = dict(attrs).get("alt")
            if alt:
                self.current.append((alt, self.italic_depth > 0))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "i" and self.in_paragraph:
            self.italic_depth = max(self.italic_depth - 1, 0)
        elif tag == "p" and self.in_paragraph:
            self._finish_paragraph()

    def handle_data(self, data: str) -> None:
        if self.in_paragraph:
            self.current.append((data, self.italic_depth > 0))


def source_opening_sentences(path: Path) -> list[dict[str, str]]:
    parser = OpeningSentenceHTML()
    parser.feed(path.read_bytes().decode("utf-8"))
    parser.close()
    if len(parser.lines) != 11:
        raise AssertionError(f"expected 11 opening source lines in {path}, got {len(parser.lines)}")
    result: list[dict[str, str]] = []
    for chunks in parser.lines:
        raw = "".join(text for text, _ in chunks)
        first_italic = next((sum(len(text) for text, _ in chunks[:index]) for index, (_, italic) in enumerate(chunks) if italic), len(raw))
        sentence, label = raw[:first_italic], raw[first_italic:]
        marker = re.search(r"\s+(\d+)\s*$", sentence)
        if marker and label:
            sentence = sentence[:marker.start()]
            label = marker.group(1) + " " + label
        result.append({"text": " ".join(sentence.replace("\ufffd", " ").split()), "label": " ".join(label.replace("\ufffd", " ").split())})
    return result


def source_visible(path: Path) -> str:
    parser = VisibleHTML()
    parser.feed(path.read_bytes().decode("utf-8"))
    parser.close()
    return " ".join("".join(parser.parts).split())


def norm(node: E._Element | None) -> str:
    return " ".join("".join(node.itertext() if node is not None else []).split())


def retained_units(service: E._Element) -> list[dict[str, object]]:
    """Flatten the retained witness while retaining branch membership/order."""
    units: list[dict[str, object]] = []

    def walk(parent: E._Element, branch_id: str | None = None) -> None:
        for child in parent:
            if child.tag == "branch":
                branch = {"id": child.get("id"), "kind": "branch", "text": child.get("label") or "", "branch_id": None}
                units.append(branch)
                walk(child, child.get("id"))
            elif child.tag == "step":
                item: dict[str, object] = {
                    "id": child.get("id"),
                    "kind": child.get("kind"),
                    "text": norm(child),
                    "branch_id": branch_id,
                }
                if child.get("speaker"):
                    item["speaker"] = child.get("speaker")
                if child.get("responseTo"):
                    item["response_to"] = child.get("responseTo")
                if child.get("sourceType"):
                    item["source_type"] = child.get("sourceType")
                if child.get("kind") == "alternative":
                    item["alternatives"] = [
                        {"label": alternative.get("label"), "text": norm(alternative)}
                        for alternative in child.findall("alternative")
                    ]
                    item["text"] = " | ".join(alternative["text"] for alternative in item["alternatives"])  # type: ignore[index]
                units.append(item)

    walk(service)
    return units


def canonical_rows(rows: list[dict[str, object]]) -> str:
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def forged_receipt(result: dict[str, object]) -> dict[str, object]:
    """Recompute only output-local hashes, leaving source evidence mismatched."""
    receipt = result["receipt"]  # type: ignore[assignment]
    rows = result["rows"]  # type: ignore[assignment]
    assert isinstance(receipt, dict) and isinstance(rows, list)
    receipt["row_count"] = len(rows)
    receipt["output_sha256"] = canonical_rows(rows)
    anchors = receipt.get("anchors")
    if isinstance(anchors, list):
        for row, anchor in zip(rows, anchors):
            if isinstance(row, dict) and isinstance(anchor, dict):
                anchor["record_id"] = row.get("record_id")
                anchor["text_sha256"] = hashlib.sha256(str(row.get("text", "")).encode("utf-8")).hexdigest()
    return receipt


def test_real_bcp_services_preserve_branches_roles_alternatives_and_responses() -> None:
    result = project(PATH, **CONTEXT)
    assert len(result["rows"]) == MANIFEST["counts"]["selected_steps"] == 43
    assert [row["service_id"] for row in result["rows"]].count(public_token("bcp1662-morning")) == 22
    assert [row["service_id"] for row in result["rows"]].count(public_token("bcp1662-evening")) == 21

    master = E.parse(str(PATH))
    for service in master.xpath("/t:TEI/t:text/t:body/t:div[@type='service']", namespaces=NS):
        assert [child.get("type") for child in service.xpath("./t:div", namespaces=NS)] == ["section", "branch", "section"]
        branch = service.xpath("./t:div[@type='branch']", namespaces=NS)[0]
        assert [E.QName(child).localname for child in branch] == ["head", "p"]
        assert "Then the Minister shall kneel" not in norm(branch)
        assert len(service.xpath(".//t:seg[@type='alternative']", namespaces=NS)) == 11

    retained = E.parse(str(FIXTURE / "retained.xml"))
    services = retained.xpath("/sourceExcerpt/service")
    assert len(services) == MANIFEST["source_unit_count"]
    expected_units = []
    for service in services:
        raw_service_id = service.get("id")
        assert raw_service_id
        for unit in retained_units(service):
            unit["service_id"] = raw_service_id
            expected_units.append(unit)
    assert [row["step_id"] for row in result["rows"]] == [public_token(str(unit["id"])) for unit in expected_units]
    for row, unit in zip(result["rows"], expected_units, strict=True):
        assert row["category"] == "liturgies"
        raw_service_id = str(unit["service_id"])
        raw_step_id = str(unit["id"])
        assert row["service_id"] == public_token(raw_service_id)
        assert row["record_id"] == f"{CONTEXT['identity']['edition_id']}:liturgy:{public_token(raw_service_id)}:{public_token(raw_step_id)}"
        assert row["step_id"] == public_token(raw_step_id)
        assert row["text"] == unit["text"]
        if unit.get("speaker"):
            assert row["speaker"] == unit["speaker"]
        if unit.get("response_to"):
            assert row["response_to"] == public_token(str(unit["response_to"]))
        if unit["kind"] == "alternative":
            assert row["step_kind"] == "alternative"
            assert row["alternatives"] == unit["alternatives"]
        elif unit["kind"] == "branch":
            assert row["step_kind"] == "branch"
            assert row["branch"] == {"id": public_token(raw_step_id), "label": unit["text"]}
        elif unit["kind"] == "rubric":
            assert row["step_kind"] == "rubric"
            assert row["rubric"]["text"] == unit["text"]
            assert row["rubric"]["source_type"] == "p@rend=rubric"
        else:
            assert row["step_kind"] == "speech"
        if unit.get("branch_id"):
            assert row["branch"] == {"id": public_token(str(unit["branch_id"])), "label": "If no priest be present"}

    assert {row["step_kind"] for row in result["rows"]} == {"speech", "rubric", "alternative", "branch"}
    assert [row["step_id"] for row in result["rows"] if row["step_kind"] == "branch"] == [
        public_token("bcp1662-morning-branch"), public_token("bcp1662-evening-branch")
    ]
    lord_prayer_ids = {public_token("bcp1662-morning-lord-prayer"), public_token("bcp1662-evening-lord-prayer")}
    branch_rubric_ids = {public_token("bcp1662-morning-branch-rubric"), public_token("bcp1662-evening-branch-rubric")}
    absolution_ids = {public_token("bcp1662-morning-absolution"), public_token("bcp1662-evening-absolution")}
    assert {row["speaker"] for row in result["rows"] if row["step_id"] in lord_prayer_ids} == {"Minister and people"}
    assert all(row["step_kind"] == "rubric" for row in result["rows"] if row["step_id"] in branch_rubric_ids)
    assert all(row["step_kind"] == "speech" for row in result["rows"] if row["step_id"] in absolution_ids)
    public_rows = json.dumps(result["rows"], ensure_ascii=False, sort_keys=True)
    for source_node in master.xpath("//*[@xml:id]", namespaces={"xml": "http://www.w3.org/XML/1998/namespace"}):
        source_id = source_node.get(XML_ID)
        assert source_id and source_id not in public_rows
    for row in result["rows"]:
        assert row["provenance"] == {"edition_title": CONTEXT["edition_title"]}
        assert row["locator"]["kind"] == "liturgy-step"
        assert row["locator"]["service"] in {1, 2}
    receipt = result["receipt"]
    assert receipt["source_binding"] == {
        "source_url": CONTEXT["source_url"],
        "source_sha256": CONTEXT["source_sha256"],
        "retained_sha256": CONTEXT["retained_sha256"],
    }
    assert receipt["master_sha256"] == hashlib.sha256(PATH.read_bytes()).hexdigest()
    assert receipt["row_count"] == len(result["rows"]) == len(receipt["anchors"])
    assert receipt["output_sha256"] == canonical_rows(result["rows"])
    assert receipt["unsupported"] == []
    assert receipt["independent_check"] == {"status": "pending"}
    assert receipt["inventory"] == result["inventory"]
    assert receipt["warnings"] == result["warnings"]
    assert receipt["exclusions"] == result["exclusions"]
    for row, anchor in zip(result["rows"], receipt["anchors"], strict=True):
        assert anchor["record_id"] == row["record_id"]
        assert anchor["step_id"] == row["step_id"]
        raw_step_id = str(next(unit["id"] for unit in expected_units if public_token(str(unit["id"])) == row["step_id"]))
        expected_unit = next(unit for unit in expected_units if public_token(str(unit["id"])) == row["step_id"])
        assert anchor["source_xml_id"] == raw_step_id
        assert anchor["source_service_xml_id"] == str(expected_unit["service_id"])
        expected_branch = expected_unit["id"] if expected_unit["kind"] == "branch" else expected_unit.get("branch_id")
        assert anchor["source_branch_xml_id"] == expected_branch
        assert anchor["source_order"] == row["sequence"] == row["sequence_in_service"]
        assert anchor["text_sha256"] == hashlib.sha256(row["text"].encode("utf-8")).hexdigest()
        assert anchor["text_length"] == len(row["text"])
        assert anchor["tei_path"].startswith("/TEI[1]/text[1]/body[1]/div")
    assert verify(PATH, result["rows"], receipt, **CONTEXT) == []


@pytest.mark.requires_local_artifacts
def test_bcp_pages_bind_every_selected_text_fragment_to_real_html() -> None:
    retained = E.parse(str(FIXTURE / "retained.xml"))
    source_services = {service.get("id"): service for service in retained.xpath("/sourceExcerpt/service")}
    manifest_services = {unit["id"]: unit for unit in MANIFEST["selected_units"]}
    for source_file in MANIFEST["source_files"]:
        path = ROOT / source_file["path"]
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == source_file["sha256"]
        service_id = "bcp1662-" + source_file["service"]
        service = source_services[service_id]
        manifest_unit = manifest_services[service_id]
        assert service.get("sourcePath") == source_file["path"]
        assert service.get("sourceSha256") == source_file["sha256"]
        assert manifest_unit["source_path"] == source_file["path"]
        visible = source_visible(path)
        folded = visible.casefold()
        units = retained_units(service)
        assert len(units) == manifest_unit["step_count"]
        assert [unit["id"] for unit in units] == manifest_unit["step_ids"]
        opening = next(unit for unit in units if unit["kind"] == "alternative")
        assert opening["alternatives"] == source_opening_sentences(path)
        offsets: list[int] = []
        for unit in units:
            text = str(unit["text"])
            alternatives = unit.get("alternatives", [])
            if alternatives:
                alternative_offsets = []
                for alternative in alternatives:
                    assert str(alternative["label"]).casefold() in folded
                    alternative_text = str(alternative["text"])
                    assert alternative_text.casefold() in folded, (service_id, unit["id"])
                    alternative_offsets.append(folded.find(alternative_text.casefold()))
                offsets.extend(alternative_offsets)
                continue
            assert text.casefold() in folded, (service_id, unit["id"])
            offsets.append(folded.find(text.casefold()))
            for alternative in alternatives:
                assert str(alternative["label"]).casefold() in folded
                assert str(alternative["text"]).casefold() in folded
        # Branch labels and their first rubric share a source span; all other
        # selected units must remain in source order.
        assert offsets == sorted(offsets), (service_id, offsets)
    assert all(note["text"] == "The sentence about the collect from Trinity 21 is new in the 1992 edition." for note in MANIFEST["source_notes"])
    assert E.parse(str(FIXTURE / "retained.xml")).getroot().get("sourceNote") == MANIFEST["source_notes"][0]["text"]


@pytest.mark.requires_local_artifacts
def test_fixture_builder_is_reproducible_and_manifest_hashes_are_bound(tmp_path: Path) -> None:
    builder = ROOT / "plans/2026-08-31-library-pipeline-redesign/artifacts/PIPE-011/build_fixture.py"
    first = tmp_path / "first"
    second = tmp_path / "second"
    for output in (first, second):
        subprocess.run([sys.executable, str(builder), "--output-dir", str(output)], check=True)
    for name in ("master.tei.xml", "retained.xml", "manifest.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
        assert (FIXTURE / name).read_bytes() == (first / name).read_bytes()
    for name, digest in MANIFEST["files"].items():
        assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == digest


def test_fixture_is_valid_tei_p5_and_schema_is_closed() -> None:
    E.XMLSchema(E.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))).assertValid(E.parse(str(PATH)))
    schema = json.loads((ROOT / "schemas/v2/categories/liturgies.schema.json").read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert "allOf" not in schema
    for property_name in ("work_id", "textual_form_id", "edition_id", "record_id", "sequence", "language", "text", "representation_revision", "provenance", "notes", "references"):
        assert schema["properties"][property_name]["$ref"].endswith(f"#/properties/{property_name}")


@pytest.mark.parametrize(
    "mutation",
    [
        "omit", "duplicate", "reverse", "text", "record_id", "sequence", "service", "service_title",
        "step_id", "step_kind", "sequence_in_service", "speaker", "response_to", "rubric", "branch",
        "alternatives", "locator", "provenance", "inventory", "warnings", "exclusions", "unsupported",
        "anchors", "master", "source", "retained", "policy", "common", "mapping", "assembler",
    ],
)
def test_source_mutations_fail_even_when_output_hashes_are_forged(mutation: str) -> None:
    result = copy.deepcopy(project(PATH, **CONTEXT))
    rows = result["rows"]
    assert isinstance(rows, list)
    speech = next(row for row in rows if row["step_kind"] == "speech")
    answer = next(row for row in rows if row.get("response_to"))
    rubric = next(row for row in rows if row["step_kind"] == "rubric")
    branch = next(row for row in rows if row["step_kind"] == "branch")
    alternative = next(row for row in rows if row["step_kind"] == "alternative")
    if mutation == "omit":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(copy.deepcopy(rows[-1]))
    elif mutation == "reverse":
        rows.reverse()
    elif mutation == "text":
        speech["text"] += " Invented words."
    elif mutation == "record_id":
        speech["record_id"] = "forged-record"
    elif mutation == "sequence":
        speech["sequence"] = 99
    elif mutation == "service":
        speech["service_id"] = "forged-service"
    elif mutation == "service_title":
        speech["service_title"] = "Forged service"
    elif mutation == "step_id":
        speech["step_id"] = "forged-step"
    elif mutation == "step_kind":
        speech["step_kind"] = "rubric"
    elif mutation == "sequence_in_service":
        speech["sequence_in_service"] = 99
    elif mutation == "speaker":
        speech["speaker"] = "Forged speaker"
    elif mutation == "response_to":
        answer["response_to"] = "forged-prompt"
    elif mutation == "rubric":
        rubric["rubric"]["text"] = "Forged rubric"
    elif mutation == "branch":
        branch["branch"]["label"] = "Forged branch"
    elif mutation == "alternatives":
        alternative["alternatives"][0]["text"] = "Forged alternative"
    elif mutation == "locator":
        speech["locator"]["step"] = 99
    elif mutation == "provenance":
        speech["provenance"]["edition_title"] = "Forged edition"
    elif mutation == "inventory":
        result["receipt"]["inventory"].pop()
    elif mutation == "warnings":
        result["receipt"]["warnings"] = [{"tei_path": "/invented", "reason": "invented"}]
    elif mutation == "exclusions":
        result["receipt"]["exclusions"] = []
    elif mutation == "unsupported":
        result["receipt"]["unsupported"] = ["invented unsupported structure"]
    elif mutation == "anchors":
        result["receipt"]["anchors"].pop()
    elif mutation == "master":
        result["receipt"]["master_sha256"] = "0" * 64
    elif mutation == "source":
        result["receipt"]["source_binding"]["source_sha256"] = "0" * 64
    elif mutation == "retained":
        result["receipt"]["source_binding"]["retained_sha256"] = "0" * 64
    elif mutation == "policy":
        result["receipt"]["policy_sha256"] = "0" * 64
    elif mutation == "common":
        result["receipt"]["common_schema_sha256"] = "0" * 64
    elif mutation == "mapping":
        result["receipt"]["mapping_version"] = "forged-mapping"
    elif mutation == "assembler":
        result["receipt"]["assembler_version"] = "forged-assembler"
    assert verify(PATH, rows, forged_receipt(result), **CONTEXT)


@pytest.mark.parametrize("change", ["table", "attribute", "loose", "tail", "duplicate-id", "namespace", "doctype", "prolog-pi", "epilog-pi", "utf16-pi", "branch-order"])
def test_unsupported_source_structure_fails_both_routes(change: str, tmp_path: Path) -> None:
    tree = E.parse(str(PATH))
    services = tree.xpath("//t:body/t:div", namespaces=NS)
    service = services[0]
    if change == "table":
        E.SubElement(service, "{" + NS["t"] + "}table")
    elif change == "attribute":
        service.set("ana", "invented")
    elif change == "loose":
        service.text = "Unmapped visible words"
    elif change == "tail":
        service[0].tail = "Unmapped visible tail"
    elif change == "duplicate-id":
        services[1].set(XML_ID, services[0].get(XML_ID))
    elif change == "namespace":
        service.tag = "{urn:wrong}div"
    elif change == "branch-order":
        branch = service.xpath("./t:div[@type='branch']", namespaces=NS)[0]
        branch.set("n", "0")
    raw = E.tostring(tree, encoding="utf-8")
    if change == "doctype":
        raw = b'<!DOCTYPE TEI [<!ENTITY x "danger">]>' + raw
    elif change == "prolog-pi":
        raw = b'<?xml-stylesheet hidden?>' + raw
    elif change == "epilog-pi":
        raw += b'<?hidden test?>'
    elif change == "utf16-pi":
        raw = ('<?xml version="1.0" encoding="utf-16"?><?hidden test?>' + raw.decode("utf-8")).encode("utf-16")
    bad = tmp_path / "bad-liturgies.xml"
    bad.write_bytes(raw)
    with pytest.raises(PipelineError):
        project(bad, **CONTEXT)
    original = project(PATH, **CONTEXT)
    assert verify(bad, original["rows"], original["receipt"], **CONTEXT)


def test_checker_has_no_producer_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    result = project(PATH, **CONTEXT)
    import ocd_kernel.projection.categories.liturgies as module

    monkeypatch.setattr(module, "project_liturgies_document", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("producer called")))
    assert verify(PATH, result["rows"], result["receipt"], **CONTEXT) == []


def test_forged_independent_status_is_rejected() -> None:
    result = project(PATH, **CONTEXT)
    forged = copy.deepcopy(result["receipt"])
    forged["independent_check"] = {"status": "passed"}
    assert verify(PATH, result["rows"], forged, **CONTEXT)

@pytest.mark.parametrize('target_kind', ['missing', 'service', 'heading'])
def test_source_response_must_resolve_to_a_projected_step(target_kind, tmp_path):
    tree = E.parse(str(PATH))
    speech = tree.xpath('//t:sp[@corresp]', namespaces=NS)[0]
    if target_kind == 'missing':
        target = 'absent-source-step'
    elif target_kind == 'service':
        target = tree.xpath('//t:div[@type="service"]', namespaces=NS)[0].get(XML_ID)
    else:
        # A real source heading exists but is deliberately not a spoken step.
        heading = tree.xpath('//t:text//t:head', namespaces=NS)[0]
        heading.set(XML_ID, 'nonstep-source-heading')
        target = heading.get(XML_ID)
    speech.set('corresp', '#' + target)
    bad = tmp_path / 'nonstep-response.xml'
    bad.write_bytes(E.tostring(tree))
    with pytest.raises(PipelineError, match='response target does not resolve'):
        project(bad, **CONTEXT)
    errors = verify(bad, [], {}, **CONTEXT)
    assert any('response target does not resolve' in error for error in errors), errors
