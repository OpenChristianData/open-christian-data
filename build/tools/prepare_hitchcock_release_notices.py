"""Prepare only a source-directed public-safe notice successor for review."""

import difflib
import json
from pathlib import Path

from build.tools.prepare_hitchcock_current import ROOT, LOG, WORK_ID, SOURCE_SHA, digest, save, json_bytes


def main():
    out = LOG / "notice-preflight-repair"
    data = ROOT / "data/reference_entries" / WORK_ID / "README.md"
    source = ROOT / "sources/reference-entries" / WORK_ID / "README.source.md"
    data_before, source_before = data.read_bytes(), source.read_bytes()
    if digest(data_before) != "da85f8e9d8a5dbc693639a2b21ac63490c5cda03dc257255676ffa37f8034860" or source_before != data_before:
        raise ValueError("Exact original paired notice differs")
    private_sentence = f" Source member: `raw/bible_dictionaries/hitchcocks.jsonl` (SHA-256 `{SOURCE_SHA}`).".encode()
    if data_before.count(private_sentence) != 1:
        raise ValueError("Private source binding sentence is not unique")
    data_after = data_before.replace(private_sentence, b"", 1)
    source_after = source_before + (
        "\nShow the human-visible source credit and every rights, identity, human-review, and publication "
        "qualification at `data/reference_entries/hitchcocks-bible-names-dictionary/README.md` "
        "in every selected private release. The installed work-local `SOURCE_CREDIT.md` retains "
        "the exact source member path and digest for private audit.\n"
    ).encode()
    records = {}
    for name, before, after, target in (("data", data_before, data_after, data), ("source", source_before, source_after, source)):
        save(out / (name + ".before.md"), before)
        save(out / (name + ".after.md"), after)
        delta = "".join(difflib.unified_diff(before.decode().splitlines(True), after.decode().splitlines(True), fromfile=name + ".before.md", tofile=name + ".after.md"))
        save(out / (name + ".diff"), delta.encode())
        records[name] = {"target": target.relative_to(ROOT).as_posix(), "before_sha256": digest(before), "after_sha256": digest(after)}
    supplement = {"status": "unapplied-proposal", "changes": records, "data_delta": "Delete only the private raw path/SHA sentence; every provider credit, native-scope and rights/identity/human/publication qualification remains byte-identical.", "source_delta": "Append the exact selected data README publication instruction; retain all prior source notice bytes.", "installed_source_credit_changed": False, "installed_generation_changed": False, "source_candidate_runtime_changed": False, "failed_preflight": {"chunk_id": "868857", "exit_code": 1, "log_path": (LOG / "private-release.log").relative_to(ROOT).as_posix()}, "release_gates_previously_executed": []}
    save(out / "proposal.json", json_bytes(supplement))
    print(json.dumps(supplement))


if __name__ == "__main__":
    main()
