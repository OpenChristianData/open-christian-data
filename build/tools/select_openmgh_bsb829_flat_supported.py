"""Freeze ten projectable flat slices and exact word-link holds from the 12-work review."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "sources/openmgh-bsb829-flat-slices/selection-plan.json"
REVIEW_SHA = "463ace336a34fad8842f5eb96a7ad48e4860103623e87dd30f894b2f87e0f4d8"
PROBE = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb829-flat-projection-probe-20260926.json"
PROBE_SHA = "79d55323c4c324f3e51d32a21b0e18f97474c1208539fa3d4ffa773dd80070fd"
OUTPUT = ROOT / "sources/openmgh-bsb829-flat-slices/stage-plan.json"


def _read(path: Path) -> bytes:
    return Path(_io_path(path)).read_bytes()


def select() -> dict:
    if sha256(_read(REVIEW)).hexdigest() != REVIEW_SHA or sha256(_read(PROBE)).hexdigest() != PROBE_SHA:
        raise ValueError("review plan or projection probe changed")
    review = json.loads(_read(REVIEW))
    probe = json.loads(_read(PROBE))
    if len(review["works"]) != 12 or len(probe["rows"]) != 12:
        raise ValueError("twelve-work review set changed")
    by_id = {row["work_id"]: row for row in probe["rows"]}
    if len(by_id) != 12 or set(by_id) != {row["work_id"] for row in review["works"]}:
        raise ValueError("probe and reviewed identity sets differ")
    supported = []
    held = []
    for row in review["works"]:
        observed = by_id[row["work_id"]]
        if observed["division"] != row["division"]:
            raise ValueError("probe division differs")
        if observed["projection"] == "pass" and not observed["outside_word_links"]:
            supported.append(row)
        else:
            held.append({"work_id": row["work_id"], "source_scope": row,
                         "candidate_sha256": observed["candidate_sha256"],
                         "outside_word_links": observed["outside_word_links"],
                         "projection_failure": observed["failure"]})
    if (len(supported) != 10 or len(held) != 2
            or {row["work_id"] for row in held} != {
                "beno-letter-to-roman-church-fathers",
                "bruno-of-segni-letter-to-st-george-brothers"}):
        raise ValueError("projectable selection set changed")
    return {"contract": "ocd-openmgh-bsb829-flat-slices-stage-plan-v1",
            "source_path": review["source_path"], "source_sha256": review["source_sha256"],
            "frozen_batch_sha256": review["frozen_batch_sha256"],
            "review_plan_sha256": REVIEW_SHA, "projection_probe_sha256": PROBE_SHA,
            "works": supported, "held": held}


def main() -> int:
    value = select()
    content = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if OUTPUT.exists() and _read(OUTPUT) != content:
        raise ValueError("existing supported selection differs")
    Path(_io_path(OUTPUT)).write_bytes(content)
    print(json.dumps({"supported": len(value["works"]), "held": len(value["held"]),
                      "path": OUTPUT.as_posix(), "sha256": sha256(content).hexdigest()},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
