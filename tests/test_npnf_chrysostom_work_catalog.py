from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

import pytest

from build.tei.npnf_chrysostom_oracle import _oracle
from build.tei.npnf_chrysostom_reconstruction import ASSIGNED, _convert
from tests.runtime_candidate_baselines import current_runtime_catalog
from ocd_kernel.reconstruction import SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.slow
SOURCE_ID = "ccel-npnf-chrysostom-110-111-112-114-retained-xml"
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/npnf-chrysostom.source-manifest.json"


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


@pytest.fixture(scope="module")
def catalog_with_evidence():
    with tempfile.TemporaryDirectory(prefix="npnf-chrysostom-catalog-") as directory:
        output = Path(directory)
        source = SourceManifest.load(MANIFEST, repository_root=ROOT)
        candidate = reconstruct(source, output / "candidate", _convert)
        validation = validate(source, candidate, _oracle)
        record = {
            "contract": "ocd-validation-report-v1",
            "status": validation.status,
            "candidate_sha256": validation.candidate_sha256,
            "source_manifest_sha256": validation.source_manifest_sha256,
            "attestation": dict(validation.attestation),
            "findings": list(validation.findings),
        }
        assert hashlib.sha256(_canonical(record)).hexdigest() == validation.sha256
        validation_path = output / "validation.json"
        validation_path.write_bytes(
            _canonical({**record, "report_sha256": validation.sha256})
        )
        evidence = {
            (SOURCE_ID, work_id): (candidate.path, validation_path)
            for _, _, work_id in ASSIGNED
        }
        yield (
            current_runtime_catalog(root=ROOT, manifest=MANIFEST,
                work_ids=[work_id for _, _, work_id in ASSIGNED], reconstruction_evidence=evidence),
            candidate,
            validation_path,
        )


def test_all_seven_chrysostom_routes_are_verified_and_nonaccepted(
    catalog_with_evidence,
) -> None:
    catalog, candidate, validation_path = catalog_with_evidence
    by_id = {work["work_id"]: work for work in catalog.works}
    assert candidate.path.is_dir()
    assert validation_path.is_file()
    for _, _, work_id in ASSIGNED:
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


def test_catalog_rejects_unused_chrysostom_runtime_evidence() -> None:
    with pytest.raises(ValueError, match="does not bind"):
        current_runtime_catalog(
            root=ROOT, manifest=MANIFEST, work_ids=[work_id for _, _, work_id in ASSIGNED],
            reconstruction_evidence={
                (SOURCE_ID, "not-an-assigned-work"): (
                    Path("missing-candidate"),
                    Path("missing-validation"),
                )
            },
        )
