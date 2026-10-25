from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.tei.npnf105_oracle import validate_candidate, validation_record
from build.tei.npnf105_reconstruction import ASSIGNED, reconstruct_candidate
from tests.runtime_candidate_baselines import current_runtime_catalog
from ocd_kernel.reconstruction.contract import SourceManifest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.slow
SOURCE_ID = "ccel-npnf105-retained-xml"
MANIFEST_PATH = ROOT / "tests/fixtures/reconstruction-runtime/npnf105.source-manifest.json"


@pytest.fixture(scope="module")
def catalog_with_evidence(tmp_path_factory: pytest.TempPathFactory):
    output = tmp_path_factory.mktemp("npnf105-catalog")
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    candidate = reconstruct_candidate(manifest, output / "candidate")
    validation = validate_candidate(manifest, candidate)
    validation_path = output / "validation.json"
    validation_path.write_text(json.dumps(validation_record(validation), ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    evidence = {(SOURCE_ID, work_id): (candidate.path, validation_path) for _, work_id in ASSIGNED}
    return current_runtime_catalog(root=ROOT, manifest=MANIFEST_PATH,
        work_ids=[work_id for _, work_id in ASSIGNED], reconstruction_evidence=evidence), candidate, validation_path


def test_all_twelve_npnf105_routes_are_candidate_and_validation_verified(catalog_with_evidence) -> None:
    catalog, candidate, validation_path = catalog_with_evidence
    by_id = {work["work_id"]: work for work in catalog.works}
    assert candidate.path.is_dir()
    assert validation_path.is_file()
    for _, work_id in ASSIGNED:
        state = by_id[work_id]["reconstruction_state"]
        assert state["retained_source"] == "manifest_bound"
        assert state["tei_candidate"] == "verified"
        assert state["validation"] == "verified"
        assert state["human_review"] == "required"
        assert state["accepted_ir"] == "not_accepted"
        assert state["publication"] == "not_ready"
        routes = [route for route in state["routes"] if route["source_id"] == SOURCE_ID]
        assert len(routes) == 1
        assert routes[0]["association"] == "source_hash+exact_id"
        assert routes[0]["scope"] == "work"
        assert routes[0]["candidate_verification"] == "verified"
        assert routes[0]["validation_verification"] == "verified"


def test_catalog_rejects_unused_or_misbound_runtime_evidence() -> None:
    with pytest.raises(ValueError, match="does not bind"):
        current_runtime_catalog(
            root=ROOT, manifest=MANIFEST_PATH, work_ids=[work_id for _, work_id in ASSIGNED],
            reconstruction_evidence={(SOURCE_ID, "not-an-assigned-work"): (Path("missing-candidate"), Path("missing-validation"))},
        )
