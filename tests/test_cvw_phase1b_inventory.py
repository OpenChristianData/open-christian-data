"""Focused tests for the bounded Phase 1B ownership seam.

Full-corpus ownership, other families, publication, bundles/events, staleness,
review workflows, UI, release, and certification remain explicitly out of scope.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

import jsonschema
import pytest

from cvw_phase1b import InventoryError, generate_inventory, serialize_inventory
from cvw_phase1b.dependency_closure import collect_local_python_dependencies


REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_OWNERSHIP = REPO_ROOT / "cvw_phase1b" / "fixtures" / "asv_ownership.json"
LIVE_SINGLE_FILE_OWNERSHIP = (
    REPO_ROOT / "cvw_phase1b" / "fixtures" / "spurgeon_ownership.json"
)
LIVE_SINGLE_FILE_SOURCE = REPO_ROOT / "raw/ia/spurgeon_all_of_grace.txt"


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
def small_repo(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "independent-repository"
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
    for dependency in (
        "cvw_phase1b/inventory.py",
        "cvw_phase1b/ownership.py",
        "build/parsers/bible_text_translations.py",
        "build/tools/count_dataset_records.py",
    ):
        _write(root / dependency, (REPO_ROOT / dependency).read_bytes())
    _copy_parser_dependency_closure(root, "build/parsers/bible_text_translations.py")
    _write(
        root / "schemas/v1/verification_inventory.schema.json",
        (REPO_ROOT / "schemas/v1/verification_inventory.schema.json").read_bytes(),
    )
    ownership = root / "cvw_phase1b/fixtures/asv_ownership.json"
    descriptor = _descriptor(hashlib.sha256(source_bytes).hexdigest())
    _write_descriptor_catalog_identity(root, descriptor)
    _write(ownership, _json_bytes(descriptor))
    return root, ownership


def _mutate_json(path: Path, mutate: Callable[[dict[str, object]], None]) -> None:
    payload = json.loads(path.read_bytes())
    mutate(payload)
    path.write_bytes(_json_bytes(payload))


def _refresh_source_hash(root: Path, ownership: Path) -> None:
    digest = hashlib.sha256(
        (root / "raw/bible_databases/formats/json/ASV.json").read_bytes()
    ).hexdigest()
    _mutate_json(
        ownership,
        lambda payload: payload["source_artifact"].__setitem__("expected_raw_sha256", digest),
    )


@pytest.mark.requires_local_artifacts
def test_live_asv_inventory_has_source_derived_66_book_ownership() -> None:
    payload = generate_inventory(REPO_ROOT, LIVE_OWNERSHIP)

    assert payload["identity"] == "verification-inventory-v1"
    assert len(payload["works"]) == 1
    assert len(payload["renderings"]) == 1
    assert len(payload["source_artifacts"]) == 1
    assert len(payload["members"]) == 66
    assert len(payload["canonical_artifacts"]) == 66
    assert payload["ir_artifacts"] == []
    assert payload["catalog_snapshot"]["file_count"] == 66
    assert {item["source_id"] for item in payload["members"]} >= {
        "I Chronicles",
        "Revelation of John",
    }
    roles = {item["role"] for item in payload["dependencies"]}
    assert roles >= {
        "catalog",
        "catalog_generator",
        "catalog_identity",
        "dependency_collector",
        "generator",
        "ownership",
        "ownership_adapter:bible_collection",
        "parser",
        "schema",
        "source",
        "source_config",
    }
    assert "transitive_code:build/parsers/bsb_bible_text.py" in roles


def _catalog_identity_bytes(*works: dict[str, object]) -> bytes:
    return _json_bytes({"identity": "work-catalog-identity-v1", "works": list(works)})


def _write_descriptor_catalog_identity(root: Path, descriptor: dict[str, object]) -> None:
    catalog = descriptor["catalog"]
    _write(
        root / catalog["identity_path"],
        _catalog_identity_bytes(
            {
                "work_id": catalog["work_id"],
                "title": catalog["title"],
                "author": catalog["author"],
                "category_label": catalog["category"],
                "file_count": catalog["expected_file_count"],
            }
        ),
    )


def _copy_parser_dependency_closure(root: Path, parser_path: str) -> None:
    dependency_collector = "cvw_phase1b/dependency_closure.py"
    _write(root / dependency_collector, (REPO_ROOT / dependency_collector).read_bytes())
    for path in collect_local_python_dependencies(REPO_ROOT, [parser_path]):
        _write(root / path, (REPO_ROOT / path).read_bytes())


@pytest.mark.skipif(
    not LIVE_SINGLE_FILE_SOURCE.is_file(),
    reason="ignored Spurgeon raw witness is unavailable",
)
def test_live_single_file_inventory_has_single_explicit_member_and_output() -> None:
    payload = generate_inventory(REPO_ROOT, LIVE_SINGLE_FILE_OWNERSHIP)

    assert payload["works"] == [{"grain": "work", "work_id": "spurgeon-all-of-grace"}]
    assert payload["renderings"] == [
        {
            "grain": "rendering",
            "rendering_id": "spurgeon-all-of-grace:structured-json",
            "work_id": "spurgeon-all-of-grace",
        }
    ]
    assert payload["members"] == [
        {
            "grain": "collection_member",
            "member_id": "spurgeon-all-of-grace",
            "rendering_id": "spurgeon-all-of-grace:structured-json",
            "source_id": "spurgeon-all-of-grace",
        }
    ]
    assert len(payload["canonical_artifacts"]) == 1
    assert payload["canonical_artifacts"][0]["path"] == (
        "data/structured-text/spurgeon-all-of-grace.json"
    )
    assert payload["catalog_snapshot"]["file_count"] == 1
    assert {
        item["role"] for item in payload["dependencies"]
    } >= {"ownership_adapter:single_file", "structured_text_schema"}
    assert next(
        item for item in payload["dependencies"] if item["role"] == "structured_text_schema"
    )["path"] == "schemas/v1/structured_text.schema.json"
    assert serialize_inventory(payload) == serialize_inventory(
        generate_inventory(REPO_ROOT, LIVE_SINGLE_FILE_OWNERSHIP)
    )


@pytest.fixture
def single_file_repo(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "independent-single-file-repository"
    work_id = "tiny-single-file"
    rendering_id = f"{work_id}:structured-json"
    source_path = "raw/ia/tiny.txt"
    source_bytes = b"A tiny independent witness.\n"
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    _write(root / source_path, source_bytes)
    _write(
        root / "sources/structured-text/tiny-single-file/config.json",
        _json_bytes(
            {
                "slug": work_id,
                "schema": "structured_text",
                "source_type": "ia",
                "ia_id": "tiny",
                "source_url": "https://example.invalid/tiny.txt",
                "source_hash": f"sha256:{source_hash}",
                "download_date": "2026-07-18",
                "processing_script": "build/parsers/gutenberg_evangelical.py@v1.0.0",
            }
        ),
    )
    _write(
        root / "data/structured-text/tiny-single-file.json",
        _json_bytes(
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
                        "processing_script_version": "build/parsers/gutenberg_evangelical.py@v1.0.0",
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
            }
        ),
    )
    _write(root / "data/structured-text/unrelated-sibling.json", b"not owned\n")
    _write(
        root / "docs/WORK_CATALOG.md",
        (
            "| Category | Title | Author | Publication date | Files | Records | Audit flags |\n"
            "|---|---|---|---|---:|---:|---|\n"
            "| Books and Long-Form Works | Tiny Single File | | 2026 | 1 | 1 | |\n"
        ).encode("utf-8"),
    )
    for dependency in (
        "cvw_phase1b/inventory.py",
        "cvw_phase1b/ownership.py",
        "build/parsers/gutenberg_evangelical.py",
        "build/tools/count_dataset_records.py",
        "schemas/v1/verification_inventory.schema.json",
        "schemas/v1/structured_text.schema.json",
    ):
        _write(root / dependency, (REPO_ROOT / dependency).read_bytes())
    _copy_parser_dependency_closure(root, "build/parsers/gutenberg_evangelical.py")
    ownership = root / "cvw_phase1b/fixtures/tiny_ownership.json"
    _write(
        ownership,
        _json_bytes(
            {
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
        ),
    )
    _write_descriptor_catalog_identity(root, json.loads(ownership.read_bytes()))
    return root, ownership


def test_independent_single_file_repository_uses_only_its_explicit_output(
    single_file_repo: tuple[Path, Path],
) -> None:
    root, ownership = single_file_repo
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}

    payload = generate_inventory(root, ownership)

    assert [item["member_id"] for item in payload["members"]] == ["tiny-single-file"]
    assert [item["path"] for item in payload["canonical_artifacts"]] == [
        "data/structured-text/tiny-single-file.json"
    ]
    assert before == {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("defect", ["slug", "source_hash", "parser"])
def test_single_file_source_config_binding_defects_fail_closed(
    single_file_repo: tuple[Path, Path], defect: str
) -> None:
    root, ownership = single_file_repo
    config_path = root / "sources/structured-text/tiny-single-file/config.json"

    def corrupt(config: dict[str, object]) -> None:
        if defect == "slug":
            config["slug"] = "other-work"
        elif defect == "source_hash":
            config["source_hash"] = "sha256:" + ("0" * 64)
        else:
            config["processing_script"] = "build/parsers/other.py@v1.0.0"

    _mutate_json(config_path, corrupt)
    with pytest.raises(InventoryError, match="source config"):
        generate_inventory(root, ownership)


def test_single_file_source_config_must_select_structured_text_schema(
    single_file_repo: tuple[Path, Path],
) -> None:
    root, ownership = single_file_repo
    _mutate_json(
        root / "sources/structured-text/tiny-single-file/config.json",
        lambda payload: payload.__setitem__("schema", "bible_text"),
    )

    with pytest.raises(InventoryError, match="structured_text"):
        generate_inventory(root, ownership)


@pytest.mark.parametrize("defect", ["identity", "provenance", "missing"])
def test_single_file_canonical_evidence_defects_fail_closed(
    single_file_repo: tuple[Path, Path], defect: str
) -> None:
    root, ownership = single_file_repo
    canonical_path = root / "data/structured-text/tiny-single-file.json"
    if defect == "missing":
        canonical_path.unlink()
    else:
        def corrupt(canonical: dict[str, object]) -> None:
            if defect == "identity":
                canonical["meta"]["id"] = "other-work"
            else:
                canonical["meta"]["provenance"]["source_hash"] = "sha256:" + ("0" * 64)

        _mutate_json(canonical_path, corrupt)

    with pytest.raises(InventoryError, match="canonical"):
        generate_inventory(root, ownership)


@pytest.mark.parametrize("defect", ["schema_type", "parser_marker", "schema_shape"])
def test_single_file_canonical_is_authenticated_against_structured_text_schema(
    single_file_repo: tuple[Path, Path], defect: str
) -> None:
    root, ownership = single_file_repo
    canonical_path = root / "data/structured-text/tiny-single-file.json"

    def corrupt(canonical: dict[str, object]) -> None:
        if defect == "schema_type":
            canonical["meta"]["schema_type"] = "bible_text"
        elif defect == "parser_marker":
            canonical["meta"]["provenance"]["processing_script_version"] = (
                "build/parsers/other.py@v1.0.0"
            )
        else:
            canonical["data"].pop("sections")

    _mutate_json(canonical_path, corrupt)

    with pytest.raises(InventoryError, match="structured_text|canonical"):
        generate_inventory(root, ownership)


def test_single_file_structured_text_schema_bytes_are_bound(
    single_file_repo: tuple[Path, Path],
) -> None:
    root, ownership = single_file_repo
    schema_path = root / "schemas/v1/structured_text.schema.json"
    schema_path.write_bytes(schema_path.read_bytes() + b"\n")

    with pytest.raises(InventoryError, match="structured_text schema"):
        generate_inventory(root, ownership)


def test_nonfinite_overflow_is_rejected_at_json_load_boundary(
    single_file_repo: tuple[Path, Path],
) -> None:
    root, ownership = single_file_repo
    config_path = root / "sources/structured-text/tiny-single-file/config.json"
    config_path.write_bytes(
        config_path.read_bytes().replace(
            b'"download_date": "2026-07-18"',
            b'"download_date": 1e999',
        )
    )

    with pytest.raises(InventoryError, match="non-finite"):
        generate_inventory(root, ownership)


@pytest.mark.requires_local_artifacts
def test_live_payload_validates_and_serialization_is_deterministic() -> None:
    payload = generate_inventory(REPO_ROOT, LIVE_OWNERSHIP)
    schema = json.loads(
        (REPO_ROOT / "schemas/v1/verification_inventory.schema.json").read_bytes()
    )

    jsonschema.Draft202012Validator(schema).validate(payload)
    first = serialize_inventory(payload)
    second = serialize_inventory(generate_inventory(REPO_ROOT, LIVE_OWNERSHIP))
    assert first == second
    assert first.decode("utf-8").encode("utf-8") == first
    assert first.endswith(b"\n") and not first.endswith(b"\n\n")


def test_small_independent_repository_generates_and_is_read_only(
    small_repo: tuple[Path, Path],
) -> None:
    root, ownership = small_repo
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}

    payload = generate_inventory(root, ownership)

    after = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert before == after
    assert [item["source_id"] for item in payload["members"]] == ["Exodus", "Genesis"]
    assert len(payload["canonical_artifacts"]) == 2


@pytest.mark.parametrize("owner_key", ["works", "renderings"])
def test_duplicate_aggregate_owner_fails_closed(
    small_repo: tuple[Path, Path], owner_key: str
) -> None:
    root, ownership = small_repo
    _mutate_json(ownership, lambda payload: payload[owner_key].append(payload[owner_key][0]))

    with pytest.raises(InventoryError, match="exactly one|duplicate"):
        generate_inventory(root, ownership)


def test_duplicate_source_member_fails_closed(small_repo: tuple[Path, Path]) -> None:
    root, ownership = small_repo
    source_path = root / "raw/bible_databases/formats/json/ASV.json"
    _mutate_json(source_path, lambda payload: payload["books"].append(payload["books"][0]))
    _refresh_source_hash(root, ownership)

    with pytest.raises(InventoryError, match="duplicate source-derived"):
        generate_inventory(root, ownership)


@pytest.mark.parametrize(
    "defect",
    [
        "book-extra-key",
        "book-missing-key",
        "empty-chapters",
        "chapter-not-object",
        "chapter-extra-key",
        "chapter-number-not-positive-int",
        "duplicate-chapter-number",
        "verse-not-object",
        "verse-extra-key",
        "verse-number-not-positive-int",
        "duplicate-verse-number",
        "verse-text-not-string",
    ],
)
def test_raw_asv_structure_defects_fail_closed(
    small_repo: tuple[Path, Path], defect: str
) -> None:
    root, ownership = small_repo
    source_path = root / "raw/bible_databases/formats/json/ASV.json"

    def corrupt(source: dict[str, object]) -> None:
        book = source["books"][0]
        chapter = book["chapters"][0]
        verse = chapter["verses"][0]
        if defect == "book-extra-key":
            book["unexpected"] = True
        elif defect == "book-missing-key":
            book.pop("name")
        elif defect == "empty-chapters":
            book["chapters"] = []
        elif defect == "chapter-not-object":
            book["chapters"][0] = []
        elif defect == "chapter-extra-key":
            chapter["unexpected"] = True
        elif defect == "chapter-number-not-positive-int":
            chapter["chapter"] = False
        elif defect == "duplicate-chapter-number":
            book["chapters"].append(chapter.copy())
        elif defect == "verse-not-object":
            chapter["verses"][0] = []
        elif defect == "verse-extra-key":
            verse["unexpected"] = True
        elif defect == "verse-number-not-positive-int":
            verse["verse"] = 0
        elif defect == "duplicate-verse-number":
            chapter["verses"].append(verse.copy())
        else:
            verse["text"] = 17

    _mutate_json(source_path, corrupt)
    _refresh_source_hash(root, ownership)

    with pytest.raises(InventoryError):
        generate_inventory(root, ownership)


@pytest.mark.parametrize(
    ("relative_path", "needle"),
    [
        ("cvw_phase1b/fixtures/asv_ownership.json", b'"identity"'),
        ("raw/bible_databases/formats/json/ASV.json", b'"translation"'),
        ("sources/bible-text/asv/config.json", b'"resource_id"'),
        ("data/bible-text/asv/genesis.json", b'"id"'),
        ("schemas/v1/verification_inventory.schema.json", b'"$schema"'),
    ],
)
def test_duplicate_keys_fail_closed_at_every_json_input_boundary(
    small_repo: tuple[Path, Path], relative_path: str, needle: bytes
) -> None:
    root, ownership = small_repo
    path = root / relative_path
    data = path.read_bytes()
    line_start = data.index(needle)
    line_end = data.index(b"\n", line_start) + 1
    path.write_bytes(data[:line_end] + data[line_start:line_end] + data[line_end:])
    if relative_path.endswith("ASV.json"):
        _refresh_source_hash(root, ownership)

    with pytest.raises(InventoryError, match="duplicate JSON object key"):
        generate_inventory(root, ownership)


@pytest.mark.parametrize("role", ["generator_dependency", "parser_dependency"])
def test_supplied_dependency_bytes_must_match_the_executing_modules(
    small_repo: tuple[Path, Path], role: str
) -> None:
    root, ownership = small_repo
    descriptor = json.loads(ownership.read_bytes())
    (root / descriptor[role]).write_bytes(b"# dummy supplied dependency\n")

    with pytest.raises(InventoryError, match="bytes differ from the executing module"):
        generate_inventory(root, ownership)


def test_dependency_provenance_binds_actual_generator_and_parser_hashes(
    small_repo: tuple[Path, Path],
) -> None:
    root, ownership = small_repo

    dependencies = {
        item["role"]: item for item in generate_inventory(root, ownership)["dependencies"]
    }
    for role, path in {
        "generator": "cvw_phase1b/inventory.py",
        "parser": "build/parsers/bible_text_translations.py",
    }.items():
        assert dependencies[role] == {
            "role": role,
            "path": path,
            "raw_sha256": hashlib.sha256((REPO_ROOT / path).read_bytes()).hexdigest(),
        }


def test_unknown_descriptor_ownership_is_not_silently_ignored(
    small_repo: tuple[Path, Path],
) -> None:
    root, ownership = small_repo
    _mutate_json(ownership, lambda payload: payload.__setitem__("members", []))

    with pytest.raises(InventoryError, match="unknown fields"):
        generate_inventory(root, ownership)


@pytest.mark.parametrize("adapter", [None, "not-allow-listed"])
def test_unknown_or_missing_ownership_adapter_fails_closed(
    small_repo: tuple[Path, Path], adapter: str | None
) -> None:
    root, ownership = small_repo
    _mutate_json(ownership, lambda payload: payload.__setitem__("adapter", adapter))

    with pytest.raises(InventoryError, match="adapter"):
        generate_inventory(root, ownership)


@pytest.mark.parametrize("bad_hash", [None, "0" * 64])
def test_missing_or_mismatched_source_hash_fails_closed(
    small_repo: tuple[Path, Path], bad_hash: str | None
) -> None:
    root, ownership = small_repo

    def corrupt(payload: dict[str, object]) -> None:
        if bad_hash is None:
            payload["source_artifact"].pop("expected_raw_sha256")
        else:
            payload["source_artifact"]["expected_raw_sha256"] = bad_hash

    _mutate_json(ownership, corrupt)
    with pytest.raises(InventoryError, match="SHA-256"):
        generate_inventory(root, ownership)


def test_missing_canonical_file_fails_closed(small_repo: tuple[Path, Path]) -> None:
    root, ownership = small_repo
    (root / "data/bible-text/asv/genesis.json").unlink()

    with pytest.raises(InventoryError, match="missing expected canonical"):
        generate_inventory(root, ownership)


def test_extra_canonical_file_fails_closed(small_repo: tuple[Path, Path]) -> None:
    root, ownership = small_repo
    _write(root / "data/bible-text/asv/orphan.json", b"{}\n")

    with pytest.raises(InventoryError, match="extra/orphan canonical"):
        generate_inventory(root, ownership)


def test_no_ir_root_does_not_invent_or_scan_a_conventional_root(
    small_repo: tuple[Path, Path],
) -> None:
    root, ownership = small_repo
    _write(root / "ir/asv/genesis.xml", b"<TEI/>\n")

    assert generate_inventory(root, ownership)["ir_artifacts"] == []


def test_ir_declarations_are_rejected_when_no_root_is_declared(
    small_repo: tuple[Path, Path],
) -> None:
    root, ownership = small_repo
    _mutate_json(
        ownership,
        lambda payload: payload["ir_artifacts"].append(
            {
                "grain": "ir_artifact",
                "path": "ir/asv/genesis.xml",
                "rendering_id": "asv:scrollmapper-json",
            }
        ),
    )

    with pytest.raises(InventoryError, match="must be empty when no IR root"):
        generate_inventory(root, ownership)


def test_ir_artifact_owner_and_output_bind_the_bounded_rendering(
    small_repo: tuple[Path, Path],
) -> None:
    root, ownership = small_repo
    ir_path = "bounded-ir/genesis.xml"
    _write(root / ir_path, b"<TEI/>\n")

    def declare(payload: dict[str, object]) -> None:
        payload["ir_root"] = "bounded-ir"
        payload["ir_artifacts"] = [
            {
                "grain": "ir_artifact",
                "path": ir_path,
                "rendering_id": "asv:scrollmapper-json",
            }
        ]

    _mutate_json(ownership, declare)

    assert generate_inventory(root, ownership)["ir_artifacts"] == [
        {
            "grain": "ir_artifact",
            "path": ir_path,
            "raw_sha256": hashlib.sha256(b"<TEI/>\n").hexdigest(),
            "rendering_id": "asv:scrollmapper-json",
        }
    ]

    _mutate_json(
        ownership,
        lambda payload: payload["ir_artifacts"][0].__setitem__(
            "rendering_id", "asv:other-rendering"
        ),
    )
    with pytest.raises(InventoryError, match="bounded rendering"):
        generate_inventory(root, ownership)


@pytest.mark.parametrize(
    ("field", "value"),
    [("work", "rendering"), ("member", "work"), ("canonical_artifact", "source_artifact")],
)
def test_grain_mixing_fails_closed(
    small_repo: tuple[Path, Path], field: str, value: str
) -> None:
    root, ownership = small_repo
    _mutate_json(ownership, lambda payload: payload["grains"].__setitem__(field, value))

    with pytest.raises(InventoryError, match="grain mixing"):
        generate_inventory(root, ownership)


@pytest.mark.parametrize("bad_path", ["/raw/ASV.json", "raw\\ASV.json", "raw/../ASV.json"])
def test_noncanonical_repository_path_fails_closed(
    small_repo: tuple[Path, Path], bad_path: str
) -> None:
    root, ownership = small_repo
    _mutate_json(
        ownership,
        lambda payload: payload["source_artifact"].__setitem__("path", bad_path),
    )

    with pytest.raises(InventoryError, match="repository-relative|canonical"):
        generate_inventory(root, ownership)


@pytest.mark.parametrize("catalog_defect", ["removed", "duplicated", "count"])
def test_catalog_identity_defects_fail_closed(
    small_repo: tuple[Path, Path], catalog_defect: str
) -> None:
    root, ownership = small_repo
    identity = root / "cvw_phase1a/fixtures/work_catalog_identity.json"
    payload = json.loads(identity.read_bytes())
    if catalog_defect == "removed":
        payload["works"] = []
    elif catalog_defect == "duplicated":
        payload["works"].append(payload["works"][0].copy())
    else:
        payload["works"][0]["file_count"] = 3
    identity.write_bytes(_json_bytes(payload))

    with pytest.raises(InventoryError, match="exactly one|count drifted"):
        generate_inventory(root, ownership)


def test_author_qualified_catalog_identity_disambiguates_duplicate_titles(
    small_repo: tuple[Path, Path],
) -> None:
    root, ownership = small_repo
    identity = root / "cvw_phase1a/fixtures/work_catalog_identity.json"
    payload = json.loads(identity.read_bytes())
    payload["works"].append(
        {
            **payload["works"][0],
            "author": "Another Author",
            "work_id": "another-asv",
        }
    )
    identity.write_bytes(_json_bytes(payload))

    assert generate_inventory(root, ownership)["catalog_snapshot"]["file_count"] == 2


def test_catalog_markdown_is_bound_as_presentation_not_interpreted(
    small_repo: tuple[Path, Path],
) -> None:
    root, ownership = small_repo
    catalog = root / "docs/WORK_CATALOG.md"
    catalog.write_text("Presentation changed without changing identity.\n", encoding="utf-8")

    inventory = generate_inventory(root, ownership)

    assert inventory["catalog_snapshot"]["file_count"] == 2
    assert next(item for item in inventory["dependencies"] if item["role"] == "catalog")[
        "raw_sha256"
    ] == hashlib.sha256(catalog.read_bytes()).hexdigest()


def test_descriptor_count_drift_fails_closed(small_repo: tuple[Path, Path]) -> None:
    root, ownership = small_repo
    _mutate_json(
        ownership,
        lambda payload: payload["catalog"].__setitem__("expected_file_count", 3),
    )

    with pytest.raises(InventoryError, match="descriptor count drifted"):
        generate_inventory(root, ownership)


def test_canonical_member_identity_mismatch_fails_closed(
    small_repo: tuple[Path, Path],
) -> None:
    root, ownership = small_repo
    _mutate_json(
        root / "data/bible-text/asv/genesis.json",
        lambda payload: payload["meta"]["scope"].__setitem__("book", "Exodus"),
    )

    with pytest.raises(InventoryError, match="identity does not match"):
        generate_inventory(root, ownership)


def test_serialize_rejects_non_json_payload() -> None:
    with pytest.raises(InventoryError):
        serialize_inventory({"bad": object()})


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
def test_serialize_rejects_nonfinite_json_values(
    small_repo: tuple[Path, Path], nonfinite: float
) -> None:
    root, ownership = small_repo
    payload = generate_inventory(root, ownership)
    payload["catalog_snapshot"]["file_count"] = nonfinite

    with pytest.raises(InventoryError, match="not JSON serializable"):
        serialize_inventory(payload)


def test_serialize_rejects_mapping_that_violates_the_closed_schema(
    small_repo: tuple[Path, Path],
) -> None:
    root, ownership = small_repo
    payload = generate_inventory(root, ownership)
    payload["invented_root_field"] = []

    with pytest.raises(InventoryError, match="does not validate"):
        serialize_inventory(payload)
