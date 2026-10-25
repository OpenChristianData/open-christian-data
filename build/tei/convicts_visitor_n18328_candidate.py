"""Reproduce the held, header-bound N18328 electronic TEI candidate."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from build.tei.convicts_visitor_n18328_check import (
    CANDIDATE, IDENTITY, REVISION, ROOT, SOURCE, SOURCE_SHA,
    check_candidate_bytes,
)
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ACQUISITION = ROOT / (
    "library/works/convicts-visitor/forms/convicts-visitor-tcp-retained/"
    "editions/convicts-visitor-tcp-electronic/acquisitions/"
    "convicts-visitor-tcp-acquired.json"
)


def generate() -> bytes:
    acquisition = json.loads(ACQUISITION.read_text(encoding="utf-8"))
    original = SOURCE.read_bytes()
    if (acquisition["source_path"] != SOURCE.relative_to(ROOT).as_posix()
            or acquisition["source_bytes"] != len(original)
            or acquisition["source_sha256"] != SOURCE_SHA
            or sha256(original).hexdigest() != SOURCE_SHA
            or len(acquisition["retained_files"]) != 1
            or acquisition["retained_files"][0]["path"] != acquisition["source_path"]
            or acquisition["retained_files"][0]["sha256"] != SOURCE_SHA):
        raise ValueError("N18328 retained source/acquisition binding differs")
    revision = {
        "id": REVISION,
        "date": "2026-09-29",
        "note": "Bind complete retained TCP electronic witness; source text unchanged.",
    }
    result = bind_reviewed_header(
        original,
        expected_sha256=SOURCE_SHA,
        identity=IDENTITY,
        source={
            "source_path": acquisition["source_path"],
            "source_bytes": len(original),
            "source_sha256": SOURCE_SHA,
        },
        source_url=acquisition["url"],
        declared_scope=acquisition["source_scope"],
        revision=revision,
    )
    check_candidate_bytes(original, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Compare fresh output with the saved candidate")
    args = parser.parse_args()
    result = generate()
    if args.check:
        if CANDIDATE.read_bytes() != result:
            raise ValueError("N18328 candidate bytes do not reproduce")
    else:
        CANDIDATE.parent.mkdir(parents=True, exist_ok=True)
        CANDIDATE.write_bytes(result)
    if errors := validate_file(CANDIDATE):
        raise ValueError(f"N18328 TEI P5 validation failed: {errors[:3]}")
    print(json.dumps({"status": "pass", "candidate_sha256": sha256(result).hexdigest(),
                      "candidate_path": CANDIDATE.relative_to(ROOT).as_posix()}, sort_keys=True))


if __name__ == "__main__":
    main()
