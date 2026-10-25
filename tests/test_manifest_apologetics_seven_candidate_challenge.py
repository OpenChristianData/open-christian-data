"""Recheck the seven retained-source apologetics candidates and mutations."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from functools import lru_cache
from pathlib import Path
import sys

import pytest

from build.lib.pytest_skips import skip_if_missing_data

pytestmark = pytest.mark.requires_local_artifacts

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_ROOT = WORKSPACE_ROOT / "plans" / "2026-09-23-acquisition-manifest-source-to-tei"
AUDIT_PATH = CAMPAIGN_ROOT / "APOLOGETICS_SEVEN_TECHNICAL_20260927.json"
if not AUDIT_PATH.is_file():
    pytest.skip("historical apologetics audit is not installed", allow_module_level=True)
AUDIT = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
EXECUTION_ROOT = Path(AUDIT["execution_root"])

# The original routes were built and checked in this execution checkout. Put
# that exact checkout first so this test invokes the bound oracle and contracts.
sys.path.insert(0, str(EXECUTION_ROOT))

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest  # noqa: E402
from ocd_kernel.tei.validate import compiled_schema  # noqa: E402

_ORACLE_PATH = EXECUTION_ROOT / "build" / "tei" / "apologetics_seven_pg_oracle_v4.py"


@lru_cache(maxsize=1)
def _bound_oracle():
    skip_if_missing_data(_ORACLE_PATH)
    spec = importlib.util.spec_from_file_location("_manifest_apologetics_pg_oracle_v4", _ORACLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._oracle


def _oracle(source, candidate):
    return _bound_oracle()(source, candidate)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _routes() -> list[dict[str, object]]:
    return AUDIT["works"]


def _route(ebook_id: str) -> dict[str, object]:
    return next(work for work in _routes() if work["ebook_id"] == ebook_id)


@lru_cache(maxsize=None)
def _bound_baseline(ebook_id: str) -> tuple[SourceManifest, CandidatePackage, dict[str, object]]:
    _bound_oracle()
    work = _route(ebook_id)
    manifest_path = Path(work["source_manifest_path"])
    assert manifest_path.is_file(), f"missing exact source manifest: {manifest_path}"
    assert _sha(manifest_path) == work["source_manifest_sha256"]
    source = SourceManifest.load(manifest_path, repository_root=EXECUTION_ROOT)

    candidate_root = Path(work["candidate_path"])
    package_root = candidate_root / "package"
    package_manifest = package_root / "manifest.json"
    validation_path = Path(work["validation_path"])
    assert _sha(package_manifest) == work["candidate_package_sha256"]
    assert _sha(package_root / "content.tei.xml") == work["tei_sha256"]
    assert _sha(validation_path) == work["validation_sha256"]

    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    assert validation["status"] == "pass"
    assert validation["candidate_sha256"] == work["candidate_package_sha256"]
    assert validation["source_manifest_sha256"] == work["source_manifest_sha256"]
    assert validation["attestation"]["profile_sha256"] == hashlib.sha256(
        source.authority_path("profile").read_bytes()
    ).hexdigest()

    candidate = CandidatePackage.load(package_root)
    package_record = json.loads(package_manifest.read_text(encoding="utf-8"))
    assert package_record["source_manifest"]["sha256"] == work["source_manifest_sha256"]
    assert package_record["source_id"] == source.record["source_id"]
    assert package_record["status"] == "nonaccepted"
    oracle_result = _oracle(source, candidate)
    assert oracle_result["status"] == "pass"
    return source, candidate, oracle_result


@pytest.mark.parametrize("work", _routes(), ids=lambda work: str(work["ebook_id"]))
def test_current_candidate_is_bound_to_exact_source_and_profile(work: dict[str, object]) -> None:
    _, _, result = _bound_baseline(str(work["ebook_id"]))
    assert result["status"] == "pass"


@pytest.mark.parametrize(
    ("work", "mutation", "reason"),
    [
        (work, mutation, reason)
        for work in _routes()
        for mutation, reason in (
            ("text", "source carrier text mutation"),
            ("order", "source carrier order/tail mutation"),
        )
    ],
    ids=lambda value: str(value["ebook_id"]) if isinstance(value, dict) and "ebook_id" in value else None,
)
def test_source_grounded_p5_valid_text_and_order_mutations_are_rejected(
    work: dict[str, object], mutation: str, reason: str
) -> None:
    source, _, baseline_result = _bound_baseline(str(work["ebook_id"]))
    assert baseline_result["status"] == "pass"

    receipt_path = Path(work["mutation_receipt_path"])
    assert _sha(receipt_path) == work["mutation_receipt_sha256"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["baseline_pass"] is True
    assert receipt["baseline_package_sha256"] == work["candidate_package_sha256"]
    check = next(item for item in receipt["checks"] if item["mutation"] == mutation)
    assert check["p5_valid"] is True
    assert check["rejected"] is True

    mutated_package = CandidatePackage.load(Path(check["package_path"]))
    xml = mutated_package.member_bytes("content.tei.xml")
    from lxml import etree

    tree = etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    assert compiled_schema().validate(tree), f"{work['ebook_id']} {mutation} mutation is not P5-valid"
    with pytest.raises(ValueError, match=reason):
        _oracle(source, mutated_package)
