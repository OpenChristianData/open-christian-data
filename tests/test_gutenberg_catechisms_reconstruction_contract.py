from __future__ import annotations

import hashlib
import ast
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys

from jsonschema import Draft202012Validator
from lxml import etree
import pytest

from ocd_kernel.reconstruction.contract import CandidatePackage, validate


ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "baltimore-catechism-no-1": ("pg14551.txt", 92_039, "d4b49653b457cc11f39df004896d072892b534e49899def16cdd75761c80993e", 2_620),
    "baltimore-catechism-no-2": ("pg14552.txt", 138_043, "3d4b556fdb094ab8e22a53df85f60ba3310b49c9c65a24281aeecb9119f9746c", 3_675),
    "baltimore-catechism-no-3": ("pg14553.txt", 438_198, "cff9e639e837f08a9c041719a49e0824ffbb4cf778393968369a0f6274da66f4", 9_253),
    "luthers-small-catechism": ("pg1670.txt", 43_598, "bef45c16f9785a86d2cc0a902415e50fb689915c5aaaf7328773b9949baaf61f", 1_035),
}
RAW = Path("D:/Library/Open Christian Data/raw/gutenberg")
SOURCE_ROOT = ROOT / "sources/gutenberg-catechisms"
NS = {"tei": "http://www.tei-c.org/ns/1.0"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


@pytest.mark.parametrize("work_id", tuple(SOURCES))
def test_external_witness_identity_is_exact(work_id: str, tmp_path: Path) -> None:
    from build.tei.gutenberg_catechisms_reconstruction import inspect_witness

    filename, byte_count, digest, line_count = SOURCES[work_id]
    mirror = tmp_path / filename
    shutil.copyfile(RAW / filename, mirror)

    witness = inspect_witness(work_id, mirror)

    assert witness.byte_count == byte_count
    assert witness.sha256 == digest
    assert witness.line_count == line_count
    assert witness.content.startswith(b"\xef\xbb\xbf")
    assert witness.content.endswith(b"\r\n")
    assert witness.content.count(b"\r\n") == line_count
    assert hashlib.sha256(witness.content).hexdigest() == digest


def _manifest(work_id: str) -> Path:
    return SOURCE_ROOT / work_id / "source-manifest.json"


def _mirror(work_id: str, root: Path) -> Path:
    filename = SOURCES[work_id][0]
    destination = root / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RAW / filename, destination)
    return destination


@pytest.mark.parametrize("work_id", tuple(SOURCES))
def test_complete_candidate_is_lossless_dual_schema_valid_and_nonaccepted(work_id: str, tmp_path: Path) -> None:
    from build.tei.gutenberg_catechisms_reconstruction import build_candidate, load_source_manifest

    manifest = load_source_manifest(_manifest(work_id), repository_root=ROOT, witness_path=_mirror(work_id, tmp_path / "external"))
    candidate = build_candidate(manifest, tmp_path / "candidate")
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    Draft202012Validator(json.loads((SOURCE_ROOT / "source-accountability.schema.json").read_bytes())).validate(accountability)
    tree = etree.ElementTree(etree.fromstring(candidate.member_bytes("content.tei.xml")))
    etree.XMLSchema(etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))).assertValid(tree)

    _, byte_count, digest, line_count = SOURCES[work_id]
    assert candidate.manifest["status"] == "nonaccepted"
    assert accountability["source_bytes"] == byte_count
    assert accountability["source_sha256"] == digest
    assert accountability["physical_lines"] == accountability["represented_lines"] == line_count
    assert accountability["omitted_lines"] == accountability["duplicated_lines"] == 0
    assert len(accountability["member_census"]) == 1
    assert accountability["excluded_members"] == []
    assert len(accountability["crosswalk"]) == line_count
    assert accountability["crosswalk"][0]["byte_start"] == 0
    assert accountability["crosswalk"][-1]["byte_end"] == byte_count
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert provenance["candidate_status"] == "nonaccepted"
    assert provenance["publication_authorized"] is False
    assert provenance["technical_validation_is_human_acceptance"] is False
    assert candidate.member_bytes("README.source.md") == (SOURCE_ROOT / work_id / "README.source.md").read_bytes()


@pytest.mark.parametrize("work_id", tuple(SOURCES))
def test_independent_oracle_accepts_exact_candidate(work_id: str, tmp_path: Path) -> None:
    from build.tei.gutenberg_catechisms_oracle import _oracle
    from build.tei.gutenberg_catechisms_reconstruction import build_candidate, load_source_manifest

    manifest = load_source_manifest(_manifest(work_id), repository_root=ROOT, witness_path=_mirror(work_id, tmp_path / "external"))
    candidate = build_candidate(manifest, tmp_path / "candidate")
    report = validate(manifest, candidate, _oracle)  # type: ignore[arg-type]
    assert report.status == "pass"
    assert report.findings == ()
    assert report.attestation["source_sha256"] == SOURCES[work_id][2]


def test_oracle_has_no_producer_or_convert_dependency() -> None:
    path = ROOT / "build/tei/gutenberg_catechisms_oracle.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert "build.tei.gutenberg_catechisms_reconstruction" not in imports
    assert "_convert" not in source


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _line_carriers(root: etree._Element) -> list[etree._Element]:
    return root.xpath("./tei:text/tei:body/tei:div//*[self::tei:ab or self::tei:head]", namespaces=NS)


def _reseal(path: Path, name: str, content: bytes) -> CandidatePackage:
    (path / name).write_bytes(content)
    manifest = json.loads((path / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member["bytes"] = len(content)
    member["sha256"] = hashlib.sha256(content).hexdigest()
    (path / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


@pytest.fixture(scope="module")
def mutation_bundle(tmp_path_factory: pytest.TempPathFactory) -> tuple[object, CandidatePackage]:
    from build.tei.gutenberg_catechisms_reconstruction import build_candidate, load_source_manifest

    root = tmp_path_factory.mktemp("lib069-mutation")
    work_id = "luthers-small-catechism"
    manifest = load_source_manifest(_manifest(work_id), repository_root=ROOT, witness_path=RAW / SOURCES[work_id][0])
    return manifest, build_candidate(manifest, root / "candidate")


@pytest.mark.parametrize("mutation", ["omission", "duplication", "reordering", "invention", "text", "metadata", "metadata-uri", "metadata-extent", "metadata-revision", "provenance", "provenance-url", "provenance-rights", "unresolved-kind", "unresolved-detail", "scope", "crosswalk", "manifest-source", "manifest-converter"])
def test_independent_oracle_rejects_resealed_fidelity_mutations(mutation: str, tmp_path: Path, mutation_bundle: tuple[object, CandidatePackage]) -> None:
    from build.tei.gutenberg_catechisms_oracle import _oracle

    manifest, candidate = mutation_bundle
    path = tmp_path / mutation
    shutil.copytree(candidate.path, path)
    if mutation in {"omission", "duplication", "reordering", "invention", "text", "metadata", "metadata-uri", "metadata-extent", "metadata-revision", "scope"}:
        root = etree.fromstring((path / "content.tei.xml").read_bytes())
        lines = _line_carriers(root)
        if mutation == "omission":
            lines[100].getparent().remove(lines[100])
        elif mutation == "duplication":
            duplicate = copy.deepcopy(lines[100]); duplicate.set(XML_ID, "invented-duplicate"); lines[100].addnext(duplicate)
        elif mutation == "reordering":
            line_container = lines[100].getparent(); parent = line_container.getparent(); index = parent.index(line_container); parent.remove(line_container); parent.insert(min(index + 2, len(parent)), line_container)
        elif mutation == "invention":
            invented = etree.SubElement(lines[-1].getparent(), "{http://www.tei-c.org/ns/1.0}ab"); invented.set(XML_ID, "invented-line"); invented.set("n", "99999"); invented.set("ana", "#source-line #work-content"); invented.text = "Invented text"
        elif mutation == "text":
            lines[100].text = (lines[100].text or "") + " invented"
        elif mutation == "metadata":
            root.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=NS)[0].text = "Accepted edition"
        elif mutation == "metadata-uri":
            root.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='URI']", namespaces=NS)[0].text = "https://example.invalid/rebound"
        elif mutation == "metadata-extent":
            root.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:extent", namespaces=NS)[0].text = "1 byte"
        elif mutation == "metadata-revision":
            root.xpath("./tei:teiHeader/tei:revisionDesc/tei:change", namespaces=NS)[0].text = "Accepted editorial edition"
        else:
            root.xpath("./tei:text/tei:body/tei:div", namespaces=NS)[0].set(XML_ID, "another-work-retained-lines")
        mutated = _reseal(path, "content.tei.xml", etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False))
    elif mutation in {"provenance", "provenance-url", "provenance-rights"}:
        value = json.loads((path / "provenance.json").read_bytes())
        if mutation == "provenance":
            value["publication_authorized"] = True
        elif mutation == "provenance-url":
            value["source_url"] = "https://example.invalid/rebound"
        else:
            value["rights"]["retained_statement"] = "cleared"
        mutated = _reseal(path, "provenance.json", _canonical(value))
    elif mutation in {"unresolved-kind", "unresolved-detail"}:
        lines = (path / "unresolved.jsonl").read_bytes().splitlines()
        value = json.loads(lines[0])
        if mutation == "unresolved-kind":
            value["kind"] = "accepted"
        else:
            value["detail"] = "invented detail"
        lines[0] = _canonical(value).rstrip(b"\n")
        mutated = _reseal(path, "unresolved.jsonl", b"\n".join(lines) + b"\n")
    elif mutation == "crosswalk":
        value = json.loads((path / "source-accountability.json").read_bytes()); value["crosswalk"][100]["target"] = "#wrong-line"; value["crosswalk_sha256"] = hashlib.sha256(_canonical(value["crosswalk"])).hexdigest()
        mutated = _reseal(path, "source-accountability.json", _canonical(value))
    else:
        value = json.loads((path / "manifest.json").read_bytes())
        if mutation == "manifest-source":
            value["source_manifest"]["sha256"] = "0" * 64
        else:
            value["converter"]["id"] = "invented-converter"
        (path / "manifest.json").write_bytes(_canonical(value))
        mutated = CandidatePackage.load(path)
    with pytest.raises(ValueError):
        validate(manifest, mutated, _oracle)  # type: ignore[arg-type]


@pytest.mark.parametrize("mutation", ["flattened", "wrong-parent", "appendix-nesting", "role-parent"])
def test_independent_oracle_rejects_equal_text_structure_mutations(mutation: str, tmp_path: Path, mutation_bundle: tuple[object, CandidatePackage]) -> None:
    from build.tei.gutenberg_catechisms_oracle import _oracle

    manifest, candidate = mutation_bundle
    path = tmp_path / mutation
    shutil.copytree(candidate.path, path)
    root = etree.fromstring((path / "content.tei.xml").read_bytes())
    if mutation == "flattened":
        container = root.xpath("./tei:text/tei:body/tei:div//tei:div[@type='part']", namespaces=NS)[0]
        parent = container.getparent()
        index = parent.index(container)
        for child in list(container):
            container.remove(child)
            parent.insert(index, child)
            index += 1
        parent.remove(container)
    elif mutation == "wrong-parent":
        container = root.xpath("./tei:text/tei:body/tei:div//tei:div[@type='question-answer']", namespaces=NS)[0]
        container.set(XML_ID, "luthers-small-catechism-question-answer-99999")
    elif mutation == "appendix-nesting":
        appendices = root.xpath("./tei:text/tei:body/tei:div/tei:div[@type='appendix']", namespaces=NS)
        appendix_two, appendix_three = appendices[1], appendices[2]
        outer = appendix_three.getparent()
        outer.remove(appendix_three)
        appendix_two.append(appendix_three)
    else:
        entries = root.xpath("./tei:text/tei:body/tei:div//tei:div[@type='home-chart-entry']", namespaces=NS)
        first_entry, second_entry = entries[0], entries[1]
        home_chart = first_entry.getparent()
        home_chart.remove(first_entry)
        second_entry.insert(0, first_entry)
    mutated = _reseal(path, "content.tei.xml", etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False))
    with pytest.raises(ValueError):
        validate(manifest, mutated, _oracle)  # type: ignore[arg-type]


@pytest.mark.parametrize("work_id", tuple(SOURCES))
def test_fresh_process_different_cwd_packages_are_byte_identical(work_id: str, tmp_path: Path) -> None:
    witness = _mirror(work_id, tmp_path / "external")
    outputs = [tmp_path / "first", tmp_path / "second"]
    cwd_values = [ROOT, tmp_path]
    for output, cwd in zip(outputs, cwd_values, strict=True):
        subprocess.run([sys.executable, "-B", "-m", "build.tei.gutenberg_catechisms_reconstruction", "--repository-root", str(ROOT), "--manifest", str(_manifest(work_id)), "--witness", str(witness), "--output", str(output)], cwd=cwd, env={**dict(__import__("os").environ), "PYTHONPATH": str(ROOT)}, check=True, capture_output=True, text=True)
    assert sorted(path.name for path in outputs[0].iterdir()) == sorted(path.name for path in outputs[1].iterdir()) == ["README.source.md", "content.tei.xml", "manifest.json", "provenance.json", "source-accountability.json", "unresolved.jsonl"]
    for name in sorted(path.name for path in outputs[0].iterdir()):
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes()
