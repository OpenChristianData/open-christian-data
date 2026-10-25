"""Freeze Nave's exact category prerequisite and technical edition-state proposal."""

from datetime import datetime, timezone
import copy
import difflib
import json

from build.tools.prepare_nave_current import ROOT, WORK, LOG, WORK_ID, FORM_ID, EDITION_ID, ACQUISITION_ID, digest, save, json_bytes
from ocd_kernel.library._common import io_path
from ocd_kernel.library.identities import validate_identity_update
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON


def main():
    home = LOG / "authority-proposal"
    before_work = io_path(WORK / "work.json").read_bytes()
    before_state = io_path(WORK / "state.json").read_bytes()
    original = json.loads(before_work)
    revised = copy.deepcopy(original)
    form = revised["textual_forms"][0]
    edition = form["editions"][0]
    if (original["work_id"] != WORK_ID or len(revised["textual_forms"]) != 1
            or form["textual_form_id"] != FORM_ID or form["language"] != "en"
            or len(form["editions"]) != 1 or edition["edition_id"] != EDITION_ID
            or edition["language"] != "en" or "category" in edition):
        raise ValueError("Exact Nave category-only preimage differs")
    edition["category"] = "topical-indexes"
    validate_identity_update(original, revised)
    state = json.loads(before_state)
    target = next(t for t in state["targets"] if t["target_id"] == EDITION_ID and t["target_type"] == "edition")
    if target["stage"] != "acquired":
        raise ValueError("Exact Nave edition-state preimage differs")
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    edition_path = WORK.relative_to(ROOT) / "forms" / FORM_ID / "editions" / EDITION_ID
    target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    target["evidence"].extend([(edition_path / "master.tei.xml").as_posix(), (edition_path / "acceptance.json").as_posix()])
    for name, before, after in (("work", before_work, json_bytes(revised)), ("state", before_state, json_bytes(state))):
        save(home / (name + ".before.json"), before)
        save(home / (name + ".after.json"), after)
        displayed_before = json.dumps(json.loads(before), ensure_ascii=False, indent=2).splitlines(keepends=True)
        displayed_after = json.dumps(json.loads(after), ensure_ascii=False, indent=2).splitlines(keepends=True)
        save(home / (name + ".diff"), "".join(difflib.unified_diff(displayed_before, displayed_after, fromfile=name+".before", tofile=name+".after")).encode())
    report = {"status": "proposed-only", "canonical_mutations": False, "work_id": WORK_ID,
              "work_before_sha256": digest(before_work), "work_after_sha256": digest(json_bytes(revised)),
              "state_before_sha256": digest(before_state), "state_after_sha256": digest(json_bytes(state)),
              "metadata_change": "Only edition.category: absent -> topical-indexes",
              "state_change": "Only specified edition target: acquired -> accepted with promoted-master reason, UTC timestamp and master/acceptance evidence; acquisition target unchanged",
              "acquisition_id": ACQUISITION_ID, "title_language_ids_source_acquisition_preserved": True,
              "rights_clearance": "unresolved", "human_decision": "not-recorded", "public_publication_authorized": False}
    save(home / "proposal.json", json_bytes(report))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
