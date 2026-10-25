"""Faithfully reconstruct the twelve LIB-004 NPNF105 works as one TEI candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.writer import XML_ID, XML_LANG, stamp_header, tei_el


SOURCE_SHA256 = "224f0e6a188ddfe691c1433c8db9a883755a9f030b71fede644d4af6c18ee63f"
ASSIGNED = (
    ("x", "augustine-merits-forgiveness-sins"),
    ("xi", "augustine-spirit-and-letter"),
    ("xii", "augustine-nature-and-grace"),
    ("xiii", "augustine-perfection-in-righteousness"),
    ("xiv", "augustine-proceedings-of-pelagius"),
    ("xv", "augustine-grace-of-christ-original-sin"),
    ("xvi", "augustine-marriage-and-concupiscence"),
    ("xvii", "augustine-soul-and-its-origin"),
    ("xviii", "augustine-against-two-letters-pelagians"),
    ("xix", "augustine-grace-and-free-will"),
    ("xx", "augustine-rebuke-and-grace"),
    ("xxi", "augustine-predestination-of-saints"),
)
OUTSIDE_SCOPE = tuple(
    [
        f"{value}"
        for value in (
            "i",
            "ii",
            "iii",
            "iv",
            "v",
            "vi",
            "vii",
            "viii",
            "ix",
            "xxii",
            "xxiii",
        )
    ]
)
TAG_MAP = {
    "div1": "div",
    "div2": "div",
    "div3": "div",
    "p": "p",
    "note": "note",
    "pb": "pb",
    "scripRef": "ref",
    "i": "hi",
    "span": "seg",
    "br": "lb",
}
EXPECTED_COUNTS = {
    "div1": 12,
    "div2": 362,
    "div3": 762,
    "p": 5920,
    "note": 3511,
    "pb": 503,
    "scripRef": 2950,
    "i": 1265,
    "span": 1361,
    "br": 2,
}
MEMBERS = frozenset(
    {
        "content.tei.xml",
        "source-accountability.json",
        "provenance.json",
        "unresolved.jsonl",
        "README.source.md",
    }
)
UNRESOLVED_TRANSLATOR_WORK_IDS = tuple(
    work_id
    for scope, work_id in ASSIGNED
    if scope in {"x", "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii"}
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _parse(path: Path) -> etree._ElementTree:
    return etree.parse(
        str(path),
        etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False),
    )


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value)


def _source_divisions(tree: etree._ElementTree) -> list[etree._Element]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained NPNF105 source has no ThML.body")
    divisions = [
        node for node in body if isinstance(node.tag, str) and node.tag == "div1"
    ]
    observed = [node.get("id") for node in divisions]
    expected = [
        *OUTSIDE_SCOPE[:9],
        *(scope for scope, _ in ASSIGNED),
        *OUTSIDE_SCOPE[9:],
    ]
    if observed != expected:
        raise ValueError("retained NPNF105 div1 order or identity drifted")
    return divisions


def _source_text_by_id(tree: etree._ElementTree, source_id: str) -> str:
    nodes = tree.xpath(f"//*[@id='{source_id}']")
    if len(nodes) != 1:
        raise ValueError(f"retained NPNF105 source evidence {source_id!r} drifted")
    return "".join(nodes[0].itertext())


def _retained_credit_evidence(tree: etree._ElementTree) -> dict[str, str]:
    evidence = {
        source_id: _source_text_by_id(tree, source_id)
        for source_id in (
            "ii-p2",
            "ii-p3",
            "ii-p7",
            "ii-p9",
            "ii-p10",
            "iii-p5",
            "ix-p14",
        )
    }
    exact = {
        "ii-p2": "translated by",
        "ii-p3": "PETER HOLMES, D.D., F.R.A.S.,",
        "ii-p7": "REV. ROBERT ERNEST WALLIS, Ph.d.,",
        "ii-p9": "THE TRANSLATION REVISED, AND AN INTRODUCTION PREFIXED, BY",
        "ii-p10": "BENJAMIN B. WARFIELD, D.D.,",
    }
    if any(evidence[source_id] != text for source_id, text in exact.items()):
        raise ValueError("retained NPNF105 title-page credit evidence drifted")
    if "By the Rev. Professor B.B. Warfield, D.D." not in evidence["iii-p5"]:
        raise ValueError("retained NPNF105 introduction credit evidence drifted")
    allocation = evidence["ix-p14"]
    required = (
        "Grace and Free-Will, Rebuke and Grace, The Predestination of the Saints, The Gift of Perseverance",
        "Against Two Letters of the Pelagians",
        "only the first was from the pen of Dr. Holmes",
        "the rest being the work of Dr. Robert Ernest Wallis",
    )
    if any(phrase not in allocation for phrase in required):
        raise ValueError("retained NPNF105 work-specific translator evidence drifted")
    return evidence


def _translator_allocation(scope: str, title: str) -> dict[str, object]:
    if scope == "xix":
        return {
            "status": "retained-explicit",
            "credited_to": "Peter Holmes",
            "source_xml_id": "ix-p14",
            "retained_scope_titles": [title],
        }
    if scope in {"xviii", "xx", "xxi"}:
        scope_titles = [title]
        if scope == "xxi":
            scope_titles.append("A Treatise on the Gift of Perseverance.")
        return {
            "status": "retained-explicit",
            "credited_to": "Robert Ernest Wallis",
            "source_xml_id": "ix-p14",
            "retained_scope_titles": scope_titles,
        }
    return {
        "status": "unresolved",
        "credited_to": None,
        "source_xml_id": None,
        "retained_scope_titles": [title],
    }


def _selector(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and current.tag != "ThML.body":
        if not isinstance(current.tag, str):
            break
        parent = current.getparent()
        if parent is None:
            break
        siblings = [
            child
            for child in parent
            if isinstance(child.tag, str) and child.tag == current.tag
        ]
        parts.append(f"{current.tag}[{siblings.index(current) + 1}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def _tei_attrs(
    source: etree._Element, feature_number: int
) -> tuple[dict[str, str], list[dict[str, str]]]:
    source_id = source.get("id")
    tei_id = "npnf105-" + (
        _safe_id(source_id) if source_id else f"feature-{feature_number:05d}"
    )
    attrs: dict[str, str] = {"xml:id": tei_id}
    dispositions: list[dict[str, str]] = []
    tag = str(source.tag)
    for name, value in source.attrib.items():
        destination = "source-accountability"
        method = "preserved-exactly"
        if name == "id":
            destination = "@xml:id"
            method = "deterministic-prefix"
        elif name == "n":
            attrs["n"] = value
            destination = "@n"
        elif name == "type":
            attrs["type"] = value
            destination = "@type"
        elif name == "class":
            attrs["rend"] = value
            destination = "@rend"
        elif name == "place" and tag == "note":
            attrs["place"] = value
            destination = "@place"
        elif name == "href" and tag == "pb":
            attrs["facs"] = value
            destination = "@facs"
        elif name == "passage" and tag == "scripRef":
            attrs["cRef"] = value
            destination = "@cRef"
        elif name == "osisRef" and tag == "scripRef":
            attrs["target"] = value
            destination = "@target"
        elif name == "lang" and tag == "span":
            attrs["xml:lang"] = value
            destination = "@xml:lang"
        elif name == "title" and tag.startswith("div"):
            destination = "child::head[1]"
        dispositions.append(
            {
                "source_attribute": name,
                "source_value": value,
                "destination": destination,
                "method": method,
            }
        )
    return attrs, dispositions


def _append_source_node(
    source: etree._Element,
    tei_parent: etree._Element,
    rows: list[dict[str, object]],
    parent_feature_id: str | None,
) -> None:
    number = len(rows) + 1
    feature_id = f"npnf105-feature-{number:05d}"
    attrs, dispositions = _tei_attrs(source, number)
    target = tei_el(TAG_MAP[str(source.tag)], attrs)
    source_title = source.get("title") if str(source.tag).startswith("div") else None
    if source_title is not None:
        target.append(tei_el("head", text=source_title))
    target.text = source.text or ""
    target.tail = source.tail or ""
    child_ordinal = 1 + sum(1 for child in tei_parent if isinstance(child.tag, str))
    tei_parent.append(target)
    row = {
        "feature_id": feature_id,
        "source_selector": _selector(source),
        "source_tag": source.tag,
        "source_xml_id": source.get("id"),
        "attributes": dict(source.attrib),
        "direct_text": source.text or "",
        "tail_text": source.tail or "",
        "direct_text_sha256": _sha((source.text or "").encode("utf-8")),
        "tail_text_sha256": _sha((source.tail or "").encode("utf-8")),
        "tei_tag": TAG_MAP[str(source.tag)],
        "tei_xml_id": target.get(XML_ID),
        "tei_parent_id": tei_parent.get(XML_ID),
        "tei_child_ordinal": child_ordinal,
        "tei_attributes": {
            (
                "xml:id" if key == XML_ID else "xml:lang" if key == XML_LANG else key
            ): value
            for key, value in target.attrib.items()
        },
        "attribute_dispositions": dispositions,
        "disposition": "represented",
        "tei_selector": f"#{target.get(XML_ID)}",
        "assertion": {
            "id": f"npnf105-crosswalk-{number:05d}",
            "profile": "npnf105-assigned-div1-x-through-xxi-v1",
            "role": "retained-source-to-candidate-crosswalk",
            "layer": "reconstruction",
            "status": "asserted",
            "asserted_by": "deterministic-converter",
            "method": "exact-depth-first-source-mapping",
            "evidence": _selector(source),
            "subject": feature_id,
            "destination": f"#{target.get(XML_ID)}",
        },
        "parent_feature_id": parent_feature_id,
        "source_title_head": source_title,
    }
    rows.append(row)
    for child in source:
        if isinstance(child.tag, str):
            if child.tag not in TAG_MAP:
                raise ValueError(f"unsupported retained source element {child.tag!r}")
            _append_source_node(child, target, rows, feature_id)
        else:
            preserved_comment = etree.Comment(child.text or "")
            preserved_comment.tail = child.tail or ""
            target.append(preserved_comment)


def _comment_records(tree: etree._ElementTree) -> list[dict[str, object]]:
    records = []
    for index, comment in enumerate(tree.xpath("//comment()"), start=1):
        parent = comment.getparent()
        division = parent
        while division is not None and not (division.tag == "div1"):
            division = division.getparent()
        scope = division.get("id") if division is not None else "edition-header"
        records.append(
            {
                "ordinal": index,
                "scope": scope,
                "assigned": scope in {value for value, _ in ASSIGNED},
                "text": comment.text or "",
                "sha256": _sha((comment.text or "").encode("utf-8")),
                "tail_text": comment.tail or "",
                "tail_sha256": _sha((comment.tail or "").encode("utf-8")),
                "disposition": "preserved-as-xml-comment"
                if scope in {value for value, _ in ASSIGNED}
                else "outside-assigned-work-scope",
            }
        )
    return records


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    source = source_manifest.authority_path("npnf105-retained-xml")
    if _sha(source.read_bytes()) != SOURCE_SHA256:
        raise ValueError("retained NPNF105 authority digest mismatch")
    tree = _parse(source)
    divisions = _source_divisions(tree)
    selected = divisions[9:21]
    credit_evidence = _retained_credit_evidence(tree)

    root = tei_el("TEI", {"xml:id": "npnf105-lib004"})
    root.append(
        stamp_header(
            title="NPNF1-05. St. Augustine: Anti-Pelagian Writings — assigned works x–xxi",
            author="Augustine of Hippo",
            contributors=[
                {"name": "Philip Schaff", "role": "editor"},
                {"name": "Peter Holmes", "role": "translator"},
                {"name": "Robert Ernest Wallis", "role": "translator"},
                {
                    "name": "Benjamin B. Warfield",
                    "role": "translation reviser and introduction author",
                },
            ],
            source_url="https://www.ccel.org/ccel/schaff/npnf105.html",
            source_sha256=SOURCE_SHA256,
            print_source="New York: Christian Literature Publishing Co., 1886 (retained title-page statement; no print collation)",
            rights_statement="The retained CCEL header states Public Domain. CCEL permits parsing this ThML; do not sell CCEL files or derivatives of their formatting. Attribution is included in README.source.md.",
        )
    )
    text = tei_el("text")
    body = tei_el("body", {"xml:id": "npnf105-assigned-body"})
    text.append(body)
    root.append(text)
    rows: list[dict[str, object]] = []
    for source_div, (scope, work_id) in zip(selected, ASSIGNED, strict=True):
        if source_div.get("id") != scope:
            raise ValueError("assigned scope order drifted")
        before = len(rows)
        _append_source_node(source_div, body, rows, None)
        rows[-(len(rows) - before)]["work_id"] = work_id

    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["source_tag"])] = counts.get(str(row["source_tag"]), 0) + 1
    if len(rows) != 16648 or counts != EXPECTED_COUNTS:
        raise ValueError(
            f"assigned source feature inventory drifted: {len(rows)} {counts}"
        )

    comments = _comment_records(tree)
    division_accounting = []
    mapping = dict(ASSIGNED)
    for ordinal, div in enumerate(divisions, start=1):
        scope = str(div.get("id"))
        division_accounting.append(
            {
                "ordinal": ordinal,
                "div1_id": scope,
                "title": div.get("title", ""),
                "disposition": "assigned-work-represented"
                if scope in mapping
                else "outside-assigned-work-scope",
                "work_id": mapping.get(scope),
            }
        )
    accountability = {
        "contract": "ocd-npnf105-source-accountability-v1",
        "schema": "npnf105.source-accountability.schema.json",
        "profile_id": "npnf105-assigned-div1-x-through-xxi-v1",
        "source_scope": "retained ThML.body div1 x through xxi",
        "source_member": {
            "path": "raw/ccel/npnf1/npnf105.xml",
            "bytes": len(source.read_bytes()),
            "sha256": SOURCE_SHA256,
        },
        "assigned_work_count": 12,
        "feature_count": len(rows),
        "feature_counts": counts,
        "omitted_feature_count": 0,
        "unresolved_feature_count": 0,
        "division_accounting": division_accounting,
        "comment_accounting": comments,
        "crosswalk": rows,
    }
    provenance = {
        "contract": "ocd-npnf105-provenance-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "source": {
            "path": "raw/ccel/npnf1/npnf105.xml",
            "sha256": SOURCE_SHA256,
            "scope": "div1 x through xxi",
        },
        "works": [
            {
                "ordinal": index,
                "div1_id": scope,
                "work_id": work_id,
                "title": selected[index - 1].get("title", ""),
                "translator_allocation": _translator_allocation(
                    scope,
                    selected[index - 1].get("title", ""),
                ),
            }
            for index, (scope, work_id) in enumerate(ASSIGNED, start=1)
        ],
        "edition": {
            "title": "NPNF1-05. St. Augustine: Anti-Pelagian Writings",
            "editor": "Philip Schaff",
            "publication": "New York: Christian Literature Publishing Co., 1886",
            "source_identifier": "/ccel/schaff/npnf105.html",
        },
        "translation_credit": {
            "retained_title_page_credits": [
                {
                    "name": "Peter Holmes",
                    "role": "translator",
                    "name_source_xml_id": "ii-p3",
                    "role_source_xml_id": "ii-p2",
                },
                {
                    "name": "Robert Ernest Wallis",
                    "role": "translator",
                    "name_source_xml_id": "ii-p7",
                    "role_source_xml_id": "ii-p2",
                },
                {
                    "name": "Benjamin B. Warfield",
                    "role": "translation reviser and introduction author",
                    "name_source_xml_id": "ii-p10",
                    "role_source_xml_ids": ["ii-p9", "iii-p5"],
                },
            ],
            "work_specific_allocation": "partially resolved from retained div1 ix",
            "work_specific_allocation_evidence": {
                "source_xml_id": "ix-p14",
                "text": credit_evidence["ix-p14"],
            },
            "schaff_translator_claim": "not adopted; retained evidence identifies Schaff as editor",
        },
        "rights": {
            "retained_statement": "Public Domain",
            "ccel_formatting_condition": "Do not sell CCEL files or derivatives of their formatting.",
            "publication_state": "not_ready",
        },
        "canonical_data_written": False,
    }
    unresolved = [
        {
            "id": "npnf105-work-specific-translator-allocation",
            "scope": "8-assigned-works",
            "status": "unresolved",
            "work_ids": list(UNRESOLVED_TRANSLATOR_WORK_IDS),
            "question": "Which retained translator credit applies to each of the eight assigned works not allocated by div1 ix?",
            "evidence": "Retained div1 ix allocates Grace and Free-Will to Peter Holmes and Rebuke and Grace, Predestination of the Saints with its Gift of Perseverance second book, and Against Two Letters of the Pelagians to Robert Ernest Wallis; it does not safely allocate the remaining eight assigned works.",
        },
        {
            "id": "npnf105-print-collation-not-performed",
            "scope": "edition",
            "status": "unresolved",
            "question": "Does the retained electronic witness differ substantively from the stated 1886 print edition?",
            "evidence": "The candidate is bound to the retained CCEL XML; no print collation was performed.",
        },
        {
            "id": "npnf105-human-acceptance-and-publication",
            "scope": "all-12-assigned-works",
            "status": "unresolved",
            "question": "Will a maintainer accept these candidate texts and separately authorize publication?",
            "evidence": "Technical verification is not human acceptance or publication authorization.",
        },
    ]
    readme = """# NPNF1-05 assigned-work reconstruction source\n\nThis nonaccepted TEI candidate is reconstructed deterministically from the retained `raw/ccel/npnf1/npnf105.xml` member, exact SHA-256 `224f0e6a188ddfe691c1433c8db9a883755a9f030b71fede644d4af6c18ee63f`, for `div1` x through xxi.\n\nThe retained header identifies the underlying text as public domain and the print source as *New York: Christian Literature Publishing Co., 1886*. The retained edition is sourced via [CCEL.org](https://www.ccel.org/ccel/schaff/npnf105.html). CCEL permits parsing its ThML; do not sell CCEL files or derivatives of CCEL's formatting. This candidate reconstructs textual and structural content and does not claim CCEL formatting as an original work.\n\nPhilip Schaff is retained as editor. The retained title-page credits Peter Holmes and Robert Ernest Wallis as translators, and Benjamin B. Warfield with revising the translation and prefixing an introduction. Retained `div1` ix allocates *Grace and Free-Will* to Holmes and allocates *Rebuke and Grace*, *The Predestination of the Saints* with its *Gift of Perseverance* second book, and *Against Two Letters of the Pelagians* to Wallis. Translator allocation remains unresolved for the other eight assigned works. Human textual acceptance and publication remain separate and absent.\n""".encode(
        "utf-8"
    )
    return {
        "README.source.md": readme,
        "content.tei.xml": etree.tostring(
            root, encoding="UTF-8", xml_declaration=True, pretty_print=False
        ),
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
    }


_convert.converter_id = "ocd-npnf105-assigned-works-to-tei"
_convert.converter_version = "2"


def reconstruct_candidate(
    source_manifest: SourceManifest, destination: str | Path
) -> CandidatePackage:
    """Seal a candidate at the caller's regenerable path without governed writes."""

    source_manifest.verify()
    converter = source_manifest.record["converter"]
    assert isinstance(converter, Mapping)
    implementation = Path(__file__).resolve(strict=True)
    expected = source_manifest.repository_root / str(converter["implementation_path"])
    if (
        converter.get("id") != _convert.converter_id
        or converter.get("version") != _convert.converter_version
        or converter.get("callable") != _convert.__name__
        or not implementation.samefile(expected)
        or _sha(implementation.read_bytes()) != converter.get("implementation_sha256")
    ):
        raise ValueError("converter callable provenance mismatch")
    output = Path(destination).resolve(strict=False)
    protected = [
        source_manifest.repository_root / value
        for value in (
            "raw",
            "data",
            "ir",
            "reports",
            "exports",
            "acceptance",
            "publication",
        )
    ]
    if any(
        output == path.resolve(strict=False)
        or path.resolve(strict=False) in output.parents
        for path in protected
    ):
        raise ValueError("candidate destination resolves inside governed storage")
    if not output.parent.is_dir():
        raise ValueError("candidate destination parent must already exist")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("candidate destination must be an empty directory")
    produced = _convert(source_manifest)
    if set(produced) != MEMBERS:
        raise ValueError("converter member set mismatch")
    manifest = {
        "contract": "ocd-candidate-package-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "source_manifest": {
            "path": source_manifest.path.relative_to(
                source_manifest.repository_root
            ).as_posix(),
            "sha256": source_manifest.sha256,
        },
        "converter": dict(converter),
        "package_schema": dict(source_manifest.record["package_schema"]),
        "members": [
            {"name": name, "bytes": len(produced[name]), "sha256": _sha(produced[name])}
            for name in sorted(produced)
        ],
    }
    schema_path = source_manifest.repository_root / str(
        source_manifest.record["package_schema"]["path"]
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(manifest), key=str)
    if errors:
        raise ValueError(f"candidate manifest schema failure: {errors[0].message}")
    output.mkdir(exist_ok=True)
    for name, content in sorted(produced.items()):
        (output / name).write_bytes(content)
    (output / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    manifest = SourceManifest.load(args.manifest, repository_root=args.repository_root)
    package = reconstruct_candidate(manifest, args.destination)
    print(
        json.dumps(
            {"candidate": str(package.path), "candidate_sha256": package.sha256},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
