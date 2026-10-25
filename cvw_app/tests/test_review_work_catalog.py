from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
from threading import Thread
from types import MappingProxyType, SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import zipfile
import zlib

import pytest

import cvw_app.review_contract as review_contract
import cvw_app.review_service as review_service
from cvw_app.review_contract import RecordedContext, ReviewApplication, ReviewContractError
from cvw_app.review_renderers import MAX_PAGE_SCALARS


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _reparse_directory_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except (OSError, NotImplementedError) as symlink_error:
        try:
            subprocess.run(
                ["cmd.exe", "/c", "mklink", "/J", str(link), str(target)],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as junction_error:
            pytest.skip(
                "this Windows host cannot create the safe reparse fixture: "
                f"{symlink_error}; {junction_error}"
            )


def _write_catalog(root: Path, works: list[dict[str, object]]) -> Path:
    path = root / "work-catalog.json"
    path.write_text(
        json.dumps({"methodology": {}, "summary": {}, "works": works}),
        encoding="utf-8",
    )
    return path


def _work(
    work_id: str,
    *,
    source_id: str | None = None,
    manifest: str | None = None,
) -> dict[str, object]:
    routes = []
    if source_id is not None and manifest is not None:
        routes.append(
            {
                "association": "exact_id",
                "manifest": manifest,
                "scope": "work",
                "source_id": source_id,
                "verification": "verified",
            }
        )
    return {
        "work_id": work_id,
        "title": f"Title for {work_id}",
        "author": None if work_id == "without-candidate" else "Example Creator",
        "category": "structured-text",
        "category_label": "Structured Texts",
        "reconstruction_state": {
            "retained_source": "manifest_bound" if routes else "not_assessed",
            "tei_candidate": "route_available" if routes else "not_started",
            "validation": "validator_available" if routes else "not_run",
            "human_review": "required" if routes else "not_started",
            "publication": "not_ready",
            "routes": routes,
        },
    }


def _install_contract_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    candidates: dict[Path, SimpleNamespace],
    source_manifest: SimpleNamespace,
    source_path: Path,
) -> None:
    if "authorities" not in source_manifest.record:
        payload = source_path.read_bytes()
        source_manifest.record = {
            **source_manifest.record,
            "authorities": (
                {
                    "name": "fixture-primary-source",
                    "role": "primary-source",
                    "path": source_path.name,
                    "bytes": len(payload),
                    "sha256": _sha(payload),
                },
            ),
        }
        source_manifest.repository_root = source_path.parent
        source_manifest.authority_path = lambda name: source_path
    monkeypatch.setattr(
        review_contract.CandidatePackage,
        "load",
        classmethod(lambda cls, path: candidates[Path(path).resolve().parent]),
    )
    monkeypatch.setattr(
        review_contract.SourceManifest,
        "load",
        classmethod(lambda cls, path, *, repository_root: source_manifest),
    )
    monkeypatch.setattr(
        review_contract,
        "_load_validation_report",
        lambda candidate_dir, loaded_source, candidate, **kwargs: SimpleNamespace(
            status="pass",
            sha256="d" * 64,
            candidate_sha256=candidate.sha256,
            source_manifest_sha256=loaded_source.sha256,
        ),
    )

def _candidate(
    path: Path,
    source_id: str,
    source_manifest_path: str,
    digest: str,
    *,
    tei: bytes | None = None,
) -> SimpleNamespace:
    tei = tei or (
        b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
        b"<p>Faithful candidate text.</p></body></text></TEI>"
    )
    package = path / "package"
    package.mkdir()
    (package / "content.tei.xml").write_bytes(tei)
    (path / "validation.json").write_text("{}", encoding="utf-8")
    return SimpleNamespace(
        path=package,
        sha256=digest,
        # CandidatePackage exposes its manifest as an immutable recursive
        # mapping; keep this seam fixture honest so the viewer cannot regress
        # to requiring a concrete dict.
        manifest=MappingProxyType(
            {
                "source_id": source_id,
                "source_manifest": MappingProxyType(
                    {"path": source_manifest_path, "sha256": "b" * 64}
                ),
                "converter": MappingProxyType(
                    {"id": "fixture-converter", "version": "1"}
                ),
                "package_schema": MappingProxyType(
                    {"path": "schema.json", "sha256": "d" * 64}
                ),
            }
        ),
        member_names=(
            "content.tei.xml",
            "manifest.json",
            "provenance.json",
            "README.source.md",
            "source-accountability.json",
            "unresolved.jsonl",
        ),
        member_bytes=lambda name: tei if name == "content.tei.xml" else b"",
    )


def _small_nave_packet(
    root: Path,
    entries: tuple[tuple[str, bytes], ...] | None = None,
) -> tuple[SimpleNamespace, Path, dict[str, Path]]:
    governed_entries = entries or (
        (
            "AARON",
            b'First <ref target="JESUS">Jesus</ref>'
            b"<lb/><list><item>Priest</item></list>",
        ),
    )
    payloads = tuple(
        b'<entryFree n="'
        + key.encode("utf-8")
        + b'"><def>'
        + definition
        + b"</def></entryFree>\x00"
        for key, definition in governed_entries
    )
    data_start = 4 + 8 * len(payloads)
    payload_cursor = data_start
    table = []
    for payload in payloads:
        table.append(struct.pack("<II", payload_cursor, len(payload)))
        payload_cursor += len(payload)
    plain = struct.pack("<I", len(payloads)) + b"".join(table) + b"".join(payloads)
    compressed = zlib.compress(plain) + (b"\x00" * 1_024)
    dat_records = []
    idx_records = []
    dat_cursor = 0
    for entry_number, (key, _) in enumerate(governed_entries):
        record = key.encode("utf-8") + b"\r\n" + struct.pack("<II", 0, entry_number)
        idx_records.append(struct.pack("<II", dat_cursor, len(record)))
        dat_records.append(record + b"\r\n")
        dat_cursor += len(record) + 2
    content = {
        "dict-zdt": compressed + b"\r\n",
        "dict-zdx": struct.pack("<II", 0, len(compressed)),
        "dict-dat": b"".join(dat_records),
        "dict-idx": b"".join(idx_records),
        "nave-conf": b"[Nave]\r\nModDrv=zLD\r\n",
    }
    relative_paths = {
        "dict-zdt": "raw/naves/modules/lexdict/zld/nave/dict.zdt",
        "dict-zdx": "raw/naves/modules/lexdict/zld/nave/dict.zdx",
        "dict-dat": "raw/naves/modules/lexdict/zld/nave/dict.dat",
        "dict-idx": "raw/naves/modules/lexdict/zld/nave/dict.idx",
        "nave-conf": "raw/naves/mods.d/nave.conf",
        "nave-archive": "raw/naves/Nave.zip",
    }
    paths = {name: root / relative for name, relative in relative_paths.items()}
    for name, value in content.items():
        paths[name].parent.mkdir(parents=True, exist_ok=True)
        paths[name].write_bytes(value)
    archive_buffer = io.BytesIO()
    archive_names = (
        ("dict-zdx", "modules/lexdict/zld/nave/dict.zdx"),
        ("dict-zdt", "modules/lexdict/zld/nave/dict.zdt"),
        ("dict-dat", "modules/lexdict/zld/nave/dict.dat"),
        ("dict-idx", "modules/lexdict/zld/nave/dict.idx"),
        ("nave-conf", "mods.d/nave.conf"),
    )
    with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, archive_name in archive_names:
            archive.writestr(archive_name, content[name])
    archive_bytes = archive_buffer.getvalue()
    paths["nave-archive"].write_bytes(archive_bytes)

    primary_names = ("dict-zdt", "dict-zdx", "dict-dat", "dict-idx")
    source_members = sorted(
        (
            {
                "name": name,
                "path": relative_paths[name],
                "bytes": len(content[name]),
                "sha256": _sha(content[name]),
            }
            for name in primary_names
        ),
        key=lambda value: (value["path"], value["name"]),
    )
    source_set_record = {
        "contract": "ocd-source-member-set-v1",
        "members": source_members,
    }
    authorities = tuple(
        {
            **next(value for value in source_members if value["name"] == name),
            "role": "primary-source",
        }
        for name in primary_names
    ) + (
        {
            "name": "nave-conf",
            "path": relative_paths["nave-conf"],
            "role": "source-support-metadata-rights",
            "bytes": len(content["nave-conf"]),
            "sha256": _sha(content["nave-conf"]),
        },
        {
            "name": "nave-archive",
            "path": relative_paths["nave-archive"],
            "role": "acquisition-container",
            "bytes": len(archive_bytes),
            "sha256": _sha(archive_bytes),
        },
    )
    source_manifest = SimpleNamespace(
        sha256="b" * 64,
        record={
            "source_id": "crosswire-nave-sword-v3",
            "authorities": authorities,
            "transformation_source_set": {
                **source_set_record,
                "sha256": _sha(_canonical(source_set_record)),
            },
        },
        repository_root=root,
        authority_path=lambda name: paths[name],
    )
    return source_manifest, paths["dict-zdt"], paths


def _validation_subject(tmp_path: Path):
    candidate_dir = tmp_path / "candidate"
    package = candidate_dir / "package"
    package.mkdir(parents=True)
    sidecar = candidate_dir / "validation.json"
    candidate_sha256 = "a" * 64
    source_manifest_sha256 = "b" * 64
    authority_digests = {
        "complete-source-feature-profile": "c" * 64,
        "candidate-package-schema": "d" * 64,
        "tei-validation-schema": "e" * 64,
        "independent-validation-policy": "f" * 64,
    }
    source_manifest = SimpleNamespace(
        sha256=source_manifest_sha256,
        record={
            "converter": {"id": "fixture-converter", "version": "1"},
            "package_schema": {
                "path": "authority/candidate-package-schema",
                "sha256": authority_digests["candidate-package-schema"],
            },
            "validator": {
                "id": "fixture-validator",
                "version": "1",
                "implementation_sha256": "1" * 64,
                "import_closure_sha256": "2" * 64,
            },
            "authorities": [
                {
                    "name": "source",
                    "role": "primary-source",
                    "path": "raw/source.txt",
                    "bytes": 6,
                    "sha256": "3" * 64,
                },
                *[
                    {
                        "name": role,
                        "role": role,
                        "path": f"authority/{role}",
                        "bytes": 1,
                        "sha256": digest,
                    }
                    for role, digest in authority_digests.items()
                ],
            ],
        },
        verify=lambda: None,
    )
    candidate = SimpleNamespace(
        path=package,
        sha256=candidate_sha256,
        manifest={
            "converter": {"id": "fixture-converter", "version": "1"},
            "package_schema": {
                "path": "authority/candidate-package-schema",
                "sha256": authority_digests["candidate-package-schema"],
            },
        },
        verify_integrity=lambda: None,
    )
    attestation = {
        "status": "pass",
        "oracle_id": "fixture-validator",
        "oracle_version": "1",
        "implementation_sha256": "1" * 64,
        "import_closure_sha256": "2" * 64,
        "runtime": "CPython fixture",
        "source_manifest_sha256": source_manifest_sha256,
        "candidate_sha256": candidate_sha256,
        "profile_sha256": authority_digests["complete-source-feature-profile"],
        "package_schema_sha256": authority_digests["candidate-package-schema"],
        "source_sha256": "3" * 64,
        "xsd_sha256": authority_digests["tei-validation-schema"],
        "policy_sha256": authority_digests["independent-validation-policy"],
        "findings": [],
    }
    attestation["result_sha256"] = _sha(_canonical(attestation))
    report = {
        "contract": "ocd-validation-report-v1",
        "status": "pass",
        "candidate_sha256": candidate_sha256,
        "source_manifest_sha256": source_manifest_sha256,
        "attestation": attestation,
        "findings": [],
    }
    report["report_sha256"] = _sha(_canonical(report))
    sidecar.write_bytes(_canonical(report))
    return candidate_dir, sidecar, source_manifest, candidate


def test_validation_sidecar_loader_binds_outer_report_to_exact_package_and_source(
    tmp_path: Path,
) -> None:
    candidate_dir, _, source_manifest, candidate = _validation_subject(tmp_path)

    report = review_contract._load_validation_report(
        candidate_dir, source_manifest, candidate
    )

    assert report.status == "pass"
    assert report.candidate_sha256 == candidate.sha256
    assert report.source_manifest_sha256 == source_manifest.sha256


def test_validation_loader_rejects_reparse_package_member_before_read(
    tmp_path: Path,
) -> None:
    candidate_dir, _, source_manifest, candidate = _validation_subject(tmp_path)
    member = candidate_dir / "package" / "README.source.md"
    outside = tmp_path / "outside-member"
    outside.mkdir()
    (outside / "payload.txt").write_text("outside", encoding="utf-8")
    _reparse_directory_or_skip(member, outside)

    with pytest.raises(ReviewContractError, match="member.*reparse"):
        review_contract._load_validation_report(
            candidate_dir, source_manifest, candidate
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.__setitem__("status", "fail"), "status"),
        (
            lambda value: value.__setitem__("candidate_sha256", "9" * 64),
            "candidate",
        ),
        (
            lambda value: value["attestation"].__setitem__("oracle_id", "other"),
            "identity",
        ),
        (
            lambda value: value["attestation"].__setitem__(
                "source_sha256", "9" * 64
            ),
            "authority",
        ),
    ],
)
def test_validation_sidecar_loader_rejects_rehashed_invalid_bindings(
    tmp_path: Path, mutation, message: str
) -> None:
    candidate_dir, sidecar, source_manifest, candidate = _validation_subject(tmp_path)
    value = json.loads(sidecar.read_bytes())
    mutation(value)
    attestation = value["attestation"]
    attestation["result_sha256"] = _sha(
        _canonical(
            {key: item for key, item in attestation.items() if key != "result_sha256"}
        )
    )
    value["report_sha256"] = _sha(
        _canonical(
            {key: item for key, item in value.items() if key != "report_sha256"}
        )
    )
    sidecar.write_bytes(_canonical(value))

    with pytest.raises(ReviewContractError, match=message):
        review_contract._load_validation_report(
            candidate_dir, source_manifest, candidate
        )


def test_validation_sidecar_loader_rejects_missing_tampered_and_duplicate_json(
    tmp_path: Path,
) -> None:
    candidate_dir, sidecar, source_manifest, candidate = _validation_subject(tmp_path)
    original = sidecar.read_bytes()
    sidecar.unlink()
    with pytest.raises(ReviewContractError, match="validation.json"):
        review_contract._load_validation_report(
            candidate_dir, source_manifest, candidate
        )

    sidecar.write_bytes(original.replace(b'"report_sha256":"', b'"report_sha256":"9'))
    with pytest.raises(ReviewContractError, match="digest|canonical"):
        review_contract._load_validation_report(
            candidate_dir, source_manifest, candidate
        )

    sidecar.write_bytes(
        original.replace(
            b'{"attestation":',
            b'{"contract":"ocd-validation-report-v1","attestation":',
            1,
        )
    )
    with pytest.raises(ReviewContractError, match="duplicated"):
        review_contract._load_validation_report(
            candidate_dir, source_manifest, candidate
        )


def _rehash_validation_for_candidate(sidecar: Path, candidate_sha256: str) -> None:
    value = json.loads(sidecar.read_bytes())
    value["candidate_sha256"] = candidate_sha256
    value["attestation"]["candidate_sha256"] = candidate_sha256
    attestation = value["attestation"]
    attestation["result_sha256"] = _sha(
        _canonical(
            {key: item for key, item in attestation.items() if key != "result_sha256"}
        )
    )
    value["report_sha256"] = _sha(
        _canonical(
            {key: item for key, item in value.items() if key != "report_sha256"}
        )
    )
    sidecar.write_bytes(_canonical(value))


@pytest.mark.parametrize("field", ["converter", "package_schema"])
def test_validation_loader_rejects_self_consistently_rehashed_candidate_authority_drift(
    tmp_path: Path, field: str
) -> None:
    candidate_dir, sidecar, source_manifest, candidate = _validation_subject(tmp_path)
    changed_key = "id" if field == "converter" else "path"
    candidate.manifest[field] = {
        **candidate.manifest[field],
        changed_key: "drifted",
    }
    candidate.sha256 = "9" * 64
    _rehash_validation_for_candidate(sidecar, candidate.sha256)

    with pytest.raises(
        ReviewContractError,
        match=f"candidate manifest {field.replace('_', '-')}",
    ):
        review_contract._load_validation_report(
            candidate_dir, source_manifest, candidate
        )


def test_validation_loader_rejects_schema_block_not_bound_to_schema_authority(
    tmp_path: Path,
) -> None:
    candidate_dir, _, source_manifest, candidate = _validation_subject(tmp_path)
    source_manifest.record["package_schema"] = {
        "path": "authority/other-schema",
        "sha256": "d" * 64,
    }
    candidate.manifest["package_schema"] = dict(
        source_manifest.record["package_schema"]
    )

    with pytest.raises(ReviewContractError, match="candidate-package-schema authority"):
        review_contract._load_validation_report(
            candidate_dir, source_manifest, candidate
        )


def test_work_catalog_loader_lists_every_work_and_opens_unlinked_source_tei_compare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_manifest_relative = "sources/example/example.source-manifest.json"
    source_manifest_path = tmp_path / source_manifest_relative
    source_manifest_path.parent.mkdir(parents=True)
    source_manifest_path.write_text("{}", encoding="utf-8")
    source_path = tmp_path / "retained" / "source.html"
    source_path.parent.mkdir()
    source_path.write_text("<html><body><p>Faithful source text.</p></body></html>", encoding="utf-8")
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    candidate = _candidate(candidate_dir, "source-example", source_manifest_relative, "a" * 64)
    source_manifest = SimpleNamespace(
        sha256="b" * 64,
        record={"source_id": "source-example"},
    )
    _install_contract_fakes(
        monkeypatch,
        candidates={candidate_dir.resolve(): candidate},
        source_manifest=source_manifest,
        source_path=source_path,
    )
    catalog_path = _write_catalog(
        tmp_path,
        [
            _work(
                "with-candidate",
                source_id="source-example",
                manifest=source_manifest_relative,
            ),
            _work("without-candidate"),
        ],
    )

    application = ReviewApplication.from_work_catalog(
        catalog_path,
        [candidate_dir],
        repository_root=tmp_path,
    )
    with monkeypatch.context() as compact_catalog_patch:
        compact_catalog_patch.setattr(
            application,
            "_resolve",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("compact Library must not render artifact bodies")
            ),
        )
        catalog = application.catalog()

    assert [work["slug"] for work in catalog["works"]] == [
        "with-candidate",
        "without-candidate",
    ]
    bound = catalog["works"][0]
    assert "reconstruction_state" not in bound
    assert bound["candidate_validation"] == {
        "status": "pass",
        "report_sha256": "d" * 64,
        "candidate_sha256": "a" * 64,
        "source_manifest_sha256": "b" * 64,
    }
    assert bound["default_compare"] == {
        "left_stage": "source",
        "right_stage": "tei",
        "linked": False,
        "correspondence": "absent",
    }
    assert [stage["availability"] for stage in bound["stages"]] == [
        "available",
        "available",
    ]
    assert [stage["label"] for stage in bound["stages"][:2]] == [
        "Retained source",
        "Faithful TEI candidate",
    ]
    assert catalog["works"][1]["creator"] == "Creator not recorded"

    source_stage, tei_stage = bound["stages"][:2]
    assert all("capabilities" not in stage for stage in bound["stages"])
    compare = application.compare_view(
        "with-candidate",
        left_stage="source",
        left_recorded=RecordedContext(
            source_stage["selected_artifact"]["id"],
            source_stage["selected_artifact"]["version"],
            "start",
        ),
        right_stage="tei",
        right_recorded=RecordedContext(
            tei_stage["selected_artifact"]["id"],
            tei_stage["selected_artifact"]["version"],
            "start",
        ),
        linked=False,
        correspondence_source=None,
    )
    assert compare["linked_navigation"] is False
    assert compare["correspondence"]["state"] == "absent"
    assert compare["left"]["availability"] == "available"
    assert compare["right"]["availability"] == "available"
    assert compare["right"]["location"]["label"] == "Start of faithful TEI candidate"


@pytest.fixture
def evidence_pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Reuse the catalog/candidate admission seam with real renderer bytes."""
    def create(source_name="source.html", source_bytes=None, tei_bytes=None):
        relative = "sources/example.source-manifest.json"
        manifest = tmp_path / relative
        manifest.parent.mkdir()
        manifest.write_text("{}", encoding="utf-8")
        source = tmp_path / source_name
        source.write_bytes(source_bytes or b"<html><body><p>Faithful source text.</p></body></html>")
        directory = tmp_path / "candidate"
        directory.mkdir()
        candidate = _candidate(directory, "source-example", relative, "a" * 64)
        if tei_bytes is not None:
            (candidate.path / "content.tei.xml").write_bytes(tei_bytes)
            candidate.member_bytes = lambda name: tei_bytes if name == "content.tei.xml" else b""
        _install_contract_fakes(
            monkeypatch, candidates={directory.resolve(): candidate},
            source_manifest=SimpleNamespace(sha256="b" * 64, record={"source_id": "source-example"}),
            source_path=source,
        )
        catalog = _write_catalog(tmp_path, [_work("brief-example", source_id="source-example", manifest=relative)])
        application = ReviewApplication.from_work_catalog(catalog, [directory], repository_root=tmp_path)
        selection = {
            "left_stage": "source", "left_recorded": RecordedContext("source-" + "b" * 64, "b" * 64, "start"),
            "right_stage": "tei", "right_recorded": RecordedContext("tei-" + "a" * 64, "a" * 64, "start"),
            "linked": False, "correspondence_source": None,
        }
        return application, selection, source
    return create


def test_evidence_brief_keeps_exact_bindings_ranges_and_material_truncation(evidence_pair) -> None:
    tei = ('<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><p>'
           + "Candidate full body. " + "x" * 80000 + '</p><p xml:id="second">Second location.</p></body></text></TEI>').encode()
    application, selection, _ = evidence_pair(tei_bytes=tei)
    selection.update(left_segment_start=0, left_segment_limit=1, right_segment_start=0, right_segment_limit=1)
    full = application.compare_view("brief-example", **selection)
    brief = application.compare_view("brief-example", **selection, evidence_brief=True)
    assert brief["route_digest"] == full["route_digest"]
    assert brief["candidate_validation"] == {
        "status": "pass", "report_sha256": "d" * 64,
        "candidate_sha256": "a" * 64, "source_manifest_sha256": "b" * 64,
    }
    for role in ("left", "right"):
        assert brief["artifacts"][brief[role]["artifact_ref"]]["sha256"] == full[role]["artifact"]["sha256"]
        assert brief[role]["location"] == full[role]["location"]
        assert brief[role]["requested_range"] == [0, 1]
        assert brief[role]["paging"]["segments"] == full[role]["paging"]["segments"]
    assert brief["right"]["availability"] == "available"
    assert {warning["code"] for warning in brief["right"]["warnings"]} == {"segment-oversize", "segment-truncated"}
    assert brief["correspondence"] == full["correspondence"]
    serialized = json.dumps(brief)
    assert "Candidate full body" not in serialized
    assert "Faithful source text" not in serialized
    assert '"nodes"' not in serialized and '"selected_context"' not in serialized
    assert '"base64"' not in serialized and "data:image" not in serialized
    assert len(serialized.encode()) < 10_000 < review_contract.serialized_payload_size(full)
    # Asymmetric requests keep their own range and out-of-range warning.
    selection["right_segment_start"] = 1
    asymmetric = application.compare_view("brief-example", **selection, evidence_brief=True)
    assert asymmetric["left"]["requested_range"] == [0, 1]
    assert asymmetric["right"]["requested_range"] == [1, 1]
    assert asymmetric["right"]["location_state"] == "location-outside-range"
    assert any(w.get("state") == "location-outside-range" for w in asymmetric["right"]["warnings"])


def test_auto_page_stage_and_compare_routes_keep_location_segment_bounded(evidence_pair, tmp_path: Path) -> None:
    tei = ('<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><p>'
           + "Candidate full body. " + "x" * 80000 + '</p><p xml:id="second">Second location.</p></body></text></TEI>').encode()
    application, selection, _ = evidence_pair(tei_bytes=tei)
    selection["right_recorded"] = RecordedContext("tei-" + "a" * 64, "a" * 64, "second")
    recorded = selection["right_recorded"]
    static_root = tmp_path / "dist"
    static_root.mkdir()
    server = review_service.ReviewHTTPServer(("127.0.0.1", 0), application, static_root)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    stage_query = {
        "expected_artifact": recorded.artifact_id,
        "expected_version": recorded.version,
        "location": recorded.location,
    }
    try:
        stage_route = f"/api/review/v1/works/brief-example/stages/tei?{urlencode(stage_query)}"
        with urlopen(origin + stage_route, timeout=10) as response:
            legacy = json.load(response)
        assert legacy["location_state"] == "page-required"

        with urlopen(origin + stage_route + "&auto_page=true", timeout=10) as response:
            stage = json.load(response)
        assert stage["paging"]["segment_count"] > 1
        assert stage["location_state"] == "in-range"
        assert stage["paging"]["segments"][0]["index"] == stage["paging"]["location_segment"]
        assert "Second location." in json.dumps(stage["presentation"]["document"]["nodes"])

        compare_query = {"linked": "false", "correspondence": "absent", "representation": "brief", "auto_page": "true"}
        for role in ("left", "right"):
            pane = selection[f"{role}_recorded"]
            compare_query.update({
                f"{role}_stage": selection[f"{role}_stage"],
                f"{role}_artifact": pane.artifact_id,
                f"{role}_version": pane.version,
                f"{role}_location": pane.location,
            })
        compare_route = "/api/review/v1/works/brief-example/compare?" + urlencode(compare_query)
        with urlopen(origin + compare_route, timeout=10) as response:
            compare = json.load(response)
        assert compare["right"]["location_state"] == "in-range"
        assert compare["right"]["paging"]["segments"][0]["index"] == compare["right"]["paging"]["location_segment"]
        assert "auto_page=true" in compare["detail"]["target"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_evidence_brief_preserves_wrong_identity_missing_location_and_stale_route(evidence_pair) -> None:
    application, selection, _ = evidence_pair()
    current = application.compare_view("brief-example", **selection, evidence_brief=True)
    with pytest.raises(review_contract.RouteStaleError):
        application.compare_view("brief-example", **selection, evidence_brief=True, echoed_route_digest="0" * 64)
    selection["left_recorded"] = RecordedContext("wrong-source", "wrong-version", "start")
    refused = application.compare_view("brief-example", **selection, evidence_brief=True)
    assert refused["left"]["availability"] == "unsupported"
    assert refused["left"]["artifact_ref"] is None
    assert refused["left"]["exact_detail"] is None
    assert refused["artifacts"]["left-requested"] == {"id": "wrong-source", "version": "wrong-version", "sha256": None}
    assert any(w["code"] == "availability" for w in refused["left"]["warnings"])
    with pytest.raises(review_contract.RouteStaleError):
        application.compare_view("brief-example", **selection, evidence_brief=True, echoed_route_digest=current["route_digest"])
    selection["left_recorded"] = RecordedContext("source-" + "b" * 64, "b" * 64, "missing-location")
    missing = application.compare_view("brief-example", **selection, evidence_brief=True)
    assert missing["left"]["recorded_context"]["state"] == "location-missing"
    assert any(w.get("state") == "location-missing" for w in missing["left"]["warnings"])


@pytest.mark.parametrize("name,dimensions_state,available", [
    ("facsimile.png", "known", True), ("facsimile.jpg", "known", True),
    ("facsimile.tiff", "unknown", False),
])
def test_evidence_brief_image_metadata_reuses_verified_bytes(
    evidence_pair, monkeypatch: pytest.MonkeyPatch, name: str, dimensions_state: str, available: bool,
) -> None:
    payload = (Path(__file__).parents[1] / "fixtures/review-v1/artifacts/binary-contract" / name).read_bytes()
    application, selection, source = evidence_pair(name, payload)
    original_read = Path.read_bytes
    reads = []
    def record_read(path):
        reads.append(path)
        return original_read(path)
    monkeypatch.setattr(Path, "read_bytes", record_read)
    brief = application.compare_view("brief-example", **selection, evidence_brief=True)
    assert reads.count(source.resolve()) == 1
    repeated = application.compare_view("brief-example", **selection, evidence_brief=True)
    assert reads.count(source.resolve()) == 1
    image = brief["left"]["image"]
    assert repeated["left"]["image"] == image
    assert image["dimensions_state"] == dimensions_state
    assert image["original_dimensions"] == ({"width": 1, "height": 1, "basis": "encoded-png-ihdr" if name.endswith(".png") else "encoded-image-header"} if dimensions_state == "known" else None)
    assert image["presentation_available"] is available
    assert image["original_ref"] == "exact_detail"
    assert brief["left"]["exact_detail"]["kind"] == "exact-bytes"
    assert brief["artifacts"]["left"]["member"]["name"] == "fixture-primary-source"
    if not available:
        assert any(w["state"] == "unsupported" for w in brief["left"]["warnings"])


@pytest.mark.parametrize("failure", ["short-header", "bad-crc", "bad-signature", "wrong-hash"])
def test_evidence_brief_never_infers_dimensions_from_bad_png(evidence_pair, failure: str) -> None:
    payload = (Path(__file__).parents[1] / "fixtures/review-v1/artifacts/binary-contract/facsimile.png").read_bytes()
    if failure == "short-header":
        payload = payload[:16]
    elif failure == "bad-crc":
        payload = payload[:29] + b"\x00\x00\x00\x00" + payload[33:]
    elif failure == "bad-signature":
        payload = b"not PNG"
    application, selection, source = evidence_pair("source.png", payload)
    if failure == "wrong-hash":
        source.write_bytes(b"mutated after admission")
    brief = application.compare_view("brief-example", **selection, evidence_brief=True)
    assert brief["left"]["image"]["original_dimensions"] is None
    if failure in {"bad-signature", "wrong-hash"}:
        assert brief["left"]["availability"] == "unsupported"
        assert brief["left"]["exact_detail"] is None


def test_evidence_brief_http_continuations_and_existing_bounds(
    evidence_pair, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    application, selection, _ = evidence_pair()
    static_root = tmp_path / "dist"
    static_root.mkdir()
    server = review_service.ReviewHTTPServer(("127.0.0.1", 0), application, static_root)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    query = {"linked": "false", "correspondence": "absent", "representation": "brief"}
    for role in ("left", "right"):
        recorded = selection[f"{role}_recorded"]
        query.update({f"{role}_stage": selection[f"{role}_stage"], f"{role}_artifact": recorded.artifact_id,
                      f"{role}_version": recorded.version, f"{role}_location": recorded.location})
    route = "/api/review/v1/works/brief-example/compare?" + urlencode(query)
    # This checks HTTP behavior, not latency under the parallel corpus load.
    request_timeout = 10
    try:
        with urlopen(origin + route, timeout=request_timeout) as response:
            brief = json.load(response)
            assert response.headers["Cache-Control"] == "no-store"
        assert brief["contract"] == review_contract.EVIDENCE_BRIEF_CONTRACT
        with urlopen(origin + brief["right"]["exact_detail"]["target"], timeout=request_timeout) as response:
            assert b"Faithful candidate text" in response.read()
        with urlopen(origin + brief["detail"]["target"], timeout=request_timeout) as response:
            full = json.load(response)
        assert full["contract"] == review_contract.COMPARE_VIEW_CONTRACT
        assert full["route_digest"] == brief["route_digest"]
        for suffix, code in (
            ("&representation=brief", "artifact-invalid"),
            ("&route_digest=" + "0" * 64, "route-stale"),
            ("&left_segment_start=0&left_segment_limit=9", "range-invalid"),
        ):
            with pytest.raises(HTTPError) as captured:
                urlopen(origin + route + suffix, timeout=request_timeout)
            assert captured.value.code == 422
            assert json.load(captured.value)["error"]["code"] == code
        with pytest.raises(HTTPError) as captured:
            urlopen(origin + route.replace("representation=brief", "representation=invalid"), timeout=request_timeout)
        assert json.load(captured.value)["error"]["code"] == "artifact-invalid"
        # No warning trimming or exceptions to the existing transport bound.
        monkeypatch.setattr(review_service, "MAX_RESPONSE_SERIALIZED_BYTES", 1000)
        with pytest.raises(HTTPError) as captured:
            urlopen(origin + route, timeout=request_timeout)
        assert json.load(captured.value)["error"]["code"] == "response-too-large"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
def test_tei_corpus_public_stage_view_keeps_each_work_in_one_bounded_segment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_manifest_relative = "sources/corpus/corpus.source-manifest.json"
    source_manifest_path = tmp_path / source_manifest_relative
    source_manifest_path.parent.mkdir(parents=True)
    source_manifest_path.write_text("{}", encoding="utf-8")
    source_path = tmp_path / "retained" / "source.xml"
    source_path.parent.mkdir()
    source_path.write_text("<source>Retained source.</source>", encoding="utf-8")
    corpus = (
        b'<teiCorpus xmlns="http://www.tei-c.org/ns/1.0">'
        b'<TEI><text><body><div xml:id="first-work"><head>First Work</head>'
        b'<p>First work body only.</p></div></body></text></TEI>'
        b'<TEI><text><body><div xml:id="second-work"><head>Second Work</head>'
        b'<p>Second work body only.</p></div></body></text></TEI>'
        b"</teiCorpus>"
    )
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    candidate = _candidate(
        candidate_dir,
        "source-corpus",
        source_manifest_relative,
        "a" * 64,
        tei=corpus,
    )
    source_manifest = SimpleNamespace(
        sha256="b" * 64,
        record={"source_id": "source-corpus"},
    )
    _install_contract_fakes(
        monkeypatch,
        candidates={candidate_dir.resolve(): candidate},
        source_manifest=source_manifest,
        source_path=source_path,
    )
    catalog_path = _write_catalog(
        tmp_path,
        [
            _work(
                "two-work-corpus",
                source_id="source-corpus",
                manifest=source_manifest_relative,
            )
        ],
    )
    application = ReviewApplication.from_work_catalog(
        catalog_path,
        [candidate_dir],
        repository_root=tmp_path,
    )
    tei_stage = application.catalog()["works"][0]["stages"][1]
    artifact = tei_stage["selected_artifact"]

    responses = [
        application.stage_view(
            "two-work-corpus",
            "tei",
            recorded=RecordedContext(
                artifact["id"], artifact["version"], location
            ),
            segment_start=index,
            segment_limit=1,
        )
        for index, location in enumerate(("first-work", "second-work"))
    ]

    for index, response in enumerate(responses):
        assert response["paging"]["segment_count"] == 2
        assert response["paging"]["max_segments_per_request"] == 1
        assert [segment["index"] for segment in response["paging"]["segments"]] == [
            index
        ]
        assert "_hard_break_before" not in json.dumps(response)
        assert '"_pages"' not in json.dumps(response)
    first_nodes = json.dumps(responses[0]["presentation"]["document"]["nodes"])
    second_nodes = json.dumps(responses[1]["presentation"]["document"]["nodes"])
    assert "First work body only." in first_nodes
    assert "Second work body only." not in first_nodes
    assert "Second work body only." in second_nodes
    assert "First work body only." not in second_nodes


def test_nave_zld_public_seam_keeps_four_exact_selections_readable_and_unlinked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repeated_markers = ("→ marker " * 7_202).strip()
    entries = (
        ("AARON", b'First <ref target="JESUS">Jesus</ref>'),
        ("GOD", repeated_markers.encode("utf-8")),
        ("JAPHLET", b"Middle dictionary record."),
        ("JESUS", repeated_markers.encode("utf-8")),
        ("ZUZIMS", b"Terminal dictionary record."),
    )
    source_manifest_relative = "sources/nave/nave.source-manifest.json"
    source_manifest_path = tmp_path / source_manifest_relative
    source_manifest_path.parent.mkdir(parents=True)
    source_manifest_path.write_text("{}", encoding="utf-8")
    source_manifest, source_path, paths = _small_nave_packet(tmp_path, entries)
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    candidate = _candidate(
        candidate_dir,
        "crosswire-nave-sword-v3",
        source_manifest_relative,
        "a" * 64,
        tei=(
            (
                '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
                + "".join(
                    f'<entryFree n="{key}"><form><orth>{key}</orth></form>'
                    f"<def>{definition.decode('utf-8')}</def></entryFree>"
                    for key, definition in entries
                )
                + "</body></text></TEI>"
            ).encode("utf-8")
        ),
    )
    _install_contract_fakes(
        monkeypatch,
        candidates={candidate_dir.resolve(): candidate},
        source_manifest=source_manifest,
        source_path=source_path,
    )
    catalog_path = _write_catalog(
        tmp_path,
        [
            _work(
                "naves-topical-bible",
                source_id="crosswire-nave-sword-v3",
                manifest=source_manifest_relative,
            )
        ],
    )
    application = ReviewApplication.from_work_catalog(
        catalog_path,
        [candidate_dir],
        repository_root=tmp_path,
    )
    work = application.catalog()["works"][0]
    source_stage, tei_stage = work["stages"][:2]
    assert source_stage["availability"] == "selection-required"
    assert source_stage["selected_artifact"] is None
    assert [artifact["name"] for artifact in source_stage["artifacts"]] == [
        "dict-zdt",
        "dict-zdx",
        "dict-dat",
        "dict-idx",
    ]

    tei_artifact = tei_stage["selected_artifact"]
    source_public_texts = []
    for source_artifact in source_stage["artifacts"]:
        source_recorded = RecordedContext(
            source_artifact["id"], source_artifact["version"], "start"
        )
        view = application.stage_view(
            "naves-topical-bible",
            "source",
            recorded=source_recorded,
            segment_start=0,
            segment_limit=1,
        )
        assert view["availability"] == "available"
        assert view["artifact"]["sha256"] == source_artifact["sha256"]
        assert view["presentation"]["kind"] == "sword-zld-reader"
        visible = json.dumps(view["presentation"], ensure_ascii=False)
        assert f"Selected exact carrier: {source_artifact['name']}" in visible
        assert "AARON ⟦entryFree/@n:AARON⟧" in visible
        assert "⟦target:JESUS⟧" in visible
        source_views = [view] + [
            application.stage_view(
                "naves-topical-bible",
                "source",
                recorded=source_recorded,
                segment_start=index,
                segment_limit=1,
            )
            for index in range(1, view["paging"]["segment_count"])
        ]
        source_segments = [
            response["paging"]["segments"][0] for response in source_views
        ]
        source_nodes = [
            node
            for response in source_views
            for node in response["presentation"]["document"]["nodes"]
        ]
        source_public_text = " ".join(node["text"] for node in source_nodes)
        source_public_texts.append(source_public_text)
        assert source_public_text.count("→") == 14_404
        assert sum(node["text"].startswith("2. GOD ") for node in source_nodes) == 1
        assert sum(node["text"].startswith("3. JAPHLET ") for node in source_nodes) == 1
        assert sum(node["text"].startswith("5. ZUZIMS ") for node in source_nodes) == 1
        assert all(
            segment["scalar_count"] <= MAX_PAGE_SCALARS
            for segment in source_segments
        )
        assert all("oversize" not in segment for segment in source_segments)
        assert all("truncated" not in segment for segment in source_segments)
        compare = application.compare_view(
            "naves-topical-bible",
            left_stage="source",
            left_recorded=source_recorded,
            right_stage="tei",
            right_recorded=RecordedContext(
                tei_artifact["id"], tei_artifact["version"], "start"
            ),
            linked=False,
            correspondence_source=None,
        )
        assert compare["left"]["availability"] == "available"
        assert compare["right"]["availability"] == "available"
        assert compare["linked_navigation"] is False
        assert compare["correspondence"]["state"] == "absent"

    tei_recorded = RecordedContext(
        tei_artifact["id"], tei_artifact["version"], "start"
    )
    tei_first = application.stage_view(
        "naves-topical-bible",
        "tei",
        recorded=tei_recorded,
        segment_start=0,
        segment_limit=1,
    )
    tei_views = [tei_first] + [
        application.stage_view(
            "naves-topical-bible",
            "tei",
            recorded=tei_recorded,
            segment_start=index,
            segment_limit=1,
        )
        for index in range(1, tei_first["paging"]["segment_count"])
    ]
    tei_segments = [response["paging"]["segments"][0] for response in tei_views]
    tei_nodes = [
        node
        for response in tei_views
        for node in response["presentation"]["document"]["nodes"]
    ]
    tei_public_text = " ".join(node["text"] for node in tei_nodes)
    assert tei_public_text.count("→") == 14_404
    for label in ("AARON", "JAPHLET", "ZUZIMS"):
        assert sum(node["text"].startswith(f"{label} ") for node in tei_nodes) == 1
    assert all(
        segment["scalar_count"] <= MAX_PAGE_SCALARS for segment in tei_segments
    )
    assert all("oversize" not in segment for segment in tei_segments)
    assert all("truncated" not in segment for segment in tei_segments)
    assert len(set(source_public_texts)) == 4

    paths["dict-idx"].write_bytes(b"drift")
    drifted = application.stage_view(
        "naves-topical-bible",
        "source",
        recorded=RecordedContext(
            source_stage["artifacts"][0]["id"],
            source_stage["artifacts"][0]["version"],
            "start",
        ),
    )
    assert drifted["availability"] == "unsupported"
    assert "context presentation member bytes drifted: dict-idx" in drifted["message"]
def test_paradise_style_multi_source_is_unselected_and_every_authority_can_be_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_manifest_relative = "sources/paradise/paradise.source-manifest.json"
    source_manifest_path = tmp_path / source_manifest_relative
    source_manifest_path.parent.mkdir(parents=True)
    source_manifest_path.write_text("{}", encoding="utf-8")
    license_path = tmp_path / "raw" / "paradise" / "LICENSE.md"
    book_path = tmp_path / "raw" / "paradise" / "book-1.xhtml"
    license_path.parent.mkdir(parents=True)
    license_path.write_text("Retained rights evidence.", encoding="utf-8")
    book_path.write_text(
        "<html><body><h1>Book I</h1><p>Of Man's first disobedience.</p></body></html>",
        encoding="utf-8",
    )
    primary = (
        {
            "name": "source-001",
            "role": "primary-source",
            "path": "raw/paradise/LICENSE.md",
            "bytes": license_path.stat().st_size,
            "sha256": _sha(license_path.read_bytes()),
        },
        {
            "name": "source-018",
            "role": "primary-source",
            "path": "raw/paradise/book-1.xhtml",
            "bytes": book_path.stat().st_size,
            "sha256": _sha(book_path.read_bytes()),
        },
    )
    source_manifest = SimpleNamespace(
        sha256="b" * 64,
        repository_root=tmp_path,
        record={"source_id": "paradise-source", "authorities": primary},
        authority_path=lambda name: {
            "source-001": license_path,
            "source-018": book_path,
        }[name],
    )
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    candidate = _candidate(
        candidate_dir,
        "paradise-source",
        source_manifest_relative,
        "a" * 64,
    )
    _install_contract_fakes(
        monkeypatch,
        candidates={candidate_dir.resolve(): candidate},
        source_manifest=source_manifest,
        source_path=license_path,
    )
    catalog_path = _write_catalog(
        tmp_path,
        [_work("paradise-lost", source_id="paradise-source", manifest=source_manifest_relative)],
    )

    application = ReviewApplication.from_work_catalog(
        catalog_path, [candidate_dir], repository_root=tmp_path
    )
    source_stage = application.catalog()["works"][0]["stages"][0]

    detail = application.work_detail("paradise-lost")["work"]
    assert len(detail["candidate_validations"]) == 1
    assert detail["candidate_validations"][0]["source_id"] == "paradise-source"
    assert detail["candidate_validations"][0]["source_artifact_count"] == 2

    assert source_stage["availability"] == "selection-required"
    assert source_stage["selected_artifact"] is None
    assert source_stage["message"] == (
        "Choose a retained source. Multiple manifest-bound authorities are available; "
        "the viewer will not guess."
    )
    assert [
        {
            key: artifact[key]
            for key in ("name", "path", "bytes", "sha256")
        }
        for artifact in source_stage["artifacts"]
    ] == [
        {
            "name": item["name"],
            "path": item["path"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        for item in primary
    ]

    license_artifact, book_artifact = source_stage["artifacts"]
    book_view = application.stage_view(
        "paradise-lost",
        "source",
        recorded=RecordedContext(
            book_artifact["id"], book_artifact["version"], "start"
        ),
    )
    assert book_view["availability"] == "available"
    assert book_view["artifact"]["id"] == book_artifact["id"]
    assert book_view["artifact"]["sha256"] == primary[1]["sha256"]
    assert book_view["paging"]["max_segments_per_request"] == 1
    with pytest.raises(ReviewContractError, match="segment_limit must be between 1 and 1"):
        application.stage_view(
            "paradise-lost",
            "source",
            recorded=RecordedContext(
                book_artifact["id"], book_artifact["version"], "start"
            ),
            segment_start=0,
            segment_limit=2,
        )
    assert "Of Man's first disobedience" in application.exact(
        "paradise-lost", "source", book_artifact["id"], book_artifact["version"]
    )
    assert application.exact(
        "paradise-lost", "source", license_artifact["id"], license_artifact["version"]
    ) == "Retained rights evidence."

    static_root = tmp_path / "dist"
    static_root.mkdir()
    (static_root / "review.html").write_text("review", encoding="utf-8")
    server = review_service.ReviewHTTPServer(
        ("127.0.0.1", 0), application, static_root
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        response = json.loads(
            urlopen(
                origin
                + "/api/review/v1/works/paradise-lost/stages/source"
                + f"?expected_artifact={book_artifact['id']}"
                + f"&expected_version={book_artifact['version']}"
                + "&location=start",
                timeout=2,
            ).read()
        )
        assert response["recorded_context"]["state"] == "exact"
        assert response["artifact"]["id"] == book_artifact["id"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_work_catalog_loader_rejects_duplicate_candidate_directories(tmp_path: Path) -> None:
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    catalog_path = _write_catalog(tmp_path, [_work("one")])

    with pytest.raises(ReviewContractError, match="candidate directory is duplicated"):
        ReviewApplication.from_work_catalog(
            catalog_path,
            [candidate_dir, candidate_dir],
            repository_root=tmp_path,
        )


def test_work_catalog_loader_rejects_duplicate_candidate_digests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relative = "sources/example.source-manifest.json"
    manifest_path = tmp_path / relative
    manifest_path.parent.mkdir()
    manifest_path.write_text("{}", encoding="utf-8")
    source_path = tmp_path / "source.txt"
    source_path.write_text("source", encoding="utf-8")
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    digest = "a" * 64
    candidates = {
        first.resolve(): _candidate(first, "source-one", relative, digest),
        second.resolve(): _candidate(second, "source-two", relative, digest),
    }
    source_manifest = SimpleNamespace(sha256="b" * 64, record={"source_id": "source-one"})
    _install_contract_fakes(
        monkeypatch,
        candidates=candidates,
        source_manifest=source_manifest,
        source_path=source_path,
    )
    catalog_path = _write_catalog(
        tmp_path,
        [
            _work("one", source_id="source-one", manifest=relative),
            _work("two", source_id="source-two", manifest=relative),
        ],
    )

    with pytest.raises(ReviewContractError, match="candidate manifest digest is duplicated"):
        ReviewApplication.from_work_catalog(
            catalog_path,
            [first, second],
            repository_root=tmp_path,
        )


@pytest.mark.parametrize(
    "relative",
    (
        "sources/example.source-manifest.json",
        "sources/structured-text/lib072-gutenberg-evangelical/work-bindings/"
        "wilberforce-practical-view/37c-322-v3-scope-v1-source-manifest.json",
    ),
)
def test_work_catalog_loader_binds_one_shared_candidate_to_every_exact_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    manifest_path = tmp_path / relative
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}", encoding="utf-8")
    source_path = tmp_path / "source.txt"
    source_path.write_text("source", encoding="utf-8")
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    candidate = _candidate(candidate_dir, "shared-source", relative, "a" * 64)
    source_manifest = SimpleNamespace(sha256="b" * 64, record={"source_id": "shared-source"})
    _install_contract_fakes(
        monkeypatch,
        candidates={candidate_dir.resolve(): candidate},
        source_manifest=source_manifest,
        source_path=source_path,
    )
    catalog_path = _write_catalog(
        tmp_path,
        [
            _work("one", source_id="shared-source", manifest=relative),
            _work("two", source_id="shared-source", manifest=relative),
        ],
    )

    catalog = ReviewApplication.from_work_catalog(
        catalog_path,
        [candidate_dir],
        repository_root=tmp_path,
    ).catalog()

    assert [work["slug"] for work in catalog["works"]] == ["one", "two"]
    assert all(
        work["candidate_validation"] == {
            "status": "pass",
            "report_sha256": "d" * 64,
            "candidate_sha256": "a" * 64,
            "source_manifest_sha256": "b" * 64,
        }
        for work in catalog["works"]
    )
    assert all(
        [stage["availability"] for stage in work["stages"]]
        == ["available", "available"]
        for work in catalog["works"]
    )


def test_work_catalog_loader_rejects_same_byte_manifest_at_candidate_alias_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_relative = (
        "sources/structured-text/lib072-gutenberg-evangelical/work-bindings/"
        "wilberforce-practical-view/37c-322-v3-scope-v1-source-manifest.json"
    )
    alias_relative = (
        "sources/structured-text/lib072-gutenberg-evangelical/work-bindings/"
        "wilberforce-practical-view/37c-322-v3-scope-v1.source-manifest.json"
    )
    package_manifest_path = tmp_path / package_relative
    alias_manifest_path = tmp_path / alias_relative
    package_manifest_path.parent.mkdir(parents=True)
    alias_manifest_path.write_bytes(b"identical source-manifest bytes\n")
    package_manifest_path.write_bytes(alias_manifest_path.read_bytes())
    assert _sha(package_manifest_path.read_bytes()) == _sha(
        alias_manifest_path.read_bytes()
    )

    source_path = tmp_path / "retained" / "source.txt"
    source_path.parent.mkdir()
    source_path.write_text("source", encoding="utf-8")
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    candidate = _candidate(
        candidate_dir,
        "shared-source",
        package_relative,
        "a" * 64,
    )
    source_manifest = SimpleNamespace(
        sha256="b" * 64,
        record={"source_id": "shared-source"},
    )
    _install_contract_fakes(
        monkeypatch,
        candidates={candidate_dir.resolve(): candidate},
        source_manifest=source_manifest,
        source_path=source_path,
    )
    catalog_path = _write_catalog(
        tmp_path,
        [_work("wilberforce", source_id="shared-source", manifest=alias_relative)],
    )

    # Matching bytes and source ID do not replace the package's exact route path.
    with pytest.raises(
        ReviewContractError,
        match="candidate 1 does not resolve to a WorkCatalog route",
    ):
        ReviewApplication.from_work_catalog(
            catalog_path,
            [candidate_dir],
            repository_root=tmp_path,
        )


def test_work_catalog_loader_exposes_each_exact_candidate_member_for_one_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_relative = "sources/equiano/part-1.source-manifest.json"
    second_relative = "sources/equiano/part-2.source-manifest.json"
    first_manifest_path = tmp_path / first_relative
    second_manifest_path = tmp_path / second_relative
    first_manifest_path.parent.mkdir(parents=True)
    first_manifest_path.write_text("{}", encoding="utf-8")
    second_manifest_path.write_text("{}", encoding="utf-8")
    first_source_path = tmp_path / "retained" / "part-1.txt"
    second_source_path = tmp_path / "retained" / "part-2.txt"
    first_source_path.parent.mkdir()
    first_source_path.write_text("part one", encoding="utf-8")
    second_source_path.write_text("part two", encoding="utf-8")

    def loaded_source(
        source_id: str, digest: str, source_path: Path
    ) -> SimpleNamespace:
        payload = source_path.read_bytes()
        return SimpleNamespace(
            sha256=digest,
            record={
                "source_id": source_id,
                "authorities": (
                    {
                        "name": source_path.name,
                        "role": "primary-source",
                        "path": source_path.relative_to(tmp_path).as_posix(),
                        "bytes": len(payload),
                        "sha256": _sha(payload),
                    },
                ),
            },
            repository_root=tmp_path,
            authority_path=lambda name, path=source_path: path,
        )

    first_source = loaded_source(
        "equiano-source", "b" * 64, first_source_path
    )
    second_source = loaded_source(
        "equiano-source", "d" * 64, second_source_path
    )
    source_manifests = {
        first_manifest_path.resolve(): first_source,
        second_manifest_path.resolve(): second_source,
    }
    first = tmp_path / "part-1"
    second = tmp_path / "part-2"
    first.mkdir()
    second.mkdir()
    first_candidate = _candidate(
        first, "equiano-source", first_relative, "a" * 64
    )
    second_candidate = _candidate(
        second, "equiano-source", second_relative, "c" * 64
    )
    second_candidate.manifest = MappingProxyType(
        {
            **second_candidate.manifest,
            "source_manifest": MappingProxyType(
                {"path": second_relative, "sha256": "d" * 64}
            ),
        }
    )
    candidates = {
        first.resolve(): first_candidate,
        second.resolve(): second_candidate,
    }
    monkeypatch.setattr(
        review_contract.CandidatePackage,
        "load",
        classmethod(lambda cls, path: candidates[Path(path).resolve().parent]),
    )
    monkeypatch.setattr(
        review_contract.SourceManifest,
        "load",
        classmethod(
            lambda cls, path, *, repository_root: source_manifests[
                Path(path).resolve()
            ]
        ),
    )
    monkeypatch.setattr(
        review_contract,
        "_load_validation_report",
        lambda candidate_dir, loaded_source, candidate, **kwargs: SimpleNamespace(
            status="pass",
            sha256=("e" if candidate.sha256 == "a" * 64 else "f") * 64,
            candidate_sha256=candidate.sha256,
            source_manifest_sha256=loaded_source.sha256,
        ),
    )
    work = _work(
        "equiano-interesting-narrative",
        source_id="equiano-source",
        manifest=first_relative,
    )
    work["reconstruction_state"]["routes"].append(
        {
            **work["reconstruction_state"]["routes"][0],
            "manifest": second_relative,
        }
    )
    catalog = ReviewApplication.from_work_catalog(
        _write_catalog(tmp_path, [work]),
        [first, second],
        repository_root=tmp_path,
    ).catalog()

    bound = catalog["works"][0]
    assert bound["candidate_validation"] is None
    assert [item["source_id"] for item in bound["candidate_validations"]] == [
        "equiano-source",
        "equiano-source",
    ]
    assert [item["candidate_sha256"] for item in bound["candidate_validations"]] == [
        "a" * 64,
        "c" * 64,
    ]
    assert [stage["availability"] for stage in bound["stages"]] == [
        "selection-required",
        "available",
    ]
    assert len(bound["stages"][0]["artifacts"]) == 2
    assert len(bound["stages"][1]["artifacts"]) == 2
    assert [
        item["source_artifact_ids"]
        for item in bound["candidate_validations"]
    ] == [
        ["source-" + "b" * 64],
        ["source-" + "d" * 64],
    ]


def test_work_catalog_loader_rejects_duplicate_routes_for_one_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relative = "sources/example.source-manifest.json"
    manifest_path = tmp_path / relative
    manifest_path.parent.mkdir()
    manifest_path.write_text("{}", encoding="utf-8")
    source_path = tmp_path / "source.txt"
    source_path.write_text("source", encoding="utf-8")
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    candidate = _candidate(candidate_dir, "shared-source", relative, "a" * 64)
    source_manifest = SimpleNamespace(sha256="b" * 64, record={"source_id": "shared-source"})
    _install_contract_fakes(
        monkeypatch,
        candidates={candidate_dir.resolve(): candidate},
        source_manifest=source_manifest,
        source_path=source_path,
    )
    work = _work("one", source_id="shared-source", manifest=relative)
    routes = work["reconstruction_state"]["routes"]
    routes.append(dict(routes[0]))
    catalog_path = _write_catalog(tmp_path, [work])

    with pytest.raises(ReviewContractError, match="duplicate routes for WorkCatalog work one"):
        ReviewApplication.from_work_catalog(
            catalog_path,
            [candidate_dir],
            repository_root=tmp_path,
        )


def test_work_catalog_loader_fails_closed_on_current_source_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relative = "sources/example.source-manifest.json"
    manifest_path = tmp_path / relative
    manifest_path.parent.mkdir()
    manifest_path.write_text("{}", encoding="utf-8")
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    candidate = _candidate(candidate_dir, "source-example", relative, "a" * 64)
    monkeypatch.setattr(
        review_contract.CandidatePackage,
        "load",
        classmethod(lambda cls, path: candidate),
    )
    monkeypatch.setattr(
        review_contract.SourceManifest,
        "load",
        classmethod(
            lambda cls, path, *, repository_root: (_ for _ in ()).throw(
                ValueError("primary-source authority bytes drifted")
            )
        ),
    )
    catalog_path = _write_catalog(
        tmp_path,
        [_work("one", source_id="source-example", manifest=relative)],
    )

    with pytest.raises(ReviewContractError, match="primary-source authority bytes drifted"):
        ReviewApplication.from_work_catalog(
            catalog_path,
            [candidate_dir],
            repository_root=tmp_path,
        )


def test_launch_parser_requires_catalog_and_accepts_repeated_candidate_directories() -> None:
    parser = review_service.build_argument_parser()
    args = parser.parse_args(
        [
            "--catalog",
            "work-catalog.json",
            "--candidate-dir",
            "candidate-one",
            "--candidate-dir",
            "candidate-two",
        ]
    )

    assert args.catalog == Path("work-catalog.json")
    assert args.candidate_dir == [Path("candidate-one"), Path("candidate-two")]
    with pytest.raises(SystemExit):
        parser.parse_args(["--manifest", "legacy.json", "--root", "legacy=path"])


def test_new_server_launch_has_no_note_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    static_root = tmp_path / "dist"
    static_root.mkdir()
    application = SimpleNamespace(roots={})
    monkeypatch.setattr(
        review_service.ReviewApplication,
        "from_work_catalog",
        classmethod(lambda cls, catalog, candidates, *, repository_root=None: application),
    )

    server = review_service.make_server(
        tmp_path / "catalog.json",
        [tmp_path / "candidate"],
        static_root=static_root,
        port=0,
        repository_root=tmp_path,
        application=application,
    )
    try:
        assert server.application is application
        assert not hasattr(server, "notes")
    finally:
        server.server_close()


def test_server_factory_requires_protected_candidate_session_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    static_root = tmp_path / "dist"
    static_root.mkdir()
    monkeypatch.setattr(
        review_service.ReviewApplication,
        "from_work_catalog",
        classmethod(
            lambda cls, catalog, candidates, *, repository_root=None: (_ for _ in ()).throw(
                AssertionError("direct server construction bypassed preflight")
            )
        ),
    )

    with pytest.raises(ValueError, match="protected candidate-session preflight"):
        review_service.make_server(
            tmp_path / "catalog.json",
            [tmp_path / "candidate"],
            static_root=static_root,
            port=0,
            repository_root=tmp_path,
        )


@pytest.mark.parametrize("inject_windows_abort", [False, True])
def test_service_has_no_notes_structure_or_pair_capability_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inject_windows_abort: bool
) -> None:
    aborted = False
    if inject_windows_abort:
        actual_urlopen = urlopen

        def abort_once(request, *args, **kwargs):
            nonlocal aborted
            if isinstance(request, Request) and not aborted:
                aborted = True
                error = ConnectionAbortedError("synthetic Windows loopback abort")
                error.winerror = 10053
                raise error
            return actual_urlopen(request, *args, **kwargs)

        monkeypatch.setitem(globals(), "urlopen", abort_once)
    static_root = tmp_path / "dist"
    static_root.mkdir()
    application = SimpleNamespace(
        roots={},
        catalog=lambda: {
            "contract": "ocd-corpus-review-catalog-v1",
            "manifest_contract": "ocd-corpus-review-manifest-v1",
            "approved_roots": [],
            "works": [],
        },
    )
    monkeypatch.setattr(
        review_service.ReviewApplication,
        "from_work_catalog",
        classmethod(lambda cls, catalog, candidates, *, repository_root=None: application),
    )
    server = review_service.make_server(
        tmp_path / "catalog.json",
        [tmp_path / "candidate"],
        static_root=static_root,
        port=0,
        repository_root=tmp_path,
        application=application,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        for route in (
            "/api/review/v1/works/example/notes",
            "/api/review/v1/works/example/structure",
            "/api/review/v1/works/example/pair-capability",
        ):
            with pytest.raises(HTTPError) as caught:
                urlopen(origin + route, timeout=2)
            assert caught.value.code == 404
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            request = Request(
                origin + "/api/review/v1/notes",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method=method,
            )
            # A Windows loopback transport abort can precede the HTTP status.
            for attempt in range(2):
                try:
                    with pytest.raises(HTTPError) as caught:
                        urlopen(request, timeout=2)
                    break
                except ConnectionAbortedError as error:
                    if getattr(error, "winerror", None) != 10053 or attempt:
                        raise
            assert caught.value.code == 404
            assert "does not expose write routes" in caught.value.read().decode("utf-8")
        assert aborted == inject_windows_abort
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("count", [3, 256])
def test_candidate_binding_uses_verified_authority_records_without_linear_rescan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    count: int,
) -> None:
    from collections import Counter
    from threading import Lock, get_ident

    source_root = tmp_path / "raw" / "large-source"
    source_root.mkdir(parents=True)
    authorities = []
    for index in range(count):
        path = source_root / f"member-{index}.txt"
        payload = f"member {index}".encode("utf-8")
        path.write_bytes(payload)
        authorities.append(
            {
                "name": f"member-{index}",
                "role": "primary-source",
                "path": path.relative_to(tmp_path).as_posix(),
                "bytes": len(payload),
                "sha256": _sha(payload),
            }
        )
    source_manifest = SimpleNamespace(
        sha256="b" * 64,
        repository_root=tmp_path,
        record={"source_id": "large-source", "authorities": tuple(authorities)},
        authority_path=lambda name: (_ for _ in ()).throw(
            AssertionError(f"authority_path rescanned {name}")
        ),
    )
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    candidate = _candidate(candidate_dir, "large-source", "source.json", "a" * 64)
    binding = {
        "review": SimpleNamespace(source_manifest=source_manifest),
        "candidate": candidate,
        "validation": SimpleNamespace(sha256="d" * 64),
        "route": {"scope": "work"},
    }

    contained = review_contract._contained
    checked = Counter()
    threads = set()
    lock = Lock()

    def observed(root, path, name):
        with lock:
            checked[name] += 1
            threads.add(get_ident())
        return contained(root, path, name)

    monkeypatch.setattr(review_contract, "_contained", observed)
    source_artifacts, _, _, scope = review_contract._materialize_candidate_binding(
        "large-work", binding, {}, []
    )

    assert scope == "work"
    assert [artifact["name"] for artifact in source_artifacts] == [f"member-{index}" for index in range(count)]
    assert [artifact["bytes"] for artifact in source_artifacts] == [len(f"member {index}") for index in range(count)]
    assert checked == Counter({f"member-{index}": 1 for index in range(count)})
    assert len(threads) == 1
    late_source = source_root / f"member-{count - 1}.txt"
    late_source.write_text(f"MEMBER {count - 1}", encoding="utf-8")
    with pytest.raises(ReviewContractError, match="primary-source authority bytes drifted"):
        review_contract._materialize_candidate_binding("large-work", binding, {}, [])

    # A double must not substitute a path outside its declared repository when
    # the authority's actual logical path is missing there.
    declared_repo = tmp_path / "declared-repo"
    declared_repo.mkdir()
    source_manifest.repository_root = declared_repo
    source_manifest.authority_path = lambda name: source_root / f"{name}.txt"
    with pytest.raises(FileNotFoundError):
        review_contract._materialize_candidate_binding("large-work", binding, {}, [])


@pytest.mark.parametrize(
    ('candidate_work_id', 'route_work_path', 'route_acquisition_path', 'selected_source_path', 'expected_error'),
    [
        ('direct-work', 'library/works/direct-work/work.json', 'library/works/direct-work/forms/direct-form/editions/direct-edition/acquisitions/acquisition.json', 'raw/source.xml#book', None),
        ('direct-work', None, 'library/works/direct-work/forms/direct-form/editions/direct-edition/acquisitions/acquisition.json', 'raw/source.xml#book', 'requires work_identity_authority binding'),
        ('direct-work', 'library/works/direct-work/work.json', None, 'raw/source.xml#book', 'requires acquisition_selection_authority binding'),
        ('direct-work', 'library/works/direct-work/work.json', 'library/works/direct-work/forms/direct-form/editions/direct-edition/acquisitions/other-acquisition.json', 'raw/source.xml#book', 'differs from the declared route'),
        ('substituted-work', 'library/works/direct-work/work.json', 'library/works/direct-work/forms/direct-form/editions/direct-edition/acquisitions/acquisition.json', 'raw/source.xml#book', 'manifest work_id differs from route work'),
        ('direct-work', 'library/works/direct-work/work.json', 'library/works/direct-work/forms/direct-form/editions/direct-edition/acquisitions/acquisition.json', 'raw/other.xml', 'selected review primary sources differ'),
    ],
)
def test_candidate_binding_binds_acquisition_direct_source_path_to_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    candidate_work_id: str,
    route_work_path: str | None,
    route_acquisition_path: str | None,
    selected_source_path: str,
    expected_error: str | None,
) -> None:
    source_path = tmp_path / "raw" / "source.xml"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><p>Source.</p></body></text></TEI>',
        encoding="utf-8",
    )
    work_path = tmp_path / "library" / "works" / "direct-work" / "work.json"
    work_path.parent.mkdir(parents=True)
    work_path.write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "work_id": "direct-work",
                "title": "Direct work",
                "evidence": ["fixture/direct-source"],
                "textual_forms": [
                    {
                        "textual_form_id": "direct-form",
                        "editions": [
                            {
                                "edition_id": "direct-edition",
                                "title": "Direct edition",
                                "acquisition_ids": ["acquisition"],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    acquisition_path = (
        work_path.parent
        / "forms"
        / "direct-form"
        / "editions"
        / "direct-edition"
        / "acquisitions"
        / "acquisition.json"
    )
    acquisition_path.parent.mkdir(parents=True)
    acquisition_path.write_text("{}", encoding="utf-8")
    payload = source_path.read_bytes()
    authority_paths = {
        "work-identity": work_path,
        "acquisition": acquisition_path,
    }
    authorities = (
        {
            "name": "retained-text",
            "role": "primary-source",
            "path": "raw/source.xml",
            "bytes": len(payload),
            "sha256": _sha(payload),
        },
        {
            "name": "acquisition",
            "role": "acquisition-selection-authority",
            "path": acquisition_path.relative_to(tmp_path).as_posix(),
            "bytes": acquisition_path.stat().st_size,
            "sha256": _sha(acquisition_path.read_bytes()),
        },
        {
            "name": "work-identity",
            "role": "work-identity-config",
            "path": work_path.relative_to(tmp_path).as_posix(),
            "bytes": work_path.stat().st_size,
            "sha256": _sha(work_path.read_bytes()),
        },
    )
    source_manifest = SimpleNamespace(
        sha256="b" * 64,
        repository_root=tmp_path,
        record={"source_id": "direct-source", "work_id": "direct-work", "authorities": authorities},
        authority_path=lambda name: authority_paths[name],
    )
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    candidate = _candidate(candidate_dir, "direct-source", "source.json", "a" * 64)
    binding = {
        "review": SimpleNamespace(source_manifest=source_manifest),
        "candidate": candidate,
        "validation": SimpleNamespace(sha256="d" * 64),
        "route": {"scope": "work"},
    }
    if route_work_path is not None:
        binding["route"]["work_identity_authority"] = route_work_path
    if route_acquisition_path is not None:
        binding["route"]["acquisition_selection_authority"] = route_acquisition_path
    monkeypatch.setattr(
        "ocd_kernel.library.acquisitions.validate_acquisition",
        lambda _path, *, root: {
            "source_path": selected_source_path,
            "source_bytes": len(payload),
            "source_sha256": _sha(payload),
            "retained_files": [{"path": selected_source_path.partition("#")[0], "bytes": len(payload), "sha256": _sha(payload)}],
        },
    )

    if expected_error is not None:
        with pytest.raises(ReviewContractError, match=expected_error):
            review_contract._materialize_candidate_binding(
                candidate_work_id, binding, {}, []
            )
        return

    artifacts, _, _, _ = review_contract._materialize_candidate_binding(candidate_work_id, binding, {}, [])

    assert [artifact["authority_path"] for artifact in artifacts] == ["raw/source.xml"]


def test_candidate_binding_rejects_duplicate_primary_authority_names(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("source", encoding="utf-8")
    payload = source_path.read_bytes()
    duplicate = {
        "name": "duplicate",
        "role": "primary-source",
        "path": "source.txt",
        "bytes": len(payload),
        "sha256": _sha(payload),
    }
    source_manifest = SimpleNamespace(
        sha256="b" * 64,
        repository_root=tmp_path,
        record={"source_id": "duplicate-source", "authorities": (duplicate, duplicate)},
        authority_path=lambda name: source_path,
    )
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    candidate = _candidate(candidate_dir, "duplicate-source", "source.json", "a" * 64)
    binding = {
        "review": SimpleNamespace(source_manifest=source_manifest),
        "candidate": candidate,
        "validation": SimpleNamespace(sha256="d" * 64),
        "route": {"scope": "work"},
    }

    with pytest.raises(ReviewContractError, match="duplicate primary-source authority name"):
        review_contract._materialize_candidate_binding("duplicate-work", binding, {}, [])


@pytest.mark.parametrize("target", ["works", "roots", "nested"])
def test_catalog_version_rejects_in_memory_authority_drift(target: str) -> None:
    manifest = {"works": [{"slug": "work", "title": "Work", "creator": "Creator", "scope": "work", "stages": {"source": {"artifacts": [{"id": "before"}]}}}],
                "approved_roots": [{"id": "root", "purpose": "before"}]}
    application = ReviewApplication(manifest, {}, review_contract.DEFAULT_RENDERER_REGISTRY)
    version = application.catalog_version
    if target == "works":
        manifest["works"].append({"slug": "another"})
    elif target == "roots":
        manifest["approved_roots"][0]["purpose"] = "after"
    else:
        manifest["works"][0]["stages"]["source"]["artifacts"][0]["id"] = "after"
    with pytest.raises(review_contract.RouteStaleError, match="manifest.*changed"):
        application.catalog_summary_page(catalog_version=version)
    with pytest.raises(review_contract.RouteStaleError, match="manifest.*changed"):
        application.catalog()


@pytest.mark.parametrize("state", ["known", "uncertain"])
def test_summary_correspondence_validates_retained_mappings_before_omitting(state: str) -> None:
    source = {
        "contract": review_contract.CORRESPONDENCE_CONTRACT,
        "id": "mapped-source", "state": state,
        "left_stage": "source", "left_artifact_id": "source-id",
        "left_artifact_version": "source-version",
        "right_stage": "tei", "right_artifact_id": "tei-id",
        "right_artifact_version": "tei-version",
        "mappings": [{"left_location": "source-anchor", "right_location": "tei-anchor"}],
        "message": "Retained correspondence",
    }
    work = {"correspondence_sources": [source]}
    application = ReviewApplication({}, {}, review_contract.DEFAULT_RENDERER_REGISTRY)
    if state == "uncertain":
        with pytest.raises(ReviewContractError, match="must not contain target mappings"):
            application._correspondence_sources(work, include_mappings=False)
    else:
        result = application._correspondence_sources(work, include_mappings=False)
        assert result[0]["mappings"] == []
        assert result[0]["mapping_count"] == 1
        assert source["mappings"] == [{"left_location": "source-anchor", "right_location": "tei-anchor"}]
        work["slug"] = "mapped-work"
        application = ReviewApplication({"works": [work]}, {}, review_contract.DEFAULT_RENDERER_REGISTRY)
        page = application.correspondence_page("mapped-work", "mapped-source", offset=0, limit=1)
        assert page["mappings"] == source["mappings"]
        assert page["page"]["total"] == 1
        assert page["page"]["next_offset"] is None
        with pytest.raises(ReviewContractError, match="not declared"):
            application.correspondence_page("mapped-work", "missing")
        with pytest.raises(review_contract.RouteStaleError):
            application.correspondence_page("mapped-work", "mapped-source", catalog_version="0" * 64)


def test_bounded_catalog_and_work_discovery_keep_large_source_members_reachable() -> None:
    source_count = 58_675
    root_count = source_count
    source_artifacts = [
        {
            "id": f"source-{index}",
            "version": f"version-{index}",
            "name": f"member-{index}",
            "authority_path": f"retained/member-{index}.txt",
            "bytes": 1,
            "sha256": "a" * 64,
            "root": f"root-{index}",
            "path": f"member-{index}.txt",
            "media_type": "text/plain",
            "presentation_kind": "exact-text",
            "location_kind": "source-anchor",
            "candidate_validation_tei_artifact_id": "tei-large",
        }
        for index in range(source_count)
    ]
    tei_artifact = {
        "id": "tei-large",
        "version": "tei-version",
        "name": "content.tei.xml",
        "authority_path": "package/content.tei.xml",
        "bytes": 1,
        "sha256": "b" * 64,
        "root": "tei-root",
        "path": "content.tei.xml",
        "media_type": "application/tei+xml",
        "presentation_kind": "tei-reader",
        "location_kind": "tei-anchor",
    }

    def make_work(slug: str, *, large: bool = False) -> dict[str, object]:
        if not large:
            stages = {
                "source": {"artifacts": []},
                "tei": {"artifacts": []},
            }
            candidate_validations: list[dict[str, object]] = []
        else:
            stages = {
                "source": {
                    "selected_artifact_id": "source-0",
                    "artifacts": source_artifacts,
                },
                "tei": {
                    "selected_artifact_id": "tei-large",
                    "artifacts": [tei_artifact],
                },
            }
            candidate_validations = [{
                "status": "pass",
                "report_sha256": "c" * 64,
                "candidate_sha256": "d" * 64,
                "source_manifest_sha256": "e" * 64,
                "source_id": "large-source",
                "source_artifact_ids": [
                    f"source-{index}" for index in range(source_count)
                ],
                "tei_artifact_id": "tei-large",
            }]
        return {
            "slug": slug,
            "title": slug,
            "creator": "Creator",
            "scope": "work",
            "candidate_validation": None,
            "default_compare": None,
            "correspondence_sources": [],
            "stages": stages,
            "candidate_validations": candidate_validations,
        }

    manifest = {
        "contract": review_contract.MANIFEST_CONTRACT,
        "approved_roots": [
            {
                "id": f"root-{index}",
                "access": "read-only",
                "purpose": "retained source",
            }
            for index in range(root_count)
        ],
        "works": [
            *[make_work(f"work-{index}") for index in range(401)],
            make_work("church-fathers-quotations", large=True),
        ],
    }
    application = ReviewApplication(
        manifest,
        {},
        review_contract.DEFAULT_RENDERER_REGISTRY,
    )

    summary = application.catalog_summary_page(offset=0, limit=50)
    assert summary["page"] == {
        "offset": 0,
        "returned": 50,
        "total": 402,
        "next_offset": 50,
        "catalog_version": application.catalog_version,
    }
    assert summary["approved_roots"] == []
    assert summary["approved_roots_count"] == root_count

    target_summary = application.catalog_summary_page(offset=401, limit=1)
    target_stage = target_summary["works"][0]["stages"][0]
    assert target_stage["artifacts"] == []
    assert target_stage["outline"] == []
    assert target_stage["selected_artifact"] == {
        "id": "source-0",
        "version": "version-0",
    }
    validation = target_summary["works"][0]["candidate_validations"][0]
    assert validation["source_artifact_ids"] == []
    assert validation["source_artifact_count"] == source_count

    detail = application.work_detail(
        "church-fathers-quotations",
        source_artifact="source-58674",
        source_version="version-58674",
    )
    assert review_contract.serialized_payload_size(detail) <= 512_000
    detail_stage = detail["work"]["stages"][0]
    detail_ids = {item["id"] for item in detail_stage["artifacts"]}
    assert {"source-0", "source-58674"} <= detail_ids
    assert detail_stage["artifact_discovery"] == {
        "total": source_count,
        "returned": len(detail_stage["artifacts"]),
        "complete": False,
    }
    assert detail["work"]["candidate_validations"][0]["source_artifact_ids"] == []
    assert detail["work"]["candidate_validations"][0]["source_artifact_count"] == source_count

    late_page = application.artifact_page(
        "church-fathers-quotations",
        "source",
        offset=0,
        limit=1,
        search="58674",
    )
    assert late_page["matched"] == 1
    assert late_page["total"] == source_count
    assert late_page["artifacts"][0]["id"] == "source-58674"

    with pytest.raises(review_contract.RouteStaleError):
        application.catalog_summary_page(catalog_version="0" * 64)
    with pytest.raises(ReviewContractError, match="current declared artifact"):
        application.work_detail(
            "church-fathers-quotations",
            source_artifact="source-58674",
            source_version="drifted-version",
        )


def test_agent_links_do_not_render_and_text_compare_preserves_identity(evidence_pair, monkeypatch):
    app, selection, _ = evidence_pair()
    original = app._resolve
    monkeypatch.setattr(app, "_resolve", lambda *a, **k: pytest.fail("discovery must not parse"))
    summary = app.catalog_summary_page(limit=1)["works"][0]
    links = summary["agent_links"]
    assert "representation=text" in links["compare_text"]
    assert "left_version=" + selection["left_recorded"].version in links["compare_text"]
    assert "linked=false" in links["compare_text"]
    assert "expected_version=" in links["source_locations"]
    assert app.work_detail("brief-example")["work"]["agent_links"] == links
    monkeypatch.setattr(app, "_resolve", original)
    full = app.compare_view("brief-example", **selection, auto_page=True)
    text = app.compare_view("brief-example", **selection, auto_page=True, text_only=True)
    assert text["contract"] == "ocd-corpus-review-text-compare-v1"
    assert text["left"]["text"] == "Faithful source text."
    assert text["right"]["text"] == "Faithful candidate text."
    assert text["route_digest"] == full["route_digest"]
    assert "document" not in text["left"]
    assert text["artifacts"]["left"]["sha256"] == full["left"]["artifact"]["sha256"]
    selection["left_recorded"] = RecordedContext("wrong", "wrong", "start")
    refused = app.compare_view("brief-example", **selection, text_only=True)
    assert refused["left"]["text"] is None
    assert refused["left"]["warnings"]
    selection["left_recorded"] = RecordedContext(
        full["left"]["artifact"]["id"], full["left"]["artifact"]["version"], "missing"
    )
    missing = app.compare_view("brief-example", **selection, text_only=True)
    assert missing["left"]["text"] is None
    assert missing["left"]["recorded_context"]["state"] == "location-missing"
    unselected = [{**stage, "selected_artifact": None} for stage in summary["stages"]]
    assert "compare_text" not in app._agent_links("brief-example", unselected)


def test_agent_text_http_paging_and_errors(evidence_pair, tmp_path):
    app, selection, _ = evidence_pair(source_bytes=(b"<p>" + b"Readable word. " * 5000 + b"</p>"))
    static = tmp_path / "dist"; static.mkdir()
    server = review_service.ReviewHTTPServer(("127.0.0.1", 0), app, static)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(origin + "/api/review/v1/works?view=summary&limit=1") as response:
            work = json.load(response)["works"][0]
        route = work["agent_links"]["compare_text"]
        with urlopen(origin + route) as response:
            first = json.load(response)
            assert response.headers["X-CVW-Request-ID"]
        assert first["left"]["text"]
        assert first["left"]["next"]
        with urlopen(origin + first["left"]["next"]) as response:
            second = json.load(response)
        assert second["left"]["paging"]["segments"][0]["index"] == 1
        assert second["left"]["text"]
        assert second["artifacts"] == first["artifacts"]
        with pytest.raises(HTTPError) as error:
            urlopen(origin + route + "&route_digest=" + "0" * 64)
        assert json.load(error.value)["error"]["code"] == "route-stale"
        with pytest.raises(HTTPError) as error:
            urlopen(origin + route + "&left_segment_start=99999&left_segment_limit=1")
        assert json.load(error.value)["error"]["code"] == "range-invalid"
    finally:
        server.shutdown(); server.server_close(); thread.join()
