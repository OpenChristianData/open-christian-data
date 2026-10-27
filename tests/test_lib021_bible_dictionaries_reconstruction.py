"""Focused LIB-021 reconstruction, authority, and mutation tests."""

from __future__ import annotations

import copy
from collections.abc import Mapping
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType

import pytest
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from build.lib.tei_xsd import compiled_tei_schema


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_RELATIVE = Path("tests/fixtures/reconstruction-runtime")
RUNTIME_PRODUCER_CLOSURE = 'be675f465fa4d7c8287f3f9d1d9f8da776733c6d168c69ca448998bd2a10f34b'
RUNTIME_VALIDATOR_CLOSURE = '70aa28d47ea6d9d4ccd995e9910497c7805fce15e386b2e09d0297c13eeb0310'
RUNTIME_CLOSURE_MEMBERS = {'build/tei/bible_dictionaries_reconstruction.py': 'a5d02075c89fe2be01c7d88132ab6cd9a79ce824be539573137b13dd2d43307f', 'build/tei/bible_dictionaries_oracle.py': '2b83251ecb0a26f8cc62170b27fe7698c715cc79277f2e8da65af8bc65a35036', 'ocd_kernel/reconstruction/contract.py': '14cb0977b1fc5ff28667edceb24596d69d3034856a6996398644fcf106550d4a', 'ocd_kernel/reconstruction/__init__.py': 'e6ed13f040ada1d57354a3b8bfe7ce384be867031e017a72f027fe2d145848ca'}
RUNTIME_ORIGINAL_PINS = {
    "eastons-bible-dictionary": {
        "manifest_sha256": "bf4115996057fbd62ae37321c8d97effea8a4e8a7c8c8c2e495ed3b5dfd210ad",
        "profile_sha256": "894afb3fd1b4f7b825f0593190560e0315e148c3ff9b6c91456265574d11de16"
    },
    "hitchcocks-bible-names-dictionary": {
        "manifest_sha256": "f74999deef0bd2df1285fe57e65bddd7eabe4ae23c56e1882119f2854fc1a7f0",
        "profile_sha256": "91c63d0f705909b6e7b3f3b7fd41db558267453333b0cad3009837dcb09046db"
    },
    "smiths-bible-dictionary": {
        "manifest_sha256": "0824c442458f58cd5048f527af1f950b6f9c0b11f3cb01689c4e49d7716c47c1",
        "profile_sha256": "06d844f896fc7096db5cfafff7f869ea2be27f302f7233c3cb11fc6ea4615a61"
    }
}
DURABLE_RAW = Path(r"D:\Library\Open Christian Data\raw\bible_dictionaries")
MANIFEST_RELATIVE = "raw/bible_dictionaries/manifest.json"
RAW_ORDER = (
    "eastons.jsonl",
    "hitchcocks.jsonl",
    "smiths.jsonl",
    "torreys.jsonl",
)
RAW_MANIFEST_SHA256 = "3438b540e27f767ae4f0172a18ff466ed2d4ab5aed73a1b4af9755f92e52c37b"
FROZEN = {
    "eastons-bible-dictionary": {
        "source_id": "jwbickel-bible-dictionaries-eastons-jsonl",
        "filename": "eastons.jsonl",
        "hf_filename": "Easton's Bible Dictionary.jsonl",
        "sha256": "978e09fdb66e9c6b722085f868c0cc84030df9e15c6188a06390f3822888082a",
        "bytes": 2690740,
        "records": 3963,
        "definition_blocks": 7464,
        "ticket_order": 1,
        "raw_order": 1,
    },
    "hitchcocks-bible-names-dictionary": {
        "source_id": "jwbickel-bible-dictionaries-hitchcocks-jsonl",
        "filename": "hitchcocks.jsonl",
        "hf_filename": "Hitchcock's Bible Names Dictionary.jsonl",
        "sha256": "e25b127cfc9c6f6f14eb9aa059ea0b3ed7ceaf97e2fd88c192d74387c3e904a5",
        "bytes": 164940,
        "records": 2622,
        "definition_blocks": 2622,
        "ticket_order": 2,
        "raw_order": 2,
    },
    "smiths-bible-dictionary": {
        "source_id": "jwbickel-bible-dictionaries-smiths-jsonl",
        "filename": "smiths.jsonl",
        "hf_filename": "Smith's Bible Dictionary.jsonl",
        "sha256": "ac91b1c3c359690c2953bd94b9d3dcb34f012a69d734179e82be5f07866cbe0d",
        "bytes": 2919477,
        "records": 4560,
        "definition_blocks": 5362,
        "ticket_order": 3,
        "raw_order": 3,
    },
}
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TEI_XSD = ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _copy_route_inputs(mirror: Path) -> None:
    for work_id in FROZEN:
        source_dir = ROOT / "sources" / work_id
        mirror_dir = mirror / "sources" / work_id
        for path in source_dir.iterdir():
            if path.is_file() and path.name != "witnesses.json":
                _copy_file(path, mirror_dir / path.name)
    for work_id in FROZEN:
        for suffix in ("source-manifest.json", "reconstruction-profile.json"):
            relative = RUNTIME_RELATIVE / f"lib021-{work_id}.{suffix}"
            _copy_file(ROOT / relative, mirror / relative)
    for relative in (
        "build/tei/bible_dictionaries_reconstruction.py",
        "build/tei/bible_dictionaries_oracle.py",
        "ocd_kernel/__init__.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
    ):
        _copy_file(ROOT / relative, mirror / relative)
    source_xsd = ROOT / "ocd_kernel/tei/vendor/xsd"
    shutil.copytree(source_xsd, mirror / "ocd_kernel/tei/vendor/xsd")
    mirror_raw = mirror / "raw/bible_dictionaries"
    for path in DURABLE_RAW.iterdir():
        if path.is_file():
            _copy_file(path, mirror_raw / path.name)


@pytest.fixture(scope="session")
def validation_mirror(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not DURABLE_RAW.is_dir():
        pytest.fail(f"canonical retained raw source is unavailable: {DURABLE_RAW}")
    mirror = tmp_path_factory.mktemp("lib021-validation-mirror")
    _copy_route_inputs(mirror)
    return mirror


def _manifest_path(root: Path, work_id: str) -> Path:
    return root / RUNTIME_RELATIVE / f"lib021-{work_id}.source-manifest.json"


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _run_candidate(mirror: Path, work_id: str, destination: Path) -> dict[str, object]:
    command = [
        sys.executable,
        str(ROOT / "build/tools/reconstruct_candidate.py"),
        "--manifest",
        _manifest_path(mirror, work_id).relative_to(mirror).as_posix(),
        "--destination",
        str(destination),
        "--repository-root",
        str(mirror),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="session")
def built_candidates(
    validation_mirror: Path, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, tuple[Path, Path]]:
    destinations = tmp_path_factory.mktemp("lib021-candidates")
    result: dict[str, tuple[Path, Path]] = {}
    for work_id in FROZEN:
        first = destinations / f"{work_id}-first"
        second = destinations / f"{work_id}-second"
        first_summary = _run_candidate(validation_mirror, work_id, first)
        second_summary = _run_candidate(validation_mirror, work_id, second)
        assert first_summary["status"] == "pass"
        assert second_summary["status"] == "pass"
        result[work_id] = (first, second)
    return result


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _load_implementation_module(mirror: Path, work_id: str, relative: str) -> ModuleType:
    path = mirror / relative
    name = f"_lib021_test_{Path(relative).stem}_{work_id}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_oracle_module(mirror: Path, work_id: str) -> ModuleType:
    return _load_implementation_module(mirror, work_id, "build/tei/bible_dictionaries_oracle.py")


def _reseal(candidate_dir: Path) -> None:
    manifest_path = candidate_dir / "manifest.json"
    manifest = _load_json(manifest_path)
    members = manifest["members"]
    assert isinstance(members, list)
    for member in members:
        assert isinstance(member, dict)
        name = member["name"]
        assert isinstance(name, str)
        content = (candidate_dir / name).read_bytes()
        member["bytes"] = len(content)
        member["sha256"] = _sha(content)
    manifest_path.write_bytes(
        (
            json.dumps(
                manifest,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    )


def _expect_mutation_rejected(
    validation_mirror: Path,
    built_candidates: dict[str, tuple[Path, Path]],
    tmp_path: Path,
    work_id: str,
    mutate,
) -> None:
    source_manifest = SourceManifest.load(
        _manifest_path(validation_mirror, work_id), repository_root=validation_mirror
    )
    candidate_dir = tmp_path / work_id / "candidate"
    candidate_dir.parent.mkdir()
    shutil.copytree(built_candidates[work_id][0] / "package", candidate_dir)
    mutate(candidate_dir)
    _reseal(candidate_dir)
    candidate = CandidatePackage.load(candidate_dir)
    oracle_module = _load_oracle_module(validation_mirror, work_id)
    with pytest.raises(ValueError):
        validate(source_manifest, candidate, oracle_module._oracle)


def _assert_schema_valid_tei(path: Path) -> None:
    schema = compiled_tei_schema(TEI_XSD)
    document = etree.parse(str(path))
    assert schema.validate(document), str(schema.error_log)


@pytest.mark.parametrize("work_id", FROZEN)
def test_runtime_fixture_preserves_complete_record_except_declared_closures(work_id: str) -> None:
    original = ROOT / "sources" / work_id / f"{work_id}.source-manifest.json"
    raw = original.read_bytes()
    assert _sha(raw) == RUNTIME_ORIGINAL_PINS[work_id]["manifest_sha256"]
    expected = json.loads(raw)
    profile_authority = next(a for a in expected["authorities"] if a["name"] == "reconstruction-profile")
    profile_raw = (ROOT / profile_authority["path"]).read_bytes()
    assert _sha(profile_raw) == RUNTIME_ORIGINAL_PINS[work_id]["profile_sha256"]
    expected_profile = json.loads(profile_raw)
    expected_profile["producer_import_closure_sha256"] = RUNTIME_PRODUCER_CLOSURE
    runtime_profile = ROOT / RUNTIME_RELATIVE / f"lib021-{work_id}.reconstruction-profile.json"
    runtime_profile_raw = runtime_profile.read_bytes()
    assert json.loads(runtime_profile_raw) == expected_profile
    expected["producer_import_closure_sha256"] = RUNTIME_PRODUCER_CLOSURE
    expected["validator"]["import_closure_sha256"] = RUNTIME_VALIDATOR_CLOSURE
    profile_authority.update(path=runtime_profile.relative_to(ROOT).as_posix(),
                             bytes=len(runtime_profile_raw), sha256=_sha(runtime_profile_raw))
    runtime_manifest = _manifest_path(ROOT, work_id)
    assert json.loads(runtime_manifest.read_bytes()) == expected
    SourceManifest.load(runtime_manifest, repository_root=ROOT)


def test_runtime_closures_bind_exact_reviewed_dependency_bytes() -> None:
    # Fixed reviewed file identities independently constrain both real helpers.
    for relative, expected in RUNTIME_CLOSURE_MEMBERS.items():
        assert _sha((ROOT / relative).read_bytes()) == expected
    for implementation, expected in (
        ("build/tei/bible_dictionaries_reconstruction.py", RUNTIME_PRODUCER_CLOSURE),
        ("build/tei/bible_dictionaries_oracle.py", RUNTIME_VALIDATOR_CLOSURE),
    ):
        records = [{"path": relative, "sha256": RUNTIME_CLOSURE_MEMBERS[relative]}
                   for relative in sorted((implementation, "ocd_kernel/reconstruction/contract.py",
                                           "ocd_kernel/reconstruction/__init__.py"))]
        canonical = (json.dumps(records, sort_keys=True, separators=(",", ":")) + "\n").encode()
        assert _sha(canonical) == expected
        module = _load_implementation_module(ROOT, "reviewed_closure", implementation)
        if implementation.endswith("_oracle.py"):
            assert module._closure(ROOT) == expected
        else:
            manifest = SourceManifest.load(_manifest_path(ROOT, "eastons-bible-dictionary"), repository_root=ROOT)
            policy = json.loads(manifest.authority_path("validation-policy").read_bytes())
            assert module._closure_digest(ROOT, policy) == expected


@pytest.mark.parametrize("relative", ["ocd_kernel/reconstruction/contract.py", "ocd_kernel/reconstruction/__init__.py"])
def test_oracle_rejects_actual_dependency_byte_tampering(
    relative: str, validation_mirror: Path, built_candidates: dict[str, tuple[Path, Path]], tmp_path: Path,
) -> None:
    mirror = tmp_path / "tampered-runtime"
    shutil.copytree(validation_mirror, mirror)
    dependency = mirror / relative
    dependency.write_bytes(dependency.read_bytes() + b"\n# Changed dependency bytes.\n")
    work_id = "eastons-bible-dictionary"
    source_manifest = SourceManifest.load(_manifest_path(mirror, work_id), repository_root=mirror)
    candidate = CandidatePackage.load(built_candidates[work_id][0] / "package")
    oracle_module = _load_oracle_module(mirror, work_id)
    with pytest.raises(ValueError, match="LIB-021 oracle import closure drift"):
        validate(source_manifest, candidate, oracle_module._oracle)


def test_frozen_source_claims_and_complete_census(validation_mirror: Path) -> None:
    raw_manifest = _load_json(validation_mirror / MANIFEST_RELATIVE)
    assert (
        _sha((validation_mirror / MANIFEST_RELATIVE).read_bytes())
        == RAW_MANIFEST_SHA256
    )
    files = raw_manifest["files"]
    assert isinstance(files, list)
    assert [item["local_filename"] for item in files] == list(RAW_ORDER)
    for work_id, expected in FROZEN.items():
        source_manifest = SourceManifest.load(
            _manifest_path(validation_mirror, work_id),
            repository_root=validation_mirror,
        )
        record = source_manifest.record
        assert record["ticket_id"] == "LIB-021"
        assert record["work_id"] == work_id
        assert record["source_id"] == expected["source_id"]
        assert record["source_order"] == {
            "ticket_order": expected["ticket_order"],
            "raw_manifest_order": expected["raw_order"],
            "raw_manifest_path": MANIFEST_RELATIVE,
        }
        census = record["retained_member_census"]
        assert isinstance(census, Mapping)
        assert census["dataset_manifest_sha256"] == RAW_MANIFEST_SHA256
        retained = census["retained"]
        assert isinstance(retained, (list, tuple)) and len(retained) == 1
        assert retained[0]["local_filename"] == expected["filename"]
        assert retained[0]["hf_filename"] == expected["hf_filename"]
        assert retained[0]["bytes"] == expected["bytes"]
        assert retained[0]["sha256"] == expected["sha256"]
        assert retained[0]["records"] == expected["records"]
        assert retained[0]["definition_blocks"] == expected["definition_blocks"]
        excluded = census["excluded"]
        assert isinstance(excluded, (list, tuple))
        assert [item["local_filename"] for item in excluded] == [
            item["local_filename"]
            for item in files
            if item["local_filename"] != expected["filename"]
        ]
        assert all(item["reason"] for item in excluded)


def test_candidate_is_nonaccepted_schema_validated_and_accounted(
    built_candidates: dict[str, tuple[Path, Path]],
) -> None:
    for work_id, (first, _) in built_candidates.items():
        package = CandidatePackage.load(first / "package")
        assert package.manifest["status"] == "nonaccepted"
        assert package.manifest["source_id"] == FROZEN[work_id]["source_id"]
        validation = _load_json(first / "validation.json")
        assert validation["status"] == "pass"
        assert validation["findings"] == []
        accountability = _load_json(package.path / "source-accountability.json")
        counts = accountability["observation_counts"]
        assert isinstance(counts, dict)
        assert counts["omitted"] == 0
        assert counts["duplicate"] == 0


def test_two_fresh_process_runs_are_byte_identical(
    built_candidates: dict[str, tuple[Path, Path]],
) -> None:
    for first, second in built_candidates.values():
        assert _tree_bytes(first) == _tree_bytes(second)


def test_oracle_is_independent_from_dictionary_producer() -> None:
    oracle_text = (ROOT / "build/tei/bible_dictionaries_oracle.py").read_text(
        encoding="utf-8"
    )
    assert "bible_dictionaries_reconstruction" not in oracle_text
    assert "build.parsers.bible_dictionaries" not in oracle_text
    assert "build/parsers/bible_dictionaries.py" not in oracle_text


def _remove_last_entry(candidate_dir: Path) -> None:
    path = candidate_dir / "content.tei.xml"
    root = etree.fromstring(path.read_bytes())
    body = root.find(f"{{{TEI_NS}}}text/{{{TEI_NS}}}body")
    assert body is not None
    body.remove(body[-1])
    path.write_bytes(
        etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    )


def _duplicate_first_entry(candidate_dir: Path) -> None:
    path = candidate_dir / "content.tei.xml"
    root = etree.fromstring(path.read_bytes())
    body = root.find(f"{{{TEI_NS}}}text/{{{TEI_NS}}}body")
    assert body is not None
    duplicate = copy.deepcopy(body[0])
    duplicate.set("n", str(len(body) + 1))
    duplicate.set(XML_ID, f"{duplicate.get(XML_ID)}-duplicate")
    body.append(duplicate)
    path.write_bytes(
        etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    )


def _reorder_entries(candidate_dir: Path) -> None:
    path = candidate_dir / "content.tei.xml"
    root = etree.fromstring(path.read_bytes())
    body = root.find(f"{{{TEI_NS}}}text/{{{TEI_NS}}}body")
    assert body is not None
    first, second = body[0], body[1]
    body.remove(first)
    body.remove(second)
    body.insert(0, second)
    body.insert(1, first)
    path.write_bytes(
        etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    )


def _invent_text(candidate_dir: Path) -> None:
    path = candidate_dir / "content.tei.xml"
    root = etree.fromstring(path.read_bytes())
    paragraph = root.find(
        f"{{{TEI_NS}}}text/{{{TEI_NS}}}body/{{{TEI_NS}}}entry/{{{TEI_NS}}}sense/{{{TEI_NS}}}def"
    )
    assert paragraph is not None and paragraph.text is not None
    paragraph.text += " INVENTED"
    path.write_bytes(
        etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    )


def _invent_attribute(candidate_dir: Path) -> None:
    path = candidate_dir / "content.tei.xml"
    root = etree.fromstring(path.read_bytes())
    entry = root.find(f"{{{TEI_NS}}}text/{{{TEI_NS}}}body/{{{TEI_NS}}}entry")
    assert entry is not None
    entry.set("type", "invented-entry-type")
    path.write_bytes(
        etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    )


def _invent_definition_attribute(candidate_dir: Path) -> None:
    path = candidate_dir / "content.tei.xml"
    root = etree.fromstring(path.read_bytes())
    paragraph = root.find(
        f"{{{TEI_NS}}}text/{{{TEI_NS}}}body/{{{TEI_NS}}}entry/{{{TEI_NS}}}sense/{{{TEI_NS}}}def"
    )
    assert paragraph is not None
    paragraph.set("rend", "invented-definition-rendition")
    path.write_bytes(
        etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=True,
        )
    )
    _assert_schema_valid_tei(path)


def _invent_nested_definition_content(candidate_dir: Path) -> None:
    path = candidate_dir / "content.tei.xml"
    root = etree.fromstring(path.read_bytes())
    paragraph = root.find(
        f"{{{TEI_NS}}}text/{{{TEI_NS}}}body/{{{TEI_NS}}}entry/{{{TEI_NS}}}sense/{{{TEI_NS}}}def"
    )
    assert paragraph is not None and paragraph.text is not None
    original = paragraph.text
    paragraph.text = original[:1]
    nested = etree.SubElement(paragraph, f"{{{TEI_NS}}}hi")
    nested.text = original[1:2] or "invented"
    nested.tail = original[2:]
    path.write_bytes(
        etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=True,
        )
    )
    _assert_schema_valid_tei(path)


def _drift_tail_whitespace(candidate_dir: Path) -> None:
    path = candidate_dir / "content.tei.xml"
    root = etree.fromstring(path.read_bytes())
    form = root.find(
        f"{{{TEI_NS}}}text/{{{TEI_NS}}}body/{{{TEI_NS}}}entry/{{{TEI_NS}}}form"
    )
    assert form is not None
    assert form.tail is not None
    form.tail += " "
    path.write_bytes(
        etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=True,
        )
    )
    _assert_schema_valid_tei(path)


def _invent_header_structure(candidate_dir: Path) -> None:
    path = candidate_dir / "content.tei.xml"
    root = etree.fromstring(path.read_bytes())
    encoding = root.find(f"{{{TEI_NS}}}teiHeader/{{{TEI_NS}}}encodingDesc")
    assert encoding is not None
    extra = etree.SubElement(encoding, f"{{{TEI_NS}}}p")
    extra.text = "Invented header statement"
    path.write_bytes(
        etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=True,
        )
    )
    _assert_schema_valid_tei(path)


def _invent_body_structure(candidate_dir: Path) -> None:
    path = candidate_dir / "content.tei.xml"
    root = etree.fromstring(path.read_bytes())
    body = root.find(f"{{{TEI_NS}}}text/{{{TEI_NS}}}body")
    assert body is not None
    extra = etree.SubElement(body, f"{{{TEI_NS}}}div")
    paragraph = etree.SubElement(extra, f"{{{TEI_NS}}}p")
    paragraph.text = "Invented body content"
    path.write_bytes(
        etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=True,
        )
    )
    _assert_schema_valid_tei(path)


def _drift_metadata(candidate_dir: Path) -> None:
    path = candidate_dir / "content.tei.xml"
    root = etree.fromstring(path.read_bytes())
    title = root.find(
        f"{{{TEI_NS}}}teiHeader/{{{TEI_NS}}}fileDesc/{{{TEI_NS}}}titleStmt/{{{TEI_NS}}}title"
    )
    assert title is not None
    title.text = "Invented title"
    path.write_bytes(
        etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    )


def _drift_source_order(candidate_dir: Path) -> None:
    path = candidate_dir / "content.tei.xml"
    root = etree.fromstring(path.read_bytes())
    entry = root.find(f"{{{TEI_NS}}}text/{{{TEI_NS}}}body/{{{TEI_NS}}}entry")
    assert entry is not None
    entry.set("n", "999999")
    path.write_bytes(
        etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    )


def _drift_evidence(candidate_dir: Path) -> None:
    path = candidate_dir / "source-accountability.json"
    record = _load_json(path)
    crosswalk = record["crosswalk"]
    assert isinstance(crosswalk, list)
    crosswalk[0]["source_term"] += " invented"
    path.write_bytes(
        (
            json.dumps(
                record, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
            + "\n"
        ).encode("utf-8")
    )


def _drift_provenance(candidate_dir: Path) -> None:
    path = candidate_dir / "provenance.json"
    record = _load_json(path)
    record["status"] = "accepted"
    path.write_bytes(
        (
            json.dumps(
                record, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
            + "\n"
        ).encode("utf-8")
    )


def _drift_unresolved(candidate_dir: Path) -> None:
    (candidate_dir / "unresolved.jsonl").write_bytes(b"{}\n")


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        ("omission", _remove_last_entry),
        ("duplication", _duplicate_first_entry),
        ("reorder", _reorder_entries),
        ("text invention", _invent_text),
        ("attribute invention", _invent_attribute),
        ("definition attribute invention", _invent_definition_attribute),
        ("nested definition invention", _invent_nested_definition_content),
        ("tail whitespace drift", _drift_tail_whitespace),
        ("header structure invention", _invent_header_structure),
        ("body structure invention", _invent_body_structure),
        ("metadata drift", _drift_metadata),
        ("source-order drift", _drift_source_order),
        ("evidence drift", _drift_evidence),
        ("provenance drift", _drift_provenance),
        ("unresolved rows", _drift_unresolved),
    ],
)
def test_required_mutations_are_rejected(
    label: str,
    mutate,
    validation_mirror: Path,
    built_candidates: dict[str, tuple[Path, Path]],
    tmp_path: Path,
) -> None:
    del label
    for work_id in FROZEN:
        _expect_mutation_rejected(
            validation_mirror,
            built_candidates,
            tmp_path,
            work_id,
            mutate,
        )


def test_stale_retained_source_hash_is_rejected(
    validation_mirror: Path,
    tmp_path: Path,
) -> None:
    stale_mirror = tmp_path / "stale-mirror"
    shutil.copytree(validation_mirror, stale_mirror)
    source = stale_mirror / "raw/bible_dictionaries/eastons.jsonl"
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="authority bytes drifted"):
        SourceManifest.load(
            _manifest_path(stale_mirror, "eastons-bible-dictionary"),
            repository_root=stale_mirror,
        )


def test_stale_manifest_evidence_is_rejected(
    validation_mirror: Path,
) -> None:
    path = validation_mirror / MANIFEST_RELATIVE
    original = path.read_bytes()
    path.write_bytes(original + b"\n")
    with pytest.raises(ValueError, match="authority bytes drifted"):
        SourceManifest.load(
            _manifest_path(validation_mirror, "smiths-bible-dictionary"),
            repository_root=validation_mirror,
        )
