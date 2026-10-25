"""Prepare source-checked, work-local NPNF204 child TEI in a fresh stage.

This command writes no canonical library files and makes no acceptance decision.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import os

from lxml import etree

from build.tei.athanasius_table_oracle import _oracle, _verify_tei
from build.tei.athanasius_table_reconstruction import ASSIGNED, SOURCE_SHA256, _work_credit
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file
from ocd_kernel.tei.writer import tei_el, stamp_header


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "raw/ccel/npnf2/npnf204.xml"
MANIFEST = ROOT / "sources/structured-text/athanasius-on-the-incarnation/athanasius-table.source-manifest.json"
AGGREGATE = Path("D:/Library/Open Christian Data/candidate-reviews/37c-008-014-athanasius-lib045-20260920-v2")
REVIEW_ROOT = Path("D:/Library/Open Christian Data/candidate-reviews")
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _io(path: Path) -> Path:
    absolute = path.resolve(strict=False)
    return Path("\\\\?\\" + str(absolute)) if os.name == "nt" else absolute


def _read(path: Path) -> bytes:
    return _io(path).read_bytes()


def _json(content: object) -> bytes:
    return (json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _write(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    _io(target).write_bytes(content)
    return target


def prepare(stage: Path) -> dict[str, object]:
    stage = stage.resolve()
    if (stage.exists() or stage.parent != REVIEW_ROOT.resolve(strict=True)
            or not stage.name.startswith("athanasius-npnf204-work-local-")):
        raise ValueError("Athanasius child stage must be a fresh named child of the durable candidate root")
    source_bytes = _read(SOURCE)
    if _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("retained NPNF204 bytes changed")
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(AGGREGATE / "package")
    prior = json.loads(_read(AGGREGATE / "validation.json"))
    result = validate(manifest, package, _oracle)
    if (prior["status"] != "pass" or prior["candidate_sha256"] != package.sha256
            or prior["report_sha256"] != result.sha256):
        raise ValueError("aggregate oracle receipt changed")
    aggregate_bytes = package.member_bytes("content.tei.xml")
    source_tree = etree.ElementTree(etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True)))
    _verify_tei(source_tree, aggregate_bytes)
    source_divs = source_tree.xpath("/ThML/ThML.body/div1")
    aggregate_tree = etree.fromstring(aggregate_bytes)
    target_divs = aggregate_tree.xpath("./t:text/t:body/t:div", namespaces={"t": TEI_NS})
    if (len(source_divs) != 26 or len(target_divs) != 20
            or [node.get("id") for node in source_divs[5:25]] != [scope for scope, _ in ASSIGNED]):
        raise ValueError("declared child division census changed")
    incarnation_source = source_divs[6]
    incarnation_target = target_divs[1]
    if (sum(isinstance(node.tag, str) for node in incarnation_source.iter()) != 1241
            or len(incarnation_source.xpath(".//table")) != 1
            or len(incarnation_source.xpath(".//tr")) != 55
            or len(incarnation_source.xpath(".//td")) != 165
            or len(incarnation_target.xpath(".//t:table", namespaces={"t": TEI_NS})) != 1
            or len(incarnation_target.xpath(".//t:row", namespaces={"t": TEI_NS})) != 55
            or len(incarnation_target.xpath(".//t:cell", namespaces={"t": TEI_NS})) != 165):
        raise ValueError("protected Athanasius table contract changed")
    stage.mkdir(parents=True)
    rows: list[dict[str, object]] = []
    for (scope, work_id), source_div, target_div in zip(ASSIGNED, source_divs[5:25], target_divs, strict=True):
        if target_div.get(XML_ID) != f"npnf204-{scope}":
            raise ValueError(f"aggregate TEI child boundary changed: {work_id}")
        work_dir = ROOT / "library/works" / work_id
        work = json.loads(_read(work_dir / "work.json"))
        state = json.loads(_read(work_dir / "state.json"))
        form = work["textual_forms"][0]
        edition = form["editions"][0]
        identity = {"work_id": work_id, "textual_form_id": form["textual_form_id"], "edition_id": edition["edition_id"], "acquisition_id": edition["acquisition_ids"][0]}
        if (work["work_id"] != work_id or edition["containing_source"]["locator"] != f"raw/ccel/npnf2/npnf204.xml#{scope}"
                or form["language"] != "en" or edition["language"] != "en"):
            raise ValueError(f"canonical child identity or locator changed: {work_id}")
        acquisition_path = work_dir / "forms" / form["textual_form_id"] / "editions" / edition["edition_id"] / "acquisitions" / f"{identity['acquisition_id']}.json"
        acquisition = json.loads(_read(acquisition_path))
        if (len(acquisition["retained_files"]) != 1
                or acquisition["retained_files"][0]["sha256"] != SOURCE_SHA256
                or acquisition["retained_files"][0]["bytes"] != len(source_bytes)):
            raise ValueError(f"acquisition source binding changed: {work_id}")
        root = tei_el("TEI", {"xml:id": f"npnf204-{scope}-work"})
        contributors = [{"name": "Philip Schaff", "role": "editorial supervisor"}, {"name": "Henry Wace", "role": "editorial supervisor"}, {"name": "Archibald Robertson", "role": "special editor"}]
        local_credit = _work_credit(scope)
        if local_credit["status"] == "retained-explicit":
            contributors.append({"name": local_credit["credited_to"], "role": local_credit["role"]})
        root.append(stamp_header(
            title=work["title"],
            author="Eusebius of Caesarea" if scope == "ix" else "Athanasius of Alexandria",
            contributors=contributors,
            source_url=acquisition["url"], source_sha256=SOURCE_SHA256,
            print_source="NPNF Second Series, Volume IV: Athanasius: Select Works and Letters; retained electronic witness, no print collation",
            rights_statement="CCEL permits parsing its ThML and asks that CCEL files or derivatives of its formatting not be sold. Rights clearance and publication remain separate.",
        ))
        text = tei_el("text")
        body = tei_el("body")
        body.append(deepcopy(target_div))
        text.append(body)
        root.append(text)
        content = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
        child = etree.fromstring(content)
        child_div = child.xpath("./t:text/t:body/t:div", namespaces={"t": TEI_NS})[0]
        if etree.tostring(child_div, method="c14n") != etree.tostring(target_div, method="c14n"):
            raise ValueError(f"child extraction changed the source-checked TEI subtree: {work_id}")
        revision = {"id": f"{work_id}-npnf204-electronic-v1", "date": "2026-09-26", "note": "Proposed work-local electronic witness; canonical acceptance pending."}
        scope_text = f"Complete retained NPNF204 div1 {scope}: {source_div.get('title')}"
        bound = bind_reviewed_header(content, expected_sha256=_sha(content), identity=identity,
                                     source={"source_path": "raw/ccel/npnf2/npnf204.xml", "source_sha256": SOURCE_SHA256, "source_bytes": len(source_bytes)},
                                     source_url=acquisition["url"], declared_scope=scope_text, revision=revision)
        path = _write(stage, Path(work_id) / "proposed-master.tei.xml", bound)
        errors = validate_file(path)
        if errors:
            raise ValueError(f"TEI P5 failure for {work_id}: {errors[:2]}")
        try:
            public_identity = {key: identity[key] for key in ("work_id", "textual_form_id", "edition_id")}
            projection = project_document(_io(path), identity=public_identity, language="en", representation_revision=revision["id"], edition_title=edition["title"], category="prose", _allow_acceptance_metadata=True)
            projection_errors = verify_document(_io(path), projection["rows"], projection["receipt"], identity=public_identity, language="en", representation_revision=revision["id"], edition_title=edition["title"], category="prose", _allow_acceptance_metadata=True)
            projection_status = "pass" if not projection_errors and not projection["receipt"].get("unsupported") else "hold"
            projection_rows = len(projection["rows"])
            canary = {"status": projection_status, "row_count": projection_rows, "unsupported": projection["receipt"].get("unsupported", []), "warnings": projection["receipt"].get("warnings", []), "independent_verifier_errors": projection_errors}
        except PipelineError as exc:
            diagnostic = str(exc)
            projection_status = "hold"
            projection_rows = 0
            canary = {"status": "hold", "row_count": 0, "failure_class": type(exc).__name__, "failure_prefix": diagnostic[:180], "failure_sha256": _sha(diagnostic.encode("utf-8"))}
        _write(stage, Path(work_id) / "projection-canary.json", _json(canary))
        source_count = sum(isinstance(node.tag, str) for node in source_div.iter())
        target_count = sum(isinstance(node.tag, str) for node in target_div.iter())
        record = {"work_id": work_id, "source_root_id": scope, "source_title": source_div.get("title"), "source_element_count": source_count,
                  "aggregate_tei_element_count": target_count, "identity": identity, "original_child_sha256": _sha(content),
                  "proposed_master_sha256": _sha(bound), "projection_rows": projection_rows,
                  "projection_status": projection_status,
                  "canonical_work_sha256": _sha(_read(work_dir / "work.json")), "canonical_state_sha256": _sha(_read(work_dir / "state.json")),
                  "canonical_acquisition_sha256": _sha(_read(acquisition_path))}
        _write(stage, Path(work_id) / "source-check.json", _json(record))
        rows.append(record)
    _write(stage, Path("README.source.md"), _read(AGGREGATE / "package" / "README.source.md"))
    files = {path.relative_to(stage).as_posix(): _sha(_read(path)) for path in sorted(stage.rglob("*")) if path.is_file()}
    receipt = {"contract": "ocd-athanasius-npnf204-child-stage-v1", "status": "source-checked-projection-held" if any(item["projection_status"] != "pass" for item in rows) else "staged-only", "source_sha256": SOURCE_SHA256,
               "source_bytes": len(source_bytes), "source_manifest_sha256": manifest.sha256, "aggregate_candidate_sha256": package.sha256,
               "aggregate_validation_sha256": _sha(_read(AGGREGATE / "validation.json")), "work_count": len(rows), "works": rows,
               "files": files, "files_sha256": _sha(_json(files)),
               "canonical_install": False, "human_review": "not-recorded", "rights_clearance": "not-assessed", "publication": "not-authorized"}
    _write(stage, Path("stage-receipt.json"), _json(receipt))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    receipt = prepare(args.stage)
    print(json.dumps({"work_count": receipt["work_count"], "stage": str(args.stage)}, sort_keys=True))


if __name__ == "__main__":
    main()
