"""Bind Anne first's completed private release to terminal and source evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "library/works/anne-askew-first-examinacyon"
OUT = ROOT / "reports/_logs/anne-askew-first-private-release-20261002-v1"
COORDINATOR_SOURCE = ROOT / "reports/_logs/anne-first-coordinator-source-review-20261002-v1/review.json"
COMPLETION_SHA = "b6a22376e48853052db37a98d4298f81b7840dbc49bd41b65d86285c63ea6203"
SOURCE_REVIEW_SHA = "d69b6b5602f60d476f5b1c687a367632d49cf98d1163304e126215e45b1446b4"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def main() -> None:
    completion_path = OUT / "completion.json"
    canonical_completion = WORK / "publication/completion.json"
    if digest(completion_path) != COMPLETION_SHA or digest(canonical_completion) != COMPLETION_SHA or digest(COORDINATOR_SOURCE) != SOURCE_REVIEW_SHA:
        raise ValueError("Anne current completion/source review differs")
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    if (completion["status"] != "pass" or completion["rows"] != 7
            or completion["accepted_master_sha256"] != "e3012ca8c173057f609ae3a20645ed76ac6c17cd44dcfeca3b4cfcb074e0c446"):
        raise ValueError("Anne private completion content differs")
    gates = {}
    for name in ("assembly", "independent-verification", "statistics", "readers", "notice-gate", "released-notice-check"):
        path = OUT / f"{name}.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        if value["status"] != "pass":
            raise ValueError(f"Anne private release gate did not pass: {name}")
        gates[name] = digest(path)
    for label, expected in completion["input_bindings"].items():
        if digest(ROOT / label) != expected:
            raise ValueError(f"Anne private release input changed: {label}")
    release = Path(completion["release_path"])
    for label, expected in completion["release_file_bindings"].items():
        if digest(release / label) != expected:
            raise ValueError(f"Anne private release file changed: {label}")
    terminal = {
        "contract": "ocd-anne-first-private-release-terminal-corroboration-v1",
        "status": "exit-zero",
        "source_command": "py -3 -m build.tools.complete_anne_first_private_release",
        "owned_session_id": 88762,
        "launch_chunk": "1d32a0",
        "assembly_chunk": "907950",
        "independent_verification_chunk": "6f0985",
        "statistics_chunk": "5d67ec",
        "terminal_chunk": "08c5a8",
        "terminal_exit_code": 0,
        "terminal_output": "readers: PASS; status=pass; rows=7; release_file_count=7",
        "completion_sha256": COMPLETION_SHA,
        "coordinator_source_review_sha256": SOURCE_REVIEW_SHA,
    }
    terminal_path = OUT / "terminal-corroboration.json"
    save(terminal_path, terminal)
    delivery = {
        "contract": "ocd-anne-first-private-final-delivery-v1",
        "status": "ready-for-coordinator-final-audit",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "work_id": "anne-askew-first-examinacyon",
        "completion_sha256": COMPLETION_SHA,
        "canonical_completion_sha256": digest(canonical_completion),
        "terminal_corroboration_sha256": digest(terminal_path),
        "coordinator_source_review_sha256": SOURCE_REVIEW_SHA,
        "gate_sha256": gates,
        "input_binding_count": len(completion["input_bindings"]),
        "release_file_count": len(completion["release_file_bindings"]),
        "rows": completion["rows"],
        "text_characters": completion["text_characters"],
        "source_text_rights": "TCP Phase I CC0 1.0 Universal",
        "page_image_rights": "not-assessed",
        "print_collation": "not-performed",
        "human_decision": "not-recorded",
        "publication_performed": False,
    }
    delivery_path = OUT / "final-delivery.json"
    save(delivery_path, delivery)
    print(json.dumps({"status": "ready-for-coordinator-final-audit", "final_delivery_sha256": digest(delivery_path), "terminal_corroboration_sha256": digest(terminal_path), "inputs": delivery["input_binding_count"], "release_files": delivery["release_file_count"]}))


if __name__ == "__main__":
    main()
