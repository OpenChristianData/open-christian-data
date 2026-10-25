"""HTML5 source nodes without the XML-name coercion of the lxml builder.

This is a structural adapter, not a source selector or TEI mapping. Both
builders share html5lib's HTML5 algorithm. Names are interpreted HTML names
(including HTML case folding), not a claim to recover lexical source spelling.
"""
from __future__ import annotations

import hashlib
import json
import re
from types import SimpleNamespace
from urllib.parse import quote
from xml.dom import Node

import html5lib


class SourceNode:
    def __init__(self, tag, attrib=None, text=None, tail=None):
        self.tag, self.attrib = tag, dict(attrib or {})
        self.text, self.tail = text, tail
        self._children = []
        self._parent = None

    def __iter__(self):
        return iter(self._children)

    def __len__(self):
        return len(self._children)

    def __getitem__(self, index):
        return self._children[index]

    def get(self, key, default=None):
        return self.attrib.get(key, default)

    def getparent(self):
        return self._parent

    def index(self, child):
        return self._children.index(child)

    def insert(self, index, child):
        if child._parent is not None:
            child._parent.remove(child)
        child._parent = self
        self._children.insert(index, child)

    def remove(self, child):
        self._children.remove(child)
        child._parent = None

    def getprevious(self):
        if self._parent is None:
            return None
        index = self._parent.index(self)
        return self._parent[index - 1] if index else None

    def addprevious(self, child):
        if self._parent is None:
            raise ValueError("Root has no sibling insertion point")
        self._parent.insert(self._parent.index(self), child)

    def iter(self, tag=None):
        if tag is None or self.tag == tag:
            yield self
        for child in self:
            yield from child.iter(tag)

    def iterdescendants(self, tag=None):
        for child in self:
            yield from child.iter(tag)

    def iterancestors(self):
        parent = self._parent
        while parent is not None:
            yield parent
            parent = parent._parent

    def itertext(self):
        if isinstance(self.tag, str) and self.text:
            yield self.text
        for child in self:
            yield from child.itertext()
            if child.tail:
                yield child.tail

    def getroottree(self):
        root = self
        while root._parent is not None:
            root = root._parent
        return SourceTree(root)

    def findall(self, tag):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", tag):
            raise ValueError(f"Unsupported source child query: {tag}")
        return [child for child in self if child.tag == tag]

    def find(self, tag):
        return next(iter(self.findall(tag)), None)

    def xpath(self, query):
        # Deliberately finite: unsupported queries must never silently misselect.
        if query in {"/html/head/link[@href]", "//link[@href]"}:
            nodes = self.iter("link") if query.startswith("//") else (
                node for head in self.findall("head") for node in head.findall("link")
            )
            return [node for node in nodes if "href" in node.attrib]
        match = re.fullmatch(r"//\*\[@id='([^']+)'(?: or @id='([^']+)')?\](/h1)?", query)
        if match:
            nodes = [node for node in self.iter() if node.get("id") in {match[1], match[2]} and node.get("id") is not None]
            return [child for node in nodes for child in node.findall("h1")] if match[3] else nodes
        raise ValueError(f"Unsupported source XPath subset: {query}")


class SourceTree:
    def __init__(self, root):
        self.root = root
        self.docinfo = SimpleNamespace(**getattr(root, "_document_metadata", {}))

    def getroot(self):
        return self.root

    def getpath(self, node):
        """Percent-encoded name and same-kind sibling index; not XPath syntax."""
        parts = []
        for current in [node, *node.iterancestors()]:
            name = quote(current.tag, safe="") if isinstance(current.tag, str) else "#comment"
            siblings = current._parent if current._parent is not None else [current]
            peers = [sibling for sibling in siblings if sibling.tag == current.tag]
            parts.append(f"{name}[{peers.index(current) + 1}]")
        if list(node.iterancestors())[-1:] != [self.root] and node is not self.root:
            raise ValueError("Node does not belong to this source tree")
        return "/" + "/".join(reversed(parts))


def _from_etree(node):
    target = SourceNode(node.tag if isinstance(node.tag, str) else None, node.attrib, node.text, node.tail)
    for child in node:
        target.insert(len(target), _from_etree(child))
    return target


def _from_dom(node):
    if node.nodeType == Node.COMMENT_NODE:
        return SourceNode(None, text=node.data)
    namespace = node.namespaceURI
    tag = f"{{{namespace}}}{node.localName}" if namespace else node.tagName
    attrs = {}
    for attr in node.attributes.values():
        key = f"{{{attr.namespaceURI}}}{attr.localName}" if attr.namespaceURI else attr.name
        attrs[key] = attr.value
    target = SourceNode(tag, attrs)
    for child in node.childNodes:
        if child.nodeType in {Node.TEXT_NODE, Node.CDATA_SECTION_NODE}:
            if len(target):
                target[-1].tail = (target[-1].tail or "") + child.data
            else:
                target.text = (target.text or "") + child.data
        elif child.nodeType in {Node.ELEMENT_NODE, Node.COMMENT_NODE}:
            target.insert(len(target), _from_dom(child))
        else:
            raise ValueError(f"Unsupported HTML DOM node type {child.nodeType}")
    return target


def parse_source(decoded: str, *, treebuilder: str) -> SourceNode:
    """Parse already-decoded input, without rewriting names or source bytes."""
    if html5lib.__version__ != "1.1":
        raise ValueError("Bound HTML5 parser version 1.1 is required")
    if treebuilder == "etree":
        parsed = html5lib.parse(decoded, treebuilder="etree", namespaceHTMLElements=False)
        root = _from_etree(parsed)
    elif treebuilder == "dom":
        parsed = html5lib.parse(decoded, treebuilder="dom", namespaceHTMLElements=False)
        root = _from_dom(parsed.documentElement)
    else:
        raise ValueError(f"Unsupported lossless source tree builder {treebuilder!r}")
    # minidom's document.doctype is unset by html5lib, but its DocumentType
    # child retains the interpreted declaration. The etree route uses DOM only
    # for this document-shell accounting, never for its element tree.
    shell = parsed if treebuilder == "dom" else html5lib.parse(
        decoded, treebuilder="dom", namespaceHTMLElements=False
    )
    declarations, comments = [], []
    doctype = ""
    for position, child in enumerate(shell.childNodes, 1):
        if child.nodeType == Node.DOCUMENT_TYPE_NODE:
            declarations.append({"document_child_position": position, "name": child.name,
                                 "public_id": child.publicId, "system_id": child.systemId})
            doctype = "<!DOCTYPE " + child.name
            if child.publicId:
                doctype += ' PUBLIC "' + child.publicId + '"'
                if child.systemId:
                    doctype += ' "' + child.systemId + '"'
            elif child.systemId:
                doctype += ' SYSTEM "' + child.systemId + '"'
            doctype += ">"
        elif child.nodeType == Node.COMMENT_NODE:
            comments.append({"document_child_position": position, "text": child.data})
        elif child.nodeType != Node.ELEMENT_NODE:
            raise ValueError(f"Unaccounted document-shell node type {child.nodeType}")
    root._document_metadata = {
        "doctype": doctype,
        "doctype_semantics": "display reconstruction from HTML5 DOM DocumentType fields; not literal source bytes",
        "declarations": declarations,
        "document_comments": comments,
        "metadata_scope": "document-level declarations and comments excluded from element-tree serialization; bind these fields separately",
        "metadata_parser": "html5lib 1.1 DOM builder shared by both document-shell accounting routes",
    }
    return root


def interpreted_tree_bytes(node: SourceNode, *, with_tail: bool = False) -> bytes:
    """Versioned JSON representation, independent of XML name restrictions."""
    def record(current, tail):
        return [current.tag, sorted(current.attrib.items()), current.text or "",
                (current.tail or "") if tail else "", [record(child, True) for child in current]]
    return json.dumps(["newadvent-html-tree-v1", record(node, with_tail)], ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def interpreted_tree_sha256(node: SourceNode, *, with_tail: bool = False) -> str:
    return hashlib.sha256(interpreted_tree_bytes(node, with_tail=with_tail)).hexdigest()
