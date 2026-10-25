"""Focused source-binding, independent-check, and determinism tests for 37c-178."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from xml.parsers import expat

from lxml import etree
import pytest

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate
from build.tei.george_whitefield_sermons_reconstruction import (
    CONVERTER_ID,
    CONVERTER_VERSION,
    _convert,
    _producer_closure,
)
from build.tei.george_whitefield_sermons_oracle import _closure, _oracle


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    ROOT / 'tests/fixtures/reconstruction-runtime/george_whitefield_sermons_oracle.source-manifest.json'
)
CCEL_PATH = ROOT / "raw/ccel/whitefield_sermons.xml"
GUTENBERG_PATH = ROOT / "raw/gutenberg/sermons/whitefield/pg77041.txt"
CCEL_SHA256 = "cd839845e3e9198302f71bda313c72f5212eb1b7aa3409e6ae4318c13b9462ec"
GUTENBERG_SHA256 = "b952725e8731399d4fd7fbe319aa9f57660d887f7cc6dd3937da91754e4ce08e"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _source() -> SourceManifest:
    return SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)


@pytest.fixture(scope="module")
def candidate_evidence(tmp_path_factory: pytest.TempPathFactory):
    source = _source()
    destination = tmp_path_factory.mktemp("37c-178-whitefield-") / "candidate"
    with pytest.raises(ValueError):
        destination.resolve().relative_to(ROOT.resolve())
    candidate = reconstruct(source, destination, _convert)
    report = validate(source, candidate, _oracle)
    return source, candidate, report, destination


def test_manifest_binds_the_exact_retained_members_and_route_closure() -> None:
    source = _source()
    source.verify()
    authorities = {
        str(item["name"]): item for item in source.record["authorities"]
    }
    assert source.record["ticket_id"] == "LIB-060"
    assert source.record["work_id"] == "george-whitefield-sermons"
    assert source.record["retained_source_path"] == "raw/ccel/whitefield_sermons.xml"
    assert authorities["retained-ccel-xml"]["path"] == str(
        CCEL_PATH.relative_to(ROOT).as_posix()
    )
    assert authorities["retained-ccel-xml"]["bytes"] == 2_046_222
    assert authorities["retained-ccel-xml"]["sha256"] == CCEL_SHA256
    assert authorities["retained-project-gutenberg-text"]["path"] == str(
        GUTENBERG_PATH.relative_to(ROOT).as_posix()
    )
    assert authorities["retained-project-gutenberg-text"]["bytes"] == 896_665
    assert authorities["retained-project-gutenberg-text"]["sha256"] == GUTENBERG_SHA256
    assert _sha(CCEL_PATH.read_bytes()) == CCEL_SHA256
    assert _sha(GUTENBERG_PATH.read_bytes()) == GUTENBERG_SHA256
    assert source.record["converter"]["id"] == CONVERTER_ID
    assert source.record["converter"]["version"] == CONVERTER_VERSION
    assert source.record["converter"]["implementation_sha256"] == _sha(
        (ROOT / "build/tei/george_whitefield_sermons_reconstruction.py").read_bytes()
    )
    assert source.record["producer_import_closure_sha256"] == _producer_closure(ROOT)
    assert source.record["validator"]["implementation_sha256"] == _sha(
        (ROOT / "build/tei/george_whitefield_sermons_oracle.py").read_bytes()
    )
    assert source.record["validator"]["import_closure_sha256"] == _closure(ROOT)

    profile = json.loads(source.authority_path("reconstruction-profile").read_text("utf-8"))
    assert profile["identity"]["collection_boundary"] == "unresolved"
    assert profile["identity"]["edition_relationship"] == "unresolved"
    assert profile["identity"]["part_relationship"] == "unresolved"
    assert profile["identity"]["rights_status"] == "unresolved; no rights inquiry performed"
    assert profile["members"][0]["path"] == CCEL_PATH.relative_to(ROOT).as_posix()
    assert profile["members"][1]["path"] == GUTENBERG_PATH.relative_to(ROOT).as_posix()
    assert profile["members"][1]["selected_source_sermon_labels"] == ["LVIII", "LIX"]


def test_candidate_and_independent_accounting_cover_declared_scope(candidate_evidence) -> None:
    source, candidate, report, destination = candidate_evidence
    assert report.status == "pass"
    assert candidate.manifest["status"] == "nonaccepted"
    assert destination.is_dir()
    assert set(item.name for item in destination.iterdir()) == set(candidate.member_names)

    account = json.loads(candidate.member_bytes("source-accountability.json"))
    ccel = account["ccel"]
    pg = account["project_gutenberg"]
    assert ccel["path"] == "raw/ccel/whitefield_sermons.xml"
    assert ccel["sha256"] == CCEL_SHA256
    assert len(ccel["ordered_carriers"]) == 62
    assert [row["source_id"] for row in ccel["ordered_carriers"][:3]] == [
        "i",
        "ii",
        "iii",
    ]
    assert [row["source_id"] for row in ccel["ordered_carriers"][-3:]] == [
        "lx",
        "lxi",
        "lxii",
    ]
    assert sum(
        row["source_id"] in {
            "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii",
            "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx", "xxi", "xxii",
            "xxiii", "xxiv", "xxv", "xxvi", "xxvii", "xxviii", "xxix", "xxx", "xxxi", "xxxii",
            "xxxiii", "xxxiv", "xxxv", "xxxvi", "xxxvii", "xxxviii", "xxxix", "xl", "xli", "xlii",
            "xliii", "xliv", "xlv", "xlvi", "xlvii", "xlviii", "xlix", "l", "li", "lii",
            "liii", "liv", "lv", "lvi", "lvii", "lviii", "lix", "lx", "lxi",
        }
        for row in ccel["ordered_carriers"]
    ) == 59
    source_instructions: list[dict[str, str]] = []
    pi_parser = expat.ParserCreate()
    pi_parser.ProcessingInstructionHandler = lambda target, data: source_instructions.append(
        {"target": target, "data": data}
    )
    pi_parser.Parse(CCEL_PATH.read_bytes(), True)
    assert ccel["processing_instructions"] == source_instructions
    assert len(source_instructions) == 2
    assert len(ccel["comments"]) == 11
    assert ccel["comments"][0]["parent_tag"] is None
    assert ccel["comments"][0]["text"] == " Copyright Christian Classics Ethereal Library "
    assert len([row for row in ccel["comments"] if row["parent_tag"] is not None]) == 10
    source_prolog_events: list[dict[str, str]] = []
    root_started = False

    def mark_root(_name: str, _attributes: dict[str, str]) -> None:
        nonlocal root_started
        root_started = True

    def observe_pi(target: str, data: str) -> None:
        if not root_started:
            source_prolog_events.append(
                {"kind": "processing-instruction", "target": target, "data": data}
            )

    def observe_comment(text: str) -> None:
        if not root_started:
            source_prolog_events.append({"kind": "comment", "text": text})

    prolog_parser = expat.ParserCreate()
    prolog_parser.StartElementHandler = mark_root
    prolog_parser.ProcessingInstructionHandler = observe_pi
    prolog_parser.CommentHandler = observe_comment
    prolog_parser.Parse(CCEL_PATH.read_bytes(), True)
    assert ccel["prolog_events"] == [
        {"kind": "processing-instruction", **source_instructions[0]},
        {"kind": "processing-instruction", **source_instructions[1]},
        {"kind": "comment", "text": " Copyright Christian Classics Ethereal Library "},
    ]
    assert ccel["prolog_events"] == source_prolog_events

    assert pg["path"] == "raw/gutenberg/sermons/whitefield/pg77041.txt"
    assert pg["sha256"] == GUTENBERG_SHA256
    assert pg["physical_line_count"] == 14_698
    assert len(pg["line_inventory"]) == 14_698
    assert len(pg["sermon_carriers"]) == 28
    assert pg["selected_source_labels"] == ["LVIII", "LIX"]
    selected = [
        row for row in pg["sermon_carriers"] if row["disposition"] == "represented-source-native-carrier"
    ]
    excluded = [
        row for row in pg["sermon_carriers"] if row["disposition"] == "not-selected-by-current-work-specific-config"
    ]
    assert [row["source_label"] for row in selected] == ["LVIII", "LIX"]
    assert len(excluded) == 26
    assert all(row["exclusion_reason"] for row in excluded)
    assert account["candidate_scope"]["status"].startswith("provisional;")
    assert "collection" in " ".join(account["candidate_scope"]["unknowns"])

    ccel_titles = {
        row["source_id"]: row["source_title_observation"]
        for row in ccel["ordered_carriers"]
    }
    pg_titles = {row["source_label"]: row["title_observation"] for row in pg["sermon_carriers"]}
    assert "Peter" not in ccel_titles["lviii"]
    assert "Peter" in pg_titles["LVIII"]
    assert "LAMB" in pg_titles["LIX"]

    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert provenance["status"] == "nonaccepted"
    assert provenance["identity_status"]["collection_boundary"] == "unresolved"
    assert provenance["identity_status"]["edition_relationship"] == "unresolved"
    assert provenance["identity_status"]["part_relationship"] == "unresolved"
    assert provenance["rights_status"] == "not-reviewed"
    assert provenance["publication_status"] == "not-authorized"
    assert "canonical_data_or_ir_written" in provenance


def _reseal_package(path: Path, changed_member: str) -> CandidatePackage:
    record = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    content = (path / changed_member).read_bytes()
    for member in record["members"]:
        if member["name"] == changed_member:
            member["bytes"] = len(content)
            member["sha256"] = _sha(content)
            break
    else:
        raise AssertionError(f"candidate manifest did not list {changed_member}")
    (path / "manifest.json").write_bytes(_canonical_json(record))
    return CandidatePackage.load(path)


def test_independent_oracle_rejects_a_resealed_text_mutation(candidate_evidence, tmp_path: Path) -> None:
    source, _, _, original_path = candidate_evidence
    tampered_path = tmp_path / "tampered-candidate"
    shutil.copytree(original_path, tampered_path)
    content_path = tampered_path / "content.tei.xml"
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    tree = etree.parse(str(content_path), parser)
    namespaces = {"t": _TEI, "xml": "http://www.w3.org/XML/1998/namespace"}
    paragraph = tree.xpath(
        "/t:TEI/t:text/t:body/t:div[@xml:id='member-ccel-whitefield']"
        "/t:div[@xml:id='ccel-div1-iii']//t:p[1]",
        namespaces=namespaces,
    )
    assert len(paragraph) == 1
    source_text = next(text for text in paragraph[0].xpath(".//text()") if text.strip())
    text_parent = source_text.getparent()
    if source_text.is_text:
        text_parent.text = (text_parent.text or "") + " [mutated]"
    else:
        text_parent.tail = (text_parent.tail or "") + " [mutated]"
    content_path.write_bytes(
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    )
    tampered_candidate = _reseal_package(tampered_path, "content.tei.xml")
    with pytest.raises(ValueError, match="CCEL source attributes or text changed"):
        validate(source, tampered_candidate, _oracle)


def test_fresh_process_reconstruction_matches_every_candidate_byte(
    candidate_evidence, tmp_path: Path
) -> None:
    _, candidate, _, first_path = candidate_evidence
    second_path = tmp_path / "fresh-process-candidate"
    script = "\n".join(
        [
            "import hashlib, json, sys",
            "from pathlib import Path",
            "from ocd_kernel.reconstruction import SourceManifest, reconstruct, validate",
            "from build.tei.george_whitefield_sermons_reconstruction import _convert",
            "from build.tei.george_whitefield_sermons_oracle import _oracle",
            "root = Path(sys.argv[1])",
            "manifest_path = root / sys.argv[2]",
            "destination = Path(sys.argv[3])",
            "source = SourceManifest.load(manifest_path, repository_root=root)",
            "package = reconstruct(source, destination, _convert)",
            "report = validate(source, package, _oracle)",
            "members = {name: hashlib.sha256(package.member_bytes(name)).hexdigest() for name in package.member_names}",
            "print(json.dumps({'candidate_sha256': package.sha256, 'validation_status': report.status, 'members': members}, sort_keys=True))",
        ]
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            script,
            str(ROOT),
            MANIFEST_PATH.relative_to(ROOT).as_posix(),
            str(second_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    observed = json.loads(completed.stdout)
    expected_members = {
        name: _sha((first_path / name).read_bytes()) for name in candidate.member_names
    }
    assert observed["validation_status"] == "pass"
    assert observed["candidate_sha256"] == candidate.sha256
    assert observed["members"] == expected_members
    assert set(item.name for item in second_path.iterdir()) == set(candidate.member_names)


def test_oracle_does_not_import_or_call_the_converter() -> None:
    oracle_path = ROOT / "build/tei/george_whitefield_sermons_oracle.py"
    tree = ast.parse(oracle_path.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
    assert not any("george_whitefield_sermons_reconstruction" in name for name in imports)
    assert "_convert" not in {
        node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
