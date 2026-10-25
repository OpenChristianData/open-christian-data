"""Rehearse the actual native prose engine on a held, proposed Ambrose master."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path("\\\\?\\" + str(Path(__file__).resolve().parents[2]))
WORK_ID = "ambrose-of-milan-on-mysteries"
WORK = Path("library/works") / WORK_ID / "work.json"
SOURCE = Path("raw/ccel/npnf2/npnf210.xml")
PACKAGE = Path("D:/Library/Open Christian Data/candidate-reviews/npnf210-work-ambrose-of-milan-on-mysteries-heading-repair-v2-20260926/package")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/npnf210-mysteries-heading-repair-v2-projection-20260926")
REVISION = "ambrose-mysteries-ccel-electronic-v2"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def rehearse() -> dict[str, object]:
    if not STAGE.parent.is_dir():
        raise ValueError("the proposed-master projection parent is absent")
    source_bytes = (ROOT / SOURCE).read_bytes()
    source_hash = _sha(source_bytes)
    if source_hash != "c6f1a9d66653852d8b743c84a613c72c521dfb1b05602f0a2eff400c17665ee8":
        raise ValueError("retained Ambrose source changed")
    source_tree = etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True))
    head = source_tree.find("ThML.head")
    if head is None or (head.findtext(".//DC.Language") or "").strip() != "eng" or (head.findtext(".//DC.Type") or "").strip() != "Text.Monograph":
        raise ValueError("primary source language or monograph type changed")
    volume = next(node for node in source_tree.iter() if node.get("id") == "i-p15")
    child = next(node for node in source_tree.iter() if node.get("id") == "iv.v")
    if "Ambrose" not in "".join(volume.itertext()) or child.get("title") != "On the Mysteries.":
        raise ValueError("primary volume author or child work evidence changed")
    work = json.loads((ROOT / WORK).read_bytes())
    if work["work_id"] != WORK_ID or work.get("creators") or work["textual_forms"][0]["editions"][0].get("category"):
        raise ValueError("canonical work identity or metadata baseline changed")
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    if form["language"] != "en" or edition["language"] != "en" or edition["containing_source"]["locator"] != "raw/ccel/npnf2/npnf210.xml#iv.v":
        raise ValueError("work-local language or child locator changed")
    form_id = form["textual_form_id"]
    identity = {"work_id": WORK_ID, "textual_form_id": form_id, "edition_id": edition["edition_id"], "acquisition_id": edition["acquisition_ids"][0]}
    acquisition_path = ROOT / "library/works" / WORK_ID / "forms" / form_id / "editions" / edition["edition_id"] / "acquisitions" / f"{identity['acquisition_id']}.json"
    acquisition = json.loads(acquisition_path.read_bytes())
    if acquisition["source_sha256"] != source_hash or acquisition["source_path"] != SOURCE.as_posix():
        raise ValueError("canonical acquisition differs from retained XML")
    original = (PACKAGE / "content.tei.xml").read_bytes()
    scope = "Complete On the Mysteries child div2 iv.v in retained CCEL NPNF2-10 XML."
    bound = bind_reviewed_header(
        original,
        expected_sha256=_sha(original),
        identity=identity,
        source={"source_path": SOURCE.as_posix(), "source_sha256": source_hash, "source_bytes": len(source_bytes)},
        source_url=acquisition["url"],
        declared_scope=scope,
        revision={"id": REVISION, "date": "2026-09-26", "note": "Proposed retained CCEL electronic witness; visual acceptance held."},
    )
    original_tree = etree.fromstring(original)
    bound_tree = etree.fromstring(bound)
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    if etree.tostring(original_tree.find("tei:text", ns), method="c14n") != etree.tostring(bound_tree.find("tei:text", ns), method="c14n"):
        raise ValueError("header binding changed candidate text")
    edition["category"] = "prose"
    work["creators"] = [{"name": "Ambrose of Milan", "role": "author", "evidence": ["raw/ccel/npnf2/npnf210.xml#i-p15", "raw/ccel/npnf2/npnf210.xml#iv.v"]}]
    proposed_work = _json(work)
    proposed = STAGE / "proposed-master.tei.xml"
    if STAGE.exists():
        if {p.name for p in STAGE.iterdir()} not in ({"proposed-work.json", "proposed-master.tei.xml"}, {"proposed-work.json", "proposed-master.tei.xml", "projection-receipt.json"}):
            raise ValueError("the existing proposed-master stage has unexpected members")
        if (STAGE / "proposed-work.json").read_bytes() != proposed_work or proposed.read_bytes() != bound:
            raise ValueError("the existing proposed-master stage differs from the source-bound proposal")
    else:
        STAGE.mkdir()
        (STAGE / "proposed-work.json").write_bytes(proposed_work)
        proposed.write_bytes(bound)
    errors = validate_file(proposed)
    if errors:
        raise ValueError(f"proposed master fails TEI P5: {errors[:3]}")
    public_identity = {key: identity[key] for key in ("work_id", "textual_form_id", "edition_id")}
    try:
        projection = project_document(proposed, identity=public_identity, language="en", representation_revision=REVISION, edition_title=edition["title"], _allow_acceptance_metadata=True, category="prose")
    except PipelineError as exc:
        result = {
            "contract": "ocd-npnf210-mysteries-proposed-master-projection-v1",
            "status": "held-native-projection",
            "acceptance": "pending-revised-visual-review",
            "canonical_install": False,
            "work_id": WORK_ID,
            "identity": identity,
            "source_sha256": source_hash,
            "candidate_sha256": _sha(original),
            "proposed_master_sha256": _sha(bound),
            "proposed_work_sha256": _sha(proposed_work),
            "projection_error_type": type(exc).__name__,
            "projection_error": str(exc)[:500],
            "independent_checker": "not-run-producer-failed",
            "stage": str(STAGE),
        }
        (STAGE / "projection-receipt.json").write_bytes(_json(result))
        return result
    independent_errors = verify_document(proposed, projection["rows"], projection["receipt"], identity=public_identity, language="en", representation_revision=REVISION, edition_title=edition["title"], _allow_acceptance_metadata=True, category="prose")
    result = {
        "contract": "ocd-npnf210-mysteries-proposed-master-projection-v1",
        "status": "pass" if not independent_errors else "failed",
        "acceptance": "pending-revised-visual-review",
        "canonical_install": False,
        "work_id": WORK_ID,
        "identity": identity,
        "source_sha256": source_hash,
        "candidate_sha256": _sha(original),
        "proposed_master_sha256": _sha(bound),
        "proposed_work_sha256": _sha((STAGE / "proposed-work.json").read_bytes()),
        "projection_rows": len(projection["rows"]),
        "projection_receipt_sha256": _sha(_json(projection["receipt"])),
        "projection_unsupported": projection["receipt"].get("unsupported"),
        "projection_warnings": projection["receipt"].get("warnings"),
        "independent_errors": independent_errors,
        "stage": str(STAGE),
    }
    (STAGE / "projection-receipt.json").write_bytes(_json(result))
    if independent_errors:
        raise ValueError(f"independent proposed-master projection errors: {independent_errors[:3]}")
    return result


if __name__ == "__main__":
    print(_json(rehearse()).decode(), end="")
