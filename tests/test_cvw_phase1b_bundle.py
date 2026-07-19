"""Public seam tests for the bounded verification bundle."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Callable

import pytest

from cvw_phase1b import bundle as bundle_module
from cvw_phase1b import ownership
from cvw_phase1b import (
    BundleError,
    generate_bundle,
    generate_inventory,
    serialize_bundle,
    serialize_inventory,
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


def _expected_seed(payload: dict[str, object]) -> str:
    digest_manifest = {
        "inventory_binding": payload["inventory_binding"],
        "dependencies": sorted(
            payload["dependencies"], key=lambda item: (item["role"], item["path"])
        ),
    }
    manifest_bytes = (
        json.dumps(
            digest_manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(manifest_bytes).hexdigest()


def _rebind_sampling(payload: dict[str, object]) -> None:
    seed = _expected_seed(payload)
    payload["sampling"]["seed"] = seed
    payload["selected_anchors"] = [
        *bundle_module._select_anchors(
            "source_members",
            payload["frames"]["source_members"]["anchors"],
            seed,
            payload["policy"]["sample_size"],
        ),
        *bundle_module._select_anchors(
            "canonical_outputs",
            payload["frames"]["canonical_outputs"]["anchors"],
            seed,
            payload["policy"]["sample_size"],
        ),
    ]
    selected_output_ids = {
        item["anchor_id"]
        for item in payload["selected_anchors"]
        if item["frame"] == "canonical_outputs"
    }
    output_by_id = {
        item["anchor_id"]: item
        for item in payload["frames"]["canonical_outputs"]["anchors"]
    }
    source_artifact = next(
        item for item in payload["artifacts"] if item["grain"] == "source_artifact"
    )
    payload["artifacts"] = [
        source_artifact,
        *[
            {
                "grain": "canonical_artifact",
                "member_id": output_by_id[anchor_id]["member_id"],
                "path": output_by_id[anchor_id]["artifact_path"],
                "raw_sha256": output_by_id[anchor_id]["artifact_sha256"],
                "rendering_id": payload["scope"]["rendering_id"],
                "work_id": payload["scope"]["work_id"],
            }
            for anchor_id in sorted(selected_output_ids)
        ],
    ]


def _rehash_source_frame(payload: dict[str, object]) -> None:
    anchors = payload["frames"]["source_members"]["anchors"]
    payload["frames"]["source_members"]["anchors_sha256"] = hashlib.sha256(
        (
            json.dumps(
                anchors,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    ).hexdigest()


@pytest.mark.requires_local_artifacts
def test_live_asv_bundle_is_deterministic_and_binds_the_bounded_scope() -> None:
    first = generate_bundle(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)
    second = generate_bundle(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)

    assert first == second
    assert first["identity"] == "verification-bundle-v1"
    assert first["scope"] == {
        "work_id": "asv",
        "rendering_id": "asv:scrollmapper-json",
    }
    assert first["inventory_binding"]["identity"] == "verification-inventory-v1"
    assert len(first["frames"]["source_members"]["anchors"]) == 66
    assert len(first["frames"]["canonical_outputs"]["anchors"]) == 66
    assert len(first["selected_anchors"]) == 6
    assert {item["reason"] for item in first["selected_anchors"]} == {
        "mandatory-first",
        "mandatory-last",
        "hash-seeded",
    }
    assert first["sampling"]["algorithm"] == "sha256-index-v1"
    assert first["inventory_binding"]["raw_sha256"] == hashlib.sha256(
        serialize_inventory(generate_inventory(REPO_ROOT, LIVE_OWNERSHIP))
    ).hexdigest()
    roles = {
        item["role"] for item in first["dependencies"]
    }
    assert roles >= {
        "catalog",
        "catalog_generator",
        "catalog_identity",
        "dependency_collector",
        "generator",
        "ownership",
        "parser",
        "schema",
        "source",
        "source_config",
        "bundle_schema",
        "bundle_generator",
        "policy",
        "ownership_adapter:bible_collection",
    }
    assert "transitive_code:build/parsers/bsb_bible_text.py" in roles
    assert first["publication_projection"]["status"] == "not_applicable"
    assert first["publication_projection"]["reason"] == (
        "Publication projection and export generation are deferred for this bounded ASV trial."
    )
    assert first["sampling"]["seed"] == _expected_seed(first)
    serialized = serialize_bundle(first)
    assert serialized == serialize_bundle(second)
    assert serialized.endswith(b"\n") and not serialized.endswith(b"\n\n")
    assert serialized.count(b"\n") == 1


@pytest.mark.skipif(
    not LIVE_SINGLE_FILE_SOURCE.is_file(),
    reason="ignored Spurgeon raw witness is unavailable",
)
def test_live_single_file_bundle_reconciles_one_member_and_selects_boundaries() -> None:
    payload = generate_bundle(
        REPO_ROOT, LIVE_SINGLE_FILE_OWNERSHIP, LIVE_SINGLE_FILE_POLICY
    )

    assert payload["scope"] == {
        "work_id": "spurgeon-all-of-grace",
        "rendering_id": "spurgeon-all-of-grace:structured-json",
    }
    assert payload["frames"]["source_members"]["count"] == 1
    assert payload["frames"]["canonical_outputs"]["count"] == 1
    assert payload["selected_anchors"] == [
        {
            "frame": "source_members",
            "anchor_id": "source:spurgeon-all-of-grace",
            "reason": "mandatory-first-and-last",
        },
        {
            "frame": "canonical_outputs",
            "anchor_id": "canonical:spurgeon-all-of-grace",
            "reason": "mandatory-first-and-last",
        },
    ]
    assert payload["publication_projection"]["status"] == "not_applicable"
    assert payload["publication_projection"]["reason"] == (
        "Publication projection and export generation are deferred for this bounded verification trial."
    )
    assert serialize_bundle(payload) == serialize_bundle(
        generate_bundle(REPO_ROOT, LIVE_SINGLE_FILE_OWNERSHIP, LIVE_SINGLE_FILE_POLICY)
    )


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _descriptor(source_hash: str) -> dict[str, object]:
    return {
        "identity": "verification-ownership-v1",
        "adapter": "bible_collection",
        "works": [{"grain": "work", "work_id": "asv"}],
        "renderings": [
            {
                "grain": "rendering",
                "rendering_id": "asv:scrollmapper-json",
                "work_id": "asv",
            }
        ],
        "source_artifact": {
            "grain": "source_artifact",
            "rendering_id": "asv:scrollmapper-json",
            "path": "raw/bible_databases/formats/json/ASV.json",
            "expected_raw_sha256": source_hash,
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


@pytest.fixture
def small_bundle_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "independent-bundle-repository"
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
    source_bytes = _json_bytes(source)
    _write(root / "raw/bible_databases/formats/json/ASV.json", source_bytes)
    _write(
        root / "sources/bible-text/asv/config.json",
        _json_bytes(
            {
                "resource_id": "asv",
                "source_file": "raw/bible_databases/formats/json/ASV.json",
            }
        ),
    )
    for member_id, book in (("genesis", "Genesis"), ("exodus", "Exodus")):
        _write(
            root / f"data/bible-text/asv/{member_id}.json",
            _json_bytes({"meta": {"id": "asv", "scope": {"book": book}}, "data": []}),
        )
    _write(
        root / "docs/WORK_CATALOG.md",
        (
            "| Category | Title | Author | Publication date | Files | Records | Audit flags |\n"
            "|---|---|---|---|---:|---:|---|\n"
            "| Bible Translations | American Standard Version | | 1901 | 2 | 0 | missing_author |\n"
        ).encode("utf-8"),
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
        _write(root / relative_path, (REPO_ROOT / relative_path).read_bytes())
    _copy_parser_dependency_closure(root, "build/parsers/bible_text_translations.py")
    ownership = root / "cvw_phase1b/fixtures/asv_ownership.json"
    descriptor = _descriptor(hashlib.sha256(source_bytes).hexdigest())
    _write_descriptor_catalog_identity(root, descriptor)
    _write(ownership, _json_bytes(descriptor))
    return root, ownership, root / "cvw_phase1b/fixtures/asv_policy.json"


def _mutate_json(path: Path, mutate: Callable[[dict[str, object]], None]) -> None:
    payload = json.loads(path.read_bytes())
    mutate(payload)
    path.write_bytes(_json_bytes(payload))


def test_small_independent_repository_generates_a_read_only_bundle(
    small_bundle_repo: tuple[Path, Path, Path],
) -> None:
    root, ownership, policy = small_bundle_repo
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}

    payload = generate_bundle(root, ownership, policy)

    after = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert before == after
    assert payload["frames"]["source_members"]["count"] == 2
    assert payload["frames"]["canonical_outputs"]["count"] == 2
    assert len(payload["selected_anchors"]) == 4
    assert len(payload["artifacts"]) == 3
    assert all(item["reason"] != "hash-seeded" for item in payload["selected_anchors"])
    assert {
        frame: sum(item["frame"] == frame for item in payload["selected_anchors"])
        for frame in ("source_members", "canonical_outputs")
    } == {"source_members": 2, "canonical_outputs": 2}


def test_policy_unknown_fields_and_noncanonical_path_fail_closed(
    small_bundle_repo: tuple[Path, Path, Path],
) -> None:
    root, ownership, policy = small_bundle_repo
    _mutate_json(policy, lambda payload: payload.__setitem__("unexpected", True))

    with pytest.raises(BundleError, match="policy.*does not validate|unknown"):
        generate_bundle(root, ownership, policy)

    with pytest.raises(BundleError, match="repository-relative|canonical|inside"):
        generate_bundle(root, ownership, root / ".." / "outside-policy.json")


def test_policy_numeric_overflow_fails_closed(
    small_bundle_repo: tuple[Path, Path, Path],
) -> None:
    root, ownership, policy = small_bundle_repo
    policy.write_bytes(
        policy.read_bytes().replace(
            b'"sample_size": 3',
            b'"sample_size": 1e999',
        )
    )

    with pytest.raises(BundleError, match="non-finite"):
        generate_bundle(root, ownership, policy)


def test_duplicate_policy_keys_fail_closed_at_the_new_json_boundary(
    small_bundle_repo: tuple[Path, Path, Path],
) -> None:
    root, ownership, policy = small_bundle_repo
    data = policy.read_bytes()
    line = next(
        line
        for line in data.splitlines(keepends=True)
        if line.strip() == b'"identity": "verification-policy-v1",'
    )
    start = data.index(line)
    policy.write_bytes(data[: start + len(line)] + line + data[start + len(line) :])

    with pytest.raises(BundleError, match="duplicate JSON object key"):
        generate_bundle(root, ownership, policy)


@pytest.mark.requires_local_artifacts
def test_serialization_rejects_unknown_nonfinite_and_non_json_values() -> None:
    payload = generate_bundle(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)

    unknown = copy.deepcopy(payload)
    unknown["unexpected"] = True
    with pytest.raises(BundleError, match="does not validate"):
        serialize_bundle(unknown)

    nonfinite = copy.deepcopy(payload)
    nonfinite["sampling"]["seed"] = float("nan")
    with pytest.raises(BundleError, match="non-finite"):
        serialize_bundle(nonfinite)

    non_json = copy.deepcopy(payload)
    non_json["sampling"]["seed"] = object()
    with pytest.raises(BundleError, match="non-JSON"):
        serialize_bundle(non_json)


@pytest.mark.parametrize("mutation", ["duplicate", "out-of-frame", "bad-frame-hash"])
@pytest.mark.requires_local_artifacts
def test_serialization_rejects_invalid_selection_or_frame_binding(
    mutation: str,
) -> None:
    payload = generate_bundle(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)
    if mutation == "duplicate":
        payload["selected_anchors"].append(copy.deepcopy(payload["selected_anchors"][0]))
    elif mutation == "out-of-frame":
        payload["selected_anchors"][0]["anchor_id"] = "source:not-in-frame"
    else:
        payload["frames"]["source_members"]["anchors_sha256"] = "0" * 64

    with pytest.raises(BundleError, match="duplicate|outside|hash"):
        serialize_bundle(payload)


@pytest.mark.requires_local_artifacts
def test_serialization_rejects_a_false_sampling_seed() -> None:
    payload = generate_bundle(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)
    payload["sampling"]["seed"] = "0" * 64

    with pytest.raises(BundleError, match="seed"):
        serialize_bundle(payload)


@pytest.mark.requires_local_artifacts
def test_serialization_rejects_replacing_the_seeded_anchor() -> None:
    payload = generate_bundle(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)
    selected = next(
        item
        for item in payload["selected_anchors"]
        if item["frame"] == "source_members" and item["reason"] == "hash-seeded"
    )
    selected_ids = {
        item["anchor_id"]
        for item in payload["selected_anchors"]
        if item["frame"] == "source_members"
    }
    selected["anchor_id"] = next(
        anchor["anchor_id"]
        for anchor in payload["frames"]["source_members"]["anchors"][1:-1]
        if anchor["anchor_id"] not in selected_ids
    )

    with pytest.raises(BundleError, match="selection"):
        serialize_bundle(payload)


@pytest.mark.requires_local_artifacts
def test_serialization_rejects_an_extra_seeded_selection() -> None:
    payload = generate_bundle(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)
    selected_ids = {
        item["anchor_id"]
        for item in payload["selected_anchors"]
        if item["frame"] == "source_members"
    }
    extra_anchor = next(
        anchor["anchor_id"]
        for anchor in payload["frames"]["source_members"]["anchors"][1:-1]
        if anchor["anchor_id"] not in selected_ids
    )
    payload["selected_anchors"].append(
        {
            "frame": "source_members",
            "anchor_id": extra_anchor,
            "reason": "hash-seeded",
        }
    )

    with pytest.raises(BundleError, match="selection|sample"):
        serialize_bundle(payload)


@pytest.mark.parametrize(
    ("role", "message"),
    [
        ("bundle_generator", "bundle generator"),
        ("bundle_schema", "bundle schema"),
        ("ownership_adapter:bible_collection", "ownership adapter"),
    ],
)
@pytest.mark.requires_local_artifacts
def test_serialization_authenticates_executing_bundle_dependency_hashes(
    role: str,
    message: str,
) -> None:
    payload = generate_bundle(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)
    dependency = next(item for item in payload["dependencies"] if item["role"] == role)
    dependency["raw_sha256"] = "0" * 64

    with pytest.raises(BundleError, match=message):
        serialize_bundle(payload)


@pytest.mark.requires_local_artifacts
def test_bundle_reconciliation_uses_authenticated_adapter_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[object] = []
    original = ownership.validate_source_identity

    def spy(adapter_name: object, source_id: object) -> str:
        observed.append(adapter_name)
        return original(adapter_name, source_id)

    monkeypatch.setattr(ownership, "validate_source_identity", spy)
    payload = generate_bundle(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)
    serialize_bundle(payload)

    assert observed
    assert set(observed) == {"bible_collection"}


@pytest.mark.parametrize("defect", ["unknown", "missing", "duplicated"])
@pytest.mark.requires_local_artifacts
def test_serialization_requires_exactly_one_recognized_ownership_adapter_role(
    defect: str,
) -> None:
    payload = generate_bundle(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)
    dependency = next(
        item
        for item in payload["dependencies"]
        if item["role"].startswith("ownership_adapter:")
    )
    if defect == "unknown":
        dependency["role"] = "ownership_adapter:not_allow_listed"
    elif defect == "missing":
        payload["dependencies"].remove(dependency)
    else:
        duplicate = copy.deepcopy(dependency)
        duplicate["role"] = "ownership_adapter:single_file"
        payload["dependencies"].append(duplicate)
        payload["dependencies"].sort(key=lambda item: (item["role"], item["path"]))

    with pytest.raises(BundleError, match="ownership adapter"):
        serialize_bundle(payload)


@pytest.mark.requires_local_artifacts
def test_serialization_rejects_adapter_role_that_mismatches_asv_source_identity() -> None:
    payload = generate_bundle(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)
    dependency = next(
        item
        for item in payload["dependencies"]
        if item["role"].startswith("ownership_adapter:")
    )
    dependency["role"] = "ownership_adapter:single_file"
    payload["dependencies"].sort(key=lambda item: (item["role"], item["path"]))
    _rebind_sampling(payload)

    with pytest.raises(BundleError, match="source identity|source member"):
        serialize_bundle(payload)


@pytest.mark.requires_local_artifacts
def test_serialization_rejects_forged_asv_source_identity() -> None:
    payload = generate_bundle(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)
    payload["frames"]["source_members"]["anchors"][0]["source_id"] = "Forged Source"
    _rehash_source_frame(payload)

    with pytest.raises(BundleError, match="source identity"):
        serialize_bundle(payload)


@pytest.mark.skipif(
    not LIVE_SINGLE_FILE_SOURCE.is_file(),
    reason="ignored Spurgeon raw witness is unavailable",
)
def test_serialization_rejects_forged_single_file_source_identity() -> None:
    payload = generate_bundle(
        REPO_ROOT, LIVE_SINGLE_FILE_OWNERSHIP, LIVE_SINGLE_FILE_POLICY
    )
    payload["frames"]["source_members"]["anchors"][0]["source_id"] = "forged-work"
    _rehash_source_frame(payload)

    with pytest.raises(BundleError, match="source identity"):
        serialize_bundle(payload)


@pytest.mark.requires_local_artifacts
def test_serialization_rejects_a_changed_inventory_binding_with_the_old_seed() -> None:
    payload = generate_bundle(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)
    payload["inventory_binding"]["raw_sha256"] = "0" * 64

    with pytest.raises(BundleError, match="seed|inventory"):
        serialize_bundle(payload)


@pytest.mark.requires_local_artifacts
def test_serialization_rejects_a_leading_space_dependency_path() -> None:
    payload = generate_bundle(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)
    dependency = next(item for item in payload["dependencies"] if item["role"] == "policy")
    dependency["path"] = f" {dependency['path']}"

    with pytest.raises(BundleError, match="canonical repository path"):
        serialize_bundle(payload)

@pytest.mark.parametrize("role", ["policy", "source"])
@pytest.mark.requires_local_artifacts
def test_serialization_rejects_changed_bound_digests_with_the_old_sampling(
    role: str,
) -> None:
    payload = generate_bundle(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)
    dependency = next(item for item in payload["dependencies"] if item["role"] == role)
    dependency["raw_sha256"] = "0" * 64

    with pytest.raises(BundleError, match="seed|digest"):
        serialize_bundle(payload)


@pytest.mark.parametrize("surface", ["artifact", "frame"])
@pytest.mark.requires_local_artifacts
def test_serialization_rejects_noncanonical_paths_at_every_bundle_surface(
    surface: str,
) -> None:
    payload = generate_bundle(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)
    if surface == "artifact":
        payload["artifacts"][0]["path"] = f" {payload['artifacts'][0]['path']}"
    else:
        anchor = payload["frames"]["source_members"]["anchors"][0]
        anchor["artifact_path"] = f" {anchor['artifact_path']}"

    with pytest.raises(BundleError, match="canonical repository path"):
        serialize_bundle(payload)
