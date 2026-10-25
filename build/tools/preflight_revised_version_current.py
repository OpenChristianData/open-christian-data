"""Read-only reconciliation of the retained whole Revised Version handoff."""

from collections import Counter
import hashlib
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.library._common import io_path
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.projection.categories.bible import project_bible_document, UnsupportedStructure

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "revised-version-with-apocrypha"
FORM_ID = "revised-version-with-apocrypha-retained-en"
EDITION_ID = "revised-version-with-apocrypha-electronic"
ACQUISITION_ID = "revised-version-with-apocrypha-acquired"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
LOG = ROOT / "reports/_logs/revised-version-current-reconciliation-20261002-v1"
HISTORICAL = ROOT / "reports/clean-ready-acquisition-to-tei/master-3/21" / WORK_ID / "candidate"
RAW = Path("raw/clean-ready-acquisition-to-tei/master-3/21") / WORK_ID


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, raw):
    io_path(path).parent.mkdir(parents=True, exist_ok=True)
    if io_path(path).exists() and io_path(path).read_bytes() != raw:
        raise FileExistsError("Frozen work evidence differs: " + str(path))
    io_path(path).write_bytes(raw)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def main():
    before = _files(ROOT / WORK)
    acquisition_path = ROOT / EDITION / "acquisitions" / (ACQUISITION_ID + ".json")
    acquisition = json.loads(io_path(acquisition_path).read_bytes())
    state = json.loads(io_path(ROOT / WORK / "state.json").read_bytes())
    work = json.loads(io_path(ROOT / WORK / "work.json").read_bytes())
    source_member_set = ROOT / acquisition["source_path"]
    if digest(io_path(source_member_set).read_bytes()) != acquisition["source_sha256"] or len(acquisition["retained_files"]) != 80:
        raise ValueError("Exact current source-member-set differs")
    members = []
    for position, member in enumerate(acquisition["retained_files"], 1):
        raw = io_path(ROOT / member["path"]).read_bytes()
        if len(raw) != member["bytes"] or digest(raw) != member["sha256"]:
            raise ValueError("Actual textual member differs: " + member["path"])
        members.append({"position": position, "path": member["path"], "bytes": len(raw), "sha256": digest(raw), "lines": len(raw.decode("utf-8").split("\n"))})
    old_receipt = json.loads((HISTORICAL / "source-receipt.json").read_bytes())
    envelope = []
    for item in old_receipt["retained_files"]:
        relative = RAW / item["path"]
        raw = io_path(ROOT / relative).read_bytes()
        if len(raw) != item["bytes"] or digest(raw) != item["sha256"]:
            raise ValueError("Historical retained envelope changed: " + relative.as_posix())
        role = "textual-authority" if relative.as_posix() in {m["path"] for m in members} else "retained-support-or-comparison-evidence"
        envelope.append({"path": relative.as_posix(), "bytes": len(raw), "sha256": digest(raw), "disposition": role})
    historical_bytes = (HISTORICAL / "content.tei.xml").read_bytes()
    parsed = etree.fromstring(historical_bytes, etree.XMLParser(resolve_entities=False, no_network=True))
    counts = dict(Counter(etree.QName(n).localname for n in parsed.iter()))
    type_counts = {}
    for name in ("div", "ab", "note", "seg"):
        type_counts[name] = dict(Counter(n.get("type", "") for n in parsed.iter("{http://www.tei-c.org/ns/1.0}" + name)))
    candidates = []
    paths = [HISTORICAL / "content.tei.xml", HISTORICAL.parent / "manifest-acquisition-20260928-replay-3/content.tei.xml", HISTORICAL.parent / "determinism/run-2/content.tei.xml", Path("D:/Library/Open Christian Data/candidate-reviews/manifest-acquisition-20260927-l74-revised-version-with-apocrypha-v1/content.tei.xml"), Path("D:/Library/Open Christian Data/candidate-reviews/manifest-acquisition-20260927-l74-revised-version-with-apocrypha-replay-2/content.tei.xml")]
    for path in paths:
        raw = path.read_bytes()
        if raw != historical_bytes:
            raise ValueError("Discovered exact-identity candidate differs: " + str(path))
        candidates.append({"path": path.as_posix(), "bytes": len(raw), "sha256": digest(raw), "exact_same_existing_TEI": True})
    probe = ""
    try:
        project_bible_document(HISTORICAL / "content.tei.xml", identity={"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID}, language="en", representation_revision="rv-current-preflight-v1", edition_title=work["textual_forms"][0]["editions"][0]["title"], versification="source-native:revised-version-with-apocrypha-v1")
    except UnsupportedStructure as exc:
        probe = str(exc)
    if not probe:
        raise ValueError("Unexpected generic route success; inspect before selecting adapter")
    pin_paths = [acquisition_path, source_member_set, ROOT / "sources/structured-text/revised-version-with-apocrypha/config.json", ROOT / "sources/structured-text/revised-version-with-apocrypha/corpus-v3/reconstruction-source-manifest.json", ROOT / "build/tei/revised_version_with_apocrypha.py", ROOT / "build/tei/revised_version_with_apocrypha_corpus.py", ROOT / "build/tei/revised_version_with_apocrypha_corpus_oracle.py", ROOT / "ocd_kernel/projection/categories/bible.py", ROOT / "schemas/v2/categories/bible.schema.json", ROOT / "schemas/v2/public-row.schema.json"]
    if _files(ROOT / WORK) != before:
        raise ValueError("Read-only reconciliation changed canonical authority")
    report = {"status": "preflight-complete-support-gap-located", "work_id": WORK_ID, "form_id": FORM_ID, "edition_id": EDITION_ID, "acquisition_id": ACQUISITION_ID, "original_canonical_files": before, "current_targets": [{"id": t["target_id"], "type": t["target_type"], "stage": t["stage"]} for t in state["targets"]], "existing_category": work["textual_forms"][0]["editions"][0].get("category"), "source_sha256": acquisition["source_sha256"], "source_scope": acquisition["source_scope"], "members": members, "historical_107_member_envelope_checked": envelope, "candidates": candidates, "selected_candidate": candidates[0], "whole_TEI_counts": counts, "native_types": type_counts, "generic_projection_failure": probe, "route_proposal": "Reuse complete single-work native TEI body unchanged; dedicated closed identity/profile Bible projection for USFM native carriers, source-line machine annotations, poetry continuation and supplied-text/word/note roles. Fresh source-bound active header. Exact body comparison and independent full-source proof remain separate from generic projection. No shared writes without frozen proposal/review.", "comparison_witness_disposition": "1895/1913 and Tobit/Greek Esther scans are retained support, not transformation authority; no print-only text invented. Baruch chapter6 Epistle of Jeremy remains an embedded source unit, not a new work/source file.", "old_corpus_profile_disposition": "Later corpus manifests split exact conserved book subtrees into80physicalTEIdocuments but do not improve the body; preserve as historical composition evidence. Prefer already-existing complete singleTEI for this one intellectual work.", "human_acceptance": "not-recorded", "rights_clearance": "unresolved", "publication_performed": False, "source_conversion_performed": False, "canonical_changes_performed": False, "bindings": {p.relative_to(ROOT).as_posix(): digest(io_path(p).read_bytes()) for p in pin_paths}}
    save(LOG / "preflight.json", json_bytes(report))
    print(json.dumps({"status": report["status"], "candidate_sha256": digest(historical_bytes), "identical_candidates": len(candidates), "textual_members": len(members), "historical_envelope_checked": len(envelope), "source_lines": sum(m["lines"] for m in members), "native_verses": type_counts["ab"]["verse"], "generic_failure": probe, "report_sha256": digest(json_bytes(report))}))


if __name__ == "__main__":
    main()
