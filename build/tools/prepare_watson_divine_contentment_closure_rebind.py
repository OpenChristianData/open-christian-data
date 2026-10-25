"""Prepare a current Watson Contentment closure without changing acceptance.

The historical source manifest, candidate, CVW record, accepted master, and
acceptance sidecar remain immutable inputs.  This creates a versioned source
manifest and a fresh nonaccepted candidate for coordinated acceptance work.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from build.tei.watson_divine_contentment_oracle import _oracle, closure_digest
from build.tools.prepare_watson_divine_contentment_acceptance import _bind_existing_header
from build.tools.reconstruct_candidate import run as reconstruct_candidate
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate


ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_MANIFEST = Path(
    "sources/structured-text/watson-divine-contentment/"
    "watson-divine-contentment.source-manifest.json"
)
CURRENT_MANIFEST = HISTORICAL_MANIFEST.with_name(
    "watson-divine-contentment.source-manifest.closure-rebind-20260926.json"
)
EDITION = Path(
    "library/works/watson-divine-contentment/forms/"
    "watson-divine-contentment-english/editions/watson-divine-contentment-ccel-thml"
)
HISTORICAL_PACKAGE = Path(
    "library/works/watson-divine-contentment/integration/"
    "ccel-thml-agent-handoff/inputs/package"
)
HISTORICAL_CVW = Path(
    "library/works/watson-divine-contentment/integration/"
    "ccel-thml-agent-handoff/inputs/cvw/session-receipt.json"
)
RECEIPT = Path(
    "plans/2026-09-22-source-preflight/"
    "watson-divine-contentment-closure-rebind-20260926.json"
)
HISTORICAL_MANIFEST_SHA = "056e2f07288f95c86831de301e2b7981824236d224143207dfac8402c458e415"
HISTORICAL_PACKAGE_SHA = "cd4e3b055480a4ffa086fa45956d8cc0ab098f0e99ce252d7792d5890ee3c965"
HISTORICAL_CVW_SHA = "be0e14ef0c8bf29caa5f7c6aa2446552ae03a21c258f8a4d2ae7df1f7097b3fb"
SOURCE_SHA = "767ed95de4c4c990480670084e8dd1ac16b6c61d50b864e8b0202e528a076d7b"
MASTER_SHA = "c72641deb76db40c5fb95e2152b04df683ac714dbaee73f90cb9c62c31805e8f"
CURRENT_CLOSURE_SHA = "80493224832c2b47d7f5b8adbf6e1c997a3e13fd9c771f000983a5246db2d05d"
CHANGED_AUTHORITIES = {
    "closure-identities": (17861, "b579eb6795f870502156fd478361f9e58f7fbf8a05f16438092752ca28bb2cfa"),
    "closure-common": (4909, "f25a86bb45274d8880eacd37162ececa54ff0ef6979a17cb78d3459e752fd98c"),
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read_pinned(path: Path, expected_sha: str) -> bytes:
    content = path.read_bytes()
    if _sha(content) != expected_sha:
        raise ValueError(f"pinned Watson evidence changed: {path}")
    return content


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def prepare_manifest(root: Path = ROOT) -> SourceManifest:
    """Version only reviewed shared dependency bindings; preserve the source."""
    historical = json.loads(_read_pinned(root / HISTORICAL_MANIFEST, HISTORICAL_MANIFEST_SHA))
    current = json.loads(json.dumps(historical))
    if closure_digest(root) != CURRENT_CLOSURE_SHA:
        raise ValueError("Watson oracle import closure changed since review")
    for authority in current["authorities"]:
        replacement = CHANGED_AUTHORITIES.get(authority["name"])
        if replacement is None:
            continue
        size, digest = replacement
        actual = (root / authority["path"]).read_bytes()
        if len(actual) != size or _sha(actual) != digest:
            raise ValueError(f"reviewed shared dependency changed: {authority['name']}")
        authority["bytes"], authority["sha256"] = size, digest
    current["validator"]["import_closure_sha256"] = CURRENT_CLOSURE_SHA
    target = root / CURRENT_MANIFEST
    expected = (json.dumps(current, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if target.exists():
        if target.read_bytes() != expected:
            raise ValueError("versioned Watson source manifest already differs")
    else:
        target.write_bytes(expected)
    return SourceManifest.load(target, repository_root=root)


def audit_candidate(candidate: Path, *, root: Path = ROOT) -> dict[str, object]:
    """Prove the new oracle result and unchanged source and accepted TEI bytes."""
    manifest = SourceManifest.load(root / CURRENT_MANIFEST, repository_root=root)
    package = CandidatePackage.load(candidate / "package")
    if package.manifest["source_manifest"] != {
        "path": CURRENT_MANIFEST.as_posix(), "sha256": manifest.sha256
    }:
        raise ValueError("new candidate does not bind the versioned Watson source manifest")
    report = validate(manifest, package, _oracle)
    validation = json.loads((candidate / "validation.json").read_text(encoding="utf-8"))
    if (
        report.status != "pass"
        or validation.get("status") != "pass"
        or validation.get("findings") != []
        or validation.get("candidate_sha256") != package.sha256
        or validation.get("source_manifest_sha256") != manifest.sha256
        or validation.get("report_sha256") != report.sha256
    ):
        raise ValueError("new Watson validation sidecar does not bind the oracle result")

    historical = CandidatePackage.load(root / HISTORICAL_PACKAGE)
    if historical.sha256 != HISTORICAL_PACKAGE_SHA:
        raise ValueError("historical Watson candidate package changed")
    original = historical.member_bytes("content.tei.xml")
    if package.member_bytes("content.tei.xml") != original:
        raise ValueError("current Watson reconstruction changed reviewed TEI bytes")
    _read_pinned(root / HISTORICAL_CVW, HISTORICAL_CVW_SHA)
    source = manifest.authority_path("retained-source")
    _read_pinned(source, SOURCE_SHA)
    acceptance = json.loads((root / EDITION / "acceptance.json").read_text(encoding="utf-8"))
    revision = acceptance["representation_revision"]
    acquisition = json.loads((root / EDITION / "acquisitions/watson-divine-contentment-ccel-retained.json").read_text(encoding="utf-8"))
    master = _read_pinned(root / EDITION / "master.tei.xml", MASTER_SHA)
    if _bind_existing_header(original, acquisition, revision) != master:
        raise ValueError("reviewed Watson TEI does not reproduce installed master")
    return {
        "contract": "ocd-watson-divine-contentment-closure-rebind-v1",
        "status": "prepared-for-coordinated-acceptance",
        "source": {"path": "raw/ccel/watson/contentment.xml", "sha256": SOURCE_SHA},
        "historical": {
            "source_manifest_sha256": HISTORICAL_MANIFEST_SHA,
            "candidate_package_sha256": historical.sha256,
            "cvw_session_receipt_sha256": HISTORICAL_CVW_SHA,
        },
        "current": {
            "source_manifest_path": CURRENT_MANIFEST.as_posix(),
            "source_manifest_sha256": manifest.sha256,
            "oracle_import_closure_sha256": CURRENT_CLOSURE_SHA,
            "candidate_path": str(candidate.resolve(strict=True)),
            "candidate_package_sha256": package.sha256,
            "validation_sidecar_sha256": _sha((candidate / "validation.json").read_bytes()),
            "validation_report_sha256": report.sha256,
            "candidate_tei_sha256": _sha(package.member_bytes("content.tei.xml")),
        },
        "installed_master_sha256": MASTER_SHA,
        "reviewed_tei_bytes_identical": True,
        "installed_master_reproduced_from_current_candidate": True,
        "remaining": "Coordinate shared acceptance route pins and fresh acceptance evidence; no canonical acceptance or master was changed.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    args = parser.parse_args()
    manifest = prepare_manifest()
    candidate = args.candidate
    if candidate.exists():
        raise ValueError("Watson rebind candidate destination must be fresh")
    reconstruct_candidate(
        manifest=CURRENT_MANIFEST.as_posix(),
        destination=str(candidate),
        repository_root=str(ROOT),
    )
    receipt = audit_candidate(candidate)
    receipt["prepared_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    target = ROOT / RECEIPT
    if target.exists():
        raise ValueError("Watson rebind receipt already exists")
    target.write_bytes(_canonical(receipt))
    print(json.dumps({"receipt": RECEIPT.as_posix(), "candidate": str(candidate), "status": receipt["status"]}))


if __name__ == "__main__":
    main()
