"""Public seam tests for bounded verification events."""

from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from cvw_phase1b import bundle as bundle_module
from cvw_phase1b import generate_bundle, serialize_bundle
from cvw_phase1b import EventError, serialize_event, validate_event
from tests.test_cvw_phase1b_inventory import (
    _copy_parser_dependency_closure,
    _write_descriptor_catalog_identity,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_OWNERSHIP = REPO_ROOT / "cvw_phase1b" / "fixtures" / "asv_ownership.json"
LIVE_POLICY = REPO_ROOT / "cvw_phase1b" / "fixtures" / "asv_policy.json"
LIVE_SPURGEON_OWNERSHIP = (
    REPO_ROOT / "cvw_phase1b" / "fixtures" / "spurgeon_ownership.json"
)
LIVE_SPURGEON_POLICY = REPO_ROOT / "cvw_phase1b" / "fixtures" / "spurgeon_policy.json"
LIVE_SPURGEON_SOURCE = REPO_ROOT / "raw" / "ia" / "spurgeon_all_of_grace.txt"
LIVE_SPURGEON_WRITER_MANIFEST = (
    REPO_ROOT
    / "review"
    / "writer-manifests"
    / "gutenberg-inline-markup-2026-07-05.json"
)


def _evidence_for_members(
    bundle: dict[str, object], member_ids: list[str]
) -> list[dict[str, str]]:
    references = {
        (anchor["artifact_path"], anchor["artifact_sha256"])
        for frame in bundle["frames"].values()
        for anchor in frame["anchors"]
        if anchor["member_id"] in member_ids
    }
    return [
        {"path": path, "raw_sha256": raw_sha256}
        for path, raw_sha256 in sorted(references)
    ]


def _live_event() -> tuple[dict[str, object], dict[str, object]]:
    bundle = generate_bundle(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)
    anchor = bundle["frames"]["source_members"]["anchors"][0]
    event = {
        "identity": "verification-event-v1",
        "bundle_binding": {
            "identity": "verification-bundle-v1",
            "raw_sha256": hashlib.sha256(serialize_bundle(bundle)).hexdigest(),
        },
        "work_id": bundle["scope"]["work_id"],
        "rendering_id": bundle["scope"]["rendering_id"],
        "subject_grain": "collection_member",
        "subject_id": anchor["member_id"],
        "anchor": {
            "frame": "source_members",
            "anchor_id": anchor["anchor_id"],
        },
        "actor": "trial-reviewer",
        "timestamp": "2026-07-18T00:00:00+00:00",
        "event_kind": "finding",
        "dimension": "omission",
        "severity": "high",
        "disposition": "open",
        "evidence": _evidence_for_members(bundle, [anchor["member_id"]]),
        "notes": "The bounded member was reviewed for omission.",
    }
    return event, bundle


def _member_set_sha256(member_ids: list[str]) -> str:
    data = (json.dumps(sorted(member_ids), separators=(",", ":")) + "\n").encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _canonical_sha256(payload: object) -> str:
    data = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _rebind_event(event: dict[str, object], bundle: dict[str, object]) -> None:
    event["bundle_binding"]["raw_sha256"] = _canonical_sha256(bundle)


def _rebind_bundle_seed(bundle: dict[str, object]) -> None:
    seed = _canonical_sha256(
        {
            "inventory_binding": bundle["inventory_binding"],
            "dependencies": sorted(
                bundle["dependencies"],
                key=lambda dependency: (dependency["role"], dependency["path"]),
            ),
        }
    )
    bundle["sampling"]["seed"] = seed
    source_selections = bundle_module._select_anchors(
        "source_members",
        bundle["frames"]["source_members"]["anchors"],
        seed,
        bundle["policy"]["sample_size"],
    )
    output_selections = bundle_module._select_anchors(
        "canonical_outputs",
        bundle["frames"]["canonical_outputs"]["anchors"],
        seed,
        bundle["policy"]["sample_size"],
    )
    bundle["selected_anchors"] = [*source_selections, *output_selections]
    selected_output_ids = {selection["anchor_id"] for selection in output_selections}
    selected_output_anchors = [
        anchor
        for anchor in bundle["frames"]["canonical_outputs"]["anchors"]
        if anchor["anchor_id"] in selected_output_ids
    ]
    source_artifacts = [
        artifact for artifact in bundle["artifacts"] if artifact["grain"] == "source_artifact"
    ]
    bundle["artifacts"] = [
        *source_artifacts,
        *[
            {
                "grain": "canonical_artifact",
                "member_id": anchor["member_id"],
                "path": anchor["artifact_path"],
                "raw_sha256": anchor["artifact_sha256"],
                "rendering_id": bundle["scope"]["rendering_id"],
                "work_id": bundle["scope"]["work_id"],
            }
            for anchor in sorted(
                selected_output_anchors,
                key=lambda selected_anchor: selected_anchor["member_id"],
            )
        ],
    ]


def _event_for(
    bundle: dict[str, object],
    *,
    frame: str = "source_members",
    index: int = 0,
    subject_grain: str = "collection_member",
) -> dict[str, object]:
    anchor = bundle["frames"][frame]["anchors"][index]
    event = {
        "identity": "verification-event-v1",
        "bundle_binding": {
            "identity": "verification-bundle-v1",
            "raw_sha256": hashlib.sha256(serialize_bundle(bundle)).hexdigest(),
        },
        "work_id": bundle["scope"]["work_id"],
        "rendering_id": bundle["scope"]["rendering_id"],
        "subject_grain": subject_grain,
        "subject_id": anchor["member_id"],
        "anchor": {"frame": frame, "anchor_id": anchor["anchor_id"]},
        "actor": "trial-reviewer",
        "timestamp": "2026-07-18T00:00:00+00:00",
        "event_kind": "finding",
        "dimension": "omission",
        "severity": "high",
        "disposition": "open",
        "evidence": [],
        "notes": "The bounded member was reviewed for omission.",
    }
    if subject_grain == "work":
        event["subject_id"] = bundle["scope"]["work_id"]
    elif subject_grain == "rendering":
        event["subject_id"] = bundle["scope"]["rendering_id"]
    elif subject_grain == "artifact":
        event["subject_id"] = anchor["artifact_path"]
    elif subject_grain == "canonical_record":
        event["subject_id"] = anchor["member_id"]
    if subject_grain in {"work", "rendering"}:
        member_ids = sorted(
            item["member_id"]
            for item in bundle["frames"]["source_members"]["anchors"]
        )
        event["scope_snapshot"] = {
            "coverage": "complete",
            "member_grain": "collection_member",
            "member_ids": member_ids,
            "count": len(member_ids),
            "member_set_sha256": _member_set_sha256(member_ids),
        }
    else:
        member_ids = [anchor["member_id"]]
    event["evidence"] = _evidence_for_members(bundle, member_ids)
    return event


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


@pytest.fixture
def small_event_bundle(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "independent-event-repository"
    source = {
        "translation": "ASV: American Standard Version (1901)",
        "books": [
            {
                "name": "Genesis",
                "chapters": [{"chapter": 1, "verses": [{"verse": 1, "text": "In the beginning"}]}],
            },
            {
                "name": "Exodus",
                "chapters": [{"chapter": 1, "verses": [{"verse": 1, "text": "Now these are"}]}],
            },
        ],
    }
    source_bytes = (json.dumps(source, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _write_json(root / "raw/bible_databases/formats/json/ASV.json", source)
    _write_json(
        root / "sources/bible-text/asv/config.json",
        {"resource_id": "asv", "source_file": "raw/bible_databases/formats/json/ASV.json"},
    )
    for member_id, book in (("genesis", "Genesis"), ("exodus", "Exodus")):
        _write_json(
            root / f"data/bible-text/asv/{member_id}.json",
            {"meta": {"id": "asv", "scope": {"book": book}}, "data": []},
        )
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs/WORK_CATALOG.md").write_text(
        "| Category | Title | Author | Publication date | Files | Records | Audit flags |\n"
        "|---|---|---|---|---:|---:|---|\n"
        "| Bible Translations | American Standard Version | | 1901 | 2 | 0 | missing_author |\n",
        encoding="utf-8",
    )
    for relative_path in (
        "cvw_phase1b/inventory.py",
        "cvw_phase1b/bundle.py",
        "cvw_phase1b/event.py",
        "cvw_phase1b/ownership.py",
        "build/parsers/bible_text_translations.py",
        "build/parsers/gutenberg_evangelical.py",
        "build/tools/count_dataset_records.py",
        "schemas/v1/verification_inventory.schema.json",
        "schemas/v1/verification_bundle.schema.json",
        "cvw_phase1b/fixtures/asv_policy.json",
        "schemas/v1/writer_manifest.schema.json",
        "build/lib/writer_identities.py",
        "cvw_phase1a/contracts.py",
    ):
        destination = root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative_path, destination)
    _copy_parser_dependency_closure(root, "build/parsers/bible_text_translations.py")
    ownership = {
        "identity": "verification-ownership-v1",
        "adapter": "bible_collection",
        "works": [{"grain": "work", "work_id": "asv"}],
        "renderings": [
            {"grain": "rendering", "rendering_id": "asv:scrollmapper-json", "work_id": "asv"}
        ],
        "source_artifact": {
            "grain": "source_artifact",
            "rendering_id": "asv:scrollmapper-json",
            "path": "raw/bible_databases/formats/json/ASV.json",
            "expected_raw_sha256": hashlib.sha256(source_bytes).hexdigest(),
        },
        "source_config": "sources/bible-text/asv/config.json",
        "canonical_root": "data/bible-text/asv",
        "ir_artifacts": [],
        "generator_dependency": "cvw_phase1b/inventory.py",
        "parser_dependency": "build/parsers/bible_text_translations.py",
        "catalog": {
            "path": "docs/WORK_CATALOG.md",
            "identity_path": "cvw_phase1a/fixtures/work_catalog_identity.json",
            "work_id": "asv",
            "title": "American Standard Version",
            "author": "",
            "category": "Bible Translations",
            "expected_file_count": 2,
        },
        "grains": {
            "work": "work",
            "rendering": "rendering",
            "member": "collection_member",
            "source_artifact": "source_artifact",
            "canonical_artifact": "canonical_artifact",
            "ir_artifact": "ir_artifact",
        },
    }
    ownership_path = root / "cvw_phase1b/fixtures/asv_ownership.json"
    _write_descriptor_catalog_identity(root, ownership)
    _write_json(ownership_path, ownership)
    policy_path = root / "cvw_phase1b/fixtures/asv_policy.json"
    bundle = generate_bundle(root, ownership_path, policy_path)
    return root, bundle


@pytest.fixture
def small_single_file_event_bundle(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "independent-single-file-event-repository"
    work_id = "tiny-single-file"
    rendering_id = f"{work_id}:structured-json"
    source_path = "raw/ia/tiny-single-file.txt"
    source_bytes = b"A tiny independent witness.\n"
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    source_file = root / source_path
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_bytes(source_bytes)
    _write_json(
        root / "sources/structured-text/tiny-single-file/config.json",
        {
            "slug": work_id,
            "schema": "structured_text",
            "source_type": "ia",
            "ia_id": "tiny",
            "source_url": "https://example.invalid/tiny.txt",
            "source_hash": f"sha256:{source_hash}",
            "download_date": "2026-07-18",
            "processing_script": "build/parsers/gutenberg_evangelical.py@v1.0.0",
        },
    )
    _write_json(
        root / "data/structured-text/tiny-single-file.json",
        {
            "meta": {
                "id": work_id,
                "title": "Tiny Single File",
                "author": "A Tiny Author",
                "language": "en",
                "tradition": ["evangelical"],
                "license": "public-domain",
                "schema_type": "structured_text",
                "schema_version": "3.0.0",
                "completeness": "full",
                "provenance": {
                    "source_url": "https://example.invalid/tiny.txt",
                    "source_format": "plain text (UTF-8)",
                    "source_edition": "Tiny edition",
                    "download_date": "2026-07-18",
                    "source_hash": f"sha256:{source_hash}",
                    "processing_method": "automated",
                    "processing_script_version": (
                        "build/parsers/gutenberg_evangelical.py@v1.0.0"
                    ),
                    "processing_date": "2026-07-18",
                },
            },
            "data": {
                "work_id": work_id,
                "work_kind": "treatise",
                "sections": [
                    {
                        "section_type": "chapter",
                        "content_blocks": ["A tiny independent witness."],
                    }
                ],
            },
        },
    )
    catalog = root / "docs/WORK_CATALOG.md"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text(
        "| Category | Title | Author | Publication date | Files | Records | Audit flags |\n"
        "|---|---|---|---|---:|---:|---|\n"
        "| Books and Long-Form Works | Tiny Single File | | 2026 | 1 | 1 | |\n",
        encoding="utf-8",
    )
    for relative_path in (
        "cvw_phase1a/contracts.py",
        "cvw_phase1b/inventory.py",
        "cvw_phase1b/bundle.py",
        "cvw_phase1b/event.py",
        "cvw_phase1b/ownership.py",
        "build/lib/writer_identities.py",
        "build/parsers/gutenberg_evangelical.py",
        "build/tools/count_dataset_records.py",
        "schemas/v1/verification_inventory.schema.json",
        "schemas/v1/verification_bundle.schema.json",
        "schemas/v1/structured_text.schema.json",
        "schemas/v1/writer_manifest.schema.json",
        "cvw_phase1b/fixtures/spurgeon_policy.json",
    ):
        destination = root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative_path, destination)
    _copy_parser_dependency_closure(root, "build/parsers/gutenberg_evangelical.py")
    ownership_path = root / "cvw_phase1b/fixtures/tiny_ownership.json"
    ownership = {
            "identity": "verification-ownership-v1",
            "adapter": "single_file",
            "works": [{"grain": "work", "work_id": work_id}],
            "renderings": [
                {
                    "grain": "rendering",
                    "rendering_id": rendering_id,
                    "work_id": work_id,
                }
            ],
            "source_artifact": {
                "grain": "source_artifact",
                "rendering_id": rendering_id,
                "path": source_path,
                "expected_raw_sha256": source_hash,
            },
            "source_config": "sources/structured-text/tiny-single-file/config.json",
            "canonical_root": "data/structured-text",
            "canonical_path": "data/structured-text/tiny-single-file.json",
            "ir_artifacts": [],
            "generator_dependency": "cvw_phase1b/inventory.py",
            "parser_dependency": "build/parsers/gutenberg_evangelical.py",
            "catalog": {
                "path": "docs/WORK_CATALOG.md",
                "identity_path": "cvw_phase1a/fixtures/work_catalog_identity.json",
                "work_id": work_id,
                "title": "Tiny Single File",
                "author": "A Tiny Author",
                "category": "Books and Long-Form Works",
                "expected_file_count": 1,
            },
            "grains": {
                "work": "work",
                "rendering": "rendering",
                "member": "collection_member",
                "source_artifact": "source_artifact",
                "canonical_artifact": "canonical_artifact",
                "ir_artifact": "ir_artifact",
            },
        }
    _write_descriptor_catalog_identity(root, ownership)
    _write_json(ownership_path, ownership)
    bundle = generate_bundle(
        root,
        ownership_path,
        root / "cvw_phase1b/fixtures/spurgeon_policy.json",
    )
    return root, bundle


@pytest.mark.requires_local_artifacts
def test_live_asv_event_validates_and_serializes_deterministically() -> None:
    event, bundle = _live_event()

    assert validate_event(event, bundle, repository_root=REPO_ROOT) == event

    serialized = serialize_event(event)
    expected = (
        json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    assert serialized == expected
    assert serialized.endswith(b"\n")
    assert not serialized.endswith(b"\n\n")
    assert serialized.count(b"\n") == 1


@pytest.mark.requires_local_artifacts
def test_serializer_is_closed_and_rejects_nonfinite_non_json_and_ambiguous_text() -> None:
    event, _ = _live_event()

    unknown = deepcopy(event)
    unknown["anchor"]["unexpected"] = True
    with pytest.raises(EventError):
        serialize_event(unknown)

    non_json = deepcopy(event)
    non_json["notes"] = object()
    with pytest.raises(EventError, match="non-JSON"):
        serialize_event(non_json)

    nonfinite = deepcopy(event)
    nonfinite["severity"] = float("nan")
    with pytest.raises(EventError, match="non-finite"):
        serialize_event(nonfinite)

    leading_space = deepcopy(event)
    leading_space["actor"] = " trial-reviewer"
    with pytest.raises(EventError, match="normalized|does not validate"):
        serialize_event(leading_space)

    naive = deepcopy(event)
    naive["timestamp"] = "2026-07-18T00:00:00"
    with pytest.raises(EventError, match="timezone|date-time"):
        serialize_event(naive)


@pytest.mark.requires_local_artifacts
def test_bundle_hash_subject_anchor_and_evidence_are_recomputed() -> None:
    event, bundle = _live_event()

    false_bundle_hash = deepcopy(event)
    false_bundle_hash["bundle_binding"]["raw_sha256"] = "0" * 64
    with pytest.raises(EventError, match="bundle binding"):
        validate_event(false_bundle_hash, bundle, repository_root=REPO_ROOT)

    wrong_work = deepcopy(event)
    wrong_work["work_id"] = "another-work"
    with pytest.raises(EventError, match="work_id"):
        validate_event(wrong_work, bundle, repository_root=REPO_ROOT)

    wrong_subject = deepcopy(event)
    wrong_subject["subject_id"] = "not-a-member"
    with pytest.raises(EventError, match="subject"):
        validate_event(wrong_subject, bundle, repository_root=REPO_ROOT)

    cross_frame = deepcopy(event)
    cross_frame["anchor"]["frame"] = "canonical_outputs"
    with pytest.raises(EventError, match="anchor"):
        validate_event(cross_frame, bundle, repository_root=REPO_ROOT)

    stale_evidence = deepcopy(event)
    stale_evidence["evidence"][0]["raw_sha256"] = "0" * 64
    with pytest.raises(EventError, match="evidence"):
        validate_event(stale_evidence, bundle, repository_root=REPO_ROOT)

    unrelated_evidence = deepcopy(event)
    unrelated_evidence["evidence"] = [
        {"path": "README.md", "raw_sha256": hashlib.sha256((REPO_ROOT / "README.md").read_bytes()).hexdigest()}
    ]
    with pytest.raises(EventError, match="evidence"):
        validate_event(unrelated_evidence, bundle, repository_root=REPO_ROOT)


@pytest.mark.requires_local_artifacts
def test_every_bundle_anchor_and_frame_is_authenticated() -> None:
    event, bundle = _live_event()
    selected = {
        (item["frame"], item["anchor_id"])
        for item in bundle["selected_anchors"]
    }
    canonical_anchors = bundle["frames"]["canonical_outputs"]["anchors"]
    nonselected = next(
        anchor
        for anchor in canonical_anchors
        if ("canonical_outputs", anchor["anchor_id"]) not in selected
    )

    false_hash_bundle = deepcopy(bundle)
    false_hash_anchor = next(
        anchor
        for anchor in false_hash_bundle["frames"]["canonical_outputs"]["anchors"]
        if anchor["anchor_id"] == nonselected["anchor_id"]
    )
    false_hash_anchor["artifact_sha256"] = "0" * 64
    false_hash_bundle["frames"]["canonical_outputs"]["anchors_sha256"] = _canonical_sha256(
        false_hash_bundle["frames"]["canonical_outputs"]["anchors"]
    )
    false_hash_event = deepcopy(event)
    _rebind_event(false_hash_event, false_hash_bundle)
    with pytest.raises(EventError, match="anchor|artifact|bytes"):
        validate_event(false_hash_event, false_hash_bundle, repository_root=REPO_ROOT)

    duplicate_bundle = deepcopy(bundle)
    duplicate_bundle["frames"]["canonical_outputs"]["anchors"][0]["anchor_id"] = (
        duplicate_bundle["frames"]["source_members"]["anchors"][0]["anchor_id"]
    )
    duplicate_bundle["frames"]["canonical_outputs"]["anchors_sha256"] = _canonical_sha256(
        duplicate_bundle["frames"]["canonical_outputs"]["anchors"]
    )
    duplicate_event = deepcopy(event)
    _rebind_event(duplicate_event, duplicate_bundle)
    with pytest.raises(EventError, match="duplicate|anchor|bundle"):
        validate_event(duplicate_event, duplicate_bundle, repository_root=REPO_ROOT)

    ambiguous_bundle = deepcopy(bundle)
    source_anchors = ambiguous_bundle["frames"]["source_members"]["anchors"]
    source_anchors[1]["source_id"] = source_anchors[0]["source_id"]
    ambiguous_bundle["frames"]["source_members"]["anchors_sha256"] = _canonical_sha256(
        source_anchors
    )
    ambiguous_event = deepcopy(event)
    _rebind_event(ambiguous_event, ambiguous_bundle)
    with pytest.raises(EventError, match="source|identity|ambiguous|duplicate"):
        validate_event(ambiguous_event, ambiguous_bundle, repository_root=REPO_ROOT)

    for frame_field, value in (("count", 999), ("anchors_sha256", "0" * 64)):
        false_frame_bundle = deepcopy(bundle)
        false_frame_bundle["frames"]["canonical_outputs"][frame_field] = value
        false_frame_event = deepcopy(event)
        _rebind_event(false_frame_event, false_frame_bundle)
        with pytest.raises(EventError, match="frame|bundle"):
            validate_event(false_frame_event, false_frame_bundle, repository_root=REPO_ROOT)


@pytest.mark.requires_local_artifacts
def test_aggregate_scope_snapshot_is_hash_bound_and_limited_is_explicit() -> None:
    _, bundle = _live_event()
    event = _event_for(bundle, subject_grain="work")
    assert validate_event(event, bundle, repository_root=REPO_ROOT) == event

    limited = deepcopy(event)
    limited["scope_snapshot"]["member_ids"] = limited["scope_snapshot"]["member_ids"][:1]
    limited["scope_snapshot"]["count"] = 1
    limited["scope_snapshot"]["member_set_sha256"] = _member_set_sha256(
        limited["scope_snapshot"]["member_ids"]
    )
    limited["evidence"] = _evidence_for_members(
        bundle, limited["scope_snapshot"]["member_ids"]
    )
    with pytest.raises(EventError, match="complete"):
        validate_event(limited, bundle, repository_root=REPO_ROOT)
    limited["scope_snapshot"]["coverage"] = "limited"
    assert validate_event(limited, bundle, repository_root=REPO_ROOT) == limited

    forged_hash = deepcopy(limited)
    forged_hash["scope_snapshot"]["member_set_sha256"] = "0" * 64
    with pytest.raises(EventError, match="member-set"):
        validate_event(forged_hash, bundle, repository_root=REPO_ROOT)

    missing = deepcopy(event)
    del missing["scope_snapshot"]
    with pytest.raises(EventError, match="scope snapshot"):
        validate_event(missing, bundle, repository_root=REPO_ROOT)


@pytest.mark.parametrize(
    ("event_kind", "disposition", "needs_prior"),
    [
        ("finding", "closed", False),
        ("disposition", "confirmed", True),
        ("review_closed", "closed", True),
        ("review_reopened", "reopened", True),
        ("invalidated", "invalidated", True),
    ],
)
@pytest.mark.requires_local_artifacts
def test_event_state_transitions_fail_closed(
    event_kind: str,
    disposition: str,
    needs_prior: bool,
) -> None:
    event, _ = _live_event()
    event["event_kind"] = event_kind
    event["disposition"] = disposition
    if needs_prior:
        with pytest.raises(EventError, match="prior"):
            serialize_event(event)
        event["prior_event_sha256"] = "a" * 64
        assert serialize_event(event).endswith(b"\n")
    else:
        with pytest.raises(EventError, match="disposition"):
            serialize_event(event)


def test_small_independent_bundle_event_is_read_only(small_event_bundle: tuple[Path, dict[str, object]]) -> None:
    root, bundle = small_event_bundle
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    event = _event_for(bundle, frame="canonical_outputs", subject_grain="canonical_record")

    assert validate_event(event, bundle, repository_root=root) == event
    after = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert before == after


@pytest.mark.requires_local_artifacts
def test_canonical_member_anchor_is_not_silently_interchanged() -> None:
    event, bundle = _live_event()
    canonical_event = _event_for(bundle, frame="canonical_outputs")
    assert validate_event(canonical_event, bundle, repository_root=REPO_ROOT) == canonical_event

    changed_frame = deepcopy(canonical_event)
    changed_frame["anchor"]["frame"] = "source_members"
    with pytest.raises(EventError, match="anchor"):
        validate_event(changed_frame, bundle, repository_root=REPO_ROOT)


def test_evidence_is_relevant_to_the_event_subject(
    small_event_bundle: tuple[Path, dict[str, object]],
) -> None:
    root, bundle = small_event_bundle
    event = _event_for(bundle, frame="canonical_outputs", index=0, subject_grain="canonical_record")
    other_anchor = bundle["frames"]["canonical_outputs"]["anchors"][1]
    event["evidence"] = [
        {
            "path": other_anchor["artifact_path"],
            "raw_sha256": other_anchor["artifact_sha256"],
        }
    ]
    with pytest.raises(EventError, match="evidence|subject|member"):
        validate_event(event, bundle, repository_root=root)

    dependency = bundle["dependencies"][0]
    event["evidence"] = [
        {"path": dependency["path"], "raw_sha256": dependency["raw_sha256"]}
    ]
    with pytest.raises(EventError, match="source|canonical|comparison|evidence"):
        validate_event(event, bundle, repository_root=root)

    source_only = deepcopy(event)
    source_anchor = bundle["frames"]["source_members"]["anchors"][0]
    source_only["evidence"] = [
        {
            "path": source_anchor["artifact_path"],
            "raw_sha256": source_anchor["artifact_sha256"],
        }
    ]
    with pytest.raises(EventError, match="source|canonical|comparison|evidence"):
        validate_event(source_only, bundle, repository_root=root)


@pytest.mark.parametrize(
    "dimension",
    ["renderer-only defect", "missing-check", "known-limitation"],
)
def test_noncomparison_dimensions_may_use_dependency_only_evidence(
    small_event_bundle: tuple[Path, dict[str, object]],
    dimension: str,
) -> None:
    root, bundle = small_event_bundle
    event = _event_for(bundle, frame="canonical_outputs", subject_grain="canonical_record")
    dependency = bundle["dependencies"][0]
    event["dimension"] = dimension
    event["evidence"] = [
        {"path": dependency["path"], "raw_sha256": dependency["raw_sha256"]}
    ]

    assert validate_event(event, bundle, repository_root=root) == event


def test_correction_receipt_binds_one_current_manifest_to_canonical_artifact(
    small_event_bundle: tuple[Path, dict[str, object]],
) -> None:
    root, bundle = small_event_bundle
    event = _event_for(bundle, frame="canonical_outputs", subject_grain="canonical_record")
    anchor = bundle["frames"]["canonical_outputs"]["anchors"][0]
    data_path = root / Path(anchor["artifact_path"])
    data_hash = hashlib.sha256(data_path.read_bytes()).hexdigest()
    manifest_path = root / "review/writer-manifests/test-run.json"
    parser_path = root / "build/parsers/bible_text_translations.py"
    manifest = {
        "schema_version": "3.0.0",
        "writer": "parser",
        "writer_version": (
            "build/parsers/bible_text_translations.py@sha256:"
            + hashlib.sha256(parser_path.read_bytes()).hexdigest()
        ),
        "writer_identity": "bible_text_translations_parser",
        "run_id": "test-run",
        "started_at": "2026-07-18T00:00:00+00:00",
        "data_paths": [anchor["artifact_path"]],
        "checksums": {
            anchor["artifact_path"]: {"before_sha256": "0" * 64, "after_sha256": data_hash}
        },
        "expected_delta_counts": {
            anchor["artifact_path"]: {"entries_changed": 1, "fields_changed": 1}
        },
        "allowed_field_paths": ["/data/*"],
        "partial_completion_policy": "all_or_nothing",
        "renames": [],
    }
    _write_json(manifest_path, manifest)
    event["event_kind"] = "correction"
    event["disposition"] = "corrected"
    manifest_bytes = manifest_path.read_bytes()
    event["correction_receipt"] = {
        "run_id": "test-run",
        "manifest_path": "review/writer-manifests/test-run.json",
        "manifest_raw_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "affected_data_path": anchor["artifact_path"],
    }
    assert validate_event(event, bundle, repository_root=root) == event

    forged_parser_hash_bundle = deepcopy(bundle)
    forged_parser_dependency = next(
        dependency
        for dependency in forged_parser_hash_bundle["dependencies"]
        if dependency["role"] == "parser"
    )
    forged_parser_dependency["raw_sha256"] = "0" * 64
    _rebind_bundle_seed(forged_parser_hash_bundle)
    assert serialize_bundle(forged_parser_hash_bundle).endswith(b"\n")
    forged_parser_hash_event = deepcopy(event)
    _rebind_event(forged_parser_hash_event, forged_parser_hash_bundle)
    with pytest.raises(EventError) as forged_parser_error:
        validate_event(
            forged_parser_hash_event,
            forged_parser_hash_bundle,
            repository_root=root,
        )
    assert str(forged_parser_error.value) == (
        "bundle parser dependency hash does not match current bytes"
    )

    wrong_registered_manifest = deepcopy(manifest)
    wrong_registered_manifest["writer_identity"] = "adam_clarke_parser"
    _write_json(manifest_path, wrong_registered_manifest)
    wrong_registered = deepcopy(event)
    wrong_registered["correction_receipt"]["manifest_raw_sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    with pytest.raises(EventError) as wrong_registered_error:
        validate_event(wrong_registered, bundle, repository_root=root)
    assert str(wrong_registered_error.value) == (
        "writer manifest is legacy-untrusted: writer identity is outside the bounded "
        "correction authority: 'adam_clarke_parser'"
    )

    substituted_bundle = deepcopy(bundle)
    substituted_parser = next(
        dependency
        for dependency in substituted_bundle["dependencies"]
        if dependency["role"] == "parser"
    )
    other_parser_path = root / "build/parsers/gutenberg_evangelical.py"
    substituted_parser["path"] = "build/parsers/gutenberg_evangelical.py"
    substituted_parser["raw_sha256"] = hashlib.sha256(other_parser_path.read_bytes()).hexdigest()
    substituted_bundle["dependencies"].sort(
        key=lambda dependency: (dependency["role"], dependency["path"])
    )
    _rebind_bundle_seed(substituted_bundle)
    assert serialize_bundle(substituted_bundle).endswith(b"\n")
    substituted_manifest = deepcopy(manifest)
    substituted_manifest["writer_identity"] = "gutenberg_evangelical_parser"
    substituted_manifest["writer_version"] = (
        "build/parsers/gutenberg_evangelical.py@sha256:"
        + substituted_parser["raw_sha256"]
    )
    _write_json(manifest_path, substituted_manifest)
    substituted = deepcopy(event)
    substituted["correction_receipt"]["manifest_raw_sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    _rebind_event(substituted, substituted_bundle)
    with pytest.raises(EventError) as substituted_error:
        validate_event(substituted, substituted_bundle, repository_root=root)
    assert str(substituted_error.value) == (
        "bundle parser dependency does not reconcile with its ownership-regenerated inventory"
    )

    _write_json(manifest_path, manifest)

    stale_sibling_manifest = deepcopy(manifest)
    sibling_anchor = bundle["frames"]["canonical_outputs"]["anchors"][1]
    sibling_path = sibling_anchor["artifact_path"]
    stale_sibling_manifest["data_paths"].append(sibling_path)
    stale_sibling_manifest["checksums"][sibling_path] = {
        "before_sha256": "1" * 64,
        "after_sha256": "0" * 64,
    }
    stale_sibling_manifest["expected_delta_counts"][sibling_path] = {
        "entries_changed": 1,
        "fields_changed": 1,
    }
    _write_json(manifest_path, stale_sibling_manifest)
    stale_sibling = deepcopy(event)
    stale_sibling["correction_receipt"]["manifest_raw_sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    with pytest.raises(EventError, match="legacy-untrusted|after checksum|manifest"):
        validate_event(stale_sibling, bundle, repository_root=root)

    source_mismatch_manifest = deepcopy(manifest)
    source_mismatch_manifest["writer_version"] = (
        "build/parsers/gutenberg_evangelical.py@sha256:"
        + hashlib.sha256(other_parser_path.read_bytes()).hexdigest()
    )
    _write_json(manifest_path, source_mismatch_manifest)
    source_mismatch = deepcopy(event)
    source_mismatch["correction_receipt"]["manifest_raw_sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    with pytest.raises(EventError, match="legacy-untrusted|authorized producer source|manifest"):
        validate_event(source_mismatch, bundle, repository_root=root)

    unregistered_manifest = deepcopy(manifest)
    unregistered_manifest["writer_identity"] = "not-registered"
    _write_json(manifest_path, unregistered_manifest)
    unregistered = deepcopy(event)
    unregistered["correction_receipt"]["manifest_raw_sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    with pytest.raises(EventError, match="registered|writer identity"):
        validate_event(unregistered, bundle, repository_root=root)

    producer_mismatch_manifest = deepcopy(manifest)
    producer_mismatch_manifest["writer"] = "tool"
    _write_json(manifest_path, producer_mismatch_manifest)
    producer_mismatch = deepcopy(event)
    producer_mismatch["correction_receipt"]["manifest_raw_sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    with pytest.raises(EventError, match="producer|writer"):
        validate_event(producer_mismatch, bundle, repository_root=root)

    no_op_manifest = deepcopy(manifest)
    no_op_manifest["checksums"][anchor["artifact_path"]]["before_sha256"] = data_hash
    _write_json(manifest_path, no_op_manifest)
    no_op = deepcopy(event)
    no_op["correction_receipt"]["manifest_raw_sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    with pytest.raises(EventError, match="change|before|after|no-op"):
        validate_event(no_op, bundle, repository_root=root)

    zero_delta_manifest = deepcopy(manifest)
    zero_delta_manifest["expected_delta_counts"][anchor["artifact_path"]] = {
        "entries_changed": 0,
        "fields_changed": 0,
    }
    _write_json(manifest_path, zero_delta_manifest)
    zero_delta = deepcopy(event)
    zero_delta["correction_receipt"]["manifest_raw_sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    with pytest.raises(EventError, match="delta|change"):
        validate_event(zero_delta, bundle, repository_root=root)

    _write_json(manifest_path, manifest)
    mismatched_path = root / "review/writer-manifests/not-the-run.json"
    mismatched_path.write_bytes(manifest_bytes)
    mismatched_name = deepcopy(event)
    mismatched_name["correction_receipt"]["manifest_path"] = (
        "review/writer-manifests/not-the-run.json"
    )
    with pytest.raises(EventError, match="run_id|manifest path|filename"):
        validate_event(mismatched_name, bundle, repository_root=root)

    unsafe_run = deepcopy(event)
    unsafe_run["correction_receipt"]["run_id"] = "nested/test-run"
    with pytest.raises(EventError, match="run_id|manifest path"):
        validate_event(unsafe_run, bundle, repository_root=root)

    unrelated = deepcopy(event)
    unrelated["correction_receipt"]["affected_data_path"] = "data/bible-text/asv/other.json"
    with pytest.raises(EventError, match="unrelated|declared|affected"):
        validate_event(unrelated, bundle, repository_root=root)

    stale_manifest = deepcopy(event)
    stale_manifest["correction_receipt"]["manifest_raw_sha256"] = "0" * 64
    with pytest.raises(EventError, match="manifest"):
        validate_event(stale_manifest, bundle, repository_root=root)

    both_null_manifest = deepcopy(manifest)
    both_null_manifest["checksums"][anchor["artifact_path"]] = {
        "before_sha256": None,
        "after_sha256": None,
    }
    _write_json(manifest_path, both_null_manifest)
    both_null = deepcopy(event)
    both_null["correction_receipt"]["manifest_raw_sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    with pytest.raises(EventError, match="schema-valid|validate|manifest"):
        validate_event(both_null, bundle, repository_root=root)

    _write_json(manifest_path, manifest)
    assessor_path = root / "cvw_phase1a/contracts.py"
    assessor_bytes = assessor_path.read_bytes()
    assessor_path.write_bytes(assessor_bytes + b"\n")
    with pytest.raises(EventError, match="assessor|executing|authenticated"):
        validate_event(event, bundle, repository_root=root)
    assessor_path.write_bytes(assessor_bytes)

    authority_path = root / "cvw_phase1b/event.py"
    authority_bytes = authority_path.read_bytes()
    authority_path.write_bytes(authority_bytes + b"\n")
    with pytest.raises(EventError, match="authority|executing|authenticated"):
        validate_event(event, bundle, repository_root=root)
    authority_path.write_bytes(authority_bytes)

    weakened_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
    }
    _write_json(root / "schemas/v1/writer_manifest.schema.json", weakened_schema)
    with pytest.raises(EventError, match="schema|executing|bytes|authoritative"):
        validate_event(event, bundle, repository_root=root)


def test_single_file_correction_binds_exact_authenticated_parser_source(
    small_single_file_event_bundle: tuple[Path, dict[str, object]],
) -> None:
    root, bundle = small_single_file_event_bundle
    event = _event_for(
        bundle,
        frame="canonical_outputs",
        subject_grain="canonical_record",
    )
    anchor = bundle["frames"]["canonical_outputs"]["anchors"][0]
    parser_dependency = next(
        dependency for dependency in bundle["dependencies"] if dependency["role"] == "parser"
    )
    manifest_path = root / "review/writer-manifests/tiny-single-file-run.json"
    manifest = {
        "schema_version": "3.0.0",
        "writer": "parser",
        "writer_version": (
            f"{parser_dependency['path']}@sha256:{parser_dependency['raw_sha256']}"
        ),
        "writer_identity": "gutenberg_evangelical_parser",
        "run_id": "tiny-single-file-run",
        "started_at": "2026-07-18T00:00:00+00:00",
        "data_paths": [anchor["artifact_path"]],
        "checksums": {
            anchor["artifact_path"]: {
                "before_sha256": hashlib.sha256(b"prior synthetic canonical bytes\n").hexdigest(),
                "after_sha256": anchor["artifact_sha256"],
            }
        },
        "expected_delta_counts": {
            anchor["artifact_path"]: {"entries_changed": 1, "fields_changed": 1}
        },
        "allowed_field_paths": ["/data/*"],
        "partial_completion_policy": "all_or_nothing",
        "renames": [],
    }
    _write_json(manifest_path, manifest)
    event["event_kind"] = "correction"
    event["disposition"] = "corrected"
    event["correction_receipt"] = {
        "run_id": manifest["run_id"],
        "manifest_path": manifest_path.relative_to(root).as_posix(),
        "manifest_raw_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "affected_data_path": anchor["artifact_path"],
    }

    assert validate_event(event, bundle, repository_root=root) == event


@pytest.mark.skipif(
    not LIVE_SPURGEON_SOURCE.is_file(),
    reason="VACUOUS: ignored Spurgeon raw witness is unavailable",
)
def test_live_spurgeon_correction_binds_single_file_ownership_and_exact_artifact() -> None:
    bundle = generate_bundle(
        REPO_ROOT,
        LIVE_SPURGEON_OWNERSHIP,
        LIVE_SPURGEON_POLICY,
    )
    event = _event_for(
        bundle,
        frame="canonical_outputs",
        subject_grain="canonical_record",
    )
    anchor = bundle["frames"]["canonical_outputs"]["anchors"][0]
    manifest = json.loads(LIVE_SPURGEON_WRITER_MANIFEST.read_bytes())
    manifest_path = LIVE_SPURGEON_WRITER_MANIFEST.relative_to(REPO_ROOT).as_posix()

    assert {
        dependency["role"]
        for dependency in bundle["dependencies"]
        if dependency["role"].startswith("ownership_adapter:")
    } == {"ownership_adapter:single_file"}
    assert anchor["artifact_path"] == "data/structured-text/spurgeon-all-of-grace.json"
    assert manifest["writer_identity"] == "gutenberg_inline_markup_parser"
    assert manifest["checksums"][anchor["artifact_path"]]["after_sha256"] == hashlib.sha256(
        (REPO_ROOT / anchor["artifact_path"]).read_bytes()
    ).hexdigest()
    assert validate_event(event, bundle, repository_root=REPO_ROOT) == event

    wrong_adapter_bundle = deepcopy(bundle)
    adapter_dependency = next(
        dependency
        for dependency in wrong_adapter_bundle["dependencies"]
        if dependency["role"].startswith("ownership_adapter:")
    )
    adapter_dependency["role"] = "ownership_adapter:bible_collection"
    wrong_adapter_bundle["sampling"]["seed"] = _canonical_sha256(
        {
            "inventory_binding": wrong_adapter_bundle["inventory_binding"],
            "dependencies": sorted(
                wrong_adapter_bundle["dependencies"],
                key=lambda dependency: (dependency["role"], dependency["path"]),
            ),
        }
    )
    wrong_adapter_event = deepcopy(event)
    _rebind_event(wrong_adapter_event, wrong_adapter_bundle)
    with pytest.raises(EventError, match="ownership adapter|source identity"):
        validate_event(wrong_adapter_event, wrong_adapter_bundle, repository_root=REPO_ROOT)

    event["event_kind"] = "correction"
    event["disposition"] = "corrected"
    event["correction_receipt"] = {
        "run_id": manifest["run_id"],
        "manifest_path": manifest_path,
        "manifest_raw_sha256": hashlib.sha256(
            LIVE_SPURGEON_WRITER_MANIFEST.read_bytes()
        ).hexdigest(),
        "affected_data_path": anchor["artifact_path"],
    }
    with pytest.raises(EventError, match="legacy-untrusted|writer manifest"):
        validate_event(event, bundle, repository_root=REPO_ROOT)

    other_manifest_path = "data/structured-text/spurgeon-lectures-to-my-students.json"
    assert other_manifest_path in manifest["data_paths"]
    assert other_manifest_path in manifest["checksums"]
    other_manifest_artifact = deepcopy(event)
    other_manifest_artifact["correction_receipt"]["affected_data_path"] = other_manifest_path
    with pytest.raises(EventError, match="unrelated|canonical artifact"):
        validate_event(other_manifest_artifact, bundle, repository_root=REPO_ROOT)
