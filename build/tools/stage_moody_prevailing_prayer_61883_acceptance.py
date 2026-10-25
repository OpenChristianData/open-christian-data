"""Stage a source-bound agent acceptance for the retained PG61883 witness.

The stage is created outside the canonical library. It accepts one complete
English electronic witness for *Prevailing Prayer: What Hinders It?*; it does
not claim completeness across Moody's other writings, rights clearance, print
collation, human review, or publication.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile
from lxml import etree

from ocd_kernel.library.acquisitions import source_member_set_bytes, validate_acquisition
from ocd_kernel.lib.path_io import resolve_path
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "d-l-moody-prevailing-prayer"
FORM_ID = "english"
EDITION_ID = "d-l-moody-prevailing-prayer-pg61883"
ACQUISITION_ID = "pg61883-retained-zip"
PROJECTION_PROFILE = "ocd-prose-moody-pg61883-source-native-v1"
IDENTITY = dict(work_id=WORK_ID, textual_form_id=FORM_ID,
                edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)
WORK = Path("library/works") / WORK_ID
EDITION = Path("forms") / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
MEMBER_SET = EDITION / "source-member-set.json"
MEMBER_SET_PATH = WORK / MEMBER_SET
MASTER = EDITION / "master.tei.xml"
ACCEPTANCE = EDITION / "acceptance.json"
EVIDENCE = Path("integration/moody-pg61883-electronic-acceptance-v1")
PROPOSAL = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/MOODY_PG61883_IDENTITY_PROPOSAL_20261003.json")
CLOSURE = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/MOODY_PG61883_V3_CANDIDATE_CLOSURE_20261003.json")
CHALLENGES = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/MOODY_PG61883_V3_ACCOUNTABILITY_CHALLENGES_20261003.json")
CHALLENGES_ERRATUM = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/MOODY_PG61883_V3_ACCOUNTABILITY_CHALLENGES_ERRATUM_20261003.json")
V2_REVIEW = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/MOODY_PG61883_CANDIDATE_INDEPENDENT_REVIEW_20261003.json")
TEST_FILE = Path("tests/test_moody_prevailing_prayer_61883_v3_reconstruction.py")
TEST_SHA = "72ef692fd240472071cec6ce1e26494320351f72f69df78808e4d21aef9e978d"
SOURCE_MANIFEST = Path("sources/manifest-acquisitions/moody-prevailing-prayer-pg61883-v3/source-manifest.json")
SOURCE_MANIFEST_SHA = "d0fa96b1f2d9ec7378c010c03cd1d50bff8d0ceca752efa5be1016d282b4de6b"
PROFILE_SHA = "45df4d350de44400a25090c81d6b648dc70808e3eee81a334faf0d76f520ff32"
IMPLEMENTATION_SHA = "ef24130de0c13b19b47da5132cf536f75558bbe8235cf5bf884633eac9216041"
IMPORT_CLOSURE_SHA = "6edf5c1cfc3c3e7fdb4e575f319231e5e07f511182c654cec087796f3888923c"
ARCHIVE_SHA = "c3e9023f2c0e1065e4f2601c21b791ef50f94f1acb31ef4c61880b7592a3ff19"
PACKAGE_SHA = "913bc2d562273e17fbe611cdfd5d889cde440fcfaedca2be24c4e3a6defc0b27"
TEI_SHA = "9037804ddb27e710c1a29982ffdf1c804e38bbab54b0d8dbcb5d2e238172d7d9"
VALIDATION_FILE_SHA = "6fd194f4bb307db1cb2dfc353e3a0f40ba2d9b36838d8bd735b2a019a9890256"
ACCOUNTABILITY_SHA = "8cf335ddbcd5536472103629965b8d00605c61fc2feaac9528c29e33169de1e6"
MEMBER_SET_SHA = "b332decb87837d629d696537ab7a59143752335c2a38b3ad6cfd3bf2e8b4c7af"
CANDIDATE_OUTPUT = Path("D:/Library/Open Christian Data/candidate-reviews/moody-prevailing-prayer-pg61883-v3-candidate-20261003/package")
REPLAY_OUTPUT = Path("D:/Library/Open Christian Data/candidate-reviews/moody-prevailing-prayer-pg61883-v3-replay-20261003/package")
DEFAULT_STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/moody-prevailing-prayer-pg61883-acceptance-stage-20261003-v1")
CONTRACT = "ocd-moody-pg61883-electronic-acceptance-stage-v1"
RUNTIME_JSON_SCHEMAS = (
    Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"),
    Path("schemas/v2/acceptance.schema.json"),
    Path("schemas/v2/work.schema.json"),
    Path("schemas/v2/acquisition.schema.json"),
    Path("schemas/v2/state.schema.json"),
    Path("schemas/v2/categories/prose.schema.json"),
    Path("schemas/v2/native-content.schema.json"),
    Path("schemas/v2/public-row.schema.json"),
    Path("schemas/v2/tei/controlled-values.json"),
)
RUNTIME_XSD_ROOT = Path("ocd_kernel/tei/vendor/xsd/tei_all.xsd")
RUNTIME_ENTRYPOINTS = (
    Path(__file__).resolve(),
    ROOT / "build/tools/install_moody_prevailing_prayer_61883.py",
)


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    data = _io_path(path).read_bytes()
    actual = sha256(data).hexdigest()
    if expected is not None and actual != expected:
        raise ValueError(f"Moody PG61883 pinned bytes differ: {path} ({actual})")
    return data


def _json(path: Path, expected: str | None = None) -> dict:
    value = json.loads(_read(path, expected))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _put(stage: Path, relative: Path, data: bytes) -> Path:
    target = stage / relative
    _io_path(target.parent).mkdir(parents=True, exist_ok=True)
    _io_path(target).write_bytes(data)
    return target


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    data = (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    return _put(stage, relative, data)


def _copy_pinned(stage: Path, relative: Path, expected: str | None = None) -> Path:
    return _put(stage, relative, _read(ROOT / relative, expected))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha_member(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _validate_sha_constants() -> None:
    pins = {
        "source manifest": SOURCE_MANIFEST_SHA, "source profile": PROFILE_SHA,
        "converter": IMPLEMENTATION_SHA, "import closure": IMPORT_CLOSURE_SHA,
        "archive": ARCHIVE_SHA, "candidate package": PACKAGE_SHA,
        "candidate TEI": TEI_SHA, "validation file": VALIDATION_FILE_SHA,
        "accountability ledger": ACCOUNTABILITY_SHA,
        "member set": MEMBER_SET_SHA, "reconstruction tests": TEST_SHA,
    }
    for label, value in pins.items():
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(f"{label} SHA-256 pin must contain exactly 64 lowercase hex characters")


def _loaded_first_party_modules() -> list[dict]:
    """Pin every loaded Python source file under this repository's build/kernel roots."""
    root = resolve_path(ROOT, strict=True)
    names_by_path: dict[str, set[str]] = {}
    for name, module in tuple(sys.modules.items()):
        source = getattr(module, "__file__", None)
        if not isinstance(source, str) or not source:
            continue
        try:
            path = resolve_path(Path(source), strict=True)
            relative = path.relative_to(root)
        except (OSError, ValueError):
            continue
        if (relative.parts[0] not in {"build", "ocd_kernel"}
                or relative.parts[:2] == ("build", "tools")
                or path.suffix.lower() != ".py"):
            continue
        names_by_path.setdefault(relative.as_posix(), set()).add(name)
    modules = []
    for relative, names in sorted(names_by_path.items()):
        data = _io_path(ROOT / relative).read_bytes()
        modules.append({"path": relative, "module_names": sorted(names),
                        "bytes": len(data), "sha256": sha256(data).hexdigest()})
    if not modules:
        raise ValueError("runtime closure captured no first-party Python modules")
    return modules


def _runtime_schema_paths() -> list[Path]:
    """Resolve the executed JSON schemas and the complete local TEI XSD import graph."""
    paths = set(RUNTIME_JSON_SCHEMAS)
    pending = [RUNTIME_XSD_ROOT]
    while pending:
        relative = pending.pop()
        if relative in paths:
            continue
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe runtime schema reference: {relative}")
        payload = _read(ROOT / relative)
        paths.add(relative)
        if relative.suffix.lower() != ".xsd":
            continue
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        schema = etree.fromstring(payload, parser=parser)
        for node in schema.iter():
            if not isinstance(node.tag, str):
                continue
            if etree.QName(node).localname not in {"include", "import", "redefine"}:
                continue
            location = node.get("schemaLocation")
            if not location:
                continue
            if "://" in location or PurePosixPath(location).is_absolute():
                raise ValueError(f"runtime XSD has a nonlocal import: {location}")
            pending.append(relative.parent / Path(location))
    for relative in RUNTIME_JSON_SCHEMAS:
        if not _io_path(ROOT / relative).is_file():
            raise ValueError(f"runtime JSON schema is missing: {relative}")
    return sorted(paths, key=lambda item: item.as_posix())


def _capture_runtime_closure(stage: Path) -> tuple[Path, dict]:
    modules = _loaded_first_party_modules()
    schemas = []
    for relative in _runtime_schema_paths():
        data = _read(ROOT / relative)
        schemas.append({"path": relative.as_posix(), "bytes": len(data),
                        "sha256": sha256(data).hexdigest()})
    drivers = []
    captured: dict[str, tuple[bytes, str]] = {}
    for record in modules:
        relative = record["path"]
        captured[relative] = (_read(ROOT / relative, record["sha256"]), "loaded-first-party-module")
    for record in schemas:
        relative = record["path"]
        captured[relative] = (_read(ROOT / relative, record["sha256"]), "loaded-schema-resource")
    for absolute in RUNTIME_ENTRYPOINTS:
        resolved = resolve_path(absolute, strict=True)
        try:
            relative = resolved.relative_to(resolve_path(ROOT, strict=True)).as_posix()
        except ValueError as exc:
            raise ValueError(f"runtime entrypoint is outside the repository: {absolute}") from exc
        data = _io_path(resolved).read_bytes()
        drivers.append({"path": relative, "bytes": len(data), "sha256": sha256(data).hexdigest()})
        captured[relative] = (data, "stage-or-install-entrypoint")
    copied_files = []
    for relative, (data, role) in sorted(captured.items()):
        copied = (WORK / EVIDENCE / "runtime-closure" / "files" / Path(relative)).as_posix()
        _put(stage, Path(copied), data)
        copied_files.append({"source_path": relative, "stage_path": copied,
                             "role": role, "bytes": len(data),
                             "sha256": sha256(data).hexdigest()})
    runtime = {
        "contract": "ocd-moody-pg61883-runtime-closure-v1",
        "captured_after": ["source and package binding checks", "acceptance/state validation",
                           "TEI P5 validation", "candidate and edition image resolution",
                           "maintained prose producer and independent checker",
                           "maintained native document producer and independent checker"],
        "first_party_loaded_modules": modules,
        "runtime_schema_files": schemas,
        "entrypoints": drivers,
        "python_version": sys.version,
        "third_party_versions": {
            name: importlib.metadata.version(distribution)
            for name, distribution in (("lxml", "lxml"), ("jsonschema", "jsonschema"),
                                       ("referencing", "referencing"))
        },
        "captured_file_copies": copied_files,
        "limits": ["The repository first-party module inventory is the exact set loaded in this stage process.",
                   "The schema inventory includes the schemas exercised by this acceptance/readers route and every local TEI XSD import.",
                   "External packages are identified by installed distribution versions; their wheel bytes are not copied."],
    }
    path = WORK / EVIDENCE / "runtime-closure.json"
    _put_json(stage, path, runtime)
    return path, runtime


def _review_status(review: dict) -> bool:
    """Require the final source-first review's exact pass and source/candidate pins."""
    decision = review.get("decision")
    source = review.get("source", {})
    candidate = review.get("candidate", {})
    return (
        isinstance(decision, str)
        and decision.startswith("Independent source-to-candidate structural and text review passes")
        and source.get("source_manifest_sha256") == SOURCE_MANIFEST_SHA
        and source.get("archive_sha256") == ARCHIVE_SHA
        and candidate.get("manifest_sha256") == PACKAGE_SHA
        and candidate.get("tei_sha256") == TEI_SHA
        and candidate.get("validation_status") == "pass"
        and candidate.get("validation_findings") == []
    )


def _copy_authorities(stage: Path, manifest: SourceManifest, acquisition: dict,
                      review_path: Path, review_sha: str) -> None:
    paths: dict[Path, str] = {}
    for authority in manifest.record["authorities"]:
        paths[Path(authority["path"])] = authority["sha256"]
    for retained in acquisition["retained_files"]:
        paths[Path(retained["path"])] = retained["sha256"]
    paths[PROPOSAL] = _sha(ROOT / PROPOSAL)
    paths[CLOSURE] = _sha(ROOT / CLOSURE)
    paths[CHALLENGES] = _sha(ROOT / CHALLENGES)
    paths[CHALLENGES_ERRATUM] = _sha(ROOT / CHALLENGES_ERRATUM)
    paths[V2_REVIEW] = _sha(ROOT / V2_REVIEW)
    paths[SOURCE_MANIFEST] = SOURCE_MANIFEST_SHA
    paths[TEST_FILE] = TEST_SHA
    implementation_path = Path(manifest.record["converter"]["implementation_path"])
    paths[implementation_path] = manifest.record["converter"]["implementation_sha256"]
    paths[review_path] = review_sha
    for relative, expected in sorted(paths.items(), key=lambda item: item[0].as_posix()):
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe Moody evidence dependency: {relative}")
        _copy_pinned(stage, relative, expected)


def _verify_archive_assets(stage: Path, acquisition: dict, package: CandidatePackage) -> list[dict]:
    archive_path = Path(acquisition["retained_files"][0]["path"])
    archive_data = _read(ROOT / archive_path, ARCHIVE_SHA)
    image_records = [item for item in acquisition["retained_files"]
                     if item.get("media_type") == "image/jpeg"]
    if len(image_records) != 18:
        raise ValueError(f"expected 18 retained image assets, found {len(image_records)}")
    html_items = [item for item in acquisition["retained_files"] if item.get("media_type") == "text/html"]
    if len(html_items) != 1:
        raise ValueError("expected exactly one extracted HTML member")
    with zipfile.ZipFile(_io_path(ROOT / archive_path)) as archive:
        infos = archive.infolist()
        archive_payloads = {info.filename: archive.read(info) for info in infos if not info.is_dir()}
    if len(archive_payloads) != 19:
        raise ValueError(f"expected 19 archive payloads, found {len(archive_payloads)}")
    ledger = json.loads(package.member_bytes("source-accountability.json"))
    actual_inventory = [{"path": info.filename, "bytes": len(archive_payloads[info.filename]),
                         "crc32": f"{info.CRC:08x}",
                         "sha256": _sha_member(archive_payloads[info.filename])}
                        for info in infos if not info.is_dir()]
    recorded_inventory = [{"path": item["path"], "bytes": item["bytes"],
                           "crc32": str(item["crc32"]).lower(), "sha256": item["sha256"]}
                          for item in ledger.get("archive_members", [])]
    if recorded_inventory != actual_inventory:
        raise ValueError("candidate source-accountability archive-member inventory differs from ZIP bytes/order")
    extracted_by_member: dict[str, tuple[dict, bytes]] = {}
    for record in [*html_items, *image_records]:
        prefix = "raw/gutenberg/61883/html/"
        if not record["path"].startswith(prefix):
            raise ValueError(f"unexpected extracted member path {record['path']}")
        member_name = record["path"][len(prefix):]
        payload = _read(ROOT / record["path"], record["sha256"])
        if len(payload) != record["bytes"] or archive_payloads.get(member_name) != payload:
            raise ValueError(f"retained extracted payload differs from ZIP member {member_name}")
        extracted_by_member[member_name] = (record, payload)
    if set(extracted_by_member) != set(archive_payloads):
        raise ValueError("the 19 archive payload members do not exactly match retained HTML/images")
    tei = package.member_bytes("content.tei.xml")
    from xml.etree import ElementTree as ET
    tree = ET.fromstring(tei)
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    graphics = tree.findall(".//tei:graphic", ns)
    by_url: dict[str, object] = {}
    for graphic in graphics:
        url = graphic.get("url")
        if not url or url in by_url:
            raise ValueError(f"missing or duplicate graphic URL: {url!r}")
        by_url[url] = graphic
    expected_urls = {"images/" + PurePosixPath(name).name for name in extracted_by_member if name.startswith("images/")}
    if set(by_url) != expected_urls or len(expected_urls) != 18:
        raise ValueError("TEI image URL set differs from the 18 retained ZIP image payloads")
    resolved = []
    for url in sorted(expected_urls):
        rel = PurePosixPath(url)
        if rel.is_absolute() or ".." in rel.parts or len(rel.parts) != 2 or rel.parts[0] != "images":
            raise ValueError(f"unsafe accepted TEI graphic URL: {url}")
        member_name = rel.as_posix()
        record, payload = extracted_by_member[member_name]
        edition_asset = EDITION / "images" / rel.name
        _put(stage, WORK / edition_asset, payload)
        staged_asset = _io_path(stage / WORK / edition_asset)
        if not staged_asset.is_file() or _sha(stage / WORK / edition_asset) != record["sha256"]:
            raise ValueError(f"edition-local image asset failed byte/hash check: {url}")
        candidate_asset = EVIDENCE / "images" / rel.name
        _put(stage, WORK / candidate_asset, payload)
        staged_candidate_asset = _io_path(stage / WORK / candidate_asset)
        if not staged_candidate_asset.is_file() or _sha(stage / WORK / candidate_asset) != record["sha256"]:
            raise ValueError(f"candidate-local image asset failed byte/hash check: {url}")
        resolved.append({"url": url, "edition_path": (WORK / edition_asset).as_posix(),
                         "candidate_path": (WORK / candidate_asset).as_posix(),
                         "source_path": record["path"], "bytes": len(payload),
                         "sha256": record["sha256"],
                         "resolution": "relative to candidate TEI and promoted edition master"})
    return resolved


def prepare(stage: Path, *, review_path: Path, review_sha: str) -> dict:
    _validate_sha_constants()
    if not re.fullmatch(r"[0-9a-f]{64}", review_sha):
        raise ValueError("independent-review SHA-256 pin must contain exactly 64 lowercase hex characters")
    stage = stage.absolute()
    if (_io_path(stage).exists() or not _io_path(stage.parent).is_dir()
            or stage.resolve() == ROOT.resolve() or ROOT.resolve() in stage.resolve().parents
            or stage.resolve() == CANDIDATE_OUTPUT.resolve()
            or CANDIDATE_OUTPUT.resolve() in stage.resolve().parents):
        raise ValueError("Moody PG61883 acceptance stage must be a fresh external directory")
    if _io_path(ROOT / WORK).exists():
        raise ValueError("Moody canonical work already exists; stage preimage is stale")
    review_bytes = _read(ROOT / review_path, review_sha)
    review = json.loads(review_bytes)
    if not isinstance(review, dict) or not _review_status(review):
        raise ValueError("final independent v3 source review is absent or not passing")
    proposal = _json(ROOT / PROPOSAL)
    if proposal.get("canonical_write_performed") is not False:
        raise ValueError("identity proposal is no longer read-only")
    records = proposal["proposed_records"]
    work_record = records["work.json"]
    state_record = records["state.json"]
    acquisition = records["acquisition.json"]
    if (work_record.get("work_id") != WORK_ID
            or state_record.get("work_id") != WORK_ID
            or acquisition.get("acquisition_id") != ACQUISITION_ID
            or acquisition.get("edition_id") != EDITION_ID
            or acquisition.get("source_sha256") != MEMBER_SET_SHA):
        raise ValueError("proposal identity or source-member-set binding differs")
    member_set = source_member_set_bytes(acquisition)
    if len(member_set) != 7285 or _sha_member(member_set) != MEMBER_SET_SHA:
        raise ValueError("canonical 22-file retained source member set differs")
    manifest = SourceManifest.load(ROOT / SOURCE_MANIFEST, repository_root=ROOT)
    if (manifest.sha256 != SOURCE_MANIFEST_SHA
            or manifest.record.get("validator", {}).get("import_closure_sha256") != IMPORT_CLOSURE_SHA
            or _sha(ROOT / "sources/manifest-acquisitions/moody-prevailing-prayer-pg61883-v3/profile.json") != PROFILE_SHA
            or _sha(ROOT / manifest.record["converter"]["implementation_path"]) != IMPLEMENTATION_SHA
            or _sha(ROOT / TEST_FILE) != TEST_SHA):
        raise ValueError("current Moody v3 SourceManifest changed")
    candidate = CandidatePackage.load(_io_path(CANDIDATE_OUTPUT / "package"))
    replay = CandidatePackage.load(_io_path(REPLAY_OUTPUT / "package"))
    validation_path = CANDIDATE_OUTPUT / "validation.json"
    validation = _json(validation_path, VALIDATION_FILE_SHA)
    if (candidate.sha256 != PACKAGE_SHA or replay.sha256 != PACKAGE_SHA
            or candidate.member_bytes("content.tei.xml") != replay.member_bytes("content.tei.xml")
            or _sha(CANDIDATE_OUTPUT / "package" / "content.tei.xml") != TEI_SHA
            or _sha(REPLAY_OUTPUT / "package" / "content.tei.xml") != TEI_SHA
            or validation.get("status") != "pass"
            or validation.get("findings") != []
            or validation.get("candidate_sha256") != PACKAGE_SHA
            or validation.get("source_manifest_sha256") != SOURCE_MANIFEST_SHA):
        raise ValueError("frozen Moody candidate, replay, or validation differs")
    source_accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    if (_sha_member(candidate.member_bytes("source-accountability.json")) != ACCOUNTABILITY_SHA
            or len(source_accountability.get("archive_members", [])) != 19):
        raise ValueError("candidate source-accountability does not bind all 19 archive payload members")
    _io_path(stage).mkdir(parents=True)
    _copy_authorities(stage, manifest, acquisition, review_path, review_sha)
    _put(stage, WORK / MEMBER_SET, member_set)
    _put_json(stage, WORK / "work.json", work_record)
    acquisition_record = dict(acquisition)
    acquisition_record["source_path"] = MEMBER_SET_PATH.as_posix()
    _put_json(stage, WORK / ACQUISITION, acquisition_record)
    staged_acq_path = stage / WORK / ACQUISITION
    validate_acquisition(_io_path(staged_acq_path), root=_io_path(stage))
    current_work = load_work(_io_path(stage / WORK / "work.json"))
    if current_work["work_id"] != WORK_ID:
        raise ValueError("staged Moody work identity does not validate")
    state_record = json.loads(json.dumps(state_record))
    review_target = next(item for item in state_record["targets"]
                         if item["target_type"] == "edition" and item["target_id"] == EDITION_ID)
    review_target["evidence"] = [
        CLOSURE.as_posix(), review_path.as_posix(),
        "plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/MOODY_PG61883_CANDIDATE_INDEPENDENT_REVIEW_20261003.json",
        CHALLENGES.as_posix(), SOURCE_MANIFEST.as_posix(),
    ]
    _put_json(stage, WORK / "state.json", state_record)
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    for name in candidate.member_names:
        _put(stage, WORK / EVIDENCE / "inputs/package" / name, candidate.member_bytes(name))
    _put(stage, WORK / EVIDENCE / "inputs/validation.json", _read(validation_path, VALIDATION_FILE_SHA))
    _put(stage, WORK / EVIDENCE / "inputs/independent-source-review.json", review_bytes)
    _put(stage, WORK / EVIDENCE / "inputs/source-accountability.json", candidate.member_bytes("source-accountability.json"))
    _put(stage, WORK / EVIDENCE / "inputs/test_moody_prevailing_prayer_61883_v3_reconstruction.py",
         _read(ROOT / TEST_FILE, TEST_SHA))
    original = candidate.member_bytes("content.tei.xml")
    source_binding = dict(source_path=MEMBER_SET_PATH.as_posix(), source_sha256=MEMBER_SET_SHA,
                          source_bytes=len(member_set), source_scope=acquisition_record["source_scope"],
                          source_kind=acquisition_record["source_kind"])
    revision = dict(id="moody-pg61883-electronic-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete retained Project Gutenberg 61883 English electronic witness for this titled work.")
    original_tree = etree.fromstring(original)
    tei_ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    historical_source_description = {
        "pointers": original_tree.xpath(".//tei:teiHeader/tei:fileDesc/tei:sourceDesc//tei:ptr/@target", namespaces=tei_ns),
        "sha256": original_tree.xpath(".//tei:teiHeader/tei:fileDesc/tei:sourceDesc//tei:idno[@type='sha256']/text()", namespaces=tei_ns),
    }
    derived = bind_reviewed_header(original, expected_sha256=TEI_SHA, identity=IDENTITY,
                                   source=source_binding, source_url=acquisition_record["url"],
                                   declared_scope=acquisition_record["source_scope"], revision=revision,
                                   historical_source_description=historical_source_description)
    # The maintained binder's direct sourceDesc/bibl insertion is not valid
    # after this sourceDesc's p-only source metadata. Preserve the binder's
    # exact bibl bytes inside a new p, without changing any original byte.
    bibl_start = derived.find(b'<bibl xmlns="http://www.tei-c.org/ns/1.0" type="ocd-acceptance-binding">')
    bibl_end_marker = b"</bibl>"
    bibl_end = derived.find(bibl_end_marker, bibl_start)
    if bibl_start < 0 or bibl_end < 0:
        raise ValueError("maintained header binder did not emit one pinned acceptance bibl")
    bibl_end += len(bibl_end_marker)
    inserted_bibl = derived[bibl_start:bibl_end]
    wrapped_bibl = b'<p xmlns="http://www.tei-c.org/ns/1.0">' + inserted_bibl + b"</p>"
    standard_bound = derived
    derived = derived[:bibl_start] + wrapped_bibl + derived[bibl_end:]
    if derived.replace(wrapped_bibl, inserted_bibl, 1) != standard_bound:
        raise ValueError("P5 sourceDesc paragraph wrapper is not an exact inverse")
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError("accepted header integration changed TEI text/body bytes")
    bound_tree = etree.fromstring(derived)
    binding_nodes = bound_tree.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc//tei:bibl[@type='ocd-acceptance-binding']", namespaces=tei_ns)
    change_nodes = bound_tree.xpath("./tei:teiHeader/tei:revisionDesc/tei:change[@xml:id=$value]", namespaces=tei_ns, value=revision["id"])
    if len(binding_nodes) != 1 or len(change_nodes) != 1:
        raise ValueError("accepted header did not add exactly one source binding and one revision change")
    binding_parent = binding_nodes[0].getparent()
    if binding_parent.tag == "{http://www.tei-c.org/ns/1.0}p" and len(binding_parent) == 1:
        binding_parent.getparent().remove(binding_parent)
    else:
        raise ValueError("acceptance bibl paragraph contains unexpected source content")
    change_nodes[0].getparent().remove(change_nodes[0])
    if original_tree.find("{http://www.tei-c.org/ns/1.0}teiHeader/{http://www.tei-c.org/ns/1.0}revisionDesc") is None:
        revision_desc = bound_tree.find("{http://www.tei-c.org/ns/1.0}teiHeader/{http://www.tei-c.org/ns/1.0}revisionDesc")
        if revision_desc is None or len(revision_desc) != 0:
            raise ValueError("new revisionDesc does not restore to the original header shape")
        revision_desc.getparent().remove(revision_desc)
    retained_pointers = bound_tree.xpath(
        ".//tei:teiHeader/tei:fileDesc/tei:sourceDesc//tei:ptr[not(ancestor::tei:bibl[@type='ocd-acceptance-binding'])]/@target",
        namespaces=tei_ns)
    retained_hashes = bound_tree.xpath(
        ".//tei:teiHeader/tei:fileDesc/tei:sourceDesc//tei:idno[@type='sha256' and not(ancestor::tei:bibl[@type='ocd-acceptance-binding'])]/text()",
        namespaces=tei_ns)
    if retained_pointers != historical_source_description["pointers"] or retained_hashes != historical_source_description["sha256"]:
        raise ValueError("acceptance binding changed the original primary-source pointer or archive SHA")
    candidate_path = stage / WORK / EVIDENCE / "candidate.tei.xml"
    _put(stage, WORK / EVIDENCE / "candidate.tei.xml", derived)
    master_path = _put(stage, WORK / MASTER, derived)
    if errors := validate_file(_io_path(master_path)):
        raise ValueError(f"Moody accepted-master TEI P5 validation failed: {errors[:5]}")
    resolved_images = _verify_archive_assets(stage, acquisition_record, candidate)
    if len(resolved_images) != 18:
        raise ValueError("not all 18 source graphic URLs resolve to edition-local bytes")
    with zipfile.ZipFile(_io_path(ROOT / "raw/gutenberg/61883/pg61883-h.zip")) as archive:
        archive_payloads = {info.filename: archive.read(info) for info in archive.infolist() if not info.is_dir()}
    content_records = [item for item in acquisition_record["retained_files"]
                       if item.get("media_type") in {"text/html", "image/jpeg"}]
    if set(item["path"].removeprefix("raw/gutenberg/61883/html/") for item in content_records) != set(archive_payloads):
        raise ValueError("source accounting members do not cover the exact archive member set")
    expected_members = [{"path": item["path"], "position": position}
                        for position, item in enumerate(acquisition_record["retained_files"], 1)]
    included_members = [{"path": item["path"], "position": position,
                         "bytes": item["bytes"], "sha256": item["sha256"],
                         "scope": item["scope"]}
                        for position, item in enumerate(acquisition_record["retained_files"], 1)]
    scope = dict(kind="edition", declared=acquisition_record["source_scope"],
                 expected_members=expected_members, included_members=included_members,
                 excluded_members=[])
    common = dict(identity=IDENTITY, source=source_binding,
                  projection_profile=PROJECTION_PROFILE,
                  candidate=make_file_binding(stage, candidate_path),
                  scope=acquisition_record["source_scope"], accepted_scope={"kind": "edition", "declared": acquisition_record["source_scope"]},
                  expected_members=expected_members, included_members=included_members,
                  excluded_members=[], missing_members=[], unknown_members=[])
    accounting = _put_json(stage, WORK / EVIDENCE / "source-accounting.json", common | {
        # The maintained source-document validator checks these summary fields
        # directly as well as the nested `source` binding shared with proofs.
        "source_sha256": source_binding["source_sha256"],
        "source_bytes": source_binding["source_bytes"],
        "primary_archive": {"path": acquisition_record["retained_files"][0]["path"],
                            "bytes": acquisition_record["retained_files"][0]["bytes"],
                            "sha256": ARCHIVE_SHA, "archive_payload_member_count": 19},
        "retained_member_set_path": MEMBER_SET_PATH.as_posix(),
        "retained_member_set_bytes": len(member_set), "retained_member_set_sha256": MEMBER_SET_SHA,
        "candidate_package_sha256": PACKAGE_SHA, "source_manifest_sha256": SOURCE_MANIFEST_SHA,
        "archive_payload_member_sha256": {name: _sha_member(payload) for name, payload in sorted(archive_payloads.items())},
        "retained_file_count": len(acquisition_record["retained_files"]),
        "image_assets": resolved_images,
        "excluded_content_members": [],
        "support_files": [item["path"] for item in acquisition_record["retained_files"]
                          if item.get("media_type") not in {"text/html", "image/jpeg", "application/zip"}],
        "rights_note": "The source's Public domain in the USA statement is preserved as source assertion, not rights clearance.",
        "basis": "The exact retained ZIP, all 19 ordered archive payload members, and all 22 retained-file identities are bound; all 18 graphic URLs resolve from the accepted master to byte-identical edition-local images.",
    })
    command = "py -3 -m build.tools.stage_moody_prevailing_prayer_61883_acceptance --stage <fresh-external-root> --independent-review <pinned-v3-review>"
    technical = {"producer": {"id": manifest.record["converter"]["id"]},
                 "checker": {"id": manifest.record["validator"]["id"]},
                 "shared_assumptions": [
                     "The source-to-TEI producer and oracle share the same pinned v3 implementation and declared source-accountability mapping.",
                     "The independent review uses a separate stdlib HTMLParser/XML traversal and source/member hashing, but does not constitute a separately implemented converter/oracle pair.",
                 ],
                 "independent_corroboration": "Pinned v3 source-first review, frozen candidate/replay equality, and direct ZIP/member/image byte checks."}
    proof_paths = {}
    for claim in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _put_json(stage, WORK / EVIDENCE / f"{claim}.json", common | {
            "status": "pass", "command": command, "exit_code": 0, "claim": claim,
            "candidate_package_sha256": PACKAGE_SHA, "source_manifest_sha256": SOURCE_MANIFEST_SHA,
            "independent_review_sha256": review_sha, "current_validation_sha256": VALIDATION_FILE_SHA,
            "accepted_header_body_unchanged": True,
            "original_source_head_metadata_preserved": True,
            "resolved_image_count": 18,
            "resolved_image_destinations": resolved_images,
        })
        technical[claim] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
        proof_paths[claim] = proof.relative_to(stage)
    reviewed_at = _now()
    review_record = common | {
        "reviewer": "agent:moody-pg61883-v3-source-first-review",
        "reviewed_at": reviewed_at,
        "coverage": {"status": "partial", "declared": acquisition_record["source_scope"],
                     "reached": ["zip/members", "html/head", "html/body", "images"],
                     "inspected": ["zip/members/names-lengths-crc32-sha256",
                                   "html/head/all-23-children-and-metadata",
                                   "html/body/all-descendant-locators-text-and-attributes",
                                   "images/all-18-payloads-and-graphic-bindings"],
                     "unreviewed": ["visual rendering and full human proofreading",
                                    "print witness collation", "rights clearance", "publication"]},
        "source_review_receipt": review_path.as_posix(),
        "source_review_sha256": review_sha,
        "candidate_sha256": PACKAGE_SHA,
        "source_manifest_sha256": SOURCE_MANIFEST_SHA,
        "source_quality_uncertainty": [
            "This acceptance covers the retained Project Gutenberg electronic witness; no separate print witness was collated.",
            "The upstream Project Gutenberg proofreading and correction history was not independently audited.",
            "The title-page copyright statement says 1884; no publication year is inferred from it.",
            "The source's Public domain in the USA statement is not rights clearance.",
        ],
        "discrepancies": [],
        "unreviewed_residuals": ["No print edition collation.", "No human review or rights clearance.",
                                  "No claim covering Moody's other writings.", "No publication authorization."],
    }
    review_file = _put_json(stage, WORK / EVIDENCE / "review.json", review_record)
    decision = {
        "source_local_disposition": "Agent acceptance of this complete retained Project Gutenberg English electronic witness only.",
        "blockers": [], "human_decision": {"status": "not-recorded"},
        "agent_assessment": {"status": "accepted", "actor": review_record["reviewer"],
                             "assessed_at": reviewed_at, "supported_scope": acquisition_record["source_scope"],
                             "unresolved_claims": [],
                             "unassessed_stronger_claims": ["print collation", "human acceptance", "rights clearance", "publication", "other Moody works"]},
    }
    acceptance_record = build_acceptance_record(stage, identity=IDENTITY,
        candidate_path=candidate_path,
        source_accounting_path=accounting, scope=scope, technical=technical,
        review=review_record | {"report_path": review_file}, representation_revision=revision,
        decision=decision)
    acceptance_path = stage / WORK / ACCEPTANCE
    write_acceptance(_io_path(acceptance_path), acceptance_record)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    acceptance_record["promotion"].update(status="promoted", promoted_at=_now(),
                                          master=make_file_binding(stage, master_path))
    write_acceptance(_io_path(acceptance_path), acceptance_record)
    state_record = _json(stage / WORK / "state.json")
    edition_target = next(item for item in state_record["targets"]
                          if item["target_type"] == "edition" and item["target_id"] == EDITION_ID)
    edition_target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=_now())
    edition_target["evidence"] = [(WORK / MASTER).as_posix(), (WORK / ACCEPTANCE).as_posix(),
                                  (EVIDENCE / "source-accounting.json").as_posix(),
                                  CLOSURE.as_posix(), review_path.as_posix()]
    _put_json(stage, WORK / "state.json", state_record)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    initial_acceptance_sha = _sha(acceptance_path)
    acceptance_binding = {
        "path": (WORK / ACCEPTANCE).as_posix(),
        "sha256": initial_acceptance_sha,
    }
    projection = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path))
    reader_errors = verify_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path),
                                          rows=projection["rows"], receipt=projection["receipt"])
    if reader_errors or not projection["rows"]:
        raise ValueError(f"Moody actual-master prose projection failed: {reader_errors[:3]}")
    from ocd_kernel.projection.categories.native_documents import (
        project_accepted_document,
        verify_accepted_document,
    )
    native_projection = project_accepted_document(
        _io_path(stage), acceptance_path=_io_path(acceptance_path), category="prose",
        projection_profile=PROJECTION_PROFILE,
    )
    native_errors = verify_accepted_document(
        _io_path(stage), acceptance_path=_io_path(acceptance_path),
        rows=native_projection["rows"], receipt=native_projection["receipt"], category="prose",
        projection_profile=PROJECTION_PROFILE,
    )
    if native_errors or not native_projection["rows"]:
        raise ValueError(f"Moody actual-master native document projection failed: {native_errors[:3]}")
    for name, result in (("prose", projection), ("native", native_projection)):
        if result["receipt"].get("authority", {}).get("acceptance") != acceptance_binding:
            raise ValueError(f"initial Moody {name} projection does not bind the current acceptance bytes")
    projection_record = {"contract": "ocd-accepted-prose-projection-v1", "status": "pass",
                         "identity": IDENTITY, "rows": projection["rows"],
                         "receipt": projection["receipt"], "row_count": len(projection["rows"]),
                         "verification_errors": []}
    _put_json(stage, WORK / EVIDENCE / "actual-prose-projection.json", projection_record)
    native_projection_record = {
        "contract": "ocd-accepted-native-document-projection-v1", "status": "pass",
        "identity": IDENTITY, "category": "prose", "rows": native_projection["rows"],
        "receipt": native_projection["receipt"], "row_count": len(native_projection["rows"]),
        "verification_errors": [],
    }
    _put_json(stage, WORK / EVIDENCE / "actual-native-document-projection.json", native_projection_record)
    runtime_path, runtime_closure = _capture_runtime_closure(stage)
    runtime_sha = _sha(stage / runtime_path)
    closure_proof_relative = proof_paths["closure"]
    closure_proof_path = stage / closure_proof_relative
    closure_proof_record = _json(closure_proof_path)
    closure_proof_record.update({
        "runtime_closure_path": runtime_path.as_posix(),
        "runtime_closure_sha256": runtime_sha,
        "runtime_loaded_module_count": len(runtime_closure["first_party_loaded_modules"]),
        "runtime_schema_file_count": len(runtime_closure["runtime_schema_files"]),
        "runtime_captured_file_count": len(runtime_closure["captured_file_copies"]),
        "native_document_projection_row_count": len(native_projection["rows"]),
        "native_document_projection_rows_sha256": _sha_member(
            json.dumps(native_projection["rows"], sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False).encode("utf-8")
        ),
    })
    _put_json(stage, closure_proof_relative, closure_proof_record)
    # Rebuild acceptance to bind the final runtime-closure proof bytes, then
    # repeat maintained readers against the final promoted generation.
    acceptance_record = build_acceptance_record(stage, identity=IDENTITY,
        candidate_path=candidate_path,
        source_accounting_path=accounting, scope=scope, technical=technical,
        review=review_record | {"report_path": review_file}, representation_revision=revision,
        decision=decision)
    acceptance_record["promotion"].update(status="promoted", promoted_at=_now(),
                                           master=make_file_binding(stage, master_path))
    write_acceptance(_io_path(acceptance_path), acceptance_record)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    final_projection = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path))
    final_prose_errors = verify_accepted_prose(
        _io_path(stage), acceptance_path=_io_path(acceptance_path),
        rows=final_projection["rows"], receipt=final_projection["receipt"]
    )
    final_native_projection = project_accepted_document(
        _io_path(stage), acceptance_path=_io_path(acceptance_path), category="prose",
        projection_profile=PROJECTION_PROFILE,
    )
    final_native_errors = verify_accepted_document(
        _io_path(stage), acceptance_path=_io_path(acceptance_path),
        rows=final_native_projection["rows"], receipt=final_native_projection["receipt"],
        category="prose", projection_profile=PROJECTION_PROFILE,
    )
    final_acceptance_sha = _sha(acceptance_path)

    def expected_rebound_receipt(receipt: dict) -> dict:
        expected = json.loads(json.dumps(receipt))
        binding = expected.get("authority", {}).get("acceptance")
        if binding != acceptance_binding:
            raise ValueError("initial Moody projection receipt acceptance binding changed unexpectedly")
        binding["sha256"] = final_acceptance_sha
        return expected

    expected_final_prose_receipt = expected_rebound_receipt(projection["receipt"])
    expected_final_native_receipt = expected_rebound_receipt(native_projection["receipt"])
    if (final_prose_errors or final_native_errors
            or final_projection["rows"] != projection["rows"]
            or final_projection["receipt"] != expected_final_prose_receipt
            or final_native_projection["rows"] != native_projection["rows"]
            or final_native_projection["receipt"] != expected_final_native_receipt):
        raise ValueError("Moody final acceptance rebinding changed maintained reader outputs")
    _put_json(stage, WORK / EVIDENCE / "actual-prose-projection.json", {
        "contract": "ocd-accepted-prose-projection-v1", "status": "pass",
        "identity": IDENTITY, "rows": final_projection["rows"],
        "receipt": final_projection["receipt"], "row_count": len(final_projection["rows"]),
        "verification_errors": [],
    })
    _put_json(stage, WORK / EVIDENCE / "actual-native-document-projection.json", {
        "contract": "ocd-accepted-native-document-projection-v1", "status": "pass",
        "identity": IDENTITY, "category": "prose", "rows": final_native_projection["rows"],
        "receipt": final_native_projection["receipt"], "row_count": len(final_native_projection["rows"]),
        "verification_errors": [],
    })
    final_loaded = _loaded_first_party_modules()
    if final_loaded != runtime_closure["first_party_loaded_modules"]:
        raise ValueError("first-party runtime modules changed after closure capture")
    before = {}
    after = _files(_io_path(stage / WORK))
    receipt = {
        "contract": CONTRACT, "status": "staged-only", "canonical_root": ROOT.as_posix(),
        "stage_root": stage.as_posix(), "work_id": WORK_ID, "identity": IDENTITY,
        "projection_profile": PROJECTION_PROFILE,
        "canonical_preimage": {"work_exists": False, "before": before},
        "source_manifest_path": SOURCE_MANIFEST.as_posix(), "source_manifest_sha256": SOURCE_MANIFEST_SHA,
        "source_archive_path": "raw/gutenberg/61883/pg61883-h.zip", "source_archive_sha256": ARCHIVE_SHA,
        "source_member_set_path": MEMBER_SET_PATH.as_posix(), "source_member_set_sha256": MEMBER_SET_SHA,
        "candidate_output_root": CANDIDATE_OUTPUT.as_posix(),
        "candidate_package_root": (CANDIDATE_OUTPUT / "package").as_posix(),
        "candidate_package_sha256": PACKAGE_SHA, "candidate_tei_sha256": TEI_SHA,
        "validation_path": (CANDIDATE_OUTPUT / "validation.json").as_posix(),
        "validation_file_sha256": VALIDATION_FILE_SHA, "independent_review_path": review_path.as_posix(),
        "independent_review_sha256": review_sha, "source_payload_member_count": 19,
        "retained_file_count": 22, "resolved_image_count": len(resolved_images),
        "resolved_candidate_image_count": len([item for item in resolved_images if item.get("candidate_path")]),
        "resolved_edition_image_count": len([item for item in resolved_images if item.get("edition_path")]),
        "resolved_edition_images": resolved_images, "header_only_binding": True,
        "candidate_body_unchanged_after_header_binding": True,
        "original_header_tree_preserved_after_removing_two_declared_insertions": True,
        "historical_source_description_pointers": historical_source_description["pointers"],
        "historical_source_description_sha256_values": historical_source_description["sha256"],
        "source_accountability_sha256": ACCOUNTABILITY_SHA,
        "p5_validation": "pass", "acceptance_validation": "pass", "state_validation": "pass",
        "prose_projection_rows": len(projection["rows"]), "prose_projection_validation": "pass",
        "native_document_projection_rows": len(native_projection["rows"]),
        "native_document_projection_validation": "pass",
        "runtime_closure_path": runtime_path.as_posix(),
        "runtime_closure_sha256": runtime_sha,
        "runtime_loaded_module_count": len(runtime_closure["first_party_loaded_modules"]),
        "runtime_schema_file_count": len(runtime_closure["runtime_schema_files"]),
        "runtime_captured_file_count": len(runtime_closure["captured_file_copies"]),
        "before": before, "after": after,
        "accepted_master_sha256": _sha(master_path), "acceptance_sha256": _sha(acceptance_path),
        "acceptance_authority_rebinding": {
            "path": acceptance_binding["path"],
            "initial_sha256": initial_acceptance_sha,
            "final_sha256": final_acceptance_sha,
            "projection_receipt_field_updated": "authority.acceptance.sha256",
            "all_other_receipt_fields_and_rows_equal": True,
        },
        "status_note": "Agent acceptance is staged only. Rights and human review are unassessed; no canonical install or publication has occurred.",
    }
    _put_json(stage, Path("moody-pg61883-stage-receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, default=DEFAULT_STAGE)
    parser.add_argument("--independent-review", type=Path, required=True)
    parser.add_argument("--review-sha256", required=True)
    args = parser.parse_args()
    result = prepare(args.stage, review_path=args.independent_review, review_sha=args.review_sha256)
    print(json.dumps({"status": result["status"], "stage_root": result["stage_root"],
                      "work_id": result["work_id"], "file_count": len(result["after"]),
                      "master_sha256": result["accepted_master_sha256"],
                      "resolved_edition_image_count": result["resolved_edition_image_count"]}, sort_keys=True))


if __name__ == "__main__":
    main()
