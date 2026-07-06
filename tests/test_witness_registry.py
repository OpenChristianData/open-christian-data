import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib._generated_enums import (  # noqa: E402
    WITNESS_REGISTRY__RIGHTS_STATUS,
    WITNESS_REGISTRY__SOURCE_TYPE,
)
from build.tools.witness_registry import (  # noqa: E402
    WitnessRecord,
    list_witnesses_for_resource,
    load_witness_registry,
    metadata_for_witness,
    validate_witness_registry,
)


TEST_TMP = REPO_ROOT / "tests" / "_tmp_witness_registry"
SOURCE_TYPE_VALUES = ("scan", "ocr", "html", "epub", "hand_corrected_text", "transcription", "unknown")
LEGACY_RIGHTS_STATUS_VALUES = ("public-domain-source", "comparison-only")


def _case_dir(name: str) -> Path:
    path = TEST_TMP / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _record(**overrides) -> dict:
    record = {
        "witness_id": "sample-witness",
        "related_resource_id": "sample-commentary",
        "related_work_title": "Sample Commentary",
        "author": "Test Author",
        "witness_title": "Sample Witness",
        "source_url": "https://example.test/witness",
        "source_type": "html",
        "rights_status": "comparison-only",
        "edition_note": "Synthetic fixture.",
        "provider": "Example Provider",
        "local_path": None,
        "notes": "No source text is copied here.",
    }
    record.update(overrides)
    return record


def _write_registry(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"witnesses": records}), encoding="utf-8")
    return path


def test_valid_registry_loads():
    path = _write_registry(_case_dir("valid") / "registry.json", [_record()])

    records = load_witness_registry(path)

    assert records == [
        WitnessRecord(
            witness_id="sample-witness",
            related_resource_id="sample-commentary",
            related_work_title="Sample Commentary",
            author="Test Author",
            witness_title="Sample Witness",
            source_url="https://example.test/witness",
            source_type="html",
            rights_status="comparison-only",
            edition_note="Synthetic fixture.",
            provider="Example Provider",
            local_path=None,
            notes="No source text is copied here.",
        )
    ]


def test_generated_source_type_enum_preserves_legacy_values():
    assert set(SOURCE_TYPE_VALUES).issubset(WITNESS_REGISTRY__SOURCE_TYPE)


def test_generated_rights_status_enum_preserves_legacy_values():
    assert set(LEGACY_RIGHTS_STATUS_VALUES).issubset(WITNESS_REGISTRY__RIGHTS_STATUS)


def test_registry_accepts_generated_enum_values_beyond_legacy_set():
    path = _write_registry(
        _case_dir("generated_enum_broadened") / "registry.json",
        [
            _record(
                source_type="hocr_pair",
                rights_status="public-domain-derivative",
            )
        ],
    )

    records = load_witness_registry(path)

    assert records[0].source_type == "hocr_pair"
    assert records[0].rights_status == "public-domain-derivative"


def test_duplicate_witness_id_fails():
    path = _write_registry(_case_dir("duplicate") / "registry.json", [_record(), _record()])

    with pytest.raises(ValueError, match="Duplicate witness_id: sample-witness"):
        load_witness_registry(path)


def test_invalid_source_type_fails():
    path = _write_registry(_case_dir("bad_source_type") / "registry.json", [_record(source_type="PDF")])

    with pytest.raises(ValueError, match="Invalid source_type"):
        load_witness_registry(path)


def test_invalid_rights_status_fails():
    path = _write_registry(_case_dir("bad_rights") / "registry.json", [_record(rights_status="copyrighted")])

    with pytest.raises(ValueError, match="Invalid rights_status"):
        load_witness_registry(path)


def test_list_by_resource_returns_only_matching_witnesses():
    path = _write_registry(
        _case_dir("list_by_resource") / "registry.json",
        [
            _record(witness_id="sample-1", related_resource_id="sample-commentary"),
            _record(witness_id="other-1", related_resource_id="other-commentary"),
        ],
    )

    records = list_witnesses_for_resource(path, "sample-commentary")

    assert [record.witness_id for record in records] == ["sample-1"]


def test_validate_witness_registry_returns_records():
    path = _write_registry(_case_dir("validate") / "registry.json", [_record()])

    assert len(validate_witness_registry(path)) == 1


def test_metadata_for_witness_returns_comparison_metadata():
    path = _write_registry(_case_dir("metadata") / "registry.json", [_record()])

    metadata = metadata_for_witness(path, "sample-witness")

    assert metadata.title == "Sample Witness"
    assert metadata.source_url == "https://example.test/witness"
    assert metadata.source_type == "html"
    assert metadata.rights_status == "comparison-only"
    assert metadata.edition_note == "Synthetic fixture."
