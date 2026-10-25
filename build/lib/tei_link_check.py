"""Document-local URI fragment checks, independent of producer mappings."""
from __future__ import annotations

from collections import defaultdict
import hashlib
from urllib.parse import unquote

from lxml import etree

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
# Deliberately URI-valued relationships, not arbitrary values beginning with '#'.
LINK_ATTRIBUTES = frozenset({"target", "corresp", "next", "prev", "sameAs",
                             "copyOf", "synch", "facs", "spanTo"})


def check_links(data: bytes) -> dict:
    """Check local fragments; external documents and xml:base need other proof."""
    root = etree.fromstring(data, etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True, collect_ids=False))
    if root.tag not in {f"{{{TEI}}}TEI", f"{{{TEI}}}teiCorpus"}:
        raise ValueError("link check requires a TEI or teiCorpus document")
    if root.getroottree().docinfo.doctype or any(isinstance(n, etree._Entity) for n in root.iter()):
        raise ValueError("DTD/entity inputs require a dedicated source reader")
    tree = root.getroottree()
    targets = defaultdict(list)
    findings, unresolved, checked = [], [], []
    external_count = 0
    for node in root.iter():
        if isinstance(node.tag, str) and node.get(f"{{{XML}}}id") is not None:
            targets[node.get(f"{{{XML}}}id")].append(tree.getpath(node))
    for identity, locations in sorted(targets.items()):
        if len(locations) != 1:
            findings.append(dict(rule="duplicate-id", identity=identity, locations=locations))
    for node in root.iter():
        if not isinstance(node.tag, str) or etree.QName(node).namespace != TEI:
            continue
        for attribute in sorted(LINK_ATTRIBUTES.intersection(node.attrib)):
            for token in node.get(attribute).split():
                if not token.startswith("#"):
                    external_count += 1
                    continue
                item = dict(location=tree.getpath(node), attribute=attribute, target=token)
                if any(n.get(f"{{{XML}}}base") for n in [node, *node.iterancestors()]):
                    unresolved.append(dict(**item, reason="xml:base requires URI resolution"))
                    continue
                identity = unquote(token[1:], errors="strict")
                if "(" in identity or ")" in identity:
                    unresolved.append(dict(**item, reason="fragment scheme is outside simple-ID scope"))
                    continue
                locations = targets.get(identity, [])
                checked.append(dict(**item, resolved_locations=locations))
                if len(locations) != 1:
                    findings.append(dict(**item, rule="fragment-target-cardinality", count=len(locations)))
    return dict(status="fail" if findings else "incomplete" if unresolved else "pass",
                candidate_sha256=hashlib.sha256(data).hexdigest(),
                checked_attributes=sorted(LINK_ATTRIBUTES), checked=checked,
                unsupported=unresolved, external_tokens_not_checked=external_count,
                findings=findings, intended_source_target="not-assessed",
                scope="simple same-document URI fragments and document-wide xml:id uniqueness")
