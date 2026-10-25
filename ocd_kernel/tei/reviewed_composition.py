"""Ordered whole-document composition; no acceptance or source rewriting."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

from lxml import etree

from ocd_kernel.library._common import PipelineError

NS = 'http://www.tei-c.org/ns/1.0'


def _parse(raw: bytes):
    try:
        tree = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        raise PipelineError('composition requires one XML document') from exc
    if tree.getroottree().docinfo.doctype or tree.xpath('//comment() | //processing-instruction()'):
        raise PipelineError('composition refuses declarations, comments, or instructions')
    return tree


def compose_reviewed_documents(header: bytes, members: Sequence[tuple[bytes, str]]) -> bytes:
    """Wrap exact ordered TEI roots, stripping only their XML declarations.

    Every input is hash-bound; original packages remain separate evidence.
    The caller establishes edition membership/order and validates the result.
    Duplicate identifiers fail instead of being silently rewritten.
    """
    if len(members) < 2:
        raise PipelineError('composition requires at least two explicit members')
    if _parse(header).tag != '{' + NS + '}teiHeader':
        raise PipelineError('composition requires a TEI header')
    identifiers = set(_parse(header).xpath('//@xml:id'))
    bodies = []
    for raw, expected_sha256 in members:
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise PipelineError('reviewed composition member hash mismatch')
        tree = _parse(raw)
        if tree.tag != '{' + NS + '}TEI' or [n.tag for n in tree] != ['{' + NS + '}teiHeader', '{' + NS + '}text']:
            raise PipelineError('composition member must be one complete TEI document')
        member_ids = tree.xpath('//@xml:id')
        if len(set(member_ids)) != len(member_ids) or identifiers.intersection(member_ids):
            raise PipelineError('composition has duplicate source identifiers')
        identifiers.update(member_ids)
        bodies.append(re.sub(br'^<\?xml[^?]*\?>', b'', raw, count=1))
    result = b'<teiCorpus xmlns="' + NS.encode() + b'">' + header + b''.join(bodies) + b'</teiCorpus>'
    _parse(result)
    return result


def verify_reviewed_composition(composed: bytes, header: bytes, members: Sequence[tuple[bytes, str]]) -> list[str]:
    """Independently compare ordered complete member trees and header content."""
    def signature(node):
        return (node.tag, tuple(sorted(node.attrib.items())), node.text,
                tuple((signature(child), child.tail) for child in node))
    try:
        root = _parse(composed)
        if len(members) < 2 or root.tag != '{' + NS + '}teiCorpus' or len(root) != len(members) + 1:
            return ['composition envelope or member count differs']
        if root.attrib or (root.text or '').strip() or any((child.tail or '').strip() for child in root):
            return ['composition has undeclared envelope attributes or text']
        if signature(root[0]) != signature(_parse(header)):
            return ['composition header differs']
        for index, (raw, digest) in enumerate(members, 1):
            if hashlib.sha256(raw).hexdigest() != digest:
                return ['composition source binding differs']
            expected = _parse(raw)
            if signature(root[index]) != signature(expected):
                return [f'composition member {index} content or order differs']
        return []
    except (ValueError, etree.XMLSyntaxError, PipelineError) as exc:
        return ['composition verification failed: ' + str(exc)]
