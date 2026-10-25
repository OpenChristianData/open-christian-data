"""Add acceptance bindings while retaining an exact reviewed TEI document."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from xml.sax.saxutils import escape, quoteattr

from lxml import etree

from ocd_kernel.library._common import PipelineError

NS = "http://www.tei-c.org/ns/1.0"


def bind_reviewed_header(
    original: bytes, *, expected_sha256: str, identity: Mapping[str, str],
    source: Mapping[str, object], source_url: str, declared_scope: str,
    revision: Mapping[str, str],
    historical_source_description: Mapping[str, object] | None = None,
) -> bytes:
    """Derive a header-bound representation without reserializing reviewed text.

    The caller retains the original and supplies an explicit evidence-backed
    identity. This operation is not acceptance and does not assert fidelity.
    Existing headers with competing bindings fail closed.
    """
    if hashlib.sha256(original).hexdigest() != expected_sha256:
        raise PipelineError("reviewed original hash mismatch")
    if set(identity) != {"work_id", "textual_form_id", "edition_id", "acquisition_id"}:
        raise PipelineError("integration requires four identity fields")
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    tree = etree.fromstring(original, parser)
    if tree.getroottree().docinfo.doctype:
        raise PipelineError("integration does not support document type declarations")
    ns = {"t": NS}
    if tree.tag != f"{{{NS}}}TEI" or len(tree.xpath("./t:teiHeader", namespaces=ns)) != 1:
        raise PipelineError("integration requires one TEI header")
    facts = dict(identity) | {
        "source_sha256": str(source["source_sha256"]),
        "source_bytes": str(source["source_bytes"]),
        "representation_revision": revision["id"],
    }
    if 'source_kind' in source:
        facts['source_kind'] = str(source['source_kind'])
    header = tree.find(f"{{{NS}}}teiHeader")
    revision_desc = header.find(f"{{{NS}}}revisionDesc")
    if tree.xpath("//*[@xml:id=$value]", value=revision["id"]):
        raise PipelineError("reviewed document already has this revision history binding")
    if any(node.get("type") in facts for node in header.iter(f"{{{NS}}}idno")):
        raise PipelineError("reviewed document already has acceptance bindings")
    if header.xpath(".//t:note[@type='source-scope' or @type='source-location']", namespaces=ns):
        raise PipelineError("reviewed document already has source bindings")
    pointers = header.xpath(".//t:sourceDesc//t:ptr/@target", namespaces=ns)
    existing_hashes = header.xpath(".//t:idno[@type='sha256']/text()", namespaces=ns)
    if historical_source_description is not None:
        if dict(historical_source_description) != {"pointers": pointers, "sha256": existing_hashes}:
            raise PipelineError("historical source description does not match explicit evidence")
    elif any(value != source_url for value in pointers):
        raise PipelineError("reviewed document has a different source URL")
    source_descs = header.xpath("./t:fileDesc/t:sourceDesc", namespaces=ns)
    if len(source_descs) != 1:
        raise PipelineError("integration requires one source description")
    def closing(node, name):
        prefix = node.prefix + ":" if node.prefix else ""
        return f"</{prefix}{name}>".encode("utf-8")
    source_end = closing(source_descs[0], "sourceDesc")
    header_end = closing(header, "teiHeader")
    for marker in (source_end, header_end):
        if original.count(marker) != 1:
            raise PipelineError("integration requires unique header boundaries")
    if historical_source_description is None and existing_hashes and any(value != str(source["source_sha256"]) for value in existing_hashes):
        raise PipelineError("reviewed document has a different retained hash")
    prose_description = bool(len(source_descs[0])) and all(node.tag == f"{{{NS}}}p" for node in source_descs[0])
    scoped_binding = historical_source_description is not None or prose_description
    if not existing_hashes or scoped_binding:
        facts["sha256"] = str(source["source_sha256"])
    bibl = '<bibl xmlns="' + NS + '"' + (' type="ocd-acceptance-binding"' if scoped_binding else '') + '>'
    if not pointers or scoped_binding:
        bibl += '<ptr target=' + quoteattr(source_url) + '/>'
    for key, value in facts.items():
        bibl += '<idno type=' + quoteattr(key) + '>' + escape(value) + '</idno>'
    for key, value in (("source-location", source["source_path"]), ("source-scope", declared_scope)):
        bibl += '<note type=' + quoteattr(key) + '>' + escape(str(value)) + '</note>'
    bibl += '</bibl>'
    binding = bibl
    if prose_description:
        binding = '<p xmlns="' + NS + '">' + bibl + '</p>'
    change = ('<change xmlns="' + NS + '" xml:id=' + quoteattr(revision["id"])
              + ' when=' + quoteattr(revision["date"]) + '>' + escape(revision["note"])
              + '</change>')
    revision_end = closing(revision_desc, "revisionDesc") if revision_desc is not None else header_end
    if original.count(revision_end) != 1:
        raise PipelineError("integration requires a unique revision boundary")
    if revision_desc is None:
        change = '<revisionDesc xmlns="' + NS + '">' + change + '</revisionDesc>'
    result = original.replace(source_end, binding.encode("utf-8") + source_end, 1)
    result = result.replace(revision_end, change.encode("utf-8") + revision_end, 1)
    etree.fromstring(result, parser)
    # Preserve every original byte; deleting precisely our additions recovers it.
    restored = result.replace(binding.encode("utf-8"), b"", 1).replace(change.encode("utf-8"), b"", 1)
    if restored != original:
        raise PipelineError("header integration changed reviewed bytes")
    return result
