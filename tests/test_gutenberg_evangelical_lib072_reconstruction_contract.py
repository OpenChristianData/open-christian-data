from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

from lxml import etree
import pytest

from build.tei.gutenberg_evangelical_lib072_oracle import (
    _closure_digest,
    _closure_paths,
    _oracle,
)
from build.tei.gutenberg_evangelical_lib072_reconstruction import _convert
from build.tools.count_dataset_records import collect_work_catalog
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


pytestmark = [pytest.mark.slow, pytest.mark.requires_local_artifacts]
ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "sources/structured-text/lib072-gutenberg-evangelical"
WORK_IDS = (
    "spurgeon-all-of-grace",
    "spurgeon-lectures-to-my-students",
    "torrey-how-to-pray",
    "torrey-what-the-bible-teaches",
    "wilberforce-practical-view",
)
FROZEN_CLAIMS = (
    "55256b4ebf3d44b6827411e898cff5ac7e446d5ed1f7313aedcefb4ea110ae04",
    "028f95dd26fa5b7d4788d06ee94b38128ae81e91cfc3bf46eca135339d6a920c",
    "4b36ffbaeceea58a3fc594b3521cc05ef06126c575e29daf3f4a0c545b1b6700",
    "b29553097adb3a6dde506ce329b58d1fe8c86a22da893358eb53d6c03f38a21b",
    "995ff74ac2c819b526d4874878507bb85e1141f7e5b35a388c44846a963d6c96",
)
PHYSICAL_HASHES = {
    "55256b4ebf3d44b6827411e898cff5ac7e446d5ed1f7313aedcefb4ea110ae04",
    "49f72c35a75b1052d98063fafc191ea05f009dc80d2a53953fd72076212f8e57",
    "bab94b8e4aff80d46f20134814b6393743c15f408a671e32c7ce7933ebf335f6",
    "4b36ffbaeceea58a3fc594b3521cc05ef06126c575e29daf3f4a0c545b1b6700",
    "b29553097adb3a6dde506ce329b58d1fe8c86a22da893358eb53d6c03f38a21b",
    "995ff74ac2c819b526d4874878507bb85e1141f7e5b35a388c44846a963d6c96",
}
LINE_COUNTS = {
    "spurgeon-all-of-grace": 4_981,
    "spurgeon-lectures-to-my-students": 19_534,
    "torrey-how-to-pray": 4_147,
    "torrey-what-the-bible-teaches": 26_584,
    "wilberforce-practical-view": 10_820,
}
TEI = {"tei": "http://www.tei-c.org/ns/1.0"}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _family_manifest_routes() -> tuple[tuple[str, Path], ...]:
    # These are test-runtime derivatives; retained originals remain frozen.
    return tuple(
        (
            work_id,
            ROOT / "tests/fixtures/reconstruction-runtime" / f"{work_id}-lib072.source-manifest.json",
        )
        for work_id in WORK_IDS
    )


def _reseal_member(path: Path, member_name: str) -> CandidatePackage:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == member_name)
    content = (path / member_name).read_bytes()
    member.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


@pytest.fixture(scope="module")
def verified_candidates(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, tuple[SourceManifest, CandidatePackage, object]]:
    result = {}
    for expected_work_id, manifest_path in _family_manifest_routes():
        source = SourceManifest.load(manifest_path, repository_root=ROOT)
        work_id = str(source.record["work_id"])
        assert work_id == expected_work_id
        assert work_id not in result
        candidate = reconstruct(
            source,
            tmp_path_factory.mktemp(f"lib072-{work_id}") / "candidate",
            _convert,
        )
        validation = validate(source, candidate, _oracle)
        result[work_id] = (source, candidate, validation)
    assert tuple(result) == WORK_IDS
    return result


def test_exact_sources_frozen_claims_and_complete_adjacent_accounting(
    verified_candidates: dict[str, tuple[SourceManifest, CandidatePackage, object]],
) -> None:
    observed_hashes = set()
    included_paths = set()
    for work_id, (source, candidate, validation) in verified_candidates.items():
        assert validation.status == "pass"
        observed_hashes.update(
            item["sha256"]
            for item in source.record["authorities"]
            if item["role"] == "primary-source"
        )
        accountability = json.loads(candidate.member_bytes("source-accountability.json"))
        assert accountability["total_line_count"] == LINE_COUNTS[work_id]
        assert accountability["omitted_line_count"] == 0
        assert accountability["duplicate_line_count"] == 0
        inventory = accountability["adjacent_retained_member_accounting"]
        assert len(inventory) == 49
        dispositions = {row["path"]: row["disposition"] for row in inventory}
        assert sum(row["disposition"].startswith("included") for row in inventory) == (
            accountability["assigned_member_count"]
        )
        assert sum(
            row["disposition"]
            == "excluded: exact retained member assigned to another LIB-072 work/package"
            for row in inventory
        ) == 6 - accountability["assigned_member_count"]
        assert dispositions["raw/gutenberg/martinlutheronth00luthuoft_djvu.txt"] == (
            "excluded: alternate 1823 Edward Thomas Vaughan OCR witness for LIB-075 "
            "The Bondage of the Will; the frozen LIB-075 map binds the different "
            "Henry Cole Covenanter transcription"
        )
        assert dispositions["raw/gutenberg/pg48250.txt"] == (
            "excluded: currently unmapped retained Project Gutenberg witness for John "
            "Knox's The History of the Reformation of Religion in Scotland; no current "
            "WorkCatalog or frozen ticket-map assignment"
        )
        assert dispositions["raw/ia/machen_origin_pauls_religion.txt"] == (
            "excluded: unassigned retained OCR witness for J. Gresham Machen's The "
            "Origin of Paul's Religion; it is absent from the current WorkCatalog and "
            "frozen ticket maps"
        )
        included_paths.update(
            row["path"] for row in inventory if row["disposition"].startswith("included")
        )
    assert observed_hashes == PHYSICAL_HASHES
    assert len(included_paths) == 6
    assert sum(LINE_COUNTS.values()) == 66_066
    profile = json.loads(
        (SOURCE_DIR / "gutenberg-evangelical-lib072.reconstruction-profile.json").read_bytes()
    )
    assert tuple(work["frozen_source_claim_sha256"] for work in profile["works"]) == FROZEN_CLAIMS


def test_each_tei_is_an_exact_closed_line_projection(
    verified_candidates: dict[str, tuple[SourceManifest, CandidatePackage, object]],
) -> None:
    for work_id, (_, candidate, _) in verified_candidates.items():
        tree = etree.fromstring(candidate.member_bytes("content.tei.xml"))
        texts = tree.xpath("/tei:TEI/tei:text/tei:group/tei:text", namespaces=TEI)
        assert len(texts) == 1
        assert texts[0].get("{http://www.w3.org/XML/1998/namespace}id") == work_id
        assert len(tree.xpath("//tei:ab[@type='source-line']", namespaces=TEI)) == LINE_COUNTS[work_id]
        assert not tree.xpath("//comment() | //processing-instruction()")
        provenance = json.loads(candidate.member_bytes("provenance.json"))
        assert provenance["works"][0]["accepted_ir"] == "not_accepted"
        assert provenance["works"][0]["publication"] == "not_ready"


@pytest.mark.parametrize("mutation", ["omission", "duplication", "reorder", "invention"])
def test_oracle_rejects_resealed_line_mutations(
    verified_candidates: dict[str, tuple[SourceManifest, CandidatePackage, object]],
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate, _ = verified_candidates["spurgeon-all-of-grace"]
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)
    path = target / "content.tei.xml"
    tree = etree.parse(str(path))
    division = tree.xpath("//tei:div[@type='retained-text-witness']", namespaces=TEI)[0]
    first, second = division[0], division[1]
    if mutation == "omission":
        division.remove(first)
    elif mutation == "duplication":
        division.append(etree.fromstring(etree.tostring(first)))
    elif mutation == "reorder":
        division.remove(second)
        division.insert(0, second)
    else:
        node = etree.SubElement(division, f"{{{TEI['tei']}}}ab", type="source-line", subtype="none", n="0")
        node.text = "invented"
    path.write_bytes(etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False))
    with pytest.raises(ValueError, match="LIB-072"):
        validate(source, _reseal_member(target, "content.tei.xml"), _oracle)


@pytest.mark.parametrize(
    "member",
    ["README.source.md", "provenance.json", "source-accountability.json", "unresolved.jsonl"],
)
def test_oracle_rejects_resealed_evidence_mutations(
    verified_candidates: dict[str, tuple[SourceManifest, CandidatePackage, object]],
    tmp_path: Path,
    member: str,
) -> None:
    source, candidate, _ = verified_candidates["spurgeon-all-of-grace"]
    target = tmp_path / member.replace(".", "-")
    shutil.copytree(candidate.path, target)
    path = target / member
    if member == "README.source.md":
        path.write_bytes(path.read_bytes() + b"\nPublication ready.\n")
    elif member == "unresolved.jsonl":
        path.write_bytes(b"")
    else:
        value = json.loads(path.read_bytes())
        if member == "provenance.json":
            value["works"][0]["title"] = "Invented title"
        else:
            value["works"][0]["omitted_line_count"] = 1
        path.write_bytes(_canonical(value))
    with pytest.raises(ValueError, match="LIB-072"):
        validate(source, _reseal_member(target, member), _oracle)


@pytest.mark.parametrize("mutation", ["source-id", "stale-source-manifest"])
def test_validation_rejects_resealed_source_identity_and_stale_evidence(
    verified_candidates: dict[str, tuple[SourceManifest, CandidatePackage, object]],
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate, _ = verified_candidates["spurgeon-all-of-grace"]
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)
    path = target / "manifest.json"
    manifest = json.loads(path.read_bytes())
    if mutation == "source-id":
        manifest["source_id"] = "invented-source-id"
    else:
        manifest["source_manifest"]["sha256"] = "0" * 64
    path.write_bytes(_canonical(manifest))
    with pytest.raises(ValueError, match="candidate source manifest binding mismatch"):
        validate(source, CandidatePackage.load(target), _oracle)


@pytest.mark.parametrize(
    "mutation", ["top-level-extra-key", "nested-member-extra-key", "accepted-status"]
)
def test_validation_rejects_fully_resealed_candidate_manifest_schema_mutations(
    verified_candidates: dict[str, tuple[SourceManifest, CandidatePackage, object]],
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate, _ = verified_candidates["spurgeon-all-of-grace"]
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if mutation == "top-level-extra-key":
        manifest["invented"] = "fully resealed"
    elif mutation == "nested-member-extra-key":
        manifest["members"][0]["invented"] = "fully resealed"
    else:
        manifest["status"] = "accepted"
    manifest_path.write_bytes(_canonical(manifest))
    mutated = CandidatePackage.load(target)
    with pytest.raises(ValueError, match="candidate manifest schema"):
        validate(source, mutated, _oracle)


def test_oracle_is_independent_and_closure_pin_is_current() -> None:
    oracle_path = ROOT / "build/tei/gutenberg_evangelical_lib072_oracle.py"
    parsed = ast.parse(oracle_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(parsed)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(parsed)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "build.tei.gutenberg_evangelical_lib072_reconstruction" not in imported
    assert "build.parsers.gutenberg_evangelical" not in imported
    observed_work_ids = set()
    for expected_work_id, manifest_path in _family_manifest_routes():
        source = SourceManifest.load(manifest_path, repository_root=ROOT)
        work_id = str(source.record["work_id"])
        assert work_id == expected_work_id
        assert work_id not in observed_work_ids
        observed_work_ids.add(work_id)
        policy = json.loads(source.authority_path("validation-policy").read_bytes())
        assert _closure_digest(ROOT, policy) == source.record["validator"]["import_closure_sha256"]
        assert oracle_path.resolve() in _closure_paths(ROOT, policy)
    assert observed_work_ids == set(WORK_IDS)


def test_ticket_maps_are_exact() -> None:
    work_map = (ROOT / "plans/2026-08-26-whole-library-faithful-tei-completion/02-work-ticket-map.md").read_text(encoding="utf-8")
    source_map = (ROOT / "plans/2026-08-26-whole-library-faithful-tei-completion/05-source-ticket-map.md").read_text(encoding="utf-8")
    for work_id, digest in zip(WORK_IDS, FROZEN_CLAIMS, strict=True):
        work_lines = [line for line in work_map.splitlines() if line.startswith(f"| `{work_id}` |")]
        source_lines = [line for line in source_map.splitlines() if line.startswith(f"| `{work_id}` |")]
        assert len(work_lines) == len(source_lines) == 1
        assert "| LIB-072 |" in work_lines[0]
        assert f"| `sha256:{digest}` | LIB-072 |" in source_lines[0]


def test_catalog_binds_five_explicit_current_runtime_routes(
    verified_candidates: dict[str, tuple[SourceManifest, CandidatePackage, object]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from build.tools import count_dataset_records

    manifest_paths = tuple(path for _, path in _family_manifest_routes())
    manifest_selections = tuple(path.relative_to(ROOT).as_posix() for path in manifest_paths)
    original_resolve = count_dataset_records._resolve_source_manifest_allowlist

    def resolve_test_runtime_paths(sources_root: Path, selections):
        if tuple(selections) == manifest_selections:
            assert sources_root == ROOT / "sources"
            assert all(path.parent == ROOT / "tests/fixtures/reconstruction-runtime" for path in manifest_paths)
            return sources_root, manifest_paths
        return original_resolve(sources_root, selections)

    # Only selection changes: actual authority, identity, candidate and report checks run.
    monkeypatch.setattr(
        count_dataset_records, "_resolve_source_manifest_allowlist", resolve_test_runtime_paths
    )
    resources = [f"data/structured-text/{work_id}.json" for work_id in WORK_IDS]
    for work_id, claim in zip(WORK_IDS, FROZEN_CLAIMS, strict=True):
        resource = json.loads((ROOT / f"data/structured-text/{work_id}.json").read_bytes())
        assert resource["meta"]["provenance"]["source_hash"] == f"sha256:{claim}"
    evidence = {}
    for work_id, (source, candidate, validation) in verified_candidates.items():
        record = {
            "contract": "ocd-validation-report-v1",
            "status": validation.status,
            "candidate_sha256": validation.candidate_sha256,
            "source_manifest_sha256": validation.source_manifest_sha256,
            "attestation": dict(validation.attestation),
            "findings": list(validation.findings),
            "report_sha256": validation.sha256,
        }
        path = tmp_path / f"{work_id}.validation.json"
        path.write_bytes(_canonical(record))
        evidence[(str(source.record["source_id"]), work_id)] = (candidate.path, path)
    catalog = collect_work_catalog(
        ROOT / "data",
        reconstruction_evidence=evidence,
        source_manifest_allowlist=manifest_selections,
        data_resource_allowlist=resources,
    )
    assert catalog.summary["work_units"] == len(WORK_IDS)
    by_id = {work["work_id"]: work for work in catalog.works}
    assert set(by_id) == set(WORK_IDS)
    for work_id, (source, _, _) in verified_candidates.items():
        routes = [
            route
            for route in by_id[work_id]["reconstruction_state"]["routes"]
            if route["source_id"] == source.record["source_id"]
        ]
        assert len(routes) == 1
        assert routes[0]["manifest"] == source.path.relative_to(ROOT).as_posix()
        assert routes[0]["verification"] == "verified"
        assert by_id[work_id]["source_paths"] == [f"structured-text/{work_id}.json"]
        assert routes[0]["candidate_verification"] == "verified"
        assert routes[0]["validation_verification"] == "verified"
        assert routes[0]["scope"] == "work"


def test_two_fresh_different_cwd_hash_seed_package_sets_are_byte_identical(tmp_path: Path) -> None:
    route_payload = json.dumps(
        [
            {
                "work_id": work_id,
                "path": manifest_path.relative_to(ROOT).as_posix(),
            }
            for work_id, manifest_path in _family_manifest_routes()
        ],
        separators=(",", ":"),
    )
    script = textwrap.dedent(
        """\
        from pathlib import Path
        import hashlib
        import json
        import sys

        from ocd_kernel.reconstruction import SourceManifest, reconstruct, validate
        from build.tei.gutenberg_evangelical_lib072_reconstruction import _convert
        from build.tei.gutenberg_evangelical_lib072_oracle import _oracle

        root = Path(sys.argv[1])
        dest = Path(sys.argv[2])
        routes = json.loads(sys.argv[3])
        result = {}
        for route in routes:
            source = SourceManifest.load(root / route["path"], repository_root=root)
            work_id = str(source.record["work_id"])
            assert work_id == route["work_id"]
            assert work_id not in result
            candidate = reconstruct(source, dest / work_id, _convert)
            validation = validate(source, candidate, _oracle)
            result[work_id] = {
                "candidate": candidate.sha256,
                "validation": validation.sha256,
                "members": {
                    name: hashlib.sha256(candidate.member_bytes(name)).hexdigest()
                    for name in candidate.member_names
                },
            }
        assert set(result) == {route["work_id"] for route in routes}
        print(json.dumps(result, sort_keys=True))
        """
    )
    results = []
    for ordinal, seed in enumerate(("17", "913"), 1):
        cwd = tmp_path / f"cwd-{ordinal}"
        cwd.mkdir()
        destination = tmp_path / f"packages-{ordinal}"
        destination.mkdir()
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = str(ROOT)
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    script,
                    str(ROOT),
                    str(destination),
                    route_payload,
                ],
                cwd=cwd,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            pytest.fail(
                f"fresh-process generation failed: {exc.stderr or exc.stdout}"
            )
        results.append(json.loads(completed.stdout.strip()))
    assert set(results[0]) == set(WORK_IDS)
    assert set(results[1]) == set(WORK_IDS)
    assert results[0] == results[1]
    for left in sorted((tmp_path / "packages-1").rglob("*")):
        if left.is_file():
            relative = left.relative_to(tmp_path / "packages-1")
            assert left.read_bytes() == (tmp_path / "packages-2" / relative).read_bytes()
