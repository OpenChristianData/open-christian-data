"""Public seam tests for the bounded status projection."""

from __future__ import annotations

import json
import hashlib
from copy import deepcopy
import shutil
from pathlib import Path

import pytest

from cvw_phase1b import (
    StatusError,
    generate_bundle,
    generate_status,
    serialize_bundle,
    serialize_status,
)
from tests.test_cvw_phase1b_inventory import (
    _copy_parser_dependency_closure,
    _write_descriptor_catalog_identity,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_OWNERSHIP = REPO_ROOT / "cvw_phase1b" / "fixtures" / "asv_ownership.json"
LIVE_POLICY = REPO_ROOT / "cvw_phase1b" / "fixtures" / "asv_policy.json"
LIVE_SINGLE_FILE_OWNERSHIP = REPO_ROOT / "cvw_phase1b" / "fixtures" / "spurgeon_ownership.json"
LIVE_SINGLE_FILE_POLICY = REPO_ROOT / "cvw_phase1b" / "fixtures" / "spurgeon_policy.json"
LIVE_SINGLE_FILE_SOURCE = REPO_ROOT / "raw/ia/spurgeon_all_of_grace.txt"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )


def make_independent_repository(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "independent-status-repository"
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
        "cvw_phase1b/ownership.py",
        "build/parsers/bible_text_translations.py",
        "build/tools/count_dataset_records.py",
        "schemas/v1/verification_inventory.schema.json",
        "schemas/v1/verification_bundle.schema.json",
        "cvw_phase1b/fixtures/asv_policy.json",
    ):
        destination = root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative_path, destination)
    _copy_parser_dependency_closure(root, "build/parsers/bible_text_translations.py")
    ownership = root / "cvw_phase1b/fixtures/asv_ownership.json"
    descriptor = {
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
    _write_descriptor_catalog_identity(root, descriptor)
    _write_json(ownership, descriptor)
    return root, ownership, root / "cvw_phase1b/fixtures/asv_policy.json"


@pytest.fixture
def independent_repository(tmp_path: Path) -> tuple[Path, Path, Path]:
    return make_independent_repository(tmp_path)


@pytest.fixture
def composite_repository(tmp_path: Path) -> tuple[Path, Path, Path]:
    root, ownership, policy = make_independent_repository(tmp_path)
    source = json.loads((root / "raw/bible_databases/formats/json/ASV.json").read_bytes())
    source["books"].append(
        {
            "name": "Leviticus",
            "chapters": [{"chapter": 1, "verses": [{"verse": 1, "text": "And the LORD called"}]}],
        }
    )
    source["books"].append(
        {
            "name": "Numbers",
            "chapters": [{"chapter": 1, "verses": [{"verse": 1, "text": "And the LORD spake"}]}],
        }
    )
    source_path = root / "raw/bible_databases/formats/json/ASV.json"
    _write_json(source_path, source)
    _write_json(
        root / "data/bible-text/asv/leviticus.json",
        {"meta": {"id": "asv", "scope": {"book": "Leviticus"}}, "data": []},
    )
    _write_json(
        root / "data/bible-text/asv/numbers.json",
        {"meta": {"id": "asv", "scope": {"book": "Numbers"}}, "data": []},
    )
    catalog = (root / "docs/WORK_CATALOG.md").read_text(encoding="utf-8").replace("| 2 | 0 |", "| 4 | 0 |")
    (root / "docs/WORK_CATALOG.md").write_text(catalog, encoding="utf-8")
    ownership_payload = json.loads(ownership.read_bytes())
    ownership_payload["source_artifact"]["expected_raw_sha256"] = hashlib.sha256(
        source_path.read_bytes()
    ).hexdigest()
    ownership_payload["catalog"]["expected_file_count"] = 4
    _write_descriptor_catalog_identity(root, ownership_payload)
    _write_json(ownership, ownership_payload)
    return root, ownership, policy


@pytest.mark.requires_local_artifacts
def test_live_bundle_reports_bounded_current_projection() -> None:
    report = generate_status(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)

    assert report["identity"] == "verification-status-v1"
    assert report["scope"] == {
        "coverage": "bounded",
        "description": "Bounded ASV verification bundle; not corpus-wide coverage.",
        "work_id": "asv",
        "rendering_id": "asv:scrollmapper-json",
    }
    assert report["counts"] == {
        "source_members": 66,
        "canonical_outputs": 66,
        "selected_anchors": {
            "source_members": 3,
            "canonical_outputs": 3,
        },
    }
    assert report["publication"]["status"] == "not_applicable"
    assert report["publication"]["reason"] == (
        "Publication projection and export generation are deferred for this bounded ASV trial."
    )
    assert report["comparison"] == {"state": "UNCOMPARED", "changes": []}


@pytest.mark.skipif(
    not LIVE_SINGLE_FILE_SOURCE.is_file(),
    reason="ignored Spurgeon raw witness is unavailable",
)
def test_live_single_file_status_reports_one_uncompared_bounded_work() -> None:
    report = generate_status(
        REPO_ROOT, LIVE_SINGLE_FILE_OWNERSHIP, LIVE_SINGLE_FILE_POLICY
    )

    assert report["scope"]["work_id"] == "spurgeon-all-of-grace"
    assert report["scope"]["description"] == (
        "Bounded verification bundle; not corpus-wide coverage."
    )
    assert report["counts"] == {
        "source_members": 1,
        "canonical_outputs": 1,
        "selected_anchors": {"source_members": 1, "canonical_outputs": 1},
    }
    assert report["comparison"] == {"state": "UNCOMPARED", "changes": []}
    assert report["publication"]["status"] == "not_applicable"
    assert report["publication"]["reason"] == (
        "Publication projection and export generation are deferred for this bounded verification trial."
    )
    assert serialize_status(report) == serialize_status(
        generate_status(REPO_ROOT, LIVE_SINGLE_FILE_OWNERSHIP, LIVE_SINGLE_FILE_POLICY)
    )


@pytest.mark.requires_local_artifacts
def test_status_serialization_is_canonical_and_strict() -> None:
    report = generate_status(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)

    serialized = serialize_status(report)

    expected = (
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    assert serialized == expected
    assert serialized.endswith(b"\n")
    assert not serialized.endswith(b"\n\n")

    nonfinite = dict(report)
    nonfinite["counts"] = {"source_members": float("nan")}
    with pytest.raises(StatusError, match="non-finite|counts"):
        serialize_status(nonfinite)

    unknown_state = json.loads(serialized)
    unknown_state["comparison"]["state"] = "BROKEN"
    with pytest.raises(StatusError, match="state"):
        serialize_status(unknown_state)

    duplicate_changes = json.loads(serialized)
    duplicate_changes["comparison"] = {
        "state": "STALE",
        "changes": [
            {
                "category": "dependency",
                "kind": "hash_changed",
                "key": "policy",
                "before": "0" * 64,
                "after": "1" * 64,
            }
        ] * 2,
    }
    with pytest.raises(StatusError, match="duplicates"):
        serialize_status(duplicate_changes)

    unordered_changes = json.loads(serialized)
    unordered_changes["comparison"] = {
        "state": "STALE",
        "changes": [
            {
                "category": "policy",
                "kind": "field_changed",
                "key": "sample_size",
                "before": 3,
                "after": 4,
            },
            {
                "category": "dependency",
                "kind": "hash_changed",
                "key": "policy",
                "before": "0" * 64,
                "after": "1" * 64,
            },
        ],
    }
    with pytest.raises(StatusError, match="canonically ordered"):
        serialize_status(unordered_changes)


def test_identical_authenticated_previous_bundle_is_current(
    independent_repository: tuple[Path, Path, Path],
) -> None:
    root, ownership, policy = independent_repository
    bundle = generate_bundle(root, ownership, policy)
    previous_path = root / "review/previous-bundle.json"
    previous_path.parent.mkdir(parents=True, exist_ok=True)
    previous_path.write_bytes(serialize_bundle(bundle))

    report = generate_status(
        root,
        ownership,
        policy,
        previous_path,
    )

    assert report["comparison"] == {"state": "CURRENT", "changes": []}


def test_changed_source_bytes_report_concrete_stale_changes(
    independent_repository: tuple[Path, Path, Path],
) -> None:
    root, ownership, policy = independent_repository
    previous_path = root / "review/previous-bundle.json"
    previous_path.parent.mkdir(parents=True, exist_ok=True)
    previous_path.write_bytes(serialize_bundle(generate_bundle(root, ownership, policy)))

    source_path = root / "raw/bible_databases/formats/json/ASV.json"
    source_path.write_bytes(source_path.read_bytes() + b"\n")
    ownership_payload = json.loads(ownership.read_bytes())
    ownership_payload["source_artifact"]["expected_raw_sha256"] = hashlib.sha256(
        source_path.read_bytes()
    ).hexdigest()
    _write_json(ownership, ownership_payload)

    report = generate_status(root, ownership, policy, previous_path)

    assert report["comparison"]["state"] == "STALE"
    changes = report["comparison"]["changes"]
    assert any(
        change["category"] == "source_artifact"
        and change["kind"] == "hash_changed"
        and change["key"] == "source_artifact"
        for change in changes
    )
    assert all(change["category"] != "unclassified" for change in changes)


def _snapshot(root: Path, ownership: Path, policy: Path) -> Path:
    path = root / "review/previous-bundle.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(serialize_bundle(generate_bundle(root, ownership, policy)))
    return path


def _sampling_seed(bundle: dict[str, object]) -> str:
    manifest = {
        "inventory_binding": bundle["inventory_binding"],
        "dependencies": sorted(
            bundle["dependencies"], key=lambda item: (item["role"], item["path"])
        ),
    }
    data = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _exact_selections(bundle: dict[str, object]) -> list[dict[str, str]]:
    seed = _sampling_seed(bundle)
    sample_size = bundle["policy"]["sample_size"]
    selections: list[dict[str, str]] = []
    for frame_name in ("source_members", "canonical_outputs"):
        anchors = bundle["frames"][frame_name]["anchors"]
        selections.append(
            {
                "frame": frame_name,
                "anchor_id": anchors[0]["anchor_id"],
                "reason": "mandatory-first",
            }
        )
        selections.append(
            {
                "frame": frame_name,
                "anchor_id": anchors[-1]["anchor_id"],
                "reason": "mandatory-last",
            }
        )
        remaining = sorted(
            anchors[1:-1],
            key=lambda anchor: hashlib.sha256(
                f"{seed}\0{frame_name}\0{anchor['anchor_id']}".encode("utf-8")
            ).hexdigest(),
        )
        wanted = min(max(sample_size - 2, 1), len(remaining)) if remaining else 0
        selections.extend(
            {
                "frame": frame_name,
                "anchor_id": anchor["anchor_id"],
                "reason": "hash-seeded",
            }
            for anchor in remaining[:wanted]
        )
    return selections


def _exact_artifacts(bundle: dict[str, object]) -> list[dict[str, str]]:
    selected_output_ids = {
        selection["anchor_id"]
        for selection in bundle["selected_anchors"]
        if selection["frame"] == "canonical_outputs"
    }
    output_anchors = [
        anchor
        for anchor in bundle["frames"]["canonical_outputs"]["anchors"]
        if anchor["anchor_id"] in selected_output_ids
    ]
    source_artifact = next(
        artifact for artifact in bundle["artifacts"] if artifact["grain"] == "source_artifact"
    )
    return [
        deepcopy(source_artifact),
        *[
            {
                "grain": "canonical_artifact",
                "member_id": anchor["member_id"],
                "path": anchor["artifact_path"],
                "raw_sha256": anchor["artifact_sha256"],
                "rendering_id": bundle["scope"]["rendering_id"],
                "work_id": bundle["scope"]["work_id"],
            }
            for anchor in sorted(output_anchors, key=lambda item: item["member_id"])
        ],
    ]


def test_transitive_parser_helper_hash_change_marks_bundle_stale(
    independent_repository: tuple[Path, Path, Path],
) -> None:
    root, ownership, policy = independent_repository
    current_bundle = generate_bundle(root, ownership, policy)
    previous_bundle = deepcopy(current_bundle)
    helper_role = "transitive_code:build/parsers/bsb_bible_text.py"
    helper = next(
        dependency
        for dependency in previous_bundle["dependencies"]
        if dependency["role"] == helper_role
    )
    helper["raw_sha256"] = "0" * 64
    previous_bundle["sampling"]["seed"] = _sampling_seed(previous_bundle)
    previous_bundle["selected_anchors"] = _exact_selections(previous_bundle)
    previous_bundle["artifacts"] = _exact_artifacts(previous_bundle)
    previous_path = root / "review/previous-bundle.json"
    previous_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(previous_path, previous_bundle)

    report = generate_status(root, ownership, policy, previous_path)

    assert report["comparison"]["state"] == "STALE"
    assert any(
        change["category"] == "dependency"
        and change["kind"] == "hash_changed"
        and change["key"] == helper_role
        for change in report["comparison"]["changes"]
    )


def test_changed_canonical_bytes_report_canonical_artifact_and_anchor_changes(
    independent_repository: tuple[Path, Path, Path],
) -> None:
    root, ownership, policy = independent_repository
    previous_path = _snapshot(root, ownership, policy)

    canonical_path = root / "data/bible-text/asv/genesis.json"
    canonical_path.write_bytes(canonical_path.read_bytes() + b"\n")

    report = generate_status(root, ownership, policy, previous_path)

    assert report["comparison"]["state"] == "STALE"
    changes = report["comparison"]["changes"]
    assert any(
        change["category"] == "canonical_artifact"
        and change["kind"] == "hash_changed"
        for change in changes
    )
    assert any(
        change["category"] == "canonical_anchor"
        and change["kind"] == "hash_changed"
        for change in changes
    )
    assert all(change["category"] != "unclassified" for change in changes)


def test_composite_valid_snapshot_explains_every_changed_top_level_field(
    composite_repository: tuple[Path, Path, Path],
) -> None:
    root, ownership, policy = composite_repository
    current_bundle = generate_bundle(root, ownership, policy)
    current_policy_hash = next(
        dependency["raw_sha256"]
        for dependency in current_bundle["dependencies"]
        if dependency["role"] == "policy"
    )
    historical_bundle: dict[str, object] | None = None
    for candidate_index in range(64):
        candidate = deepcopy(current_bundle)
        candidate_policy_hash = hashlib.sha256(
            f"historical-policy-dependency-{candidate_index}".encode("utf-8")
        ).hexdigest()
        policy_dependency = next(
            dependency
            for dependency in candidate["dependencies"]
            if dependency["role"] == "policy"
        )
        policy_dependency["raw_sha256"] = candidate_policy_hash
        candidate["sampling"]["seed"] = _sampling_seed(candidate)
        candidate["selected_anchors"] = _exact_selections(candidate)
        candidate["artifacts"] = _exact_artifacts(candidate)
        if (
            candidate["selected_anchors"] != current_bundle["selected_anchors"]
            and candidate["artifacts"] != current_bundle["artifacts"]
        ):
            historical_bundle = candidate
            break
    assert historical_bundle is not None, (
        "bounded historical dependency-hash sequence did not change exact selections"
    )
    assert next(
        dependency["raw_sha256"]
        for dependency in historical_bundle["dependencies"]
        if dependency["role"] == "policy"
    ) != current_policy_hash
    assert historical_bundle["sampling"]["seed"] != current_bundle["sampling"]["seed"]
    assert historical_bundle["selected_anchors"] != current_bundle["selected_anchors"]
    assert historical_bundle["artifacts"] != current_bundle["artifacts"]
    previous_bundle = historical_bundle
    previous_bundle["machine_checks"] = list(reversed(previous_bundle["machine_checks"]))
    previous_bundle["policy"]["machine_checks"] = list(previous_bundle["machine_checks"])
    previous_bundle["publication_projection"]["reason"] = "Historical bounded projection."
    assert previous_bundle["machine_checks"] != current_bundle["machine_checks"]
    assert previous_bundle["policy"]["machine_checks"] == previous_bundle["machine_checks"]
    assert (
        previous_bundle["publication_projection"]["reason"]
        != current_bundle["publication_projection"]["reason"]
    )
    previous_path = root / "review/previous-bundle.json"
    previous_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(previous_path, previous_bundle)

    report = generate_status(root, ownership, policy, previous_path)

    assert report["comparison"]["state"] == "STALE"
    changes = report["comparison"]["changes"]
    assert ("dependency", "hash_changed", "policy") in {
        (change["category"], change["kind"], change["key"]) for change in changes
    }
    assert ("publication", "field_changed", "reason") in {
        (change["category"], change["kind"], change["key"]) for change in changes
    }
    assert {
        (change["category"], change["kind"], change["key"])
        for change in changes
    } >= {
        ("sampling", "changed", "sampling"),
        ("selected_anchors", "changed", "selected_anchors"),
        ("machine_checks", "changed", "machine_checks"),
    }


def test_changed_policy_reports_policy_and_dependency_changes(
    independent_repository: tuple[Path, Path, Path],
) -> None:
    root, ownership, policy = independent_repository
    previous_path = _snapshot(root, ownership, policy)
    policy_payload = json.loads(policy.read_bytes())
    policy_payload["sample_size"] = 4
    _write_json(policy, policy_payload)

    report = generate_status(root, ownership, policy, previous_path)

    changes = report["comparison"]["changes"]
    assert any(
        change["category"] == "policy"
        and change["kind"] == "field_changed"
        and change["key"] == "sample_size"
        for change in changes
    )
    assert any(
        change["category"] == "dependency"
        and change["kind"] == "hash_changed"
        and change["key"] == "policy"
        for change in changes
    )
    assert all(change["category"] != "unclassified" for change in changes)


def test_old_dependency_hashes_are_accepted_and_explained(
    independent_repository: tuple[Path, Path, Path],
) -> None:
    root, ownership, policy = independent_repository
    current_bundle = generate_bundle(root, ownership, policy)
    previous_bundle = deepcopy(current_bundle)
    policy_dependency = next(
        dependency for dependency in previous_bundle["dependencies"] if dependency["role"] == "policy"
    )
    policy_dependency["raw_sha256"] = "0" * 64
    previous_bundle["sampling"]["seed"] = _sampling_seed(previous_bundle)
    previous_path = root / "review/previous-bundle.json"
    previous_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(previous_path, previous_bundle)

    report = generate_status(root, ownership, policy, previous_path)

    assert report["comparison"]["state"] == "STALE"
    assert any(
        change["category"] == "dependency"
        and change["kind"] == "hash_changed"
        and change["key"] == "policy"
        for change in report["comparison"]["changes"]
    )


def test_rehashed_previous_bundle_with_forged_source_identity_is_rejected(
    independent_repository: tuple[Path, Path, Path],
) -> None:
    root, ownership, policy = independent_repository
    previous_bundle = generate_bundle(root, ownership, policy)
    source_anchor = previous_bundle["frames"]["source_members"]["anchors"][0]
    source_anchor["source_id"] = "Forged Source Identity"
    previous_bundle["frames"]["source_members"]["anchors_sha256"] = hashlib.sha256(
        (
            json.dumps(
                previous_bundle["frames"]["source_members"]["anchors"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    ).hexdigest()
    previous_path = root / "review/previous-bundle.json"
    previous_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(previous_path, previous_bundle)

    with pytest.raises(StatusError, match="previous bundle|source identity"):
        generate_status(root, ownership, policy, previous_path)


def test_rehashed_previous_bundle_with_forged_non_boundary_source_hash_is_rejected(
    composite_repository: tuple[Path, Path, Path],
) -> None:
    root, ownership, policy = composite_repository
    previous_bundle = generate_bundle(root, ownership, policy)
    source_anchor = previous_bundle["frames"]["source_members"]["anchors"][1]
    source_anchor["artifact_sha256"] = "0" * 64
    previous_bundle["frames"]["source_members"]["anchors_sha256"] = hashlib.sha256(
        (
            json.dumps(
                previous_bundle["frames"]["source_members"]["anchors"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    ).hexdigest()
    previous_path = root / "review/previous-bundle.json"
    previous_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(previous_path, previous_bundle)

    with pytest.raises(StatusError, match="previous bundle|source witness"):
        generate_status(root, ownership, policy, previous_path)


def test_dependency_addition_removal_and_ownership_changes_are_classified(
    independent_repository: tuple[Path, Path, Path],
) -> None:
    root, ownership, policy = independent_repository
    previous_bundle = generate_bundle(root, ownership, policy)
    for dependency in previous_bundle["dependencies"]:
        if dependency["role"] == "policy":
            dependency["role"] = "old-policy"
            dependency["path"] = "review/old-policy.json"
        elif dependency["role"] == "bundle_generator":
            dependency["path"] = "review/old-bundle-generator.py"
            dependency["raw_sha256"] = "0" * 64
    previous_bundle["dependencies"] = sorted(
        previous_bundle["dependencies"], key=lambda item: (item["role"], item["path"])
    )
    previous_bundle["sampling"]["seed"] = _sampling_seed(previous_bundle)
    previous_path = root / "review/previous-bundle.json"
    previous_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(previous_path, previous_bundle)

    report = generate_status(root, ownership, policy, previous_path)

    changes = report["comparison"]["changes"]
    assert {(
        change["kind"], change["key"]
    ) for change in changes if change["category"] == "dependency"} >= {
        ("added", "policy"),
        ("removed", "old-policy"),
        ("ownership_changed", "bundle_generator"),
        ("hash_changed", "bundle_generator"),
    }


def test_publication_projection_reason_change_is_reported(
    independent_repository: tuple[Path, Path, Path],
) -> None:
    root, ownership, policy = independent_repository
    previous_path = _snapshot(root, ownership, policy)
    previous_bundle = json.loads(previous_path.read_bytes())
    previous_bundle["publication_projection"]["reason"] = "Historical bounded projection."
    _write_json(previous_path, previous_bundle)

    report = generate_status(root, ownership, policy, previous_path)

    assert report["comparison"]["changes"] == [
        {
            "category": "publication",
            "kind": "field_changed",
            "key": "reason",
            "before": "Historical bounded projection.",
            "after": "Publication projection and export generation are deferred for this bounded ASV trial.",
        }
    ]


def test_malformed_duplicate_key_and_forged_previous_bundles_fail_closed(
    independent_repository: tuple[Path, Path, Path],
) -> None:
    root, ownership, policy = independent_repository
    previous_path = root / "review/previous-bundle.json"
    previous_path.parent.mkdir(parents=True, exist_ok=True)

    previous_path.write_bytes(b'{"identity":"verification-bundle-v1","identity":"forged"}\n')
    with pytest.raises(StatusError, match="duplicate|previous bundle"):
        generate_status(root, ownership, policy, previous_path)

    previous_path.write_bytes(b'{"identity":NaN}\n')
    with pytest.raises(StatusError, match="non-finite|previous bundle"):
        generate_status(root, ownership, policy, previous_path)

    forged = generate_bundle(root, ownership, policy)
    forged["frames"]["source_members"]["count"] = 999
    _write_json(previous_path, forged)
    with pytest.raises(StatusError, match="previous bundle|frame count"):
        generate_status(root, ownership, policy, previous_path)
