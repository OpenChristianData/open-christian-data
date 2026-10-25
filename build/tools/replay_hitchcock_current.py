"""Deterministic assembly replay of conserved native body and reviewed fresh header."""

import argparse
import json
from pathlib import Path

from build.tools.prepare_hitchcock_current import ROOT, BASE, HISTORICAL, SOURCE, SOURCE_SHA, OLD_SHA, digest, save, json_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    old = (HISTORICAL / "content.tei.xml").read_bytes()
    header = (BASE / "fresh-header.xml").read_bytes()
    if digest(old) != OLD_SHA or digest(SOURCE.read_bytes()) != SOURCE_SHA:
        raise ValueError("Retained body/source replay input drifted")
    proof = json.loads((BASE / "source-proof.json").read_text())
    start = old.index(b"<teiHeader")
    end = old.index(b"</teiHeader>") + len(b"</teiHeader>")
    replay = old[:start] + header + old[end:]
    if replay != (BASE / "candidate.tei.xml").read_bytes() or digest(replay) != proof["candidate_sha256"]:
        raise ValueError("Exact reviewed-header/native-body assembly replay differs")
    save(args.output, replay)
    report = {"status": "pass", "candidate_sha256": digest(replay), "historical_body_candidate_sha256": OLD_SHA, "source_sha256": SOURCE_SHA, "fresh_header_sha256": digest(header), "scope": "Exact deterministic composition of the pinned retained native body and separately reviewed current header; does not claim fresh source conversion or visual collation.", "generator_path": Path(__file__).resolve().relative_to(ROOT).as_posix(), "generator_sha256": digest(Path(__file__).read_bytes()), "native_body_bytes_identical": True}
    save(args.output.with_suffix(".replay.json"), json_bytes(report))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
