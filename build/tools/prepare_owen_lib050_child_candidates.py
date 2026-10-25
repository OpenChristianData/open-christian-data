"""Extract seven source-bounded, nonaccepted LIB-050 TEI child candidates.

The source/oracle authority remains the complete ten-member family candidate.
This tool neither creates accepted masters nor changes canonical work sidecars.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from lxml import etree

from build.tei.john_owen_lib050_oracle import _oracle
from ocd_kernel.library._common import PipelineError
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
LIBRARY = Path(r"D:\Library\Open Christian Data")
FAMILY = Path("sources/structured-text/lib050-john-owen")
PROFILE = FAMILY / "john-owen-lib050.reconstruction-profile.json"
MANIFEST = FAMILY / "john-owen-lib050.source-manifest.json"
PARENT = LIBRARY / "candidate-reviews/ticket37-nonblocked-20260912/37c-214"
CHILDREN = (
    "john-owen-apostasy", "john-owen-church-love", "john-owen-death-of-death",
    "john-owen-display-arminianism", "john-owen-divine-justice",
    "john-owen-eshcol", "john-owen-faith-elect",
)
OPENING_TITLES = {
    "john-owen-apostasy": "Nature and Causes of Apostasy from the Gospel",
    "john-owen-church-love": "A Discourse concerning Evangelical Love, Church Peace, and Unity",
    "john-owen-death-of-death": "The Death of Death in the Death of Christ.",
    "john-owen-display-arminianism": "A Display of Arminianism",
    "john-owen-divine-justice": "A Dissertation on Divine Justice",
    "john-owen-eshcol": "Eshcol; A Cluster of the Fruit of Canaan",
    "john-owen-faith-elect": "Gospel Grounds and Evidences of the Faith of God's Elect",
}
NS = {"tei": "http://www.tei-c.org/ns/1.0", "xml": "http://www.w3.org/XML/1998/namespace"}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _source_boundary(row: dict[str, object]) -> tuple[bytes, list[dict[str, str | None]]]:
    source = Path(str(row["path"]))
    content = (ROOT / source).read_bytes()
    if len(content) != row["bytes"] or _sha(content) != row["sha256"]:
        raise PipelineError(f"retained LIB-050 source changed: {source}")
    root = etree.fromstring(content, etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True,
    ))
    body = root.find("ThML.body")
    if root.tag != "ThML" or body is None:
        raise PipelineError(f"retained source envelope differs: {source}")
    divisions = [child for child in body if isinstance(child.tag, str)]
    if not divisions or any(child.tag != "div1" for child in divisions):
        raise PipelineError(f"top-level source boundary differs: {source}")
    titles = [(child.get("title") or "").strip() for child in divisions]
    if titles[0] != OPENING_TITLES[row["work_id"]]:
        raise PipelineError(f"work opening title differs: {source}")
    if row["work_id"] == "john-owen-faith-elect":
        expected = ("Gospel Grounds and Evidences", "Prefatory note", "To the reader",
                    "Evidences of the faith", "The first evidence", "The second evidence",
                    "The third evidence", "The fourth evidence", "Indexes")
        if len(titles) != len(expected) or any(not actual.casefold().startswith(name.casefold()) for actual, name in zip(titles, expected)):
            raise PipelineError("Faith of the Elect internal division envelope differs")
    elif any(title.rstrip(" .") != "Indexes" for title in titles[1:]):
        raise PipelineError(f"source has another titled constituent work: {source}")
    return content, [{"source_id": child.get("id"), "title": child.get("title")}
                     for child in divisions]


def prepare(destination: Path) -> dict[str, object]:
    destination = destination.resolve(strict=False)
    candidate_home = (LIBRARY / "candidate-reviews").resolve(strict=True)
    if destination.exists() or destination.parent != candidate_home or not destination.name.startswith("lib050-seven-work-local-"):
        raise PipelineError("destination must be a fresh declared child of candidate-reviews")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    manifest.verify()
    package = CandidatePackage.load(PARENT / "package")
    recorded = _json(PARENT / "validation.json")
    fresh = validate(manifest, package, _oracle)
    if (recorded.get("status") != "pass" or fresh.status != "pass"
            or recorded.get("candidate_sha256") != package.sha256
            or recorded.get("source_manifest_sha256") != manifest.sha256
            or recorded.get("report_sha256") != fresh.sha256):
        raise PipelineError("current family package or source-led oracle differs")
    corpus = etree.fromstring(package.member_bytes("content.tei.xml"), etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True,
    ))
    all_members = corpus.xpath("./tei:TEI", namespaces=NS)
    if corpus.tag != "{http://www.tei-c.org/ns/1.0}teiCorpus" or len(all_members) != 10:
        raise PipelineError("not the complete ten-member LIB-050 parent package")
    profile = _json(ROOT / PROFILE)
    rows = {str(row["work_id"]): row for row in profile["works"]}
    if len(rows) != 10 or set(CHILDREN) - rows.keys():
        raise PipelineError("LIB-050 profile work inventory differs")
    checked: list[tuple[str, bytes, dict[str, object]]] = []
    for work_id in CHILDREN:
        row = rows[work_id]
        source_bytes, divisions = _source_boundary(row)
        work = _json(ROOT / "library/works" / work_id / "work.json")
        form = work["textual_forms"][0]
        edition = form["editions"][0]
        acquisition_id = edition["acquisition_ids"][0]
        acquisition_path = (Path("library/works") / work_id / "forms" / form["textual_form_id"]
                            / "editions" / edition["edition_id"] / "acquisitions" / (acquisition_id + ".json"))
        acquisition = _json(ROOT / acquisition_path)
        retained = acquisition["retained_files"]
        if (work["work_id"] != work_id or len(work["textual_forms"]) != 1
                or len(form["editions"]) != 1 or len(edition["acquisition_ids"]) != 1
                or len(retained) != 1 or retained[0]["path"] != row["path"]
                or retained[0]["bytes"] != len(source_bytes)
                or retained[0]["sha256"] != _sha(source_bytes)
                or acquisition["source_sha256"] != _sha(source_bytes)):
            raise PipelineError(f"work/acquisition/source binding differs: {work_id}")
        members = corpus.xpath("./tei:TEI[@xml:id=$id]", namespaces=NS, id=work_id)
        if len(members) != 1:
            raise PipelineError(f"one TEI child required: {work_id}")
        tei = etree.tostring(members[0], encoding="UTF-8", xml_declaration=True) + b"\n"
        body = members[0].find("tei:text/tei:body", namespaces=NS)
        if body is None or len(body) != 1 or body[0].get("type") != "retained-source-member":
            raise PipelineError(f"readable/source evidence child differs: {work_id}")
        expected_ids = [row["source_id"] for row in divisions]
        source_names = [div.get("{http://www.w3.org/XML/1998/namespace}id") for div in body[0].xpath("./tei:div[@type='readable-transcription']/tei:div[@type='source-division']", namespaces=NS)]
        if source_names != [f"{work_id}--{source_id}" for source_id in expected_ids]:
            raise PipelineError(f"source divisions absent from child TEI: {work_id}")
        receipt = {
            "contract": "ocd-lib050-work-local-candidate-v1", "status": "nonaccepted",
            "work_id": work_id, "textual_form_id": form["textual_form_id"],
            "edition_id": edition["edition_id"], "acquisition_id": acquisition_id,
            "source_path": row["path"], "source_bytes": len(source_bytes), "source_sha256": _sha(source_bytes),
            "source_divisions": divisions, "source_division_count": len(divisions),
            "tei_sha256": _sha(tei), "tei_bytes": len(tei),
            "parent_package_manifest_sha256": _sha((PARENT / "package/manifest.json").read_bytes()),
            "parent_candidate_sha256": package.sha256, "source_manifest_sha256": manifest.sha256,
            "recorded_validation_sha256": _sha((PARENT / "validation.json").read_bytes()),
            "fresh_oracle_report_sha256": fresh.sha256,
            "oracle_status": fresh.status, "schema_status": "pass",
            "native_projection": "held: retained-source-member has head/readable-transcription/retained-evidence children; current adapter requires readable-transcription/exact-source-evidence",
            "acceptance": "not-staged", "rights_clearance": "not-assessed", "publication": "not-authorized",
        }
        checked.append((work_id, tei, receipt))
    destination.mkdir()
    for work_id, tei, receipt in checked:
        child = destination / work_id
        child.mkdir()
        path = child / "candidate.tei.xml"
        path.write_bytes(tei)
        if errors := validate_file(path):
            raise PipelineError(f"work-local TEI P5 failed for {work_id}: {errors[:3]}")
        (child / "receipt.json").write_bytes((json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    result = {"contract": "ocd-lib050-seven-work-local-candidate-stage-v1", "status": "nonaccepted",
              "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
              "root": destination.as_posix(), "work_ids": list(CHILDREN),
              "source_manifest_sha256": manifest.sha256, "parent_candidate_sha256": package.sha256,
              "fresh_oracle_report_sha256": fresh.sha256,
              "work_receipt_sha256": {work_id: _sha((destination / work_id / "receipt.json").read_bytes()) for work_id in CHILDREN},
              "work_tei_sha256": {work_id: _sha((destination / work_id / "candidate.tei.xml").read_bytes()) for work_id in CHILDREN},
              "acceptance": "not-staged", "canonical_action": "none"}
    (destination / "stage-receipt.json").write_bytes((json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.destination), sort_keys=True))


if __name__ == "__main__":
    main()
