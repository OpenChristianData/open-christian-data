"""PIPE-012 source-bound poetry projection checks."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from lxml import etree as E
import jsonschema
import pytest
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from ocd_kernel.library._common import PipelineError
import ocd_kernel.projection.categories.poetry as poetry
from ocd_kernel.projection.categories.poetry import (
    project_poetry_document as project,
    verify_poetry_document as verify,
)
from build.lib.tei_xsd import compiled_tei_schema


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/library-pipeline/categories/poetry"
MANIFEST = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
PATH = FIXTURE / "master.tei.xml"
CONTEXT = MANIFEST["context"]
TEI_XSD = ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"
SCHEMA = ROOT / "schemas/v2/categories/poetry.schema.json"
COMMON = ROOT / "schemas/v2/public-row.schema.json"
BUILDER = ROOT / "plans/2026-08-31-library-pipeline-redesign/artifacts/PIPE-012/build_fixture.py"
NS = {"t": "http://www.tei-c.org/ns/1.0"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def canonical_rows(rows: list[dict[str, object]]) -> str:
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def normalize(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def source_verse(raw: bytes, source_id: str) -> tuple[bytes, E._Element]:
    pattern = rb"<verse\s+id=\"" + re.escape(source_id.encode("ascii")) + rb"\">.*?</verse>"
    match = re.search(pattern, raw, flags=re.S)
    assert match is not None, source_id
    source = E.fromstring(raw, parser=E.XMLParser(load_dtd=False, resolve_entities=False, no_network=True))
    found = source.xpath("//*[@id=$id]", id=source_id)
    assert len(found) == 1
    return match.group(0), found[0]


def test_real_poems_preserve_short_and_long_source_divisions() -> None:
    result = project(PATH, **CONTEXT)
    rows = result["rows"]
    token = lambda value: hashlib.sha256(value.encode()).hexdigest()[:20]
    assert len(rows) == MANIFEST["counts"]["public_poem_rows"] == 2
    assert MANIFEST["counts"]["selected_units"] == 10
    assert rows[0]["division_id"] == token("v.vi-p32.1")
    assert rows[0]["poem_id"] == token("v.vi-p32.1")
    assert rows[0]["stanzas"] == [{"number": 1, "lines": ["O Lamb of God, was ever pain,", "Was ever love like thine?"]}]
    assert "poem_title" not in rows[0]
    assert rows[1]["poem_id"] == rows[1]["division_id"] == token("v.xxvi-p48")
    assert rows[1]["poem_title"] == "A PARAPHRASE ON THE LORD’S PRAYER"
    assert len(rows[1]["stanzas"]) == 9
    assert [stanza["number"] for stanza in rows[1]["stanzas"]] == list(range(1, 10))
    assert all(len(stanza["lines"]) == 8 for stanza in rows[1]["stanzas"])
    assert [row["sequence"] for row in rows] == [1, 2]
    assert [row["record_id"] for row in rows] == [f"{CONTEXT['identity']['edition_id']}:poetry:{row['division_id']}" for row in rows]
    retained = E.parse(str(FIXTURE / "retained.xml"))
    source_poems = retained.xpath("/sourceExcerpt/poem")
    assert len(source_poems) == len(rows)
    for row, poem, anchor in zip(rows, source_poems, result["receipt"]["anchors"], strict=True):
        lines = poem.xpath('./division/stanza/line')
        assert row['text'] == "\n".join(normalize(line.text) for line in lines)
        assert [line.get('id') for line in lines] == anchor['line_ids']
        assert row['locator']['division'] == 1
    serialized = json.dumps(rows)
    assert 'John Wesley sermons' not in serialized
    for identifier in retained.xpath('//@id'):
        assert identifier not in serialized

    receipt = result["receipt"]
    assert receipt["source_binding"] == {
        "source_url": CONTEXT["source_url"],
        "source_sha256": CONTEXT["source_sha256"],
        "retained_sha256": CONTEXT["retained_sha256"],
    }
    assert receipt["master_sha256"] == hashlib.sha256(PATH.read_bytes()).hexdigest()
    assert receipt["row_count"] == len(rows) == len(receipt["anchors"])
    assert receipt["output_sha256"] == canonical_rows(rows)
    assert receipt["inventory"] == result["inventory"]
    assert receipt["warnings"] == result["warnings"]
    assert receipt["exclusions"] == result["exclusions"]
    assert receipt["unsupported"] == []
    assert receipt["independent_check"] == {"status": "pending"}
    for row, anchor in zip(rows, receipt["anchors"], strict=True):
        assert anchor["record_id"] == row["record_id"]
        assert token(anchor["source_xml_id"]) == row["division_id"]
        assert token(anchor["poem_id"]) == row["poem_id"]
        assert anchor["source_order"] == row["sequence"]
        assert anchor["poem_order"] == row["locator"]["division"]
        assert anchor["text_sha256"] == hashlib.sha256(row["text"].encode("utf-8")).hexdigest()
        assert anchor["text_length"] == len(row["text"])
        assert anchor["stanza_count"] == len(row["stanzas"])
        assert anchor["line_count"] == sum(len(stanza["lines"]) for stanza in row["stanzas"])
        assert anchor["tei_path"].startswith("/TEI[1]/text[1]/body[1]/div")
    assert verify(PATH, rows, receipt, **CONTEXT) == []


@pytest.mark.requires_local_artifacts
def test_selected_units_bind_to_the_actual_ccel_verse_nodes() -> None:
    source = ROOT / MANIFEST["source"]["path"]
    raw = source.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == MANIFEST["source"]["sha256"] == CONTEXT["source_sha256"]
    assert len(raw) == MANIFEST["source"]["bytes"]
    root = E.fromstring(raw, parser=E.XMLParser(load_dtd=False, resolve_entities=False, no_network=True))
    assert len(root.xpath('//*[local-name()="verse"]')) == MANIFEST["source"]["verse_count"] == 412
    retained = E.parse(str(FIXTURE / "retained.xml"))
    selected = MANIFEST["selection"]["selected_units"]
    divisions = retained.xpath("/sourceExcerpt/poem/division")
    assert [item["source_xml_id"] for item in selected] == [unit.get("id") for unit in divisions]
    for item, division in zip(selected, divisions, strict=True):
        fragment, verse = source_verse(raw, item["source_xml_id"])
        raw_node = division.find("rawSourceFragment")
        assert raw_node is not None
        assert bytes(raw_node.text or "", "utf-8") == fragment
        assert hashlib.sha256(fragment).hexdigest() == item["raw_fragment_sha256"] == raw_node.get("sha256")
        source_lines = verse.xpath("./l")
        retained_lines = division.xpath("./stanza/line")
        assert [line.get("id") for line in source_lines] == [line.get("id") for line in retained_lines] == item["line_ids"]
        assert [normalize("".join(line.itertext())) for line in source_lines] == [normalize("".join(line.itertext())) for line in retained_lines]
        assert item["source_path"] == f"{MANIFEST['source']['path']}#{item['source_xml_id']}"
        assert int(division.get("sourceOrdinal")) == item["source_ordinal"]
    assert MANIFEST["counts"]["excluded_source_verse_count"] == len(MANIFEST["selection"]["excluded_source_ids"]) == 402
    all_ids = [node.get("id") for node in root.xpath('//*[local-name()="verse"]')]
    assert set(MANIFEST["selection"]["selected_source_ids"]) | set(MANIFEST["selection"]["excluded_source_ids"]) == set(all_ids)


@pytest.mark.requires_local_artifacts
def test_fixture_builder_is_reproducible_in_two_processes(tmp_path: Path) -> None:
    outputs: list[Path] = []
    for index in (1, 2):
        target = tmp_path / f"build-{index}"
        subprocess.run([sys.executable, str(BUILDER), "--output-dir", str(target)], check=True)
        outputs.append(target)
    names = ("master.tei.xml", "retained.xml", "manifest.json")
    for name in names:
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes()
        assert (outputs[0] / name).read_bytes() == (FIXTURE / name).read_bytes()


def test_tei_xsd_and_closed_json_schema() -> None:
    tree = E.parse(str(PATH))
    compiled_tei_schema(TEI_XSD).assertValid(tree)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    common = json.loads(COMMON.read_text(encoding="utf-8"))
    registry = Registry().with_resource(common["$id"], Resource.from_contents(common, default_specification=DRAFT202012))
    validator = jsonschema.Draft202012Validator(schema, registry=registry)
    validator.check_schema(schema)
    assert all(profile["additionalProperties"] is False for profile in schema["oneOf"])
    assert "allOf" not in json.dumps(schema)
    for name in ("work_id", "textual_form_id", "edition_id", "record_id", "sequence", "language", "text", "representation_revision", "provenance", "notes", "references"):
        assert schema["oneOf"][0]["properties"][name]["$ref"].startswith("ocd://schemas/v2/public-row.schema.json#/")
    result = project(PATH, **CONTEXT)
    for row in result["rows"]:
        assert not list(validator.iter_errors(row))


def test_source_bound_mutations_are_rejected() -> None:
    result = project(PATH, **CONTEXT)
    mutations: list[tuple[str, object]] = []
    row_fields = (
        "record_id", "sequence", "text", "poem_id", "division_id", "poem_title", "stanzas", "locator",
    )
    for field in row_fields:
        altered = copy.deepcopy(result["rows"])
        row = altered[1]
        if field == "record_id":
            row[field] = "forged-record"
        elif field == "sequence":
            row[field] = 99
        elif field == "text":
            row[field] += " forged"
        elif field == "poem_id":
            row[field] = "forged-poem"
        elif field == "division_id":
            row[field] = "forged-division"
        elif field == "poem_title":
            row[field] = "Forged title"
        elif field == "stanzas":
            row[field][0]["lines"].reverse()
        else:
            row[field]["division"] = 99
        mutations.append((f"row:{field}", altered))
    for label, altered in mutations:
        assert verify(PATH, altered, result["receipt"], **CONTEXT), label

    receipt_fields = (
        "mapping_version", "assembler_version", "master_sha256", "source_binding", "policy_sha256",
        "common_schema_sha256", "output_sha256", "row_count", "anchors", "inventory", "warnings",
        "exclusions", "unsupported", "independent_check",
    )
    for field in receipt_fields:
        receipt = copy.deepcopy(result["receipt"])
        if field == "source_binding":
            receipt[field]["source_sha256"] = "0" * 64
        elif field == "anchors":
            receipt[field][0]["line_ids"].reverse()
        elif field == "inventory":
            receipt[field][0]["ordinal"] = 999
        elif field in {"warnings", "exclusions", "unsupported"}:
            receipt[field] = list(receipt[field]) + [{"forged": True}]
        elif field == "independent_check":
            receipt[field] = {"status": "passed"}
        elif field == "row_count":
            receipt[field] = 99
        else:
            receipt[field] = "forged"
        assert verify(PATH, result["rows"], receipt, **CONTEXT), field


@pytest.mark.parametrize(
    "label,replacement",
    [
        ("table", ("<lg type=\"stanza\"", "<table><row/></table><lg type=\"stanza\"")),
        ("unknown-attribute", ("xml:id=\"v.vi-p32.1\"", "ana=\"forged\" xml:id=\"v.vi-p32.1\"")),
        ("loose-text", ("<div type=\"poem\" xml:id=\"v.vi-p32.1\">", "<div type=\"poem\" xml:id=\"v.vi-p32.1\">FORGED")),
        ("duplicate-id", ("<div type=\"poem\" xml:id=\"v.xxvi-p48\">", "<div type=\"poem\" xml:id=\"v.vi-p32.1\">")),
        ("bad-stanza-number", ("<lg type=\"stanza\" n=\"1\"", "<lg type=\"stanza\" n=\"bad\"")),
        ("empty-line", ("<l xml:id=\"v.vi-p32.2\">O Lamb", "<l xml:id=\"v.vi-p32.2\"></l><l xml:id=\"v.vi-p32.2b\">O Lamb")),
        ("mixed-poem", ("<div type=\"poem\" xml:id=\"v.xxvi-p48\">", "<div type=\"poem\" xml:id=\"v.xxvi-p48\"><div type=\"poem-division\" xml:id=\"invented-division\"><lg type=\"stanza\"><l xml:id=\"invented\">x</l></lg></div>")),
        ("prolog-pi", ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>", "<?xml version=\"1.0\" encoding=\"UTF-8\"?><?xml-stylesheet href=\"x\"?>")),
        ("epilog-pi", ("</TEI>\n", "<?xml-stylesheet href=\"x\"?></TEI>\n")),
    ],
)
def test_unsupported_structure_is_visible_to_both_routes(tmp_path: Path, label: str, replacement: tuple[str, str]) -> None:
    raw = PATH.read_bytes()
    old, new = replacement
    assert old in raw.decode("utf-8"), label
    mutated = tmp_path / f"{label}.tei.xml"
    mutated.write_bytes(raw.replace(old.encode("utf-8"), new.encode("utf-8"), 1))
    with pytest.raises(PipelineError):
        project(mutated, **CONTEXT)
    errors = verify(mutated, [], None, **CONTEXT)
    assert errors, label


def test_checker_does_not_call_producer_and_rejects_forged_status(monkeypatch: pytest.MonkeyPatch) -> None:
    result = project(PATH, **CONTEXT)

    def bomb(*args: object, **kwargs: object) -> object:
        raise AssertionError("producer called")

    monkeypatch.setattr(poetry, "project_poetry_document", bomb)
    assert verify(PATH, result["rows"], result["receipt"], **CONTEXT) == []
    forged = copy.deepcopy(result["receipt"])
    forged["independent_check"] = {"status": "passed"}
    assert verify(PATH, result["rows"], forged, **CONTEXT)


@pytest.mark.requires_local_artifacts
def test_complete_short_owen_poem_keeps_language_emphasis_and_all_lines(tmp_path):
    manifest = json.loads((FIXTURE/'owen.manifest.json').read_text(encoding='utf-8'))
    raw = (ROOT/manifest['source_path']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest['source_sha256']
    source = E.fromstring(raw, E.XMLParser(load_dtd=False, resolve_entities=False, no_network=True))
    section = source.xpath('.//div2[@id="i.iv"]')[0]
    assert E.tostring(section, method='c14n') == (FIXTURE/'owen.retained.xml').read_bytes()
    assert [n.get('id') for n in source.xpath('.//div2')] == [n['id'] for n in manifest['source_sections']]
    for node, entry in zip(source.xpath('.//div2'), manifest['source_sections'], strict=True):
        assert hashlib.sha256(E.tostring(node, method='c14n')).hexdigest() == entry['sha256']
    lines = section.xpath('./verse/l')
    assert len(lines) == manifest['line_count'] == 16
    assert all(line.xpath('./span[@lang="LA"]') for line in lines)
    path = FIXTURE/'owen.tei.xml'; context = manifest['context']; out = project(path, **context)
    assert len(out['rows']) == 1
    row = out['rows'][0]
    assert row['language'] == 'la'
    assert row['poem_title'] == ''.join(section.find('p').itertext())
    assert row['stanzas'] == [{'number':1, 'lines':[normalize(''.join(line.itertext())) for line in lines]}]
    tree = E.parse(str(path)); namespaces={'t':'http://www.tei-c.org/ns/1.0'}
    assert len(tree.xpath('//t:foreign[@xml:lang="la"]', namespaces=namespaces)) == 16
    assert [normalize(''.join(n.itertext())) for n in tree.xpath('//t:hi[@rend="small-caps"]', namespaces=namespaces)] == [normalize(''.join(n.itertext())) for n in section.xpath('./verse//span[@class="sc"]')]
    assert verify(path, out['rows'], out['receipt'], **context) == []
    compiled_tei_schema(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd').assertValid(tree)
    builder=ROOT/'plans/2026-08-31-library-pipeline-redesign/artifacts/PIPE-012/build_owen_fixture.py'
    target=tmp_path/'owen-rebuild';subprocess.run([sys.executable,str(builder),'--output-dir',str(target)],check=True)
    for name in ['owen.manifest.json','owen.tei.xml','owen.retained.xml']:
        assert (target/name).read_bytes() == (FIXTURE/name).read_bytes()
