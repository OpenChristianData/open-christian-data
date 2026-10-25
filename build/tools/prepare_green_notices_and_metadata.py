"""Freeze source-backed Green prerequisites and paired visible credit notices."""

import copy
from datetime import datetime, timezone
import difflib
import json

from lxml import etree

from build.tools.prepare_green_current import ROOT, LOG, BASE, WORK, WORK_ID, FORM_ID, EDITION_ID, ACQUISITION_ID, REVISION, T, digest, save, json_bytes
from ocd_kernel.library._common import io_path
from ocd_kernel.library.identities import validate_identity_update
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON


def main():
    before = io_path(WORK / "work.json").read_bytes()
    state_before = io_path(WORK / "state.json").read_bytes()
    original = json.loads(before)
    revised = copy.deepcopy(original)
    form = revised["textual_forms"][0]
    edition = form["editions"][0]
    if (revised["work_id"] != WORK_ID or len(revised["textual_forms"]) != 1 or form["textual_form_id"] != FORM_ID or len(form["editions"]) != 1
            or edition["edition_id"] != EDITION_ID or "language" in form or "language" in edition or "category" in edition):
        raise ValueError("Exact three-field Green metadata preimage differs")
    source = etree.fromstring((ROOT / "raw/docsouth/l763-greenew-exact-1888/greenew.xml").read_bytes(), etree.XMLParser(resolve_entities=False, no_network=True))
    languages = source.findall("teiHeader/profileDesc/langUsage/language")
    if len(languages) != 1 or languages[0].get("id") != "eng" or languages[0].text != "English":
        raise ValueError("Literal English source-language evidence differs")
    form["language"] = edition["language"] = "en"
    edition["category"] = "prose"
    validate_identity_update(original, revised)
    state = json.loads(state_before)
    target = next(t for t in state["targets"] if t["target_id"] == EDITION_ID and t["target_type"] == "edition")
    if target["stage"] != "review":
        raise ValueError("Exact existing Green review stage differs")
    edition_home = WORK.relative_to(ROOT) / "forms" / FORM_ID / "editions" / EDITION_ID
    target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    target["evidence"].extend([(edition_home / "master.tei.xml").as_posix(), (edition_home / "acceptance.json").as_posix()])
    for name, old, new in (("work", before, json_bytes(revised)), ("state", state_before, json_bytes(state))):
        save(LOG / "authority-proposal" / (name + ".before.json"), old)
        save(LOG / "authority-proposal" / (name + ".after.json"), new)
        a, b = (json.dumps(json.loads(raw), ensure_ascii=False, indent=2).splitlines(keepends=True) for raw in (old, new))
        save(LOG / "authority-proposal" / (name + ".diff"), "".join(difflib.unified_diff(a, b, fromfile=name+".before", tofile=name+".after")).encode())
    proposal = {"status": "proposed-only", "work_id": WORK_ID, "work_before_sha256": digest(before), "work_after_sha256": digest(json_bytes(revised)), "state_before_sha256": digest(state_before), "state_after_sha256": digest(json_bytes(state)), "metadata_changes": ["form.language absent -> en", "edition.language absent -> en", "edition.category absent -> prose"], "source_language": "retained TEI.2 profileDesc/langUsage/language id=eng, literal English; en normalized for canonical BCP47 field", "state_change": "Only edition target review -> accepted with standard promoted-master reason, timestamp and two authority evidence paths; acquisition target unchanged", "canonical_changes_performed": False, "identity_title_creator_acquisition_and_existing_source_credit_preserved": True}
    save(LOG / "authority-proposal/proposal.json", json_bytes(proposal))
    rights = "No Copyright - United States. The organization that has made the Item available believes that the Item is in the Public Domain under the laws of the United States, but a determination was not made as to its copyright status under the copyright laws of other countries. The Item may not be in the Public Domain under the laws of other countries. Please refer to the organization that has made the Item available for more information."
    notice = ("# Source credit and provider rights statement\n\n"
              "*Life of the Rev. Elisha W. Green, Written by Himself* — Elisha Winfield Green. Source: Documenting the American South, University of North Carolina at Chapel Hill, https://docsouth.unc.edu/neh/greenew/greenew.xml.\n\n"
              "The source names Academic Affairs Library, UNC-Chapel Hill as electronic publisher, First edition 2001. Funding from the National Endowment for the Humanities supported electronic publication. Text transcribed by Apex Data Services, Inc.; images scanned by LeeAnn Morawski; text encoded by Apex Data Services, Inc., LeeAnn Morawski and Natalia Smith. These are the source's distinct contributor roles, not newly inferred authorship.\n\n"
              "The source describes a print edition at Maysville, Kentucky, The Republican Printing Office, 1888, with call number B921 G82 at Wake Forest University Library. These retained description fields are distinct from the electronic edition; no new physical print collation is asserted.\n\n"
              "The provider statement is reproduced here: “" + rights + "” Statement: http://rightsstatements.org/vocab/NoC-US/1.0/. This records a provider U.S.-law belief, not an independent worldwide rights determination.\n\n"
              "This edition represents the complete retained electronic volume including its own front matter, letters, body and editorial context. The source has no back matter. Three source-declared illustration URLs are preserved; the image binaries were not retained, and image content has not been verified. Source errors, correction alternatives, page labels and meaningful structure remain represented.\n\n"
              "Technical adoption and a verified private offline release do not establish human acceptance, rights clearance or public publication authorization.\n")
    save(BASE / "README.data.md", notice.encode())
    source_notice = notice + "\nThe source-directed public credit and rights notice is delivered at `data/prose/elisha-w-green-life-1888/README.md`.\n"
    save(BASE / "README.source.md", source_notice.encode())
    save(BASE / "SOURCE_CREDIT.supplement.md", source_notice.encode())
    print(json.dumps(proposal))


if __name__ == "__main__":
    main()
