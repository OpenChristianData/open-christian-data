"""Bounded retained-source and historical native body reconciliation for BSB."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from jsonschema import Draft202012Validator
from ocd_kernel.library._common import io_path
from ocd_kernel.reconstruction.contract import SourceManifest
from build.tei.bsb_reconstruction import _convert
from build.tei.bsb_oracle import _read_native_source, _enumerate_source, _verify_candidate_tei, _expected_accountability

ROOT = Path(__file__).resolve().parents[2]
LOG = Path("reports/_logs/bsb-current-reconciliation-20261002-v1")
BASELINE = LOG / "source-derived-historical-native"


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def save(path, payload):
    physical = io_path(ROOT / path)
    physical.parent.mkdir(parents=True, exist_ok=True)
    physical.write_bytes(payload)


class NativeMember:
    def __init__(self, raw):
        self.raw = raw

    def member_bytes(self, name):
        if name != "content.tei.xml":
            raise ValueError(name)
        return self.raw


def main():
    if io_path(ROOT / LOG / "preflight.json").exists():
        raise FileExistsError("Preserve existing preflight")
    manifest = SourceManifest.load(ROOT / "sources/bible-text/bsb/bsb.source-manifest.json", repository_root=ROOT)
    manifest.verify()
    members = _convert(manifest)
    raw, source, config, profile, policy = _read_native_source(manifest)
    marker, books, chapters, verses, empties = _enumerate_source(source, profile, policy)
    _verify_candidate_tei(manifest, NativeMember(members["content.tei.xml"]), config, marker, books, raw)
    independent = _expected_accountability(marker, books, manifest, raw)
    if canonical(independent) != members["source-accountability.json"]:
        raise ValueError("Complete independent source ledger differs")
    Draft202012Validator(json.loads((ROOT / "sources/bible-text/bsb/bsb.source-accountability.schema.json").read_bytes())).validate(independent)
    for name, content in members.items():
        save(BASELINE / name, content)
    recorded_tei_sha = "d2382c393edf36488497e1865c2bd155a00c515103219b2fb5d4cd6491d5b511"
    tei_sha = sha256(members["content.tei.xml"]).hexdigest()
    bindings = {}
    for rel in ["library/works/bsb/work.json", "library/works/bsb/state.json", "library/works/bsb/forms/bsb-english/editions/bsb-retained-electronic-witness/acquisitions/bsb-retained-source.json", "sources/bible-text/bsb/bsb.source-manifest.json", "sources/bible-text/bsb/config.json", "sources/bible-text/bsb/bsb.reconstruction-profile.json", "build/tei/bsb_reconstruction.py", "build/tei/bsb_oracle.py", "raw/bible_databases/formats/json/BSB.json", "raw/bible_databases/LICENSE", "raw/bible_databases/README.md", "raw/bsb/LICENSE.md", "raw/bsb/README.md", "raw/bsb/src/index.ts", "raw/bsb/src/frt.ts", "raw/bsb/download/bsb_tables.xlsx"]:
        content = io_path(ROOT / rel).read_bytes()
        bindings[rel] = dict(bytes=len(content), sha256=sha256(content).hexdigest())
    verse_values = [v["text"] for b in books for c in b["chapters"] for v in c["verses"]]
    proof = dict(status="pass", pid=os.getpid(), exit_code=0, checked_at=datetime.now(timezone.utc).isoformat(), work_id="bsb", source_manifest_sha256=manifest.sha256,
                 source_sha256=sha256(raw).hexdigest(), source_bytes=len(raw), marker=marker,
                 books=len(books), chapters=chapters, verses=verses, empty_locations=empties,
                 empty_source_slots=len(empties), text_characters=sum(map(len, verse_values)),
                 leading_whitespace_values=sum(bool(v) and v[:1].isspace() for v in verse_values),
                 trailing_whitespace_values=sum(bool(v) and v[-1:].isspace() for v in verse_values),
                 baseline_tei_sha256=tei_sha, recorded_historical_tei_sha256=recorded_tei_sha,
                 matches_recorded_historical_tei_bytes_hash=(tei_sha == recorded_tei_sha),
                 baseline_ledger_sha256=sha256(members["source-accountability.json"]).hexdigest(),
                 source_fidelity="Unchanged independent complete JSON enumerator, full native hierarchy/IDs/order/text check, independent full source field ledger, P5, accountability schema.",
                 original_manifest_source_and_implementation_verification="pass", bindings=bindings,
                 prior_completion_reconciliation=dict(canonical_acceptance=False, canonical_master=False, canonical_publication_directory=False, historical_disposition="Technical nonaccepted candidate, no release claimed", bounded_durable_candidate_names=[], historical_declared_paths=["F:/Open Christian Data/CodexScratch/LIB-024-37c-087-20260911-02/package", "F:/Open Christian Data/CodexScratch/LIB-024-37c-087-20260911-03/package"], historical_access="Exact four manifest/TEI file reads returned PermissionError in sandbox and approved host contexts; not an absence claim. Native source-derived replay and recorded TEI hash are the reusable evidence route.", exhaustive_all_files_search_claimed=False),
                 source_and_permission_disposition="Canonical textual authority is the acquired complete native BSB.json, not any ZIP. Separate openbible-io/bsb spreadsheet and CC0 metadata remain comparison/permission support; no byte-equivalence or print identity inferred from them. No individual JSON contributor fields exist; precise retained repository roles/claims stay separately qualified.",
                 canonical_mutations_performed=False)
    save(BASELINE / "validation.json", canonical(proof))
    save(LOG / "preflight.json", canonical(proof))
    print(json.dumps({k: proof[k] for k in ["status", "baseline_tei_sha256", "matches_recorded_historical_tei_bytes_hash", "verses", "empty_source_slots", "text_characters", "leading_whitespace_values", "trailing_whitespace_values"]}))


if __name__ == "__main__":
    main()
