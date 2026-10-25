from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
from lxml import etree

from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path('tests/fixtures/reconstruction-runtime/ccel_puritan_lib055_flavel_method_of_grace_oracle.source-manifest.json')
SOURCE_PATH = "raw/ccel/flavel/grace.xml"
SOURCE_SHA256 = "c044cad334d574b0cf52c936d6179a978c5c9a86bf7d8f51c4b3246a617f40cf"
SOURCE_BYTES = 1_796_532
WORK_ID = "flavel-method-of-grace"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI_NS}
EXPECTED_DIVISION_IDS = (
    "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
    "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix",
    "xx", "xxi", "xxii", "xxiii", "xxiv", "xxv", "xxvi", "xxvii",
    "xxviii", "xxix", "xxx", "xxxi", "xxxii", "xxxiii", "xxxiv",
    "xxxv", "xxxvi", "xxxvii", "xxxviii", "xxxix",
)


def _bound_callable(manifest: SourceManifest, role: str):
    binding = manifest.record[role]
    path = ROOT / str(binding["implementation_path"])
    module_name = f"_test_37c174_{role}_{binding['implementation_sha256']}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return getattr(module, str(binding["callable"]))


@pytest.fixture(scope="session")
def route():
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    return manifest, _bound_callable(manifest, "converter"), _bound_callable(
        manifest, "validator"
    )


@pytest.fixture
def candidate(route, tmp_path):
    manifest, converter, _oracle = route
    return reconstruct(manifest, tmp_path / "candidate", converter)


def _canonical(record: object) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _rewrite_member(candidate: CandidatePackage, name: str, content: bytes) -> CandidatePackage:
    member_path = candidate.path / name
    member_path.write_bytes(content)
    manifest_path = candidate.path / "manifest.json"
    record = json.loads(manifest_path.read_bytes())
    for member in record["members"]:
        if member["name"] == name:
            member["bytes"] = len(content)
            member["sha256"] = hashlib.sha256(content).hexdigest()
            break
    else:
        raise AssertionError(f"candidate manifest does not list {name!r}")
    manifest_path.write_bytes(_canonical(record))
    return CandidatePackage.load(candidate.path)


def _mutated_tei(candidate: CandidatePackage, mutation: str) -> CandidatePackage:
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    body = root.find("./tei:text/tei:body", NS)
    assert body is not None
    divisions = body.findall("./tei:div", NS)

    if mutation == "omit-carrier":
        body.remove(divisions[0])
    elif mutation == "duplicate-carrier":
        body.insert(1, deepcopy(divisions[0]))
    elif mutation == "reorder-carriers":
        body.remove(divisions[0])
        body.insert(1, divisions[0])
    elif mutation == "link-fragment":
        link = next(
            node
            for node in root.findall(".//tei:ref", NS)
            if node.get("type") != "scripture"
            and node.get("target")
            and "?" in node.get("target", "").split("#", 1)[0]
            and "#" in node.get("target", "")
        )
        prefix, fragment = link.get("target", "").rsplit("#", 1)
        link.set("target", f"{prefix}#{fragment}-mutated")
    elif mutation == "scripture-reference":
        reference = root.find(".//tei:ref[@type='scripture']", NS)
        assert reference is not None and reference.get("target")
        reference.set("target", reference.get("target", "") + "-mutated")
    elif mutation == "commentary-marker":
        marker = root.find(".//tei:anchor[@type='scripture-commentary-marker']", NS)
        assert marker is not None and marker.getparent() is not None
        marker.getparent().remove(marker)
    elif mutation == "heading":
        headings = root.xpath(
            ".//tei:head[@type='source-h3'] | .//tei:p[@rend='source-heading-h3']",
            namespaces=NS,
        )
        assert headings
        heading = headings[0]
        heading.text = (heading.text or "") + " mutated"
    elif mutation == "metadata":
        title = root.find("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", NS)
        assert title is not None
        title.text = "A different source-record title"
    elif mutation == "remove-comment":
        comments = root.xpath(".//tei:body//comment()", namespaces=NS)
        assert comments
        comments[0].getparent().remove(comments[0])
    elif mutation == "reorder-comment":
        parent = next(
            node
            for node in root.iter()
            if sum(isinstance(child, etree._Comment) for child in node) >= 2
        )
        pair = [child for child in parent if isinstance(child, etree._Comment)][:2]
        left_index, right_index = (parent.index(item) for item in pair)
        left, right = pair
        parent.remove(left)
        parent.remove(right)
        parent.insert(left_index, right)
        parent.insert(right_index, left)
    else:
        raise AssertionError(f"unknown mutation {mutation}")

    changed = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    return _rewrite_member(candidate, "content.tei.xml", changed)


def _run_handoff(destination: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "build/tools/reconstruct_candidate.py"),
            "--manifest",
            MANIFEST_PATH.as_posix(),
            "--destination",
            str(destination),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_manifest_binds_the_exact_source_and_owner_supported_route():
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    record = manifest.record
    source = ROOT / SOURCE_PATH
    raw = source.read_bytes()
    source_authorities = [
        item for item in record["authorities"] if item.get("role") == "primary-source"
    ]
    assert record["ticket"] == "37c-174"
    assert record["owner_route"] == "LIB-055"
    assert record["work_id"] == WORK_ID
    assert record["identity"]["work_id"] == WORK_ID
    assert all(
        record["identity"][field] is None
        for field in (
            "textual_form", "edition", "parts", "witness_claim", "translator",
            "original_publication_year",
        )
    )
    assert len(source_authorities) == 1
    assert source_authorities[0]["path"] == SOURCE_PATH
    assert source_authorities[0]["bytes"] == SOURCE_BYTES == len(raw)
    assert source_authorities[0]["sha256"] == SOURCE_SHA256
    assert hashlib.sha256(raw).hexdigest() == SOURCE_SHA256
    assert tuple(record["scope"]["member_order"]) == (SOURCE_PATH,)
    assert record["scope"]["selector"] == "ThML[1] (complete retained document envelope)"
    assert tuple(record["scope"]["top_level_div1_ids"]) == EXPECTED_DIVISION_IDS

    owner_ticket = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/tickets/library/055-reconstruct-and-review-ccel-puritan-works-cohort-2.md"
    ).read_text(encoding="utf-8")
    work_map = (
        ROOT / "plans/2026-08-26-whole-library-faithful-tei-completion/02-work-ticket-map.md"
    ).read_text(encoding="utf-8")
    source_map = (
        ROOT / "plans/2026-08-26-whole-library-faithful-tei-completion/05-source-ticket-map.md"
    ).read_text(encoding="utf-8")
    assert "`flavel-method-of-grace` — The Method of Grace in the Gospel Redemption" in owner_ticket
    assert "| `flavel-method-of-grace` | The Method of Grace in the Gospel Redemption | LIB-055 | 1 | none |" in work_map
    assert f"| `{WORK_ID}` | `sha256:{SOURCE_SHA256}` | LIB-055 | current-claim |" in source_map


def test_candidate_reconciles_the_full_source_envelope_and_validates(route, candidate):
    manifest, _converter, oracle = route
    report = validate(manifest, candidate, oracle)
    assert report.status == "pass"
    assert candidate.manifest["status"] == "nonaccepted"
    assert set(candidate.member_names) == {
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    }

    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accounting["source_member"] == {
        "path": SOURCE_PATH,
        "bytes": SOURCE_BYTES,
        "sha256": SOURCE_SHA256,
    }
    assert accounting["source_envelope"]["profile"]["element_count"] == 8789
    assert accounting["source_envelope"]["profile"]["attribute_count"] == 19422
    assert len(accounting["elements"]) == 8789
    assert len(accounting["body_carriers"]) == 39
    assert accounting["source_envelope"]["profile"]["comment_count"] == 11
    assert len(accounting["source_envelope"]["shell_nodes"]) == 13

    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert tei.tag == f"{{{TEI_NS}}}TEI"
    body = tei.find("./tei:text/tei:body", NS)
    assert body is not None
    divisions = body.findall("./tei:div", NS)
    assert [item.get(f"{{{XML_NS}}}id") for item in divisions] == list(
        EXPECTED_DIVISION_IDS
    )
    assert tei.findtext(
        "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=NS
    ) == "The Method of Grace in the Gospel Redemption"
    assert len(tei.findall(".//tei:ref[@type='scripture']", NS)) == 2591
    assert len(tei.findall(".//tei:anchor[@type='scripture-commentary-marker']", NS)) == 35
    assert len(tei.findall(".//tei:anchor[@type='index-insertion']", NS)) == 2
    assert "sourced via CCEL.org" in candidate.member_bytes("README.source.md").decode("utf-8")
    unresolved = candidate.member_bytes("unresolved.jsonl").decode("utf-8").splitlines()
    assert {json.loads(line)["claim"] for line in unresolved} == {
        "work_boundary",
        "textual_form_and_translator",
        "edition_and_publication_history",
        "parts",
        "witness_claim",
        "rights_clearance",
    }


@pytest.mark.parametrize(
    "mutation",
    (
        "omit-carrier",
        "duplicate-carrier",
        "reorder-carriers",
        "link-fragment",
        "scripture-reference",
        "commentary-marker",
        "heading",
        "metadata",
        "remove-comment",
        "reorder-comment",
    ),
)
def test_independent_oracle_rejects_source_meaning_mutations(route, candidate, mutation):
    manifest, _converter, oracle = route
    changed = _mutated_tei(candidate, mutation)
    with pytest.raises(ValueError, match="TEI|candidate"):
        validate(manifest, changed, oracle)


def test_fresh_process_reproduction_matches_every_candidate_and_validation_byte(tmp_path):
    outputs: list[dict[str, bytes]] = []
    for label in ("first", "second"):
        destination = tmp_path / label
        result = _run_handoff(destination)
        assert result.returncode == 0, result.stdout + result.stderr
        summary = json.loads(result.stdout)
        assert summary["status"] == "pass"
        assert summary["acceptance_status"] == "nonaccepted"
        text_quality_sha = hashlib.sha256((destination / "text-quality.json").read_bytes()).hexdigest()
        assert summary["text_quality"]["sha256"] == text_quality_sha
        assert json.loads((destination / "validation.json").read_bytes())["text_quality_sha256"] == text_quality_sha
        outputs.append(
            {
                path.relative_to(destination).as_posix(): path.read_bytes()
                for path in sorted(destination.rglob("*"))
                if path.is_file()
            }
        )
    assert outputs[0] == outputs[1]
    assert set(outputs[0]) == {
        "package/README.source.md",
        "package/content.tei.xml",
        "package/manifest.json",
        "package/provenance.json",
        "package/source-accountability.json",
        "package/unresolved.jsonl",
        "validation.json",
        "text-quality.json",
    }


def test_workcatalog_route_association_is_exact_and_read_only(tmp_path):
    destination = tmp_path / "catalog-check"
    result = _run_handoff(destination)
    assert result.returncode == 0, result.stdout + result.stderr

    from tests.runtime_candidate_baselines import current_runtime_catalog

    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    catalog = current_runtime_catalog(
        root=ROOT, manifest=ROOT / MANIFEST_PATH, work_ids=(WORK_ID,),
        reconstruction_evidence={
            (manifest.record["source_id"], manifest.record["work_id"]): (
                destination / "package",
                destination / "validation.json",
            )
        },
        data_resource_allowlist=["data/structured-text/flavel-method-of-grace.json"],
    )
    assert [work["work_id"] for work in catalog.works] == [WORK_ID]
    work = catalog.works[0]
    route = work["reconstruction_state"]["routes"][0]
    assert route["association"] == "source_hash+exact_id"
    assert route["verification"] == "verified"
    assert route["candidate_verification"] == "verified"
    assert route["validation_verification"] == "verified"
    assert work["reconstruction_state"]["retained_source"] == "manifest_bound"
    assert work["reconstruction_state"]["tei_candidate"] == "verified"
    assert work["reconstruction_state"]["validation"] == "verified"
    assert work["reconstruction_state"]["human_review"] == "required"
    assert work["reconstruction_state"]["accepted_ir"] == "not_accepted"
