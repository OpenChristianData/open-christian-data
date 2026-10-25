from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.athanasius_table_oracle import _closure_digest, _oracle
from build.tei.athanasius_table_reconstruction import ASSIGNED, _convert
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    prepare_review,
    reconstruct,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "raw/ccel/npnf2/npnf204.xml"
RETAINED_SOURCE_MANIFEST = (
    ROOT
    / "sources/structured-text/athanasius-on-the-incarnation"
    / "athanasius-table.source-manifest.json"
)
SOURCE_MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/athanasius-table.source-manifest.json"
SOURCE_SHA256 = "bd625a0fa4f5ddd4b2fa13fcee753de8832ea4b316625e0e06454beb81cfa652"
TEI_NS = "http://www.tei-c.org/ns/1.0"
EXPECTED_MEMBERS = {
    "manifest.json",
    "content.tei.xml",
    "source-accountability.json",
    "provenance.json",
    "unresolved.jsonl",
    "README.source.md",
}
EXPECTED_DIVISIONS = [
    "i",
    "ii",
    "iii",
    "iv",
    "v",
    *(scope for scope, _ in ASSIGNED),
    "xxvi",
]
EXPECTED_ORACLE_IMPORT_CLOSURE = (
    "build/__init__.py",
    "build/tei/__init__.py",
    "build/tei/athanasius_table_oracle.py",
    "ocd_kernel/__init__.py",
    "ocd_kernel/lib/__init__.py",
    "ocd_kernel/lib/path_io.py",
    "ocd_kernel/lib/storage_topology.py",
    "ocd_kernel/reconstruction/__init__.py",
    "ocd_kernel/reconstruction/contract.py",
    "ocd_kernel/tei/__init__.py",
    "ocd_kernel/tei/normalization.py",
    "ocd_kernel/tei/projection_profile.py",
    "ocd_kernel/tei/validate.py",
)
GOVERNED_LF_PATHS = (
    "sources/structured-text/athanasius-on-the-incarnation/config.json",
    "sources/structured-text/athanasius-on-the-incarnation/athanasius-table.source-manifest.json",
    "sources/structured-text/athanasius-on-the-incarnation/README.md",
    "sources/structured-text/athanasius-on-the-incarnation/ccel-permission.md",
    "sources/structured-text/athanasius-on-the-incarnation/athanasius-table.reconstruction-profile.json",
    "sources/structured-text/athanasius-on-the-incarnation/athanasius-table.validation-policy.json",
    "sources/structured-text/athanasius-on-the-incarnation/athanasius-table.source-accountability.schema.json",
    "build/tei/athanasius_table_reconstruction.py",
    "build/tei/athanasius_table_oracle.py",
)
GOVERNED_CRLF_PATHS = (
    "sources/structured-text/athanasius-against-the-arians/config.json",
    "sources/structured-text/athanasius-against-the-heathen/config.json",
    "sources/structured-text/athanasius-apology-to-the-emperor/config.json",
    "sources/structured-text/athanasius-arian-history/config.json",
    "sources/structured-text/athanasius-circular-to-bishops-of-egypt-and-libya/config.json",
    "sources/structured-text/athanasius-defence-against-the-arians/config.json",
    "sources/structured-text/athanasius-defence-of-dionysius/config.json",
    "sources/structured-text/athanasius-defence-of-his-flight/config.json",
    "sources/structured-text/athanasius-defence-of-the-nicene-definition/config.json",
    "sources/structured-text/athanasius-deposition-of-arius/config.json",
    "sources/structured-text/athanasius-encyclical-letter/config.json",
    "sources/structured-text/athanasius-letters-and-chronicles/config.json",
    "sources/structured-text/athanasius-life-of-antony/config.json",
    "sources/structured-text/athanasius-on-ariminum-and-seleucia/config.json",
    "sources/structured-text/athanasius-on-luke-10-22/config.json",
    "sources/structured-text/athanasius-statement-of-faith/config.json",
    "sources/structured-text/athanasius-synodal-letter-to-africa/config.json",
    "sources/structured-text/athanasius-synodal-letter-to-antioch/config.json",
    "sources/structured-text/eusebius-letter-on-nicene-creed/config.json",
    "build/tei/__init__.py",
    "ocd_kernel/__init__.py",
    "ocd_kernel/tei/__init__.py",
    "ocd_kernel/tei/normalization.py",
    "ocd_kernel/tei/projection_profile.py",
    "ocd_kernel/tei/validate.py",
)

# These authorities intentionally use `-text` so Git preserves their bound
# bytes, including the committed mixed-line-ending projection dependency.
EXACT_BYTE_TEXT_UNSET_PATHS = frozenset(
    [
        "sources/structured-text/athanasius-on-the-incarnation/config.json",
        *GOVERNED_CRLF_PATHS[:19],
        "ocd_kernel/tei/projection_profile.py",
    ]
)
MIXED_EOL_PATHS = frozenset({"ocd_kernel/tei/projection_profile.py"})


def _assert_effective_checkout_eol(relative: str, expected: str) -> None:
    relative_bytes = relative.encode("utf-8")
    output = subprocess.run(
        ["git", "check-attr", "-z", "text", "eol", "--", relative],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    expected_text = (
        b"unset" if relative in EXACT_BYTE_TEXT_UNSET_PATHS else b"set"
    )
    expected_eol = (
        "unspecified"
        if relative in EXACT_BYTE_TEXT_UNSET_PATHS
        else expected
    )
    assert output.split(b"\0") == [
        relative_bytes,
        b"text",
        expected_text,
        relative_bytes,
        b"eol",
        expected_eol.encode("ascii"),
        b"",
    ]


def _canonical(record: object) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_runtime_fixture_preserves_retained_authorities_and_only_updates_closure() -> None:
    raw = RETAINED_SOURCE_MANIFEST.read_bytes()
    assert _sha(raw) == "9f65b4c6fb61c59750e8d1b06d0a590f78915764bd8bf355edc1459dfea8c5cf"
    expected = json.loads(raw)
    policy_path = next(item["path"] for item in expected["authorities"]
                       if item["name"] == "validation-policy")
    policy = json.loads((ROOT / policy_path).read_bytes())
    expected["validator"]["import_closure_sha256"] = _closure_digest(ROOT, policy)
    assert json.loads(SOURCE_MANIFEST.read_bytes()) == expected


def test_manifest_authorities_and_recursive_closure_materialize_portably() -> None:
    manifest = json.loads(SOURCE_MANIFEST.read_bytes())
    authority_bindings = {
        item["path"]: (item["bytes"], item["sha256"])
        for item in manifest["authorities"]
    }
    implementation_bindings = {
        manifest["converter"]["implementation_path"]: manifest["converter"][
            "implementation_sha256"
        ],
        manifest["validator"]["implementation_path"]: manifest["validator"][
            "implementation_sha256"
        ],
    }

    for relative in GOVERNED_LF_PATHS:
        _assert_effective_checkout_eol(relative, "lf")
        payload = (ROOT / relative).read_bytes()
        assert b"\r\n" not in payload
        if relative in authority_bindings:
            expected_bytes, expected_sha256 = authority_bindings[relative]
            assert len(payload) == expected_bytes
            assert _sha(payload) == expected_sha256
        if relative in implementation_bindings:
            assert _sha(payload) == implementation_bindings[relative]

    for relative in GOVERNED_CRLF_PATHS:
        _assert_effective_checkout_eol(relative, "crlf")
        payload = (ROOT / relative).read_bytes()
        assert b"\r\n" in payload
        if relative in MIXED_EOL_PATHS:
            assert b"\n" in payload.replace(b"\r\n", b"")
        else:
            assert b"\n" not in payload.replace(b"\r\n", b"")
        if relative in authority_bindings:
            expected_bytes, expected_sha256 = authority_bindings[relative]
            assert len(payload) == expected_bytes
            assert _sha(payload) == expected_sha256


@pytest.fixture(scope="module")
def athanasius_candidate(tmp_path_factory: pytest.TempPathFactory):
    source = SourceManifest.load(SOURCE_MANIFEST, repository_root=ROOT)
    candidate = reconstruct(
        source,
        tmp_path_factory.mktemp("athanasius-table") / "candidate",
        _convert,
    )
    report = validate(source, candidate, _oracle)
    return source, candidate, report


def _resealed_copy(candidate: CandidatePackage, destination: Path) -> Path:
    shutil.copytree(candidate.path, destination)
    return destination


def _reseal_member(path: Path, name: str) -> CandidatePackage:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    content = (path / name).read_bytes()
    member = next(item for item in manifest["members"] if item["name"] == name)
    member.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _write_xml(path: Path, root: etree._Element) -> None:
    path.write_bytes(
        etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=False,
        )
    )


def test_retained_npnf204_authority_and_scope_are_exact() -> None:
    content = SOURCE.read_bytes()
    tree = etree.fromstring(
        content,
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    body = tree.find("ThML.body")
    assert body is not None
    divisions = [child for child in body if child.tag == "div1"]
    selected = divisions[5:25]
    features = [node for division in selected for node in division.iter()]

    assert len(content) == 5_809_854
    assert _sha(content) == SOURCE_SHA256
    assert [division.get("id") for division in divisions] == EXPECTED_DIVISIONS
    assert [division.get("id") for division in selected] == [
        scope for scope, _ in ASSIGNED
    ]
    assert len(features) == 26_890
    assert sum(len(node.attrib) for node in features) == 57_398
    assert not any(
        isinstance(node, (etree._Comment, etree._ProcessingInstruction))
        for node in features
    )
    assert sum(node.tag == "table" for node in features) == 6
    assert sum(node.tag == "tr" for node in features) == 180
    assert sum(node.tag == "td" for node in features) == 966


@pytest.mark.slow
def test_candidate_is_complete_nonaccepted_source_bound_and_reviewable(
    athanasius_candidate,
) -> None:
    source, candidate, report = athanasius_candidate
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    unresolved = [
        json.loads(line)
        for line in candidate.member_bytes("unresolved.jsonl").splitlines()
    ]

    assert set(candidate.member_names) == EXPECTED_MEMBERS
    assert candidate.manifest["status"] == "nonaccepted"
    assert accountability["assigned_work_count"] == 20
    assert accountability["feature_count"] == 26_890
    assert accountability["attribute_count"] == 57_398
    assert len(accountability["crosswalk"]) == 26_890
    assert accountability["omitted_feature_count"] == 0
    assert accountability["duplicate_feature_count"] == 0
    assert accountability["unresolved_feature_count"] == 0
    assert accountability["table_census"] == {
        "tables": 6,
        "rows": 180,
        "cells": 966,
    }
    assert accountability["preserved_table_route"] == {
        "div1_id": "vii",
        "feature_count": 1241,
        "table_id": "vii.i-p19.1",
        "tables": 1,
        "rows": 55,
        "cells": 165,
    }
    assert [work["work_id"] for work in provenance["works"]] == [
        work_id for _, work_id in ASSIGNED
    ]
    assert all(work["accepted_ir"] == "not_accepted" for work in provenance["works"])
    assert all(work["human_review"] == "required" for work in provenance["works"])
    assert all(work["publication"] == "not_ready" for work in provenance["works"])
    assert [item["id"] for item in unresolved] == [
        "npnf204-work-specific-translation-allocation",
        "npnf204-print-collation-not-performed",
        "npnf204-rights-human-acceptance-and-publication",
    ]
    assert report.status == "pass"
    review = prepare_review(source, candidate, report)
    assert review.candidate_sha256 == candidate.sha256
    assert review.source_manifest.authority_path("retained-thml").samefile(SOURCE)


@pytest.mark.slow
def test_all_retained_divisions_and_twenty_work_bindings_are_accounted(
    athanasius_candidate,
) -> None:
    _, candidate, _ = athanasius_candidate
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    divisions = accountability["division_accounting"]

    assert [item["div1_id"] for item in divisions] == EXPECTED_DIVISIONS
    assert [
        item["div1_id"]
        for item in divisions
        if item["disposition"] == "outside-assigned-work-scope"
    ] == ["i", "ii", "iii", "iv", "v", "xxvi"]
    assert [
        (item["div1_id"], item["work_id"])
        for item in divisions
        if item["disposition"] == "assigned-work-represented"
    ] == list(ASSIGNED)


@pytest.mark.slow
def test_retained_attributions_are_exact_and_not_inferred(
    athanasius_candidate,
) -> None:
    _, candidate, _ = athanasius_candidate
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    works = {item["div1_id"]: item for item in provenance["works"]}
    assert provenance["edition"]["editorial_supervision"] == [
        "Philip Schaff",
        "Henry Wace",
    ]
    assert provenance["edition"]["special_editor"] == "Archibald Robertson"
    assert works["xvi"]["translation_credit"] == {
        "status": "retained-explicit",
        "credited_to": "H. Ellershaw",
        "role": "translator",
        "source_xml_ids": ["iv-p11", "xvi.ii.i-p50"],
    }
    assert works["xxii"]["translation_credit"]["credited_to"] == "John Henry Newman"
    assert works["xxiii"]["translation_credit"]["credited_to"] is None
    assert works["xxiv"]["translation_credit"]["credited_to"] is None
    assert works["xxv"]["translation_credit"]["credited_to"] == "Miss Payne Smith"
    assert works["vi"]["translation_credit"]["status"] == "unresolved"
    assert (
        "sourced via [CCEL.org]" in candidate.member_bytes("README.source.md").decode()
    )


@pytest.mark.slow
@pytest.mark.parametrize(
    "mutation",
    [
        "missing-declaration",
        "standalone-declaration",
        "doctype",
        "pre-root-comment",
        "post-root-comment",
    ],
)
def test_oracle_rejects_document_prolog_and_root_sibling_drift(
    athanasius_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate, _ = athanasius_candidate
    target = _resealed_copy(candidate, tmp_path / mutation)
    name = "content.tei.xml"
    content = (target / name).read_bytes()
    declaration, document = content.split(b"\n", 1)
    if mutation == "missing-declaration":
        content = document
    elif mutation == "standalone-declaration":
        content = declaration[:-2] + b" standalone='yes'?>\n" + document
    elif mutation == "doctype":
        content = declaration + b"\n<!DOCTYPE TEI>\n" + document
    elif mutation == "pre-root-comment":
        content = declaration + b"\n<!-- invented -->\n" + document
    else:
        content = content + b"<!-- invented -->\n"
    (target / name).write_bytes(content)
    mutated = _reseal_member(target, name)
    with pytest.raises(ValueError, match="prolog drift|sibling drift"):
        validate(source, mutated, _oracle)


@pytest.mark.slow
@pytest.mark.parametrize(
    "mutation",
    ["extra-header", "extra-wrapper", "body-comment", "extra-namespace"],
)
def test_oracle_rejects_header_body_and_namespace_invention(
    athanasius_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate, _ = athanasius_candidate
    target = _resealed_copy(candidate, tmp_path / mutation)
    name = "content.tei.xml"
    tree = etree.fromstring((target / name).read_bytes())
    ns = f"{{{TEI_NS}}}"
    if mutation == "extra-header":
        title_stmt = tree.find(f".//{ns}titleStmt")
        assert title_stmt is not None
        title_stmt.append(etree.Element(f"{ns}author"))
    elif mutation == "extra-wrapper":
        body = tree.find(f".//{ns}body")
        assert body is not None
        body.append(etree.Element(f"{ns}seg", type="invented"))
    elif mutation == "body-comment":
        body = tree.find(f".//{ns}body")
        assert body is not None
        body.append(etree.Comment("invented"))
    else:
        tree.set("{urn:invented}claim", "invented")
    _write_xml(target / name, tree)
    mutated = _reseal_member(target, name)
    with pytest.raises(ValueError):
        validate(source, mutated, _oracle)


@pytest.mark.slow
@pytest.mark.parametrize(
    "mutation",
    [
        "front",
        "back",
        "stand-off",
        "tei-attribute",
        "text-attribute",
        "tei-text",
        "header-tail",
        "text-text",
        "body-tail",
        "tei-child-order",
        "text-child-order",
    ],
)
def test_oracle_rejects_complete_tei_and_text_container_drift(
    athanasius_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate, _ = athanasius_candidate
    target = _resealed_copy(candidate, tmp_path / mutation)
    name = "content.tei.xml"
    tree = etree.fromstring((target / name).read_bytes())
    ns = f"{{{TEI_NS}}}"
    header = tree.find(f"{ns}teiHeader")
    text = tree.find(f"{ns}text")
    assert header is not None
    assert text is not None
    body = text.find(f"{ns}body")
    assert body is not None

    if mutation in {"front", "back"}:
        container = etree.Element(f"{ns}{mutation}")
        division = etree.SubElement(container, f"{ns}div")
        etree.SubElement(division, f"{ns}p").text = "INVENTED REVIEW TEXT"
        if mutation == "front":
            text.insert(0, container)
        else:
            text.append(container)
    elif mutation == "stand-off":
        stand_off = etree.SubElement(tree, f"{ns}standOff")
        annotations = etree.SubElement(stand_off, f"{ns}listAnnotation")
        etree.SubElement(annotations, f"{ns}annotation")
    elif mutation == "tei-attribute":
        tree.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
    elif mutation == "text-attribute":
        text.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
    elif mutation == "tei-text":
        tree.text = "\n"
    elif mutation == "header-tail":
        header.tail = "\n"
    elif mutation == "text-text":
        text.text = "\n"
    elif mutation == "body-tail":
        body.tail = "\n"
    elif mutation == "tei-child-order":
        tree.remove(text)
        tree.insert(0, text)
    else:
        back = etree.SubElement(text, f"{ns}back")
        division = etree.SubElement(back, f"{ns}div")
        etree.SubElement(division, f"{ns}p").text = "INVENTED REVIEW TEXT"
        text.remove(body)
        text.append(body)

    _write_xml(target / name, tree)
    mutated = _reseal_member(target, name)
    with pytest.raises(ValueError):
        validate(source, mutated, _oracle)


@pytest.mark.slow
@pytest.mark.parametrize(
    "mutation",
    [
        "work-omission",
        "work-duplication",
        "work-reorder",
        "direct-text",
        "tail-text",
        "source-attribute",
        "division-title",
    ],
)
def test_oracle_rejects_source_text_structure_order_and_attribute_drift(
    athanasius_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate, _ = athanasius_candidate
    target = _resealed_copy(candidate, tmp_path / mutation)
    name = "content.tei.xml"
    tree = etree.fromstring((target / name).read_bytes())
    ns = f"{{{TEI_NS}}}"
    body = tree.find(f".//{ns}body")
    assert body is not None
    if mutation == "work-omission":
        body.remove(body[-1])
    elif mutation == "work-duplication":
        body.append(etree.fromstring(etree.tostring(body[-1])))
    elif mutation == "work-reorder":
        first, second = body[0], body[1]
        body.remove(second)
        body.insert(0, second)
        assert body[1] is first
    elif mutation == "direct-text":
        paragraph = next(node for node in tree.iter(f"{ns}p") if node.text)
        paragraph.text = "Invented" + paragraph.text
    elif mutation == "tail-text":
        node = next(node for node in tree.iter() if node.tail)
        node.tail = node.tail + "Invented"
    elif mutation == "source-attribute":
        reference = tree.find(f".//{ns}ref[@cRef]")
        assert reference is not None
        reference.set("cRef", "Invented.999")
    else:
        heading = tree.find(f".//{ns}body/{ns}div/{ns}head")
        assert heading is not None
        heading.text = "Invented division title"
    _write_xml(target / name, tree)
    mutated = _reseal_member(target, name)
    with pytest.raises(ValueError):
        validate(source, mutated, _oracle)


@pytest.mark.slow
@pytest.mark.parametrize(
    "mutation",
    [
        "crosswalk-omission",
        "crosswalk-duplication",
        "crosswalk-reorder",
        "crosswalk-invention",
        "source-stale",
        "division-stale",
        "work-stale",
        "table-stale",
    ],
)
def test_oracle_rejects_accounting_omission_duplication_reorder_and_staleness(
    athanasius_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate, _ = athanasius_candidate
    target = _resealed_copy(candidate, tmp_path / mutation)
    name = "source-accountability.json"
    record = json.loads((target / name).read_bytes())
    if mutation == "crosswalk-omission":
        record["crosswalk"].pop()
    elif mutation == "crosswalk-duplication":
        record["crosswalk"][-1] = record["crosswalk"][-2]
    elif mutation == "crosswalk-reorder":
        record["crosswalk"][20], record["crosswalk"][21] = (
            record["crosswalk"][21],
            record["crosswalk"][20],
        )
    elif mutation == "crosswalk-invention":
        record["crosswalk"].append(dict(record["crosswalk"][-1]))
    elif mutation == "source-stale":
        record["source_member"]["sha256"] = "0" * 64
    elif mutation == "division-stale":
        record["division_accounting"][0]["disposition"] = "assigned-work-represented"
    elif mutation == "work-stale":
        record["division_accounting"][5]["work_id"] = "invented-work"
    else:
        record["table_census"]["rows"] = 179
    (target / name).write_bytes(_canonical(record))
    mutated = _reseal_member(target, name)
    with pytest.raises(ValueError):
        validate(source, mutated, _oracle)


@pytest.mark.slow
@pytest.mark.parametrize(
    "mutation",
    ["credit", "rights", "work-state", "unresolved-order", "readme"],
)
def test_oracle_rejects_metadata_rights_state_and_review_evidence_drift(
    athanasius_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate, _ = athanasius_candidate
    target = _resealed_copy(candidate, tmp_path / mutation)
    if mutation in {"credit", "rights", "work-state"}:
        name = "provenance.json"
        record = json.loads((target / name).read_bytes())
        if mutation == "credit":
            record["works"][0]["translation_credit"]["credited_to"] = "Invented"
        elif mutation == "rights":
            record["rights"]["human_acceptance"] = "accepted"
        else:
            record["works"][0]["publication"] = "ready"
        (target / name).write_bytes(_canonical(record))
    elif mutation == "unresolved-order":
        name = "unresolved.jsonl"
        lines = (target / name).read_bytes().splitlines(keepends=True)
        (target / name).write_bytes(lines[1] + lines[0] + b"".join(lines[2:]))
    else:
        name = "README.source.md"
        (target / name).write_bytes(
            candidate.member_bytes(name).replace(
                b"sourced via [CCEL.org]", b"source omitted"
            )
        )
    mutated = _reseal_member(target, name)
    with pytest.raises(ValueError):
        validate(source, mutated, _oracle)


@pytest.mark.slow
def test_oracle_rejects_weakened_candidate_authority(
    athanasius_candidate,
    tmp_path: Path,
) -> None:
    source, candidate, _ = athanasius_candidate
    target = _resealed_copy(candidate, tmp_path / "weakened-authority")
    manifest = json.loads((target / "manifest.json").read_bytes())
    manifest["source_manifest"]["sha256"] = "0" * 64
    (target / "manifest.json").write_bytes(_canonical(manifest))
    mutated = CandidatePackage.load(target)
    with pytest.raises(
        ValueError, match="^candidate source manifest binding mismatch$"
    ):
        validate(source, mutated, _oracle)


@pytest.mark.slow
def test_runtime_is_producer_independent_and_has_no_old_campaign_imports(
    athanasius_candidate,
) -> None:
    _, _, report = athanasius_candidate
    for path in (
        ROOT / "build/tei/athanasius_table_reconstruction.py",
        ROOT / "build/tei/athanasius_table_oracle.py",
    ):
        content = path.read_text(encoding="utf-8")
        assert "build.reconstruction" not in content
        assert "case_declaration" not in content
        assert "reconstruction.persistence" not in content
        assert "reconstruction.wave" not in content
        assert "reports/adaptive-reconstruction-waves" not in content
    oracle_source = (ROOT / "build/tei/athanasius_table_oracle.py").read_text(
        encoding="utf-8"
    )
    assert "athanasius_table_reconstruction" not in oracle_source
    assert "build.tei.thml" not in oracle_source
    assert "__import__(" not in oracle_source
    assert len(report.attestation["import_closure_sha256"]) == 64


def test_oracle_import_closure_covers_every_executed_first_party_module() -> None:
    policy_path = (
        ROOT
        / "sources/structured-text/athanasius-on-the-incarnation"
        / "athanasius-table.validation-policy.json"
    )
    policy = json.loads(policy_path.read_bytes())
    records = [
        {"path": relative, "sha256": _sha((ROOT / relative).read_bytes())}
        for relative in EXPECTED_ORACLE_IMPORT_CLOSURE
    ]
    assert _closure_digest(ROOT, policy) == _sha(_canonical(records))

    code = (
        "import json,pathlib,sys; "
        f"r=pathlib.Path({str(ROOT)!r}).resolve(); "
        "import build.tei.athanasius_table_oracle; "
        "paths=sorted({pathlib.Path(m.__file__).resolve().relative_to(r).as_posix() "
        "for m in sys.modules.values() if getattr(m,'__file__',None) "
        "and pathlib.Path(m.__file__).resolve().is_relative_to(r)}); "
        "print(json.dumps(paths))"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONHASHSEED": "731"},
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert tuple(json.loads(result.stdout)) == EXPECTED_ORACLE_IMPORT_CLOSURE


@pytest.mark.parametrize(
    ("source", "match"),
    [
        (
            "import build.tei.athanasius_table_reconstruction\n",
            "forbidden import",
        ),
        (
            "import importlib\nimportlib.import_module('arbitrary.module')\n",
            "dynamic import or execution",
        ),
    ],
)
def test_oracle_import_closure_rejects_forbidden_and_dynamic_imports(
    tmp_path: Path,
    source: str,
    match: str,
) -> None:
    oracle_path = tmp_path / "build/tei/athanasius_table_oracle.py"
    oracle_path.parent.mkdir(parents=True)
    oracle_path.write_text(source, encoding="utf-8")
    policy = {"forbidden_oracle_imports": ["build.tei.athanasius_table_reconstruction"]}
    with pytest.raises(ValueError, match=match):
        _closure_digest(tmp_path, policy)


@pytest.mark.slow
def test_candidate_is_byte_identical_across_fresh_processes(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    other_cwd = tmp_path / "fresh-cwd"
    other_cwd.mkdir()
    code = (
        "from pathlib import Path; "
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct; "
        "from build.tei.athanasius_table_reconstruction import _convert; "
        f"r=Path({str(ROOT)!r}); "
        f"s=SourceManifest.load(r/{str(SOURCE_MANIFEST.relative_to(ROOT))!r},repository_root=r); "
        "reconstruct(s,Path(__import__('sys').argv[1]),_convert)"
    )
    environments = []
    for seed in ("17", "90210"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONPATH"] = str(ROOT)
        environments.append(environment)
    subprocess.run(
        [sys.executable, "-c", code, str(first)],
        cwd=ROOT,
        env=environments[0],
        check=True,
        timeout=120,
    )
    subprocess.run(
        [sys.executable, "-c", code, str(second)],
        cwd=other_cwd,
        env=environments[1],
        check=True,
        timeout=120,
    )
    first_paths = {
        path.relative_to(first).as_posix(): path.read_bytes()
        for path in sorted(first.rglob("*"))
        if path.is_file()
    }
    second_paths = {
        path.relative_to(second).as_posix(): path.read_bytes()
        for path in sorted(second.rglob("*"))
        if path.is_file()
    }
    assert first_paths == second_paths
