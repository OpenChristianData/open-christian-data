"""Bind Smith's completed private release to installed and terminal evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "library/works/smiths-bible-dictionary"
OUT = ROOT / "reports/_logs/smiths-bible-dictionary-private-release-20261002-v1"
LOG = ROOT / "reports/_logs/smiths-bible-dictionary-current-reconciliation-20261002-v1"
INSTALLED_REVIEW = LOG / "coordinator-installed-generation-review.json"
INSTALLED_REVIEW_SHA = "fed527be1380f73af6d3d819aa3db06b847f734f59388cf3aed0b517e7d4eed3"
COMPLETION_SHA = "4e9a8d604d055eabf1918c27638101fe162fb52a817ed3a2c35b2252b8a5d6c6"
INSTALL_SHA = "539b333ac2f765758c72b93dcdeedad7d46dd9a1961c82f231268cf27603cf5a"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def main() -> None:
    completion_path = OUT / "completion.json"
    canonical_completion = WORK / "publication/completion.json"
    if (digest(completion_path) != COMPLETION_SHA or digest(canonical_completion) != COMPLETION_SHA
            or digest(INSTALLED_REVIEW) != INSTALLED_REVIEW_SHA
            or digest(LOG / "canonical-install-result.json") != INSTALL_SHA):
        raise ValueError("Smith completion or installed review binding drifted")
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    if completion["status"] != "pass" or completion["rows"] != 4560 or completion["definition_blocks"] != 5362 or completion["installed_receipt_sha256"] != INSTALL_SHA:
        raise ValueError("Smith private completion status/counts differ")
    gates = {}
    for name in ("assembly", "independent-verification", "statistics", "readers", "notice-gate", "released-notice-check"):
        path = OUT / f"{name}.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        if value["status"] != "pass":
            raise ValueError(f"Smith private release {name} did not pass")
        gates[name] = digest(path)
    for label, expected in completion["input_bindings"].items():
        if digest(ROOT / label) != expected:
            raise ValueError(f"Smith final bound input drifted: {label}")
    release = Path(completion["release_path"])
    for label, expected in completion["release_file_bindings"].items():
        if digest(release / label) != expected:
            raise ValueError(f"Smith final release file drifted: {label}")
    terminal = {
        "contract": "ocd-smith-private-release-terminal-corroboration-v1",
        "status": "exit-zero",
        "source_command": "py -3 -m build.tools.complete_smith_private_release --installed-receipt-sha256 " + INSTALL_SHA,
        "owned_session_id": 71405,
        "launch_chunk": "7f4e98",
        "assembly_chunk": "0842f5",
        "independent_verification_chunk": "04d782",
        "statistics_chunk": "f8d8b2",
        "terminal_chunk": "d94952",
        "terminal_exit_code": 0,
        "terminal_output": "readers: PASS; status=pass; rows=4560; release_file_count=7",
        "completion_sha256": COMPLETION_SHA,
        "installed_receipt_sha256": INSTALL_SHA,
        "coordinator_installed_review_sha256": INSTALLED_REVIEW_SHA,
    }
    terminal_path = OUT / "terminal-corroboration.json"
    save(terminal_path, terminal)
    delivery = {
        "contract": "ocd-smith-private-final-delivery-v1",
        "status": "ready-for-coordinator-final-audit",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "work_id": "smiths-bible-dictionary",
        "completion_sha256": COMPLETION_SHA,
        "canonical_completion_sha256": digest(canonical_completion),
        "terminal_corroboration_sha256": digest(terminal_path),
        "coordinator_installed_review_sha256": INSTALLED_REVIEW_SHA,
        "installed_receipt_sha256": INSTALL_SHA,
        "gate_sha256": gates,
        "input_binding_count": len(completion["input_bindings"]),
        "release_file_count": len(completion["release_file_bindings"]),
        "rows": completion["rows"],
        "definition_blocks": completion["definition_blocks"],
        "text_characters": completion["text_characters"],
        "human_decision": "not-recorded",
        "rights_clearance": "unresolved",
        "publication_performed": False,
    }
    delivery_path = OUT / "final-delivery.json"
    save(delivery_path, delivery)
    print(json.dumps({"status": "ready-for-coordinator-final-audit", "final_delivery_sha256": digest(delivery_path), "terminal_corroboration_sha256": digest(terminal_path), "inputs": delivery["input_binding_count"], "release_files": delivery["release_file_count"]}))


if __name__ == "__main__":
    main()
