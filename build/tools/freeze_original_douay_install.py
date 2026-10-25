"""Bind the exact durable Douay stage, source proof, and current install runtime."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ocd_kernel.library.identities import validate_identity_update
from ocd_kernel.tei.install_accepted import _files

from build.tools.stage_original_douay_current import ROOT, WORK, EDITION


LOG = ROOT / "reports/_logs/original-douay-rheims-current-reconciliation-20261002-v1"
PROMOTED = Path("D:/Library/Open Christian Data/candidate-reviews/original-douay-current-20261002-v2-promoted")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/original-douay-current-20261002-v2-stage")
PINS = [
    "schemas/v2/categories/bible.schema.json",
    "schemas/v2/work.schema.json",
    "ocd_kernel/projection/categories/bible.py",
    "ocd_kernel/projection/envelope.py",
    "ocd_kernel/tei/acceptance.py",
    "ocd_kernel/tei/install_accepted.py",
    "ocd_kernel/tei/reviewed_integration.py",
    "ocd_kernel/release/notices.py",
    "ocd_kernel/release/public_allowlist.py",
    "build/tools/stage_original_douay_current.py",
    "build/tools/stage_original_douay_notices.py",
    "build/tools/check_original_douay_companion_v2.py",
    "build/tools/check_original_douay_release_notices.py",
    "build/tools/check_original_douay_rollback.py",
    "build/tools/install_original_douay_current.py",
]


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_bytes())


def main() -> None:
    stage = STAGE.resolve(strict=True)
    promoted = PROMOTED.resolve(strict=True)
    if stage != STAGE or promoted != PROMOTED:
        raise ValueError("Exact durable candidate-review paths changed")
    location = read_json(LOG / "durable-stage-location.json")
    receipt_bytes = (promoted / "stage-receipt.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    rollback_bytes = (ROOT / ".tmp_audit/original-douay-rollback-proof.json").read_bytes()
    rollback = json.loads(rollback_bytes)
    derivative_bytes = (LOG / "readable-companion-v2-release-proof.json").read_bytes()
    derivative = json.loads(derivative_bytes)
    header_bytes = (promoted / WORK / "integration/original-douay-current-v1/header-rebinding.json").read_bytes()
    header = json.loads(header_bytes)
    if (location["status"] != "pass" or location["stage_receipt_sha256"] != sha(receipt_bytes)
            or receipt["status"] != "pass" or receipt["work_id"] != "original-douay-rheims"
            or receipt["human_acceptance"] != "not-recorded" or receipt["public_publication"] != "not-authorized"
            or receipt["projection_rows"] != 37181 or receipt["projection_errors"]
            or rollback["status"] != "pass" or rollback["stage_receipt_sha256"] != sha(receipt_bytes)
            or not rollback["original_canonical_preimage_restored"]
            or derivative["status"] != "pass" or derivative["native_nonverse_fields"] != 25145
            or derivative["literal_nonverse_utf8_bytes"] != 3781838
            or derivative["whitespace_bound_italic_spans"] != 4
            or header["status"] != "pass" or not header["inverse_restores_original_candidate"]
            or not header["body_unchanged"] or header["bound_candidate_sha256"] != receipt["bound_master_sha256"]
            or _files(ROOT / WORK) != receipt["before"] or _files(promoted / WORK) != receipt["after"]):
        raise ValueError("Promoted Douay, canonical preimage, or independent proof changed")
    before_work = (ROOT / WORK / "work.json").read_bytes()
    after_work = (promoted / WORK / "work.json").read_bytes()
    original = json.loads(before_work)
    revised = json.loads(after_work)
    exact = json.loads(json.dumps(original))
    edition = exact["textual_forms"][0]["editions"][0]
    if original["work_id"] != "original-douay-rheims" or "category" in edition:
        raise ValueError("Exact Douay category prerequisite preimage differs")
    edition["category"] = "bible"
    if revised != exact:
        raise ValueError("Staged work metadata differs by more than category=bible")
    validate_identity_update(original, revised)
    credit = (promoted / WORK / "SOURCE_CREDIT.md").read_bytes()
    source_credit = (promoted / "sources/original-douay-existing-native-current/original-douay-rheims/README.source.md").read_bytes()
    data_credit = (promoted / "data/bible/original-douay-rheims/README.md").read_bytes()
    if credit != source_credit or credit != data_credit:
        raise ValueError("Full three-way source and data-path credits differ")
    notice_bindings = read_json(promoted / "original-douay-notice-bindings.json")
    if (notice_bindings["status"] != "pass" or notice_bindings["notice_count"] != 170
            or notice_bindings["companion_manifest_sha256"] != derivative["markdown_manifest_sha256"]):
        raise ValueError("Release notice manifest differs from native derivative proof")
    if (promoted / EDITION / "master.tei.xml").read_bytes() != (promoted / WORK / "integration/original-douay-current-v1/candidate.tei.xml").read_bytes():
        raise ValueError("Promoted master and accepted integration candidate differ")
    result = {
        "status": "pass",
        "work_id": "original-douay-rheims",
        "canonical_install": False,
        "durable_stage": str(stage),
        "durable_promoted": str(promoted),
        "stage_receipt_sha256": sha(receipt_bytes),
        "rollback_proof_sha256": sha(rollback_bytes),
        "markdown_derivative_proof_sha256": sha(derivative_bytes),
        "header_inverse_sha256": sha(header_bytes),
        "before_work_sha256": sha(before_work),
        "after_work_sha256": sha(after_work),
        "metadata_prerequisite": "only textual_forms[0].editions[0].category=bible",
        "before": receipt["before"],
        "after": receipt["after"],
        "bound_master_sha256": receipt["bound_master_sha256"],
        "original_candidate_sha256": receipt["candidate_content_sha256"],
        "full_paired_credit_sha256": sha(credit),
        "notice_bindings_sha256": sha((promoted / "original-douay-notice-bindings.json").read_bytes()),
        "notice_count": 170,
        "native_nonverse_fields": 25145,
        "literal_nonverse_utf8_bytes": 3781838,
        "source_line_breaks": derivative["native_line_breaks"],
        "source_inline_styles": derivative["native_inline_styles"],
        "whitespace_bound_italic_spans": 4,
        "runtime_schema_pins": {relative: sha((ROOT / relative).read_bytes()) for relative in PINS},
    }
    target = LOG / "coordinator-install-freeze.json"
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in {"before", "after", "runtime_schema_pins"}}, indent=2))


if __name__ == "__main__":
    main()
