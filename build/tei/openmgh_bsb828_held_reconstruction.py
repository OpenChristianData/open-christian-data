"""Source-native reconstruction of the eight bounded bsb00000828 identities.

The extracted XML is the only text authority. Selection is declared per work in
the pinned profile; source siblings and the acquisition ZIP are not text inputs.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"
CONVERTER_ID = "ocd-openmgh-bsb828-held-to-tei"
CONVERTER_VERSION = "1"


def _tag(name: str) -> str:
    return f"{{{TEI}}}{name}"


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source(manifest: SourceManifest, profile: Mapping[str, object]) -> tuple[etree._Element, etree._Element]:
    data = manifest.authority_path("extracted-xml").read_bytes()
    if _sha(data) != profile["source_sha256"]:
        raise ValueError("extracted XML hash drifted")
    root = etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if root.tag != _tag("TEI") or root.getroottree().docinfo.doctype:
        raise ValueError("source is not entity-free TEI")
    volume = root.find(f"{_tag('text')}/{_tag('body')}/{_tag('div')}")
    if volume is None or volume.get("type") != "volume":
        raise ValueError("source volume missing")
    works = list(volume)
    if len(works) != 17 or any(n.tag != _tag("div") or n.get("type") != "work" for n in works):
        raise ValueError("source work envelope changed")
    ordinal = profile["work_div_ordinal"]
    if not isinstance(ordinal, int) or not 1 <= ordinal <= 17:
        raise ValueError("invalid work division ordinal")
    work = works[ordinal - 1]
    if work.get("n") != profile["work_div_n"]:
        raise ValueError("source work label changed")
    return root, work


def _selected(work: etree._Element, profile: Mapping[str, object]) -> etree._Element:
    mode = profile["selection_mode"]
    start = profile["child_start"]
    stop = profile["child_stop"]
    children = list(work[0]) if mode == "ab-child-range" and len(work) == 1 else list(work)
    if not isinstance(start, int) or not isinstance(stop, int) or not 1 <= start <= stop <= len(children):
        raise ValueError("invalid source child range")
    if mode == "whole-div":
        if start != 1 or stop != len(work):
            raise ValueError("whole division selection is incomplete")
        return deepcopy(work)
    output = etree.Element(_tag("div"), type="work", n=str(profile["work_div_n"]))
    if mode == "part-range":
        if any(child.tag != _tag("div") or child.get("type") != "part" for child in work):
            raise ValueError("part envelope changed")
        for child in list(work)[start - 1:stop]:
            output.append(deepcopy(child))
    elif mode == "ab-child-range":
        if len(work) != 1 or work[0].tag != _tag("ab"):
            raise ValueError("flat ab envelope changed")
        ab = etree.SubElement(output, _tag("ab"), attrib=work[0].attrib)
        ab.text = work[0].text
        for child in list(work[0])[start - 1:stop]:
            ab.append(deepcopy(child))
    else:
        raise ValueError("unknown source selection mode")
    return output


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    manifest.verify()
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    if profile.get("contract") != "ocd-openmgh-bsb828-held-profile-v1":
        raise ValueError("held profile contract invalid")
    root, source_work = _source(manifest, profile)
    selected = _selected(source_work, profile)
    source_header = root.find(_tag("teiHeader"))
    if source_header is None:
        raise ValueError("source header missing")
    publication = source_header.find(f"{_tag('fileDesc')}/{_tag('publicationStmt')}")
    bibliography = source_header.find(f"{_tag('fileDesc')}/{_tag('sourceDesc')}/{_tag('biblFull')}")
    if publication is None or bibliography is None:
        raise ValueError("source publication or bibliography missing")
    output = etree.Element(_tag("TEI"), nsmap={None: TEI})
    output.set(XML_ID, f"ocd-{profile['work_id']}-electronic-v1")
    header = etree.SubElement(output, _tag("teiHeader"))
    description = etree.SubElement(header, _tag("fileDesc"))
    title_stmt = etree.SubElement(description, _tag("titleStmt"))
    etree.SubElement(title_stmt, _tag("title")).text = str(profile["work_title"])
    description.append(deepcopy(publication))
    etree.SubElement(description, _tag("sourceDesc")).append(deepcopy(bibliography))
    etree.SubElement(etree.SubElement(output, _tag("text")), _tag("body")).append(selected)
    content = etree.tostring(output, encoding="UTF-8", xml_declaration=True)
    source = manifest.authority_path("extracted-xml").read_bytes()
    selected_bytes = etree.tostring(selected, method="c14n", with_comments=True)
    counts = Counter(etree.QName(n).localname for n in selected.iter() if isinstance(n.tag, str))
    accounting = {
        "contract": "ocd-openmgh-bsb828-held-accounting-v1",
        "work_id": profile["work_id"], "edition_id": profile["edition_id"],
        "acquisition_id": profile["acquisition_id"],
        "source_path": profile["source_path"], "source_sha256": _sha(source),
        "work_div_ordinal": profile["work_div_ordinal"], "work_div_n": profile["work_div_n"],
        "selection_mode": profile["selection_mode"], "child_start": profile["child_start"],
        "child_stop": profile["child_stop"], "scope_note": profile["scope_note"],
        "selected_c14n_sha256": _sha(selected_bytes), "element_counts": dict(sorted(counts.items())),
        "outside_work_disposition": "Unselected source divisions and selected-division siblings remain in the acquired XML.",
        "zip_disposition": "The ZIP is an acquisition package, not a text source.",
    }
    provenance = {
        "contract": "ocd-openmgh-bsb828-held-provenance-v1", "status": "nonaccepted",
        "work_id": profile["work_id"], "edition_id": profile["edition_id"],
        "acquisition_id": profile["acquisition_id"], "source_path": profile["source_path"],
        "source_sha256": _sha(source), "canonical_ir_written": False, "publication": "not-ready",
    }
    unresolved = [
        {"status": "unresolved", "item": "Close visual and human review have not occurred."},
        {"status": "unresolved", "item": "Print collation, rights clearance, and publication attribution remain separate."},
    ]
    readme = (
        f"# {profile['work_title']} — source-bounded openMGH candidate\n\n"
        f"Extracted XML: `{profile['source_path']}` (SHA-256 `{_sha(source)}`).\n"
        f"Scope: {profile['scope_note']}\n"
        f"Selection: division {profile['work_div_ordinal']}, {profile['selection_mode']} "
        f"children {profile['child_start']}–{profile['child_stop']}.\n"
        "The original publication statement and bibliography remain in the TEI header. "
        "Monumenta Germaniae Historica (MGH) and the Bavarian State Library request naming in derivatives.\n"
    ).encode()
    return {"content.tei.xml": content, "source-accountability.json": _json(accounting),
            "provenance.json": _json(provenance),
            "unresolved.jsonl": b"".join(_json(x) for x in unresolved),
            "README.source.md": readme}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
