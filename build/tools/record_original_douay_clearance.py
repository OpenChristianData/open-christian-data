"""Record coordinator review of the exact Douay install freeze before apply."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "reports/_logs/original-douay-rheims-current-reconciliation-20261002-v1"
FREEZE = LOG / "coordinator-install-freeze.json"
EXPECTED_FREEZE = "bba49ab37609479bb821d98c37ba5f181098d4c525f9fbf208967169b988c4eb"


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    raw = FREEZE.read_bytes()
    frozen = json.loads(raw)
    if (sha(raw) != EXPECTED_FREEZE or frozen["status"] != "pass"
            or frozen["stage_receipt_sha256"] != "45ca40da33cfa82cb4d13dfcf91c4e7b61ed726ffd6af8dc5d9af28d686222fe"
            or frozen["bound_master_sha256"] != "b087c520e62b7796b889072daf39259d263d1cc1f18930b19b33e2ee36161b16"
            or frozen["markdown_derivative_proof_sha256"] != "f3e9d319449ffeaefaa2fe728dc5dc21a4a5474b07e0fbbc22f282e0372d25dc"
            or frozen["rollback_proof_sha256"] != "918418a7ada056e196ef7433ab798ba33f25ae1e2b99ec5fa57bc0640e9aac81"
            or len(frozen["runtime_schema_pins"]) != 15 or frozen["notice_count"] != 170):
        raise ValueError("Coordinator-reviewed Douay install freeze differs")
    target = LOG / "coordinator-install-clearance.json"
    if target.exists():
        raise FileExistsError("Douay clearance must not be overwritten")
    record = {
        "status": "cleared-for-scoped-guarded-install",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": "root coordinator",
        "freeze_sha256": sha(raw),
        "stage_receipt_sha256": frozen["stage_receipt_sha256"],
        "bound_master_sha256": frozen["bound_master_sha256"],
        "markdown_derivative_proof_sha256": frozen["markdown_derivative_proof_sha256"],
        "header_inverse_sha256": frozen["header_inverse_sha256"],
        "rollback_proof_sha256": frozen["rollback_proof_sha256"],
        "reviewed_observations": [
            "32 promoted work files and four canonical preimage files agree with freeze",
            "15 current runtime and schema pins agree with freeze",
            "169 source-context Markdown part hashes agree with release manifest",
            "native TEI text body is byte-equal across accepted header binding",
            "sole canonical work metadata prerequisite is category=bible",
            "independent direct JSON proof covers all 62,326 source fields",
        ],
        "authorization_scope": "Original Douay-Rheims exact guarded canonical work install and private offline release",
        "human_acceptance": "not-recorded",
        "rights_clearance": "not-established",
        "public_publication": "not-authorized",
    }
    target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
