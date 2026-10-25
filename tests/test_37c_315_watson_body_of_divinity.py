from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from jsonschema import Draft202012Validator
from lxml import etree
import pytest

from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.source_selection import (
    derive_source_carrier_inventory,
    verify_source_selection,
)
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)
from ocd_kernel.tei.validate import compiled_schema


ROOT = Path(__file__).resolve().parents[1]
WORK_DIR = ROOT / "library/works/watson-body-of-divinity"
ACQUISITION_PATH = (
    WORK_DIR
    / "forms/watson-body-of-divinity-route-source-form/editions/"
    "watson-body-of-divinity-retained-thml-route/acquisitions/"
    "watson-body-of-divinity-retained-source.json"
)
SOURCE = ROOT / "raw/ccel/watson/divinity.xml"
SOURCE_SHA256 = "4d51224997805193f13058ccf5fa84a6652bc41570283956cbcbe1300e1f815a"
MANIFEST_PATH = (
    ROOT / 'tests/fixtures/reconstruction-runtime/watson-body-of-divinity.source-manifest.json'
)
ACCOUNTABILITY_PATH = (
    ROOT
    / "sources/structured-text/watson-body-of-divinity/"
    "watson-body-of-divinity.source-accountability.json"
)
ACCOUNTABILITY_SCHEMA_PATH = (
    ROOT
    / "sources/structured-text/watson-body-of-divinity/"
    "watson-body-of-divinity.source-accountability.schema.json"
)
RECONSTRUCTION_PATH = (
    ROOT
    / "sources/structured-text/watson-body-of-divinity/"
    "watson_body_of_divinity_reconstruction.py"
)
ORACLE_PATH = (
    ROOT
    / "sources/structured-text/watson-body-of-divinity/"
    "watson_body_of_divinity_oracle.py"
)
NS = {
    "t": "http://www.tei-c.org/ns/1.0",
    "xml": "http://www.w3.org/XML/1998/namespace",
}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
EXPECTED_NATIVE_IDS = ("i", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi")
EXPECTED_FEATURE_COUNT = 5861
EXPECTED_FEATURE_COUNTS = {
    "a": 2070,
    "div": 1,
    "div1": 10,
    "div2": 42,
    "h1": 2,
    "h2": 13,
    "h3": 39,
    "insertIndex": 1,
    "p": 1658,
    "scripRef": 2025,
}


def _load_route_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_RECONSTRUCTION = _load_route_module(
    "w315_reconstruction", RECONSTRUCTION_PATH
)
_ORACLE = _load_route_module("w315_oracle", ORACLE_PATH)
_convert = _RECONSTRUCTION._convert
_oracle = _ORACLE._oracle


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _reseal_member(package_path: Path, member_name: str) -> None:
    manifest_path = package_path / "manifest.json"
    package_manifest = json.loads(manifest_path.read_bytes())
    content = (package_path / member_name).read_bytes()
    member = next(row for row in package_manifest["members"] if row["name"] == member_name)
    member.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical_json(package_manifest))


def _read_accountability() -> dict:
    return json.loads(ACCOUNTABILITY_PATH.read_bytes())


def test_bound_exact_source_envelope_and_ticket_authorities() -> None:
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    work = load_work(WORK_DIR / "work.json")
    acquisition = validate_acquisition(ACQUISITION_PATH, root=ROOT)
    selection = verify_source_selection(acquisition, work, root=ROOT)
    assert selection["selected_native_ids"] == list(EXPECTED_NATIVE_IDS)
    assert SOURCE.stat().st_size == 1_327_340
    assert _sha(SOURCE.read_bytes()) == SOURCE_SHA256

    account = _read_accountability()
    schema = json.loads(ACCOUNTABILITY_SCHEMA_PATH.read_bytes())
    assert list(Draft202012Validator(schema).iter_errors(account)) == []
    inventory = derive_source_carrier_inventory(acquisition, root=ROOT)
    assert [
        (row["position"], row["native_id"], row["title"], row["tag"])
        for row in inventory
    ] == [
        (row["position"], row["native_id"], row["source_title"], row["source_tag"])
        for row in account["carrier_inventory"]
    ]
    assert [row["position"] for row in account["body_node_sequence"]] == list(range(12))
    assert [
        row["native_id"] for row in account["carrier_inventory"]
    ] == list(EXPECTED_NATIVE_IDS)
    assert account["selected_feature_count"] == EXPECTED_FEATURE_COUNT
    assert account["selected_feature_counts"] == EXPECTED_FEATURE_COUNTS
    assert account["selected_comment_count"] == 4
    assert account["document_comment_count"] == 6
    assert manifest.record["work_id"] == "watson-body-of-divinity"
    assert manifest.record["validator"]["import_closure_sha256"] == _ORACLE._closure_digest(ROOT)

    edition = work["textual_forms"][0]["editions"][0]
    assert "unresolved" in work["textual_forms"][0]["title"]
    assert "unresolved" in edition["title"]
    assert "containing_source" not in edition
    assert "rights" not in acquisition


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory):
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    destination = tmp_path_factory.mktemp("w315") / "candidate"
    candidate = reconstruct(manifest, destination, _convert)
    report = validate(manifest, candidate, _oracle)
    return manifest, candidate, report


def test_nonaccepted_candidate_preserves_complete_route_envelope(built) -> None:
    _manifest, candidate, report = built
    assert report.status == "pass"
    assert report.findings == ()
    assert candidate.manifest["status"] == "nonaccepted"
    assert set(candidate.member_names) == {
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    }

    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert compiled_schema().validate(tei), str(compiled_schema().error_log)
    text = tei.xpath("/t:TEI/t:text", namespaces=NS)[0]
    assert [etree.QName(child).localname for child in text] == ["body", "back"]
    body, back = list(text)
    assert len(body) == 9
    assert len(back) == 1
    assert len(tei.xpath("/t:TEI/t:text//t:head", namespaces=NS)) == 54
    assert len(tei.xpath("/t:TEI/t:text//t:head[@type='thml-h3']", namespaces=NS)) == 39
    assert not tei.xpath(
        "/t:TEI/t:text//t:div/t:head[not(@xml:id)]", namespaces=NS
    )

    candidate_account = json.loads(candidate.member_bytes("source-accountability.json"))
    source_account = _read_accountability()
    assert len(candidate_account["units"]) == 10
    assert candidate_account["source_envelope"] == source_account["carrier_inventory"]
    assert len(candidate_account["features"]) == EXPECTED_FEATURE_COUNT
    assert [
        row["position"] for row in candidate_account["body_node_sequence"]
    ] == list(range(12))
    assert len(candidate.member_bytes("unresolved.jsonl").splitlines()) == 5
    assert "Nonaccepted per-work reconstruction." in candidate.member_bytes(
        "README.source.md"
    ).decode("utf-8")
    assert "2002-07-17" in candidate.member_bytes("README.source.md").decode("utf-8")
    assert "Public Domain" in candidate.member_bytes("README.source.md").decode("utf-8")


def test_fresh_process_reproduces_identical_candidate(built, tmp_path: Path) -> None:
    _manifest, candidate, _report = built
    destination = tmp_path / "fresh"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    code = (
        "from pathlib import Path; import sys; "
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct,validate; "
        "import importlib.util; "
        f"r=Path({str(ROOT)!r}); "
        "ps=importlib.util.spec_from_file_location('w315_reconstruction',r/"
        "'sources/structured-text/watson-body-of-divinity/"
        "watson_body_of_divinity_reconstruction.py'); "
        "producer=importlib.util.module_from_spec(ps); ps.loader.exec_module(producer); "
        "ospec=importlib.util.spec_from_file_location('w315_oracle',r/"
        "'sources/structured-text/watson-body-of-divinity/"
        "watson_body_of_divinity_oracle.py'); "
        "oracle=importlib.util.module_from_spec(ospec); ospec.loader.exec_module(oracle); "
        "m=SourceManifest.load(r/'tests/fixtures/reconstruction-runtime/watson-body-of-divinity.source-manifest.json',repository_root=r); "
        f"p=reconstruct(m,Path({str(destination)!r}),producer._convert); "
        "v=validate(m,p,oracle._oracle); "
        "print(v.status); print(p.sha256); "
        "[print(name) for name in p.member_names]"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines == ["pass", candidate.sha256, *candidate.member_names]
    for name in candidate.member_names:
        assert (destination / name).read_bytes() == candidate.member_bytes(name)


@pytest.mark.parametrize("mutation", ["omit", "reorder", "metadata", "accounting"])
def test_independent_checker_rejects_resealed_mutations(
    built, tmp_path: Path, mutation: str
) -> None:
    manifest, candidate, _report = built
    mutated = tmp_path / mutation
    shutil.copytree(candidate.path, mutated)

    if mutation == "accounting":
        path = mutated / "source-accountability.json"
        account = json.loads(path.read_bytes())
        account["source_envelope"].pop()
        path.write_bytes(_canonical_json(account))
        _reseal_member(mutated, "source-accountability.json")
    else:
        path = mutated / "content.tei.xml"
        tei = etree.fromstring(path.read_bytes())
        if mutation == "omit":
            paragraph = tei.xpath("/t:TEI/t:text/t:body//t:p", namespaces=NS)[0]
            paragraph.getparent().remove(paragraph)
        elif mutation == "reorder":
            body = tei.xpath("/t:TEI/t:text/t:body", namespaces=NS)[0]
            divisions = list(body)
            moved = divisions[1]
            body.remove(moved)
            body.insert(0, moved)
        else:
            title = tei.xpath(
                "/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=NS
            )[0]
            title.text = "A different work"
        assert compiled_schema().validate(tei), str(compiled_schema().error_log)
        path.write_bytes(etree.tostring(tei, encoding="UTF-8", xml_declaration=True))
        _reseal_member(mutated, "content.tei.xml")

    with pytest.raises(ValueError):
        validate(manifest, CandidatePackage.load(mutated), _oracle)
