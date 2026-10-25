"""Independent HTML/TEI reading of the complete Bede Gutenberg edition."""

from __future__ import annotations

import hashlib
from importlib.metadata import version as distribution_version
import json
from pathlib import Path
import platform
import sys
from zipfile import ZipFile

from bs4 import BeautifulSoup, NavigableString
from jsonschema import Draft202012Validator
from lxml import etree
from urllib.parse import quote


TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(content: bytes) -> dict[str, object]:
    return json.loads(content.decode("utf-8"))


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _closure_digest() -> str:
    return _sha(_canonical({
        "oracle_sha256": _sha(Path(__file__).resolve(strict=True).read_bytes()),
        "distributions": {name: distribution_version(name) for name in ("beautifulsoup4", "jsonschema", "lxml")},
    }))


def _norm(value: str) -> str:
    return " ".join(value.split())


def _tei_text(node: etree._Element) -> str:
    """Read a TEI carrier with source page labels restored from pb@n."""
    pieces = [node.text or ""]
    for child in node:
        if child.tag == TEI + "pb":
            pieces.append(child.get("n", ""))
        else:
            pieces.append(_tei_text(child))
        pieces.append(child.tail or "")
    return "".join(pieces)


def _require_equal(label: str, expected: object, actual: object) -> None:
    if expected != actual:
        raise ValueError(f"Bede source/TEI {label} mismatch: expected {str(expected)[:100]!r}, actual {str(actual)[:100]!r}")


def _direct_slots(source: object) -> tuple[list[object], list[str]]:
    children = []
    slots = [""]
    for item in source.contents:
        if isinstance(item, NavigableString):
            slots[-1] += str(item)
        else:
            children.append(item)
            slots.append("")
    return children, [_norm(value) for value in slots]


def _check_tree(source: object, target: etree._Element, path: str) -> int:
    """Independently compare every source element, edge, and direct text slot."""
    classes = set(source.get("class", []))
    if source.name == "div" and "tei-tb" in classes:
        if target.tag != TEI + "milestone" or target.get("unit") != "source-text-break" or len(source.find_all(recursive=False)) != 1:
            raise ValueError(f"Bede text-break carrier differs at {path}")
        return 1
    if source.name == "dl":
        if target.tag != TEI + "list" or target.get("type") != "footnotes":
            raise ValueError(f"Bede note list differs at {path}")
        children = source.find_all(recursive=False)
        if len(children) != 2 * len(target):
            raise ValueError(f"Bede note pair count differs at {path}")
        checked = 1
        for index, item in enumerate(target):
            if item.tag != TEI + "item" or len(item) != 2:
                raise ValueError(f"Bede note item attachment differs at {path}/{index + 1}")
            if children[2 * index].name != "dt" or children[2 * index + 1].name != "dd":
                raise ValueError(f"Bede source note pair order differs at {path}/{index + 1}")
            checked += _check_tree(children[2 * index], item[0], f"{path}/{index + 1}/label")
            checked += _check_tree(children[2 * index + 1], item[1], f"{path}/{index + 1}/note")
        return checked
    if source.name == "span" and "tei-pb" in classes:
        expected = "pb"
    elif source.name == "div":
        expected = "lg" if "tei-lg" in classes else "l" if "tei-l" in classes else "quote" if "tei-quote" in classes else "div"
    elif source.name == "span":
        expected = "seg"
    elif source.name == "a":
        expected = "ref" if source.get("href") or source.get_text().strip() else "anchor"
    else:
        expected = {"p": "p", "h1": "head", "h2": "head", "ul": "list", "li": "item", "hr": "milestone", "br": "lb", "pre": "ab", "dt": "label", "dd": "note"}.get(source.name)
    if expected is None or target.tag != TEI + expected:
        raise ValueError(f"Bede source carrier kind differs at {path}: {source.name} to {etree.QName(target).localname}")
    if source.get("id") != target.get(XML_ID):
        raise ValueError(f"Bede source carrier ID differs at {path}")
    if source.get("href") != target.get("target"):
        raise ValueError(f"Bede source link target differs at {path}")
    if source.get("lang") != target.get("{http://www.w3.org/XML/1998/namespace}lang"):
        raise ValueError(f"Bede source language differs at {path}")
    expected_rend = " ".join(
        f"source-{key}:" + quote(" ".join(source[key]) if key == "class" else source[key], safe="")
        for key in ("class", "style") if source.has_attr(key)
    )
    if expected_rend != target.get("rend", ""):
        raise ValueError(f"Bede source class/style differs at {path}")
    if expected == "pb":
        if target.get("n") != _norm(source.get_text()) or len(target) or target.text:
            raise ValueError(f"Bede source page marker differs at {path}")
        return 1
    source_children, source_slots = _direct_slots(source)
    target_slots = [_norm(target.text or "")] + [_norm(child.tail or "") for child in target]
    if len(source_children) != len(target) or source_slots != target_slots:
        raise ValueError(f"Bede source child or direct text order differs at {path}")
    count = 1
    for ordinal, (left, right) in enumerate(zip(source_children, target, strict=True), 1):
        count += _check_tree(left, right, f"{path}/{ordinal}")
    return count


def _role(manifest: object, name: str) -> bytes:
    authority = next((a for a in manifest.record["authorities"] if a.get("name") == name), None)
    if authority is None:
        raise ValueError(f"Bede manifest lacks authority {name}")
    value = manifest.authority_path(name).read_bytes()
    if len(value) != authority["bytes"] or _sha(value) != authority["sha256"]:
        raise ValueError(f"Bede authority {name} differs from manifest")
    return value


def _oracle(manifest: object, candidate: object) -> dict[str, object]:
    profile = _json(_role(manifest, "source-profile"))
    policy = _json(_role(manifest, "validation-policy"))
    _role(manifest, "tei-p5-xsd")
    _role(manifest, "candidate-package-schema")
    source = _role(manifest, "retained-html")
    archive = _role(manifest, "retained-archive")
    cover = _role(manifest, "cover-image")
    work = _json(_role(manifest, "work-sidecar"))
    acquisition = _json(_role(manifest, "acquisition-sidecar"))
    if (work.get("work_id") != profile["work_id"] or acquisition.get("edition_id") != profile["edition_id"]
            or acquisition.get("acquisition_id") != profile["acquisition_id"]
            or acquisition.get("source_path") != profile["source_html"]["path"]
            or acquisition.get("source_sha256") != _sha(source)
            or any(manifest.record.get(key) != profile[key] for key in ("work_id", "edition_id", "acquisition_id"))):
        raise ValueError("Bede sidecar/source identity mismatch")
    with ZipFile(manifest.authority_path("retained-archive")) as zipped:
        if zipped.testzip() is not None:
            raise ValueError("Bede archive CRC mismatch")
        members = [
            {"path": info.filename, "bytes": info.file_size, "crc32": f"{info.CRC:08x}", "sha256": _sha(zipped.read(info))}
            for info in zipped.infolist() if not info.is_dir()
        ]
        _require_equal("ZIP members", profile["source_archive"]["members"], members)
        if zipped.read("pg38326-images.html") != source or zipped.read("38326-cover.png") != cover:
            raise ValueError("Bede extracted members differ from ZIP")
    if _sha(archive) != profile["source_archive"]["sha256"]:
        raise ValueError("Bede ZIP hash mismatch")
    soup = BeautifulSoup(source, "lxml")
    body = soup.body
    if body is None:
        raise ValueError("Bede source body absent")
    direct = body.find_all(recursive=False)
    if [item.name for item in direct] != ["header", "div", "footer"]:
        raise ValueError("Bede provider wrapper changed")
    literary = direct[1]
    if "tei-text" not in literary.get("class", []):
        raise ValueError("Bede text selection changed")
    parts = literary.find_all(recursive=False)
    if [item.name for item in parts] != ["div", "div", "hr", "div"]:
        raise ValueError("Bede front/body/back envelope changed")
    if ["tei-front" in parts[0].get("class", []), "tei-body" in parts[1].get("class", []), "tei-back" in parts[3].get("class", [])] != [True] * 3:
        raise ValueError("Bede source part classes changed")
    candidate.verify_integrity()
    if candidate.manifest.get("source_id") != manifest.record["source_id"]:
        raise ValueError("Bede candidate source identity mismatch")
    content = candidate.member_bytes("content.tei.xml")
    account = _json(candidate.member_bytes("source-accountability.json"))
    schema = _json(_role(manifest, "source-accountability-schema"))
    errors = list(Draft202012Validator(schema).iter_errors(account))
    if errors:
        raise ValueError(f"Bede accountability schema failure: {errors[0].message}")
    if (account.get("source_sha256") != _sha(source) or account.get("source_archive_sha256") != _sha(archive)
            or account.get("candidate_sha256") != _sha(content)
            or account.get("source_members") != members
            or any(account.get(key) != profile[key] for key in ("work_id", "edition_id", "acquisition_id"))):
        raise ValueError("Bede candidate accounting differs from exact source")
    if candidate.member_bytes("README.source.md") != _role(manifest, "source-readme"):
        raise ValueError("Bede human-visible source notice differs")
    if candidate.member_bytes("provenance.json") != _canonical(policy["provenance"]):
        raise ValueError("Bede candidate provenance differs")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(_canonical(item) for item in policy["unresolved"]):
        raise ValueError("Bede candidate unresolved decisions differ")
    root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
    if root.tag != TEI + "TEI":
        raise ValueError("Bede candidate has no TEI root")
    text = root.find(TEI + "text")
    if text is None or [child.tag for child in text] != [TEI + "front", TEI + "body", TEI + "back"]:
        raise ValueError("Bede candidate part boundaries differ")
    checked_elements = 0
    for index, source_part in ((0, parts[0]), (1, parts[1]), (2, parts[3])):
        source_children, source_slots = _direct_slots(source_part)
        target_part = text[index]
        target_children = list(target_part)
        if index == 1:
            if not target_children or target_children[-1].tag != TEI + "milestone":
                raise ValueError("Bede body/back separator differs")
            target_children = target_children[:-1]
        target_slots = [_norm(target_part.text or "")] + [_norm(child.tail or "") for child in target_children]
        if len(source_children) != len(target_children) or source_slots != target_slots:
            raise ValueError(f"Bede {etree.QName(target_part).localname} direct carrier order differs")
        for ordinal, (left, right) in enumerate(zip(source_children, target_children, strict=True), 1):
            checked_elements += _check_tree(left, right, f"{index + 1}/{ordinal}")
    if checked_elements < 20000:
        raise ValueError("Bede complete literary carrier traversal was unexpectedly small")
    source_ids = [item["id"] for item in literary.find_all(id=True)]
    candidate_ids = [item.get(XML_ID) for item in text.iter() if item.get(XML_ID)]
    _require_equal("ordered source IDs", source_ids, candidate_ids)
    if len(set(source_ids)) != len(source_ids) or len(source_ids) != profile["expected_source_ids"]:
        raise ValueError("Bede source IDs are not unique or complete")
    source_refs = [(item.get("href"), item.get("id"), _norm(item.get_text())) for item in literary.find_all("a", href=True)]
    tei_refs = [(item.get("target"), item.get(XML_ID), _norm(_tei_text(item))) for item in text.iter(TEI + "ref")]
    _require_equal("ordered link targets, IDs and wording", source_refs, tei_refs)
    if len(source_refs) != profile["expected_local_links"]:
        raise ValueError("Bede source link count differs from profile")
    dangling = [href for href, _, _ in source_refs if href.startswith("#") and href[1:] not in source_ids]
    if dangling:
        raise ValueError(f"Bede source has dangling links: {dangling[:3]}")
    source_headings = [_norm(item.get_text()) for item in literary.find_all(["h1", "h2"])]
    tei_headings = [_norm(_tei_text(item)) for item in text.iter(TEI + "head")]
    _require_equal("ordered headings", source_headings, tei_headings)
    body_sections = [_norm(item.get_text()) for item in parts[1].find_all("h1")]
    _require_equal("body work and apparatus boundaries", profile["expected_sections"], body_sections)
    for source_name, target_name in (("p", "p"), ("div.tei-lg", "lg"), ("div.tei-l", "l")):
        selected = literary.select(source_name)
        observed = list(text.iter(TEI + target_name))
        _require_equal(f"{source_name} count", len(selected), len(observed))
        for ordinal, (left, right) in enumerate(zip(selected, observed, strict=True), 1):
            if _norm(left.get_text()) != _norm(_tei_text(right)):
                raise ValueError(f"Bede {source_name} wording/order differs at occurrence {ordinal}")
    source_pages = [(item.get("id"), _norm(item.get_text())) for item in literary.select("span.tei-pb")]
    tei_pages = [(item.get(XML_ID), item.get("n")) for item in text.iter(TEI + "pb")]
    _require_equal("ordered printed page markers", source_pages, tei_pages)
    if len(source_pages) != profile["expected_page_markers"]:
        raise ValueError("Bede printed-page count differs")
    note_labels = literary.select("dt.tei-notelabel")
    note_texts = literary.select("dd.tei-notetext")
    candidate_labels = list(text.iter(TEI + "label"))
    candidate_notes = list(text.iter(TEI + "note"))
    _require_equal("note pair counts", (len(note_labels), len(note_texts), len(candidate_labels), len(candidate_notes)), (1081, 1081, 1081, 1081))
    for ordinal, (label, note, tei_label, tei_note) in enumerate(zip(note_labels, note_texts, candidate_labels, candidate_notes, strict=True), 1):
        if _norm(label.get_text()) != _norm(_tei_text(tei_label)) or _norm(note.get_text()) != _norm(_tei_text(tei_note)):
            raise ValueError(f"Bede footnote label/body differs at note {ordinal}")
    books = [item for item in text.iter(TEI + "div") if item.get("type") == "book"]
    _require_equal("five books", [f"Book {n}" for n in ("I", "II", "III", "IV", "V")], [_norm(_tei_text(next(item.iter(TEI + "head")))) for item in books])
    continuation = [item for item in text.iter(TEI + "div") if item.get("type") == "continuation"]
    if len(continuation) != 1 or _norm(_tei_text(next(continuation[0].iter(TEI + "head")))) != "Continuation":
        raise ValueError("Bede Continuation boundary differs")
    if not any("The Continuation is by a later hand" in _tei_text(item) for item in candidate_notes):
        raise ValueError("Bede later-hand attribution note is absent")
    schema_path = Path(__file__).resolve(strict=True).parents[2] / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"
    xsd = etree.XMLSchema(etree.parse(str(schema_path)))
    xsd.assertValid(root)
    authorities = {item["role"]: item for item in manifest.record["authorities"]}
    report = {
        "status": "pass", "oracle_id": "ocd-bede-gutenberg-independent-html-reader",
        "oracle_version": "1", "implementation_sha256": _sha(Path(__file__).resolve(strict=True).read_bytes()),
        "import_closure_sha256": _closure_digest(),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": manifest.sha256, "candidate_sha256": candidate.sha256,
        "profile_sha256": authorities["complete-source-feature-profile"]["sha256"],
        "package_schema_sha256": authorities["candidate-package-schema"]["sha256"],
        "source_sha256": _sha(source),
        "xsd_sha256": authorities["tei-validation-schema"]["sha256"],
        "policy_sha256": authorities["independent-validation-policy"]["sha256"],
        "findings": [],
    }
    report["result_sha256"] = _sha(_canonical(report))
    return report


_oracle.oracle_id = "ocd-bede-gutenberg-independent-html-reader"
_oracle.oracle_version = "1"
_oracle.implementation_path = Path(__file__).resolve()
