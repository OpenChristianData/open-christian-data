import base64
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ocd_kernel.lib.schema_enums import resolve_schema_path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _schema(name: str) -> dict:
    return json.loads(resolve_schema_path(name).read_text(encoding="utf-8"))


RECONCILED_SCHEMA = _schema("reconciled_record")
MODERNISED_SCHEMA = _schema("modernised_record")
CATALOG_SCHEMA = _schema("rendering_catalog")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _record(
    *,
    work_id: str,
    title: str,
    schema_type: str = "reconciled_record",
    paired_with: str | None = None,
) -> dict:
    ruleset = "en@1.0.0" if schema_type == "modernised_record" else None
    meta = {
        "id": f"{work_id}/0001",
        "title": title,
        "author_slug": "fixture-author",
        "author_display_name": "Fixture Author",
        "author_birth_year": None,
        "author_death_year": None,
        "original_publication_year": 2000,
        "language": "en",
        "tradition": ["reformed"],
        "license": "public-domain",
        "schema_type": schema_type,
        "schema_version": "3.0.0",
        "edition": "2000",
        "pd_anchor": "fixture-anchor",
        "modernisation_ruleset_version": ruleset,
        "attestation_summary": {
            "block_count": 1,
            "fully_attested_blocks": 1,
            "blocks_with_disagreements": 0,
            "blocks_with_structural_disagreements": 0,
        },
    }
    if paired_with is not None:
        meta["paired_with"] = paired_with

    return {
        "meta": meta,
        "blocks": [
            {
                "block_id": "0001-p1",
                "block_id_history": [],
                "block_type": "paragraph",
                "language": "en",
                "language_confidence": 1.0,
                "language_alternates": [],
                "language_segments": [],
                "original_text": f"{title} original text.",
                "modern_text": f"{title} modern text.",
                "annotations": {},
                "source_pages": [{"rendering_id": "fixture-anchor", "page_number": 1}],
                "attested_by": ["fixture-anchor"],
                "disagreements": [],
                "structural_disagreements": [],
                "modernisations": [],
            }
        ],
        "match_explanations": [],
    }


def _catalog(work_id: str) -> dict:
    return {
        "work_id": work_id,
        "edition": "2000",
        "modernisation_intent": "intended",
        "pd_anchor_decision": {
            "chosen_rendering": "fixture-anchor",
            "rationale": "Fixture anchor selected for deterministic publisher tests.",
            "decided_at": "2026-05-17T00:00:00Z",
            "alternates_considered": [
                {
                    "rendering_id": "fixture-attestor",
                    "rejected_because": "Fixture alternate for catalog coverage.",
                }
            ],
        },
        "renderings": [
            {
                "rendering_id": "fixture-anchor",
                "role": "pd_anchor",
                "source": "fixture",
                "format": "plain",
                "license": "public-domain",
            },
            {
                "rendering_id": "fixture-attestor",
                "role": "pd_attestor",
                "source": "fixture",
                "format": "plain",
                "license": "public-domain",
            },
        ],
    }


def _validate_and_write(path: Path, payload: dict, schema: dict) -> None:
    Draft202012Validator(schema).validate(payload)
    _write_json(path, payload)


def _stage_work(
    tmp_path: Path,
    *,
    work_slug: str,
    title: str,
    with_modernised: bool,
) -> None:
    work_id = f"reference/{work_slug}"
    work_dir = tmp_path / "data" / "reference" / work_slug / "2000"
    _validate_and_write(work_dir / "catalog.json", _catalog(work_id), CATALOG_SCHEMA)
    _validate_and_write(
        work_dir / "original" / "0001.json",
        _record(work_id=work_id, title=title),
        RECONCILED_SCHEMA,
    )
    if with_modernised:
        _validate_and_write(
            work_dir / "modernised" / "0001.json",
            _record(
                work_id=work_id,
                title=title,
                schema_type="modernised_record",
                paired_with=f"data/reference/{work_slug}/2000/original/0001.json",
            ),
            MODERNISED_SCHEMA,
        )


def _stage_export_fixture(tmp_path: Path, *, include_work_c: bool = False) -> None:
    _stage_work(tmp_path, work_slug="work-a", title="Work A", with_modernised=False)
    _stage_work(tmp_path, work_slug="work-b", title="Work B", with_modernised=True)
    if include_work_c:
        _stage_work(tmp_path, work_slug="work-c", title="Work C", with_modernised=False)


def _short_hf_cache_root(caller_root: Path) -> Path:
    """Return a caller-path-independent cache root for HuggingFace test locks."""
    caller_key = os.path.normcase(os.path.abspath(os.fspath(caller_root)))
    digest = hashlib.sha256(caller_key.encode("utf-8")).digest()[:16]
    token = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return Path(tempfile.gettempdir()) / "h" / token


@pytest.fixture
def hf_cache_root(tmp_path: Path):
    cache_root = _short_hf_cache_root(tmp_path)
    if cache_root.exists():
        shutil.rmtree(cache_root)
    yield cache_root
    if cache_root.exists():
        shutil.rmtree(cache_root)


def _load_split(export_root: Path, config: str, cache_root: Path):
    from datasets import Dataset
    from datasets import load_dataset

    dataset = load_dataset(str(export_root), config, cache_dir=str(cache_root))
    split = dataset["train"] if isinstance(dataset, dict) else dataset
    assert isinstance(split, Dataset)
    return split


def _work_ids(dataset) -> set[str]:
    return {record["meta"]["id"].rsplit("/", 1)[0] for record in dataset}


@pytest.mark.slow
def test_exports_artefact_validates(tmp_path: Path, hf_cache_root: Path) -> None:
    _stage_export_fixture(tmp_path)

    from build.tools.export_hf_dataset import main

    export_root = tmp_path / "exports"
    assert main(["--data-root", str(tmp_path / "data"), "--output", str(export_root)]) == 0
    assert export_root.exists()

    dataset_infos = json.loads((export_root / "dataset_infos.json").read_text(encoding="utf-8"))
    assert set(dataset_infos) == {"original", "modernised"}

    original = _load_split(export_root, "original", hf_cache_root)
    modernised = _load_split(export_root, "modernised", hf_cache_root)
    assert len(original) == 2
    assert len(modernised) == 1


def test_two_config_split_correct(tmp_path: Path, hf_cache_root: Path) -> None:
    _stage_export_fixture(tmp_path)

    from build.tools.export_hf_dataset import main

    export_root = tmp_path / "exports"
    assert main(["--data-root", str(tmp_path / "data"), "--output", str(export_root)]) == 0

    assert _work_ids(_load_split(export_root, "original", hf_cache_root)) == {
        "reference/work-a",
        "reference/work-b",
    }
    assert _work_ids(_load_split(export_root, "modernised", hf_cache_root)) == {"reference/work-b"}

    card = (export_root / "README.md").read_text(encoding="utf-8")
    assert "| reference/work-a | present | absent |" in card


def test_coverage_gap_dataset_card_surfacing(tmp_path: Path) -> None:
    _stage_export_fixture(tmp_path, include_work_c=True)

    from build.tools.export_hf_dataset import main

    export_root = tmp_path / "exports"
    assert main(["--data-root", str(tmp_path / "data"), "--output", str(export_root)]) == 0

    card = (export_root / "README.md").read_text(encoding="utf-8")
    assert "work_handle | original | modernised | rationale" in card
    assert "| reference/work-a | present | absent |" in card
    assert "| reference/work-c | present | absent |" in card
    assert "| reference/schaff/encyclopedia/1908-1914 | present | absent |" in card
    schaff_row = next(
        line
        for line in card.splitlines()
        if line.startswith("| reference/schaff/encyclopedia/1908-1914 |")
    )
    assert "R43" in schaff_row


@pytest.mark.skipif(os.name != "nt", reason="Windows lock-path regression")
def test_hf_cache_root_is_independent_of_long_caller_path(tmp_path: Path) -> None:
    caller_root = tmp_path.joinpath(*(["caller-path-segment-abcdefghijklmnop"] * 12))
    cache_root = _short_hf_cache_root(caller_root)

    _stage_export_fixture(tmp_path)
    from build.tools.export_hf_dataset import main
    from datasets import load_dataset_builder

    export_root = tmp_path / "exports"
    assert main(["--data-root", str(tmp_path / "data"), "--output", str(export_root)]) == 0
    try:
        builder = load_dataset_builder(str(export_root), "original", cache_dir=str(cache_root))
        builder_cache = Path(builder._cache_dir)
        lock_path = cache_root / f"{builder_cache.as_posix().replace('/', '_')}.lock"

        assert len(os.fspath(lock_path)) <= 220
    finally:
        if cache_root.exists():
            shutil.rmtree(cache_root)

    assert len(os.fspath(caller_root)) > 260
    assert len(cache_root.name) == 22
    assert os.fspath(caller_root) not in os.fspath(cache_root)
    assert cache_root != _short_hf_cache_root(caller_root / "different")
