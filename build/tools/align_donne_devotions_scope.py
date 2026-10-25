"""Align historical Donne mapping instructions with the current accepted work scope."""
from hashlib import sha256
import json
from pathlib import Path
from build.tools.prepare_donne_devotions import ROOT, BASE, WORK_ID, SCOPE, SOURCE, SOURCE_SHA, canonical
from build.tei import lib068_source_local_oracle as historical_checker


def main():
    archive = ROOT / "reports/_logs/donne-reconciliation-20261001-v2"
    files = [Path("sources/structured-text") / WORK_ID / name for name in
             ("LIB-068.reconstruction-profile.json", "LIB-068.source-manifest.json", "LIB-068.README.source.md")]
    files += [Path("plans/2026-08-31-sample-first-library-verification/issues/32a-review-donnes-devotions.md"),
              Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-10-structural-audit/79-lib068-repair-handoff.md")]
    before = {}
    for relative in files:
        saved = (archive / "before" / relative).read_bytes()
        if (ROOT / relative).read_bytes() != saved:
            raise ValueError("active instruction changed before alignment: " + relative.as_posix())
        before[relative.as_posix()] = sha256(saved).hexdigest()
    if sha256((ROOT / SOURCE).read_bytes()).hexdigest() != SOURCE_SHA:
        raise ValueError("raw source differs")
    heading = ("\n## Current Donne scope reconciliation — October 1, 2026\n\n"
        "The historical LIB-068 whole-volume mapping and September repair receipts below remain evidence of source conservation; they are not the current Devotions acceptance boundary. "
        "Acquisition retains the entire unchanged 7647-carrier Project Gutenberg member. The source Contents lists Walton's explicitly attributed excerpt at roman page v, Devotions at page 1, and Death's Duel at page 161. "
        + SCOPE + "\n\nCurrent selected master represents 6842 carriers; the 805 Death's Duel carriers remain retained-only and fully accounted. "
        "The prior October 1 narrow candidate's exclusion of Walton front matter is superseded explicitly; its receipts remain historical. "
        "Canonical catalog identity is Devotions Upon Emergent Occasions; the longer volume title in acquisition metadata is a provider observation, not a combined intellectual-work identity. "
        "No source deletion, new work ID, human visual acceptance, print equivalence, rights clearance, or publication is implied. "
        "Current source/work scope and independent checker are bound in `sources/donne-devotions-pg23772/" + WORK_ID + "/source-manifest.json`.\n\n"
        "### Historical whole-volume mapping and review instructions\n\n")
    profile = json.loads((ROOT / files[0]).read_bytes())
    profile["current_work_scope_reconciliation"] = dict(date="2026-10-01", status="historical-whole-volume-mapping-retained",
        mapping_scope=profile["scope"], current_selected_work_scope=SCOPE, represented_carriers=6842,
        retained_only_sermon_carriers=805, authority=(BASE / "source-manifest.json").as_posix(),
        rationale="Source Contents roman v and explicit Taken from the life by Izaak Walton establish attributed edition front context. Devotions page 1 and separate Death's Duel page 161 delimit body and excluded sermon.",
        supersedes="Earlier October 1 exclusion of Walton excerpt; narrow receipts preserved.")
    (ROOT / files[0]).write_bytes(canonical(profile))
    for relative in files[2:]:
        original = (archive / "before" / relative).read_text(encoding="utf8")
        first, rest = original.split("\n", 1)
        (ROOT / relative).write_bytes((first + "\n" + heading + rest).encode())
    manifest = json.loads((ROOT / files[1]).read_bytes())
    for authority in manifest["authorities"]:
        raw = (ROOT / authority["path"]).read_bytes()
        authority.update(bytes=len(raw), sha256=sha256(raw).hexdigest())
    manifest["validator"]["import_closure_sha256"] = historical_checker._closure(ROOT)
    (ROOT / files[1]).write_bytes(canonical(manifest))
    after = {p.as_posix(): sha256((ROOT / p).read_bytes()).hexdigest() for p in files}
    (archive / "active-scope-alignment.json").write_bytes(canonical(dict(status="aligned", before=before, after=after,
        scope=SCOPE, source_sha256=SOURCE_SHA, source_unchanged=True, historical_structure_unchanged=True,
        historical_mapping_authority="Immutable preimages retained; current selected manifest binds those preimages, not silently overridden active instructions.")))
    print(json.dumps(dict(status="aligned", files=len(files))))


if __name__ == "__main__":
    main()
