"""Bounded XML text reader with internal entities and no external retrieval.

This reads text, not DTD validity or external default attributes. Unsupported
dependencies remain gaps; no filesystem or network resolver is installed.
"""
from __future__ import annotations

import hashlib
import codecs
from pathlib import Path
import re
from xml.parsers import expat

from lxml import etree

MAX_PROLOG_BYTES = 1024 * 1024
MAX_ENTITIES = 256
MAX_ENTITY_CHARACTERS = 1024 * 1024
MAX_ENTITY_DEPTH = 16
MAX_DTD_INPUT_BYTES = 64 * 1024 * 1024
_REFERENCE = re.compile(r"&([^;]+);")
_XML_ENCODING = re.compile(br"^<\?xml\s[^?]*\bencoding\s*=\s*(['\"])([A-Za-z][A-Za-z0-9._-]*)\1")


def _inspection_encoding(data: bytes) -> str:
    # XML 1.0 Appendix F signatures; the final tree is always parsed from the
    # original bytes by libxml2, so transcoding cannot legitimize bad input.
    if data.startswith((b'\xff\xfe\x00\x00', b'\x00\x00\xfe\xff')):
        return "utf-32"
    if data.startswith(b'\x00\x00\x00<'):
        return "utf-32-be"
    if data.startswith(b'<\x00\x00\x00'):
        return "utf-32-le"
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return "utf-16"
    if data.startswith(b'\x00<\x00?'):
        return "utf-16-be"
    if data.startswith(b'<\x00?\x00'):
        return "utf-16-le"
    prefix = data[:MAX_PROLOG_BYTES].removeprefix(codecs.BOM_UTF8)
    declared = _XML_ENCODING.match(prefix)
    return declared.group(2).decode("ascii") if declared else "utf-8-sig"


def inspection_decoder(data: bytes):
    encoding = _inspection_encoding(data)
    try:
        if not codecs.lookup(encoding)._is_text_encoding:
            raise ValueError(f"Nontext XML inspection encoding: {encoding}")
        return encoding, codecs.getincrementaldecoder(encoding)(errors="strict")
    except LookupError as exc:
        raise ValueError(f"Unsupported XML inspection encoding: {encoding}") from exc


class _RootFound(Exception):
    pass


class _DenyExternal(etree.Resolver):
    def resolve(self, url, public_id, context):
        raise ValueError("XML external dependency requires a retained hash-bound reader")


class _InertSubset(_DenyExternal):
    def __init__(self, system_id):
        self.system_id = system_id

    def resolve(self, url, public_id, context):
        if url == self.system_id:
            # resolve_empty lets libxml2 fall through to an existing local DTD.
            return self.resolve_string(b"", context)
        return super().resolve(url, public_id, context)


def _prolog(data: bytes) -> dict:
    """Inspect declarations without expanding general entity references."""
    encoding, decoder = inspection_decoder(data)
    parser = expat.ParserCreate(encoding="UTF-8")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    entities = {}
    evidence = {"doctype": None, "external_subset": None, "unparsed_entities": 0,
                "inspection_encoding": encoding, "inert_parameter_declarations": []}

    def doctype(name, system_id, public_id, internal):
        evidence.update(doctype=name, external_subset=system_id)

    def entity(name, parameter, value, base, system_id, public_id, notation):
        if parameter:
            if system_id is None:
                raise ValueError("XML internal parameter entities require a dedicated reader")
            evidence["inert_parameter_declarations"].append(
                {"name": name, "system_id": system_id, "public_id": public_id})
            if len(evidence["inert_parameter_declarations"]) > MAX_ENTITIES:
                raise ValueError("XML parameter declaration budget exceeded")
            return
        if notation is not None:
            evidence["unparsed_entities"] += 1
            return
        if system_id is not None or public_id is not None:
            raise ValueError("XML external text entities require a retained hash-bound reader")
        if name in entities:
            raise ValueError("Duplicate XML entity declaration")
        entities[name] = value or ""
        if len(entities) > MAX_ENTITIES or sum(map(len, entities.values())) > MAX_ENTITY_CHARACTERS:
            raise ValueError("XML entity declaration budget exceeded")

    def bound_entities():
        # Bound nested expansion before handing the same bytes to libxml2.
        sizes, depths = {}, {}
        pending = dict(entities)
        while pending:
            progressed = False
            for name, value in list(pending.items()):
                refs = [m.group(1) for m in _REFERENCE.finditer(value)
                        if m.group(1) in entities]
                if any(ref not in sizes for ref in refs):
                    continue
                size = len(value) + sum(sizes[ref] for ref in refs)
                depth = 1 + max((depths[ref] for ref in refs), default=0)
                if size > MAX_ENTITY_CHARACTERS or depth > MAX_ENTITY_DEPTH:
                    raise ValueError("XML entity expansion budget exceeded")
                sizes[name], depths[name] = size, depth
                del pending[name]
                progressed = True
            if not progressed:
                raise ValueError("Cyclic XML entity declarations are unsupported")

    def root(name, attributes):
        raise _RootFound

    def unexpanded(value):
        if value.startswith("%") and value.endswith(";"):
            raise ValueError("XML parameter entity references require a retained hash-bound reader")

    def skipped(name, parameter):
        raise ValueError("XML skipped entity requires a retained hash-bound reader")

    parser.StartDoctypeDeclHandler = doctype
    parser.EntityDeclHandler = entity
    parser.EndDoctypeDeclHandler = bound_entities
    parser.StartElementHandler = root
    parser.DefaultHandler = unexpanded
    parser.SkippedEntityHandler = skipped
    try:
        for offset in range(0, len(data), 16384):
            if offset >= MAX_PROLOG_BYTES:
                raise ValueError("XML prolog exceeds the 1 MiB inspection limit")
            parser.Parse(decoder.decode(data[offset:offset + 16384], final=False), False)
        parser.Parse(decoder.decode(b"", final=True), True)
    except _RootFound:
        pass
    except expat.ExpatError as exc:
        raise ValueError(f"XML prolog parsing failed: {exc}") from exc
    except UnicodeError as exc:
        raise ValueError(f"XML prolog decoding failed ({encoding}): {exc}") from exc

    evidence["internal_entities"] = len(entities)
    return evidence


def read_text_xml(data: bytes):
    """Return an expanded tree and explicit reader evidence from retained bytes.

    Inert external DOCTYPE identifiers, unreferenced external parameter
    declarations and unparsed media declarations are
    retained as evidence but never loaded. DTD-bearing inputs use libxml2's
    ordinary depth, text and amplification limits, with recovery disabled.
    """
    evidence = _prolog(data)
    dtd = evidence["doctype"] is not None
    if dtd and len(data) > MAX_DTD_INPUT_BYTES:
        raise ValueError("DTD-bearing XML exceeds the 64 MiB input limit")
    parser = etree.XMLParser(resolve_entities=True, no_network=True, load_dtd=False,
                             attribute_defaults=False, dtd_validation=False,
                             remove_comments=False, remove_pis=False,
                             remove_blank_text=False, huge_tree=not dtd, recover=False,
                             collect_ids=False)
    # libxml2 may request the subset when ID collection is disabled; no bytes
    # are retrieved and the inventoried inert subset is deliberately empty.
    parser.resolvers.add(_InertSubset(evidence["external_subset"]))
    try:
        root = etree.fromstring(data, parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"XML parsing failed: {exc}") from exc
    # An omitted external subset makes libxml2 warn and discard undeclared text.
    if any(entry.type_name in {"WAR_UNDECLARED_ENTITY", "ERR_UNDECLARED_ENTITY"}
           for entry in parser.error_log):
        raise ValueError("XML reader encountered undeclared entity text")
    if any(isinstance(node, etree._Entity) for node in root.iter()):
        raise ValueError("XML reader left unresolved entity text")
    evidence.update(
        name="bounded-internal-entities-v1", external_retrieval="disabled",
        external_subset_disposition="ignored_empty_subset",
        entity_expansion="internal_general_entities_only",
        implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        expat_version=expat.EXPAT_VERSION, libxml_version=list(etree.LIBXML_VERSION),
        limits={"prolog_bytes": MAX_PROLOG_BYTES, "entities": MAX_ENTITIES,
                "entity_characters": MAX_ENTITY_CHARACTERS, "entity_depth": MAX_ENTITY_DEPTH,
                "dtd_input_bytes": MAX_DTD_INPUT_BYTES},
    )
    return root, evidence
