from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "sources/structured-text/church-fathers-quotations/church-fathers-quotations.source-manifest.json"
ROUTE = ROOT / "sources/structured-text/church-fathers-quotations"
RAW_TREE = ROOT / "raw/Commentaries-Database"
KNOWN_CANDIDATE = Path(r"C:\tmp\lib061-route-candidate-d")
pytestmark = pytest.mark.skipif(not RAW_TREE.exists(), reason="retained Commentaries-Database tree is not available")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_route_binds_complete_source_envelope_and_work_scope():
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    equality = json.loads((ROUTE / "source-member-equality.json").read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert source.record["source_id"] == source.record["work_id"] == "church-fathers-quotations"
    assert manifest["expression_scope"]["status"] == "complete"
    assert manifest["catalog_claim_lineage"]["claim_count"] == 325
    assert equality["archive"]["member_count"] == 59021
    assert equality["archive"]["regular_file_count"] == 58682
    assert equality["archive"]["toml_file_count"] == 58675
    assert equality["member_equality"]["matched_regular_file_count"] == 58682
    assert equality["member_equality"]["mismatch_count"] == 0
    assert equality["member_equality"]["missing_member_count"] == 0


def test_candidate_integrity_rejects_unresealed_content_mutation(tmp_path):
    if not KNOWN_CANDIDATE.exists():
        pytest.skip("fresh LIB-061 candidate evidence is not available")
    candidate = CandidatePackage.load(KNOWN_CANDIDATE)
    target = tmp_path / "mutated"
    target.mkdir()
    for name in candidate.member_names:
        (target / name).write_bytes(candidate.member_bytes(name))
    content_path = target / "content.tei.xml"
    content = content_path.read_bytes()
    needle = b"Nonaccepted reconstruction candidate; publication not ready"
    assert content.count(needle) == 1
    mutated = content.replace(needle, needle + b"?")
    content_path.write_bytes(mutated)
    with pytest.raises(ValueError, match=r"content\.tei\.xml bytes drifted"):
        CandidatePackage.load(target)


def test_oracle_import_closure_is_explicit_and_independent():
    closure = json.loads((ROUTE / "oracle-import-closure.json").read_text(encoding="utf-8"))
    oracle_text = (ROOT / "build/tei/church_fathers_oracle.py").read_text(encoding="utf-8")
    assert closure["contract"] == "ocd-lib061-oracle-import-closure-v1"
    assert closure["forbidden_imports"] == ["build.tei.church_fathers_reconstruction", "build.parsers.church_fathers"]
    assert all(forbidden not in oracle_text for forbidden in closure["forbidden_imports"])
    assert _sha((ROOT / "build/tei/church_fathers_oracle.py").read_bytes()) == next(
        item["sha256"] for item in closure["files"] if item["path"] == "build/tei/church_fathers_oracle.py"
    )
