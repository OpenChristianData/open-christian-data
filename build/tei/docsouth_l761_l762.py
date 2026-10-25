"""Source-bound TEI.2 to P5 conversion for six retained DocSouth electronic editions."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
T = "{" + TEI + "}"
X = "{" + XML + "}"
CONVERTER_ID = "ocd-docsouth-l761-l762-tei2-to-p5"
CONVERTER_VERSION = "1"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _read(manifest: SourceManifest) -> tuple[dict, dict, etree._Element, dict[str, str]]:
    receipt = json.loads(manifest.authority_path("acquisition-receipt").read_text(encoding="utf-8"))
    profile = json.loads(manifest.authority_path("profile").read_text(encoding="utf-8"))
    raw = manifest.authority_path("official-source-member").read_bytes()
    inventory = manifest.authority_path("member-inventory").read_bytes()
    if (_sha(raw), len(raw)) != (receipt["member"]["sha256"], receipt["member"]["bytes"]):
        raise ValueError("official source differs from acquisition receipt")
    if _sha(inventory) != receipt["verification"]["member_inventory_sha256"]:
        raise ValueError("member inventory differs from receipt")
    if receipt["source_id"] != manifest.record["source_id"] or receipt["member"]["sha256"] != profile["source_sha256"]:
        raise ValueError("source/manifest/profile identity differs")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    root = etree.fromstring(raw, parser=parser)
    if _local(root) != "TEI.2":
        raise ValueError("retained member is not TEI.2")
    entities = {e.name: e.system_url for e in root.getroottree().docinfo.internalDTD.iterentities() if e.system_url and e.system_url.lower().endswith(".jpg")}
    if entities != profile["image_entities"]:
        raise ValueError("unparsed image entity declarations differ")
    return receipt, profile, root, entities


def _migrate(root: etree._Element, stylesheet: bytes, entities: Mapping[str, str], source_url: str) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    transform = etree.XSLT(etree.fromstring(stylesheet, parser=parser))
    output = transform(etree.ElementTree(root)).getroot()
    if output is None or _local(output) != "TEI":
        raise ValueError("migration did not produce TEI")
    source_figures = [n.get("entity") for n in root.iter() if _local(n) == "figure" and n.get("entity")]
    migrated_graphics = list(output.iter(T + "graphic"))
    if len(source_figures) != len(migrated_graphics):
        raise ValueError("source figure to migrated graphic count differs")
    for entity, graphic in zip(source_figures, migrated_graphics):
        if entity not in entities or graphic.get("url") != entities[entity]:
            raise ValueError("source figure entity to stylesheet graphic mapping differs")
        graphic.set("n", entity)
        graphic.set("url", source_url.rsplit("/", 1)[0] + "/" + entities[entity])

    for node in list(output.iter()):
        name = _local(node)
        if re.fullmatch(r"div[1-9]", name):
            level = name[3:]
            old_type = node.attrib.pop("type", None)
            node.tag = T + "div"
            node.set("type", "source-div-" + level)
            if old_type:
                node.set("subtype", "-".join(old_type.split()))
        elif name == "q" and node.xpath('./*[local-name()="text"]'):
            old_type = node.attrib.pop("type", None)
            node.tag = T + "div"
            node.set("type", "source-q")
            if old_type:
                node.set("subtype", "-".join(old_type.split()))
    for node in list(output.iter()):
        parent = node.getparent()
        if parent is None:
            continue
        if _local(node) == "text" and parent.get("type") == "source-q":
            node.tag = T + "div"
            node.set("type", "embedded-text")
        elif _local(node) == "body" and parent.get("type") == "embedded-text":
            node.tag = T + "div"
            node.set("type", "embedded-body")

    for node in list(output.iter()):
        name = _local(node)
        if name == "a":
            node.tag = T + "ref"
            href = node.attrib.pop("href", None)
            if href:
                node.set("target", href)
        elif name == "language" and node.get(X + "id"):
            node.set("ident", node.attrib.pop(X + "id"))
        if node.get("type") and any(c.isspace() for c in node.get("type", "")):
            node.set("type", "-".join(node.get("type", "").split()))
        lang = node.get(X + "lang")
        if lang and re.fullmatch(r"(?:lane|walt|heard|johns?|payne|holsey)\d+[a-z]?", lang):
            node.attrib.pop(X + "lang")
            node.set("ana", "#" + lang)
        if name == "pb" and node.get("rend") is not None and not node.get("rend", "").strip():
            node.attrib.pop("rend")
        target = node.get("target")
        if target and not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
            node.set("target", " ".join("#" + part.lstrip("#") for part in target.split()))
        if name == "figure":
            entity = node.attrib.pop("entity", None)
            if entity:
                if entity not in entities:
                    raise ValueError(f"unmapped figure entity {entity}")
                graphic = etree.Element(T + "graphic", url=source_url.rsplit("/", 1)[0] + "/" + entities[entity])
                graphic.set("n", entity)
                node.insert(0, graphic)

    header = output.find(T + "teiHeader")
    if header is None:
        raise ValueError("source header omitted")
    legacy = {key: header.attrib.pop(key) for key in ("type", "status") if key in header.attrib}
    if legacy:
        encoding = header.find(T + "encodingDesc")
        if encoding is None:
            encoding = etree.SubElement(header, T + "encodingDesc")
        project = encoding.find(T + "projectDesc")
        if project is None:
            project = etree.SubElement(encoding, T + "projectDesc")
        etree.SubElement(project, T + "p").text = "Source TEI.2 teiHeader attributes: " + "; ".join(
            f"{key}={value}" for key, value in sorted(legacy.items())
        )

    for node in list(output.iter()):
        if _local(node) != "pubPlace" or node.getparent() is None or _local(node.getparent()) != "publicationStmt":
            continue
        bfull = next((a for a in node.iterancestors() if _local(a) == "biblFull"), None)
        if bfull is not None:
            desc = bfull.find(T + "sourceDesc")
            if desc is None:
                desc = etree.SubElement(bfull, T + "sourceDesc")
            etree.SubElement(desc, T + "bibl", type="source-publication-place").append(node)

    # Payne has an embedded multi-paragraph quoted document inside one source
    # paragraph. P5 does not permit block divisions inside p; keep the source
    # paragraph as an enclosing div with contiguous p runs around the quote.
    for paragraph in list(output.iter(T + "p")):
        if not any(_local(child) == "div" for child in paragraph):
            continue
        children = list(paragraph)
        opening = paragraph.text
        paragraph.text = None
        for child in children:
            paragraph.remove(child)
        paragraph.tag = T + "div"
        paragraph.set("type", "source-paragraph-with-block-quote")
        segment = etree.Element(T + "p")
        segment.text = opening
        for child in children:
            if _local(child) == "div":
                if segment.text or len(segment):
                    paragraph.append(segment)
                tail = child.tail
                child.tail = None
                paragraph.append(child)
                segment = etree.Element(T + "p")
                segment.text = tail
            else:
                segment.append(child)
        if segment.text or len(segment):
            paragraph.append(segment)

    for parent in list(output.iter()):
        if _local(parent) != "div":
            continue
        children = [child for child in list(parent) if isinstance(child.tag, str)]
        if not any(_local(child) == "div" for child in children):
            continue
        runs = []
        run = []
        for child in children:
            if _local(child) == "div":
                if run:
                    runs.append(run)
                    run = []
            else:
                run.append(child)
        if run:
            runs.append(run)
        for number, members in enumerate(runs, 1):
            wrapper = etree.Element(T + "div", type="source-content-sequence", n=str(number))
            parent.insert(parent.index(members[0]), wrapper)
            for child in members:
                wrapper.append(child)
    return output



def _holsey_corpus(volume: etree._Element) -> etree._Element:
    """Partition 29 titled body works while retaining shared volume matter once."""
    text = volume.find(T + "text")
    header = volume.find(T + "teiHeader")
    if text is None or header is None:
        raise ValueError("Holsey volume header or text is missing")
    source_front = text.find(T + "front")
    source_body = text.find(T + "body")
    if source_front is None or source_body is None:
        raise ValueError("Holsey volume front/body is missing")
    divisions = [n for n in source_body if _local(n) == "div" and n.get("type") == "source-div-1"]
    if len(divisions) != 3:
        raise ValueError("Holsey autobiography/sermons/essays body boundary differs")
    groups = []
    for group in divisions[1:]:
        children = [n for n in group.iterchildren() if _local(n) == "div" and n.get("type") == "source-div-2"]
        if not children:
            children = group.xpath('./tei:div/tei:div[@type="source-div-2"]', namespaces={"tei": TEI})
        groups.append(children)
    if [len(group) for group in groups] != [15, 13]:
        raise ValueError("Holsey source must contain 15 sermons and 13 later titled works")

    corpus = etree.Element(T + "teiCorpus", nsmap={None: TEI})
    corpus.append(header)
    corpus.set(X + "id", "holsey-1898-docsouth-collection")

    def add_unit(identity: str, title: str, *, front: etree._Element | None = None,
                 members: list[etree._Element] | None = None) -> None:
        child = etree.SubElement(corpus, T + "TEI")
        child.set(X + "id", identity)
        child_header = etree.SubElement(child, T + "teiHeader")
        file_desc = etree.SubElement(child_header, T + "fileDesc")
        title_stmt = etree.SubElement(file_desc, T + "titleStmt")
        etree.SubElement(title_stmt, T + "title").text = title
        publication = etree.SubElement(file_desc, T + "publicationStmt")
        etree.SubElement(publication, T + "p").text = "Nonaccepted source-bound reconstruction of the retained DocSouth electronic edition."
        source_desc = etree.SubElement(file_desc, T + "sourceDesc")
        bibl = etree.SubElement(source_desc, T + "bibl")
        etree.SubElement(bibl, T + "title").text = "Autobiography, Sermons, Addresses, and Essays of Bishop L. H. Holsey (1898), DocSouth electronic edition"
        child_text = etree.SubElement(child, T + "text")
        if front is not None:
            child_text.append(copy.deepcopy(front))
        body = etree.SubElement(child_text, T + "body")
        if not members:
            etree.SubElement(body, T + "ab", type="source-front-only")
        for member in members or []:
            body.append(copy.deepcopy(member))

    add_unit("holsey-volume-front", "Shared volume front matter", front=source_front)
    add_unit("holsey-autobiography", "Autobiography of Bishop L. H. Holsey", members=[divisions[0]])

    sermons_group = divisions[1]
    group_shell = copy.deepcopy(sermons_group)
    for sub in list(group_shell.iter(T + "div")):
        if sub.get("type") == "source-div-2" and sub.getparent() is not None:
            sub.getparent().remove(sub)
    add_unit("holsey-sermons-group", "Sermons group heading and opening page", members=[group_shell])
    for number, unit in enumerate(groups[0], 1):
        heading = next((h for h in unit.iter(T + "head")), None)
        if heading is None:
            raise ValueError("Holsey sermon lacks source heading")
        add_unit(f"holsey-sermon-{number:02d}", " ".join(heading.itertext()).strip(), members=[unit])

    essays_group = divisions[2]
    later_shell = copy.deepcopy(essays_group)
    for sub in list(later_shell.iter(T + "div")):
        if sub.get("type") == "source-div-2" and sub.getparent() is not None:
            sub.getparent().remove(sub)
    add_unit("holsey-later-group", "Later works group opening page", members=[later_shell])
    for number, unit in enumerate(groups[1], 1):
        heading = next((h for h in unit.iter(T + "head")), None)
        if heading is None:
            raise ValueError("Holsey later work lacks source heading")
        add_unit(f"holsey-later-work-{number:02d}", " ".join(heading.itertext()).strip(), members=[unit])
    return corpus


def _heard_corpus(volume: etree._Element) -> etree._Element:
    """Separate Tyler's explicitly authored poem from Heard's autobiography."""
    text = volume.find(T + "text")
    header = volume.find(T + "teiHeader")
    if text is None or header is None:
        raise ValueError("Heard source header or text missing")
    front = text.find(T + "front")
    body = text.find(T + "body")
    if front is None or body is None:
        raise ValueError("Heard source front/body missing")
    chapters = [child for child in body if _local(child) == "div" and child.get("type") == "source-div-1"]
    if len(chapters) != 10:
        raise ValueError("Heard source ten-chapter boundary differs")
    poem = chapters[-1]
    poem_title = " ".join(" ".join("".join(h.itertext()).split()) for h in poem.findall(T + "head"))
    author = poem.find(T + "docAuthor")
    if "An Original Poem" not in poem_title or author is None or "EPHRAIM D. TYLER" not in "".join(author.itertext()):
        raise ValueError("Heard Chapter Ten is not the identified Tyler poem")

    corpus = etree.Element(T + "teiCorpus", nsmap={None: TEI})
    corpus.set(X + "id", "heard-1928-docsouth-collection")
    corpus.append(header)
    for identity, title, units, include_front, creator in (
        ("heard-autobiography", "From Slavery to the Bishopric in the A.M.E. Church: An Autobiography", chapters[:-1], True, "William H. Heard"),
        ("heard-tyler-poem", "The Life of William H. Heard: An Original Poem", [poem], False, "Ephraim D. Tyler"),
    ):
        child = etree.SubElement(corpus, T + "TEI")
        child.set(X + "id", identity)
        child_header = etree.SubElement(child, T + "teiHeader")
        desc = etree.SubElement(child_header, T + "fileDesc")
        title_stmt = etree.SubElement(desc, T + "titleStmt")
        etree.SubElement(title_stmt, T + "title").text = title
        etree.SubElement(title_stmt, T + "author").text = creator
        pub = etree.SubElement(desc, T + "publicationStmt")
        etree.SubElement(pub, T + "p").text = "Nonaccepted source-bound reconstruction of the retained DocSouth electronic edition."
        source_desc = etree.SubElement(desc, T + "sourceDesc")
        bibl = etree.SubElement(source_desc, T + "bibl")
        etree.SubElement(bibl, T + "title").text = "From Slavery to the Bishopric in the A.M.E. Church (1928), DocSouth electronic edition"
        child_text = etree.SubElement(child, T + "text")
        if include_front:
            child_text.append(copy.deepcopy(front))
        child_body = etree.SubElement(child_text, T + "body")
        for unit in units:
            child_body.append(copy.deepcopy(unit))
    return corpus

def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    receipt, profile, source, entities = _read(manifest)
    stylesheet = manifest.authority_path("p4-to-p5-stylesheet").read_bytes()
    output = _migrate(source, stylesheet, entities, receipt["source_url"])
    if receipt["source_id"] == "docsouth-holsey":
        output = _holsey_corpus(output)
    elif receipt["source_id"] == "docsouth-heard":
        output = _heard_corpus(output)
    tei_bytes = etree.tostring(output, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    policy = json.loads(manifest.authority_path("policy").read_text(encoding="utf-8"))
    account = {
        "contract": "ocd-docsouth-l761-l762-source-accountability-v1",
        "source_id": receipt["source_id"],
        "work_id": manifest.record["work_id"],
        "edition_id": profile["edition_id"],
        "source_sha256": receipt["member"]["sha256"],
        "member_inventory_sha256": receipt["verification"]["member_inventory_sha256"],
        "stylesheet_sha256": _sha(stylesheet),
        "source_features": profile["source_features"],
        "constituent_units": profile["constituent_units"],
        "tei_sha256": _sha(tei_bytes),
        "tei_bytes": len(tei_bytes),
    }
    return {
        "README.source.md": manifest.authority_path("readme").read_bytes(),
        "content.tei.xml": tei_bytes,
        "provenance.json": _json(policy["provenance"]),
        "source-accountability.json": _json(account),
        "unresolved.jsonl": b"".join(_json(item) for item in policy["unresolved"]),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()