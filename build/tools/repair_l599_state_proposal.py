"""Add missing inherited evidence to L599's future state proposal only."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / "sources/manifest-acquisitions/l599-slave-trade-header-proposal-v1"
OUT = ROOT / "sources/manifest-acquisitions/l599-slave-trade-state-proposal-v2"
def enc(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
def pin(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
def prepare():
    if OUT.exists():
        raise ValueError("Preserve state proposal successor")
    from ocd_kernel.library.identities import validate_record
    original = json.loads((OLD / "original-state.json").read_bytes())
    before_bytes = (OLD / "state-proposal.json").read_bytes()
    proposed = json.loads(before_bytes)
    before = next(row for row in original["targets"] if row["target_type"] == "edition")
    after = next(row for row in proposed["targets"] if row["target_type"] == "edition")
    additions = list(after["evidence"])
    after["evidence"] = list(dict.fromkeys(before["evidence"] + additions))
    check = json.loads(enc(proposed))
    next(row for row in check["targets"] if row["target_type"] == "edition")["evidence"] = additions
    if check != json.loads(before_bytes):
        raise ValueError("State-only successor changed additional fields")
    if [row for row in original["targets"] if row["target_type"] == "acquisition"] != [row for row in proposed["targets"] if row["target_type"] == "acquisition"]:
        raise ValueError("Acquisition target changed")
    validate_record("state", proposed, context="L599 evidence-preserving future state proposal")
    OUT.mkdir()
    (OUT / "predecessor-state-proposal.json").write_bytes(before_bytes)
    (OUT / "state-proposal.json").write_bytes(enc(proposed))
    record = {"status": "schema-valid-state-only-proposal-successor", "predecessor_proposal": pin(OLD / "proposal.json"),
              "original_state": pin(OLD / "original-state.json"), "header_unchanged": pin(OLD / "candidate.tei.xml"),
              "predecessor_state": pin(OUT / "predecessor-state-proposal.json"), "current_state": pin(OUT / "state-proposal.json"),
              "preserved_existing_edition_evidence": before["evidence"], "appended_evidence": additions,
              "acquisition_target_unchanged": True, "only_change": "Existing edition evidence plus exact new pointers, deduplicated in order.",
              "qualification": "No accepted state, stage or canonical change. Header/leaf/source proposal and all prior evidence remain unchanged."}
    (OUT / "proposal.json").write_bytes(enc(record))
    return pin(OUT / "proposal.json")
if __name__ == "__main__":
    print(json.dumps(prepare(), sort_keys=True))
