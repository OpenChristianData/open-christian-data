"""Focused LIB-041 source-to-TEI, mutation, and fresh-process gates."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from lxml import etree
import pytest

from build.tei.npnf113_lib041_oracle import _oracle
from build.tei.npnf113_lib041_reconstruction import _convert
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
ROUTE = ROOT / "sources/structured-text/chrysostom-npnf113-lib041"
# The original manifest retains historical CRLF campaign-evidence bindings.
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/npnf113-lib041.source-manifest.json'
PROFILE = ROUTE / "npnf113-lib041.reconstruction-profile.json"
RUNNER = ROOT / "build/tools/reconstruct_candidate.py"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"

EXPECTED_WORKS = (
    ("iii.iii", "chrysostom-commentary-on-galatians"),
    ("iii.iv", "chrysostom-homilies-on-ephesians"),
    ("iv.iii", "chrysostom-homilies-on-philippians"),
    ("iv.iv", "chrysostom-homilies-on-colossians"),
    ("iv.v", "chrysostom-homilies-on-1-thessalonians"),
    ("iv.vi", "chrysostom-homilies-on-2-thessalonians"),
    ("v.iii", "chrysostom-homilies-on-1-timothy"),
    ("v.iv", "chrysostom-homilies-on-2-timothy"),
    ("v.v", "chrysostom-homilies-on-titus"),
    ("v.vi", "chrysostom-homilies-on-philemon"),
)
EXPECTED_SOURCE_HASH = "d62c7c82b262c738739090ffaf5473aa5a76dbadf62ebee0dccac8c4a7db4762"
EXPECTED_CENSUS = {
    "elements": 11528,
    "attributes": 32716,
    "text_nodes": 8037,
    "tail_nodes": 9268,
    "characters": 2820015,
    "non_ascii_characters": 31247,
}
EXPECTED_TAG_COUNTS = {
    "div2": 10,
    "div3": 114,
    "i": 378,
    "note": 1572,
    "p": 4975,
    "pb": 536,
    "scripCom": 119,
    "scripRef": 3139,
    "span": 685,
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _source_census(source: SourceManifest) -> tuple[dict[str, int], Counter[str]]:
    content = source.authority_path("npnf113-retained-xml").read_bytes()
    assert len(content) == 4441248
    assert _sha(content) == EXPECTED_SOURCE_HASH
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
    assert tree.docinfo.doctype == (
        '<!DOCTYPE ThML PUBLIC "-//CCEL/DTD Theological Markup Language//EN" '
        '"http://www.ccel.org/dtd/ThML10.dtd">'
    )
    assert len(tree.xpath("/comment()")) == 2
    body = tree.getroot().find("ThML.body")
    assert body is not None
    profile = json.loads(PROFILE.read_bytes())
    selected = []
    for root_id, _ in EXPECTED_WORKS:
        nodes = body.xpath(f".//*[@id='{root_id}']")
        assert len(nodes) == 1
        assert nodes[0].tag == "div2"
        selected.append(nodes[0])
    assert [node.get("id") for node in body.iter("div2") if node.get("id") in {root_id for root_id, _ in EXPECTED_WORKS}] == [
        root_id for root_id, _ in EXPECTED_WORKS
    ]
    observed_nodes = [
        node for root in selected for node in root.iter() if isinstance(node.tag, str)
    ]
    census = {
        "elements": len(observed_nodes),
        "attributes": sum(len(node.attrib) for node in observed_nodes),
        "text_nodes": sum(node.text is not None for node in observed_nodes),
        "tail_nodes": sum(node.tail is not None for node in observed_nodes),
        "characters": sum(
            len((node.text or "") + (node.tail or "")) for node in observed_nodes
        ),
        "non_ascii_characters": sum(
            sum(ord(char) > 127 for char in (node.text or "") + (node.tail or ""))
            for node in observed_nodes
        ),
    }
    tags = Counter(str(node.tag) for node in observed_nodes)
    assert census == {
        "elements": profile["expected"]["retained_elements"],
        "attributes": profile["expected"]["retained_attributes"],
        "text_nodes": profile["expected"]["retained_text_nodes"],
        "tail_nodes": profile["expected"]["retained_tail_nodes"],
        "characters": profile["expected"]["retained_characters_including_root_tails"],
        "non_ascii_characters": profile["expected"]["non_ascii_characters_including_root_tails"],
    }
    assert census == EXPECTED_CENSUS
    return census, tags


@pytest.fixture(scope="module")
def verified_candidate():
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    with tempfile.TemporaryDirectory(prefix="ocd-lib041-candidate-") as temp_dir:
        candidate_path = Path(temp_dir) / "package"
        candidate = reconstruct(source, candidate_path, _convert)
        report = validate(source, candidate, _oracle)
        assert report.status == "pass"
        yield source, candidate, report


def _parsed(candidate: CandidatePackage) -> etree._ElementTree:
    return etree.fromstring(
        candidate.member_bytes("content.tei.xml"),
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            remove_pis=False,
            huge_tree=True,
        ),
    ).getroottree()


def _copy_candidate(source: CandidatePackage, destination: Path) -> CandidatePackage:
    destination.mkdir()
    for member in source.path.iterdir():
        shutil.copy2(member, destination / member.name)
    return CandidatePackage.load(destination)


def _reseal(path: Path, member_name: str) -> CandidatePackage:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    content = (path / member_name).read_bytes()
    entry = next(item for item in manifest["members"] if item["name"] == member_name)
    entry["bytes"] = len(content)
    entry["sha256"] = _sha(content)
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def test_manifest_and_current_runtime_closure_are_exact() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    assert source.record["ticket"] == "LIB-041"
    assert source.record["source_id"] == "ccel-npnf113-lib041-ten-work-retained-xml"
    assert [
        (row["path"], row["sha256"])
        for row in source.record["authorities"]
        if row["role"] == "primary-source"
    ] == [("raw/ccel/npnf1/npnf113.xml", EXPECTED_SOURCE_HASH)]
    assert len(
        [
            row
            for row in source.record["authorities"]
            if row["role"] == "local-route-and-catalog-evidence"
        ]
    ) == 10
    closure = json.loads(source.authority_path("oracle-import-closure").read_bytes())
    assert closure["oracle_sha256"] == _sha(
        (ROOT / "build/tei/npnf113_lib041_oracle.py").read_bytes()
    )
    assert source.record["validator"]["import_closure_sha256"] == _sha(
        source.authority_path("oracle-import-closure").read_bytes()
    )
    for row in closure["first_party"]:
        path = ROOT / row["path"]
        assert path.is_file()
        assert _sha(path.read_bytes()) == row["sha256"]


def test_independent_source_accounting_covers_exact_ten_roots() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    census, tags = _source_census(source)
    assert census == EXPECTED_CENSUS
    assert dict(sorted(tags.items())) == EXPECTED_TAG_COUNTS


def test_current_ticket_maps_bind_exact_ten_work_associations() -> None:
    work_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/02-work-ticket-map.md"
    ).read_text(encoding="utf-8")
    source_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/05-source-ticket-map.md"
    ).read_text(encoding="utf-8")
    expected_hash = f"sha256:{EXPECTED_SOURCE_HASH}"
    for _, work_id in EXPECTED_WORKS:
        work_rows = [
            line
            for line in work_map.splitlines()
            if f"`{work_id}`" in line and "LIB-041" in line
        ]
        source_rows = [
            line
            for line in source_map.splitlines()
            if f"`{work_id}`" in line
            and expected_hash in line
            and "LIB-041" in line
        ]
        assert len(work_rows) == 1
        assert len(source_rows) == 1


def test_candidate_is_p5_valid_and_binds_all_ten_roots(
    verified_candidate,
) -> None:
    source, candidate, report = verified_candidate
    assert candidate.manifest["status"] == "nonaccepted"
    assert candidate.manifest["source_id"] == source.record["source_id"]
    assert candidate.manifest["source_manifest"]["sha256"] == source.sha256
    tree = _parsed(candidate)
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    assert schema.validate(tree), schema.error_log
    roots = tree.xpath(
        "/tei:TEI/tei:text/tei:body/tei:div",
        namespaces={"tei": TEI_NS},
    )
    assert [root.get("corresp") for root in roots] == [
        f"#npnf113:{root_id}:{work_id}" for root_id, work_id in EXPECTED_WORKS
    ]
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["assigned_work_count"] == 10
    assert accountability["feature_count"] == EXPECTED_CENSUS["elements"]
    assert accountability["attribute_count"] == EXPECTED_CENSUS["attributes"]
    assert accountability["omitted_feature_count"] == 0
    assert accountability["duplicate_feature_count"] == 0
    assert accountability["unresolved_feature_count"] == 0
    assert report.attestation["source_sha256"] == EXPECTED_SOURCE_HASH
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert [row["work_id"] for row in provenance["works"]] == [
        work_id for _, work_id in EXPECTED_WORKS
    ]
    assert all(row["human_review"] == "human_required" for row in provenance["works"])
    assert all(row["accepted_ir"] == "not_accepted" for row in provenance["works"])
    assert all(row["publication"] == "not_ready" for row in provenance["works"])


@pytest.mark.parametrize(
    "mutation",
    (
        "omission",
        "direct-text",
        "rights",
        "accountability",
        "duplicate-root",
        "reorder-root",
        "attribute",
        "moved-note",
    ),
)
def test_resealed_mutations_are_rejected(
    verified_candidate,
    mutation: str,
) -> None:
    source, candidate, _ = verified_candidate
    with tempfile.TemporaryDirectory(prefix=f"ocd-lib041-mutation-{mutation}-") as temp_dir:
        path = Path(temp_dir) / mutation
        mutant = _copy_candidate(candidate, path)
        if mutation in {
            "omission",
            "direct-text",
            "duplicate-root",
            "reorder-root",
            "attribute",
            "moved-note",
        }:
            tree = _parsed(mutant)
            roots = tree.xpath(
                "/tei:TEI/tei:text/tei:body/tei:div",
                namespaces={"tei": TEI_NS},
            )
            if mutation == "omission":
                first = tree.xpath("//tei:p", namespaces={"tei": TEI_NS})[0]
                first.getparent().remove(first)
            elif mutation == "direct-text":
                first = tree.xpath("//tei:p", namespaces={"tei": TEI_NS})[0]
                first.text = (first.text or "") + " INVENTED"
            elif mutation == "duplicate-root":
                roots[0].getparent().append(deepcopy(roots[0]))
            elif mutation == "reorder-root":
                parent = roots[0].getparent()
                first, last = roots[0], roots[-1]
                parent.remove(first)
                parent.remove(last)
                parent.insert(0, last)
                parent.insert(1, first)
            elif mutation == "attribute":
                roots[0].set("corresp", f"{roots[0].get('corresp')}-mutated")
            else:
                note = tree.xpath("//tei:note", namespaces={"tei": TEI_NS})[0]
                note.getparent().remove(note)
                roots[-1].append(note)
            (path / "content.tei.xml").write_bytes(
                etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
            )
            mutant = _reseal(path, "content.tei.xml")
        elif mutation == "rights":
            provenance = json.loads((path / "provenance.json").read_bytes())
            provenance["rights"]["retained_dc_rights"] = "Unrestricted commercial sale."
            (path / "provenance.json").write_bytes(_canonical(provenance))
            mutant = _reseal(path, "provenance.json")
        else:
            accountability = json.loads((path / "source-accountability.json").read_bytes())
            accountability["feature_count"] = 1
            (path / "source-accountability.json").write_bytes(_canonical(accountability))
            mutant = _reseal(path, "source-accountability.json")
        with pytest.raises((ValueError, etree.XMLSyntaxError)):
            validate(source, mutant, _oracle)


def test_two_fresh_processes_reproduce_the_complete_candidate() -> None:
    outputs = []
    with tempfile.TemporaryDirectory(prefix="ocd-lib041-fresh-") as temp_dir:
        base = Path(temp_dir)
        for ordinal, seed in enumerate(("101", "907"), start=1):
            output = base / f"fresh-{ordinal}"
            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONHASHSEED"] = seed
            env["PYTHONPATH"] = str(ROOT)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "build.tools.reconstruct_candidate",
                    "--manifest",
                    str(MANIFEST.relative_to(ROOT)),
                    "--destination",
                    str(output),
                    "--repository-root",
                    str(ROOT),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            assert completed.returncode == 0, completed.stderr
            outputs.append((output, json.loads(completed.stdout)))
        assert outputs[0][1] == outputs[1][1]
        assert outputs[0][1]["status"] == "pass"
        assert outputs[0][1]["acceptance_status"] == "nonaccepted"
        assert outputs[0][1]["human_review_required"] is True
        assert outputs[0][1]["publication_status"] == "not-authorized"
        fingerprints = []
        for output, summary in outputs:
            package = output / "package"
            fingerprints.append(
                {
                    path.name: _sha(path.read_bytes())
                    for path in package.iterdir()
                    if path.is_file()
                }
            )
            assert summary["candidate"]["sha256"] == fingerprints[-1]["manifest.json"]
            assert {path.name for path in package.iterdir()} == {
                "README.source.md",
                "content.tei.xml",
                "manifest.json",
                "provenance.json",
                "source-accountability.json",
                "unresolved.jsonl",
            }
        assert fingerprints[0] == fingerprints[1]
