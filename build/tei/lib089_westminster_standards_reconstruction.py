"""Deterministic source-bound TEI candidates for retained LIB-089 HTML witnesses."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree, html

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-lib089-westminster-retained-html-to-tei"
CONVERTER_VERSION = "1"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_BLOCK_SELECTOR = (
    "//div[contains(concat(' ',normalize-space(@class),' '),"
    "' wpb_text_column ') and not(ancestor::div[contains(concat(' ',normalize-space(@class),' '),' toggle ')])]"
    " | //div[contains(concat(' ',normalize-space(@class),' '),' toggle ')"
    " and descendant::div[contains(concat(' ',normalize-space(@class),' '),' wpb_text_column ')]]"
)
_SUPPORTED_TAGS = frozenset(
    {
        "a",
        "b",
        "br",
        "div",
        "em",
        "h1",
        "h2",
        "h3",
        "header",
        "i",
        "li",
        "ol",
        "p",
        "strong",
        "table",
        "tbody",
        "td",
        "tr",
    }
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _normalized_text(node: etree._Element) -> str:
    return " ".join(" ".join(node.itertext()).split())


def _source_attributes(node: etree._Element) -> dict[str, str]:
    return {str(key): str(value) for key, value in sorted(node.attrib.items())}


def _tei_attributes(node: etree._Element) -> dict[str, str]:
    return {
        etree.QName(key).localname: str(value)
        for key, value in sorted(node.attrib.items())
        if key != _XML_ID
    }


def _append_text(parent: etree._Element, value: str | None) -> None:
    if value is None:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + value
    else:
        parent.text = (parent.text or "") + value


class _Projection:
    def __init__(self, slug: str, document: etree._ElementTree) -> None:
        self.slug = slug
        self.document = document
        self.serial = 0
        self.events: list[dict[str, object]] = []

    def bind(
        self,
        source: etree._Element,
        target: etree._Element,
        *,
        disposition: str = "represented",
    ) -> None:
        self.serial += 1
        identifier = f"{self.slug}-source-{self.serial:06d}"
        target.set(_XML_ID, identifier)
        self.events.append(
            {
                "ordinal": self.serial,
                "source_xpath": self.document.getpath(source),
                "source_tag": str(source.tag).lower(),
                "source_attributes": _source_attributes(source),
                "direct_text_sha256": _sha((source.text or "").encode("utf-8")),
                "tail_sha256": _sha((source.tail or "").encode("utf-8")),
                "tei_xml_id": identifier,
                "tei_tag": etree.QName(target).localname,
                "tei_attributes": _tei_attributes(target),
                "disposition": disposition,
            }
        )


def _target_for(source: etree._Element) -> etree._Element:
    tag = str(source.tag).lower()
    if tag in {"div", "header", "table", "tbody", "tr", "td"}:
        return etree.Element(f"{{{_TEI}}}div", type=f"html-{tag}")
    if tag in {"h1", "h2", "h3"}:
        return etree.Element(f"{{{_TEI}}}head", type=f"html-{tag}")
    if tag == "p":
        return etree.Element(f"{{{_TEI}}}p")
    if tag in {"em", "strong", "b"}:
        rend = "italic" if tag == "em" else "bold"
        return etree.Element(f"{{{_TEI}}}hi", rend=rend, ana=f"html-{tag}")
    if tag == "i" and source.get("class") == "icon-plus-sign" and not len(source) and not (source.text or "").strip():
        return etree.Element(f"{{{_TEI}}}seg", type="html-icon", n="icon-plus-sign")
    if tag == "a":
        href = source.get("href")
        if href is not None:
            return etree.Element(f"{{{_TEI}}}ref", target=href, type="html-a")
        target = etree.Element(f"{{{_TEI}}}seg", type="html-a")
        if source.get("name"):
            target.set("n", str(source.get("name")))
        return target
    if tag == "br":
        return etree.Element(f"{{{_TEI}}}lb")
    if tag in {"ol", "ul"}:
        return etree.Element(
            f"{{{_TEI}}}list", type="ordered" if tag == "ol" else "unordered"
        )
    if tag == "li":
        return etree.Element(f"{{{_TEI}}}item")
    raise ValueError(f"unsupported retained source element {tag!r}")


def _project_node(
    parent: etree._Element, source: etree._Element, context: _Projection
) -> None:
    tag = str(source.tag).lower()
    if tag not in _SUPPORTED_TAGS:
        raise ValueError(f"unsupported retained source element {tag!r}")
    target = _target_for(source)
    if tag in {"h1", "h2", "h3"}:
        # HTML permits headings among paragraphs. TEI head must precede body
        # content; a transparent wrapper keeps source sibling order unchanged.
        wrapper = etree.SubElement(parent, f"{{{_TEI}}}div", type="source-heading")
        wrapper.append(target)
    elif parent.tag == f"{{{_TEI}}}div" and tag in {"p", "ol", "ul"}:
        wrapper = etree.SubElement(parent, f"{{{_TEI}}}div", type="source-block-content")
        wrapper.append(target)
    else:
        parent.append(target)
    context.bind(source, target)
    if source.text is not None:
        target.text = source.text
    for child in source:
        if not isinstance(child.tag, str):
            raise ValueError("retained source comments or processing instructions drifted")
        _project_node(target, child, context)
        if child.tail is not None:
            target[-1].tail = child.tail


def _profile_and_blocks(
    source_manifest: SourceManifest,
) -> tuple[dict[str, object], bytes, list[etree._Element], list[dict[str, object]]]:
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    profile = _strict_json(profile_bytes, "LIB-089 reconstruction profile")
    if profile.get("contract") != "ocd-lib089-westminster-html-profile-v1":
        raise ValueError("LIB-089 profile contract drifted")
    if (
        profile.get("ticket_id") != "LIB-089"
        or profile.get("work_id") != source_manifest.record.get("work_id")
    ):
        raise ValueError("LIB-089 profile identity drifted")
    source = source_manifest.authority_path("retained-html").read_bytes()
    document = html.document_fromstring(source)
    blocks = document.xpath(_BLOCK_SELECTOR)
    if not all(isinstance(item, etree._Element) for item in blocks):
        raise ValueError("LIB-089 source block selection is invalid")
    census = profile.get("html_block_census")
    if not isinstance(census, list) or len(census) != len(blocks):
        raise ValueError("LIB-089 complete HTML block census drifted")
    observed: list[dict[str, object]] = []
    for index, (block, expected) in enumerate(zip(blocks, census), 1):
        if not isinstance(expected, dict):
            raise ValueError("LIB-089 block census row is invalid")
        normalized = _normalized_text(block)
        row = {
            "index": index,
            "disposition": expected.get("disposition"),
            "subtree_sha256": _sha(
                etree.tostring(block, encoding="utf-8", with_tail=False)
            ),
            "normalized_text_sha256": _sha(normalized.encode("utf-8")),
            "word_count": len(normalized.split()),
            "element_count": sum(
                1 for node in block.iter() if isinstance(node.tag, str)
            ),
        }
        if row != expected:
            raise ValueError(f"LIB-089 HTML block {index} census drifted")
        observed.append(row)
    return profile, source, list(blocks), observed


def _unresolved(slug: str) -> tuple[dict[str, object], ...]:
    questions = (
        (
            "identity",
            "The retained provider page does not by itself settle the work, expression, or responsible-body identity.",
        ),
        (
            "edition-witness",
            "The relationship between this web transcription, its page-local wrapper material, and a named historical edition remains undecided.",
        ),
        (
            "rights",
            "Underlying historical public-domain status does not settle rights or requested attribution for this retained web transcription.",
        ),
        (
            "editorial",
            "Replacement characters, source spellings, page-local wrapper material, and excluded navigation controls require human editorial review; no wording was modernized.",
        ),
        (
            "acceptance",
            "The candidate has not received human textual acceptance.",
        ),
    )
    return tuple(
        {
            "id": f"{slug}-{kind}",
            "kind": kind,
            "status": "unresolved",
            "detail": detail,
            "owner": "project-maintainer",
        }
        for kind, detail in questions
    )


def _producer_closure(root: Path) -> str:
    paths = (
        "build/__init__.py", "build/tei/__init__.py",
        "build/tei/lib089_westminster_standards_reconstruction.py",
        "ocd_kernel/__init__.py", "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/reconstruction/contract.py",
    )
    return _sha(_canonical([
        {"path": path, "sha256": _sha((root / path).read_bytes())}
        for path in sorted(paths)
    ]))


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    if _producer_closure(source_manifest.repository_root) != source_manifest.record.get("producer_import_closure_sha256"):
        raise ValueError("LIB-089 producer import closure drifted")
    source_manifest.verify()
    profile, source, blocks, observed_blocks = _profile_and_blocks(source_manifest)
    slug = str(profile["work_id"])
    represented = [
        (block, row)
        for block, row in zip(blocks, observed_blocks)
        if str(row["disposition"]).startswith("represented-")
    ]
    if not represented:
        raise ValueError("LIB-089 profile represents no source blocks")

    root = etree.Element(f"{{{_TEI}}}TEI", nsmap={None: _TEI})
    root.set(_XML_ID, f"{slug}-lib089-candidate")
    header = etree.SubElement(root, f"{{{_TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{_TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{_TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{_TEI}}}title").text = str(
        profile["identity"]["title"]  # type: ignore[index]
    )
    publication = etree.SubElement(file_desc, f"{{{_TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{_TEI}}}publisher").text = (
        "Open Christian Data"
    )
    availability = etree.SubElement(
        publication, f"{{{_TEI}}}availability", status="restricted"
    )
    etree.SubElement(availability, f"{{{_TEI}}}p").text = (
        "Nonaccepted candidate; publication is false and not authorized."
    )
    source_desc = etree.SubElement(file_desc, f"{{{_TEI}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{_TEI}}}bibl")
    etree.SubElement(bibl, f"{{{_TEI}}}title").text = str(
        profile["identity"]["source_page_title"]  # type: ignore[index]
    )
    etree.SubElement(
        bibl, f"{{{_TEI}}}ptr", target=str(profile["identity"]["source_url"])  # type: ignore[index]
    )
    etree.SubElement(bibl, f"{{{_TEI}}}idno", type="sha256").text = _sha(source)
    encoding = etree.SubElement(header, f"{{{_TEI}}}encodingDesc")
    etree.SubElement(encoding, f"{{{_TEI}}}p").text = str(
        profile["projection_policy"]["summary"]  # type: ignore[index]
    )
    revision = etree.SubElement(header, f"{{{_TEI}}}revisionDesc", status="candidate")
    etree.SubElement(
        revision, f"{{{_TEI}}}change",
        when=str(profile.get("reconstruction_revision_date", "2026-08-31")),
    ).text = (
        "Generated from the exact retained HTML as a nonaccepted LIB-089 candidate."
    )
    text = etree.SubElement(root, f"{{{_TEI}}}text")
    body = etree.SubElement(text, f"{{{_TEI}}}body")

    # Carrier paths must refer to the tree that supplied the selected blocks.
    # Reparsing identical bytes creates different nodes and invalidates getpath.
    source_document = represented[0][0].getroottree()
    context = _Projection(slug, source_document)
    for block, row in represented:
        target = etree.SubElement(
            body,
            f"{{{_TEI}}}div",
            type="source-block",
            subtype=str(row["disposition"])[len("represented-") :],
            n=str(row["index"]),
        )
        context.bind(block, target)
        if block.text is not None:
            target.text = block.text
        for child in block:
            if not isinstance(child.tag, str):
                raise ValueError(
                    "retained source comments or processing instructions drifted"
                )
            _project_node(target, child, context)
            if child.tail is not None:
                target[-1].tail = child.tail

    if profile.get("local_fragment_policy") == "resolve-retained-targets":
        anchors = {}
        targets = {node.get(_XML_ID): node for node in root.iter() if node.get(_XML_ID)}
        for event in context.events:
            attributes = event["source_attributes"]
            for name in set(filter(None, (attributes.get("id"), attributes.get("name") if event["source_tag"] == "a" else None))):
                if name in anchors:
                    raise ValueError("LIB-089 duplicate retained fragment target")
                anchors[name] = event["tei_xml_id"]
        for event in context.events:
            href = event["source_attributes"].get("href", "")
            if event["source_tag"] == "a" and href.startswith("#") and len(href) > 1:
                if href[1:] not in anchors:
                    raise ValueError("LIB-089 unresolved retained fragment target")
                target = targets[event["tei_xml_id"]]
                target.set("target", "#" + anchors[href[1:]])
                event["tei_attributes"] = _tei_attributes(target)

    represented_text = [_normalized_text(block) for block, _ in represented]
    element_census = Counter(
        str(node.tag).lower()
        for block, _ in represented
        for node in block.iter()
        if isinstance(node.tag, str)
    )
    family_census_path = source_manifest.authority_path("family-member-census")
    blocker_path = source_manifest.authority_path("publick-worship-blocker")
    accountability = {
        "contract": "ocd-lib089-westminster-source-accountability-v1",
        "ticket_id": "LIB-089",
        "work_id": slug,
        "source_id": source_manifest.record["source_id"],
        "source": {
            "path": source_manifest.record["retained_source_path"],
            "bytes": len(source),
            "sha256": _sha(source),
        },
        "family_member_census": {
            "path": family_census_path.relative_to(
                source_manifest.repository_root
            ).as_posix(),
            "sha256": _sha(family_census_path.read_bytes()),
        },
        "publick_worship_blocker": {
            "path": blocker_path.relative_to(
                source_manifest.repository_root
            ).as_posix(),
            "sha256": _sha(blocker_path.read_bytes()),
        },
        "html_block_census": observed_blocks,
        "represented_block_count": len(represented),
        "excluded_block_count": len(blocks) - len(represented),
        "represented_word_count": sum(len(value.split()) for value in represented_text),
        "represented_text_sha256": _sha("\n".join(represented_text).encode("utf-8")),
        "represented_element_census": dict(sorted(element_census.items())),
        "source_events": context.events,
        "omitted_textual_block_count": 0,
        "duplicate_source_event_count": 0,
        "legacy_json_authority": False,
        "projection_limit": profile["projection_limit"],
    }
    authorities = {
        str(item["name"]): {
            key: item[key] for key in ("path", "bytes", "sha256", "role")
        }
        for item in source_manifest.record["authorities"]  # type: ignore[union-attr]
    }
    provenance = {
        "contract": "ocd-lib089-westminster-candidate-provenance-v1",
        "ticket_id": "LIB-089",
        "work_id": slug,
        "source_id": source_manifest.record["source_id"],
        "status": "nonaccepted",
        "publication": False,
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_authority": "exact retained HTML only; existing JSON is excluded",
        "identity": profile["identity"],
        "rights": profile["rights"],
        "authorities": authorities,
        "canonical_data_or_ir_written": False,
    }
    return {
        "content.tei.xml": etree.tostring(
            root, encoding="UTF-8", xml_declaration=True, pretty_print=False
        ),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(row) for row in _unresolved(slug)),
        "README.source.md": source_manifest.authority_path(
            "source-attribution-readme"
        ).read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
