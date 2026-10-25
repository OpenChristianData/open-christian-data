"""Focused LIB-042 route, accounting, mutation, and reproduction gates."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.npnf109_chrysostom_oracle import _oracle
from build.tei.npnf109_chrysostom_reconstruction import _convert
from build.tools.count_dataset_records import collect_work_catalog
from build.tools import verify_whole_library_ticket_maps as map_verifier
from tests.runtime_candidate_baselines import current_runtime_catalog

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
ROUTE = ROOT / "sources/structured-text/chrysostom-npnf109-16"
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/npnf109-chrysostom.source-manifest.json'
TEI_XSD = ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"
TEI_NS = "http://www.tei-c.org/ns/1.0"
ASSIGNED_DIV1 = (
    "iv", "v", "vi", "vii", "viii", "ix", "x", "xi",
    "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix",
)
WORK_IDS = (
    "chrysostom-correspondence-with-rome",
    "chrysostom-exhortation-to-theodore",
    "chrysostom-homilies-ignatius-and-babylas",
    "chrysostom-homilies-on-the-statues",
    "chrysostom-homily-against-publishing-errors",
    "chrysostom-homily-on-father-if-it-be-possible",
    "chrysostom-homily-on-lowliness-of-mind",
    "chrysostom-homily-on-the-paralytic",
    "chrysostom-homily-to-those-not-attended-assembly",
    "chrysostom-instructions-to-catechumens",
    "chrysostom-letter-to-young-widow",
    "chrysostom-letters-to-olympias",
    "chrysostom-no-one-can-be-harmed",
    "chrysostom-on-the-priesthood",
    "chrysostom-three-homilies-on-power-of-demons",
    "chrysostom-two-homilies-on-eutropius",
)
EXPECTED_CENSUS = {
    "elements": 7723,
    "attributes": 19877,
    "text_nodes": 5200,
    "tail_nodes": 5528,
    "characters": 2021867,
    "non_ascii_characters": 12334,
}
EXPECTED_TAG_COUNTS = {
    "br": 3,
    "div1": 16,
    "div2": 82,
    "i": 491,
    "note": 1832,
    "p": 3022,
    "pb": 427,
    "scripCom": 1,
    "scripRef": 1281,
    "span": 568,
}


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def validation_bytes(report: object) -> bytes:
    return canonical(
        {
            "contract": "ocd-validation-report-v1",
            "status": report.status,
            "candidate_sha256": report.candidate_sha256,
            "source_manifest_sha256": report.source_manifest_sha256,
            "attestation": dict(report.attestation),
            "findings": list(report.findings),
            "report_sha256": report.sha256,
        }
    )


@pytest.fixture(scope="module")
def verified_candidate(tmp_path_factory: pytest.TempPathFactory):
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate_path = tmp_path_factory.mktemp("lib042-candidate") / "package"
    candidate = reconstruct(source, candidate_path, _convert)
    report = validate(source, candidate, _oracle)
    assert report.status == "pass"
    validation_path = candidate_path.parent / "validation.json"
    validation_path.write_bytes(validation_bytes(report))
    return source, candidate, report, validation_path


def _parsed(candidate: CandidatePackage) -> etree._ElementTree:
    return etree.fromstring(
        candidate.member_bytes("content.tei.xml"),
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    ).getroottree()


def _reseal(candidate_path: Path, member_name: str) -> None:
    manifest_path = candidate_path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    content = (candidate_path / member_name).read_bytes()
    row = next(item for item in manifest["members"] if item["name"] == member_name)
    row["bytes"] = len(content)
    row["sha256"] = hashlib.sha256(content).hexdigest()
    manifest_path.write_bytes(canonical(manifest))


def _copy_candidate(source: CandidatePackage, destination: Path) -> CandidatePackage:
    destination.mkdir()
    for member in source.path.iterdir():
        (destination / member.name).write_bytes(member.read_bytes())
    return CandidatePackage.load(destination)


def _leaf_p_span(content: bytes) -> tuple[int, int, int, int]:
    tree = etree.fromstring(
        content,
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    ).getroottree()
    ns = {"tei": TEI_NS}
    xml_id = "{http://www.w3.org/XML/1998/namespace}id"
    node = next(
        item
        for item in tree.xpath("/tei:TEI/tei:text/tei:body//tei:p", namespaces=ns)
        if item.text and len(item) == 0
    )
    identifier = node.get(xml_id)
    assert identifier is not None
    opening = f'<p xml:id="{identifier}"'.encode("utf-8")
    start = content.find(opening)
    assert start >= 0
    open_end = content.find(b">", start) + 1
    close = content.find(b"</p>", open_end)
    assert open_end > start and close >= open_end
    return start, close + len(b"</p>"), open_end, close


def _leaf_feature_span(content: bytes, localname: str) -> tuple[int, int]:
    tree = etree.fromstring(
        content,
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    ).getroottree()
    ns = {"tei": TEI_NS}
    xml_id = "{http://www.w3.org/XML/1998/namespace}id"
    node = next(
        item
        for item in tree.xpath("/tei:TEI/tei:text/tei:body//*", namespaces=ns)
        if etree.QName(item).localname == localname
        and item.text
        and not item.tail
        and len(item) == 0
    )
    identifier = node.get(xml_id)
    assert identifier is not None
    opening = f'<{localname} xml:id="{identifier}"'.encode("utf-8")
    start = content.find(opening)
    assert start >= 0
    open_end = content.find(b">", start) + 1
    close_marker = f"</{localname}>".encode("utf-8")
    close = content.find(close_marker, open_end)
    assert open_end > start and close >= open_end
    return start, close + len(close_marker)


def _div_span(content: bytes, identifier: str) -> tuple[int, int]:
    opening = f'<div xml:id="{identifier}"'.encode("utf-8")
    start = content.find(opening)
    assert start >= 0
    depth = 0
    token_pattern = re.compile(rb"<div\b[^>]*>|</div\s*>")
    for match in token_pattern.finditer(content, start):
        token = match.group(0)
        if token.startswith(b"</"):
            depth -= 1
            if depth == 0:
                return start, match.end()
        elif not token.rstrip().endswith(b"/>"):
            depth += 1
    raise AssertionError(f"unclosed div {identifier}")


def _write_content(candidate_path: Path, content: bytes) -> None:
    (candidate_path / "content.tei.xml").write_bytes(content)
    _reseal(candidate_path, "content.tei.xml")


def _independent_source_census(source: SourceManifest) -> tuple[dict[str, int], Counter[str]]:
    content = source.authority_path("npnf109-retained-xml").read_bytes()
    assert len(content) == 3017592
    assert hashlib.sha256(content).hexdigest() == (
        "6d0887393b4d197d7784cbea989aeb422d7e38f55711b4c4d4af85e3de680175"
    )
    tree = etree.fromstring(
        content,
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            remove_pis=False,
            huge_tree=True,
        ),
    ).getroottree()
    body = tree.getroot().find("ThML.body")
    assert body is not None
    top = [node for node in body if isinstance(node.tag, str) and node.tag == "div1"]
    assert [node.get("id") for node in top] == [
        "i", "ii", "iii", *ASSIGNED_DIV1, "xx", "xxi"
    ]
    selected = [node for node in top if node.get("id") in set(ASSIGNED_DIV1)]
    nodes = [node for division in selected for node in division.iter() if isinstance(node.tag, str)]
    census = {
        "elements": len(nodes),
        "attributes": sum(len(node.attrib) for node in nodes),
        "text_nodes": sum(node.text is not None for node in nodes),
        "tail_nodes": sum(node.tail is not None for node in nodes),
        "characters": sum(len((node.text or "") + (node.tail or "")) for node in nodes),
        "non_ascii_characters": sum(
            sum(ord(char) > 127 for char in (node.text or "") + (node.tail or ""))
            for node in nodes
        ),
    }
    return census, Counter(str(node.tag) for node in nodes)


def test_current_manifest_binds_one_member_and_all_sixteen_configs() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    assert source.record["source_id"] == "LIB-042"
    primary = [row for row in source.record["authorities"] if row["role"] == "primary-source"]
    assert [(row["name"], row["bytes"], row["sha256"]) for row in primary] == [
        (
            "npnf109-retained-xml",
            3017592,
            "6d0887393b4d197d7784cbea989aeb422d7e38f55711b4c4d4af85e3de680175",
        )
    ]
    config_rows = [row for row in source.record["authorities"] if row["role"] == "source-config"]
    assert len(config_rows) == 16
    assert {Path(row["path"]).parent.name for row in config_rows} == set(WORK_IDS)


def test_independent_source_accounting_covers_all_assigned_roots() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    census, tags = _independent_source_census(source)
    assert census == EXPECTED_CENSUS
    assert dict(sorted(tags.items())) == EXPECTED_TAG_COUNTS


def test_candidate_schema_and_independent_oracle_pass(verified_candidate) -> None:
    source, candidate, report, _ = verified_candidate
    assert candidate.manifest["source_id"] == "LIB-042"
    assert candidate.manifest["source_manifest"]["sha256"] == source.sha256
    tree = _parsed(candidate)
    schema = etree.XMLSchema(etree.parse(str(TEI_XSD)))
    assert schema.validate(tree), schema.error_log
    ns = {"tei": TEI_NS}
    roots = tree.xpath("/tei:TEI/tei:text/tei:body/tei:div", namespaces=ns)
    assert len(roots) == 16
    assert [root.get("corresp").split(":", 2)[1] for root in roots] == list(ASSIGNED_DIV1)
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["assigned_work_count"] == 16
    assert accountability["feature_count"] == 7723
    assert accountability["omitted_feature_count"] == 0
    assert accountability["duplicate_feature_count"] == 0
    assert accountability["unresolved_feature_count"] == 0
    assert report.attestation["source_sha256"] == (
        "6d0887393b4d197d7784cbea989aeb422d7e38f55711b4c4d4af85e3de680175"
    )


def test_oracle_rejects_wrong_root_loaded_kernel(verified_candidate, tmp_path: Path, monkeypatch) -> None:
    source, candidate, _, _ = verified_candidate
    module = sys.modules["ocd_kernel.reconstruction.contract"]
    original = Path(str(module.__file__)).resolve(strict=True)
    wrong_root = tmp_path / "wrong-root-contract.py"
    wrong_root.write_bytes(original.read_bytes())
    monkeypatch.setattr(module, "__file__", str(wrong_root))
    with pytest.raises(ValueError, match="loaded from the wrong root"):
        _oracle(source, candidate)


@pytest.mark.parametrize("mutation", ("omission", "direct-text", "rights", "coverage"))
def test_resealed_mutations_are_rejected(verified_candidate, tmp_path: Path, mutation: str) -> None:
    source, candidate, _, _ = verified_candidate
    path = tmp_path / mutation
    mutant = _copy_candidate(candidate, path)
    if mutation == "omission":
        content = (path / "content.tei.xml").read_bytes()
        start, end = _leaf_feature_span(content, "seg")
        _write_content(path, content[:start] + content[end:])
    elif mutation == "direct-text":
        content = (path / "content.tei.xml").read_bytes()
        _, _, text_start, text_end = _leaf_p_span(content)
        _write_content(path, content[:text_end] + b" INVENTED" + content[text_end:])
    elif mutation == "rights":
        provenance = json.loads((path / "provenance.json").read_bytes())
        provenance["rights"]["ccel_formatting_condition"] = "Unrestricted commercial sale."
        (path / "provenance.json").write_bytes(canonical(provenance))
        _reseal(path, "provenance.json")
    else:
        accountability = json.loads((path / "source-accountability.json").read_bytes())
        accountability["source_census"]["assigned_scope"]["elements"] = 0
        (path / "source-accountability.json").write_bytes(canonical(accountability))
        _reseal(path, "source-accountability.json")
    mutant = CandidatePackage.load(path)
    expected_messages = {
        "omission": "candidate feature omission/duplication",
        "direct-text": "candidate direct text drift",
        "rights": "candidate complete provenance/rights/credit nested-structure drift",
        "coverage": "candidate complete accountability nested-structure drift",
    }
    with pytest.raises(ValueError, match=expected_messages[mutation]):
        validate(source, mutant, _oracle)


def test_remaining_policy_mutations_are_rejected(verified_candidate, tmp_path: Path) -> None:
    source, candidate, _, _ = verified_candidate
    ns = {"tei": TEI_NS}
    xml_id = "{http://www.w3.org/XML/1998/namespace}id"

    cases: list[tuple[str, str]] = [
        ("duplication", "candidate feature order/count drift"),
        ("reordering", "candidate feature order/count drift"),
        ("invention", "candidate source-root count drift"),
        ("tail-text", "candidate tail drift"),
        ("attribute", "candidate attributes drift"),
        ("metadata", "candidate retained metadata/header drift"),
        ("wrong-source", "candidate complete provenance/rights/credit nested-structure drift"),
        ("stale-binding", "^candidate source manifest binding mismatch$"),
        ("namespace", "candidate namespace declaration topology drift"),
        ("shell", "candidate XML shell invention"),
        ("p5-invalid", "candidate TEI P5 schema invalid"),
    ]
    for label, expected_message in cases:
        path = tmp_path / label
        mutant = _copy_candidate(candidate, path)
        if label in {
            "duplication", "reordering", "invention", "tail-text",
            "attribute", "metadata", "namespace", "shell", "p5-invalid",
        }:
            content = (path / "content.tei.xml").read_bytes()
            if label == "duplication":
                start, end, _, _ = _leaf_p_span(content)
                block = content[start:end]
                match = re.search(rb'xml:id="[^"]+"', block)
                assert match is not None
                duplicate = block[:match.start()] + b'xml:id="lib042-duplicate"' + block[match.end():]
                next_tag = content.find(b"<", end)
                assert next_tag >= end
                tail = content[end:next_tag]
                content = content[:end] + tail + duplicate + tail + content[next_tag:]
            elif label == "reordering":
                first_start, first_end = _div_span(content, "npnf109-iv")
                second_start, second_end = _div_span(content, "npnf109-v")
                assert first_end <= second_start
                content = (
                    content[:first_start]
                    + content[second_start:second_end]
                    + content[first_end:second_start]
                    + content[first_start:first_end]
                    + content[second_end:]
                )
            elif label == "invention":
                marker = b"</body>"
                position = content.find(marker)
                assert position >= 0
                invented = b'<div xml:id="lib042-invented" type="invented"><p>Invented content</p></div>'
                content = content[:position] + invented + content[position:]
            elif label == "tail-text":
                tree = etree.fromstring(
                    content,
                    etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
                ).getroottree()
                tail_node = next(
                    node
                    for node in tree.xpath("/tei:TEI/tei:text/tei:body//*", namespaces=ns)
                    if (node.tail or "").strip()
                    and len(node.tail or "") > 20
                    and etree.QName(node.getparent()).localname in {"p", "note", "hi", "seg", "ref"}
                )
                tail = (tail_node.tail or "").encode("utf-8")
                position = content.find(tail)
                assert position >= 0
                content = content[:position] + tail + b" INVENTED" + content[position + len(tail):]
            elif label == "attribute":
                assert b'rend="c29"' in content
                content = content.replace(b'rend="c29"', b'rend="invented"', 1)
            elif label == "metadata":
                start = content.find(b"<title>")
                end = content.find(b"</title>", start)
                assert start >= 0 and end > start
                content = content[:end] + b" invented" + content[end:]
            elif label == "namespace":
                assert b"<p xml:id=" in content
                content = content.replace(
                    b"<p xml:id=",
                    b'<p xmlns="http://www.tei-c.org/ns/1.0" xml:id=',
                    1,
                )
            elif label == "shell":
                assert b"?>" in content
                content = content.replace(b"?>", b"?><?lib042-invented?>", 1)
            elif label == "p5-invalid":
                assert b"<body " in content and b"</body>" in content
                content = content.replace(b"<body ", b"<bogus ", 1).replace(
                    b"</body>", b"</bogus>", 1
                )
            _write_content(path, content)
            mutant = CandidatePackage.load(path)
            with pytest.raises(ValueError, match=expected_message):
                validate(source, mutant, _oracle)
            continue
        if label in {"duplication", "reordering", "invention", "tail-text", "attribute", "metadata", "namespace", "shell", "p5-invalid"}:
            tree = _parsed(mutant)
            body = tree.xpath("/tei:TEI/tei:text/tei:body", namespaces=ns)[0]
            first_p = tree.xpath("/tei:TEI/tei:text/tei:body//tei:p", namespaces=ns)[0]
            if label == "duplication":
                duplicate = etree.fromstring(etree.tostring(first_p))
                for ordinal, node in enumerate(duplicate.iter(), start=1):
                    if node.get(xml_id):
                        node.set(xml_id, f"lib042-duplicate-{ordinal}")
                first_p.addnext(duplicate)
            elif label == "reordering":
                first, second = body[0], body[1]
                body.remove(second)
                body.insert(0, second)
                assert body[1] is first
            elif label == "invention":
                invented = etree.SubElement(body, f"{{{TEI_NS}}}div")
                invented.set(xml_id, "lib042-invented")
                invented.set("type", "invented")
                etree.SubElement(invented, f"{{{TEI_NS}}}p").text = "Invented content"
            elif label == "tail-text":
                tail_node = next(
                    node
                    for node in tree.xpath("/tei:TEI/tei:text/tei:body//*", namespaces=ns)
                    if (node.tail or "").strip()
                    and etree.QName(node.getparent()).localname in {"p", "note", "hi", "seg", "ref"}
                )
                tail_node.tail = (tail_node.tail or "") + " INVENTED"
            elif label == "attribute":
                first_p.set("rend", "invented")
            elif label == "metadata":
                title = tree.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=ns)[0]
                title.text = (title.text or "") + " invented"
            elif label == "namespace":
                content = (path / "content.tei.xml").read_bytes()
                assert b"<p xml:id=" in content
                (path / "content.tei.xml").write_bytes(
                    content.replace(b"<p xml:id=", b'<p xmlns="http://www.tei-c.org/ns/1.0" xml:id=', 1)
                )
                _reseal(path, "content.tei.xml")
                tree = None
            elif label == "shell":
                content = (path / "content.tei.xml").read_bytes()
                assert b"?>" in content
                (path / "content.tei.xml").write_bytes(content.replace(b"?>", b"?><?lib042-invented?>", 1))
                _reseal(path, "content.tei.xml")
                tree = None
            elif label == "p5-invalid":
                content = (path / "content.tei.xml").read_bytes()
                assert b"<body " in content and b"</body>" in content
                (path / "content.tei.xml").write_bytes(
                    content.replace(b"<body ", b"<bogus ", 1).replace(b"</body>", b"</bogus>", 1)
                )
                _reseal(path, "content.tei.xml")
                tree = None
            if tree is not None:
                (path / "content.tei.xml").write_bytes(
                    etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
                )
                _reseal(path, "content.tei.xml")
        elif label == "wrong-source":
            provenance = json.loads((path / "provenance.json").read_bytes())
            provenance["sources"][0]["path"] = "raw/ccel/npnf1/npnf108.xml"
            (path / "provenance.json").write_bytes(canonical(provenance))
            _reseal(path, "provenance.json")
        else:
            manifest = json.loads((path / "manifest.json").read_bytes())
            manifest["source_manifest"]["sha256"] = "0" * 64
            (path / "manifest.json").write_bytes(canonical(manifest))
        mutant = CandidatePackage.load(path)
        with pytest.raises(ValueError, match=expected_message):
            validate(source, mutant, _oracle)

    surplus = tmp_path / "surplus-product"
    _copy_candidate(candidate, surplus)
    (surplus / "extra-product.xml").write_bytes(b"<invented/>")
    with pytest.raises(ValueError, match="exactly six flat members"):
        CandidatePackage.load(surplus)


def test_frozen_maps_and_workcatalog_bind_all_sixteen(verified_candidate) -> None:
    source, candidate, _, validation_path = verified_candidate
    work_rows = map_verifier.parse_work_ticket_map(map_verifier.DEFAULT_WORK_MAP)
    source_rows = map_verifier.parse_source_ticket_map(map_verifier.DEFAULT_SOURCE_MAP)
    assert len(work_rows) == 402
    assert len(source_rows) == 1045
    assigned = [row for row in work_rows if row["ticket"] == "LIB-042"]
    links = [row for row in source_rows if row["ticket"] == "LIB-042"]
    assert {row["work_id"] for row in assigned} == set(WORK_IDS)
    assert {row["work_id"] for row in links} == set(WORK_IDS)
    assert {row["digest"] for row in links} == {
        item["sha256"] for item in source.record["authorities"] if item["role"] == "primary-source"
    }
    evidence = {
        ("LIB-042", work_id): (candidate.path, validation_path)
        for work_id in WORK_IDS
    }
    catalog = current_runtime_catalog(
        root=ROOT, manifest=MANIFEST, work_ids=WORK_IDS, reconstruction_evidence=evidence)
    by_id = {work["work_id"]: work for work in catalog.works}
    for work_id in WORK_IDS:
        state = by_id[work_id]["reconstruction_state"]
        routes = [
            route for route in state["routes"] if route.get("source_id") == "LIB-042"
        ]
        assert len(routes) == 1
        assert routes[0]["association"] == "source_hash+exact_id"
        assert routes[0]["candidate_verification"] == "verified"
        assert state["tei_candidate"] == "verified"
        assert state["validation"] == "verified"


def test_two_fresh_processes_reproduce_complete_candidate(verified_candidate, tmp_path: Path) -> None:
    _, candidate, _, _ = verified_candidate
    outputs = []
    producer = ROOT / "build/tei/npnf109_chrysostom_reconstruction.py"
    for ordinal, seed in enumerate(("101", "907"), start=1):
        output = tmp_path / f"fresh-{ordinal}"
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = str(ROOT)
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(producer),
                "--repository-root",
                str(ROOT),
                "--source-manifest",
                str(MANIFEST),
                "--output-dir",
                str(output),
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        outputs.append(output)
    expected = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in candidate.path.iterdir()
    }
    for output in outputs:
        observed = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in output.iterdir()
        }
        assert observed == expected
