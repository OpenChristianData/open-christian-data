from __future__ import annotations

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
MANIFEST_PATH = Path('tests/fixtures/reconstruction-runtime/edwards-religious-affections.source-manifest.json')
SOURCE_PATH = "raw/ccel/edwards/affections.xml"
SOURCE_SHA256 = "2ffd4300ada5d0cc5b3929ed5b61ed0e1053042a065419ee35943facc79738ce"
SOURCE_BYTES = 1_183_960
SOURCE_DIV1_IDS = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii")
TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS}


def _bound_callable(manifest: SourceManifest, role: str):
    binding = manifest.record[role]
    assert isinstance(binding, dict) or hasattr(binding, "get")
    path = ROOT / str(binding["implementation_path"])
    module_name = f"_test_37c142_{role}_{binding['implementation_sha256']}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return getattr(module, str(binding["callable"]))


@pytest.fixture(scope="session")
def route():
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    return manifest, _bound_callable(manifest, "converter"), _bound_callable(manifest, "validator")


@pytest.fixture
def candidate(route, tmp_path):
    manifest, converter, _oracle = route
    return reconstruct(manifest, tmp_path / "candidate", converter)


def test_manifest_binds_only_the_exact_37c_142_work_and_retained_member():
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    record = manifest.record
    source_authorities = [
        authority
        for authority in record["authorities"]
        if authority.get("role") == "primary-source"
    ]

    assert record["ticket"] == "37c-142"
    assert record["owner_route"] == "LIB-055"
    assert record["work_id"] == "edwards-religious-affections"
    assert record["identity"]["work_id"] == "edwards-religious-affections"
    assert record["identity"]["textual_form"] is None
    assert record["identity"]["edition"] is None
    assert record["identity"]["parts"] is None
    assert record["identity"]["witness_claim"] is None
    assert len(source_authorities) == 1
    assert source_authorities[0]["path"] == SOURCE_PATH
    assert source_authorities[0]["bytes"] == SOURCE_BYTES
    assert source_authorities[0]["sha256"] == SOURCE_SHA256
    assert tuple(record["scope"]["member_order"]) == (SOURCE_PATH,)
    assert tuple(record["scope"]["top_level_div1_ids"]) == SOURCE_DIV1_IDS


def test_candidate_accounts_for_the_full_envelope_and_emits_readable_tei(route, candidate):
    manifest, _converter, oracle = route
    report = validate(manifest, candidate, oracle)
    assert report.status == "pass"
    assert candidate.manifest["status"] == "nonaccepted"
    assert set(candidate.member_names) == {
        "content.tei.xml",
        "source-accountability.json",
        "provenance.json",
        "unresolved.jsonl",
        "README.source.md",
        "manifest.json",
    }

    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert tei.tag == f"{{{TEI_NS}}}TEI"
    divisions = tei.findall("./tei:text/tei:body/tei:div", NS)
    assert [item.get("{http://www.w3.org/XML/1998/namespace}id") for item in divisions] == list(
        SOURCE_DIV1_IDS
    )
    assert tei.findtext("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=NS) == (
        "Religious Affections"
    )

    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["work_id"] == "edwards-religious-affections"
    assert accountability["source_member"]["sha256"] == SOURCE_SHA256
    assert accountability["source_envelope"]["doctype"]["public_id"].startswith("-//CCEL/")
    assert accountability["source_envelope"]["counts"]["body_elements_including_wrapper"] == 3373
    assert len(accountability["elements"]) == 3420
    assert "sourced via CCEL.org" in candidate.member_bytes("README.source.md").decode("utf-8")


def test_exact_candidate_is_admitted_by_the_bounded_workcatalog_route(tmp_path, monkeypatch):
    destination = tmp_path / "candidate-run"
    result = subprocess.run(
        [
            sys.executable,
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
    assert result.returncode == 0, result.stdout + result.stderr

    from build.tools.count_dataset_records import collect_work_catalog
    from build.tools import count_dataset_records

    def selected_paths(sources_root, selections):
        assert sources_root == ROOT / "sources"
        assert tuple(selections) == (MANIFEST_PATH.as_posix(),)
        return sources_root, (ROOT / MANIFEST_PATH,)

    original_identity = count_dataset_records._runtime_policy_identity

    def identity(source, record, path, sources_root, **kwargs):
        retained = ROOT / "sources/structured-text/edwards-religious-affections/lib055/37c-142.source-manifest.json"
        return original_identity(source, record, retained if path == ROOT / MANIFEST_PATH else path,
                                 sources_root, **kwargs)

    monkeypatch.setattr(count_dataset_records, "_resolve_source_manifest_allowlist", selected_paths)
    monkeypatch.setattr(count_dataset_records, "_runtime_policy_identity", identity)

    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    work_catalog = collect_work_catalog(
        ROOT / "data",
        reconstruction_evidence={
            (manifest.record["source_id"], manifest.record["work_id"]): (
                destination / "package",
                destination / "validation.json",
            )
        },
        source_manifest_allowlist=[MANIFEST_PATH.as_posix()],
        data_resource_allowlist=[
            "data/structured-text/edwards-religious-affections.json"
        ],
    )

    assert [work["work_id"] for work in work_catalog.works] == [
        "edwards-religious-affections"
    ]
    work = work_catalog.works[0]
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


def _rewrite_member(candidate: CandidatePackage, name: str, update) -> CandidatePackage:
    package_path = candidate.path
    content = (package_path / name).read_bytes()
    changed = update(content)
    (package_path / name).write_bytes(changed)

    manifest_path = package_path / "manifest.json"
    manifest_record = json.loads(manifest_path.read_bytes())
    for member in manifest_record["members"]:
        if member["name"] == name:
            member["bytes"] = len(changed)
            member["sha256"] = hashlib.sha256(changed).hexdigest()
            break
    manifest_path.write_text(
        json.dumps(manifest_record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return CandidatePackage.load(package_path)


@pytest.mark.parametrize("mutation", ("reorder-divisions", "drop-marker", "alter-reference", "drift-title"))
def test_independent_oracle_rejects_source_meaning_mutations(route, candidate, mutation):
    manifest, _converter, oracle = route

    def mutate_tei(content: bytes) -> bytes:
        root = etree.fromstring(content)
        body = root.find("./tei:text/tei:body", NS)
        assert body is not None
        if mutation == "reorder-divisions":
            first, second = body.findall("./tei:div", NS)[:2]
            body.remove(first)
            body.insert(1, first)
        elif mutation == "drop-marker":
            marker = root.find(".//tei:anchor[@type='scripture-commentary-marker']", NS)
            assert marker is not None
            marker.getparent().remove(marker)
        elif mutation == "alter-reference":
            reference = root.find(".//tei:ref[@type='scripture']", NS)
            assert reference is not None and reference.text
            reference.text += " altered"
        else:
            title = root.find("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", NS)
            assert title is not None
            title.text = "A different title"
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True)

    changed_candidate = _rewrite_member(
        candidate,
        "content.tei.xml",
        mutate_tei,
    )
    with pytest.raises(ValueError):
        validate(manifest, changed_candidate, oracle)


def test_fresh_process_reproduction_matches_every_package_byte(tmp_path):
    outputs: list[dict[str, bytes]] = []
    for label in ("first", "second"):
        destination = tmp_path / label
        result = subprocess.run(
            [
                sys.executable,
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
        assert result.returncode == 0, result.stdout + result.stderr
        outputs.append(
            {
                path.relative_to(destination).as_posix(): path.read_bytes()
                for path in sorted(destination.rglob("*"))
                if path.is_file()
            }
        )

    assert outputs[0] == outputs[1]
