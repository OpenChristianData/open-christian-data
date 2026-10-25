"""Independent source/candidate accounting for American Missionary volume 36.

The checker has its own retained-HTML walk and TEI census.  It deliberately
does not import the Volume 36 producer or any producer traversal helpers.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from lxml import etree, html

from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-american-missionary-volume-36-independent-source-accounting"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"

_CONFIG_IDENTITY = "provisional net-new serial-volume candidate; no canonical WorkCatalog write"
_CONFIG_TITLE = "The American Missionary, Volume 36"
_CONFIG_BODY = "American Missionary Association"
_CONFIG_YEAR = 1882
_SERIES_URL = "https://www.gutenberg.org/ebooks/bookshelf/262"
_RIGHTS = "Project Gutenberg states these issues are public domain in the USA; rights outside the USA and Project Gutenberg trademark or redistribution terms require separate review before publication."
_HEADER_RIGHTS = "Project Gutenberg states these issues are public domain in the USA. Rights elsewhere and Project Gutenberg redistribution conditions require separate review. This candidate is not publication clearance."
_PRINT_SOURCE = "The American Missionary, volume 36, numbers 1–12, January–December 1882."
_ISSUES = (
    (1, "January", 57445, "76f775aa529175bd9bfd333bd44d766518397ee3f6edc64f69a2389ec539ed31", "700fc7a89656d43a2d6352937d1b8b6f4a06476b1bf2da62a680ce7a7ae90367", "051a85270386e8db0b6e51f87b9b5e93f0b7267a2d56f8840bada1449a5f97d4"),
    (2, "February", 57446, "1612e66970d4b512531e8c625c99dd22cdc894f1113659f0c363965717a27193", "bd61c5eec77ddc0b3471338d55801cd84053d236b989f910c4b8a87b334731ac", "a4e4650e8d66703b34fcaebdae0258d059c12f9bd41590fa7be7717bd53596e1"),
    (3, "March", 57510, "ebb03be0c7de45a2b44f7d223167fe610a8e29006b517ea04c4bb11bc7455686", "1701bd93a88407a8e301e384a16b406e780f99276bf77ac951e3e56c49b9f9d3", "f6e33a372ef3dad4081832fee6acb38fd8b6aa214612b9449c8f66f36000fc03"),
    (4, "April", 57591, "331a1d6fa6169e83a73ec84977b94a88c4cadc759536060dee8aafaeb2bf5de9", "d2e7b48a5ca8ac19ee8bbab3222b9846daca2f8357bc1df713883bba53b836f8", "2727f42a7a06e951eb7add6c59b672a2a18ac442b98c34d27005abf32e8614aa"),
    (5, "May", 57859, "332b9165cc05490fdc803e09dbe872da9517ccc80981fdb01c60aea7e93c552a", "7ac8f97db602862e1ecfa5dbc6edf410f3bca3b6d2b175e3f328ad7f14ed8f92", "40797cdb71fbca5c8436aebef597fe1b04185c3571576ac192d51cccf11d8576"),
    (6, "June", 57974, "075c16855d55c5383bc3baaaee165c27d9039e11a857da2f4af9157a97d96721", "4fe557f31a713e05aca519c975bfbe4af237b86268459a599c7df8423a5ed6d6", "e1734e897c9d75a0ec781028ba15e4d45115574db6fd7c05d331d238da527693"),
    (7, "July", 58038, "d3b224a17cb4f6a49ba194b83e3f3798cb23a28c5138fe58e56f1f33e09283ce", "309234d4bd22c10276a63aa7d78ff719f1d25b3b09be507b4b0ffbc7f8ca6288", "9f6667640e277af1cc63332b36419c8909e8ae3d5629105450476b9226440065"),
    (8, "August", 58050, "182d21673e019b615e72a592ea69d172447b35fc8743bd2955d00a8736003cc4", "c25c43f9df81c0497071f09eed1995b666c9f8c928b67a734605020196209c0a", "eaee25f4698e5399fd0e803ffc678f5561f7744cf3799a5b8a04901f0a9f5370"),
    (9, "September", 58051, "568d6fa003295f841328dcf59c5b44e88a5c5e8da36cda4595868931415f374d", "1ae6bdd6bb8a98a7c81eee30894998d4f9d51028c75b2076b18b35fa5d57a01e", "79a4d2b9c5dca586d8cc934e62110c8182986de7410e46eaf9be3a77ddddcde9"),
    (10, "October", 58126, "07811148fad1e23954f8200f2f0113881ee528e04ca813cbea60c3555404d3c0", "bd08a358219a3fc24a68bfad2d756c8a47f6abdd1b973e823fa1e72d9cd7e6f0", "a36e08b770d923c1f260796bcad72793f124cb878ce4433af0061120b44b8883"),
    (11, "November", 58127, "070bfefe6c8b38dc2443a9f7e1b8eda60905e92a1da191c662449c447db3eb05", "66460a5bdf9e1e9d5607bcc1a8d2963d13dff4696930802cfbe021d7146c6429", "a26f5dd22c41829657e205632190e986c4481548aa22555d513f19d78f4debe3"),
    (12, "December", 58128, "098705fd5dc66ea1e4ef0fff1152fe3e61009356d8678640d3f022207f7527dc", "70e10f8f74100dbcfc372f930699e89ed33a214bb07767296248cbd5b63c7daf", "3d927e33e6ff063680943ce026735c323f8978a4eeb51b8f8abfab473da613de"),
)

_HTML_TAGS = {
    "html", "head", "title", "meta", "link", "body", "header", "footer", "script", "style", "pre", "hr", "div", "h1", "h2", "h3", "h4", "h5", "h6", "p", "address", "blockquote", "dl", "dt", "dd", "ol", "ul", "li", "table", "thead", "tbody", "tfoot", "tr", "th", "td", "img", "a", "q", "cite", "b", "strong", "i", "em", "sup", "sub", "span", "small", "br",
}
_HTML_ATTRIBUTES = {"alt", "aria-labelledby", "charset", "class", "colspan", "content", "data-summary", "height", "href", "id", "lang", "name", "property", "rel", "role", "src", "style", "title", "type", "width"}
_TEI_TAGS = {"TEI", "teiHeader", "fileDesc", "titleStmt", "title", "author", "respStmt", "resp", "name", "publicationStmt", "publisher", "availability", "p", "sourceDesc", "bibl", "ptr", "idno", "note", "encodingDesc", "projectDesc", "text", "body", "div", "head", "ab", "anchor", "cell", "row", "table", "item", "list", "figure", "graphic", "figDesc", "pb", "lb", "milestone", "q", "ref", "hi", "seg"}


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _norm(value: str) -> str:
    return " ".join(value.split())


def _stream_digest(values: list[str]) -> str:
    return _sha("\n".join(values).encode("utf-8"))


def _strict_json(path: Path, label: str) -> dict[str, Any]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, value in pairs:
            if key in output:
                raise ValueError(f"{label} has duplicate key {key!r}")
            output[key] = value
        return output

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not readable strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _config_records(config_path: Path) -> list[dict[str, Any]]:
    config = _strict_json(config_path, "Volume 36 source config")
    if (config.get("slug"), config.get("title"), config.get("issuing_body"), config.get("year"), config.get("identity"), config.get("source_series_url"), config.get("rights")) != ("american-missionary-volume-36-1882", _CONFIG_TITLE, _CONFIG_BODY, _CONFIG_YEAR, _CONFIG_IDENTITY, _SERIES_URL, _RIGHTS):
        raise ValueError("Volume 36 source config identity drift")
    configured = config.get("issues")
    if not isinstance(configured, list) or len(configured) != 12:
        raise ValueError("Volume 36 must configure exactly twelve HTML authorities")
    records: list[dict[str, Any]] = []
    for actual, expected in zip(configured, _ISSUES, strict=True):
        if not isinstance(actual, dict):
            raise ValueError("Volume 36 issue authority is not an object")
        number, month, ebook, html_sha, text_sha, archive_sha = expected
        wanted = {"number": number, "month": month, "ebook": ebook, "html_sha256": html_sha, "text_sha256": text_sha, "archive_sha256": archive_sha}
        if actual != wanted:
            raise ValueError(f"Volume 36 configured authority {ebook} identity drift")
        records.append(wanted)
    return records


def _element(node: etree._Element) -> bool:
    return isinstance(node.tag, str)


def _path(node: etree._Element) -> str:
    return node.getroottree().getpath(node)


def _classes(node: etree._Element) -> set[str]:
    return set((node.get("class") or "").split())


def _has_ancestor(node: etree._Element, tags: set[str]) -> bool:
    return any(_element(parent) and parent.tag.lower() in tags for parent in node.iterancestors())


def _hidden(node: etree._Element) -> bool:
    return not _element(node) or bool(_classes(node) & {"pagenum", "hidev"}) or node.tag.lower() in {"script", "style"}


def _visible_text(node: etree._Element, *, omit_nested_lists: bool = False) -> str:
    pieces: list[str] = []

    def visit(current: etree._Element, root: bool = False) -> None:
        if not _element(current) or (not root and _hidden(current)):
            return
        pieces.append(current.text or "")
        for child in current:
            if _element(child) and not (omit_nested_lists and child.tag.lower() in {"ul", "ol"}):
                visit(child)
            pieces.append(child.tail or "")

    visit(node, True)
    return _norm("".join(pieces))


def _direct_text(node: etree._Element) -> str:
    return _norm(" ".join([node.text or "", *(child.tail or "" for child in node)]))


def _source_docs(raw_root: Path, authorities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for authority in authorities:
        ebook = int(authority["ebook"])
        issue_dir = raw_root / f"pg{ebook}"
        paths = ((issue_dir / f"pg{ebook}-images.html", authority["html_sha256"], "HTML"), (issue_dir / f"pg{ebook}.txt", authority["text_sha256"], "plain text"), (issue_dir / f"pg{ebook}-h.zip", authority["archive_sha256"], "archive"))
        for path, expected, kind in paths:
            try:
                actual = _sha(path.read_bytes())
            except OSError as exc:
                raise ValueError(f"Volume 36 retained {kind} authority unreadable: {path}") from exc
            if actual != expected:
                raise ValueError(f"Volume 36 retained {kind} authority hash mismatch: {path}")
        html_path = paths[0][0]
        try:
            document = html.fromstring(html_path.read_bytes())
        except (OSError, etree.XMLSyntaxError, ValueError) as exc:
            raise ValueError(f"Volume 36 retained HTML is not parseable: {html_path}") from exc
        body_nodes = document.xpath("./body")
        end_nodes = document.xpath("//*[@id='pg-end-separator']")
        if len(body_nodes) != 1 or len(end_nodes) != 1:
            raise ValueError(f"Volume 36 retained HTML boundary cardinality drift: {html_path}")
        end_marker = _norm("".join(end_nodes[0].itertext()))
        content = [child for child in body_nodes[0] if _element(child) and child.get("id") not in {"pg-header", "pg-footer"} and child.tag.lower() not in {"header", "footer"}]
        if not content or "END OF THE PROJECT GUTENBERG EBOOK" not in end_marker:
            raise ValueError(f"Volume 36 retained HTML bounds drift: {html_path}")
        docs.append({"number": int(authority["number"]), "month": str(authority["month"]), "ebook": ebook, "path": html_path, "root": document, "body": body_nodes[0], "content": content, "title": _norm(document.xpath("string(//title)")), "end_node": end_nodes[0], "end_marker": end_marker})
    return docs


def _add_carrier(carriers: list[dict[str, Any]], document: Mapping[str, Any], node: etree._Element, source_tag: str, candidate_tag: str, value: str) -> None:
    text = _norm(value)
    if text:
        carriers.append({"issue": document["number"], "ebook": document["ebook"], "source_path": _path(node), "source_tag": source_tag, "candidate_tag": candidate_tag, "text": text, "disposition": "represented"})


def _walk_block(node: etree._Element, document: Mapping[str, Any], carriers: list[dict[str, Any]]) -> None:
    if not _element(node):
        return
    tag = node.tag.lower()
    if _classes(node) & {"pg-boilerplate", "pgheader"} or tag in {"header", "footer", "script", "style"}:
        return
    if tag == "a" and node.get("id") and not node.get("href") and not _visible_text(node):
        return
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        value = _visible_text(node) or _norm(node.get("title") or "")
        _add_carrier(carriers, document, node, tag, "head", value)
    elif tag in {"p", "address"}:
        _add_carrier(carriers, document, node, tag, "p", _visible_text(node))
    elif tag == "pre":
        _add_carrier(carriers, document, node, tag, "ab", _visible_text(node))
    elif tag in {"ul", "ol"}:
        for child in node:
            if _element(child) and child.tag.lower() == "li":
                _add_carrier(carriers, document, child, "li", "item", _visible_text(child, omit_nested_lists=True))
                for nested in child:
                    if _element(nested) and nested.tag.lower() in {"ul", "ol"}:
                        _walk_block(nested, document, carriers)
    elif tag == "table":
        for row in node.xpath("./thead/tr|./tbody/tr|./tfoot/tr|./tr"):
            for cell in row.xpath("./th|./td"):
                _add_carrier(carriers, document, cell, cell.tag.lower(), "cell", _visible_text(cell))
    elif tag in {"img", "hr"}:
        return
    elif tag in {"blockquote", "div"}:
        _add_carrier(carriers, document, node, "direct-text", "ab", _direct_text(node))
        for child in node:
            if _element(child) and child.tag.lower() not in {"script", "style"}:
                _walk_block(child, document, carriers)
    elif tag == "dl":
        for child in node:
            if _element(child) and child.tag.lower() in {"dt", "dd"}:
                _add_carrier(carriers, document, child, child.tag.lower(), "item", _visible_text(child))
    else:
        _add_carrier(carriers, document, node, tag, "ab", _visible_text(node))


def _source_carriers(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    carriers: list[dict[str, Any]] = []
    for document in documents:
        for node in document["content"]:
            _walk_block(node, document, carriers)
        _add_carrier(carriers, document, document["end_node"], "end-marker", "p", document["end_marker"])
    for ordinal, carrier in enumerate(carriers, 1):
        carrier["ordinal"] = ordinal
        carrier["candidate_id"] = f"amv36-src-B{ordinal:05d}"
    return carriers


def _source_scope(node: etree._Element) -> str:
    if not _element(node):
        return "retained-body-content"
    tag = node.tag.lower()
    if tag in {"script", "style"} or _has_ancestor(node, {"script", "style"}):
        return "excluded-electronic-wrapper"
    if tag in {"header", "footer"} or _has_ancestor(node, {"header", "footer"}):
        return "excluded-electronic-wrapper"
    if _classes(node) & {"pg-boilerplate", "pgheader"} or any(_classes(parent) & {"pg-boilerplate", "pgheader"} for parent in node.iterancestors() if _element(parent)):
        return "excluded-electronic-wrapper"
    if tag in {"html", "head", "title", "meta", "link"} or _has_ancestor(node, {"head"}):
        return "retained-source-shell"
    return "retained-body-content"


def _carrier_paths(carriers: list[dict[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(item["source_path"]): item for item in carriers}


def _nearest_carrier(node: etree._Element, paths: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any] | None:
    current: etree._Element | None = node
    while current is not None:
        if (value := paths.get(_path(current))) is not None:
            return value
        current = current.getparent()
    return None


def _inline_context(node: etree._Element) -> bool:
    inline_tags = {"p", "address", "td", "th", "li", "dt", "dd", "a", "q", "cite", "b", "strong", "i", "em", "sup", "sub", "span", "small"}
    for parent in node.iterancestors():
        if not _element(parent):
            continue
        tag = parent.tag.lower()
        if tag == "pre":
            return False
        if tag in inline_tags or (tag.startswith("h") and tag[1:].isdigit()):
            return True
        if tag in {"div", "blockquote", "table", "ul", "ol", "dl", "body"}:
            return False
    return False


def _nearest_table(node: etree._Element) -> etree._Element | None:
    for parent in node.iterancestors():
        if _element(parent) and parent.tag.lower() == "table":
            return parent
    return None


def _source_fragments(documents: list[dict[str, Any]], carriers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter[str]]:
    paths = _carrier_paths(carriers)
    fragments: list[dict[str, Any]] = []
    dispositions: Counter[str] = Counter()
    for document in documents:
        for node in document["root"].iter():
            if not _element(node):
                if node.text and node.text.strip() and _source_scope(node.getparent()) == "retained-body-content":
                    raise ValueError(f"unsupported HTML comment in retained body at {_path(node.getparent())}")
                continue
            scope = _source_scope(node)
            carrier = _nearest_carrier(node, paths)
            if _norm(node.text or ""):
                hidden = _hidden(node) or _has_ancestor(node, {"script", "style"})
                if "pagenum" in _classes(node) and not _inline_context(node):
                    hidden = False
                disposition = "explicitly-disposed-electronic-marker" if hidden else "explicitly-disposed-source-shell" if scope == "retained-source-shell" else "represented-in-source-carrier" if carrier is not None else "explicitly-disposed-structural-wrapper"
                row = {"issue": document["number"], "ebook": document["ebook"], "kind": "element-text", "source_path": _path(node), "text": _norm(node.text or ""), "sha256": _sha(_norm(node.text or "").encode("utf-8")), "disposition": disposition}
                if carrier is not None:
                    row["carrier_id"] = carrier["candidate_id"]
                fragments.append(row)
                dispositions[disposition] += 1
            for child in node:
                tail = _norm(child.tail or "")
                if not tail:
                    continue
                child_scope = _source_scope(child)
                child_carrier = _nearest_carrier(child, paths)
                disposition = "explicitly-disposed-source-shell" if child_scope == "retained-source-shell" else "represented-in-source-carrier" if child_carrier is not None else "explicitly-disposed-electronic-marker" if _hidden(child) else "explicitly-disposed-structural-wrapper"
                row = {"issue": document["number"], "ebook": document["ebook"], "kind": "child-tail", "source_path": _path(child), "text": tail, "sha256": _sha(tail.encode("utf-8")), "disposition": disposition}
                if child_carrier is not None:
                    row["carrier_id"] = child_carrier["candidate_id"]
                fragments.append(row)
                dispositions[disposition] += 1
    return fragments, dispositions


def _source_features(documents: list[dict[str, Any]], carriers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter[str], list[dict[str, Any]]]:
    paths = _carrier_paths(carriers)
    features: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    images: list[dict[str, Any]] = []
    for document in documents:
        for node in document["root"].iter():
            if not _element(node):
                continue
            tag = node.tag.lower()
            if tag not in _HTML_TAGS:
                raise ValueError(f"unsupported retained HTML element {tag!r} at {_path(node)}")
            unknown = set(node.attrib) - _HTML_ATTRIBUTES
            if unknown:
                raise ValueError(f"unsupported retained HTML attribute(s) {sorted(unknown)!r} at {_path(node)}")
            scope = _source_scope(node)
            carrier = _nearest_carrier(node, paths)
            if scope != "retained-body-content":
                disposition = scope
            elif "pagenum" in _classes(node):
                disposition = "represented-as-page-break-when-inline" if _inline_context(node) else "represented-in-source-carrier"
            elif tag == "img":
                inline = _inline_context(node)
                disposition = "represented-as-inline-graphic" if inline else "represented-as-figure-graphic"
                images.append({"issue": document["number"], "ebook": document["ebook"], "source_path": _path(node), "url": f"pg{document['ebook']}/{node.get('src') or ''}", "alt": node.get("alt") or "", "inline": inline})
            elif tag == "hr":
                disposition = "represented-as-separator-milestone"
            elif tag == "br":
                disposition = "represented-as-line-break-when-inline"
            elif tag == "table":
                disposition = "represented-inline-in-cell" if _nearest_table(node) is not None else "represented-as-table"
            elif tag == "tr":
                parent = node.getparent()
                table = _nearest_table(node)
                structural = _element(parent) and parent.tag.lower() in {"table", "thead", "tbody", "tfoot"} and table is not None and _nearest_table(table) is None
                disposition = "represented-as-row" if structural else "represented-inline-in-cell"
            elif tag in {"td", "th"}:
                parent = node.getparent()
                table = _nearest_table(node)
                structural = _element(parent) and parent.tag.lower() == "tr" and table is not None and _nearest_table(table) is None
                disposition = "represented-as-cell" if structural else "represented-inline-in-cell"
            elif carrier is not None:
                disposition = "represented-in-source-carrier"
            else:
                disposition = "represented-as-structure-or-explicit-wrapper"
            features.append({"issue": document["number"], "ebook": document["ebook"], "tag": tag, "source_path": _path(node), "disposition": disposition})
            counts[tag] += 1
    return features, counts, images


def _candidate_text(node: etree._Element) -> str:
    clone = etree.fromstring(etree.tostring(node, encoding="utf-8"))
    for nested in clone.xpath(".//*[@xml:id and starts-with(@xml:id, 'amv36-src-B')]", namespaces={"xml": XML_NS}):
        parent = nested.getparent()
        if parent is not None:
            parent.remove(nested)
    return _norm("".join(clone.itertext()))


def _candidate_carriers(root: etree._Element) -> list[dict[str, Any]]:
    carriers: list[dict[str, Any]] = []
    for node in root.iter():
        if not _element(node):
            continue
        identity = node.get(XML_ID) or ""
        if not identity.startswith("amv36-src-B"):
            continue
        issue = None
        parent = node.getparent()
        while parent is not None:
            if _element(parent) and etree.QName(parent).localname == "div" and parent.get("type") == "issue":
                issue = parent.get("n")
                break
            parent = parent.getparent()
        carriers.append({"node": node, "id": identity, "n": node.get("n"), "tag": etree.QName(node).localname, "text": _candidate_text(node), "issue": issue})
    return carriers


def _inside_carrier(node: etree._Element) -> bool:
    current: etree._Element | None = node
    while current is not None:
        if (current.get(XML_ID) or "").startswith("amv36-src-B"):
            return True
        current = current.getparent()
    return False


def _candidate_header(root: etree._Element, authorities: list[dict[str, Any]]) -> None:
    ns = {"t": TEI_NS}
    if etree.QName(root).namespace != TEI_NS or etree.QName(root).localname != "TEI" or root.get(f"{{{XML_NS}}}lang") != "en":
        raise ValueError("Volume 36 TEI root identity drift")
    if [etree.QName(child).localname for child in root] != ["teiHeader", "text"]:
        raise ValueError("Volume 36 TEI root structure drift")
    title = root.xpath("string(./t:teiHeader/t:fileDesc/t:titleStmt/t:title)", namespaces=ns)
    author = root.xpath("string(./t:teiHeader/t:fileDesc/t:titleStmt/t:author)", namespaces=ns)
    publisher = root.xpath("string(./t:teiHeader/t:fileDesc/t:publicationStmt/t:publisher)", namespaces=ns)
    if (title, author, publisher) != ("The American Missionary, Volume 36 (1882)", _CONFIG_BODY, "Open Christian Data"):
        raise ValueError("Volume 36 TEI header identity drift")
    availability = root.xpath("./t:teiHeader/t:fileDesc/t:publicationStmt/t:availability", namespaces=ns)
    if len(availability) != 1 or availability[0].get("status") != "restricted" or _norm("".join(availability[0].itertext())) != _HEADER_RIGHTS:
        raise ValueError("Volume 36 TEI rights boundary drift")
    pointers = root.xpath("./t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:ptr", namespaces=ns)
    combined = _sha("\n".join(str(item["html_sha256"]) for item in authorities).encode("ascii"))
    if len(pointers) != 1 or pointers[0].get("target") != _SERIES_URL or root.xpath("string(./t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:idno[@type='sha256'])", namespaces=ns) != combined:
        raise ValueError("Volume 36 TEI source identity drift")
    if root.xpath("string(./t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:note[@type='print-source'])", namespaces=ns) != _PRINT_SOURCE:
        raise ValueError("Volume 36 TEI print-source identity drift")


def _candidate_structure(root: etree._Element, documents: list[dict[str, Any]], source_carriers: list[dict[str, Any]], source_features: list[dict[str, Any]], source_images: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter[str]]:
    ns = {"t": TEI_NS}
    if any(not _element(node) or etree.QName(node).namespace != TEI_NS or etree.QName(node).localname not in _TEI_TAGS for node in root.iter()):
        raise ValueError("Volume 36 TEI contains an unsupported element or namespace")
    if any(not _element(node) for node in root.iter()):
        raise ValueError("Volume 36 TEI contains an unsupported comment or processing instruction")
    ids = [node.get(XML_ID) for node in root.iter() if _element(node) and node.get(XML_ID)]
    if len(ids) != len(set(ids)):
        raise ValueError("Volume 36 TEI duplicate xml:id")
    issues = root.xpath("./t:text/t:body/t:div[@type='issue']", namespaces=ns)
    expected_issues = [(str(doc["number"]), f"amv36-issue-{doc['number']:02d}") for doc in documents]
    if len(issues) != 12 or [(item.get("n"), item.get(XML_ID)) for item in issues] != expected_issues:
        raise ValueError("Volume 36 TEI issue omission, order, or identity drift")
    for document, issue in zip(documents, issues, strict=True):
        expected_head = f"Number {document['number']}: {document['month']} 1882 (Project Gutenberg {document['ebook']})"
        heads = issue.xpath("./t:head", namespaces=ns)
        markers = issue.xpath("./t:div[@type='source-wrapper'][@rend='project-gutenberg-end']/t:p", namespaces=ns)
        if len(heads) != 1 or heads[0].text != expected_head or len(markers) != 1 or markers[0].text != document["end_marker"]:
            raise ValueError("Volume 36 TEI issue heading or end-marker drift")
    candidates = _candidate_carriers(root)
    if len(candidates) != len(source_carriers):
        raise ValueError(f"Volume 36 TEI carrier omission or duplication: {len(candidates)} != {len(source_carriers)}")
    expected_tags = Counter(str(item["candidate_tag"]) for item in source_carriers)
    observed_tags = Counter(str(item["tag"]) for item in candidates)
    if observed_tags != expected_tags:
        raise ValueError(f"Volume 36 TEI carrier kind census drift: {observed_tags} != {expected_tags}")
    expected_stream = [(str(item["issue"]), str(item["candidate_tag"]), str(item["text"])) for item in source_carriers]
    observed_stream = [(str(item["issue"]), str(item["tag"]), str(item["text"])) for item in candidates]
    if observed_stream != expected_stream:
        for ordinal, (expected, actual) in enumerate(zip(expected_stream, observed_stream), 1):
            if expected != actual:
                raise ValueError(f"Volume 36 TEI carrier stream drift at ordinal {ordinal}")
        raise ValueError("Volume 36 TEI carrier stream length drift")
    for ordinal, expected in enumerate(source_carriers, 1):
        actual = candidates[ordinal - 1]
        if actual["id"] != f"amv36-src-B{ordinal:05d}" or actual["n"] != str(ordinal) or actual["issue"] != str(expected["issue"]):
            raise ValueError(f"Volume 36 TEI carrier identity, order, or attachment drift at ordinal {ordinal}")
    source_tags = Counter(str(item["tag"]) for item in source_features)
    structural = {
        "table": sum(1 for item in source_features if item["tag"] == "table" and item["disposition"] == "represented-as-table"),
        "row": sum(1 for item in source_features if item["tag"] == "tr" and item["disposition"] == "represented-as-row"),
        "cell": sum(1 for item in source_features if item["tag"] in {"td", "th"} and item["disposition"] == "represented-as-cell"),
        "milestone": source_tags["hr"],
        "pb": sum(1 for item in source_features if item["disposition"] == "represented-as-page-break-when-inline"),
        "figure": sum(1 for item in source_images if not item["inline"]),
        "list-item": sum(1 for item in source_carriers if item["candidate_tag"] == "item"),
        "head-carrier": sum(1 for item in source_carriers if item["candidate_tag"] == "head"),
        "ab-carrier": sum(1 for item in source_carriers if item["candidate_tag"] == "ab"),
    }
    actual_structural = {"table": len(root.xpath("//t:table", namespaces=ns)), "row": len(root.xpath("//t:table/t:row", namespaces=ns)), "cell": len(root.xpath("//t:table/t:row/t:cell", namespaces=ns)), "milestone": len(root.xpath("//t:milestone[@unit='separator']", namespaces=ns)), "pb": len(root.xpath("//t:pb", namespaces=ns)), "figure": len(root.xpath("//t:figure", namespaces=ns)), "list-item": len(root.xpath("//t:list/t:item", namespaces=ns)), "head-carrier": len(root.xpath("//t:head[@type]", namespaces=ns)), "ab-carrier": sum(1 for item in candidates if item["tag"] == "ab")}
    if actual_structural != structural:
        raise ValueError(f"Volume 36 TEI structural feature census drift: {actual_structural} != {structural}")
    tag_counts = Counter(etree.QName(node).localname for node in root.iter() if _element(node))
    expected_inline = {"anchor": 59, "q": source_tags["cite"], "ref": 277, "hi": 3912, "lb": 179, "seg": 15, "figDesc": sum(1 for item in source_images if item["alt"] and not item["inline"])}
    if {tag: tag_counts.get(tag, 0) for tag in expected_inline} != expected_inline:
        raise ValueError("Volume 36 TEI inline feature census drift")
    body = root.xpath("./t:text/t:body", namespaces=ns)[0]
    for node in body.iter():
        if not _element(node) or _inside_carrier(node) or node.tag.endswith("figDesc") or not _norm(node.text or ""):
            continue
        if etree.QName(node).localname == "head" and node.getparent() is not None and node.getparent().get("type") == "issue":
            continue
        raise ValueError(f"Volume 36 TEI body text is outside an accounted carrier at {etree.QName(node).localname}")
    for node in body.iter():
        if not _element(node) or _inside_carrier(node):
            continue
        for child in node:
            if _element(child) and not _inside_carrier(child) and etree.QName(child).localname != "figDesc" and _norm(child.tail or ""):
                raise ValueError(f"Volume 36 TEI body tail is outside an accounted carrier at {etree.QName(child).localname}")
    return candidates, tag_counts


def check_candidate(config_path: Path, raw_root: Path, candidate_path: Path) -> dict[str, Any]:
    """Read retained source and candidate and return independent pass evidence."""

    authorities = _config_records(config_path)
    documents = _source_docs(raw_root, authorities)
    source_carriers = _source_carriers(documents)
    fragments, fragment_dispositions = _source_fragments(documents, source_carriers)
    features, source_tag_counts, images = _source_features(documents, source_carriers)
    try:
        candidate_bytes = candidate_path.read_bytes()
        root = etree.fromstring(candidate_bytes, parser=etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, remove_pis=False, collect_ids=False))
    except (OSError, etree.XMLSyntaxError) as exc:
        raise ValueError("Volume 36 TEI candidate is not readable or well formed") from exc
    schema = compiled_schema()
    if not schema.validate(etree.ElementTree(root)):
        raise ValueError(f"Volume 36 TEI schema failure: {schema.error_log.last_error}")
    _candidate_header(root, authorities)
    candidates, candidate_tag_counts = _candidate_structure(root, documents, source_carriers, features, images)
    source_texts = [str(item["text"]) for item in source_carriers]
    candidate_texts = [str(item["text"]) for item in candidates]
    if _stream_digest(source_texts) != _stream_digest(candidate_texts):
        raise ValueError("Volume 36 carrier stream digest mismatch")
    return {
        "status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION,
        "config_path": config_path.resolve().as_posix(), "raw_root": raw_root.resolve().as_posix(), "candidate_path": candidate_path.resolve().as_posix(), "candidate_sha256": _sha(candidate_bytes),
        "authorities": [{"number": item["number"], "month": item["month"], "ebook": item["ebook"], "html_sha256": item["html_sha256"], "path": f"pg{item['ebook']}/pg{item['ebook']}-images.html"} for item in authorities],
        "source_carrier_count": len(source_carriers), "candidate_carrier_count": len(candidates), "source_carrier_stream_sha256": _stream_digest(source_texts), "candidate_carrier_stream_sha256": _stream_digest(candidate_texts),
        "source_issue_carrier_counts": dict(Counter(str(item["issue"]) for item in source_carriers)), "candidate_issue_carrier_counts": dict(Counter(str(item["issue"]) for item in candidates)),
        "source_fragment_count": len(fragments), "source_fragment_kind_counts": dict(Counter(str(item["kind"]) for item in fragments)), "source_fragment_disposition_counts": dict(fragment_dispositions),
        "source_feature_tag_counts": dict(source_tag_counts), "source_feature_disposition_counts": dict(Counter(str(item["disposition"]) for item in features)), "candidate_tag_counts": dict(candidate_tag_counts),
        "source_carrier_inventory": source_carriers, "source_fragment_inventory": fragments, "candidate_carrier_inventory": [{key: value for key, value in item.items() if key != "node"} for item in candidates], "findings": [],
    }


verify_candidate = check_candidate

__all__ = ["ORACLE_ID", "ORACLE_VERSION", "check_candidate", "verify_candidate"]
