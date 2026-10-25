"""Independent complete-body text and illustration oracle for retained PG55819."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import zipfile

from lxml import etree, html

from ocd_kernel.lib.storage_topology import resolve_repo_path
from build.tei.singmaster_pg55819_native import ROOT, SOURCE, ARCHIVE


SOURCE_HASH = "11d6827013ade4b36ed68c3f9f9d4f5d96086405013deb202651361d5a41871a"
ZIP_HASH = "ec7e7196279f4a24c8e584d87dc8e985d47e7136bd49ba3f7245f9b2e4b36f3e"
END_MARKER = "*** END OF THE PROJECT GUTENBERG EBOOK THE STORY OF LUTHERAN MISSIONS ***"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _norm(value: str) -> str:
    return " ".join(value.split())


def _classes(node: etree._Element) -> set[str]:
    return set((node.get("class") or "").split())


def _visible(node: etree._Element, *, without_lists: bool = False) -> str:
    parts: list[str] = []

    def walk(element: etree._Element) -> None:
        if element.text:
            parts.append(element.text)
        for child in element:
            if isinstance(child.tag, str) and child.tag.lower() not in {"img", "br"}:
                if "hidev" not in _classes(child) and not (without_lists and child.tag.lower() in {"ul", "ol"}):
                    walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(node)
    return _norm("".join(parts))


def _source_carriers(node: etree._Element) -> list[str]:
    tag = node.tag.lower()
    classes = _classes(node)
    if tag == "div" and "pbb" in classes:
        return []
    if node.xpath(".//img"):
        captions = node.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), ' ic002 ')]//p")
        return [_visible(captions[0])] if captions and _visible(captions[0]) else []
    if tag in {"h1", "h2", "h3", "h4", "p", "td", "th"} or (tag == "div" and "line" in classes):
        value = _visible(node)
        return [value] if value else []
    if tag == "li":
        value = _visible(node, without_lists=True)
        result = [value] if value else []
        for child in node:
            if isinstance(child.tag, str) and child.tag.lower() in {"ul", "ol"}:
                result.extend(_source_carriers(child))
        return result
    if tag in {"ul", "ol"}:
        return [value for child in node if isinstance(child.tag, str) and child.tag.lower() == "li"
                for value in _source_carriers(child)]
    if tag == "table":
        return [value for cell in node.xpath(".//th|.//td") for value in _source_carriers(cell)]
    if tag == "div" and not node.xpath("./div|./p|./ul|./ol|./table|./blockquote|./h1|./h2|./h3|./h4|./hr"):
        value = _visible(node)
        return [value] if value else []
    if tag in {"div", "blockquote"}:
        children = [child for child in node if isinstance(child.tag, str)]
        if not children:
            value = _visible(node)
            return [value] if value else []
        return [value for child in children for value in _source_carriers(child)]
    return []


def _candidate_carrier(node: etree._Element) -> str:
    fragments: list[str] = []

    def walk(child: etree._Element) -> None:
        if child.text:
            fragments.append(child.text)
        for nested in child:
            if not (node.tag == f"{{{TEI_NS}}}item" and nested.tag == f"{{{TEI_NS}}}list"):
                walk(nested)
            if nested.tail:
                fragments.append(nested.tail)

    walk(node)
    return _norm("".join(fragments))


def check(candidate: bytes, *, source_root: Path = ROOT) -> dict:
    source_file = resolve_repo_path(source_root, SOURCE.as_posix())
    raw = source_file.read_bytes()
    if sha256(raw).hexdigest() != SOURCE_HASH:
        raise ValueError("PG55819 independent HTML authority hash differs")
    body = html.fromstring(raw.decode("utf-8-sig")).xpath("//body")
    if len(body) != 1:
        raise ValueError("PG55819 body count differs")
    direct = [child for child in body[0] if isinstance(child.tag, str)]
    head = [i for i, node in enumerate(direct) if node.get("id") == "pg-header"]
    foot = [i for i, node in enumerate(direct) if node.get("id") == "pg-footer"]
    if len(head) != 1 or len(foot) != 1 or head[0] >= foot[0]:
        raise ValueError("PG55819 Gutenberg wrapper differs")
    selected = direct[head[0] + 1:foot[0]]
    if len(selected) != 774:
        raise ValueError("PG55819 selected HTML body boundary differs")
    for position, node in enumerate(selected, 1):
        if _visible(node) != _norm(" ".join(_source_carriers(node))):
            raise ValueError(f"PG55819 selected direct body child {position} has unaccounted text")
    expected = [value for node in selected for value in _source_carriers(node)]
    tree = etree.fromstring(candidate)
    found = [node for node in tree.iter() if (node.get(XML_ID) or "").startswith("slm-src-B")]
    actual = [_candidate_carrier(node) for node in found]
    if len(expected) != 1010 or len(actual) != len(expected):
        raise ValueError(f"PG55819 text carrier count differs: source={len(expected)} TEI={len(actual)}")
    for position, (source, rendered) in enumerate(zip(expected, actual), 1):
        if found[position - 1].get(XML_ID) != f"slm-src-B{position:04d}" or source != rendered:
            raise ValueError(f"PG55819 first carrier mismatch at {position}: {source!r} != {rendered!r}")
    image_refs = [ref for node in selected for ref in node.xpath(".//img/@src")]
    graphics = tree.xpath("//tei:graphic/@url", namespaces={"tei": TEI_NS})
    if len(image_refs) != 36 or graphics != [f"https://www.gutenberg.org/cache/epub/55819/{ref}" for ref in image_refs]:
        raise ValueError("PG55819 source image order differs")
    archive_path = resolve_repo_path(source_root, ARCHIVE.as_posix())
    if sha256(archive_path.read_bytes()).hexdigest() != ZIP_HASH:
        raise ValueError("PG55819 package hash differs")
    with zipfile.ZipFile(archive_path) as archive:
        if tuple(archive.namelist()) != ("pg55819-images.html", *image_refs):
            raise ValueError("PG55819 package members differ from source image order")
        if archive.read("pg55819-images.html") != raw:
            raise ValueError("PG55819 package HTML member differs")
        for name in image_refs:
            if resolve_repo_path(source_root, (SOURCE.parent / name).as_posix()).read_bytes() != archive.read(name):
                raise ValueError(f"PG55819 extracted image differs: {name}")
    footer = _norm(" ".join(direct[foot[0]].itertext()))
    if END_MARKER not in footer or END_MARKER not in _norm("".join(tree.itertext())):
        raise ValueError("PG55819 end marker differs")
    ns = {"tei": TEI_NS}
    source_chapters = [_visible(node.xpath("./h2")[0]) for node in selected
                       if "chapter" in _classes(node) and node.xpath("./h2")
                       and (node.xpath("./h2")[0].get("id") or "").startswith("ch")]
    tei_chapters = [_norm("".join(node.xpath("./tei:head", namespaces=ns)[0].itertext()))
                    for node in tree.xpath("//tei:body/tei:div[@type='chapter']", namespaces=ns)]
    if len(source_chapters) != 6 or tei_chapters != source_chapters:
        raise ValueError("PG55819 source chapter titles or boundaries differ")
    pages = tree.xpath("//tei:pb", namespaces=ns)
    if (len(pages) != 21 or [page.get("n") for page in pages] != [str(i) for i in range(1, 22)]
            or any(page.get("rend") != "source-electronic-break" for page in pages)):
        raise ValueError("PG55819 page-marker sequence differs")
    notes = tree.xpath("//tei:note[@place='foot']", namespaces=ns)
    if [note.get(XML_ID) for note in notes] != [f"slm-f{i}" for i in range(1, 12)]:
        raise ValueError("PG55819 page/note marker counts differ")
    if len(tree.xpath("//tei:table", namespaces=ns)) != 2:
        raise ValueError("PG55819 source table count differs")
    return dict(contract="ocd-pg55819-independent-html-oracle-v1", source_sha256=SOURCE_HASH,
                selected_direct_children=len(selected), excluded_header_children=head[0] + 1,
                excluded_footer_children=len(direct) - foot[0], carriers=len(expected),
                carrier_sha256=sha256("\n".join(expected).encode()).hexdigest(),
                image_occurrences=len(image_refs), unique_extracted_images=len(set(image_refs)),
                page_breaks=21, notes=11, tables=2, chapters=source_chapters,
                end_marker=END_MARKER)
