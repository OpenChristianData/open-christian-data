"""Replay exact frozen current header plus retained complete Nave body."""

import argparse
import json
from pathlib import Path

from build.tools.prepare_nave_current import ROOT, BASE, HISTORICAL, OLD_SHA, digest, save, json_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    old = (HISTORICAL / "content.tei.xml").read_bytes()
    header = (BASE / "fresh-header.xml").read_bytes()
    profile = json.loads((BASE / "profile.json").read_bytes())
    if digest(old) != OLD_SHA or digest(header) != profile["header_sha256"]:
        raise ValueError("Exact historical body/current header changed")
    start = old.index(b"<teiHeader>"); end = old.index(b"</teiHeader>") + len(b"</teiHeader>")
    replay = old[:start] + header + old[end:]
    if replay != (BASE / "candidate.tei.xml").read_bytes() or digest(replay) != profile["candidate_sha256"]:
        raise ValueError("Exact reviewed-header/native-body composition replay differs")
    save(args.output, replay)
    report = {"status": "pass", "candidate_sha256": digest(replay), "historical_candidate_sha256": OLD_SHA, "fresh_header_sha256": digest(header), "native_body_bytes_identical": True, "scope": "Deterministic composition replay of pinned existing native body and reviewed current header; no new source conversion or visual collation claim.", "generator_path": Path(__file__).resolve().relative_to(ROOT).as_posix(), "generator_sha256": digest(Path(__file__).read_bytes())}
    save(args.output.with_suffix(".replay.json"), json_bytes(report)); print(json.dumps(report))


if __name__ == "__main__":
    main()
