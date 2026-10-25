"""Independent source/order and native check for Owen's Of Temptation CCEL edition."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.contract import _canonical, _runtime_binding


ROOT = Path(__file__).resolve().parents[2]
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"
SOURCES = {
    "temptation": (
        "john-owen-temptation",
        "raw/ccel/owen/temptation.xml",
        "6b5231f59965fe7b7d75db2f59919fd5e9aff429d48e65cabb528f393c14a0ab",
        1228, 0, [], ["ii"],
    ),
}


def check(member_id: str, directory: Path, *, formal: bool = False) -> dict[str, object]:
    work_id, source_rel, sha, expected_elements, expected_comments, front_ids, back_ids = SOURCES[member_id]
    source_bytes = (ROOT / source_rel).read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != sha:
        raise ValueError(f"{member_id} retained source identity differs")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False,
                             remove_pis=False, huge_tree=True)
    source = etree.fromstring(source_bytes, parser)
    body = source.find("ThML.body")
    if body is None:
        raise ValueError(f"{member_id} source body missing")
    candidate_path = directory / ("content.tei.xml" if formal else f"{member_id}.tei.xml")
    candidate = etree.parse(str(candidate_path))
    source_title = source.findtext("ThML.head/electronicEdInfo/DC/DC.Title")
    candidate_title = candidate.findtext(
        f".//{NS}teiHeader/{NS}fileDesc/{NS}titleStmt/{NS}title"
    )
    if source_title != "Of Temptation" or candidate_title != source_title:
        raise ValueError(f"{member_id} electronic header title differs")
    schema = etree.XMLSchema(etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")))
    if not schema.validate(candidate):
        raise ValueError(f"{member_id} TEI P5: {schema.error_log[0]}")
    regions = candidate.getroot().find(NS + "text")
    if regions is None or [x.tag for x in regions] != [NS + x for x in ("front", "body", "back")]:
        raise ValueError(f"{member_id} TEI divisions differ")
    if regions[0].text != body.text or regions[1].text or regions[2].text:
        raise ValueError(f"{member_id} source body envelope text differs")
    roots = [x for x in body if isinstance(x.tag, str)]
    if ([x.get("id") for x in roots] != ["i", "ii"]
            or [x.get("id") for x in roots if x.get("id") in front_ids] != front_ids
            or [x.get("id") for x in roots if x.get("id") in back_ids] != back_ids):
        raise ValueError(f"{member_id} source roots differ")
    source_elements = [x for x in body.iter() if isinstance(x.tag, str)][1:]
    tei_elements = [x for part in regions for root in part for x in root.iter()
                    if isinstance(x.tag, str) and x.tag not in {NS + "graphic", NS + "figDesc", NS + "label"}]
    if len(source_elements) != expected_elements or len(tei_elements) != expected_elements:
        raise ValueError(f"{member_id} source or TEI feature count differs")
    source_ids = [x.get("id") for x in source_elements if x.get("id")]
    from collections import Counter
    duplicates = {key: count for key, count in Counter(source_ids).items() if count > 1}
    if duplicates:
        raise ValueError(f"{member_id} source IDs are duplicated")
    id_occurrences: dict[str, int] = {}
    source_id_set = set(source_ids)
    source_position = {element: index for index, element in enumerate(source_elements)}
    paired = zip(source_elements, tei_elements, strict=True)
    for ordinal, (left, right) in enumerate(paired, 1):
        source_id = left.get("id")
        if source_id:
            id_occurrences[source_id] = id_occurrences.get(source_id, 0) + 1
        expected_id = (f"{member_id}-{source_id}-source-occurrence-{id_occurrences[source_id]}"
                       if source_id in duplicates else f"{member_id}-{source_id}") if source_id else f"{member_id}-feature-{ordinal:06d}"
        if right.get(XML + "id") != expected_id or (left.text or "") != (right.text or "") or (left.tail or "") != (right.tail or ""):
            raise ValueError(f"{member_id} source ID or direct text/tail differs at feature {ordinal}")
        tag = left.tag
        expected_tag = (
            "div" if tag.startswith("div") and tag != "div" else
            "quote" if tag == "div" else
            "p" if tag == "argument" else
            "name" if tag == "name" else
            "hi" if tag == "cite" else
            "p" if tag in {"p", "h1", "h2", "h3", "h4"} else
            "hi" if tag in {"i", "b", "small", "em", "sup", "cite"} else
            "seg" if tag == "a" and (left.get("href") or "").startswith("#") and left.get("href")[1:] not in source_id_set else
            "ref" if tag in {"scripRef"} or tag == "a" and left.get("href") is not None else
            "seg" if tag == "a" and (left.text or len(left)) else
            "anchor" if tag == "a" else
            "milestone" if tag in {"scripCom", "scripContext", "insertIndex", "hr"} else
            "lb" if tag == "br" else
            "seg" if tag == "span" else
            "lg" if tag == "verse" else "list" if tag == "ul" else "item" if tag == "li" else
            "quote" if tag == "blockquote" else tag
        )
        if right.tag != NS + expected_tag:
            raise ValueError(f"{member_id} TEI tag differs at source feature {ordinal}")
        if tag == "insertIndex" and (right.get("unit") != "insertIndex" or right.get("type") != left.get("type")
                or right.get("{http://www.w3.org/XML/1998/namespace}lang") != left.get("lang")):
            raise ValueError(f"{member_id} source index marker type/language differs at feature {ordinal}")
        if tag == "argument" and right.get("rend") != "source-argument":
            raise ValueError(f"{member_id} source argument type differs at feature {ordinal}")
        if tag == "name" and right.get("key") != left.get("title"):
            raise ValueError(f"{member_id} source name title differs at feature {ordinal}")
        if tag == "scripContext" and (right.get("unit") != "scripContext" or right.get("n") != left.get("version")):
            raise ValueError(f"{member_id} scripture context differs at feature {ordinal}")
        if tag == "hr" and (right.get("unit") != "horizontal-rule" or right.get("rend") != "source-class-" + left.get("class", "")):
            raise ValueError(f"{member_id} source horizontal rule differs at feature {ordinal}")
        if tag == "cite" and (right.get("rend") != "source-citation" or right.get("n") != left.get("title") or right.get("target") is not None):
            raise ValueError(f"{member_id} source citation rendition differs at feature {ordinal}")
        if tag == "hr" and (right.get("unit") != "horizontal-rule" or right.text or len(right)):
            raise ValueError(f"{member_id} source horizontal rule differs at feature {ordinal}")
        if tag == "blockquote" and right.get("type") != "source-blockquote":
            raise ValueError(f"{member_id} source blockquote type differs at feature {ordinal}")
        if tag == "scripRef" and right.get("target") != left.get("osisRef"):
            raise ValueError(f"{member_id} source scripture reference differs at feature {ordinal}")
        if tag == "pb" and right.get("n") != left.get("n"):
            raise ValueError(f"{member_id} source page break differs at feature {ordinal}")
        if tag == "a" and left.get("href") is None and expected_tag == "seg" and right.get("type") != "source-anchor":
            raise ValueError(f"{member_id} textual source anchor type differs at feature {ordinal}")
        if left.getparent() is not body:
            expected_parent = tei_elements[source_position[left.getparent()]]
            if right.getparent() is not expected_parent:
                raise ValueError(f"{member_id} source hierarchy differs at source feature {ordinal}")
        if tag == "a" and (left.get("href") or "").startswith("#") and left.get("href")[1:] not in source_id_set:
            if (right.get("type") != "source-unresolved-link" or right.get("n") != left.get("href")
                    or right.get("target") is not None):
                raise ValueError(f"{member_id} source-broken local link differs at feature {ordinal}")
        elif tag == "a" and left.get("href"):
            target = left.get("href")
            if target.startswith("#"):
                target = f"#{member_id}-{target[1:]}"
            if right.get("target") != target:
                raise ValueError(f"{member_id} TEI link differs at source feature {ordinal}")
    source_comments = [x for x in body.iter() if x.tag is etree.Comment]
    if len(source_comments) != expected_comments or any((x.tail or "").strip() for x in source_comments):
        raise ValueError(f"{member_id} source comment disposition differs")
    ledger = json.loads((directory / ("source-accountability.json" if formal else f"{member_id}.source-accountability.json")).read_bytes())
    if ledger["feature_count"] != expected_elements or ledger["comment_count"] != expected_comments:
        raise ValueError(f"{member_id} ledger counts differ")
    expected_broken = []
    if ledger.get("broken_local_links") != expected_broken:
        raise ValueError(f"{member_id} broken-link ledger differs")
    for position, (left, right) in enumerate(zip(source_elements, ledger["features"], strict=True), 1):
        if (right["ordinal"] != position or right["source_tag"] != left.tag
                or right["source_id"] != left.get("id") or right["source_attributes"] != dict(left.attrib)
                or right["source_text"] != (left.text or "") or right["source_tail"] != (left.tail or "")):
            raise ValueError(f"{member_id} source ledger differs at {position}")
    comments = ledger["comments"]
    if [(x["text"], x["tail"]) for x in comments] != [(x.text or "", x.tail or "") for x in source_comments] or any(x["disposition"] != "source-comment-ledger-only" for x in comments):
        raise ValueError(f"{member_id} source comments ledger differs")
    ordered: list[tuple[str, etree._Element]] = []
    def walk(node: etree._Element) -> None:
        for child in node:
            ordered.append(("element" if isinstance(child.tag, str) else "comment", child))
            if isinstance(child.tag, str):
                walk(child)
    walk(body)
    feature_position = 0
    comment_position = 0
    for kind, node in ordered:
        if kind == "element":
            feature_position += 1
        else:
            if node.tag is not etree.Comment or comments[comment_position]["after_feature"] != feature_position:
                raise ValueError(f"{member_id} source comment order differs")
            comment_position += 1
    work = json.loads((ROOT / "library/works" / work_id / "work.json").read_bytes())
    edition = next(e for form in work["textual_forms"] for e in form["editions"] if member_id in e["edition_id"])
    form = next(f for f in work["textual_forms"] if edition in f["editions"])
    args = {"identity": {"work_id": work_id, "textual_form_id": form["textual_form_id"], "edition_id": edition["edition_id"]},
            "language": "en", "representation_revision": "owen-temptation-readable-probe-v1",
            "edition_title": edition["title"], "category": "prose"}
    projected = project_document(candidate_path, **args)
    failures = verify_document(candidate_path, projected["rows"], projected["receipt"], **args)
    if failures:
        raise ValueError(f"{member_id} independent native verifier failed: {failures[:2]}")
    return {"member_id": member_id, "source_sha256": sha,
            "tei_sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
            "source_elements": expected_elements, "source_comments": expected_comments,
            "native_rows": len(projected["rows"]), "p5": True, "native_verification": "passed"}


def _oracle(source: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source.verify()
    candidate.verify_integrity()
    member_id = source.record["source_id"].removeprefix("ccel-owen-lib052-readable-").removesuffix("-v1")
    if member_id not in SOURCES or candidate.manifest["status"] != "nonaccepted" or candidate.manifest["converter"] != source.record["converter"]:
        raise ValueError("Owen Of Temptation candidate source or converter binding differs")
    result = check(member_id, candidate.path, formal=True)
    if (source.authority_path("retained-thml").read_bytes()
            != (ROOT / SOURCES[member_id][1]).read_bytes()):
        raise ValueError("Owen Of Temptation candidate source authority differs")
    if json.loads(candidate.member_bytes("provenance.json"))["work_id"] != SOURCES[member_id][0]:
        raise ValueError("Owen Of Temptation candidate provenance work differs")
    record = {
        "status": "pass", "oracle_id": _oracle.oracle_id, "oracle_version": _oracle.oracle_version,
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "import_closure_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "runtime": _runtime_binding(), "source_manifest_sha256": source.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": next(a["sha256"] for a in source.record["authorities"] if a["role"] == "complete-source-feature-profile"),
        "package_schema_sha256": next(a["sha256"] for a in source.record["authorities"] if a["role"] == "candidate-package-schema"),
        "source_sha256": result["source_sha256"],
        "xsd_sha256": next(a["sha256"] for a in source.record["authorities"] if a["role"] == "tei-validation-schema"),
        "policy_sha256": next(a["sha256"] for a in source.record["authorities"] if a["role"] == "independent-validation-policy"),
        "findings": [f"Independently checked {result['source_elements']} source elements, {result['source_comments']} comments, ordered source divisions, TEI P5, and {result['native_rows']} native rows for {member_id}."],
    }
    record["result_sha256"] = hashlib.sha256(_canonical(record)).hexdigest()
    return record


_oracle.oracle_id = "ocd-owen-lib052-temptation-readable-independent-oracle"
_oracle.oracle_version = "1"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps([check(member_id, args.directory) for member_id in SOURCES], sort_keys=True))


if __name__ == "__main__":
    main()
