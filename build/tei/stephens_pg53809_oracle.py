"""Independent complete-body oracle for the real extracted PG53809 HTML."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from lxml import etree, html

from ocd_kernel.lib.storage_topology import resolve_repo_path

from build.tei.stephens_pg53809_native import (
    ARCHIVE, ARCHIVE_SHA256, ROOT, SOURCE, SOURCE_SHA256, SUPPORT,
)


TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
TAGS = {
    "header": ("div", "provider-header"), "footer": ("div", "provider-license"),
    "div": ("div", "html-div"), "blockquote": ("div", "blockquote"),
    "h1": ("div", "source-heading"), "h2": ("div", "source-heading"),
    "h3": ("div", "source-heading"), "table": ("div", "html-table"),
    "tbody": ("table", None), "tr": ("row", None), "td": ("cell", None),
    "ul": ("list", "unordered"), "li": ("item", None),
    "p": ("p", None), "br": ("lb", None), "hr": ("milestone", None),
    "span": ("seg", "html-span"), "small": ("seg", "html-small"),
    "i": ("hi", None), "em": ("hi", None), "strong": ("hi", None),
    "img": ("graphic", None),
}


def check(candidate: bytes, *, source_root: Path = ROOT) -> dict:
    """Compare every selected HTML body element, relation, text, and support."""
    raw = resolve_repo_path(source_root, SOURCE.as_posix()).read_bytes()
    archive_path = resolve_repo_path(source_root, ARCHIVE.as_posix())
    archive = archive_path.read_bytes()
    if sha256(raw).hexdigest() != SOURCE_SHA256 or sha256(archive).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("PG53809 source or ZIP changed")
    expected = [(SOURCE.name, raw)]
    for name, digest in SUPPORT.items():
        real = resolve_repo_path(source_root, (SOURCE.parent / name).as_posix()).read_bytes()
        if sha256(real).hexdigest() != digest:
            raise ValueError(f"PG53809 real image differs: {name}")
        expected.append((name, real))
    with ZipFile(archive_path) as bundle:
        if bundle.namelist() != [name for name, _ in expected] or bundle.testzip() is not None:
            raise ValueError("PG53809 ZIP inventory differs")
        for name, real in expected:
            if bundle.read(name) != real:
                raise ValueError(f"PG53809 ZIP member differs: {name}")

    source_document = html.fromstring(raw)
    bodies = source_document.xpath("//body")
    if len(bodies) != 1 or len(bodies[0]) != 1457:
        raise ValueError("PG53809 complete HTML body envelope differs")
    source_body = bodies[0]
    source_nodes = list(source_body.iter())[1:]
    root = etree.fromstring(candidate)
    body = root.find(".//" + TEI + "body")
    if body is None or len(body) != 1 or body[0].get("type") != "source-html-body":
        raise ValueError("PG53809 TEI body envelope differs")
    carriers = [node for node in body.iter() if (node.get(XML_ID) or "").startswith("src-")]
    if len(source_nodes) != 11904 or len(carriers) != len(source_nodes):
        raise ValueError("PG53809 body element/carrier count differs")
    if len([node for node in body.iter(TEI + "div") if node.get("type") == "source-html-carrier"]) != 1457:
        raise ValueError("PG53809 top-level HTML carrier count differs")
    source_position = {node: position for position, node in enumerate(source_nodes, 1)}
    source_targets = {node.get("id"): f"#src-{position:05d}"
                      for position, node in enumerate(source_nodes, 1) if node.get("id")}
    if len(source_targets) != 2016:
        raise ValueError("PG53809 source target identity inventory differs")
    tag_counts: Counter[str] = Counter()
    for position, (source, carrier) in enumerate(zip(source_nodes, carriers, strict=True), 1):
        tag_counts[source.tag] += 1
        role = TAGS.get(source.tag)
        if role is None or carrier.tag != TEI + role[0] or carrier.get("type") != role[1]:
            # Links have two supported representations: text-bearing references and empty anchors.
            if not (source.tag == "a" and
                    ((source.get("href") is not None and carrier.tag == TEI + "ref" and carrier.get("type") is None) or
                     (source.get("id") is not None and source.get("href") is None and carrier.tag == TEI + "seg" and carrier.get("type") == "anchor"))):
                raise ValueError(f"PG53809 source carrier role differs at {position}: {source.tag}")
        if carrier.get(XML_ID) != f"src-{position:05d}":
            raise ValueError(f"PG53809 source carrier identity/order differs at {position}")
        parent_position = source_position.get(source.getparent(), 0)
        ancestor = carrier.getparent()
        while ancestor is not None and not (ancestor.get(XML_ID) or "").startswith("src-"):
            ancestor = ancestor.getparent()
        actual_parent = int(ancestor.get(XML_ID)[4:]) if ancestor is not None else 0
        if actual_parent != parent_position:
            raise ValueError(f"PG53809 source ancestry differs at {position}")
        if "".join(source.itertext()) != "".join(carrier.itertext()):
            raise ValueError(f"PG53809 source descendant text differs at {position}")
        if set(source.attrib) - {"id", "class", "style", "lang", "href", "src", "alt", "height", "width", "colspan", "data-summary", "title"}:
            raise ValueError(f"PG53809 unaccounted source attribute at {position}")
        if source.get("id") is not None and carrier.get("n") != source.get("id"):
            raise ValueError(f"PG53809 HTML id differs at {position}")
        if source.get("lang") is not None and carrier.get(XML_LANG) != source.get("lang"):
            raise ValueError(f"PG53809 language differs at {position}")
        if source.get("href") is not None:
            literal = source.get("href")
            if literal.startswith("#"):
                expected_target = source_targets.get(unquote(literal[1:]))
                if carrier.get("n") != literal or carrier.get("target") != expected_target:
                    raise ValueError(f"PG53809 local hyperlink/TEI target differs at {position}")
            elif carrier.get("target") != literal or carrier.get("n") is not None:
                raise ValueError(f"PG53809 hyperlink differs at {position}")
        if source.get("src") is not None and carrier.get("url") != source.get("src"):
            raise ValueError(f"PG53809 image target differs at {position}")
        if source.get("colspan") is not None and carrier.get("cols") != source.get("colspan"):
            raise ValueError(f"PG53809 table span differs at {position}")
        rendition = carrier.get("rend") or ""
        if source.get("class") is not None and not all(
            "class:" + token in rendition.split() for token in source.get("class").split()
        ):
            raise ValueError(f"PG53809 source class differs at {position}")
        if source.get("style") is not None and "source-style:" + source.get("style") not in rendition:
            raise ValueError(f"PG53809 source style differs at {position}")
        if source.get("data-summary") is not None and "source-data-summary:" + source.get("data-summary") not in rendition:
            raise ValueError(f"PG53809 table summary differs at {position}")
        if source.tag in {"h1", "h2", "h3"} and (carrier.get("subtype") != f"html-heading-level-{source.tag[1]}" or len(carrier) != 1 or carrier[0].tag != TEI + "head"):
            raise ValueError(f"PG53809 heading level differs at {position}")
        if source.tag in {"i", "em", "strong"} and carrier.get("rend") != ("bold" if source.tag == "strong" else "italic"):
            raise ValueError(f"PG53809 emphasis differs at {position}")
        if source.tag == "hr" and carrier.get("unit") != "source-horizontal-rule":
            raise ValueError(f"PG53809 horizontal rule differs at {position}")
        if source.tag == "td" and carrier.get("ana") != "source-role:data":
            raise ValueError(f"PG53809 table cell role differs at {position}")
        if source.tag == "img" and (source.get("alt") != "" or
                                    carrier.get("ana") != f"source-rend:source-width:{source.get('width')} source-height:{source.get('height')}"):
            raise ValueError(f"PG53809 frontispiece attributes differ at {position}")
        if source.get("title") is not None and source.get("title") != "":
            raise ValueError(f"PG53809 nonempty title attribute lacks a carrier at {position}")
    source_text = "".join(source_body.itertext())
    candidate_text = "".join(body.itertext())
    if source_text != candidate_text:
        raise ValueError("PG53809 complete HTML body text/order differs")
    source_ids = {node.get("id") for node in source_nodes if node.get("id")}
    links = [node.get("href") for node in source_nodes if node.tag == "a" and node.get("href")]
    internal = [target for target in links if target.startswith("#")]
    if any(unquote(target[1:]) not in source_ids for target in internal):
        raise ValueError("PG53809 source fragment link does not resolve")
    carrier_ids = {node.get(XML_ID) for node in body.iter() if node.get(XML_ID)}
    if any(ref.get("target")[1:] not in carrier_ids for ref in body.iter(TEI + "ref")
           if (ref.get("target") or "").startswith("#")):
        raise ValueError("PG53809 TEI local hyperlink does not resolve")
    if (tag_counts["img"], tag_counts["hr"], tag_counts["br"], tag_counts["table"],
            tag_counts["tr"], tag_counts["td"], tag_counts["ul"], tag_counts["li"],
            len(links), len(internal), len(source_ids)) != (1, 32, 84, 1, 49, 74, 244, 1766, 3553, 3548, 2016):
        raise ValueError("PG53809 illustration/structure/link inventory differs")
    if "images/cover.jpg" in [node.get("src") for node in source_nodes] or len(list(body.iter(TEI + "graphic"))) != 1:
        raise ValueError("PG53809 cover role differs")
    return dict(contract="ocd-pg53809-independent-complete-html-oracle-v1",
                source_sha256=SOURCE_SHA256, archive_sha256=ARCHIVE_SHA256,
                body_children=len(source_body), html_elements=len(source_nodes),
                visible_sha256=sha256(source_text.encode("utf-8")).hexdigest(),
                links=len(links), internal_links=len(internal), source_ids=len(source_ids),
                headings=sum(tag_counts[tag] for tag in ("h1", "h2", "h3")),
                horizontal_rules=tag_counts["hr"], line_breaks=tag_counts["br"],
                table_rows=tag_counts["tr"], table_cells=tag_counts["td"],
                referenced_images=1, unreferenced_cover=1)
