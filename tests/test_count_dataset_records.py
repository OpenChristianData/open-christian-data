import hashlib
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.live_work_catalog_fixture import _live_work_catalog_record, live_work_catalog


def _write_resource(
    path: Path,
    *,
    resource_id: str,
    title: str | None,
    author: str | None,
    schema_type: str,
    data,
    provenance: dict | None = None,
    extra_meta: dict | None = None,
) -> None:
    meta = {
        "id": resource_id,
        "author": author,
        "schema_type": schema_type,
        "license": "public-domain",
        "provenance": provenance or {},
    }
    if extra_meta is not None:
        meta.update(extra_meta)
    if title is not None:
        meta["title"] = title
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"meta": meta, "data": data}, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_source_manifest(
    repo_root: Path,
    manifest_relative_path: str,
    *,
    source_id: str,
    config_ids: tuple[tuple[str, str], ...] = (),
    config_payloads: dict[str, dict[str, object]] | None = None,
    partial: bool = False,
    mutate=None,
) -> tuple[Path, str]:
    stem = Path(manifest_relative_path).name.removesuffix(".source-manifest.json")

    def write_member(relative_path: str, content: bytes) -> dict[str, object]:
        path = repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return {
            "path": relative_path,
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    primary = write_member(f"raw/{stem}.txt", b"retained source bytes\n")
    converter = write_member(
        f"build/tei/{stem}_reconstruction.py", b"def _convert():\n    pass\n"
    )
    validator = write_member(
        f"build/tei/{stem}_oracle.py", b"def _oracle():\n    pass\n"
    )
    schema = write_member(f"schemas/{stem}.candidate-package.schema.json", b"{}\n")
    authorities = [{"name": "primary", "role": "primary-source", **primary}]
    for index, (config_path, resource_id) in enumerate(config_ids, start=1):
        config_payload = (config_payloads or {}).get(
            config_path,
            {"resource_id": resource_id},
        )
        config = write_member(
            config_path,
            (json.dumps(config_payload, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
        )
        authorities.append(
            {"name": f"config-{index}", "role": "source-config", **config}
        )
    manifest = {
        "contract": "ocd-source-manifest-v1",
        "source_id": source_id,
        "authorities": authorities,
        "converter": {
            "callable": "_convert",
            "implementation_path": converter["path"],
            "implementation_sha256": converter["sha256"],
        },
        "validator": {
            "callable": "_oracle",
            "implementation_path": validator["path"],
            "implementation_sha256": validator["sha256"],
            "import_closure_sha256": "0" * 64,
        },
        "package_schema": {"path": schema["path"], "sha256": schema["sha256"]},
    }
    if partial:
        manifest["expression_scope"] = {"status": "partial"}
    if mutate is not None:
        mutate(manifest)
    manifest_path = repo_root / manifest_relative_path
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path, str(primary["sha256"])


def _write_runtime_source_manifest(
    repo_root: Path,
    manifest_relative_path: str,
    *,
    source_id: str,
    title: str,
    author: str,
    date: str,
    policy_identity: dict | None = None,
    work_id: str | None = None,
    identity_resolution_path: str | None = None,
    identity_resolution: dict | None = None,
) -> Path:
    manifest_path, primary_sha256 = _write_source_manifest(
        repo_root, manifest_relative_path, source_id=source_id
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    identity = {
        "title": title,
        "author": author,
        "date": date,
    }
    if policy_identity is not None:
        identity.update(policy_identity)
    policy = {
        "contract": "test-runtime-validation-policy-v1",
        "provenance": {
            "identity": identity,
            "source": {"bytes": len(b"retained source bytes\n"), "sha256": primary_sha256},
        },
    }
    policy_path = manifest_path.with_name("runtime.validation-policy.json")
    policy_bytes = (json.dumps(policy, sort_keys=True) + "\n").encode("utf-8")
    policy_path.write_bytes(policy_bytes)
    manifest["authorities"].append(
        {
            "name": "runtime-policy",
            "path": policy_path.relative_to(repo_root).as_posix(),
            "role": "independent-validation-policy",
            "bytes": len(policy_bytes),
            "sha256": hashlib.sha256(policy_bytes).hexdigest(),
        }
    )
    if work_id is not None:
        manifest["work_id"] = work_id
    if identity_resolution_path is not None:
        if identity_resolution is None:
            raise AssertionError("identity resolution content is required")
        resolution_path = repo_root / identity_resolution_path
        resolution_path.parent.mkdir(parents=True, exist_ok=True)
        resolution_bytes = (json.dumps(identity_resolution, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        resolution_path.write_bytes(resolution_bytes)
        manifest["authorities"].append(
            {
                "name": "runtime-identity-resolution",
                "path": resolution_path.relative_to(repo_root).as_posix(),
                "role": "source-identity-resolution-evidence",
                "bytes": len(resolution_bytes),
                "sha256": hashlib.sha256(resolution_bytes).hexdigest(),
            }
        )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def test_title_level_work_catalog_groups_reference_volumes(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "reference" / "ce-vol01.json",
        resource_id="catholic-encyclopedia-vol01",
        title="The Catholic Encyclopedia",
        author="Various contributors",
        schema_type="reference_entry",
        data=[{"id": "a"}, {"id": "b"}],
        provenance={"source_edition": "Volume 1"},
    )
    _write_resource(
        data_root / "reference" / "ce-vol02.json",
        resource_id="catholic-encyclopedia-vol02",
        title="The Catholic Encyclopedia",
        author="Various contributors",
        schema_type="reference_entry",
        data=[{"id": "c"}],
        provenance={"source_edition": "Volume 2"},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(data_root)

    assert catalog.summary["work_units"] == 1
    work = catalog.works[0]
    assert work["title"] == "The Catholic Encyclopedia"
    assert work["file_count"] == 2
    assert work["top_level_records"] == 3
    assert work["metadata_fields"]["provenance.source_edition"] == [
        "Volume 1",
        "Volume 2",
    ]


def test_distinct_author_led_works_with_shared_resource_id_get_unique_work_ids(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    for author, filename in (("W.H. Bennett", "jer.json"), ("Marcus Dods", "gen.json")):
        _write_resource(
            data_root / "commentaries" / "expositors-bible" / filename,
            resource_id="expositors-bible",
            title="The Expositor's Bible",
            author=author,
            schema_type="commentary",
            data=[],
        )

    from build.tools.count_dataset_records import collect_work_catalog

    works = collect_work_catalog(data_root).works

    assert {work["work_id"] for work in works} == {
        "expositors-bible--marcus-dods",
        "expositors-bible--w-h-bennett",
    }


def test_catalog_identity_snapshot_is_compact_authoritative_and_deterministic(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "work.json",
        resource_id="work",
        title="A Work",
        author="An Author",
        schema_type="structured_text",
        data={"sections": []},
    )
    from build.tools.count_dataset_records import (
        catalog_identity_snapshot,
        collect_work_catalog,
        serialize_catalog_identity,
    )

    catalog = collect_work_catalog(data_root)
    snapshot = catalog_identity_snapshot(catalog)

    assert snapshot == {
        "identity": "work-catalog-identity-v1",
        "works": [
            {
                "author": "An Author",
                "category": "structured-text",
                "category_label": "Books and Long-Form Works",
                "file_count": 1,
                "resource_ids": ["work"],
                "schema_types": ["structured_text"],
                "source_paths": ["structured-text/work.json"],
                "title": "A Work",
                "work_id": "work",
            }
        ],
    }
    assert serialize_catalog_identity(catalog) == serialize_catalog_identity(
        collect_work_catalog(data_root)
    )
    assert b"methodology" not in serialize_catalog_identity(catalog)


def test_work_catalog_records_default_to_unassessed_reconstruction_state(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "work.json",
        resource_id="work",
        title="A Work",
        author="An Author",
        schema_type="structured_text",
        data={"sections": []},
    )

    from build.tools.count_dataset_records import (
        collect_work_catalog,
        render_catalog_html,
        render_catalog_markdown,
    )

    catalog = collect_work_catalog(data_root)
    work = catalog.works[0]

    assert work["reconstruction_state"] == {
        "retained_source": "not_assessed",
        "tei_candidate": "not_started",
        "validation": "not_run",
        "human_review": "not_started",
        "accepted_ir": "not_accepted",
        "blocker": None,
        "publication": "not_ready",
        "routes": [],
    }
    assert catalog.summary["reconstruction_state_counts"] == {
        "accepted_ir": {"not_accepted": 1},
        "blockers": {},
        "human_review": {"not_started": 1},
        "manifest_verification": {},
        "partial_routes": 0,
        "publication": {"not_ready": 1},
        "retained_source": {"not_assessed": 1},
        "route_verification": {},
        "routes": 0,
        "tei_candidate": {"not_started": 1},
        "unassociated_manifests": {},
        "validation": {"not_run": 1},
    }
    markdown = render_catalog_markdown(catalog)
    html = render_catalog_html(catalog)
    assert "| Reconstruction |" in markdown
    assert "retained source: not assessed" in markdown
    assert "<th>Reconstruction</th>" in html
    assert "retained source: not assessed" in html


@pytest.mark.parametrize(
    "mutation",
    [
        "unsupported_contract",
        "empty_converter",
        "nonexistent_validator",
        "invalid_digest",
        "missing_authority",
    ],
)
def test_unverified_source_manifest_indexes_a_blocked_route_without_claiming_availability(
    tmp_path: Path,
    mutation: str,
) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "work.json",
        resource_id="work",
        title="Work",
        author="Author",
        schema_type="structured_text",
        data={"sections": []},
    )

    def mutate(manifest: dict) -> None:
        if mutation == "unsupported_contract":
            manifest["contract"] = "ocd-source-manifest-v2"
        elif mutation == "empty_converter":
            manifest["converter"] = {}
        elif mutation == "nonexistent_validator":
            manifest["validator"]["implementation_path"] = "build/tei/missing.py"
        elif mutation == "invalid_digest":
            manifest["converter"]["implementation_sha256"] = "not-a-digest"
        elif mutation == "missing_authority":
            manifest["authorities"][0]["path"] = "raw/missing.txt"

    _write_source_manifest(
        tmp_path,
        "sources/work/work.source-manifest.json",
        source_id="work-retained",
        mutate=mutate,
    )

    from build.tools.count_dataset_records import collect_work_catalog

    state = collect_work_catalog(data_root).works[0]["reconstruction_state"]
    route = dict(state["routes"][0])
    assert route.pop("blocker")
    state_without_blocker = {**state, "routes": [route]}
    assert state_without_blocker.pop("blocker")

    assert state_without_blocker == {
        "retained_source": "manifest_unverified",
        "tei_candidate": "blocked",
        "validation": "blocked",
        "human_review": "blocked",
        "accepted_ir": "not_accepted",
        "publication": "not_ready",
        "routes": [
            {
                "association": "slug",
                "manifest": "sources/work/work.source-manifest.json",
                "scope": "work",
                "source_id": "work-retained",
                "verification": "blocked",
            }
        ],
    }


def test_missing_referenced_config_uses_remaining_hash_evidence_and_blocks_route(
    tmp_path: Path,
) -> None:
    def remove_config(manifest: dict) -> None:
        manifest["authorities"][1]["path"] = "sources/work/missing/config.json"

    _, primary_hash = _write_source_manifest(
        tmp_path,
        "sources/work/work.source-manifest.json",
        source_id="work-retained",
        config_ids=(("sources/work/config.json", "work"),),
        mutate=remove_config,
    )
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "work.json",
        resource_id="work",
        title="Work",
        author="Author",
        schema_type="structured_text",
        data={"sections": []},
        provenance={"source_hash": f"sha256:{primary_hash}"},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    state = collect_work_catalog(data_root).works[0]["reconstruction_state"]

    assert state["retained_source"] == "manifest_unverified"
    assert state["tei_candidate"] == "blocked"
    assert state["accepted_ir"] == "not_accepted"
    assert state["blocker"] == "manifest dependency unavailable"
    assert state["routes"] == [
        {
            "association": "source_hash",
            "blocker": "manifest dependency unavailable",
            "manifest": "sources/work/work.source-manifest.json",
            "scope": "work",
            "source_id": "work-retained",
            "verification": "blocked",
        }
    ]


@pytest.mark.parametrize(
    ("content", "blocker"),
    [
        (b"{", "source manifest is not valid JSON"),
        (b"[]", "source manifest must be a JSON object"),
        (b"\xff", "source manifest is not UTF-8 JSON"),
    ],
)
def test_unreadable_manifest_slug_indexes_a_blocked_route(
    tmp_path: Path,
    content: bytes,
    blocker: str,
) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "work.json",
        resource_id="work",
        title="Work",
        author="Author",
        schema_type="structured_text",
        data={"sections": []},
    )
    manifest_path = tmp_path / "sources" / "work" / "work.source-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(content)

    from build.tools.count_dataset_records import collect_work_catalog

    route = collect_work_catalog(data_root).works[0]["reconstruction_state"]["routes"][
        0
    ]

    assert route == {
        "association": "slug",
        "blocker": blocker,
        "manifest": "sources/work/work.source-manifest.json",
        "scope": "work",
        "source_id": "work",
        "verification": "blocked",
    }


@pytest.mark.parametrize("manifest_filename", ["orphan.source-manifest.json", "source-manifest.json"])
def test_unassociated_unreadable_manifest_is_counted_in_summary(
    tmp_path: Path,
    manifest_filename: str,
) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "work.json",
        resource_id="work",
        title="Work",
        author="Author",
        schema_type="structured_text",
        data={"sections": []},
    )
    manifest_path = tmp_path / "sources" / "orphan" / manifest_filename
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(b"{")

    from build.tools.count_dataset_records import (
        collect_work_catalog,
        render_catalog_html,
        render_catalog_markdown,
    )

    catalog = collect_work_catalog(data_root)

    assert catalog.works[0]["reconstruction_state"]["retained_source"] == "not_assessed"
    assert catalog.summary["reconstruction_state_counts"]["unassociated_manifests"] == {
        "blocked": 1
    }
    assert "Unassociated reconstruction manifests: 1" in render_catalog_markdown(
        catalog
    )
    assert (
        "Unassociated reconstruction manifests: <strong>1</strong>"
        in render_catalog_html(catalog)
    )


@pytest.mark.parametrize(
    "selected_relative_path",
    (
        "sources/structured-text/family.source-manifest.json",
        "sources/structured-text/lib072-gutenberg-evangelical/work-bindings/"
        "wilberforce-practical-view/37c-322-v3-scope-v1-source-manifest.json",
    ),
)
def test_source_manifest_allowlist_binds_only_target_work_without_unselected_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selected_relative_path: str,
) -> None:
    data_root = tmp_path / "data"
    selected_manifest, primary_hash = _write_source_manifest(
        tmp_path,
        selected_relative_path,
        source_id="selected-work",
        config_ids=(
            ("sources/structured-text/work/config.json", "work"),
            ("sources/structured-text/sibling/config.json", "sibling"),
        ),
        config_payloads={
            "sources/structured-text/work/config.json": {
                "resource_id": "work",
                "source_dir": "raw",
            },
            "sources/structured-text/sibling/config.json": {
                "resource_id": "sibling",
                "source_dir": "raw/ocr",
            },
        },
    )
    unselected_manifest, _ = _write_source_manifest(
        tmp_path,
        "sources/ocr/unselected/unselected.source-manifest.json",
        source_id="unselected-ocr",
        config_ids=(("sources/ocr/unselected/config.json", "unselected-ocr"),),
        config_payloads={
            "sources/ocr/unselected/config.json": {
                "resource_id": "unselected-ocr",
                "source_file": "raw/ocr/unselected-body.xml",
            },
        },
    )
    unselected_config = tmp_path / "sources/ocr/unselected/config.json"
    unselected_body = tmp_path / "raw/ocr/unselected-body.xml"
    unselected_body.parent.mkdir(parents=True, exist_ok=True)
    unselected_body.write_bytes(b"unselected OCR body sentinel\n")
    selected_data_paths = {
        (data_root / "structured-text" / "work.json").resolve(),
        (data_root / "structured-text" / "sibling.json").resolve(),
    }
    for resource_id, title in (("work", "Work"), ("sibling", "Sibling")):
        _write_resource(
            data_root / "structured-text" / f"{resource_id}.json",
            resource_id=resource_id,
            title=title,
            author="Author",
            schema_type="structured_text",
            data={"sections": []},
            provenance={"source_hash": f"sha256:{primary_hash}"},
        )
    unselected_data_record = data_root / "ocr" / "unselected-record.json"
    unselected_data_record.parent.mkdir(parents=True, exist_ok=True)
    unselected_data_record.write_text(
        json.dumps(
            {
                "meta": {"id": "unselected-ocr", "title": "OCR sentinel"},
                "data": {"text": "unselected OCR body sentinel"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    from build.tools import count_dataset_records
    from ocd_kernel.reconstruction.contract import SourceManifest

    loaded_manifests: list[Path] = []
    original_load = SourceManifest.load

    def record_manifest_load(
        cls,
        path: str | Path,
        *,
        repository_root: str | Path,
    ) -> SourceManifest:
        loaded_manifests.append(Path(path).resolve())
        return original_load(path, repository_root=repository_root)

    monkeypatch.setattr(
        SourceManifest,
        "load",
        classmethod(record_manifest_load),
    )
    def skip_candidate_validation_for_route_scope_test(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(
        count_dataset_records,
        "_apply_candidate_validation_evidence",
        skip_candidate_validation_for_route_scope_test,
    )
    ocr_body_bytes = b"unselected OCR body sentinel\n"
    original_sha256 = count_dataset_records.hashlib.sha256

    def reject_ocr_body_hash(data: bytes = b""):
        if data == ocr_body_bytes:
            pytest.fail("unselected OCR body was hashed")
        return original_sha256(data)

    monkeypatch.setattr(count_dataset_records.hashlib, "sha256", reject_ocr_body_hash)
    original_read_text = Path.read_text
    selected_data_reads: set[Path] = set()

    def guard_unselected_read(path: Path, *args, **kwargs) -> str:
        resolved = path.resolve()
        if resolved == unselected_config.resolve():
            pytest.fail("unselected source config was read")
        if resolved == unselected_data_record.resolve():
            pytest.fail("unselected OCR-derived data record was read")
        if resolved in selected_data_paths:
            selected_data_reads.add(resolved)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guard_unselected_read)
    original_read_bytes = Path.read_bytes

    def reject_ocr_body_read(path: Path) -> bytes:
        if path.resolve() == unselected_body.resolve():
            pytest.fail("unselected OCR body was read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_ocr_body_read)
    sources_root = (tmp_path / "sources").resolve()
    original_rglob = Path.rglob

    def reject_unscoped_source_walk(path: Path, pattern: str):
        if path.resolve() == sources_root and pattern in {
            "*.source-manifest.json",
            "source-manifest.json",
            "config.json",
        }:
            pytest.fail("allowlisted route binding enumerated unselected sources")
        return original_rglob(path, pattern)

    monkeypatch.setattr(Path, "rglob", reject_unscoped_source_walk)
    monkeypatch.setattr(
        count_dataset_records,
        "_resource_paths",
        lambda _root: pytest.fail("allowlisted route binding enumerated data resources"),
    )
    monkeypatch.setattr(
        count_dataset_records,
        "_raw_git_witnesses",
        lambda _root: pytest.fail("scoped route binding scanned raw Git witnesses"),
    )
    monkeypatch.setattr(
        count_dataset_records,
        "_inventory_witnesses",
        lambda _root: pytest.fail("scoped route binding scanned inventory witnesses"),
    )

    catalog = count_dataset_records.collect_work_catalog(
        data_root,
        source_manifest_allowlist=[selected_relative_path],
        data_resource_allowlist=[
            "data/structured-text/work.json",
            "data/structured-text/sibling.json",
        ],
        reconstruction_evidence={
            ("selected-work", "work"): (
                tmp_path / "candidate",
                tmp_path / "validation.json",
            ),
        },
    )

    assert loaded_manifests == [selected_manifest.resolve()]
    assert selected_data_reads == selected_data_paths
    works_by_id = {work["work_id"]: work for work in catalog.works}
    route = works_by_id["work"]["reconstruction_state"]["routes"][0]
    assert route["manifest"] == selected_relative_path
    assert route["source_id"] == "selected-work"
    assert route["association"] == "source_hash+exact_id"
    assert route["verification"] == "verified"
    assert works_by_id["sibling"]["reconstruction_state"]["routes"] == []
    assert works_by_id["sibling"]["retained_witness_gaps"] == []
    assert unselected_manifest.exists()


@pytest.mark.parametrize(
    ("selection", "error_match"),
    [
        ("sources/../outside.source-manifest.json", "normalized repository-relative"),
        ("sibling/outside.source-manifest.json", "under sources/"),
        ("sources/work/config.json", "does not name a source manifest"),
        ("sources/work/missing.source-manifest.json", "is unavailable"),
    ],
)
def test_source_manifest_allowlist_rejects_invalid_paths_before_data_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selection: str,
    error_match: str,
) -> None:
    data_root = tmp_path / "data"
    sources_root = tmp_path / "sources"
    (sources_root / "work").mkdir(parents=True)
    (sources_root / "work" / "config.json").write_text("{}\n", encoding="utf-8")
    data_resource_path = "data/structured-text/work.json"
    data_record = tmp_path / data_resource_path
    data_record.parent.mkdir(parents=True)
    data_record.write_text("{}\n", encoding="utf-8")

    from build.tools import count_dataset_records

    def reject_data_scan(_data_root: Path):
        pytest.fail("invalid source manifest allowlist reached the WorkCatalog data scan")

    monkeypatch.setattr(count_dataset_records, "_resource_paths", reject_data_scan)

    with pytest.raises(ValueError, match=error_match):
        count_dataset_records.collect_work_catalog(
            data_root,
            source_manifest_allowlist=[selection],
            data_resource_allowlist=[data_resource_path],
        )


def test_source_manifest_allowlist_rejects_absolute_and_duplicate_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    data_resource_path = "data/structured-text/work.json"
    data_record = tmp_path / data_resource_path
    data_record.parent.mkdir(parents=True)
    data_record.write_text("{}\n", encoding="utf-8")
    manifest_relative_path = "sources/work/work.source-manifest.json"
    manifest_path, _ = _write_source_manifest(
        tmp_path,
        manifest_relative_path,
        source_id="work",
    )

    from build.tools import count_dataset_records

    def reject_data_scan(_data_root: Path):
        pytest.fail("invalid source manifest allowlist reached the WorkCatalog data scan")

    monkeypatch.setattr(count_dataset_records, "_resource_paths", reject_data_scan)
    for selections, error_match in (
        ([str(manifest_path.resolve())], "repository-relative paths under sources/"),
        (
            [manifest_relative_path, manifest_relative_path],
            "contains a duplicate path",
        ),
    ):
        with pytest.raises(ValueError, match=error_match):
            count_dataset_records.collect_work_catalog(
                data_root,
                source_manifest_allowlist=selections,
                data_resource_allowlist=[data_resource_path],
            )

    with pytest.raises(ValueError, match="must include at least one path"):
        count_dataset_records.collect_work_catalog(
            data_root,
            source_manifest_allowlist=[],
            data_resource_allowlist=[data_resource_path],
        )
    for selections, error_match in (
        ([str(data_record.resolve())], "normalized repository-relative paths"),
        ([data_resource_path, data_resource_path], "contains a duplicate path"),
    ):
        with pytest.raises(ValueError, match=error_match):
            count_dataset_records.collect_work_catalog(
                data_root,
                source_manifest_allowlist=[manifest_relative_path],
                data_resource_allowlist=selections,
            )
    with pytest.raises(ValueError, match="must include at least one path"):
        count_dataset_records.collect_work_catalog(
            data_root,
            source_manifest_allowlist=[manifest_relative_path],
            data_resource_allowlist=[],
        )


@pytest.mark.parametrize(
    ("selection", "error_match"),
    [
        ("data/../outside.json", "normalized repository-relative"),
        ("sources/work/work.source-manifest.json", "under data/"),
        ("data/structured-text/missing.json", "is unavailable"),
        ("data/structured-text/_excluded.json", "excluded from the WorkCatalog"),
    ],
)
def test_data_resource_allowlist_rejects_invalid_paths_before_data_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selection: str,
    error_match: str,
) -> None:
    data_root = tmp_path / "data"
    structured_text = data_root / "structured-text"
    structured_text.mkdir(parents=True)
    (structured_text / "_excluded.json").write_text("{}\n", encoding="utf-8")
    sources_root = tmp_path / "sources" / "work"
    sources_root.mkdir(parents=True)

    from build.tools import count_dataset_records

    def reject_data_scan(_data_root: Path):
        pytest.fail("invalid data resource allowlist reached the WorkCatalog data scan")

    monkeypatch.setattr(count_dataset_records, "_resource_paths", reject_data_scan)

    with pytest.raises(ValueError, match=error_match):
        count_dataset_records.collect_work_catalog(
            data_root,
            source_manifest_allowlist=["sources/work/work.source-manifest.json"],
            data_resource_allowlist=[selection],
        )


def test_bounded_route_allowlists_must_be_supplied_together(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    from build.tools import count_dataset_records

    with pytest.raises(ValueError, match="requires both source manifest and data resource"):
        count_dataset_records.collect_work_catalog(
            data_root,
            source_manifest_allowlist=["sources/work/work.source-manifest.json"],
        )
    with pytest.raises(ValueError, match="requires both source manifest and data resource"):
        count_dataset_records.collect_work_catalog(
            data_root,
            data_resource_allowlist=["data/structured-text/work.json"],
        )


def test_historical_catalog_cli_forwards_repeatable_route_allowlists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from build.tools import count_dataset_records

    repository_root = tmp_path / "repository"
    data_root = repository_root / "data"
    source_paths = [
        "sources/structured-text/first.source-manifest.json",
        "sources/structured-text/second/source-manifest.json",
    ]
    data_paths = [
        "data/structured-text/first.json",
        "data/structured-text/second.json",
    ]
    for relative in (*source_paths, *data_paths):
        path = repository_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    calls = []

    def collect(data_path, **kwargs):
        calls.append((data_path, kwargs))
        return SimpleNamespace(summary={"works": 1})

    monkeypatch.setattr(count_dataset_records, "collect_work_catalog", collect)
    result = count_dataset_records.main(
        [
            "--legacy-catalog",
            "--data-root",
            str(data_root),
            "--source-manifest-allowlist",
            source_paths[0],
            "--source-manifest-allowlist",
            source_paths[1],
            "--data-resource-allowlist",
            data_paths[0],
            "--data-resource-allowlist",
            data_paths[1],
            "--no-write",
        ]
    )

    assert result == 0
    assert len(calls) == 1
    assert calls[0][0] == data_root
    assert calls[0][1]["source_manifest_allowlist"] == source_paths
    assert calls[0][1]["data_resource_allowlist"] == data_paths
    assert json.loads(capsys.readouterr().out) == {"works": 1}

@pytest.mark.parametrize("manifest_filename", ["mark.source-manifest.json", "source-manifest.json"])
def test_source_hash_binds_a_partial_reconstruction_route_to_the_exact_work(
    tmp_path: Path,
    manifest_filename: str,
) -> None:
    data_root = tmp_path / "data"
    manifest_relative_path = f"sources/commentaries/expositors-bible/{manifest_filename}"
    _, mark_hash = _write_source_manifest(
        tmp_path,
        manifest_relative_path,
        source_id="ccel-chadwick-mark-whole-thml",
    )
    for filename, source_hash in (("exod.json", "f" * 64), ("mark.json", mark_hash)):
        _write_resource(
            data_root / "commentaries" / "expositors-bible" / filename,
            resource_id="expositors-bible",
            title="The Expositor's Bible",
            author="G.A. Chadwick",
            schema_type="commentary",
            data=[],
            provenance={"source_hash": f"sha256:{source_hash}"},
        )

    from build.tools.count_dataset_records import (
        collect_work_catalog,
        render_catalog_html,
        render_catalog_markdown,
        serialize_catalog_identity,
    )

    catalog = collect_work_catalog(data_root)
    work = catalog.works[0]

    assert work["reconstruction_state"] == {
        "retained_source": "manifest_bound_partial",
        "tei_candidate": "route_available_partial",
        "validation": "validator_available_partial",
        "human_review": "required",
        "accepted_ir": "not_accepted",
        "blocker": "partial source coverage cannot establish whole-work accepted IR",
        "publication": "not_ready",
        "routes": [
            {
                "association": "source_hash",
                "manifest": manifest_relative_path,
                "scope": "partial",
                "source_id": "ccel-chadwick-mark-whole-thml",
                "verification": "verified",
            }
        ],
    }
    repeated = collect_work_catalog(data_root)
    assert catalog.to_dict() == repeated.to_dict()
    assert serialize_catalog_identity(catalog) == serialize_catalog_identity(repeated)
    assert render_catalog_markdown(catalog) == render_catalog_markdown(repeated)
    assert render_catalog_html(catalog) == render_catalog_html(repeated)


def test_exact_config_ids_without_hashes_only_bind_blocked_partial_routes(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    for category, resource_id, title in (
        ("structured-text", "bcp-1662", "The Book of Common Prayer (1662)"),
        ("prayers", "bcp-1662-collects", "Book of Common Prayer (1662) -- Collects"),
    ):
        _write_resource(
            data_root / category / f"{resource_id}.json",
            resource_id=resource_id,
            title=title,
            author="Church of England",
            schema_type="structured_text",
            data={"sections": []},
        )
    _write_source_manifest(
        tmp_path,
        "sources/structured-text/bcp-1662/bcp-1662.source-manifest.json",
        source_id="bcp-1662-retained-partial-html",
        config_ids=(
            ("sources/structured-text/bcp-1662/config.json", "bcp-1662"),
            ("sources/prayers/bcp-1662-collects/config.json", "bcp-1662-collects"),
        ),
        partial=True,
    )

    from build.tools.count_dataset_records import collect_work_catalog

    works = collect_work_catalog(data_root).works

    assert {work["work_id"] for work in works} == {"bcp-1662", "bcp-1662-collects"}
    for work in works:
        assert work["reconstruction_state"]["retained_source"] == "manifest_unverified"
        assert work["reconstruction_state"]["tei_candidate"] == "blocked"
        assert work["reconstruction_state"]["validation"] == "blocked"
        assert work["reconstruction_state"]["human_review"] == "blocked"
        assert work["reconstruction_state"]["accepted_ir"] == "not_accepted"
        assert work["reconstruction_state"]["blocker"] == (
            "exact source hash participation is required for a fully verified route"
        )
        assert work["reconstruction_state"]["publication"] == "not_ready"
        assert work["reconstruction_state"]["routes"] == [
            {
                "association": "exact_id",
                "blocker": "exact source hash participation is required for a fully verified route",
                "manifest": "sources/structured-text/bcp-1662/bcp-1662.source-manifest.json",
                "manifest_verification": "verified",
                "scope": "partial",
                "source_id": "bcp-1662-retained-partial-html",
                "verification": "blocked",
            }
        ]


@pytest.mark.parametrize("with_candidate_evidence", [False, True])
def test_catalog_claim_lineage_binds_legacy_hashes_to_exact_retained_manifest(
    tmp_path: Path, with_candidate_evidence: bool,
) -> None:
    data_root = tmp_path / "data"
    legacy_hashes = ("a" * 64, "b" * 64)
    source_paths = (
        "structured-text/legacy-work-a.json",
        "structured-text/legacy-work-b.json",
    )
    for source_path, source_hash in zip(source_paths, legacy_hashes, strict=True):
        _write_resource(
            data_root / source_path,
            resource_id="legacy-work",
            title="Legacy Work",
            author="Author",
            schema_type="structured_text",
            data={"sections": []},
            provenance={"source_hash": f"sha256:{source_hash}"},
        )

    retained_hash = hashlib.sha256(b"retained source bytes\n").hexdigest()

    def add_lineage(manifest: dict) -> None:
        manifest["work_id"] = "legacy-work"
        manifest["catalog_claim_lineage"] = {
            "contract": "ocd-catalog-claim-lineage-v1",
            "work_id": "legacy-work",
            "retained_source_sha256": retained_hash,
            "claim_count": 2,
            "claims": [
                {
                    "source_path": source_path,
                    "legacy_source_sha256": source_hash,
                }
                for source_path, source_hash in zip(
                    source_paths, legacy_hashes, strict=True
                )
            ],
        }

    _write_source_manifest(
        tmp_path,
        "sources/legacy/legacy.source-manifest.json",
        source_id="legacy-retained",
        config_ids=(("sources/legacy/config.json", "legacy-work"),),
        mutate=add_lineage,
    )

    from build.tools.count_dataset_records import collect_work_catalog

    evidence = ({("legacy-retained", "legacy-work"): (
        tmp_path / "missing-candidate", tmp_path / "missing-validation.json"
    )} if with_candidate_evidence else None)
    work = collect_work_catalog(data_root, reconstruction_evidence=evidence).works[0]
    route = work["reconstruction_state"]["routes"][0]
    assert route["association"] == "catalog_claim_lineage+exact_id"
    assert route["verification"] == "verified"
    if with_candidate_evidence:
        assert route["candidate_verification"] == "blocked"
    assert work["reconstruction_state"]["retained_source"] == "manifest_bound"
    assert work["reconstruction_state"]["accepted_ir"] == "not_accepted"
    assert work["reconstruction_state"]["publication"] == "not_ready"
    assert "retained_source_witness_missing_from_parser_provenance" in work[
        "audit_flags"
    ]


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("stale-retained", "retained digest is not verified"),
        ("missing-claim", "does not exactly match current WorkCatalog claims"),
        ("stale-legacy-hash", "does not exactly match current WorkCatalog claims"),
        ("swapped-hashes", "does not exactly match current WorkCatalog claims"),
        ("wrong-work", "does not bind the exact work"),
        ("unsorted", "source paths must be sorted and unique"),
    ),
)
def test_catalog_claim_lineage_fails_closed_on_drift(
    tmp_path: Path, mutation: str, message: str
) -> None:
    data_root = tmp_path / "data"
    legacy_hashes = ("a" * 64, "b" * 64)
    source_paths = (
        "structured-text/legacy-work-a.json",
        "structured-text/legacy-work-b.json",
    )
    for source_path, source_hash in zip(source_paths, legacy_hashes, strict=True):
        _write_resource(
            data_root / source_path,
            resource_id="legacy-work",
            title="Legacy Work",
            author="Author",
            schema_type="structured_text",
            data={"sections": []},
            provenance={"source_hash": f"sha256:{source_hash}"},
        )

    retained_hash = hashlib.sha256(b"retained source bytes\n").hexdigest()

    def add_drifted_lineage(manifest: dict) -> None:
        lineage = {
            "contract": "ocd-catalog-claim-lineage-v1",
            "work_id": "legacy-work",
            "retained_source_sha256": retained_hash,
            "claim_count": 2,
            "claims": [
                {
                    "source_path": source_path,
                    "legacy_source_sha256": source_hash,
                }
                for source_path, source_hash in zip(
                    source_paths, legacy_hashes, strict=True
                )
            ],
        }
        if mutation == "stale-retained":
            lineage["retained_source_sha256"] = "f" * 64
        elif mutation == "missing-claim":
            lineage["claims"].pop()
            lineage["claim_count"] = 1
        elif mutation == "stale-legacy-hash":
            lineage["claims"][0]["legacy_source_sha256"] = "c" * 64
        elif mutation == "swapped-hashes":
            first = lineage["claims"][0]["legacy_source_sha256"]
            lineage["claims"][0]["legacy_source_sha256"] = lineage["claims"][1][
                "legacy_source_sha256"
            ]
            lineage["claims"][1]["legacy_source_sha256"] = first
        elif mutation == "wrong-work":
            lineage["work_id"] = "other-work"
        elif mutation == "unsorted":
            lineage["claims"].reverse()
        manifest["catalog_claim_lineage"] = lineage

    _write_source_manifest(
        tmp_path,
        "sources/legacy/legacy.source-manifest.json",
        source_id="legacy-retained",
        config_ids=(("sources/legacy/config.json", "legacy-work"),),
        mutate=add_drifted_lineage,
    )

    from build.tools.count_dataset_records import collect_work_catalog

    with pytest.raises(ValueError, match=message):
        collect_work_catalog(data_root)


def test_unambiguous_manifest_slug_fallback_binds_the_matching_work(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "calvins-institutes.json",
        resource_id="calvins-institutes",
        title="Institutes of the Christian Religion",
        author="John Calvin",
        schema_type="structured_text",
        data={"sections": []},
    )
    _write_source_manifest(
        tmp_path,
        "sources/calvins-institutes/calvins-institutes.source-manifest.json",
        source_id="calvins-institutes-project-gutenberg-two-volume-retained",
    )

    from build.tools.count_dataset_records import collect_work_catalog

    route = collect_work_catalog(data_root).works[0]["reconstruction_state"]["routes"][
        0
    ]

    assert route == {
        "association": "slug",
        "blocker": "exact source hash participation is required for a fully verified route",
        "manifest": "sources/calvins-institutes/calvins-institutes.source-manifest.json",
        "manifest_verification": "verified",
        "scope": "work",
        "source_id": "calvins-institutes-project-gutenberg-two-volume-retained",
        "verification": "blocked",
    }


def test_ambiguous_manifest_slug_fallback_fails_instead_of_guessing(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    for author, filename in (("One Author", "one.json"), ("Two Author", "two.json")):
        _write_resource(
            data_root / "structured-text" / filename,
            resource_id="shared",
            title="Shared",
            author=author,
            schema_type="structured_text",
            data={"sections": []},
        )
    manifest_path = tmp_path / "sources" / "shared" / "shared.source-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "contract": "ocd-source-manifest-v1",
                "source_id": "shared-retained",
                "authorities": [],
                "converter": {
                    "implementation_path": "build/tei/shared_reconstruction.py"
                },
                "validator": {"implementation_path": "build/tei/shared_oracle.py"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    from build.tools.count_dataset_records import collect_work_catalog

    with pytest.raises(ValueError, match="slug association is ambiguous"):
        collect_work_catalog(data_root)


@pytest.mark.parametrize("declaration", [{"work_id": "one"}, {"work_ids": ["one", "two"]}])
def test_manifest_explicit_work_identity_uses_existing_declared_convention(tmp_path, declaration):
    from build.tools.count_dataset_records import _manifest_config_ids

    assert _manifest_config_ids(declaration, tmp_path) == set(declaration.get("work_ids", ["one"]))


@pytest.mark.parametrize("declaration", [
    {"work_id": "one", "work_ids": ["one"]},
    {"work_ids": []}, {"work_ids": ["one", "one"]},
    {"work_ids": "one"}, {"work_ids": [None]}, {"work_id": "../one"},
])
def test_manifest_explicit_work_identity_rejects_invalid_declarations(tmp_path, declaration):
    from build.tools.count_dataset_records import _manifest_config_ids

    with pytest.raises(ValueError):
        _manifest_config_ids(declaration, tmp_path)


def test_manifest_explicit_identity_rejects_conflicting_config(tmp_path):
    from build.tools.count_dataset_records import _manifest_config_ids

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"resource_id": "other"}), encoding="utf-8")
    with pytest.raises(ValueError, match="conflict with config"):
        _manifest_config_ids({"work_ids": ["one"], "authorities": [{"path": "config.json"}]}, tmp_path)


def _add_bound_work_profile(
    manifest_path: Path, repository_root: Path, profile: dict,
    *, authority_name: str = "reconstruction-profile",
) -> Path:
    profile_path = manifest_path.with_name("profile.json")
    content = (json.dumps(profile, sort_keys=True) + "\n").encode("utf-8")
    profile_path.write_bytes(content)
    manifest = json.loads(manifest_path.read_bytes())
    manifest["authorities"].append({
        "name": authority_name,
        "role": "complete-source-feature-profile",
        "path": profile_path.relative_to(repository_root).as_posix(),
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    })
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    return profile_path


@pytest.mark.parametrize("profile", [{"work_id": "one"}, {"work_ids": ["one", "two"]}])
@pytest.mark.parametrize("authority_name", ["reconstruction-profile", "work-binding", "olympias-binding"])
def test_bound_work_profile_disambiguates_only_a_singular_shared_volume_work(
    tmp_path: Path, profile: dict, authority_name: str,
) -> None:
    manifest_path, source_hash = _write_source_manifest(
        tmp_path, "sources/shared/source-manifest.json", source_id="shared-volume",
    )
    _add_bound_work_profile(manifest_path, tmp_path, profile, authority_name=authority_name)
    for work_id in ("one", "two"):
        _write_resource(
            tmp_path / "data/structured-text" / f"{work_id}.json",
            resource_id=work_id, title=work_id, author="Author",
            schema_type="structured_text", data={"sections": []},
            provenance={"source_hash": source_hash},
        )
    from build.tools.count_dataset_records import collect_work_catalog
    from ocd_kernel.reconstruction.contract import SourceManifest

    SourceManifest.load(manifest_path, repository_root=tmp_path)
    if "work_ids" in profile:
        with pytest.raises(ValueError, match="hash association is ambiguous"):
            collect_work_catalog(tmp_path / "data")
        return
    catalog = collect_work_catalog(tmp_path / "data")
    by_id = {work["work_id"]: work for work in catalog.works}
    route, = by_id["one"]["reconstruction_state"]["routes"]
    assert route["association"] == "source_hash+exact_id"
    assert route["verification"] == "verified"
    assert by_id["two"]["reconstruction_state"]["routes"] == []
    assert all(work["reconstruction_state"]["accepted_ir"] == "not_accepted" for work in catalog.works)
    assert all(work["reconstruction_state"]["publication"] == "not_ready" for work in catalog.works)


@pytest.mark.parametrize("damage", [
    "hash", "bytes", "role", "name", "escape", "resolved-escape",
    "competing-identity", "duplicate-key", "duplicate-profile", "unsafe-identity",
])
def test_profile_identity_requires_one_exact_contained_work_profile(
    tmp_path: Path, damage: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, _ = _write_source_manifest(
        tmp_path, "sources/shared/source-manifest.json", source_id="shared-volume",
    )
    profile_path = _add_bound_work_profile(manifest_path, tmp_path, {"work_id": "one"})
    manifest = json.loads(manifest_path.read_bytes())
    authority = manifest["authorities"][-1]
    if damage == "hash":
        authority["sha256"] = "0" * 64
    elif damage == "bytes":
        authority["bytes"] += 1
    elif damage == "role":
        authority["role"] = "unrelated-profile"
    elif damage == "name":
        authority["name"] = None
    elif damage == "escape":
        authority["path"] = "../outside-profile.json"
    elif damage == "resolved-escape":
        original_resolve = Path.resolve
        outside = tmp_path.parent / "outside-profile.json"

        def resolve_outside(path: Path, *args, **kwargs):
            return outside if path == profile_path else original_resolve(path, *args, **kwargs)

        original_read = Path.read_bytes

        def reject_outside_read(path: Path):
            assert path != outside, "profile outside repository was read before containment check"
            return original_read(path)

        monkeypatch.setattr(Path, "resolve", resolve_outside)
        monkeypatch.setattr(Path, "read_bytes", reject_outside_read)
    elif damage == "duplicate-profile":
        manifest["authorities"].append({**authority, "name": "other-work-profile"})
    else:
        content = {
            "competing-identity": b'{"work_id":"one","work_ids":["two"]}',
            "duplicate-key": b'{"work_id":"two","work_id":"one"}',
            "unsafe-identity": b'{"work_id":"../one"}',
        }[damage]
        profile_path.write_bytes(content)
        authority.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    from build.tools.count_dataset_records import _manifest_config_ids

    assert _manifest_config_ids(manifest, tmp_path) == set()


@pytest.mark.parametrize("shared_source", [False, True])
def test_profile_identity_cannot_override_conflicting_explicit_config_evidence(tmp_path: Path, shared_source: bool) -> None:
    manifest_path, source_hash = _write_source_manifest(
        tmp_path, "sources/shared/source-manifest.json", source_id="shared-volume",
        config_ids=(("sources/shared/config.json", "two"),),
    )
    _add_bound_work_profile(manifest_path, tmp_path, {"work_id": "one"})
    for work_id, digest in (("one", source_hash), ("two", source_hash if shared_source else "b" * 64)):
        _write_resource(
            tmp_path / "data/structured-text" / f"{work_id}.json",
            resource_id=work_id, title=work_id, author="Author",
            schema_type="structured_text", data={"sections": []},
            provenance={"source_hash": digest},
        )
    from build.tools.count_dataset_records import collect_work_catalog

    if not shared_source:
        with pytest.raises(ValueError, match="hash and exact-ID evidence"):
            collect_work_catalog(tmp_path / "data")
        return
    catalog = collect_work_catalog(tmp_path / "data")
    by_id = {work["work_id"]: work for work in catalog.works}
    assert by_id["one"]["reconstruction_state"]["routes"] == []
    route, = by_id["two"]["reconstruction_state"]["routes"]
    assert (route["association"], route["verification"]) == ("source_hash+exact_id", "verified")


@pytest.mark.parametrize(("manifest_relative_path", "work_ids"), [
    ("sources/manifest-acquisitions/first-corinthians-collection-npnf112/source-manifest.json",
     ("chrysostom-homilies-on-1-corinthians", "chrysostom-homilies-on-2-corinthians")),
    ("sources/structured-text/chrysostom-npnf109-16/olympias-corpus/source-manifest.json",
     ("chrysostom-letters-to-olympias", "chrysostom-on-the-priesthood")),
    ("sources/structured-text/chrysostom-npnf109-16/work-bindings/chrysostom-letters-to-olympias/source-manifest.json",
     ("chrysostom-letters-to-olympias", "chrysostom-on-the-priesthood")),
])
@pytest.mark.requires_local_artifacts
def test_real_work_profile_binds_only_its_work_from_the_shared_volume(
    monkeypatch: pytest.MonkeyPatch, manifest_relative_path: str, work_ids: tuple[str, str],
) -> None:
    from build.tools.count_dataset_records import _bind_reconstruction_routes, _default_reconstruction_state
    from ocd_kernel.reconstruction.contract import SourceManifest

    root = Path(__file__).resolve().parents[1]
    manifest_path = root / manifest_relative_path
    original = manifest_path.read_bytes()
    manifest = SourceManifest.load(manifest_path, repository_root=root)
    primary, = [authority for authority in manifest.record["authorities"] if authority["role"] == "primary-source"]
    works = [
        {"work_id": work_id, "resource_ids": [work_id], "title": work_id,
         "source_paths": [], "audit_flags": [],
         "metadata_fields": {"provenance.source_hash": [primary["sha256"]]},
         "reconstruction_state": _default_reconstruction_state()}
        for work_id in work_ids
    ]
    original_rglob = Path.rglob

    def discover_only_real_manifest(path: Path, pattern: str):
        if path == root / "sources":
            return iter([manifest_path] if pattern == "source-manifest.json" else [])
        return original_rglob(path, pattern)

    monkeypatch.setattr(Path, "rglob", discover_only_real_manifest)
    assert _bind_reconstruction_routes(
        works, root / "sources", root / "data",
    ) == {}
    route, = works[0]["reconstruction_state"]["routes"]
    assert (route["association"], route["verification"], route["scope"]) == ("source_hash+exact_id", "verified", "work")
    assert works[1]["reconstruction_state"]["routes"] == []
    assert manifest_path.read_bytes() == original


def test_conflicting_source_hash_and_config_id_fail_instead_of_cross_binding(
    tmp_path: Path,
) -> None:
    manifest_path, hash_a = _write_source_manifest(
        tmp_path, "sources/config-work/hash-work.source-manifest.json",
        source_id="conflicting-evidence",
        config_ids=(("sources/config-work/config.json", "config-work"),),
    )
    data_root = tmp_path / "data"
    for resource_id, source_hash in (("hash-work", hash_a), ("config-work", "b" * 64)):
        _write_resource(
            data_root / "structured-text" / f"{resource_id}.json",
            resource_id=resource_id,
            title=resource_id,
            author="Author",
            schema_type="structured_text",
            data={"sections": []},
            provenance={"source_hash": f"sha256:{source_hash}"},
        )

    from build.tools.count_dataset_records import collect_work_catalog
    from ocd_kernel.reconstruction.contract import SourceManifest

    SourceManifest.load(manifest_path, repository_root=tmp_path)
    with pytest.raises(ValueError, match="hash and exact-ID evidence"):
        collect_work_catalog(data_root)


def test_unbound_runtime_evidence_fails_instead_of_disappearing(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    (tmp_path / "sources").mkdir()
    _write_resource(
        data_root / "structured-text" / "work.json",
        resource_id="work",
        title="Work",
        author="Author",
        schema_type="structured_text",
        data={"sections": []},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    with pytest.raises(ValueError, match="does not bind an exact source/work route"):
        collect_work_catalog(
            data_root,
            reconstruction_evidence={
                ("missing-source", "work"): (
                    tmp_path / "candidate",
                    tmp_path / "validation.json",
                )
            },
        )


def test_runtime_source_admission_derives_exact_source_only_work_from_policy(
    tmp_path: Path,
) -> None:
    source_id = "eebo-tcp-demo-pinned-tei-p5"
    work_id = "demo-source-only-work"
    _write_runtime_source_manifest(
        tmp_path,
        "sources/structured-text/demo-source-only/demo.source-manifest.json",
        source_id=source_id,
        title="A Demonstration Work",
        author="Demonstrator, Example, 1700-1770.",
        date="1760",
    )
    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(
        tmp_path / "data",
        reconstruction_evidence={
            (source_id, work_id): (
                tmp_path / "candidate" / "package",
                tmp_path / "candidate" / "validation.json",
            )
        },
    )

    assert catalog.summary["work_units"] == 1
    work = catalog.works[0]
    assert work["work_id"] == work_id
    assert work["title"] == "A Demonstration Work"
    assert work["author"] == "Demonstrator, Example, 1700-1770."
    assert work["file_count"] == 0
    assert work["audit_flags"] == ["runtime_source_admission"]
    route = work["reconstruction_state"]["routes"]
    assert len(route) == 1
    assert route[0]["association"] == "runtime_source_admission"
    assert route[0]["source_id"] == source_id
    assert route[0]["verification"] == "verified"
    assert route[0]["candidate_verification"] == "blocked"


def test_runtime_source_admission_rejects_unrelated_same_identity_manifests(
    tmp_path: Path,
) -> None:
    work_id = "same-metadata-work"
    source_ids = (
        "eebo-tcp-same-metadata-a-pinned-tei-p5",
        "eebo-tcp-same-metadata-b-pinned-tei-p5",
    )
    for index, source_id in enumerate(source_ids, start=1):
        _write_runtime_source_manifest(
            tmp_path,
            f"sources/structured-text/unrelated-{index}/source.source-manifest.json",
            source_id=source_id,
            title="The Same Metadata",
            author="The Same Author, 1700-1770.",
            date="1760",
            work_id=work_id,
        )

    from build.tools.count_dataset_records import collect_work_catalog

    with pytest.raises(ValueError, match="without an explicit physical-member cohort"):
        collect_work_catalog(
            tmp_path / "data",
            reconstruction_evidence={
                (source_id, work_id): (
                    tmp_path / f"candidate-{index}" / "package",
                    tmp_path / f"candidate-{index}" / "validation.json",
                )
                for index, source_id in enumerate(source_ids, start=1)
            },
        )


@pytest.mark.parametrize("invalid_work_id", [42, ""])
def test_runtime_source_admission_rejects_present_invalid_manifest_work_id(
    tmp_path: Path, invalid_work_id: object
) -> None:
    source_id = "eebo-tcp-invalid-work-id-pinned-tei-p5"
    work_id = "caller-selected-work"
    manifest_path = _write_runtime_source_manifest(
        tmp_path,
        "sources/structured-text/invalid-work-id/source.source-manifest.json",
        source_id=source_id,
        title="A Work",
        author="An Author, 1700-1770.",
        date="1760",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["work_id"] = invalid_work_id
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    from build.tools.count_dataset_records import collect_work_catalog

    with pytest.raises(ValueError, match="manifest work_id is invalid"):
        collect_work_catalog(
            tmp_path / "data",
            reconstruction_evidence={
                (source_id, work_id): (
                    tmp_path / "candidate" / "package",
                    tmp_path / "candidate" / "validation.json",
                )
            },
        )


def test_runtime_source_admission_rejects_boolean_policy_source_bytes(
    tmp_path: Path,
) -> None:
    source_id = "eebo-tcp-boolean-bytes-pinned-tei-p5"
    work_id = "boolean-bytes-work"
    manifest_path = _write_runtime_source_manifest(
        tmp_path,
        "sources/structured-text/boolean-bytes/source.source-manifest.json",
        source_id=source_id,
        title="A Work",
        author="An Author, 1700-1770.",
        date="1760",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    primary = next(
        item for item in manifest["authorities"] if item["role"] == "primary-source"
    )
    primary_path = tmp_path / primary["path"]
    primary_path.write_bytes(b"x")
    primary.update(bytes=1, sha256=hashlib.sha256(b"x").hexdigest())
    policy_authority = next(
        item
        for item in manifest["authorities"]
        if item["role"] == "independent-validation-policy"
    )
    policy_path = tmp_path / policy_authority["path"]
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["provenance"]["source"] = {
        "bytes": True,
        "sha256": primary["sha256"],
    }
    policy_bytes = (json.dumps(policy, sort_keys=True) + "\n").encode("utf-8")
    policy_path.write_bytes(policy_bytes)
    policy_authority.update(
        bytes=len(policy_bytes), sha256=hashlib.sha256(policy_bytes).hexdigest()
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    from build.tools.count_dataset_records import collect_work_catalog

    with pytest.raises(ValueError, match="policy source byte count is invalid"):
        collect_work_catalog(
            tmp_path / "data",
            reconstruction_evidence={
                (source_id, work_id): (
                    tmp_path / "candidate" / "package",
                    tmp_path / "candidate" / "validation.json",
                )
            },
        )


def test_runtime_equiano_admission_coalesces_two_ordered_members_without_composite_title(
    tmp_path: Path,
) -> None:
    resolution = {
        "contract": "ocd-equiano-ecco-tcp-identity-resolution-v1",
        "abstract_work": "The Abstract Narrative",
        "author": "Equiano, Olaudah, b. 1745.",
        "parts": [
            {"part": 1, "tcp_id": "K053415.001"},
            {"part": 2, "tcp_id": "K053415.002"},
        ],
        "status": "resolved",
        "guessed_identity": False,
        "composite_identity": False,
        "canonical_write": False,
    }
    common_resolution = (
        "sources/structured-text/equiano/equiano.identity-resolution.json"
    )
    source_ids = (
        "ecco-tcp-k053415-001-pinned-ets",
        "ecco-tcp-k053415-002-pinned-ets",
    )
    for part, source_id in enumerate(source_ids, start=1):
        _write_runtime_source_manifest(
            tmp_path,
            f"sources/structured-text/equiano-part-{part}/part-{part}.source-manifest.json",
            source_id=source_id,
            title=f"The Abstract Narrative [pt.{part}]",
            author="Equiano, Olaudah, b. 1745.",
            date="1789",
            policy_identity={
                "part": part,
                "tcp_id": f"K053415.00{part}",
            },
            identity_resolution_path=common_resolution,
            identity_resolution=resolution,
        )
    from build.tools.count_dataset_records import collect_work_catalog

    work_id = "equiano-abstract-narrative"
    catalog = collect_work_catalog(
        tmp_path / "data",
        reconstruction_evidence={
            (source_id, work_id): (
                tmp_path / f"candidate-{part}" / "package",
                tmp_path / f"candidate-{part}" / "validation.json",
            )
            for part, source_id in enumerate(source_ids, start=1)
        },
    )

    assert catalog.summary["work_units"] == 1
    work = catalog.works[0]
    assert work["work_id"] == work_id
    assert work["title"] == "The Abstract Narrative"
    assert work["metadata_fields"]["title"] == ["The Abstract Narrative"]
    routes = work["reconstruction_state"]["routes"]
    assert [route["member"]["part"] for route in routes] == [1, 2]
    assert [route["member"]["title"] for route in routes] == [
        "The Abstract Narrative [pt.1]",
        "The Abstract Narrative [pt.2]",
    ]
    assert all(route["scope"] == "partial" for route in routes)
    with pytest.raises(ValueError, match="missing an expected physical member"):
        collect_work_catalog(
            tmp_path / "data",
            reconstruction_evidence={
                (source_ids[0], work_id): (
                    tmp_path / "candidate-1" / "package",
                    tmp_path / "candidate-1" / "validation.json",
                )
            },
        )


def test_runtime_equiano_admission_rejects_conflicting_derived_metadata(
    tmp_path: Path,
) -> None:
    resolution = {
        "contract": "ocd-equiano-ecco-tcp-identity-resolution-v1",
        "abstract_work": "The Abstract Narrative",
        "author": "Equiano, Olaudah, b. 1745.",
        "parts": [
            {"part": 1, "tcp_id": "K053415.001"},
            {"part": 2, "tcp_id": "K053415.002"},
        ],
        "status": "resolved",
        "guessed_identity": False,
        "composite_identity": False,
        "canonical_write": False,
    }
    source_ids = (
        "ecco-tcp-k053415-001-pinned-ets",
        "ecco-tcp-k053415-002-pinned-ets",
    )
    for part, source_id in enumerate(source_ids, start=1):
        _write_runtime_source_manifest(
            tmp_path,
            f"sources/structured-text/equiano-part-{part}/part-{part}.source-manifest.json",
            source_id=source_id,
            title=f"The Abstract Narrative [pt.{part}]",
            author="Equiano, Olaudah, b. 1745.",
            date="1789",
            policy_identity={
                "part": part,
                "tcp_id": f"K053415.00{part}",
                **({"edition": "Different derived edition"} if part == 2 else {}),
            },
            identity_resolution_path=(
                "sources/structured-text/equiano/equiano.identity-resolution.json"
            ),
            identity_resolution=resolution,
        )

    from build.tools.count_dataset_records import collect_work_catalog

    work_id = "equiano-abstract-narrative"
    with pytest.raises(ValueError, match="metadata fields conflict"):
        collect_work_catalog(
            tmp_path / "data",
            reconstruction_evidence={
                (source_id, work_id): (
                    tmp_path / f"candidate-{part}" / "package",
                    tmp_path / f"candidate-{part}" / "validation.json",
                )
                for part, source_id in enumerate(source_ids, start=1)
            },
        )


def test_runtime_source_admission_rejects_ambiguous_policy_identity(
    tmp_path: Path,
) -> None:
    manifest_path = _write_runtime_source_manifest(
        tmp_path,
        "sources/structured-text/ambiguous/ambiguous.source-manifest.json",
        source_id="eebo-tcp-ambiguous-pinned-tei-p5",
        title="Ambiguous Work",
        author="Author, A.",
        date="1760",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    policy = next(
        item
        for item in manifest["authorities"]
        if item["role"] == "independent-validation-policy"
    )
    manifest["authorities"].append({**policy, "name": "duplicate-runtime-policy"})
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    from build.tools.count_dataset_records import collect_work_catalog

    with pytest.raises(ValueError, match="exactly one independent-validation-policy"):
        collect_work_catalog(
            tmp_path / "data",
            reconstruction_evidence={
                ("eebo-tcp-ambiguous-pinned-tei-p5", "ambiguous-work"): (
                    tmp_path / "candidate" / "package",
                    tmp_path / "candidate" / "validation.json",
                )
            },
        )


def test_runtime_equiano_admission_rejects_mismatched_sidecar_identity(
    tmp_path: Path,
) -> None:
    resolution = {
        "contract": "ocd-equiano-ecco-tcp-identity-resolution-v1",
        "abstract_work": "The Abstract Narrative",
        "author": "Equiano, Olaudah, b. 1745.",
        "parts": [{"part": 1, "tcp_id": "K053415.001"}, {"part": 2, "tcp_id": "K053415.002"}],
        "status": "resolved",
        "guessed_identity": False,
        "composite_identity": False,
        "canonical_write": False,
    }
    source_id = "ecco-tcp-k053415-001-pinned-ets"
    _write_runtime_source_manifest(
        tmp_path,
        "sources/structured-text/equiano-mismatch/mismatch.source-manifest.json",
        source_id=source_id,
        title="The Abstract Narrative [pt.1]",
        author="Wrong, Person.",
        date="1789",
        policy_identity={"part": 1, "tcp_id": "K053415.001"},
        identity_resolution_path=(
            "sources/structured-text/equiano/equiano.identity-resolution.json"
        ),
        identity_resolution=resolution,
    )
    from build.tools.count_dataset_records import collect_work_catalog

    with pytest.raises(ValueError, match="policy author does not match"):
        collect_work_catalog(
            tmp_path / "data",
            reconstruction_evidence={
                (source_id, "equiano-mismatch"): (
                    tmp_path / "candidate" / "package",
                    tmp_path / "candidate" / "validation.json",
                )
            },
        )


def test_overlapping_hash_and_two_exact_work_ids_fail_instead_of_dropping_one_work(
    tmp_path: Path,
) -> None:
    _, primary_hash = _write_source_manifest(
        tmp_path,
        "sources/shared/shared.source-manifest.json",
        source_id="shared-retained",
        config_ids=(
            ("sources/work-a/config.json", "work-a"),
            ("sources/work-b/config.json", "work-b"),
        ),
    )
    data_root = tmp_path / "data"
    for resource_id, source_hash in (("work-a", primary_hash), ("work-b", "f" * 64)):
        _write_resource(
            data_root / "structured-text" / f"{resource_id}.json",
            resource_id=resource_id,
            title=resource_id,
            author="Author",
            schema_type="structured_text",
            data={"sections": []},
            provenance={"source_hash": f"sha256:{source_hash}"},
        )

    from build.tools.count_dataset_records import collect_work_catalog

    with pytest.raises(ValueError, match="overlapping multi-work evidence"):
        collect_work_catalog(data_root)


@pytest.mark.parametrize("identity_mode", ["config", "legacy-alias", "declared", "unmatched-declaration"])
def test_shared_source_hash_with_complete_exact_ids_binds_every_work(
    tmp_path: Path, identity_mode: str,
) -> None:
    def declare(manifest):
        if identity_mode == "legacy-alias":
            manifest["work_id"] = "work-a"
        elif identity_mode != "config":
            manifest["work_ids"] = ["work-a", "work-b"]
            if identity_mode == "unmatched-declaration":
                manifest["work_ids"].append("missing-work")

    _, primary_hash = _write_source_manifest(
        tmp_path,
        "sources/shared/shared.source-manifest.json",
        source_id="shared-retained",
        config_ids=(
            ("sources/work-a/config.json", "work-a"),
            ("sources/work-b/config.json", "work-b"),
        ) + (("sources/old-alias/config.json", "unresolved-old-alias"),)
        if identity_mode == "legacy-alias" else (
            ("sources/work-a/config.json", "work-a"),
            ("sources/work-b/config.json", "work-b"),
        ) if identity_mode == "config" else (),
        mutate=declare,
    )
    data_root = tmp_path / "data"
    for resource_id in ("work-a", "work-b", "unselected-work"):
        _write_resource(
            data_root / "structured-text" / f"{resource_id}.json",
            resource_id=resource_id,
            title=resource_id,
            author="Author",
            schema_type="structured_text",
            data={"sections": []},
            provenance={"source_hash": f"sha256:{primary_hash}"},
        )

    from build.tools.count_dataset_records import collect_work_catalog

    if identity_mode == "unmatched-declaration":
        with pytest.raises(ValueError, match="declared work identity does not bind exactly once"):
            collect_work_catalog(data_root)
        return
    catalog = collect_work_catalog(data_root)
    routes = {
        work["work_id"]: work["reconstruction_state"]["routes"]
        for work in catalog.works
    }
    assert set(routes) == {"work-a", "work-b", "unselected-work"}
    assert routes["unselected-work"] == []
    for work_routes in (routes["work-a"], routes["work-b"]):
        assert len(work_routes) == 1
        assert work_routes[0]["association"] == "source_hash+exact_id"
        assert work_routes[0]["verification"] == "verified"


def test_declared_work_absent_from_legacy_catalog_is_accounted_without_slug_guess(tmp_path):
    _write_source_manifest(
        tmp_path, "sources/new/old-work.source-manifest.json",
        source_id="new-declared-source",
        mutate=lambda manifest: manifest.update(work_ids=["new-work"]),
    )
    _write_resource(
        tmp_path / "data/structured-text/old-work.json",
        resource_id="old-work", title="Old Work", author="Author",
        schema_type="structured_text", data={"sections": []},
        provenance={"source_hash": "sha256:" + "f" * 64},
    )
    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(tmp_path / "data")
    assert [work["work_id"] for work in catalog.works] == ["old-work"]
    assert catalog.works[0]["reconstruction_state"]["routes"] == []
    assert catalog.summary["reconstruction_state_counts"]["unassociated_manifests"] == {"verified": 1}


@pytest.mark.parametrize("conflict", ["declared", "overlap", "disjoint", "ambiguous-hash"])
def test_discovered_unverified_identity_conflicts_are_counted_without_binding(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, conflict: str,
) -> None:
    def stale_record(manifest):
        manifest["converter"]["implementation_sha256"] = "0" * 64
        if conflict != "ambiguous-hash":
            manifest["work_ids"] = {
                "declared": ["missing-work"],
                "overlap": ["work-a", "work-b"],
                "disjoint": ["work-b"],
            }[conflict]

    manifest_path, digest = _write_source_manifest(
        tmp_path, "sources/challenge/challenge.source-manifest.json",
        source_id="stale-challenge", mutate=stale_record,
    )
    for work_id in ("work-a", "work-b"):
        _write_resource(
            tmp_path / "data/structured-text" / f"{work_id}.json",
            resource_id=work_id, title=work_id, author="Author",
            schema_type="structured_text", data={"sections": []},
            provenance={"source_hash": "sha256:" + (digest if work_id == "work-a" or conflict == "ambiguous-hash" else "f" * 64)},
        )
    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(tmp_path / "data")
    assert all(not work["reconstruction_state"]["routes"] for work in catalog.works)
    assert catalog.summary["reconstruction_state_counts"]["unassociated_manifests"] == {"blocked": 1}
    assert str(manifest_path) in caplog.text
    assert "stale-challenge" in caplog.text and "manifest verification blocked" in caplog.text
    with pytest.raises(ValueError, match="source manifest"):
        collect_work_catalog(
            tmp_path / "data",
            source_manifest_allowlist=[manifest_path.relative_to(tmp_path)],
            data_resource_allowlist=["data/structured-text/work-a.json", "data/structured-text/work-b.json"],
            reconstruction_evidence={("stale-challenge", "work-a"): (tmp_path / "package", tmp_path / "validation.json")},
        )


def test_historical_blaikie_identity_challenge_is_accounted_without_admission(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    from build.tools.count_dataset_records import _bind_reconstruction_routes

    root = Path(__file__).resolve().parents[1]
    sources = root / "sources"
    path = sources / "commentaries/expositors-bible/blaikie-joshua-retained-install-20261003-v1/identity-challenges-v3/source-work-identity.source-manifest.json"
    original = path.read_bytes()
    record = json.loads(original)
    primary = next(authority for authority in record["authorities"] if authority["role"] == "primary-source")
    work = {
        "work_id": "expositors-bible--william-g-blaikie",
        "resource_ids": ["expositors-bible--william-g-blaikie"],
        "metadata_fields": {"provenance.source_hash": ["sha256:" + primary["sha256"]]},
        "reconstruction_state": {"routes": []},
    }
    original_rglob = Path.rglob

    def selected_manifest_discovery(directory, pattern):
        if directory == sources and pattern in {"*.source-manifest.json", "source-manifest.json"}:
            return iter((path,))
        return original_rglob(directory, pattern)

    monkeypatch.setattr(Path, "rglob", selected_manifest_discovery)
    assert _bind_reconstruction_routes([work], sources, root / "data") == {"blocked": 1}
    assert work["reconstruction_state"]["routes"] == []
    assert str(path) in caplog.text and "declared work identity" in caplog.text
    assert "manifest verification blocked" in caplog.text
    assert path.read_bytes() == original


def test_catalog_derives_visible_structured_blocker_from_current_evidence(
    tmp_path: Path,
) -> None:
    manifest_path, _ = _write_source_manifest(
        tmp_path,
        "sources/blocked/blocked.source-manifest.json",
        source_id="blocked-source",
        config_ids=(("sources/blocked/config.json", "blocked-work"),),
    )
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "blocked-work.json",
        resource_id="blocked-work",
        title="Blocked Work",
        author="Author",
        schema_type="structured_text",
        data={"sections": []},
        provenance={"source_hash": "sha256:" + "f" * 64},
    )
    evidence_path = tmp_path / "sources" / "blocked" / "acquisition.txt"
    evidence_path.write_text(
        "The retained member is unavailable from the named acquisition route.\n",
        encoding="utf-8",
        newline="\n",
    )
    from ocd_kernel.reconstruction.decision import (
        blocker_record,
        decision_path,
        serialize_decision,
    )

    evidence_relative = evidence_path.relative_to(tmp_path).as_posix()
    record = blocker_record(
        manifest_path,
        repository_root=tmp_path,
        source_id="blocked-source",
        work_id="blocked-work",
        blocker={
            "kind": "acquisition",
            "dependency": "named retained-source acquisition",
            "evidence": [
                {
                    "path": evidence_relative,
                    "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                }
            ],
            "attempted_routes": [
                {
                    "route": "retained source member",
                    "outcome": "member unavailable",
                    "evidence_refs": [evidence_relative],
                }
            ],
            "owner": "source-acquisition",
            "next_action": "Acquire the exact retained member.",
            "reopening_condition": "The retained member is present and hashable.",
        },
        decided_by="technical-reviewer",
        decided_at="2026-08-27T00:00:00Z",
    )
    decision_path(
        manifest_path, source_id="blocked-source", work_id="blocked-work"
    ).write_bytes(serialize_decision(record))
    (tmp_path / "raw" / "blocked.txt").unlink()

    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(data_root)
    state = catalog.works[0]["reconstruction_state"]
    assert state["tei_candidate"] == "blocked"
    assert state["validation"] == "blocked"
    assert state["human_review"] == "blocked"
    assert state["accepted_ir"] == "not_accepted"
    assert state["publication"] == "not_ready"
    assert state["blocker"] == "named retained-source acquisition"
    assert state["blocker_details"]["owner"] == "source-acquisition"
    assert state["blocker_details"]["next_action"] == (
        "Acquire the exact retained member."
    )
    assert state["blocker_details"]["reopening_condition"] == (
        "The retained member is present and hashable."
    )


@pytest.mark.parametrize("parser_has_exact_member", [False, True])
def test_catalog_flags_only_retained_config_members_missing_from_parser_provenance(
    tmp_path: Path,
    parser_has_exact_member: bool,
) -> None:
    retained_path = tmp_path / "raw" / "fixture.txt"
    retained_path.parent.mkdir(parents=True)
    retained_path.write_bytes(b"retained upstream witness\n")
    digest = hashlib.sha256(retained_path.read_bytes()).hexdigest()
    config_path = tmp_path / "sources" / "fixture" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "resource_id": "retained-work",
                "source_file": "raw/fixture.txt",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "retained-work.json",
        resource_id="retained-work",
        title="Retained Work",
        author="Author",
        schema_type="structured_text",
        data={"sections": []},
        provenance={
            "source_hash": f"sha256:{digest if parser_has_exact_member else 'f' * 64}"
        },
    )

    from build.tools.count_dataset_records import collect_work_catalog

    work = collect_work_catalog(data_root).works[0]
    if parser_has_exact_member:
        assert work["retained_witness_gaps"] == []
        assert (
            "retained_source_witness_missing_from_parser_provenance"
            not in work["audit_flags"]
        )
    else:
        assert work["retained_witness_gaps"] == [
            {
                "evidence": "sources/fixture/config.json",
                "retained_path": "raw/fixture.txt",
                "member_count": 1,
                "missing_from_parser_provenance": 1,
                "missing_member_sample": ["raw/fixture.txt"],
                "verification": "verified",
            }
        ]
        assert (
            "retained_source_witness_missing_from_parser_provenance"
            in work["audit_flags"]
        )


def test_catalog_reads_configured_external_raw_without_repository_junction(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repo"
    library_root = tmp_path / "library"
    repository_root.mkdir()
    (repository_root / ".ocd-storage.json").write_text(
        json.dumps({"library_root": str(library_root)}) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    retained_path = library_root / "raw" / "fixture.txt"
    retained_path.parent.mkdir(parents=True)
    retained_path.write_bytes(b"retained external witness\n")
    config_path = repository_root / "sources" / "fixture" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "resource_id": "retained-work",
                "source_file": "raw/fixture.txt",
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    data_root = repository_root / "data"
    _write_resource(
        data_root / "structured-text" / "retained-work.json",
        resource_id="retained-work",
        title="Retained Work",
        author="Author",
        schema_type="structured_text",
        data={"sections": []},
        provenance={"source_hash": "sha256:" + "f" * 64},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    gap = collect_work_catalog(data_root).works[0]["retained_witness_gaps"][0]
    assert gap["retained_path"] == "raw/fixture.txt"
    assert gap["member_count"] == 1
    assert gap["verification"] == "verified"


def test_catalog_binds_retained_git_checkout_by_exact_source_url(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "raw" / "provider" / "unrelated-local-name"
    git_config = checkout / ".git" / "config"
    git_config.parent.mkdir(parents=True)
    git_config.write_text(
        '[remote "origin"]\n\turl = https://example.test/provider/exact-work.git\n',
        encoding="utf-8",
        newline="\n",
    )
    source_member = checkout / "src" / "text.xhtml"
    source_member.parent.mkdir(parents=True)
    source_member.write_bytes(b"<p>retained text</p>\n")
    source_config = tmp_path / "sources" / "family" / "config.json"
    source_config.parent.mkdir(parents=True)
    source_config.write_text(
        json.dumps(
            {
                "resource_id": "exact-work",
                "source_url": "https://example.test/provider/exact-work",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "exact-work.json",
        resource_id="exact-work",
        title="Exact Work",
        author="Author",
        schema_type="structured_text",
        data={"sections": []},
        provenance={"source_hash": "sha256:" + "f" * 64},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    gap = collect_work_catalog(data_root).works[0]["retained_witness_gaps"][0]
    assert gap["evidence"] == "sources/family/config.json"
    assert gap["retained_path"] == "raw/provider/unrelated-local-name"
    assert gap["member_count"] == 1
    assert gap["missing_member_sample"] == [
        "raw/provider/unrelated-local-name/src/text.xhtml"
    ]


def test_catalog_does_not_bind_retained_git_checkout_by_mismatched_source_url(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "raw" / "provider" / "checkout"
    git_config = checkout / ".git" / "config"
    git_config.parent.mkdir(parents=True)
    git_config.write_text(
        '[remote "origin"]\n\turl = https://example.test/provider/other-work.git\n',
        encoding="utf-8",
        newline="\n",
    )
    source_member = checkout / "src" / "text.xhtml"
    source_member.parent.mkdir(parents=True)
    source_member.write_bytes(b"<p>retained text</p>\n")
    source_config = tmp_path / "sources" / "family" / "config.json"
    source_config.parent.mkdir(parents=True)
    source_config.write_text(
        json.dumps(
            {
                "resource_id": "exact-work",
                "source_url": "https://example.test/provider/exact-work",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "exact-work.json",
        resource_id="exact-work",
        title="Exact Work",
        author="Author",
        schema_type="structured_text",
        data={"sections": []},
        provenance={"source_hash": "sha256:" + "f" * 64},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    assert collect_work_catalog(data_root).works[0]["retained_witness_gaps"] == []


@pytest.mark.parametrize("section", ["core", "DEFAULT"])
def test_catalog_ignores_url_outside_git_remote_section(
    tmp_path: Path,
    section: str,
) -> None:
    checkout = tmp_path / "raw" / "provider" / "checkout"
    git_config = checkout / ".git" / "config"
    git_config.parent.mkdir(parents=True)
    git_config.write_text(
        f"[{section}]\n\turl = https://example.test/provider/exact-work.git\n",
        encoding="utf-8",
        newline="\n",
    )
    source_member = checkout / "src" / "text.xhtml"
    source_member.parent.mkdir(parents=True)
    source_member.write_bytes(b"<p>retained text</p>\n")
    source_config = tmp_path / "sources" / "family" / "config.json"
    source_config.parent.mkdir(parents=True)
    source_config.write_text(
        json.dumps(
            {
                "resource_id": "exact-work",
                "source_url": "https://example.test/provider/exact-work",
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "exact-work.json",
        resource_id="exact-work",
        title="Exact Work",
        author="Author",
        schema_type="structured_text",
        data={"sections": []},
        provenance={"source_hash": "sha256:" + "f" * 64},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    assert collect_work_catalog(data_root).works[0]["retained_witness_gaps"] == []


def test_catalog_fails_closed_on_malformed_source_config(tmp_path: Path) -> None:
    config_path = tmp_path / "sources" / "fixture" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("{\n", encoding="utf-8", newline="\n")
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "fixture.json",
        resource_id="fixture",
        title="Fixture",
        author="Author",
        schema_type="structured_text",
        data={"sections": []},
        provenance={"source_hash": "sha256:" + "f" * 64},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    with pytest.raises(ValueError, match="source config is invalid JSON object"):
        collect_work_catalog(data_root)


def test_catalog_exposes_missing_configured_retained_path_as_blocked(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "sources" / "fixture" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "resource_id": "fixture",
                "source_file": "raw/fixture/missing.txt",
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "fixture.json",
        resource_id="fixture",
        title="Fixture",
        author="Author",
        schema_type="structured_text",
        data={"sections": []},
        provenance={"source_hash": "sha256:" + "f" * 64},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    gap = collect_work_catalog(data_root).works[0]["retained_witness_gaps"][0]
    assert gap == {
        "evidence": "sources/fixture/config.json",
        "retained_path": "raw/fixture/missing.txt",
        "member_count": 0,
        "missing_from_parser_provenance": 0,
        "missing_member_sample": [],
        "verification": "blocked",
        "blocker": "configured retained path is missing or is an unsupported link",
    }


def test_catalog_fails_closed_on_unreadable_retained_git_metadata(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "raw" / "fixture" / ".git" / "config"
    config_path.parent.mkdir(parents=True)
    config_path.write_bytes(b"\xff")
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "fixture.json",
        resource_id="fixture",
        title="Fixture",
        author="Author",
        schema_type="structured_text",
        data={"sections": []},
        provenance={"source_hash": "sha256:" + "f" * 64},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    with pytest.raises(ValueError, match="retained Git metadata is unreadable"):
        collect_work_catalog(data_root)


def test_catalog_fails_closed_on_malformed_retained_git_metadata(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "raw" / "fixture" / ".git" / "config"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        '[remote "origin"\n\turl = https://example.test/fixture.git\n',
        encoding="utf-8",
        newline="\n",
    )
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "fixture.json",
        resource_id="fixture",
        title="Fixture",
        author="Author",
        schema_type="structured_text",
        data={"sections": []},
        provenance={"source_hash": "sha256:" + "f" * 64},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    with pytest.raises(ValueError, match="retained Git metadata is invalid"):
        collect_work_catalog(data_root)


def test_catalog_fails_closed_on_malformed_retained_witness_evidence(
    tmp_path: Path,
) -> None:
    evidence_path = (
        tmp_path
        / "tests"
        / "fixtures"
        / "fixture"
        / "proof-selection-observations-v1.json"
    )
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text("{}\n", encoding="utf-8", newline="\n")
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "fixture.json",
        resource_id="fixture",
        title="Fixture",
        author="Author",
        schema_type="structured_text",
        data={"sections": []},
        provenance={"source_hash": "sha256:" + "f" * 64},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    with pytest.raises(ValueError, match="lacks identity or authority"):
        collect_work_catalog(data_root)


@pytest.mark.parametrize("inventory_state", ["missing", "stale"])
def test_catalog_exposes_uncurrent_retained_inventory_as_blocked(
    tmp_path: Path,
    inventory_state: str,
) -> None:
    inventory_relative = "tests/fixtures/fixture/retained-member-inventory-v1.tsv"
    inventory_path = tmp_path / inventory_relative
    inventory_path.parent.mkdir(parents=True)
    if inventory_state == "stale":
        inventory_path.write_text(
            "logical_path\tbyte_count\tsha256\n",
            encoding="utf-8",
            newline="\n",
        )
    evidence_path = inventory_path.with_name("proof-selection-observations-v1.json")
    evidence_path.write_text(
        json.dumps(
            {
                "source_identity": {"resource_id": "fixture"},
                "retained_authority": {
                    "inventory": inventory_relative,
                    "inventory_sha256": "0" * 64,
                    "member_count": 2,
                },
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "fixture.json",
        resource_id="fixture",
        title="Fixture",
        author="Author",
        schema_type="structured_text",
        data={"sections": []},
        provenance={"source_hash": "sha256:" + "f" * 64},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    gap = collect_work_catalog(data_root).works[0]["retained_witness_gaps"][0]
    assert gap["retained_path"] == inventory_relative
    assert gap["member_count"] == 2
    assert gap["missing_from_parser_provenance"] == 2
    assert gap["missing_member_sample"] == []
    assert gap["verification"] == "blocked"
    assert (
        gap["blocker"]
        == f"retained inventory {'is missing' if inventory_state == 'missing' else 'digest is stale'}"
    )


@pytest.mark.parametrize("member_path", ["../outside.txt", "C:/outside.txt"])
def test_catalog_rejects_inventory_member_path_escape(
    tmp_path: Path,
    member_path: str,
) -> None:
    inventory_relative = "tests/fixtures/fixture/retained-member-inventory-v1.tsv"
    inventory_path = tmp_path / inventory_relative
    inventory_path.parent.mkdir(parents=True)
    inventory_path.write_text(
        f"logical_path\tbyte_count\tsha256\n{member_path}\t1\t{'0' * 64}\n",
        encoding="utf-8",
        newline="\n",
    )
    evidence_path = inventory_path.with_name("proof-selection-observations-v1.json")
    evidence_path.write_text(
        json.dumps(
            {
                "source_identity": {"resource_id": "fixture"},
                "retained_authority": {
                    "inventory": inventory_relative,
                    "inventory_sha256": hashlib.sha256(
                        inventory_path.read_bytes()
                    ).hexdigest(),
                    "member_count": 1,
                },
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "fixture.json",
        resource_id="fixture",
        title="Fixture",
        author="Author",
        schema_type="structured_text",
        data={"sections": []},
        provenance={"source_hash": "sha256:" + "f" * 64},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    with pytest.raises(ValueError, match="retained inventory member path"):
        collect_work_catalog(data_root)


@pytest.mark.slow
@pytest.mark.requires_local_artifacts
def test_live_catalog_attaches_current_reconstruction_routes_without_claiming_acceptance(live_work_catalog) -> (
    None
):
    repo_root = Path(__file__).resolve().parents[1]

    from build.tools.count_dataset_records import (
        _identity_slug,
        _manifest_config_ids,
        _manifest_source_hashes,
        _work_source_hashes,
        collect_work_catalog,
        render_catalog_html,
        render_catalog_markdown,
    )
    from ocd_kernel.reconstruction.contract import SourceManifest

    catalog = live_work_catalog
    backed = {
        work["work_id"]: work
        for work in catalog.works
        if work["reconstruction_state"]["routes"]
    }

    assert catalog.summary["work_units"] == 402
    manifest_records = {}
    manifest_status = {}
    for manifest_path in sorted(
        path
        for path in (repo_root / "sources").rglob("*.json")
        if path.name == "source-manifest.json"
        or path.name.endswith(".source-manifest.json")
    ):
        relative_path = manifest_path.relative_to(repo_root).as_posix()
        manifest_records[relative_path] = json.loads(manifest_path.read_bytes())
        try:
            SourceManifest.load(manifest_path, repository_root=repo_root)
        except (OSError, ValueError):
            manifest_status[relative_path] = "blocked"
        else:
            manifest_status[relative_path] = "verified"

    live_routes = [
        (work, route)
        for work in backed.values()
        for route in work["reconstruction_state"]["routes"]
    ]
    assert live_routes
    routed_manifests = {route["manifest"] for _work, route in live_routes}
    assert routed_manifests <= set(manifest_records)
    unassociated_manifests = set(manifest_records) - routed_manifests
    assert {
        work["reconstruction_state"]["accepted_ir"] for work in catalog.works
    } == {"not_accepted"}
    assert {
        work["reconstruction_state"]["publication"] for work in catalog.works
    } == {"not_ready"}

    for work, route in live_routes:
        manifest = manifest_records[route["manifest"]]
        expected_source_id = manifest.get("source_id") or Path(
            route["manifest"]
        ).name.removesuffix(".source-manifest.json")
        assert route["source_id"] == expected_source_id
        association = route["association"]
        if "source_hash" in association:
            assert _work_source_hashes(work) & _manifest_source_hashes(manifest)
        if "exact_id" in association:
            assert _manifest_config_ids(manifest, repo_root) & {
                work["work_id"],
                *work["resource_ids"],
            }
        if association == "catalog_claim_lineage+exact_id":
            lineage = manifest["catalog_claim_lineage"]
            assert lineage["work_id"] == work["work_id"]
            assert [claim["source_path"] for claim in lineage["claims"]] == work[
                "source_paths"
            ]
        if association == "slug":
            manifest_slug = _identity_slug(
                Path(route["manifest"]).name.removesuffix(".source-manifest.json")
            )
            assert manifest_slug in {
                _identity_slug(work["work_id"]),
                _identity_slug(work["title"]),
                *(_identity_slug(identifier) for identifier in work["resource_ids"]),
            }
    by_id = {work["work_id"]: work for work in catalog.works}
    spurgeon_gaps = by_id["spurgeon-mtp"]["retained_witness_gaps"]
    assert len(spurgeon_gaps) == 1
    assert spurgeon_gaps[0]["retained_path"] == (
        "tests/fixtures/spurgeon_mtp/retained-member-inventory-v1.tsv"
    )
    assert spurgeon_gaps[0]["member_count"] == 3_551
    assert spurgeon_gaps[0]["verification"] == "verified"
    for work_id in (
        "george-macdonald-unspoken-sermons",
        "heretics",
        "orthodoxy",
        "practical-mysticism",
        "the-everlasting-man",
    ):
        assert by_id[work_id]["retained_witness_gaps"]
        assert (
            "retained_source_witness_missing_from_parser_provenance"
            in by_id[work_id]["audit_flags"]
        )
    assert len(backed["augustine-city-of-god"]["reconstruction_state"]["routes"]) == 4
    assert {
        route["manifest"] for route in backed["augustine-city-of-god"]["reconstruction_state"]["routes"]
    } == {
        "sources/city-of-god/city-of-god-dods-1871.source-manifest.json",
        "sources/city-of-god/city-of-god-npnf-1887.source-manifest.json",
        "sources/city-of-god/city-of-god-dods-1871-electronic-v2.source-manifest.json",
        "sources/city-of-god/city-of-god-npnf-1887-electronic-v2.source-manifest.json",
    }
    assert (
        backed["expositors-bible--g-a-chadwick"]["reconstruction_state"]["routes"][0][
            "scope"
        ]
        == "partial"
    )
    for work_id in ("bcp-1662", "bcp-1662-collects"):
        partial_routes = [
            route for route in backed[work_id]["reconstruction_state"]["routes"]
            if route["manifest"] == "sources/structured-text/bcp-1662/bcp-1662.source-manifest.json"
        ]
        assert len(partial_routes) == 1
        route = partial_routes[0]
        assert (
            route["manifest"]
            == "sources/structured-text/bcp-1662/bcp-1662.source-manifest.json"
        )
        assert route["scope"] == "partial"
        assert route["verification"] == manifest_status[route["manifest"]]
    douay_route = backed["drc"]["reconstruction_state"]["routes"][0]
    assert douay_route["manifest"] == (
        "sources/douay-rheims-1899/douay-rheims-1899.source-manifest.json"
    )
    assert douay_route["scope"] == "work"
    assert douay_route["verification"] == "verified"

    for work_id, work in backed.items():
        state = work["reconstruction_state"]
        assert state["publication"] == "not_ready"
        assert state["accepted_ir"] == "not_accepted"
        expected_route_statuses = {
            "verified"
            if route["association"]
            in {
                "source_hash",
                "source_hash+exact_id",
                "catalog_claim_lineage+exact_id",
            }
            and manifest_status[route["manifest"]] == "verified"
            else "blocked"
            for route in state["routes"]
        }
        assert {
            route["verification"] for route in state["routes"]
        } == expected_route_statuses
        complete_verified = any(
            route["verification"] == "verified" and route["scope"] == "work"
            for route in state["routes"]
        )
        partial_verified = any(
            route["verification"] == "verified" and route["scope"] == "partial"
            for route in state["routes"]
        )
        if complete_verified:
            assert state["retained_source"] == "manifest_bound"
            assert state["tei_candidate"] == "route_available"
            assert state["validation"] == "validator_available"
            assert state["human_review"] == "required"
        elif partial_verified:
            assert state["retained_source"] == "manifest_bound_partial"
            assert state["tei_candidate"] == "route_available_partial"
            assert state["validation"] == "validator_available_partial"
            assert state["human_review"] == "required"
        else:
            assert state["retained_source"] == "manifest_unverified"
            assert state["tei_candidate"] == "blocked"
            assert state["validation"] == "blocked"
            assert state["human_review"] == "blocked"
        assert state["routes"] == sorted(
            state["routes"],
            key=lambda route: (
                route["manifest"],
                route["source_id"],
                route["association"],
            ),
        )
    assert sum(
        work["reconstruction_state"]["retained_source"] == "not_assessed"
        for work in catalog.works
    ) == len(catalog.works) - len(backed)
    counts = catalog.summary["reconstruction_state_counts"]
    assert counts["manifest_verification"] == dict(
        sorted(Counter(manifest_status[path] for path in routed_manifests).items())
    )
    assert counts["route_verification"] == dict(
        sorted(
            Counter(
                route["verification"]
                for work in backed.values()
                for route in work["reconstruction_state"]["routes"]
            ).items()
        )
    )
    assert counts["routes"] == len(live_routes)
    assert counts["unassociated_manifests"] == dict(
        sorted(Counter(manifest_status[path] for path in unassociated_manifests).items())
    )
    assert counts["accepted_ir"] == {"not_accepted": 402}
    assert counts["publication"] == {"not_ready": 402}
    markdown = render_catalog_markdown(catalog)
    html = render_catalog_html(catalog)
    for rendered in (markdown, html):
        for source_id in ("ccel-chadwick-mark-whole-thml", "bcp-1662-retained-partial-html"):
            route = next(route for _work, route in live_routes if route["source_id"] == source_id)
            assert route["scope"] == "partial"
            assert f"{source_id} (partial, {manifest_status[route['manifest']]})" in rendered
        athanasius_route = backed["athanasius-on-the-incarnation"][
            "reconstruction_state"
        ]["routes"][0]
        assert (
            f"{athanasius_route['source_id']} ({athanasius_route['scope']}, "
            f"{athanasius_route['verification']})"
        ) in rendered


def test_church_fathers_quote_dump_is_one_source_collection_unit(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "church-fathers" / "augustine.json",
        resource_id="augustine-of-hippo",
        title=None,
        author="Augustine of Hippo",
        schema_type="church_fathers",
        data=[{"quote": "one"}, {"quote": "two"}],
        provenance={"source": "HistoricalChristianFaith/Commentaries-Database"},
    )
    _write_resource(
        data_root / "church-fathers" / "chrysostom.json",
        resource_id="john-chrysostom",
        title=None,
        author="John Chrysostom",
        schema_type="church_fathers",
        data=[{"quote": "three"}],
        provenance={"source": "HistoricalChristianFaith/Commentaries-Database"},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(data_root)

    assert catalog.summary["work_units"] == 1
    work = catalog.works[0]
    assert work["work_id"] == "church-fathers-quotations"
    assert work["title"] == "Church Fathers verse-reference quotations"
    assert work["author_count"] == 2
    assert work["top_level_records"] == 3
    assert "missing_title" not in work["audit_flags"]
    assert catalog.summary["source_author_labels"] == 2


def test_catalog_surfaces_missing_metadata_and_renders_html(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "untitled.json",
        resource_id="untitled-work",
        title=None,
        author=None,
        schema_type="structured_text",
        data={"sections": [{"heading": "Intro", "blocks": [{"text": "Body."}]}]},
    )

    from build.tools.count_dataset_records import (
        collect_work_catalog,
        render_catalog_html,
    )

    catalog = collect_work_catalog(data_root)

    assert catalog.summary["work_units"] == 1
    work = catalog.works[0]
    assert "missing_title" in work["audit_flags"]
    assert "missing_author" in work["audit_flags"]
    assert "needs_bibliographic_review" in work["audit_flags"]

    html = render_catalog_html(catalog)
    assert "<table" in html
    assert "untitled-work" in html
    assert "missing_title" in html
    assert "<pre>" not in html
    assert "<dt>Resource ID</dt>" in html


def test_lexicon_is_an_auxiliary_tool_not_a_public_work_category(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    lexicon_path = data_root / "lexicon" / "archaic_forms_en.json"
    lexicon_path.parent.mkdir(parents=True, exist_ok=True)
    lexicon_path.write_text(json.dumps({"shew": "show"}) + "\n", encoding="utf-8")
    _write_resource(
        data_root / "structured-text" / "work.json",
        resource_id="work",
        title="A Work",
        author="An Author",
        schema_type="structured_text",
        data={"sections": []},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(data_root)

    assert catalog.summary["work_units"] == 1
    assert "lexicon" not in catalog.summary["works_by_category"]
    assert catalog.works[0]["category_label"] == "Books and Long-Form Works"


def test_topical_schema_is_cataloged_as_topical_even_under_legacy_reference_path(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "reference" / "torrey.json",
        resource_id="torreys-topical-textbook",
        title="Torrey's New Topical Textbook",
        author="R. A. Torrey",
        schema_type="topical_reference",
        data=[{"topic": "Prayer"}],
    )

    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(data_root)

    assert catalog.summary["works_by_category"] == {"topical-reference": 1}
    assert catalog.works[0]["category_label"] == "Topical Bibles and Indexes"


def test_publication_date_is_derived_from_original_publication_year(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "catechisms" / "outlines.json",
        resource_id="outlines",
        title="Outlines of Theology",
        author="A. A. Hodge",
        schema_type="catechism_qa",
        data=[{"question": "Q?", "answer": "A."}],
        provenance={"source_edition": "1879 edition"},
        extra_meta={"original_publication_year": 1879},
    )

    from build.tools.count_dataset_records import (
        collect_work_catalog,
        render_catalog_html,
        render_catalog_markdown,
    )

    catalog = collect_work_catalog(data_root)

    assert catalog.works[0]["publication_date"] == "1879"
    assert "<th>Publication date</th>" in render_catalog_html(catalog)
    assert (
        "| Category | Title | Author | Publication date |"
        in render_catalog_markdown(catalog)
    )


def test_hymn_collection_renders_as_summary_not_individual_hymn_rows(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "hymns" / "hymnary-pd" / "collection.json",
        resource_id="hymnary-pd",
        title="Public Domain Hymns (Hymnary.org)",
        author=None,
        schema_type="hymn_collection",
        data=[
            {
                "title": "First Hymn",
                "hymnal_title": "Test Hymnal",
                "hymnal_year": 1900,
                "year_written": 1850,
                "language": "en",
            },
            {
                "title": "Second Hymn",
                "hymnal_title": "Other Hymnal",
                "hymnal_year": 1910,
                "year_written": None,
                "language": "en",
            },
        ],
        provenance={"source_edition": "Hymnary.org export"},
    )

    from build.tools.count_dataset_records import (
        collect_work_catalog,
        render_catalog_html,
    )

    catalog = collect_work_catalog(data_root)
    work = catalog.works[0]

    assert work["publication_date"] == "Hymnal publication years 1900-1910"
    assert work["hymn_summary"]["hymn_entries"] == 2

    html = render_catalog_html(catalog)
    assert "Hymn collection coverage" in html
    assert "2 hymn entries" in html
    assert "First Hymn" not in html


def test_slug_equivalent_human_title_is_not_flagged_as_internal_id(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "catechisms" / "westminster-shorter-catechism.json",
        resource_id="westminster-shorter-catechism",
        title="Westminster Shorter Catechism",
        author="Westminster Assembly",
        schema_type="catechism_qa",
        data=[{"question": "Q?", "answer": "A."}],
    )

    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(data_root)

    assert catalog.works[0]["audit_flags"] == ["missing_source_edition"]


def test_nsh_pipeline_reference_artifacts_are_out_of_dataset_scope(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root
        / "reference"
        / "schaff"
        / "encyclopedia"
        / "1908-1914"
        / "original"
        / "vol_01.json",
        resource_id="schaff-herzog-encyclopedia",
        title="New Schaff-Herzog Encyclopedia of Religious Knowledge",
        author=None,
        schema_type="reference_entry",
        data=[{"id": "a"}],
    )
    _write_resource(
        data_root / "reference" / "schaff-herzog-encyclopedia.json",
        resource_id="schaff-herzog-encyclopedia",
        title="Schaff-Herzog Encyclopedia of Religious Knowledge",
        author="Philip Schaff",
        schema_type="reference_entry",
        data=[{"id": "b"}],
    )

    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(data_root)

    assert catalog.summary["work_units"] == 1
    assert catalog.summary["top_level_records"] == 1
    assert (
        catalog.works[0]["title"] == "Schaff-Herzog Encyclopedia of Religious Knowledge"
    )


def test_known_dataset_labels_are_flagged_for_public_title_review(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "commentaries" / "calvin" / "genesis.json",
        resource_id="calvin",
        title="Calvin's Collected Commentaries",
        author="John Calvin",
        schema_type="commentary",
        data=[{"commentary_text": "Text."}],
        provenance={"source_edition": "CrossWire SWORD module"},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(data_root)

    assert "official_title_unconfirmed" in catalog.works[0]["audit_flags"]


def test_summary_counts_legacy_huggingface_flattened_rows(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "work.json",
        resource_id="work",
        title="Work",
        author="Author",
        schema_type="structured_text",
        data={
            "work_id": "work",
            "sections": [
                {
                    "content_blocks": ["one", "two"],
                    "children": [{"content_blocks": ["three"]}],
                }
            ],
        },
    )
    _write_resource(
        data_root / "doctrinal-documents" / "doc.json",
        resource_id="doc",
        title="Doc",
        author="Author",
        schema_type="doctrinal_document",
        data={
            "document_id": "doc",
            "units": [
                {"children": [{"content": "one"}, {"content": "two"}]},
            ],
        },
    )

    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(data_root)

    assert catalog.summary["top_level_records"] == 2
    assert catalog.summary["legacy_hf_export_records"] == 5
    assert catalog.summary["legacy_hf_export_records_by_schema"] == {
        "doctrinal_document": 2,
        "structured_text": 3,
    }


@pytest.mark.parametrize("change", ["none", "manifest", "candidate", "report", "closure", "schema", "unsupported", "import_error", "value_error", "refused_invalid", "failed"])
def test_candidate_review_reuse_requires_fresh_complete_bindings(tmp_path, monkeypatch, change):
    from types import SimpleNamespace
    from hashlib import sha256
    from build.tools import count_dataset_records as catalog_module
    from ocd_kernel.reconstruction import contract, closure_verification, decision

    manifest_path = tmp_path / "source-manifest.json"
    candidate_path = tmp_path / "candidate"
    report_path = tmp_path / "validation.json"
    for path in (manifest_path, candidate_path, report_path):
        path.write_bytes(b"original")
    schema_root = tmp_path / "ocd_kernel/tei/vendor/xsd"
    schema_root.mkdir(parents=True)
    for name in ("tei_all.xsd", "tei_all_teix.xsd", "tei_all_xml.xsd"):
        (schema_root / name).write_bytes(b"original")
    calls = {"manifest": 0, "candidate": 0, "closure": 0, "oracle": 0}
    closure = ["original"]

    def load_manifest(cls, path, *, repository_root):
        calls["manifest"] += 1
        return SimpleNamespace(sha256=sha256(path.read_bytes()).hexdigest(),
                               record=contract._freeze({"validator": {"implementation_path": "oracle.py"},
                                                        "authorities": [{"name": "policy"}]}))

    def load_candidate(cls, path):
        calls["candidate"] += 1
        return SimpleNamespace(path=path, sha256=sha256(path.read_bytes()).hexdigest())

    def live_closure(*args, **kwargs):
        calls["closure"] += 1
        record = args[2]
        assert type(record) is dict and type(record["authorities"]) is list
        assert type(record["authorities"][0]) is dict
        if change == "unsupported":
            raise NotImplementedError("no exact closure adapter")
        if change == "import_error":
            raise ImportError("fingerprint dependency unavailable")
        if change in {"value_error", "refused_invalid"}:
            raise ValueError("fingerprint unavailable")
        return closure[0], "test"

    def verify(*args, **kwargs):
        calls["oracle"] += 1
        if change in {"failed", "refused_invalid"}:
            raise ValueError("invalid evidence")

    monkeypatch.setattr(contract.SourceManifest, "load", classmethod(load_manifest))
    monkeypatch.setattr(contract.CandidatePackage, "load", classmethod(load_candidate))
    monkeypatch.setattr(closure_verification, "_call_validator_closure", live_closure)
    monkeypatch.setattr(decision, "load_verified_review", verify)
    reviews = set()

    def apply():
        work = {"reconstruction_state": {}}
        route = {}
        catalog_module._apply_candidate_validation_evidence(
            work, manifest_path, tmp_path, scope="work", verified=True,
            candidate_path=candidate_path, validation_path=report_path,
            route=route, verified_reviews=reviews)
        assert route["validation_verification"] == ("blocked" if change in {"failed", "refused_invalid"} else "verified")

    apply()
    if change in {"manifest", "candidate", "report"}:
        {"manifest": manifest_path, "candidate": candidate_path, "report": report_path}[change].write_bytes(b"changed!")
    elif change == "closure":
        closure[0] = "changed"
    elif change == "schema":
        (schema_root / "tei_all_xml.xsd").write_bytes(b"changed!")
    apply()
    assert calls == {"manifest": 2, "candidate": 2, "closure": 2,
                     "oracle": 1 if change == "none" else 2}
    # No result survives a new catalog build, even with identical files.
    reviews = set()
    apply()
    assert calls["oracle"] == (2 if change == "none" else 3)


@pytest.mark.parametrize("extra_declarations", [False, True])
def test_shared_retained_members_stream_once_and_compare_every_work(tmp_path, monkeypatch, extra_declarations):
    from build.tools import count_dataset_records as module
    source = tmp_path / "raw/retained.txt"
    source.parent.mkdir()
    original = b"retained source text\n"
    source.write_bytes(original)
    digest = hashlib.sha256(original).hexdigest()
    config = tmp_path / "sources/fixture/config.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"resource_id": "first", "work_id": "second",
                                  "source_file": "raw/retained.txt"}), encoding="utf-8")
    if extra_declarations:
        other = tmp_path / "sources/other/config.json"
        other.parent.mkdir()
        other.write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
        registry = tmp_path / "sources/witnesses/registry.json"
        registry.parent.mkdir()
        registry.write_text(json.dumps({"witnesses": [
            {"related_resource_id": "first", "local_path": "raw/retained.txt"},
        ]}), encoding="utf-8")
    original_read = Path.read_bytes
    original_hash = module._sha256_retained_member
    reads = []

    def refuse_whole_file_read(path):
        assert path != source, "Large retained sources must be hashed in bounded chunks"
        return original_read(path)

    def stream(path):
        reads.append(path)
        return original_hash(path)

    monkeypatch.setattr(Path, "read_bytes", refuse_whole_file_read)
    monkeypatch.setattr(module, "_sha256_retained_member", stream)

    def works():
        return [{"work_id": key, "metadata_fields": {"provenance.source_hash": [value]}}
                for key, value in (("first", digest), ("second", "f" * 64))]

    first = works()
    module._attach_retained_witness_gaps(first, tmp_path)
    assert reads == [source]
    assert first[0]["retained_witness_gaps"] == []
    assert first[1]["retained_witness_gaps"][0]["missing_from_parser_provenance"] == 1
    source.write_bytes(b"changed source text\n")
    second = works()
    module._attach_retained_witness_gaps(second, tmp_path)
    assert reads == [source, source]
    assert all(work["retained_witness_gaps"][0]["missing_from_parser_provenance"] == 1 for work in second)

    def refuse_boundary(*args):
        raise ValueError("retained member outside storage boundary")

    monkeypatch.setattr(module, "_logical_retained_path", refuse_boundary)
    with pytest.raises(ValueError, match="outside storage boundary"):
        module._attach_retained_witness_gaps(works(), tmp_path)
    assert reads == [source, source]

    if extra_declarations:
        boundary_calls = []

        def refuse_repeated_declaration(root, path, label):
            boundary_calls.append(path)
            if len(boundary_calls) == 2:
                raise ValueError("retained member outside storage boundary")
            return "raw/retained.txt"

        monkeypatch.setattr(module, "_logical_retained_path", refuse_repeated_declaration)
        with pytest.raises(ValueError, match="outside storage boundary"):
            module._attach_retained_witness_gaps(works(), tmp_path)
        assert boundary_calls == [source, source]
        assert reads == [source, source, source]
