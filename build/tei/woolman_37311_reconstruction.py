"""Build one direct TEI root for a source-bound held Project Gutenberg work."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from lxml import etree, html

from ocd_kernel.reconstruction.contract import SourceManifest


TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _node(parent: etree._Element, name: str, **attributes: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{TEI}}}{name}", **attributes)


def _read_source(manifest: SourceManifest) -> tuple[dict[str, object], dict[str, object], etree._Element, list[dict[str, object]]]:
    profile = json.loads(manifest.authority_path("profile").read_text(encoding="utf-8"))
    base_bytes = manifest.authority_path("base-profile").read_bytes()
    base_profile = json.loads(base_bytes)
    if _sha(base_bytes) != profile["base_profile_sha256"]:
        raise ValueError("base PG source profile differs from direct-TEI boundary profile")
    archive_path = manifest.authority_path("retained-archive")
    receipt = json.loads(manifest.authority_path("acquisition-receipt").read_text(encoding="utf-8"))
    if _sha(archive_path.read_bytes()) != base_profile["archive_sha256"] or receipt["package"]["sha256"] != base_profile["archive_sha256"]:
        raise ValueError("retained archive or acquisition receipt digest differs from source profile")
    with ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError("retained archive CRC failure")
        members = [
            {"path": item.filename, "bytes": item.file_size, "crc32": f"{item.CRC:08x}", "sha256": _sha(archive.read(item))}
            for item in archive.infolist() if not item.is_dir()
        ]
        if members != base_profile["archive_members"]:
            raise ValueError("retained archive member inventory differs from profile")
        source_bytes = archive.read(str(base_profile["html_member"]))
    if _sha(source_bytes) != base_profile["html_sha256"] or receipt["html"]["sha256"] != base_profile["html_sha256"]:
        raise ValueError("HTML member digest differs from source profile or receipt")
    if manifest.authority_path("extracted-html").read_bytes() != source_bytes:
        raise ValueError("retained extracted HTML differs from archive member")
    root = html.fromstring(source_bytes.decode("utf-8", errors="strict"))
    body = root.find(".//body")
    if body is None or len(body) != base_profile["body_direct_children"]:
        raise ValueError("source HTML body boundary or direct-child count differs")
    return profile, base_profile, body, members


def _element_name(tag: str, *, top_level: bool) -> tuple[str, dict[str, str]]:
    allowed = {
        "header", "footer", "div", "p", "h1", "h2", "h3", "h4", "blockquote",
        "ul", "ol", "li", "table", "tbody", "thead", "tfoot", "tr", "td",
        "th", "colgroup", "col", "a", "img", "br", "hr", "span", "i", "em",
        "strong", "b", "small", "sup", "sub", "cite", "ins", "pre",
    }
    if tag not in allowed:
        raise ValueError(f"unmapped retained HTML tag: {tag}")
    if top_level:
        return ("table", {}) if tag == "table" else ("ab", {"type": f"source-{tag}"})
    if tag == "table":
        return "table", {}
    if tag == "tr":
        return "row", {}
    if tag in {"td", "th"}:
        return "cell", {"role": "label"} if tag == "th" else {}
    if tag == "a":
        return "ref", {}
    if tag == "img":
        return "graphic", {}
    if tag == "br":
        return "lb", {}
    if tag == "hr":
        return "milestone", {"unit": "source-rule"}
    if tag in {"i", "em", "strong", "b", "small", "sup", "sub"}:
        return "hi", {"rend": tag}
    if tag == "cite":
        return "title", {"type": "source-citation"}
    if tag == "ins":
        return "add", {}
    return "seg", {"type": f"source-{tag}"}


def _copy(source: etree._Element, parent: etree._Element, number: str, *, top_level: bool = False) -> etree._Element:
    if not isinstance(source.tag, str):
        target = _node(parent, "milestone", unit="source-comment", n=str(number))
        target.set("rend", "comment-sha256:" + _sha((source.text or "").encode("utf-8")))
        target.tail = source.tail
        return target
    tag = source.tag.lower()
    if tag in {"tbody", "thead", "tfoot", "colgroup", "col"}:
        start = _node(parent, "milestone", unit=f"source-{tag}-start", n=number)
        start.set(XML_ID, source.get("id") or f"source-node-{number}")
        start.tail = source.text
        for index, child in enumerate(source, 1):
            _copy(child, parent, f"{number}.{index}")
        end = _node(parent, "milestone", unit=f"source-{tag}-end", n=f"{number}.end")
        end.set(XML_ID, f"source-node-{number}.end")
        end.tail = source.tail
        return start
    name, attributes = _element_name(tag, top_level=top_level)
    target = _node(parent, name, **attributes)
    target.set("n", str(number))
    target.set(XML_ID, source.get("id") or f"source-node-{number}")
    if source.get("lang"):
        target.set(XML_LANG, source.get("lang"))
    render = [f"source-class:{source.get('class')}"] if source.get("class") else []
    if source.get("style"):
        render.append(f"source-style:{source.get('style')}")
    if render:
        target.set("rend", " | ".join(filter(None, (target.get("rend"), *render))))
    if tag == "a" and source.get("href"):
        target.set("target", source.get("href"))
    if tag == "img":
        if not source.get("src"):
            raise ValueError("source image lacks a path")
        target.set("url", source.get("src"))
        if source.get("alt"):
            target.set("rend", " | ".join(filter(None, (target.get("rend"), "source-alt:" + source.get("alt")))))
    if tag in {"td", "th"} and source.get("colspan"):
        target.set("cols", source.get("colspan"))
    target.text = source.text
    for index, child in enumerate(source, 1):
        _copy(child, target, f"{number}.{index}")
    target.tail = source.tail
    return target


def _header(tei: etree._Element, profile: dict[str, object], base: dict[str, object]) -> None:
    header = _node(tei, "teiHeader")
    desc = _node(_node(header, "fileDesc"), "titleStmt")
    _node(desc, "title").text = str(profile["title"])
    publication = _node(_node(tei.find(f"{{{TEI}}}teiHeader/{{{TEI}}}fileDesc"), "publicationStmt"), "p")
    publication.text = "Nonaccepted retained-source reconstruction candidate. Human acceptance, rights clearance, and publication are pending."
    source_desc = _node(_node(tei.find(f"{{{TEI}}}teiHeader/{{{TEI}}}fileDesc"), "sourceDesc"), "bibl")
    _node(source_desc, "title").text = str(base["volume_title"])
    _node(source_desc, "idno", type="gutenberg-ebook-id").text = str(base["ebook_id"])
    _node(source_desc, "idno", type="archive-sha256").text = str(base["archive_sha256"])
    _node(source_desc, "idno", type="html-sha256").text = str(base["html_sha256"])


def _unit_text(body: etree._Element, unit: dict[str, object]) -> str:
    start = int(unit["start"])
    end = int(unit["end"])
    return "".join(
        "".join(body[index].itertext()) + (body[index].tail or "")
        for index in range(start, end + 1)
    )


def _convert(manifest: SourceManifest) -> dict[str, bytes]:
    profile, base, body, members = _read_source(manifest)
    identity = {
        "work_id": profile["work_id"],
        "textual_form_id": profile["textual_form_id"],
        "edition_id": profile["edition_id"],
        "acquisition_id": profile["acquisition_id"],
    }
    if any(manifest.record.get(key) != value for key, value in identity.items()) or profile["source_id"] != manifest.record.get("source_id"):
        raise ValueError("source manifest and profile canonical identities differ")
    identity_evidence_bytes = manifest.authority_path("edition-identity").read_bytes()
    if _sha(identity_evidence_bytes) != profile.get("edition_identity_sha256"):
        raise ValueError("edition identity evidence differs from the source profile")
    identity_evidence = json.loads(identity_evidence_bytes)
    if (identity_evidence.get("work_id") != identity["work_id"] or identity_evidence.get("edition_id") != identity["edition_id"]
            or identity_evidence.get("electronic_source", {}).get("ebook_id") != profile.get("ebook_id")
            or identity_evidence.get("volume_boundary", {}).get("tei_document_count") != 1
            or identity_evidence.get("journal_component", {}).get("status") != "abridged"):
        raise ValueError("edition identity evidence does not establish the selected volume and component scope")
    work = json.loads(manifest.authority_path("work-sidecar").read_text(encoding="utf-8"))
    acquisition = json.loads(manifest.authority_path("acquisition-sidecar").read_text(encoding="utf-8"))
    form = next((item for item in work.get("textual_forms", []) if item.get("textual_form_id") == identity["textual_form_id"]), None)
    edition = next((item for item in (form or {}).get("editions", []) if item.get("edition_id") == identity["edition_id"]), None)
    if work.get("work_id") != identity["work_id"] or edition is None or identity["acquisition_id"] not in edition.get("acquisition_ids", []):
        raise ValueError("canonical WorkCatalog sidecar identity mismatch")
    if acquisition.get("acquisition_id") != identity["acquisition_id"] or acquisition.get("edition_id") != identity["edition_id"]:
        raise ValueError("canonical acquisition sidecar identity mismatch")
    units = base["units"]
    if not units or units[0]["start"] != 0 or units[-1]["end"] != len(body) - 1:
        raise ValueError("source unit ranges do not cover complete HTML body")
    if any(left["end"] + 1 != right["start"] for left, right in zip(units, units[1:])):
        raise ValueError("source unit ranges overlap or leave a gap")
    selected = profile["selected_unit_ids"]
    unit_by_id = {str(unit["id"]): unit for unit in units}
    if not selected or len(selected) != len(set(selected)) or any(unit_id not in unit_by_id for unit_id in selected):
        raise ValueError("direct-TEI selected unit inventory is invalid")
    selected_units = [unit_by_id[unit_id] for unit_id in selected]
    if profile["selection_mode"] == "complete-volume" and selected != [unit["id"] for unit in units]:
        raise ValueError("complete-volume candidate must include every source unit in source order")
    if profile["selection_mode"] == "single-titled-work" and len(selected_units) != 1:
        raise ValueError("single-work candidate must select exactly one source unit")

    tei = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    tei.set(XML_ID, str(profile["root_xml_id"]))
    _header(tei, profile, base)
    text = _node(tei, "text")
    body_target = _node(text, "body")
    if profile["selection_mode"] == "complete-volume":
        body_target.text = body.text
    for unit in selected_units:
        wrapper_type = "source-unit" if profile["selection_mode"] == "complete-volume" else "work"
        wrapper = _node(body_target, "div", type=wrapper_type, n=str(unit["id"]))
        wrapper.set(XML_ID, str(unit["id"]))
        for index in range(int(unit["start"]), int(unit["end"]) + 1):
            _copy(body[index], wrapper, str(index + 1), top_level=True)
    xml = etree.tostring(tei, encoding="UTF-8", xml_declaration=True)

    dispositions = profile["unit_dispositions"]
    account_units = []
    for unit in units:
        disposition = dispositions[str(unit["id"])]
        account_units.append({
            "id": unit["id"], "title": unit["title"], "kind": unit["kind"],
            "start": unit["start"], "end": unit["end"],
            "disposition": disposition["disposition"],
            "assigned_candidate_source_id": disposition.get("assigned_candidate_source_id"),
            "source_direct_child_count": int(unit["end"]) - int(unit["start"]) + 1,
            "source_text_sha256": _sha(_unit_text(body, unit).encode("utf-8")),
        })
    account = {
        "contract": "ocd-manifest-held-pg-one-root-source-accounting-v1",
        "source_id": manifest.record["source_id"],
        "scope_id": profile["scope_id"],
        "selection_mode": profile["selection_mode"], "title": profile["title"],
        "root_xml_id": profile["root_xml_id"],
        "archive_sha256": base["archive_sha256"], "html_sha256": base["html_sha256"],
        "archive_members": members,
        "source_body_direct_children": len(body),
        "source_body_text_sha256": _sha("".join(body.itertext()).encode("utf-8")),
        "source_body_opening_text_sha256": _sha((body.text or "").encode("utf-8")),
        "units": account_units,
        "selected_unit_ids": selected,
        "represented_body_text_sha256": _sha("".join(body_target.itertext()).encode("utf-8")),
        "tei_sha256": _sha(xml),
        "mapping": "One direct TEI root represents the source title boundary. Included HTML direct-child ranges are mapped once in order with nested text, tails, headings, lists, tables, inline roles, source IDs, local links, and retained image targets. Every excluded source range, opening text segment, archive member, and sibling-work disposition remains explicit in source accounting.",
        **identity,
    }
    policy = json.loads(manifest.authority_path("policy").read_text(encoding="utf-8"))
    return {
        "content.tei.xml": xml,
        "source-accountability.json": _json(account),
        "README.source.md": manifest.authority_path("readme").read_bytes(),
        "provenance.json": _json(policy["provenance"]),
        "unresolved.jsonl": b"".join(_json(item) for item in policy["unresolved"]),
    }


_convert.converter_id = "ocd-woolman-pg37311-direct-one-root"
_convert.converter_version = "2"
_convert.implementation_path = Path(__file__).resolve()
