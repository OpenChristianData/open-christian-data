from __future__ import annotations

import ast
from io import BytesIO
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from lxml import etree
import pytest

from build.tei.schaff_history_vol_1_oracle import _independent_check
from build.tei.schaff_history_vol_1_reconstruction import _build_tei
from ocd_kernel.reconstruction.contract import SourceManifest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    ROOT / 'tests/fixtures/reconstruction-runtime/schaff_history_vol_1_oracle.source-manifest.json'
)
SOURCE_PATH = ROOT / "raw/ccel/schaff/hcc1.xml"
PROFILE_PATH = (
    ROOT
    / "sources/structured-text/schaff-history-vol-1/"
    / "schaff-history-vol-1.reconstruction-profile.json"
)
POLICY_PATH = (
    ROOT
    / "sources/structured-text/schaff-history-vol-1/"
    / "schaff-history-vol-1.validation-policy.json"
)
ACCOUNTABILITY_SCHEMA_PATH = (
    ROOT
    / "sources/structured-text/schaff-history-vol-1/"
    / "schaff-history-vol-1.source-accountability.schema.json"
)
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"t": TEI_NS, "xml": XML_NS}


@pytest.fixture(scope="module")
def built() -> tuple[SourceManifest, bytes, object, dict[str, object]]:
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    tei_bytes = _build_tei(manifest)
    facts, accountability = _independent_check(manifest, tei_bytes)
    return manifest, tei_bytes, facts, accountability


def _mutate(tei_bytes: bytes, mutation: str) -> bytes:
    tree = etree.parse(BytesIO(tei_bytes))
    root = tree.getroot()
    if mutation == "omit-div3":
        target = root.xpath(
            ".//t:div[@type='ThML-div3'][@xml:id='i.v.i']",
            namespaces=NS,
        )[0]
        target.getparent().remove(target)
    elif mutation == "reorder-div3":
        pair = root.xpath(
            ".//t:div[@type='ThML-div3'][@xml:id='i.v.i' or @xml:id='i.v.1']",
            namespaces=NS,
        )
        assert len(pair) == 2 and pair[0].getparent() is pair[1].getparent()
        parent = pair[0].getparent()
        parent.remove(pair[1])
        parent.insert(parent.index(pair[0]), pair[1])
    elif mutation == "alter-heading":
        heading = root.xpath(
            ".//t:head[@type='source-h1']", namespaces=NS
        )[0]
        heading.text = "Invented index heading"
    elif mutation == "alter-source-attributes":
        target = root.xpath(
            "./t:standOff/t:list[@type='source-projection']/"
            "t:item[@corresp='#i']",
            namespaces=NS,
        )[0]
        record = json.loads(target.text)
        record["source_attributes"] = []
        target.text = json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    elif mutation == "reorder-header":
        header = root.xpath(
            "./t:teiHeader/t:fileDesc/t:notesStmt/"
            "t:note[@type='retained-ThML-header']/t:p/"
            "t:seg[@type='retained-ThML-header']",
            namespaces=NS,
        )[0]
        children = [child for child in header if isinstance(child.tag, str)]
        assert len(children) >= 2
        header.remove(children[1])
        header.insert(header.index(children[0]), children[1])
    else:
        raise AssertionError(f"unknown test mutation: {mutation}")
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + etree.tostring(
        tree, encoding="UTF-8", xml_declaration=False, pretty_print=False
    )


def test_manifest_binds_exact_owner_routed_member_and_unresolved_identity() -> None:
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    source = manifest.authority_path("primary-source")
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    authority = next(
        row
        for row in manifest.record["authorities"]
        if row["name"] == "primary-source"
    )

    assert manifest.record["ticket_id"] == "LIB-058"
    assert manifest.record["work_id"] == "schaff-history-vol-1"
    assert manifest.record["source_id"] == "ccel-schaff-hcc1-thml"
    assert authority["path"] == "raw/ccel/schaff/hcc1.xml"
    assert source.samefile(SOURCE_PATH.resolve())
    assert len(source.read_bytes()) == 3_630_817
    assert authority["sha256"] == (
        "0a2a7cc56e2d00c791eeaacd5516a292a855426c3a8ceb8d5eeef6eeb49e3d09"
    )
    assert profile["owner_route"]["stored_file_count_used_as_boundary"] is False
    assert profile["identity"]["textual_form"] == "unresolved"
    assert profile["identity"]["print_edition"] == "unresolved"
    assert profile["identity"]["rights_status"] == "unresolved"
    assert policy["prohibited_authorities"]
    assert profile["identity"].get("license") is None


def test_complete_six_division_and_h1_to_h6_envelope_is_accounted(built) -> None:
    _manifest, _tei, facts, accountability = built

    assert facts.findings == ()
    assert accountability["division_counts"] == {
        "div": 16,
        "div1": 2,
        "div2": 25,
        "div3": 102,
        "div4": 0,
        "div5": 0,
        "div6": 0,
    }
    assert accountability["heading_counts"] == {
        "h1": 1,
        "h2": 8,
        "h3": 0,
        "h4": 1,
        "h5": 0,
        "h6": 1,
    }
    assert accountability["source_element_count"] == accountability[
        "represented_element_count"
    ]
    assert accountability["omitted_element_count"] == 0
    assert accountability["duplicate_element_count"] == 0
    assert accountability["selection"]["included_body_div1_ids"] == ["i", "ii"]
    assert accountability["selection"]["excluded_body_division_ids"] == []
    assert len(accountability["division_carriers"]) == 145
    assert len(accountability["heading_carriers"]) == 11

    first, second = [
        row
        for row in accountability["division_carriers"]
        if row["tag"] == "div1"
    ]
    assert (first["id"], first["ordinal"], first["title"]) == (
        "i",
        1,
        "Apostolic Christianity",
    )
    assert (second["id"], second["ordinal"], second["title"]) == (
        "ii",
        2,
        "Indexes",
    )
    assert accountability["envelope"]["external_dtd_loaded"] is False
    assert accountability["envelope"]["source_head_disposition"] == (
        "represented_in_TEI_header"
    )
    assert accountability["envelope"]["source_body_disposition"] == (
        "represented_in_TEI_text_body"
    )

    schema = json.loads(ACCOUNTABILITY_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(accountability))
    assert errors == []


def test_producer_emits_deterministic_schema_valid_tei_without_package_writes(built) -> None:
    manifest, first, facts, accountability = built
    source_hash_before = SOURCE_PATH.read_bytes()
    second = _build_tei(manifest)
    tree = etree.parse(BytesIO(first))
    root = tree.getroot()

    assert first == second
    assert first.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
    assert root.xpath("count(/t:TEI/t:text/t:body/t:div[@type='ThML-div1'])", namespaces=NS) == 2.0
    assert root.xpath(
        "/t:TEI/t:text/t:body/t:div[@xml:id='i' or @xml:id='ii']/@xml:id",
        namespaces={**NS, "xml": "http://www.w3.org/XML/1998/namespace"},
    ) == ["i", "ii"]
    assert root.xpath("count(.//t:head[@type='source-h3'])", namespaces=NS) == 0.0
    assert root.xpath(
        "count(/t:TEI/t:text/t:body//t:div[@type='source-order-wrapper'])",
        namespaces=NS,
    ) == 2.0
    assert root.xpath(
        "count(/t:TEI/t:standOff/t:list[@type='source-projection']/"
        "t:item)",
        namespaces=NS,
    ) == float(accountability["source_element_count"])
    assert facts.findings == ()
    assert SOURCE_PATH.read_bytes() == source_hash_before


@pytest.mark.parametrize(
    "mutation",
    [
        "omit-div3",
        "reorder-div3",
        "alter-heading",
        "alter-source-attributes",
        "reorder-header",
    ],
)
def test_independent_checker_rejects_source_carrier_mutations(built, mutation: str) -> None:
    manifest, tei_bytes, _facts, _accountability = built
    mutated = _mutate(tei_bytes, mutation)

    with pytest.raises(ValueError):
        _independent_check(manifest, mutated)


def test_checker_has_no_producer_import_and_assembles_mechanical_facts(built) -> None:
    source = (ROOT / "build/tei/schaff_history_vol_1_oracle.py").read_text(
        encoding="utf-8"
    )
    syntax = ast.parse(source)
    imported_modules = []
    for node in ast.walk(syntax):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)
    assert all(
        "schaff_history_vol_1_reconstruction" not in module
        for module in imported_modules
    )
    assert source.count("verify_mechanical_facts(") == 1

    _manifest, _tei, facts, _accountability = built
    assert facts.validator_implementation_sha256
    assert facts.validator_import_closure_sha256
    assert facts.source_sha256 == (
        "0a2a7cc56e2d00c791eeaacd5516a292a855426c3a8ceb8d5eeef6eeb49e3d09"
    )
