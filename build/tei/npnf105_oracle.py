"""Producer-independent retained-source oracle for the LIB-004 NPNF105 candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    ValidationReport,
    validate,
)


SOURCE_SHA256 = "224f0e6a188ddfe691c1433c8db9a883755a9f030b71fede644d4af6c18ee63f"
XML_NS = "http://www.w3.org/XML/1998/namespace"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"
EXPECTED_TEI_PROLOG = b"<?xml version='1.0' encoding='UTF-8'?>\n"
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
ALL_DIV1 = (
    "i",
    "ii",
    "iii",
    "iv",
    "v",
    "vi",
    "vii",
    "viii",
    "ix",
    "x",
    "xi",
    "xii",
    "xiii",
    "xiv",
    "xv",
    "xvi",
    "xvii",
    "xviii",
    "xix",
    "xx",
    "xxi",
    "xxii",
    "xxiii",
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
EXPECTED_COMMENT_TEXTS = (
    ' <a href="#_edn1609" name="_ednref1609" id="xiv.iv-p1.3">  ',
    " </a> ",
    ' <a href="#_edn3415" name="_ednref3415" id="xxi.ii-p5.3"> ',
    " </a> ",
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_object(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _parse(content_or_path: bytes | Path) -> etree._ElementTree:
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, remove_comments=False
    )
    try:
        if isinstance(content_or_path, Path):
            return etree.parse(str(content_or_path), parser)
        return etree.ElementTree(etree.fromstring(content_or_path, parser))
    except etree.XMLSyntaxError as exc:
        raise ValueError(
            "XML evidence is not well-formed or has duplicate IDs"
        ) from exc


def _parse_candidate_tei(content: bytes) -> etree._ElementTree:
    if not content.startswith(EXPECTED_TEI_PROLOG):
        raise ValueError("TEI document prolog drift")
    if content[len(EXPECTED_TEI_PROLOG) : len(EXPECTED_TEI_PROLOG) + 1] != b"<":
        raise ValueError("TEI document prolog drift")
    tree = _parse(content)
    if tree.docinfo.doctype:
        raise ValueError("TEI document prolog drift")
    return tree


def _assert_document_topology(tree: etree._ElementTree) -> None:
    root = tree.getroot()
    if root.getprevious() is not None or root.getnext() is not None:
        raise ValueError("TEI document contains an unbound top-level node")
    expected_nsmap = {None: TEI_NS}
    for node in root.iter():
        if isinstance(node.tag, str) and node.nsmap != expected_nsmap:
            raise ValueError("TEI namespace topology drift")


def _single_text(tree: etree._ElementTree, xpath: str, label: str) -> str:
    values = tree.xpath(xpath)
    if len(values) != 1 or not isinstance(values[0], str) or not values[0]:
        raise ValueError(f"retained source {label} evidence drift")
    return values[0]


def _source_text_by_id(tree: etree._ElementTree, source_id: str) -> str:
    nodes = tree.xpath(f"//*[@id='{source_id}']")
    if len(nodes) != 1:
        raise ValueError(f"retained source evidence {source_id!r} drift")
    return "".join(nodes[0].itertext())


def _retained_credit_evidence(
    source_tree: etree._ElementTree,
    profile: Mapping[str, object],
) -> dict[str, str]:
    selectors = profile.get("retained_credit_evidence")
    if not isinstance(selectors, Mapping):
        raise ValueError(
            "reconstruction profile lacks retained credit evidence selectors"
        )
    expected_selectors = {
        "title_page_role": "ii-p2",
        "peter_holmes": "ii-p3",
        "robert_ernest_wallis": "ii-p7",
        "warfield_roles": ["ii-p9", "iii-p5"],
        "benjamin_b_warfield": "ii-p10",
        "work_specific_allocation": "ix-p14",
    }
    if dict(selectors) != expected_selectors:
        raise ValueError("reconstruction profile retained credit selectors drift")
    source_ids = ("ii-p2", "ii-p3", "ii-p7", "ii-p9", "ii-p10", "iii-p5", "ix-p14")
    evidence = {
        source_id: _source_text_by_id(source_tree, source_id)
        for source_id in source_ids
    }
    exact = {
        "ii-p2": "translated by",
        "ii-p3": "PETER HOLMES, D.D., F.R.A.S.,",
        "ii-p7": "REV. ROBERT ERNEST WALLIS, Ph.d.,",
        "ii-p9": "THE TRANSLATION REVISED, AND AN INTRODUCTION PREFIXED, BY",
        "ii-p10": "BENJAMIN B. WARFIELD, D.D.,",
    }
    if any(evidence[source_id] != text for source_id, text in exact.items()):
        raise ValueError("retained source title-page contributor evidence drift")
    if "By the Rev. Professor B.B. Warfield, D.D." not in evidence["iii-p5"]:
        raise ValueError("retained source introduction byline evidence drift")
    allocation = evidence["ix-p14"]
    allocation_phrases = (
        "Grace and Free-Will, Rebuke and Grace, The Predestination of the Saints, The Gift of Perseverance",
        "Against Two Letters of the Pelagians",
        "only the first was from the pen of Dr. Holmes",
        "the rest being the work of Dr. Robert Ernest Wallis",
    )
    if any(phrase not in allocation for phrase in allocation_phrases):
        raise ValueError("retained source work-specific translator evidence drift")
    return evidence


def _element_signature(node: etree._Element) -> tuple[object, ...]:
    return (
        node.tag,
        tuple(sorted(node.attrib.items())),
        node.text,
        node.tail,
        tuple(_element_signature(child) for child in node),
    )


def _expected_header_signature(
    policy: Mapping[str, object],
    contributors: list[tuple[str, str]],
) -> tuple[object, ...]:
    header = policy.get("tei_header")
    if not isinstance(header, Mapping):
        raise ValueError("validation policy lacks exact TEI header authority")

    def q(local: str) -> str:
        return f"{{{TEI_NS}}}{local}"

    def leaf(
        local: str,
        text: str | None,
        attrs: tuple[tuple[str, str], ...] = (),
    ) -> tuple[object, ...]:
        return (q(local), tuple(sorted(attrs)), text, None, ())

    resp_statements = tuple(
        (
            q("respStmt"),
            (),
            None,
            None,
            (leaf("resp", role), leaf("name", name)),
        )
        for role, name in contributors
    )
    title_stmt = (
        q("titleStmt"),
        (),
        None,
        None,
        (
            leaf("title", str(header["title"])),
            leaf("author", str(header["author"])),
            *resp_statements,
        ),
    )
    publication_stmt = (
        q("publicationStmt"),
        (),
        None,
        None,
        (
            leaf("publisher", str(header["publisher"])),
            (
                q("availability"),
                (("status", str(header["availability_status"])),),
                None,
                None,
                (leaf("p", str(header["rights_statement"])),),
            ),
        ),
    )
    source_desc = (
        q("sourceDesc"),
        (),
        None,
        None,
        (
            (
                q("bibl"),
                (),
                None,
                None,
                (
                    leaf("ptr", None, (("target", str(header["source_url"])),)),
                    leaf("idno", SOURCE_SHA256, (("type", "sha256"),)),
                    leaf(
                        "note", str(header["print_source"]), (("type", "print-source"),)
                    ),
                ),
            ),
        ),
    )
    return (
        q("teiHeader"),
        (),
        None,
        None,
        ((q("fileDesc"), (), None, None, (title_stmt, publication_stmt, source_desc)),),
    )


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value)


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


def _source_features(
    source_tree: etree._ElementTree,
) -> tuple[list[etree._Element], list[etree._Element], list[etree._Comment]]:
    body = source_tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("source body missing")
    divs = [
        child for child in body if isinstance(child.tag, str) and child.tag == "div1"
    ]
    if tuple(node.get("id") for node in divs) != ALL_DIV1:
        raise ValueError("source div1 identity/order drift")
    selected = divs[9:21]
    features = [
        node
        for division in selected
        for node in division.iter()
        if isinstance(node.tag, str)
    ]
    comments = [
        node for division in selected for node in division.xpath(".//comment()")
    ]
    return divs, features, comments


def _expected_accountability_attrs(
    source: etree._Element, ordinal: int
) -> dict[str, str]:
    source_id = source.get("id")
    attrs = {
        "xml:id": "npnf105-"
        + (_safe_id(source_id) if source_id else f"feature-{ordinal:05d}")
    }
    tag = str(source.tag)
    for name, value in source.attrib.items():
        if name == "n":
            attrs["n"] = value
        elif name == "type":
            attrs["type"] = value
        elif name == "class":
            attrs["rend"] = value
        elif name == "place" and tag == "note":
            attrs["place"] = value
        elif name == "href" and tag == "pb":
            attrs["facs"] = value
        elif name == "passage" and tag == "scripRef":
            attrs["cRef"] = value
        elif name == "osisRef" and tag == "scripRef":
            attrs["target"] = value
        elif name == "lang" and tag == "span":
            attrs["xml:lang"] = value
    return attrs


def _expected_attrs(source: etree._Element, ordinal: int) -> dict[str, str]:
    return {
        (
            XML_ID if name == "xml:id" else XML_LANG if name == "xml:lang" else name
        ): value
        for name, value in _expected_accountability_attrs(source, ordinal).items()
    }


def _expected_attribute_dispositions(source: etree._Element) -> list[dict[str, str]]:
    dispositions: list[dict[str, str]] = []
    tag = str(source.tag)
    for name, value in source.attrib.items():
        destination = "source-accountability"
        method = "preserved-exactly"
        if name == "id":
            destination = "@xml:id"
            method = "deterministic-prefix"
        elif name == "n":
            destination = "@n"
        elif name == "type":
            destination = "@type"
        elif name == "class":
            destination = "@rend"
        elif name == "place" and tag == "note":
            destination = "@place"
        elif name == "href" and tag == "pb":
            destination = "@facs"
        elif name == "passage" and tag == "scripRef":
            destination = "@cRef"
        elif name == "osisRef" and tag == "scripRef":
            destination = "@target"
        elif name == "lang" and tag == "span":
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
    return dispositions


def _expected_comment_accounting(
    source_tree: etree._ElementTree,
) -> list[dict[str, object]]:
    assigned_scopes = {scope for scope, _ in ASSIGNED}
    records: list[dict[str, object]] = []
    for ordinal, comment in enumerate(source_tree.xpath("//comment()"), start=1):
        parent = comment.getparent()
        division = parent
        while division is not None and division.tag != "div1":
            division = division.getparent()
        scope = division.get("id") if division is not None else "edition-header"
        assigned = scope in assigned_scopes
        text = comment.text or ""
        tail = comment.tail or ""
        records.append(
            {
                "ordinal": ordinal,
                "scope": scope,
                "assigned": assigned,
                "text": text,
                "sha256": _sha(text.encode("utf-8")),
                "tail_text": tail,
                "tail_sha256": _sha(tail.encode("utf-8")),
                "disposition": "preserved-as-xml-comment"
                if assigned
                else "outside-assigned-work-scope",
            }
        )
    return records


def _closure(root: Path) -> tuple[str, list[dict[str, object]]]:
    paths = (
        "build/tei/npnf105_oracle.py",
        "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/reconstruction/contract.py",
    )
    members = []
    for logical in paths:
        content = (root / logical).read_bytes()
        members.append(
            {"path": logical, "bytes": len(content), "sha256": _sha(content)}
        )
    return _sha(
        _canonical(
            {"contract": "ocd-npnf105-oracle-import-closure-v1", "members": members}
        )
    ), members


def _authority(source_manifest: SourceManifest, role: str) -> Mapping[str, object]:
    authorities = source_manifest.record["authorities"]
    matches = [
        item
        for item in authorities
        if isinstance(item, Mapping) and item.get("role") == role
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one {role} authority")
    return matches[0]


def _expected_source_local_readme(
    *, source_path: str, publication: str, source_identifier: str, editor: str
) -> str:
    return (
        "# Augustine NPNF105 retained-source reconstruction\n\n"
        "This source-family packet binds the twelve LIB-004 works to the complete retained\n"
        f"`div1` scopes x through xxi of `{source_path}`. The single retained\n"
        "member has SHA-256\n"
        f"`{SOURCE_SHA256}`.\n\n"
        "The retained header identifies the underlying text as public domain and the\n"
        f"print source as *{publication}*. The\n"
        f"retained electronic edition is sourced via [CCEL.org](https://www.ccel.org{source_identifier}).\n"
        "CCEL permits parsing its ThML; do not sell CCEL files or derivatives of CCEL's\n"
        "formatting. The reconstruction preserves text and meaningful source structure;\n"
        "it does not claim CCEL formatting as an original work.\n\n"
        f"{editor} is retained as editor. The retained title page credits Peter Holmes\n"
        "and Robert Ernest Wallis as translators, and Benjamin B. Warfield as translation\n"
        "reviser and introduction author. Retained `div1` ix supplies work-specific\n"
        "allocations for four works: *Grace and Free-Will* to Holmes; and *Rebuke and\n"
        "Grace*, *The Predestination of the Saints* with its *Gift of Perseverance* second\n"
        "book, and *Against Two Letters of the Pelagians* to Wallis. The retained contents note at `iii-p74` additionally assigns the asterisk-marked\n"
        "works to Wallis and the other listed treatises to Holmes. The unstarred entries\n"
        "at `iii-p10`, `iii-p15`, `iii-p19`, `iii-p24`, `iii-p28`, `iii-p33`, `iii-p38`\n"
        "and `iii-p46` therefore establish Holmes for the other eight assigned works.\n\n"
        "This later metadata inspection does not regenerate the historical candidate.\n"
        "The current reconstruction profile and converter still implement the narrower\n"
        "`ix-p14` allocation; their eight unresolved candidate metadata entries are a\n"
        "recorded reconstruction limitation, not an unresolved source attribution.\n"
        "The existing LIB-004 reconstruction owner must carry the supported successor\n"
        "metadata into a future candidate and verify it independently. Human textual acceptance and publication\n"
        "authorization remain separate and absent.\n"
    )


def _expected_review_evidence(
    source_manifest: SourceManifest,
    source_tree: etree._ElementTree,
    divisions: list[etree._Element],
) -> tuple[dict[str, object], list[dict[str, object]], str]:
    edition_title = _single_text(
        source_tree,
        "/ThML/ThML.head/electronicEdInfo/DC/DC.Title[not(@sub)]/text()",
        "edition title",
    )
    editor = _single_text(
        source_tree,
        "/ThML/ThML.head/electronicEdInfo/DC/DC.Creator[@sub='Editor'][@scheme='short-form']/text()",
        "editor",
    )
    publication = _single_text(
        source_tree,
        "/ThML/ThML.head/printSourceInfo/published/text()",
        "publication",
    )
    source_identifier = _single_text(
        source_tree,
        "/ThML/ThML.head/electronicEdInfo/DC/DC.Identifier[@scheme='URL']/text()",
        "source identifier",
    )
    retained_rights = _single_text(
        source_tree,
        "/ThML/ThML.head/electronicEdInfo/DC/DC.Rights/text()",
        "rights",
    )
    profile_path = source_manifest.authority_path("reconstruction-profile")
    profile = _strict_object(
        profile_path.read_bytes(), "NPNF105 reconstruction profile"
    )
    credit_evidence = _retained_credit_evidence(source_tree, profile)

    permission = source_manifest.authority_path("ccel-permission-evidence").read_text(
        encoding="utf-8"
    )
    permission_requirements = (
        "Restriction: do not sell CCEL files or derivatives of their formatting.",
        'Attribution convention: include "sourced via CCEL.org" in dataset README/card.',
    )
    if any(requirement not in permission for requirement in permission_requirements):
        raise ValueError("CCEL rights or attribution authority drift")

    policy_path = source_manifest.authority_path("validation-policy")
    policy = _strict_object(policy_path.read_bytes(), "NPNF105 validation policy")
    if (
        policy.get("candidate_status") != "nonaccepted"
        or policy.get("publication_state") != "not_ready"
    ):
        raise ValueError("validation policy closure-state drift")
    header_policy = policy.get("tei_header")
    if not isinstance(header_policy, Mapping):
        raise ValueError("validation policy exact TEI header authority drift")
    if (
        header_policy.get("source_url") != f"https://www.ccel.org{source_identifier}"
        or not str(header_policy.get("print_source", "")).startswith(publication)
        or retained_rights not in str(header_policy.get("rights_statement", ""))
        or "CCEL" not in str(header_policy.get("rights_statement", ""))
    ):
        raise ValueError(
            "validation policy TEI header is not bound to retained metadata"
        )

    source_authority = _authority(source_manifest, "primary-source")
    source_path = str(source_authority["path"])
    expected_source_readme = _expected_source_local_readme(
        source_path=source_path,
        publication=publication,
        source_identifier=source_identifier,
        editor=editor,
    ).encode("utf-8")
    observed_source_readme = source_manifest.authority_path(
        "source-local-attribution-readme"
    ).read_bytes()
    if observed_source_readme != expected_source_readme:
        raise ValueError("source-local attribution README drift")
    selected = divisions[9:21]
    source_scope = f"div1 {ASSIGNED[0][0]} through {ASSIGNED[-1][0]}"
    explicit_allocations = profile.get("retained_explicit_translator_allocations")
    expected_explicit_allocations = {
        "xviii": "Robert Ernest Wallis",
        "xix": "Peter Holmes",
        "xx": "Robert Ernest Wallis",
        "xxi": "Robert Ernest Wallis",
    }
    if explicit_allocations != expected_explicit_allocations:
        raise ValueError("reconstruction profile translator allocations drift")
    xxi = selected[-1]
    xxi_children = [
        (child.get("id"), child.get("title"))
        for child in xxi
        if isinstance(child.tag, str) and child.tag == "div2"
    ]
    if xxi_children != [
        ("xxi.i", "Title Page."),
        ("xxi.ii", "Book I"),
        ("xxi.iii", "A Treatise on the Gift of Perseverance."),
    ]:
        raise ValueError("retained Predestination/Gift of Perseverance structure drift")
    works: list[dict[str, object]] = []
    unresolved_work_ids: list[str] = []
    for ordinal, ((scope, work_id), division) in enumerate(
        zip(ASSIGNED, selected, strict=True),
        start=1,
    ):
        title = division.get("title", "")
        credited_to = expected_explicit_allocations.get(scope)
        scope_titles = [title]
        if scope == "xxi":
            scope_titles.append("A Treatise on the Gift of Perseverance.")
        if credited_to is None:
            unresolved_work_ids.append(work_id)
            allocation: dict[str, object] = {
                "status": "unresolved",
                "credited_to": None,
                "source_xml_id": None,
                "retained_scope_titles": scope_titles,
            }
        else:
            allocation = {
                "status": "retained-explicit",
                "credited_to": credited_to,
                "source_xml_id": "ix-p14",
                "retained_scope_titles": scope_titles,
            }
        works.append(
            {
                "ordinal": ordinal,
                "div1_id": scope,
                "work_id": work_id,
                "title": title,
                "translator_allocation": allocation,
            }
        )
    expected_provenance: dict[str, object] = {
        "contract": "ocd-npnf105-provenance-v1",
        "status": str(policy["candidate_status"]),
        "source_id": source_manifest.record["source_id"],
        "source": {"path": source_path, "sha256": SOURCE_SHA256, "scope": source_scope},
        "works": works,
        "edition": {
            "title": edition_title,
            "editor": editor,
            "publication": publication,
            "source_identifier": source_identifier,
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
            "retained_statement": retained_rights,
            "ccel_formatting_condition": "Do not sell CCEL files or derivatives of their formatting.",
            "publication_state": str(policy["publication_state"]),
        },
        "canonical_data_written": False,
    }
    expected_unresolved = [
        {
            "id": "npnf105-work-specific-translator-allocation",
            "scope": "8-assigned-works",
            "status": "unresolved",
            "work_ids": unresolved_work_ids,
            "question": (
                "Which retained translator credit applies to each of the eight assigned works not "
                "allocated by div1 ix?"
            ),
            "evidence": (
                "Retained div1 ix allocates Grace and Free-Will to Peter Holmes and Rebuke and "
                "Grace, Predestination of the Saints with its Gift of Perseverance second book, "
                "and Against Two Letters of the Pelagians to Robert Ernest Wallis; it does not "
                "safely allocate the remaining eight assigned works."
            ),
        },
        {
            "id": "npnf105-print-collation-not-performed",
            "scope": "edition",
            "status": "unresolved",
            "question": (
                "Does the retained electronic witness differ substantively from the stated 1886 "
                "print edition?"
            ),
            "evidence": (
                "The candidate is bound to the retained CCEL XML; no print collation was performed."
            ),
        },
        {
            "id": "npnf105-human-acceptance-and-publication",
            "scope": "all-12-assigned-works",
            "status": "unresolved",
            "question": (
                "Will a maintainer accept these candidate texts and separately authorize publication?"
            ),
            "evidence": "Technical verification is not human acceptance or publication authorization.",
        },
    ]
    readme = (
        "# NPNF1-05 assigned-work reconstruction source\n\n"
        f"This nonaccepted TEI candidate is reconstructed deterministically from the retained `{source_path}` "
        f"member, exact SHA-256 `{SOURCE_SHA256}`, for `div1` {ASSIGNED[0][0]} through {ASSIGNED[-1][0]}.\n\n"
        f"The retained header identifies the underlying text as public domain and the print source as *{publication}*. "
        f"The retained edition is sourced via [CCEL.org](https://www.ccel.org{source_identifier}). CCEL permits parsing "
        "its ThML; do not sell CCEL files or derivatives of CCEL's formatting. This candidate reconstructs textual and "
        "structural content and does not claim CCEL formatting as an original work.\n\n"
        f"{editor} is retained as editor. The retained title-page credits Peter Holmes and Robert Ernest Wallis as "
        "translators, and Benjamin B. Warfield with revising the translation and prefixing an introduction. Retained "
        "`div1` ix allocates *Grace and Free-Will* to Holmes and allocates *Rebuke and Grace*, *The Predestination of "
        "the Saints* with its *Gift of Perseverance* second book, and *Against Two Letters of the Pelagians* to Wallis. "
        "Translator allocation remains unresolved for the other eight assigned works. Human textual acceptance and "
        "publication remain separate and absent.\n"
    )
    return expected_provenance, expected_unresolved, readme


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> Mapping[str, object]:
    """Re-read retained XML and prove candidate completeness without producer logic."""

    findings: list[str] = []
    source_manifest.verify()
    candidate.verify_integrity()
    source = source_manifest.authority_path("npnf105-retained-xml")
    source_bytes = source.read_bytes()
    if _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("wrong retained source")
    source_tree = _parse(source)
    divs, features, comments = _source_features(source_tree)
    counts: dict[str, int] = {}
    for feature in features:
        counts[str(feature.tag)] = counts.get(str(feature.tag), 0) + 1
    if len(features) != 16648 or counts != EXPECTED_COUNTS:
        raise ValueError("retained assigned-scope inventory drift")
    if (
        len(comments) != 4
        or tuple(comment.text or "" for comment in comments) != EXPECTED_COMMENT_TEXTS
    ):
        raise ValueError("assigned technical XML comment inventory drift")

    manifest = candidate.manifest
    expected_manifest_binding = {
        "path": source_manifest.path.relative_to(
            source_manifest.repository_root
        ).as_posix(),
        "sha256": source_manifest.sha256,
    }
    if (
        manifest.get("source_id") != source_manifest.record["source_id"]
        or dict(manifest.get("source_manifest", {})) != expected_manifest_binding
    ):
        raise ValueError("candidate uses a wrong or stale source manifest")
    if dict(manifest.get("converter", {})) != dict(source_manifest.record["converter"]):
        raise ValueError("candidate converter binding drift")
    if dict(manifest.get("package_schema", {})) != dict(
        source_manifest.record["package_schema"]
    ):
        raise ValueError("candidate package schema binding drift")

    expected_provenance, expected_unresolved, expected_readme = (
        _expected_review_evidence(
            source_manifest,
            source_tree,
            divs,
        )
    )
    provenance = _strict_object(candidate.member_bytes("provenance.json"), "provenance")
    if provenance != expected_provenance:
        raise ValueError("provenance semantic drift")
    unresolved_lines = [
        _strict_object(line.encode("utf-8"), f"unresolved evidence line {ordinal}")
        for ordinal, line in enumerate(
            candidate.member_bytes("unresolved.jsonl").decode("utf-8").splitlines(),
            start=1,
        )
    ]
    if unresolved_lines != expected_unresolved:
        raise ValueError("unresolved evidence drift")
    readme = candidate.member_bytes("README.source.md").decode("utf-8")
    if readme != expected_readme:
        raise ValueError("README attribution drift")

    accountability = _strict_object(
        candidate.member_bytes("source-accountability.json"), "source accountability"
    )
    schema_path = source_manifest.authority_path("source-accountability-schema")
    schema = _strict_object(schema_path.read_bytes(), "source accountability schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"source-accountability schema failure: {errors[0].message}")
    member = accountability.get("source_member")
    if member != {
        "path": "raw/ccel/npnf1/npnf105.xml",
        "bytes": len(source_bytes),
        "sha256": SOURCE_SHA256,
    }:
        raise ValueError("source-member accounting drift")
    exact_accountability_fields = {
        "contract": "ocd-npnf105-source-accountability-v1",
        "schema": "npnf105.source-accountability.schema.json",
        "profile_id": "npnf105-assigned-div1-x-through-xxi-v1",
        "source_scope": "retained ThML.body div1 x through xxi",
        "assigned_work_count": 12,
        "feature_count": 16648,
        "feature_counts": counts,
        "omitted_feature_count": 0,
        "unresolved_feature_count": 0,
    }
    if any(
        accountability.get(key) != value
        for key, value in exact_accountability_fields.items()
    ):
        raise ValueError("feature accounting is incomplete")
    division_accounting = accountability.get("division_accounting")
    if not isinstance(division_accounting, list) or len(division_accounting) != 23:
        raise ValueError("div1 scope accounting is incomplete")
    assigned_map = dict(ASSIGNED)
    for ordinal, (record, division) in enumerate(
        zip(division_accounting, divs, strict=True), start=1
    ):
        expected = {
            "ordinal": ordinal,
            "div1_id": division.get("id"),
            "title": division.get("title", ""),
            "disposition": "assigned-work-represented"
            if division.get("id") in assigned_map
            else "outside-assigned-work-scope",
            "work_id": assigned_map.get(str(division.get("id"))),
        }
        if record != expected:
            raise ValueError("div1 scope accounting drift")
    comment_accounting = accountability.get("comment_accounting")
    if comment_accounting != _expected_comment_accounting(source_tree):
        raise ValueError("comment accounting drift")

    crosswalk = accountability.get("crosswalk")
    if not isinstance(crosswalk, list) or len(crosswalk) != len(features):
        raise ValueError("crosswalk omission or duplication")
    tei_tree = _parse_candidate_tei(candidate.member_bytes("content.tei.xml"))
    _assert_document_topology(tei_tree)
    if tei_tree.getroot().tag != f"{{{TEI_NS}}}TEI":
        raise ValueError("candidate is not TEI")
    ids: dict[str, etree._Element] = {}
    for node in tei_tree.iter():
        if not isinstance(node.tag, str):
            continue
        node_id = node.get(XML_ID)
        if node_id is not None:
            if node_id in ids:
                raise ValueError("duplicate TEI xml:id")
            ids[node_id] = node
    observed_target_ids: list[str] = []
    generated_head_parent_ids: list[str] = []
    feature_ordinals = {
        id(feature): ordinal for ordinal, feature in enumerate(features, start=1)
    }
    for ordinal, (row, source_node) in enumerate(
        zip(crosswalk, features, strict=True), start=1
    ):
        expected_id = "npnf105-" + (
            _safe_id(source_node.get("id"))
            if source_node.get("id")
            else f"feature-{ordinal:05d}"
        )
        expected_row_core = {
            "feature_id": f"npnf105-feature-{ordinal:05d}",
            "source_selector": _selector(source_node),
            "source_tag": source_node.tag,
            "source_xml_id": source_node.get("id"),
            "attributes": dict(source_node.attrib),
            "direct_text": source_node.text or "",
            "tail_text": source_node.tail or "",
            "direct_text_sha256": _sha((source_node.text or "").encode("utf-8")),
            "tail_text_sha256": _sha((source_node.tail or "").encode("utf-8")),
            "tei_tag": TAG_MAP[str(source_node.tag)],
            "tei_xml_id": expected_id,
            "tei_selector": f"#{expected_id}",
            "disposition": "represented",
            "source_title_head": source_node.get("title")
            if str(source_node.tag).startswith("div")
            else None,
        }
        if any(row.get(key) != value for key, value in expected_row_core.items()):
            raise ValueError(
                f"crosswalk source/order binding drift at feature {ordinal}"
            )
        target = ids.get(expected_id)
        if (
            target is None
            or etree.QName(target).localname != TAG_MAP[str(source_node.tag)]
        ):
            raise ValueError(f"missing or wrong TEI target at feature {ordinal}")
        observed_target_ids.append(expected_id)
        if dict(target.attrib) != _expected_attrs(source_node, ordinal):
            raise ValueError(f"TEI attribute invention/drift at feature {ordinal}")
        if (target.text or "") != (source_node.text or "") or (target.tail or "") != (
            source_node.tail or ""
        ):
            raise ValueError(f"TEI direct/tail text drift at feature {ordinal}")
        title = (
            source_node.get("title") if str(source_node.tag).startswith("div") else None
        )
        heads = [
            child
            for child in target
            if isinstance(child.tag, str) and etree.QName(child).localname == "head"
        ]
        if title is None and heads:
            raise ValueError(f"invented division head at feature {ordinal}")
        if title is not None:
            if (
                len(heads) != 1
                or heads[0].text != title
                or heads[0].tail is not None
                or dict(heads[0].attrib)
                or len(heads[0])
            ):
                raise ValueError(
                    f"division title projection drift at feature {ordinal}"
                )
            generated_head_parent_ids.append(expected_id)
        source_parent = source_node.getparent()
        if source_parent is not None and source_parent.tag in TAG_MAP:
            parent_ordinal = feature_ordinals[id(source_parent)]
            expected_parent_id = "npnf105-" + (
                _safe_id(source_parent.get("id"))
                if source_parent.get("id")
                else f"feature-{parent_ordinal:05d}"
            )
            expected_parent_feature_id: str | None = (
                f"npnf105-feature-{parent_ordinal:05d}"
            )
            expected_child_ordinal = (
                1
                + int(
                    str(source_parent.tag).startswith("div")
                    and source_parent.get("title") is not None
                )
                + sum(
                    1
                    for sibling in source_parent[: source_parent.index(source_node)]
                    if isinstance(sibling.tag, str)
                )
            )
        else:
            expected_parent_id = "npnf105-assigned-body"
            expected_parent_feature_id = None
            expected_child_ordinal = next(
                index
                for index, (scope, _) in enumerate(ASSIGNED, start=1)
                if scope == source_node.get("id")
            )
        expected_row = {
            **expected_row_core,
            "tei_parent_id": expected_parent_id,
            "tei_child_ordinal": expected_child_ordinal,
            "tei_attributes": _expected_accountability_attrs(source_node, ordinal),
            "attribute_dispositions": _expected_attribute_dispositions(source_node),
            "assertion": {
                "id": f"npnf105-crosswalk-{ordinal:05d}",
                "profile": "npnf105-assigned-div1-x-through-xxi-v1",
                "role": "retained-source-to-candidate-crosswalk",
                "layer": "reconstruction",
                "status": "asserted",
                "asserted_by": "deterministic-converter",
                "method": "exact-depth-first-source-mapping",
                "evidence": _selector(source_node),
                "subject": f"npnf105-feature-{ordinal:05d}",
                "destination": f"#{expected_id}",
            },
            "parent_feature_id": expected_parent_feature_id,
        }
        if expected_parent_feature_id is None:
            expected_row["work_id"] = assigned_map[str(source_node.get("id"))]
        if row != expected_row:
            raise ValueError(f"crosswalk accountability drift at feature {ordinal}")
        if (
            target.getparent() is None
            or target.getparent().get(XML_ID) != expected_parent_id
            or row.get("tei_parent_id") != expected_parent_id
        ):
            raise ValueError(f"TEI hierarchy drift at feature {ordinal}")
    if len(observed_target_ids) != len(set(observed_target_ids)):
        raise ValueError("duplicate crosswalk target")
    candidate_feature_nodes = [
        node
        for node in tei_tree.xpath(
            "/tei:TEI/tei:text/tei:body//*[@xml:id]",
            namespaces={"tei": TEI_NS, "xml": XML_NS},
        )
    ]
    if [node.get(XML_ID) for node in candidate_feature_nodes] != observed_target_ids:
        raise ValueError(
            "TEI source feature omission, duplication, reorder, or invention"
        )
    body = tei_tree.xpath("/tei:TEI/tei:text/tei:body", namespaces={"tei": TEI_NS})[0]
    expected_body_keys = {
        *(("source", node_id) for node_id in observed_target_ids),
        *(("generated-head", parent_id) for parent_id in generated_head_parent_ids),
    }
    observed_body_keys: list[tuple[str, str]] = []
    generated_head_parent_set = set(generated_head_parent_ids)
    for node in body.iterdescendants():
        if not isinstance(node.tag, str):
            if isinstance(node, etree._Comment):
                continue
            raise ValueError("TEI body contains an unbound non-element node")
        node_id = node.get(XML_ID)
        if node_id is not None:
            observed_body_keys.append(("source", node_id))
            continue
        parent = node.getparent()
        parent_id = parent.get(XML_ID) if parent is not None else None
        if (
            etree.QName(node).localname == "head"
            and parent_id in generated_head_parent_set
        ):
            observed_body_keys.append(("generated-head", str(parent_id)))
            continue
        raise ValueError("TEI body contains an unbound or invented element")
    if (
        len(observed_body_keys) != len(expected_body_keys)
        or set(observed_body_keys) != expected_body_keys
    ):
        raise ValueError("TEI body element census drift")
    tei_comments = tei_tree.xpath(
        "/tei:TEI/tei:text/tei:body//comment()", namespaces={"tei": TEI_NS}
    )
    if [(comment.text or "", comment.tail or "") for comment in tei_comments] != [
        (comment.text or "", comment.tail or "") for comment in comments
    ]:
        raise ValueError("assigned technical comment preservation drift")
    for source_comment, tei_comment in zip(comments, tei_comments, strict=True):
        source_parent = source_comment.getparent()
        if source_parent is None or source_parent.tag not in TAG_MAP:
            raise ValueError("assigned technical comment has an unbound source parent")
        parent_ordinal = feature_ordinals[id(source_parent)]
        expected_parent_id = "npnf105-" + (
            _safe_id(source_parent.get("id"))
            if source_parent.get("id")
            else f"feature-{parent_ordinal:05d}"
        )
        tei_parent = tei_comment.getparent()
        generated_head_offset = int(
            str(source_parent.tag).startswith("div")
            and source_parent.get("title") is not None
        )
        if (
            tei_parent is None
            or tei_parent.get(XML_ID) != expected_parent_id
            or tei_parent.index(tei_comment)
            != source_parent.index(source_comment) + generated_head_offset
        ):
            raise ValueError("assigned technical comment parent/position drift")

    policy = _strict_object(
        source_manifest.authority_path("validation-policy").read_bytes(),
        "NPNF105 validation policy",
    )
    header_policy = policy.get("tei_header")
    if not isinstance(header_policy, Mapping):
        raise ValueError("validation policy exact TEI header authority drift")
    root = tei_tree.getroot()
    children = list(root)
    if (
        root.tag != f"{{{TEI_NS}}}TEI"
        or root.nsmap != {None: TEI_NS}
        or dict(root.attrib) != {XML_ID: str(header_policy["root_xml_id"])}
        or root.text is not None
        or root.tail is not None
        or len(children) != 2
        or children[0].tag != f"{{{TEI_NS}}}teiHeader"
        or children[1].tag != f"{{{TEI_NS}}}text"
    ):
        raise ValueError(
            "TEI root identity, namespace, attributes, or child order drift"
        )
    text_node = children[1]
    text_children = list(text_node)
    if (
        dict(text_node.attrib)
        or text_node.text is not None
        or text_node.tail is not None
        or len(text_children) != 1
        or text_children[0] is not body
        or body.tag != f"{{{TEI_NS}}}body"
        or dict(body.attrib) != {XML_ID: str(header_policy["body_xml_id"])}
        or body.text is not None
        or body.tail is not None
    ):
        raise ValueError("TEI text/body container identity or structure drift")
    expected_contributors = [
        ("editor", "Philip Schaff"),
        ("translator", "Peter Holmes"),
        ("translator", "Robert Ernest Wallis"),
        ("translation reviser and introduction author", "Benjamin B. Warfield"),
    ]
    if _element_signature(children[0]) != _expected_header_signature(
        policy,
        expected_contributors,
    ):
        raise ValueError(
            "TEI header QName, order, attributes, text, tail, or metadata drift"
        )

    xsd_path = source_manifest.authority_path("tei-p5-xsd")
    xsd = etree.XMLSchema(etree.parse(str(xsd_path)))
    if not xsd.validate(tei_tree):
        raise ValueError(f"TEI P5 XSD failure: {xsd.error_log.last_error}")

    closure_sha256, closure_members = _closure(source_manifest.repository_root)
    validator = source_manifest.record["validator"]
    assert isinstance(validator, Mapping)
    implementation_content = Path(__file__).resolve(strict=True).read_bytes()
    result = {
        "status": "pass",
        "oracle_id": _oracle.oracle_id,
        "oracle_version": _oracle.oracle_version,
        "implementation_sha256": _sha(implementation_content),
        "import_closure_sha256": closure_sha256,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": str(
            _authority(source_manifest, "complete-source-feature-profile")["sha256"]
        ),
        "package_schema_sha256": str(
            _authority(source_manifest, "candidate-package-schema")["sha256"]
        ),
        "source_sha256": SOURCE_SHA256,
        "xsd_sha256": str(
            _authority(source_manifest, "tei-validation-schema")["sha256"]
        ),
        "policy_sha256": str(
            _authority(source_manifest, "independent-validation-policy")["sha256"]
        ),
        "result_sha256": "",
        "findings": findings,
    }
    result["result_sha256"] = _sha(
        _canonical(
            {key: value for key, value in result.items() if key != "result_sha256"}
        )
    )
    return result


_oracle.oracle_id = "ocd-npnf105-source-to-tei-oracle"
_oracle.oracle_version = "7"


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def validation_record(report: ValidationReport) -> dict[str, object]:
    return {
        "contract": "ocd-validation-report-v1",
        "status": report.status,
        "candidate_sha256": report.candidate_sha256,
        "source_manifest_sha256": report.source_manifest_sha256,
        "attestation": _jsonable(report.attestation),
        "findings": list(report.findings),
        "report_sha256": report.sha256,
    }


def validate_candidate(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> ValidationReport:
    return validate(source_manifest, candidate, _oracle)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    manifest = SourceManifest.load(args.manifest, repository_root=args.repository_root)
    candidate = CandidatePackage.load(args.candidate)
    report = validate_candidate(manifest, candidate)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(_canonical(validation_record(report)))
    print(
        json.dumps(
            {"status": report.status, "report_sha256": report.sha256}, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
