"""Current-contract regression and mutation checks for LIB-040."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from lxml import etree
import pytest

from build.lib.pytest_candidate_clone import clone_candidate_package
from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_LOCAL = ROOT / "sources/structured-text/augustine-npnf101-106-107-lib040"
MANIFEST_PATH = SOURCE_LOCAL / "lib040.source-manifest.json"
PRODUCER_PATH = ROOT / "build/tei/npnf1_lib040_reconstruction.py"
ORACLE_PATH = ROOT / "build/tei/npnf1_lib040_oracle.py"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TEI = {"tei": TEI_NS}
WORK_IDS = {
    "augustine-confessions",
    "augustine-letters-part-1",
    "augustine-sermon-on-the-mount",
    "augustine-harmony-of-gospels",
    "augustine-sermons-selected-lessons",
    "augustine-tractates-on-john",
    "augustine-homilies-on-first-john",
    "augustine-soliloquies",
}


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    assert Path(module.__file__).resolve(strict=True).samefile(path)
    return module


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _reseal(target: Path, member: str) -> CandidatePackage:
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    content = (target / member).read_bytes()
    entry = next(item for item in manifest["members"] if item["name"] == member)
    entry["bytes"] = len(content)
    entry["sha256"] = hashlib.sha256(content).hexdigest()
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(target)


@pytest.fixture(scope="module")
def current_candidate(tmp_path_factory: pytest.TempPathFactory):
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    producer = _load(PRODUCER_PATH, "_lib040_current_producer").produce
    oracle = _load(ORACLE_PATH, "_lib040_current_oracle")._oracle
    root = tmp_path_factory.mktemp("lib040-current")
    candidate = reconstruct(manifest, root / "candidate", producer)
    report = validate(manifest, candidate, oracle)
    assert report.status == "pass"
    yield manifest, candidate, oracle, report


def test_current_manifest_and_candidate_bind_exact_eight_works(current_candidate) -> None:
    manifest, candidate, _, report = current_candidate
    assert len(manifest.record["authorities"]) == 20
    configs = [
        authority
        for authority in manifest.record["authorities"]
        if authority["role"] == "local-metadata-claim-evidence"
    ]
    assert len(configs) == 8
    assert {
        json.loads((ROOT / authority["path"]).read_text(encoding="utf-8"))["resource_id"]
        for authority in configs
    } == WORK_IDS
    accountability = json.loads(
        candidate.member_bytes("source-accountability.json")
    )
    assert accountability["assigned_work_count"] == 8
    assert accountability["feature_count"] == 45_301
    assert accountability["source_id_accounting"]["occurrence_count"] == 39_623
    assert {item["work_id"] for item in accountability["work_bindings"]} == WORK_IDS
    assert report.source_manifest_sha256 == manifest.sha256
    assert report.candidate_sha256 == candidate.sha256


def test_current_candidate_has_valid_tei_and_complete_package_inventory(
    current_candidate,
) -> None:
    _, candidate, _, _ = current_candidate
    schema_path = ROOT / "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    manifest = json.loads((candidate.path / "manifest.json").read_text(encoding="utf-8"))
    from jsonschema import Draft202012Validator

    Draft202012Validator(schema).validate(manifest)
    tree = etree.parse(
        str(candidate.path / "content.tei.xml"),
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    assert tree.getroot().get(XML_ID) == "lib040-candidate"
    works = tree.xpath(
        "/tei:TEI/tei:text/tei:body/tei:div[@type='work']", namespaces=TEI
    )
    assert len(works) == 8
    assert {node.get("subtype") for node in works} == WORK_IDS
    assert set(candidate.member_names) == {
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    }


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        ("direct-text", "TEI direct text or tail drift"),
        ("crosswalk", "complete source crosswalk or work-binding drift"),
        ("provenance", "provenance disposition drift"),
        ("omit-work", "TEI work count or order shell drift"),
        ("swap-work-order", "TEI semantic attribute drift"),
        ("move-note", "TEI source tag or namespace drift"),
        ("attribute", "TEI semantic attribute drift"),
    ],
)
def test_current_oracle_rejects_meaningful_resealed_mutations(
    current_candidate, tmp_path: Path, mutation: str, expected_reason: str
) -> None:
    manifest, candidate, oracle, _ = current_candidate
    target = tmp_path / mutation
    mutable = {
        "direct-text": ("content.tei.xml", "manifest.json"),
        "crosswalk": ("source-accountability.json", "manifest.json"),
        "provenance": ("provenance.json", "manifest.json"),
        "omit-work": ("content.tei.xml", "manifest.json"),
        "swap-work-order": ("content.tei.xml", "manifest.json"),
        "move-note": ("content.tei.xml", "manifest.json"),
        "attribute": ("content.tei.xml", "manifest.json"),
    }[mutation]
    clone_candidate_package(
        candidate.path,
        target,
        hardlink_members=tuple(
            name for name in candidate.member_names if name not in mutable
        ),
    )
    if mutation in {"direct-text", "omit-work", "swap-work-order", "move-note", "attribute"}:
        tree = etree.parse(
            str(target / "content.tei.xml"),
            etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
        )
        if mutation == "direct-text":
            node = tree.xpath(
                "/tei:TEI/tei:text/tei:body//tei:p", namespaces=TEI
            )[0]
            node.text = (node.text or "") + " [mutated]"
        elif mutation == "omit-work":
            body = tree.xpath(
                "/tei:TEI/tei:text/tei:body", namespaces=TEI
            )[0]
            body.remove(body[0])
        elif mutation == "swap-work-order":
            body = tree.xpath(
                "/tei:TEI/tei:text/tei:body", namespaces=TEI
            )[0]
            second = body[1]
            body.remove(second)
            body.insert(0, second)
        elif mutation == "move-note":
            note = next(
                node
                for node in tree.xpath(
                    "/tei:TEI/tei:text/tei:body//tei:note", namespaces=TEI
                )
                if node.getparent() is not None
                and len(node.getparent()) > 1
                and node.getparent().index(node) < len(node.getparent()) - 1
            )
            parent = note.getparent()
            assert parent is not None
            parent.remove(note)
            parent.append(note)
        else:
            page_break = tree.xpath(
                "/tei:TEI/tei:text/tei:body//tei:pb[@n]", namespaces=TEI
            )[0]
            page_break.set("n", (page_break.get("n") or "") + "-mutated")
        (target / "content.tei.xml").write_bytes(
            etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
        )
        _reseal(target, "content.tei.xml")
    elif mutation == "crosswalk":
        data = json.loads(
            (target / "source-accountability.json").read_text(encoding="utf-8")
        )
        data["crosswalk"][0]["source_tag"] = "invented"
        (target / "source-accountability.json").write_bytes(_canonical(data))
        _reseal(target, "source-accountability.json")
    else:
        data = json.loads(
            (target / "provenance.json").read_text(encoding="utf-8")
        )
        data["implementation_closure"][
            "build/tei/npnf1_lib040_reconstruction.py"
        ] = "0" * 64
        (target / "provenance.json").write_bytes(_canonical(data))
        _reseal(target, "provenance.json")
    with pytest.raises(ValueError) as exc_info:
        validate(manifest, CandidatePackage.load(target), oracle)
    assert str(exc_info.value) == expected_reason


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _run_cli(destination: Path, seed: int) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = str(seed)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "build.tools.reconstruct_candidate",
            "--manifest",
            "sources/structured-text/augustine-npnf101-106-107-lib040/lib040.source-manifest.json",
            "--destination",
            str(destination),
            "--repository-root",
            str(ROOT),
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_two_clean_cli_processes_are_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    summary1 = _run_cli(first, 101)
    summary2 = _run_cli(second, 202)
    first_snapshot = _snapshot(first)
    second_snapshot = _snapshot(second)
    assert summary1["status"] == "pass"
    assert summary2["status"] == "pass"
    assert set(first_snapshot) == set(second_snapshot)
    assert all(first_snapshot[name] == second_snapshot[name] for name in first_snapshot)
    assert set(first_snapshot) == {
        "package/README.source.md", "package/content.tei.xml", "package/manifest.json",
        "package/provenance.json", "package/source-accountability.json", "package/unresolved.jsonl",
        "validation.json", "text-quality.json",
    }
    quality_sha = hashlib.sha256(first_snapshot["text-quality.json"]).hexdigest()
    assert summary1["text_quality"]["sha256"] == summary2["text_quality"]["sha256"] == quality_sha
    assert json.loads(first_snapshot["validation.json"])["text_quality_sha256"] == quality_sha
