from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
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
WORK_DIR = ROOT / "library/works/watson-lords-prayer"
ACQUISITION_PATH = (
    WORK_DIR
    / "forms/watson-lords-prayer-route-source-form/editions/"
    "watson-lords-prayer-retained-thml-route/acquisitions/"
    "watson-lords-prayer-retained-source.json"
)
SOURCE = ROOT / "raw/ccel/watson/prayer.xml"
SOURCE_SHA256 = "9f14813ac77f4a44ce08b63ec6343ec8f59f006df7f80f11fcf87926730468ca"
MANIFEST_PATH = (
    ROOT / 'tests/fixtures/reconstruction-runtime/watson-lords-prayer.source-manifest.json'
)
ACCOUNTABILITY_PATH = (
    ROOT
    / "sources/structured-text/watson-lords-prayer/"
    "watson-lords-prayer.source-accountability.json"
)
ACCOUNTABILITY_SCHEMA_PATH = (
    ROOT
    / "sources/structured-text/watson-lords-prayer/"
    "watson-lords-prayer.source-accountability.schema.json"
)
RECONSTRUCTION_PATH = (
    ROOT
    / "sources/structured-text/watson-lords-prayer/"
    "watson_lords_prayer_reconstruction.py"
)
ORACLE_PATH = (
    ROOT
    / "sources/structured-text/watson-lords-prayer/"
    "watson_lords_prayer_oracle.py"
)
NS = {
    "t": "http://www.tei-c.org/ns/1.0",
    "xml": "http://www.w3.org/XML/1998/namespace",
}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _load_route_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_RECONSTRUCTION = _load_route_module(
    "w317_reconstruction", RECONSTRUCTION_PATH
)
_ORACLE = _load_route_module("w317_oracle", ORACLE_PATH)
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


def test_bound_work_and_complete_source_envelope() -> None:
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    work = load_work(WORK_DIR / "work.json")
    acquisition = validate_acquisition(ACQUISITION_PATH, root=ROOT)
    selection = verify_source_selection(acquisition, work, root=ROOT)
    assert selection["selected_native_ids"] == [
        "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"
    ]
    assert SOURCE.stat().st_size == 1_376_060
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
    assert [row["position"] for row in account["body_node_sequence"]] == list(range(10))
    assert all(row["disposition"] == "selected-work" for row in account["carrier_inventory"])
    assert [row["tei_region"] for row in account["carrier_inventory"]] == [
        "front", "body", "body", "body", "body",
        "body", "body", "body", "body", "back",
    ]
    assert account["selected_feature_count"] == 6723
    assert account["selected_feature_counts"]["h3"] == 1
    assert account["selected_comment_count"] == 0
    assert account["document_comment_count"] == 0
    assert len(account["document_shell"]["prolog"]) == 1
    assert account["document_shell"]["comments_and_processing_instructions"] == []
    print_claim = next(
        row for row in account["source_claims"]
        if row["source_path"] == "/ThML/ThML.head/printSourceInfo"
    )
    assert print_claim["excerpt"] == "1692"
    assert "not an adopted edition date" in print_claim["interpretation"]
    work_edition = work["textual_forms"][0]["editions"][0]
    assert "containing_source" not in work_edition
    assert "rights" not in acquisition
    assert manifest.record["work_id"] == "watson-lords-prayer"


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory):
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    destination = tmp_path_factory.mktemp("w317") / "candidate"
    candidate = reconstruct(manifest, destination, _convert)
    report = validate(manifest, candidate, _oracle)
    return manifest, candidate, report


def test_nonaccepted_candidate_preserves_full_envelope_and_schema(built) -> None:
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
    assert [etree.QName(child).localname for child in text] == [
        "front", "body", "back"
    ]
    front, body, back = list(text)
    assert len(front) == 1
    assert len(body) == 8
    assert len(back) == 1
    assert len(tei.xpath("/t:TEI/t:text//t:head[@type='thml-h3']", namespaces=NS)) == 1
    assert len(tei.xpath("/t:TEI/t:text//t:head", namespaces=NS)) == 20
    assert len(tei.xpath("/t:TEI/t:text//*[@xml:id]", namespaces=NS)) == 6723
    assert "Title Page" in [
        " ".join(" ".join(head.itertext()).split())
        for head in tei.xpath("/t:TEI/t:text//t:head", namespaces=NS)
    ]
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    assert len(account["units"]) == 10
    assert account["source_envelope"] == _read_accountability()["carrier_inventory"]
    assert len(account["features"]) == 6723
    assert len(candidate.member_bytes("unresolved.jsonl").splitlines()) == 5
    readme = candidate.member_bytes("README.source.md").decode("utf-8")
    assert "2000-07-09" in readme
    assert "First published as part of A Body of Practical Divinity, 1692" in (
        " ".join(" ".join(front.itertext()).split())
    )
    assert "1692" in readme
    assert not tei.xpath("/t:TEI/t:teiHeader//t:note[@type='print-source']", namespaces=NS)


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
        "ps=importlib.util.spec_from_file_location('w317_reconstruction',r/"
        "'sources/structured-text/watson-lords-prayer/"
        "watson_lords_prayer_reconstruction.py'); "
        "producer=importlib.util.module_from_spec(ps); ps.loader.exec_module(producer); "
        "ospec=importlib.util.spec_from_file_location('w317_oracle',r/"
        "'sources/structured-text/watson-lords-prayer/"
        "watson_lords_prayer_oracle.py'); "
        "oracle=importlib.util.module_from_spec(ospec); ospec.loader.exec_module(oracle); "
        "m=SourceManifest.load(r/'tests/fixtures/reconstruction-runtime/watson-lords-prayer.source-manifest.json',repository_root=r); "
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


@pytest.mark.parametrize(
    "mutation",
    [
        "omit", "duplicate", "reorder", "invent", "metadata", "h3",
        "region", "accounting", "synthetic-title-head",
    ],
)
def test_independent_checker_rejects_resealed_mutations(built, mutation: str) -> None:
    manifest, candidate, _report = built
    originals = {
        name: (candidate.path / name).read_bytes()
        for name in candidate.member_names
    }
    try:
        if mutation == "accounting":
            path = candidate.path / "source-accountability.json"
            account = json.loads(path.read_bytes())
            account["source_envelope"].pop()
            path.write_bytes(_canonical_json(account))
            _reseal_member(candidate.path, "source-accountability.json")
        else:
            path = candidate.path / "content.tei.xml"
            tei = etree.fromstring(path.read_bytes())
            if mutation == "omit":
                paragraph = tei.xpath("/t:TEI/t:text/t:body//t:p", namespaces=NS)[0]
                paragraph.getparent().remove(paragraph)
            elif mutation == "duplicate":
                paragraph = tei.xpath("/t:TEI/t:text/t:body//t:p", namespaces=NS)[0]
                duplicate = copy.deepcopy(paragraph)
                for index, node in enumerate(duplicate.iter()):
                    if node.get(XML_ID) is not None:
                        node.set(XML_ID, f"mutation-duplicate-{index}")
                paragraph.getparent().insert(paragraph.getparent().index(paragraph) + 1, duplicate)
            elif mutation == "reorder":
                body = tei.xpath("/t:TEI/t:text/t:body", namespaces=NS)[0]
                moved = list(body)[1]
                body.remove(moved)
                body.insert(0, moved)
            elif mutation == "invent":
                paragraph = tei.xpath("/t:TEI/t:text/t:body//t:p", namespaces=NS)[0]
                paragraph.text = (paragraph.text or "") + " invented wording"
            elif mutation == "metadata":
                title = tei.xpath(
                    "/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title",
                    namespaces=NS,
                )[0]
                title.text = "A different work"
            elif mutation == "h3":
                heading = tei.xpath(
                    "/t:TEI/t:text//t:head[@type='thml-h3']",
                    namespaces=NS,
                )[0]
                heading.set("type", "flattened-or-mislabeled")
            elif mutation == "synthetic-title-head":
                synthetic = tei.xpath(
                    "/t:TEI/t:text/t:front/t:div/t:head[normalize-space(.)='Title Page']",
                    namespaces=NS,
                )[0]
                synthetic.getparent().remove(synthetic)
            else:
                front = tei.xpath("/t:TEI/t:text/t:front", namespaces=NS)[0]
                body = tei.xpath("/t:TEI/t:text/t:body", namespaces=NS)[0]
                title_page = front[0]
                front.remove(title_page)
                body.insert(0, title_page)
            assert compiled_schema().validate(tei), str(compiled_schema().error_log)
            path.write_bytes(etree.tostring(tei, encoding="UTF-8", xml_declaration=True))
            _reseal_member(candidate.path, "content.tei.xml")

        with pytest.raises(ValueError):
            validate(manifest, CandidatePackage.load(candidate.path), _oracle)
    finally:
        for name, content in originals.items():
            (candidate.path / name).write_bytes(content)

