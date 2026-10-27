"""PIPE-010 hymn occurrence projection and independent source checks."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

from lxml import etree as E
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.hymns import (
    project_hymns_document as project,
    verify_hymns_document as verify,
)
from build.lib.tei_xsd import compiled_tei_schema

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/library-pipeline/categories/hymns"
MANIFEST = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
PATH = FIXTURE / "master.tei.xml"
CONTEXT = {**MANIFEST["context"], "retained_path": FIXTURE / "retained.xml"}


def norm(node: E._Element) -> str:
    return " ".join("".join(node.xpath(".//text()") if node is not None else []).split())


def source_segments(node: E._Element) -> list[dict]:
    result = []
    for segment in node.findall("segment"):
        lines = [norm(line) for line in segment.findall("line")]
        if segment.get("kind") == "stanza":
            result.append({"kind": "stanza", "number": int(segment.get("number")), "lines": lines})
        elif segment.get("kind") == "refrain-marker":
            result.append({"kind": "refrain-marker", "label": segment.get("label")})
        else:
            result.append({"kind": "refrain", "label": segment.get("label"), "lines": lines})
    return result


def retained_source_rows() -> list[dict[str, str]]:
    archive = ROOT / MANIFEST["source_path"]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == MANIFEST["source_sha256"]
    with zipfile.ZipFile(archive) as bundle:
        payload = bundle.read(MANIFEST["source_member"])
    assert hashlib.sha256(payload).hexdigest() == MANIFEST["payload_sha256"]
    csv.field_size_limit(len(payload) + 1)
    reader = csv.DictReader(io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8-sig", newline=""), strict=True)
    selected = [next(reader) for _ in range(MANIFEST["source_unit_count"])]
    complete_count = MANIFEST["source_unit_count"]
    try:
        for _ in reader:
            complete_count += 1
    except csv.Error as exc:
        assert complete_count == MANIFEST["complete_prefix_count"]
        assert reader.line_num == MANIFEST["malformed_line"]
        assert str(exc) == MANIFEST["malformed_error"]
    else:
        raise AssertionError("strict source reader unexpectedly accepted malformed Hymnary tail")
    return selected


def projected_source_lines(full_text: str) -> list[str]:
    lines = []
    for raw_line in full_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line or line == "Refrain:":
            continue
        line = line.removesuffix(" [Refrain]")
        line = re.sub(r"^\d+\s+", "", line)
        lines.append(line)
    return lines


def derived_source_text_id(title: str, contributor: str, text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    basis = f"{' '.join(title.split()).casefold()}\n{' '.join(contributor.split()).casefold()}\n{text}".encode("utf-8")
    return f"text-{slug}-{hashlib.sha256(basis).hexdigest()[:16]}"


def forged_receipt(result: dict) -> dict:
    """Make output internally plausible while leaving source evidence untouched."""
    receipt = result["receipt"]
    rows = result["rows"]
    receipt["row_count"] = len(rows)
    receipt["output_sha256"] = hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    for row, anchor in zip(rows, receipt["anchors"]):
        anchor["record_id"] = row["record_id"]
        anchor["text_sha256"] = hashlib.sha256(row["text"].encode()).hexdigest()
    return receipt


def test_real_hymnary_rows_keep_occurrence_text_identity_and_refrain_order():
    result = project(PATH, **CONTEXT)
    for name, digest in MANIFEST["files"].items():
        assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == digest
    source = E.parse(str(FIXTURE / "retained.xml"))
    occurrences = source.xpath("/sourceExcerpt/occurrence")
    assert len(result["rows"]) == len(occurrences) == MANIFEST["source_unit_count"]
    assert [row["occurrence_id"] for row in result["rows"]] == [hashlib.sha256(node.get("id").encode()).hexdigest()[:20] for node in occurrences]
    for row, node in zip(result["rows"], occurrences):
        segments = source_segments(node)
        assert row["hymn_text_id"] == node.get("textId")
        assert row["segments"] == segments
        assert row["stanzas"] == [{key: value for key, value in segment.items() if key != "kind"} for segment in segments if segment["kind"] == "stanza"]
        expected_refrain = next((
            {key: value for key, value in segment.items() if key != "kind"}
            for segment in segments if segment["kind"] == "refrain"
        ), None)
        assert row.get("refrain") == expected_refrain
        assert row["text"] == "\n".join(line for segment in segments if "lines" in segment for line in segment["lines"])
        assert row["first_line"] == segments[0]["lines"][0]
        assert row["title"] == node.get("title")
        assert row["contributor"] == node.get("author")
        for row_key, node_key in (("author_birth", "authorBirth"), ("author_death", "authorDeath"), ("year_written", "yearWritten")):
            if node.get(node_key) and node.get(node_key).strip("; "):
                assert row[row_key] == node.get(node_key)
            else:
                assert row_key not in row
        assert row["hymnal_setting"] == {"title": node.get("hymnal"), "edition": node.get("edition")}
        assert "tune" not in row
        assert "rights" not in row
    assert len({row["hymn_text_id"] for row in result["rows"]}) == 3
    assert result["rows"][0]["title"] != result["rows"][0]["first_line"]
    assert result["rows"][2]["title"] != result["rows"][2]["first_line"]
    assert result["receipt"]["source_binding"] == {
        "source_url": CONTEXT["source_url"],
        "source_sha256": CONTEXT["source_sha256"],
        "retained_sha256": CONTEXT["retained_sha256"],
    }
    assert result["receipt"]["master_sha256"] == hashlib.sha256(PATH.read_bytes()).hexdigest()
    assert verify(PATH, result["rows"], result["receipt"], **CONTEXT) == []


@pytest.mark.requires_local_artifacts
def test_selected_rows_bind_the_retained_witness_to_the_real_hymnary_payload():
    rows = retained_source_rows()
    retained = E.parse(str(FIXTURE / "retained.xml"))
    occurrences = retained.xpath("/sourceExcerpt/occurrence")
    assert MANIFEST["source_row_ordinals"] == [int(node.get("sourceOrdinal")) for node in occurrences]
    assert MANIFEST["excluded_units"][0] == {
        "source_path": "oldest_pd_instances.csv[row=4..17915]",
        "count": 17912,
        "reason": "complete source rows outside this bounded fixture selection",
        "disposition": "outside-scope-unprojected",
    }
    assert MANIFEST["excluded_units"][1]["reason"] == "malformed source row after bounded complete prefix"
    for occurrence in occurrences:
        source_row = rows[int(occurrence.get("sourceOrdinal")) - 1]
        assert occurrence.get("sourcePath") == f"{MANIFEST['source_member']}[row={occurrence.get('sourceOrdinal')}]"
        assert occurrence.get("title") == source_row["Title"]
        assert occurrence.get("author") == source_row["Author name"]
        assert occurrence.get("hymnal") == source_row["Hymnal title"]
        assert occurrence.get("edition") == source_row["Hymnal publication year"]
        for retained_name, source_name in (("authorBirth", "Author birth"), ("authorDeath", "Author death"), ("yearWritten", "Year written")):
            assert occurrence.get(retained_name) == (source_row[source_name] or None)
        assert occurrence.findtext("rawFullText") == source_row["Full text"].replace("\r\n", "\n").replace("\r", "\n")
        expected_lines = projected_source_lines(source_row["Full text"])
        actual_lines = [norm(line) for segment in occurrence.findall("segment") for line in segment.findall("line")]
        assert actual_lines == expected_lines
        assert occurrence.get("textId") == derived_source_text_id(source_row["Title"], source_row["Author name"], "\n".join(expected_lines))


def test_fixture_is_valid_tei_p5_and_schema_is_closed():
    compiled_tei_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd").assertValid(E.parse(str(PATH)))
    schema = json.loads((ROOT / "schemas/v2/categories/hymns.schema.json").read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert schema["properties"]["work_id"]["$ref"].endswith("#/properties/work_id")
    assert "allOf" not in schema


@pytest.mark.parametrize(
    "mutation",
    [
        "omit", "duplicate", "reverse", "text", "title", "first_line", "text_identity",
        "occurrence_identity", "segment_order", "stanza", "refrain", "hymnal", "tune",
        "locator", "rights", "warning", "exclusion", "inventory", "unsupported", "source",
        "policy", "common", "mapping",
    ],
)
def test_source_mutations_fail_even_when_receipt_is_forged(mutation):
    result = project(PATH, **CONTEXT)
    rows = result["rows"]
    if mutation == "omit":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(copy.deepcopy(rows[-1]))
    elif mutation == "reverse":
        rows.reverse()
    elif mutation == "text":
        rows[0]["text"] += " Invented line."
    elif mutation == "title":
        rows[2]["title"] = "Promoted first line"
    elif mutation == "first_line":
        rows[0]["first_line"] = "Invented first line"
    elif mutation == "text_identity":
        rows[0]["hymn_text_id"] = "text-forged"
    elif mutation == "occurrence_identity":
        rows[0]["occurrence_id"] = "occ-forged"
    elif mutation == "segment_order":
        rows[0]["segments"].reverse()
    elif mutation == "stanza":
        rows[0]["stanzas"][0]["lines"].pop()
    elif mutation == "refrain":
        rows[0]["refrain"]["lines"].append("Invented refrain")
    elif mutation == "hymnal":
        rows[0]["hymnal_setting"]["edition"] = "1901"
    elif mutation == "tune":
        rows[0]["tune"] = "Invented tune"
    elif mutation == "locator":
        rows[0]["locator"]["occurrence"] = 99
    elif mutation == "rights":
        rows[0]["rights"] = {"text": "Forged", "tune": "Cleared"}
    elif mutation == "warning":
        result["receipt"]["warnings"] = [{"tei_path": "/invented", "reason": "invented"}]
    elif mutation == "exclusion":
        result["receipt"]["exclusions"] = []
    elif mutation == "inventory":
        result["receipt"]["inventory"].pop()
    elif mutation == "unsupported":
        result["receipt"]["unsupported"] = ["hidden structure"]
    elif mutation == "source":
        result["receipt"]["master_sha256"] = "0" * 64
    elif mutation == "policy":
        result["receipt"]["policy_sha256"] = "0" * 64
    elif mutation == "common":
        result["receipt"]["common_schema_sha256"] = "0" * 64
    elif mutation == "mapping":
        result["receipt"]["mapping_version"] = "forged"
    assert verify(PATH, rows, forged_receipt(result), **CONTEXT)


@pytest.mark.parametrize("change", ["table", "attribute", "loose", "tail", "duplicate-id", "namespace", "doctype", "prolog-pi", "epilog-pi", "utf16-pi"])
def test_unsupported_source_structure_fails_both_routes(change, tmp_path):
    root = E.parse(str(PATH))
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    occurrences = root.xpath("//t:body/t:div/t:div", namespaces=ns)
    if change == "table":
        E.SubElement(occurrences[0], "{" + ns["t"] + "}table")
    elif change == "attribute":
        occurrences[0].set("ana", "invented")
    elif change == "loose":
        occurrences[0].text = "Unmapped visible words"
    elif change == "tail":
        occurrences[0][0].tail = "Unmapped visible tail"
    elif change == "duplicate-id":
        occurrences[1].set("{http://www.w3.org/XML/1998/namespace}id", occurrences[0].get("{http://www.w3.org/XML/1998/namespace}id"))
    elif change == "namespace":
        occurrences[0].tag = "{urn:wrong}div"
    raw = E.tostring(root, encoding="utf-8")
    if change == "doctype":
        raw = b'<!DOCTYPE TEI [<!ENTITY x "danger">]>' + raw
    elif change == "prolog-pi":
        raw = b'<?xml-stylesheet hidden?>' + raw
    elif change == "epilog-pi":
        raw += b'<?hidden test?>'
    elif change == "utf16-pi":
        raw = ('<?xml version="1.0" encoding="utf-16"?><?hidden test?>' + raw.decode("utf-8")).encode("utf-16")
    bad = tmp_path / "bad-hymns.xml"
    bad.write_bytes(raw)
    result = project(PATH, **CONTEXT)
    with pytest.raises(PipelineError):
        project(bad, **CONTEXT)
    assert verify(bad, result["rows"], result["receipt"], **CONTEXT)


def test_checker_has_no_producer_dependency(monkeypatch):
    result = project(PATH, **CONTEXT)
    import ocd_kernel.projection.categories.hymns as module

    monkeypatch.setattr(module, "project_hymns_document", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("producer called")))
    assert verify(PATH, result["rows"], result["receipt"], **CONTEXT) == []


def test_forged_independent_status_is_rejected():
    result = project(PATH, **CONTEXT)
    forged = copy.deepcopy(result["receipt"])
    forged["independent_check"] = {"status": "passed"}
    assert verify(PATH, result["rows"], forged, **CONTEXT)


def test_retained_hash_is_verified_against_actual_file():
    context = {**CONTEXT, "retained_sha256": "0" * 64}
    with pytest.raises(PipelineError, match="retained source sha256"):
        project(PATH, **context)
    assert any("retained source sha256" in error for error in verify(PATH, [], {}, **context))
    context.pop("retained_path")
    with pytest.raises(PipelineError, match="retained source path"):
        project(PATH, **context)


def test_stanza_note_rejected_before_correspondence(tmp_path):
    tree = E.parse(str(PATH)); stanza = tree.xpath('//t:lg[@type="stanza"]', namespaces={"t":"http://www.tei-c.org/ns/1.0"})[0]
    note = E.SubElement(stanza, '{http://www.tei-c.org/ns/1.0}note', type="tune"); note.text = "Unsupported tune note"
    bad = tmp_path / "stanza-note.xml"; bad.write_bytes(E.tostring(tree))
    with pytest.raises(PipelineError, match="note inside stanza"):
        project(bad, **CONTEXT)
    assert any("note inside stanza" in error for error in verify(bad, [], {}, **CONTEXT))


def test_private_occurrence_ids_do_not_escape_into_public_rows():
    result = project(PATH, **CONTEXT)
    serialized = json.dumps(result['rows'])
    assert 'Oldest public-domain instances' not in serialized
    tree = E.parse(str(PATH))
    for unit in tree.xpath('//t:div[@type="hymn"]', namespaces={"t":"http://www.tei-c.org/ns/1.0"}):
        assert unit.get('{http://www.w3.org/XML/1998/namespace}id') not in serialized
