"""Source-defined Bible verse projection for PIPE-007A.

This category keeps the edition's native verse carriers and labels. It does
not create a versification bridge or turn headings into verse text. Known
source paragraph continuations remain in the preceding verse. The producer
uses :mod:`xml.etree.ElementTree`; the checker independently recomputes the
private receipt from the TEI.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qs, urlparse

from ocd_kernel.library._common import PipelineError, ensure_relative_path, io_path
from ocd_kernel.projection.scripture_authority import BOOK_CODES_PATH, load_book_codes
from ocd_kernel.projection.scripture_targets import normalize_explicit_target
from ocd_kernel.projection.scripture_targets_check import observe_explicit_target
from ocd_kernel.projection.envelope import canonical_row_bytes, make_row, row_text_hash

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_SPACE = f"{{{XML_NS}}}space"
MAPPING_VERSION = "ocd-bible-mapping-provisional-v6"
CORPUS_MAPPING_VERSION = "ocd-bible-corpus-mapping-provisional-v2"
ENGWEBPB_MAPPING_VERSION = "ocd-bible-engwebpb-mapping-provisional-v1"
ASSEMBLER_VERSION = "ocd-bible-assembler-provisional-v2"
CATEGORY = "bible"
RECEIPT_VERSION = "ocd-bible-receipt-provisional-v2"
_NATIVE_ZERO_POLICY = "source-native-zero-chapter-v1"
_NATIVE_ZERO_VERSIFICATION = "source-native:original-douay-rheims-v1.0"
_ENGWEBPB_IDENTITY = {
    "work_id": "engwebpb", "textual_form_id": "engwebpb-retained-en",
    "edition_id": "engwebpb-electronic-2020",
}
_ENGWEBPB_REVISION = "engwebpb-retained-current-20261003-v1"
_ENGWEBPB_SOURCE_SHA256 = "822a44d0f1fbeaa95056fb5fcc0a81c9349dbdf2b5f1349f06005c4d742a16e7"
_ENGWEBPB_CORRESP = re.compile(r"source-usfm:engwebpb/([^/#&]+)#line=([1-9][0-9]*)(?:&span=([0-9]+):([0-9]+))?\Z")
_ENGWEBPB_CONTINUATIONS = {"usfm-q1", "usfm-q2", "usfm-p", "usfm-m", "usfm-pi1", "usfm-mi", "usfm-li1"}
_ENGWEBPB_NONVERSE = {"usfm-d", "usfm-sp", "usfm-id", "usfm-ide", "usfm-ip", "usfm-ili", "usfm-cl"}
_ENGWEBPB_EMPTY_MARKERS = {"usfm-b", "usfm-nb", "usfm-c-content"}
ROOT = Path(__file__).resolve().parents[3]
_ENGWEBPB_MEMBER_SET = ROOT / "library/works/engwebpb/forms/engwebpb-retained-en/editions/engwebpb-electronic-2020/source-member-set.json"

_RETAINED_USFM_PROFILES = {
    "engwebpb": {
        "identity": _ENGWEBPB_IDENTITY, "revision": _ENGWEBPB_REVISION,
        "source_sha256": _ENGWEBPB_SOURCE_SHA256,
        "member_set": "library/works/engwebpb/forms/engwebpb-retained-en/editions/engwebpb-electronic-2020/source-member-set.json",
        "members": 68, "lines": 61098, "spans": 690050, "verses": 31103,
        "words": 682692, "notes": 1572, "retained_notes": 4,
        "mapping_version": ENGWEBPB_MAPPING_VERSION,
        "warning": "engwebpb-verse-rows-include-source-continuations;front-back-headings-markers-and-four-notes-retained-in-master",
    },
    "eng-web-c": {
        "identity": {"work_id": "eng-web-c", "textual_form_id": "eng-web-c-retained-en", "edition_id": "eng-web-c-electronic-2020"},
        "revision": "eng-web-c-retained-native-accepted-20261004-v1",
        "source_sha256": "16241fddce8056e078eedbd1c5946e6c87900924ac989b53cca324c435250a5c",
        "member_set": "library/works/eng-web-c/forms/eng-web-c-retained-en/editions/eng-web-c-electronic-2020/source-member-set.json",
        "members": 73, "lines": 70744, "spans": 678353, "verses": 35408,
        "words": 669387, "notes": 2021, "retained_notes": 4,
        "mapping_version": "ocd-bible-engwebc-mapping-provisional-v1",
        "warning": "eng-web-c-verse-rows-include-source-continuations;headings-markers-Sirach51-caption-and-four-notes-retained-in-master;two-exact-Esther-note-boundaries-render-as-spaces",
    },
    "engwmb": {
        "identity": {"work_id": "engwmb", "textual_form_id": "engwmb-retained-en", "edition_id": "engwmb-electronic-2022"},
        "revision": "engwmb-retained-native-accepted-20261004-v1",
        "source_sha256": "8922c9bb2ac5f58f1ae764d05fda580bc00e3102b0779f77d295eb107f80fc1e",
        "member_set": "library/works/engwmb/forms/engwmb-retained-en/editions/engwmb-electronic-2022/source-member-set.json",
        "members": 66, "lines": 60960, "spans": 689220, "verses": 31103,
        "words": 682148, "notes": 1533, "retained_notes": 3,
        "mapping_version": "ocd-bible-engwmb-mapping-provisional-v1",
        "warning": "engwmb-verse-rows-include-source-continuations;headings-markers-and-three-notes-retained-in-master",
    },
}
for _profile_slug, _profile_values in _RETAINED_USFM_PROFILES.items():
    _profile_values["slug"] = _profile_slug
    _profile_values["filename_pattern"] = re.compile(r"[0-9]+-([A-Z0-9]+)" + re.escape(_profile_slug) + r"\.usfm\Z")
    _profile_values["member_pattern"] = re.compile(r"raw/ebible/" + re.escape(_profile_slug) + r"/usfm/members/[0-9]+-[A-Z0-9]+" + re.escape(_profile_slug) + r"\.usfm\Z")
    _profile_values["corresp_pattern"] = re.compile(r"source-usfm:" + re.escape(_profile_slug) + r"/([^/#&]+)#line=([1-9][0-9]*)(?:&span=([0-9]+):([0-9]+))?\Z")
    _profile_values["line_pattern"] = re.compile(r"source-usfm:" + re.escape(_profile_slug) + r"/[^/#&]+#line=[1-9][0-9]*\Z")
del _profile_slug, _profile_values

SCHEMA_PATH = ROOT / "schemas" / "v2" / "categories" / "bible.schema.json"
COMMON_SCHEMA_PATH = ROOT / "schemas" / "v2" / "public-row.schema.json"
_IDENTITY_KEYS = ("work_id", "textual_form_id", "edition_id")
_TEXT_PARTS = {"front", "body", "back"}
_CARRIER_NAMES = {"ab", "p", "seg", "verse"}
_ALLOWED_VISIBLE = {
    "text", "front", "body", "back", "div", "chapter", "head", "p", "ab",
    "seg", "verse", "hi", "foreign", "ref", "note", "lb", "pb", "anchor",
    "ptr", "title", "w", "supplied",
}
_ATTRS = {
    "TEI": {"xml:id"},
    "text": {"xml:id"},
    "front": {"xml:id"},
    "body": {"xml:id", "book", "book_name", "book_osis", "osis", "osisID"},
    "back": {"xml:id"},
    "div": {"type", "n", "xml:id", "book", "book_name", "book_osis", "osis", "osisID", "corresp", "ana"},
    "chapter": {"n", "xml:id"},
    "head": {"type", "xml:id"},
    "p": {"type", "n", "xml:id", "xml:lang"},
    "ab": {"type", "n", "xml:id", "xml:lang", "xml:space", "corresp", "ana"},
    "seg": {"type", "n", "xml:id", "xml:lang"},
    "title": {"type", "xml:id", "xml:lang"},
    "w": {"n", "xml:id", "xml:lang"},
    "supplied": {"reason", "xml:id", "xml:lang"},
    "verse": {"type", "n", "xml:id", "xml:lang", "number", "verse"},
    "hi": {"rend", "xml:id", "xml:lang"},
    "foreign": {"xml:id", "xml:lang"},
    "ref": {"type", "target", "cRef", "xml:id"},
    "note": {"type", "place", "n", "xml:id"},
    "lb": {"break", "xml:id"},
    "pb": {"n", "xml:id"},
    "anchor": {"xml:id"},
    "ptr": {"type", "target", "xml:id"},
}
_HEADER_ATTRS = {
    "teiHeader": {"xml:id"}, "encodingDesc": {"xml:id"}, "profileDesc": {"xml:id"},
    "langUsage": {"xml:id"}, "language": {"ident", "xml:id"}, "textClass": {"xml:id"},
    "keywords": {"xml:id"}, "term": {"xml:id"}, "fileDesc": {"xml:id"},
    "titleStmt": {"xml:id"}, "title": {"xml:id", "type"}, "author": {"xml:id"},
    "editor": {"xml:id"}, "publicationStmt": {"xml:id"}, "publisher": {"xml:id"},
    "availability": {"status", "xml:id"}, "licence": {"target", "xml:id"},
    "sourceDesc": {"xml:id"}, "bibl": {"xml:id", "type"}, "idno": {"type", "xml:id"},
    "ptr": {"type", "target", "xml:id"}, "note": {"type", "place", "n", "xml:id"},
    "revisionDesc": {"xml:id"}, "change": {"when", "xml:id"}, "date": {"when", "xml:id"},
    "respStmt": {"xml:id"}, "resp": {"xml:id"}, "name": {"xml:id"},
}
_EXCLUDED_TYPES = {"title-page", "half-title-page", "copyright-page", "imprint", "colophon", "paratext"}
_CORPUS_MARKERS = {
    "centered-paragraph": {"pc"},
    "continuation-paragraph": {"nb"},
    "flush-paragraph": {"m"},
    "introduction-paragraph": {"ip"},
    "paragraph-break": {"p"},
    "poetry-line": {"q1", "q2"},
    "source-id-label": {"id"},
    "stanza-break": {"b"},
    "usfm-d": {"d"},
    "usfm-h": {"h"},
    "usfm-is1": {"is1"},
    "usfm-ms1": {"ms1"},
    "usfm-ms2": {"ms2"},
    "usfm-mt1": {"mt1"},
    "usfm-mt2": {"mt2"},
    "usfm-mt3": {"mt3"},
    "usfm-s1": {"s1"},
    "usfm-toc1": {"toc1"},
    "usfm-toc2": {"toc2"},
    "usfm-toc3": {"toc3"},
}
_CORPUS_CONTINUATIONS = {"continuation-paragraph", "flush-paragraph", "paragraph-break", "poetry-line"}
_WARNING_REASONS = {
    "hi": "styling-to-plain-text",
    "foreign": "language-span-to-plain-text",
    "seg": "segmentation-to-plain-text",
    "note": "note-extracted",
    "pb": "milestone-omitted",
    "anchor": "milestone-omitted",
    "ptr": "milestone-omitted",
    "lb": "line-break-to-space",
    "ref": "source-reference-preserved",
    "supplied": "source-supplied-text-marker-flattened",
}


class UnsupportedStructure(PipelineError):
    """The source exposes visible Bible structure outside this slice."""


def _local(tag: Any) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_text(value: str) -> str:
    return _hash_bytes(value.encode("utf-8"))


def _valid_hash(value: str, *, field: str) -> str:
    normalized = value.strip().lower().removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise PipelineError(f"{field} must be a lowercase SHA-256 digest")
    return normalized


def _identity(identity: Mapping[str, str]) -> dict[str, str]:
    if set(identity) != set(_IDENTITY_KEYS):
        raise PipelineError("public identity requires exactly work, form, and edition")
    result: dict[str, str] = {}
    for key in _IDENTITY_KEYS:
        value = identity.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
            raise PipelineError(f"invalid public identity {key}")
        result[key] = value
    return result


def _engwebpb_profile(identity: Mapping[str, str], revision: str, header: Mapping[str, Any]) -> Mapping[str, Any] | None:
    profile = _RETAINED_USFM_PROFILES.get(identity.get("work_id", ""))
    if profile is None:
        return None
    if (
        dict(identity) != profile["identity"] or revision != profile["revision"]
        or header["ids"].get("source_kind") != "retained-member-set"
        or header["ids"].get("representation_revision") != revision
        or header.get("source_sha256") != profile["source_sha256"]
        or header.get("retained_sha256") != profile["source_sha256"]
    ):
        raise PipelineError(f"{profile['slug']} projection profile does not bind the accepted source and revision")
    return profile



def _engwebpb_members(profile: Mapping[str, Any] | None = None) -> list[tuple[str, list[str]]]:
    if profile is None:
        profile = _RETAINED_USFM_PROFILES["engwebpb"]
    raw = (ROOT / profile["member_set"]).read_bytes()
    if _hash_bytes(raw) != profile["source_sha256"]:
        raise PipelineError("engwebpb retained member set differs")
    manifest = json.loads(raw)
    members = manifest.get("members")
    if manifest.get("contract") != "ocd-retained-source-member-set-v1" or not isinstance(members, list) or len(members) != profile["members"]:
        raise PipelineError("engwebpb retained member inventory differs")
    result: list[tuple[str, list[str]]] = []
    for position, member in enumerate(members, 1):
        relative = member.get("path") if isinstance(member, dict) else None
        if (
            not isinstance(member, dict) or member.get("position") != position or not isinstance(relative, str)
            or not profile["member_pattern"].fullmatch(relative)
            or not isinstance(member.get("bytes"), int)
            or not re.fullmatch(r"[0-9a-f]{64}", str(member.get("sha256", "")))
        ):
            raise PipelineError(f"engwebpb retained member {position} differs")
        content = io_path(ROOT / relative).read_bytes()
        if len(content) != member["bytes"] or _hash_bytes(content) != member["sha256"]:
            raise PipelineError(f"engwebpb retained source member {position} differs")
        result.append((Path(relative).name, content.decode("utf-8-sig").splitlines()))
    if sum(len(lines) for _name, lines in result) != profile["lines"]:
        raise PipelineError("engwebpb retained source line count differs")
    return result



def _read(path: Path) -> tuple[ET.Element, bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read Bible TEI {path}: {exc}") from exc
    if any(token in raw.lower() for token in (b"<!doctype", b"<!entity", b"<!--")):
        raise UnsupportedStructure("unsupported-visible: declaration, entity, or comment")
    if re.search(rb"<\?(?!xml\b)", raw, re.IGNORECASE):
        raise UnsupportedStructure("unsupported-visible: processing instruction")

    class NoExternal(ET.TreeBuilder):
        def doctype(self, name: str, pubid: str, system: str) -> None:
            raise UnsupportedStructure("unsupported-visible: DTD or entity declaration")

        def comment(self, text: str) -> None:
            raise UnsupportedStructure("unsupported-visible: XML comment")

        def pi(self, target: str, text: str) -> None:
            raise UnsupportedStructure("unsupported-visible: processing instruction")

    try:
        root = ET.fromstring(raw, parser=ET.XMLParser(target=NoExternal()))
    except ET.ParseError as exc:
        raise PipelineError(f"invalid Bible TEI: {exc}") from exc
    if root.tag not in {f"{{{TEI_NS}}}TEI", f"{{{TEI_NS}}}teiCorpus"}:
        raise PipelineError("Bible projection requires a TEI P5 TEI or teiCorpus root")
    if any(not isinstance(node.tag, str) or not node.tag.startswith(f"{{{TEI_NS}}}") for node in root.iter()):
        raise UnsupportedStructure("unsupported-visible: non-TEI element")
    return root, raw


def _paths(root: ET.Element) -> dict[ET.Element, str]:
    paths: dict[ET.Element, str] = {root: f"/{_local(root.tag)}[1]"}
    for parent in root.iter():
        counts: dict[str, int] = {}
        for child in list(parent):
            kind = _local(child.tag)
            counts[kind] = counts.get(kind, 0) + 1
            paths[child] = f"{paths[parent]}/{kind}[{counts[kind]}]"
    return paths


def _parents(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in list(parent)}


def _body_nodes(root: ET.Element) -> list[ET.Element]:
    documents = [root] if _local(root.tag) == "TEI" else [
        child for child in list(root) if _local(child.tag) == "TEI"
    ]
    bodies: list[ET.Element] = []
    for document in documents:
        text = next((child for child in list(document) if _local(child.tag) == "text"), None)
        if text is not None:
            bodies.extend(child for child in list(text) if _local(child.tag) == "body")
    return bodies


def _ancestors(node: ET.Element, parents: Mapping[ET.Element, ET.Element]) -> list[ET.Element]:
    result: list[ET.Element] = []
    current = parents.get(node)
    while current is not None:
        result.insert(0, current)
        current = parents.get(current)
    return result


def _is_zip_package_url(value: str) -> bool:
    return urlparse(value).path.casefold().endswith(".zip")


def _header(root: ET.Element) -> dict[str, Any]:
    common_header = next(
        (child for child in list(root) if _local(child.tag) == "teiHeader"), None
    )
    if common_header is None:
        raise PipelineError("Bible TEI has no document header")
    descriptions = [node for node in common_header.iter() if _local(node.tag) == "sourceDesc"]
    if len(descriptions) != 1:
        raise PipelineError("Bible TEI must contain one sourceDesc")
    source_desc = descriptions[0]
    header_parents = _parents(root)
    targets = [
        (node, (node.get("target") or "").strip())
        for node in source_desc.iter()
        if (node.get("target") or "").strip()
    ]
    if _local(root.tag) == "teiCorpus":
        source_kind = next((
            _norm("".join(node.itertext()))
            for node in source_desc.iter()
            if _local(node.tag) == "idno"
            and (node.get("type") or "").strip().lower().replace("ocd-", "") == "source_kind"
        ), None)
        source_refs = [
            value for node, value in targets
            if _local(node.tag) == "ref"
            and not any(
                _local(ancestor.tag) == "bibl"
                and (ancestor.get("type") or "") == "ocd-acceptance-binding"
                for ancestor in _ancestors(node, header_parents)
            )
        ]
        package_ptrs = [
            value for node, value in targets
            if _local(node.tag) == "ptr"
            and any(
                _local(ancestor.tag) == "bibl"
                and (ancestor.get("type") or "") == "ocd-acceptance-binding"
                for ancestor in _ancestors(node, header_parents)
            )
        ]
        all_ptrs = [value for node, value in targets if _local(node.tag) == "ptr"]
        unscoped_ptrs = [
            value for node, value in targets
            if _local(node.tag) == "ptr"
            and not any(
                _local(ancestor.tag) == "bibl"
                and (ancestor.get("type") or "") == "ocd-acceptance-binding"
                for ancestor in _ancestors(node, header_parents)
            )
        ]
        if source_kind == "retained-member-set":
            if source_refs:
                if len(source_refs) != 1 or len(package_ptrs) != 1 or unscoped_ptrs:
                    raise UnsupportedStructure(
                        "unsupported-visible: retained member set requires one provider ref and one bound package ptr"
                    )
                if _is_zip_package_url(source_refs[0]):
                    raise UnsupportedStructure("unsupported-visible: provider ref points to a ZIP package")
                source_url = source_refs[0]
                package_url = package_ptrs[0]
            elif len(targets) == 1 and len(package_ptrs) == 1:
                package_url = package_ptrs[0]
                source_url = None if _is_zip_package_url(package_url) else package_url
            else:
                raise UnsupportedStructure(
                    "unsupported-visible: retained member set requires one provider ref or one package ptr"
                )
        elif source_refs:
            if len(source_refs) != 1:
                raise UnsupportedStructure("unsupported-visible: Bible sourceDesc requires one provider source ref")
            if _is_zip_package_url(source_refs[0]):
                raise UnsupportedStructure("unsupported-visible: provider ref points to a ZIP package")
            if unscoped_ptrs:
                raise UnsupportedStructure("unsupported-visible: Bible sourceDesc has an unbound source ptr")
            source_url = source_refs[0]
            if len(package_ptrs) > 1:
                raise UnsupportedStructure("unsupported-visible: Bible acceptance binding requires one package ptr")
            package_url = package_ptrs[0] if package_ptrs else None
        elif len(all_ptrs) == 1:
            package_url = all_ptrs[0]
            source_url = None if _is_zip_package_url(package_url) else package_url
        else:
            raise PipelineError("Bible TEI sourceDesc must identify one source page")
    else:
        source_kind = next((
            _norm("".join(node.itertext()))
            for node in source_desc.iter()
            if _local(node.tag) == "idno"
            and (node.get("type") or "").strip().lower().replace("ocd-", "") == "source_kind"
        ), None)
        if source_kind == "retained-member-set":
            source_refs = [
                value for node, value in targets
                if _local(node.tag) == "ref"
                and not any(
                    _local(ancestor.tag) == "bibl"
                    and (ancestor.get("type") or "") == "ocd-acceptance-binding"
                    for ancestor in _ancestors(node, header_parents)
                )
            ]
            package_ptrs = [
                value for node, value in targets
                if _local(node.tag) == "ptr"
            ]
            if source_refs:
                if len(targets) != 2 or len(source_refs) != 1 or len(package_ptrs) != 1:
                    raise UnsupportedStructure(
                        "unsupported-visible: retained member set requires one provider ref and one package ptr"
                    )
                if _is_zip_package_url(source_refs[0]):
                    raise UnsupportedStructure("unsupported-visible: provider ref points to a ZIP package")
                source_url = source_refs[0]
                package_url = package_ptrs[0]
            elif len(targets) == 1 and len(package_ptrs) == 1:
                package_url = package_ptrs[0]
                source_url = None if _is_zip_package_url(package_url) else package_url
            else:
                raise UnsupportedStructure(
                    "unsupported-visible: retained member set requires one provider ref or one package ptr"
                )
        else:
            pointers = [value for _, value in targets]
            if not pointers:
                raise PipelineError("Bible TEI sourceDesc must contain a source ptr")
            if len(pointers) != 1:
                raise UnsupportedStructure("unsupported-visible: Bible sourceDesc requires one source ptr")
            package_url = pointers[0]
            source_url = None if _is_zip_package_url(package_url) else package_url
    ids: dict[str, str] = {}
    for node in source_desc.iter():
        if _local(node.tag) != "idno":
            continue
        kind = (node.get("type") or "").strip().lower().replace("ocd-", "")
        value = _norm("".join(node.itertext()))
        if not value:
            continue
        binding_key = "retained_sha256" if kind in {"sha256", "retained_sha256", "archive_sha256"} else "source_sha256" if kind in {"source_sha256", "origin_sha256"} else "versification" if kind == "bible_versification" else kind
        if binding_key in ids:
            raise UnsupportedStructure(f"unsupported-visible: duplicate source binding {binding_key}")
        if kind in {"sha256", "retained_sha256", "archive_sha256"}:
            ids["retained_sha256"] = _valid_hash(value, field="retained source sha256")
        elif kind in {"source_sha256", "origin_sha256"}:
            ids["source_sha256"] = _valid_hash(value, field="source sha256")
        elif kind in {"work_id", "textual_form_id", "edition_id", "acquisition_id", "representation_revision", "versification", "bible_versification", "bible_native_chapter_policy", "source_kind", "source_bytes"}:
            ids[binding_key] = value
    if "bible_native_chapter_policy" in ids and (
        ids["bible_native_chapter_policy"] != _NATIVE_ZERO_POLICY
        or ids.get("versification") != _NATIVE_ZERO_VERSIFICATION
    ):
        raise UnsupportedStructure("unsupported-visible: invalid native chapter policy")
    if "retained_sha256" not in ids:
        raise PipelineError("Bible TEI sourceDesc must bind retained source sha256")
    return {
        "source_url": source_url,
        "package_url": package_url,
        "source_location": next(
            ((node.text or "").strip() for node in source_desc.iter()
             if _local(node.tag) == "note" and node.get("type") == "source-location"),
            None,
        ),
        "retained_sha256": ids["retained_sha256"],
        "source_sha256": ids.get("source_sha256"),
        "ids": ids,
    }


def _source_marker(node: ET.Element) -> str | None:
    raw_notes = [
        "".join(child.itertext()).strip()
        for child in list(node)
        if _local(child.tag) == "note" and child.get("type") == "source-usfm-raw"
    ]
    if len(raw_notes) != 1:
        return None
    match = re.match(r"^\\{1,2}([A-Za-z][A-Za-z0-9]*)(?=\s|$)", raw_notes[0])
    return match.group(1) if match else None


def _corpus_marker_matches(node: ET.Element) -> bool:
    expected = _CORPUS_MARKERS.get(node.get("type") or "")
    marker = _source_marker(node)
    return bool(
        expected
        and marker in expected
        and (node.get("n") is None or node.get("n") == marker)
    )


def _inside_note(node: ET.Element, parents: Mapping[ET.Element, ET.Element]) -> bool:
    return any(_local(ancestor.tag) == "note" for ancestor in _ancestors(node, parents))


def _has_visible_source_text(node: ET.Element) -> bool:
    if _local(node.tag) == "note" and node.get("type") == "source-usfm-raw":
        return False
    if _norm(node.text or ""):
        return True
    return any(_has_visible_source_text(child) or _norm(child.tail or "") for child in list(node))


def _validate_elements(root: ET.Element, paths: Mapping[ET.Element, str]) -> None:
    root_kind = _local(root.tag)
    if root_kind == "TEI":
        documents = [root]
    elif root_kind == "teiCorpus":
        children = list(root)
        if (
            not children
            or _local(children[0].tag) != "teiHeader"
            or len(children) < 2
            or any(_local(child.tag) != "TEI" for child in children[1:])
        ):
            raise UnsupportedStructure("unsupported-visible: teiCorpus requires one header followed by TEI documents")
        documents = children[1:]
    else:
        raise UnsupportedStructure("unsupported-visible: TEI P5 TEI or teiCorpus root required")
    for document in documents:
        if [_local(child.tag) for child in list(document)] != ["teiHeader", "text"]:
            raise UnsupportedStructure("unsupported-visible: TEI document requires teiHeader then text")
        text = next((child for child in list(document) if _local(child.tag) == "text"), None)
        if text is None:
            raise UnsupportedStructure("unsupported-visible: Bible TEI has no text")
        if any(_local(child.tag) not in _TEXT_PARTS for child in list(text)):
            raise UnsupportedStructure("unsupported-visible: text requires front/body/back parts")
        if sum(_local(child.tag) == "body" for child in list(text)) != 1:
            raise UnsupportedStructure("unsupported-visible: Bible TEI requires one body")
    seen_ids: set[str] = set()
    parents = _parents(root)
    for node in root.iter():
        kind = _local(node.tag)
        if node.get(XML_ID):
            if node.get(XML_ID) in seen_ids:
                raise UnsupportedStructure(f"unsupported-visible: duplicate xml:id at {paths[node]}")
            seen_ids.add(node.get(XML_ID, ""))
        if any(key.startswith("{") and not key.startswith(f"{{{XML_NS}}}") for key in node.attrib):
            raise UnsupportedStructure(f"unsupported-visible: attribute namespace at {paths[node]}")
        attrs = {"xml:" + _local(key) if key.startswith(f"{{{XML_NS}}}") else key for key in node.attrib}
        if kind == "teiCorpus":
            if node is not root:
                raise UnsupportedStructure(f"unsupported-visible: nested teiCorpus at {paths[node]}")
            if _norm(node.text or "") or any(_norm(child.tail or "") for child in list(node)):
                raise UnsupportedStructure(f"unsupported-visible: loose text in teiCorpus at {paths[node]}")
            unknown = attrs - {"xml:id", "xml:lang"}
            if unknown:
                raise UnsupportedStructure(f"unsupported-visible: teiCorpus/@{sorted(unknown)[0]} at {paths[node]}")
            continue
        if kind == "TEI":
            if root_kind == "teiCorpus" and parents.get(node) is not root:
                raise UnsupportedStructure(f"unsupported-visible: nested TEI document at {paths[node]}")
            if _norm(node.text or "") or any(_norm(child.tail or "") for child in list(node)):
                raise UnsupportedStructure(f"unsupported-visible: loose text in TEI at {paths[node]}")
            if (
                root_kind == "teiCorpus"
                and root.get(f"{{{XML_NS}}}lang")
                and node.get(f"{{{XML_NS}}}lang")
                and root.get(f"{{{XML_NS}}}lang") != node.get(f"{{{XML_NS}}}lang")
            ):
                raise UnsupportedStructure(f"unsupported-visible: conflicting TEI document language at {paths[node]}")
            allowed_tei_attrs = _ATTRS["TEI"]
            if node is root:
                allowed_tei_attrs = allowed_tei_attrs | {"xml:lang"}
            if node is root and node.get("ana") == "#retained-source-representation":
                allowed_tei_attrs = allowed_tei_attrs | {"ana"}
            if root_kind == "teiCorpus" and parents.get(node) is root:
                allowed_tei_attrs = allowed_tei_attrs | {"xml:lang"}
            unknown = attrs - allowed_tei_attrs
            if unknown:
                raise UnsupportedStructure(f"unsupported-visible: TEI/@{sorted(unknown)[0]} at {paths[node]}")
            continue
        if kind == "teiHeader" or any(_local(ancestor.tag) == "teiHeader" for ancestor in _ancestors(node, parents)):
            allowed_header = _HEADER_ATTRS.get(kind, _ATTRS.get(kind) if kind in {"p", "hi", "foreign", "ref"} else None)
            if allowed_header is None or attrs - allowed_header:
                raise UnsupportedStructure(f"unsupported-visible: header element or attribute at {paths[node]}")
            if kind == "ref" and "target" in node.attrib and "cRef" in node.attrib:
                raise UnsupportedStructure(f"unsupported-visible: conflicting reference targets at {paths[node]}")
            continue
        if kind == "ref" and "target" in node.attrib and "cRef" in node.attrib:
            raise UnsupportedStructure(f"unsupported-visible: conflicting reference targets at {paths[node]}")
        if kind not in _ALLOWED_VISIBLE:
            raise UnsupportedStructure(f"unsupported-visible: {kind} at {paths[node]}")
        if root_kind == "teiCorpus" and kind == "ab" and node.get("type") == "introduction-paragraph" and not _corpus_marker_matches(node):
            raise UnsupportedStructure(f"unsupported-visible: source introduction marker mismatch at {paths[node]}")
        if kind == "title" and any(
            _explicit_verse(ancestor)
            or _implicit_verse(ancestor, parents, strict_types=root_kind == "teiCorpus")
            for ancestor in _ancestors(node, parents)
        ):
            raise UnsupportedStructure(f"unsupported-visible: title inside verse carrier at {paths[node]}")
        if "ana" in attrs and (
            root_kind != "teiCorpus"
            or kind not in {"div", "ab"}
            or not any(_local(ancestor.tag) == "body" for ancestor in _ancestors(node, parents))
            or not re.fullmatch(r"#[A-Za-z0-9_.-]+", node.get("ana", ""))
        ):
            raise UnsupportedStructure(f"unsupported-visible: {kind}/@ana at {paths[node]}")
        if root_kind == "teiCorpus" and kind in {"p", "ab", "seg"} and _nearest(
            node, parents, {"div", "chapter"}, type_value="chapter"
        ) is not None and not _inside_note(node, parents):
            ancestors = _ancestors(node, parents)
            in_verse = any(
                ancestor is not node
                and (_local(ancestor.tag) == "verse" or _local(ancestor.tag) == "div" and ancestor.get("type") == "verse"
                     or _local(ancestor.tag) in {"p", "ab", "seg"} and ancestor.get("type") == "verse")
                for ancestor in ancestors
            )
            inline_continuation = (
                kind == "seg" and node.get("type") == "usfm-qs" and not node.get("n")
                and any(_local(ancestor.tag) in {"p", "ab", "seg"}
                        and ancestor.get("type") in _CORPUS_CONTINUATIONS for ancestor in ancestors)
            )
            has_numeric_label = any(
                re.fullmatch(r"[1-9][0-9]*", node.get(key, ""))
                for key in ("n", "verse", "number")
            )
            is_verse = (
                _local(node.tag) == "verse"
                or _local(node.tag) == "div" and node.get("type") == "verse"
                or _local(node.tag) in {"p", "ab", "seg"}
                and (node.get("type") == "verse" or node.get("type") is None and has_numeric_label)
            )
            if not in_verse and not is_verse and not inline_continuation and not _corpus_marker_matches(node) and (
                _has_visible_source_text(node)
                or any(node.get(key) for key in ("n", "verse", "number"))
                or any(_local(child.tag) == "note" and child.get("type") == "source-usfm-raw" for child in list(node))
            ):
                raise UnsupportedStructure(f"unsupported-visible: unclassified typed verse carrier at {paths[node]}")
        allowed = _ATTRS.get(kind, set())
        unknown = attrs - allowed
        if unknown:
            raise UnsupportedStructure(f"unsupported-visible: {kind}/@{sorted(unknown)[0]} at {paths[node]}")
        if kind == "ab" and node.get(XML_SPACE) not in {None, "preserve"}:
            raise UnsupportedStructure(f"unsupported-visible: ab/@xml:space at {paths[node]}")
        if kind == "note" and node.get("place") not in {None, "foot", "end", "unspecified"}:
            raise UnsupportedStructure(f"unsupported-visible: note/@place at {paths[node]}")
        if kind == "lb" and node.get("break") not in {None, "yes", "no"}:
            raise UnsupportedStructure(f"unsupported-visible: lb/@break at {paths[node]}")
        if kind in {"text", "front", "body", "back", "div", "chapter"}:
            if _norm(node.text or "") or any(_norm(child.tail or "") for child in list(node)):
                raise UnsupportedStructure(f"unsupported-visible: loose text in {kind} at {paths[node]}")
def _engwebpb_validate(
    root: ET.Element, paths: Mapping[ET.Element, str], parents: Mapping[ET.Element, ET.Element],
    members: Sequence[tuple[str, Sequence[str]]], profile: Mapping[str, Any] | None = None,
) -> None:
    """Validate the exact retained single-TEI USFM shape and every source pointer."""
    if profile is None:
        profile = _RETAINED_USFM_PROFILES["engwebpb"]
    catholic = profile is not None and profile["slug"] == "eng-web-c"
    if root.tag != f"{{{TEI_NS}}}TEI" or [_local(child.tag) for child in root] != ["teiHeader", "text"]:
        raise UnsupportedStructure("unsupported-visible: engwebpb requires one TEI header and text")
    text = root[1]
    if [_local(child.tag) for child in text] != ["body"]:
        raise UnsupportedStructure("unsupported-visible: engwebpb requires one body")
    if any(_norm(value or "") for value in (root.text, root[0].tail, text.text, text.tail, text[0].text, text[0].tail)):
        raise UnsupportedStructure("unsupported-visible: engwebpb loose body text")
    header_only = ET.Element(root.tag, root.attrib)
    header_only.append(copy.deepcopy(root[0]))
    copied_text = ET.SubElement(header_only, f"{{{TEI_NS}}}text", text.attrib)
    ET.SubElement(copied_text, f"{{{TEI_NS}}}body")
    _validate_elements(header_only, _paths(header_only))
    body = text[0]
    sections = list(body)
    if len(sections) != len(members):
        raise UnsupportedStructure("unsupported-visible: engwebpb source division count differs")
    if any(_norm(section.tail or "") for section in sections):
        raise UnsupportedStructure("unsupported-visible: engwebpb loose member text")
    line_markers: set[tuple[str, int]] = set()
    spans = 0
    counts: dict[str, int] = {}
    head_types = {"usfm-h", "usfm-is1", "usfm-ms1", "usfm-mt1", "usfm-mt2", "usfm-mt3", "usfm-toc1", "usfm-toc2", "usfm-toc3"} | ({"usfm-s1"} if catholic else set())
    for ordinal, (section, (filename, lines)) in enumerate(zip(sections, members, strict=True), 1):
        expected_line = 1
        marker = profile["filename_pattern"].fullmatch(filename)
        code = marker.group(1) if marker else ""
        section_type = "front" if code == "FRT" else "back" if code == "GLO" else "book"
        if (
            section.tag != f"{{{TEI_NS}}}div" or section.get("type") != section_type
            or section.get("n") != code or section.get(XML_ID) != f"{profile['slug']}-{code}"
        ):
            raise UnsupportedStructure(f"unsupported-visible: engwebpb member division {ordinal} differs")
        for node in section.iter():
            kind = _local(node.tag)
            parent = parents.get(node)
            parent_kind = _local(parent.tag) if parent is not None else ""
            parent_type = parent.get("type") if parent is not None else None
            typ = node.get("type")
            attrs = set(_attributes(node))
            allowed: set[str]
            if kind == "div":
                allowed = {"type", "n", "xml:id"} if node is section else {"type", "n", "corresp"} if typ == "chapter" else {"type", "n"}
                valid = (
                    node is section or parent_kind == "div" and (
                        parent_type == "book" and typ in {"chapter", "usfm-heading", "usfm-line"}
                        or parent_type in {"front", "back"} and typ in {"usfm-heading", "usfm-line"}
                        or catholic and parent_type == "chapter" and parent.get("n") == "3" and section.get("n") == "DAG" and typ == "usfm-section"
                    )
                )
                valid = valid and bool(node.get("n")) and typ in ({"front", "back", "book", "chapter", "usfm-heading", "usfm-line"} | ({"usfm-section"} if catholic else set()))
                if typ == "chapter":
                    valid = valid and bool(re.fullmatch(r"[1-9][0-9]*", node.get("n", "")))
                if _norm(node.text or "") or any(_norm(child.tail or "") for child in node):
                    valid = False
            elif kind == "p":
                allowed = set()
                valid = parent_kind == "div" and parent_type in ({"chapter", "usfm-line"} | ({"usfm-section"} if catholic else set())) and len(node) == 1 and _local(node[0].tag) == "seg"
                valid = valid and not _norm(node.text or "") and not _norm(node[0].tail or "")
            elif kind == "ab":
                allowed = {"type", "n", "corresp", "xml:space"}
                valid = parent_kind == "div" and parent_type in ({"chapter"} | ({"usfm-section"} if catholic else set())) and typ == "verse" and node.get(XML_SPACE) == "preserve" and (bool(re.fullmatch(r"[1-9][0-9]*", node.get("n", ""))) or catholic and (node.get("corresp"), node.get("n")) in {("source-usfm:eng-web-c/46-SIReng-web-c.usfm#line=972", "15-16"), ("source-usfm:eng-web-c/46-SIReng-web-c.usfm#line=1396", "15-16"), ("source-usfm:eng-web-c/46-SIReng-web-c.usfm#line=1691", "18-19"), ("source-usfm:eng-web-c/46-SIReng-web-c.usfm#line=1951", "9-10"), ("source-usfm:eng-web-c/46-SIReng-web-c.usfm#line=2394", "19-27")})
            elif kind == "seg":
                allowed = {"type"} if typ == "usfm-c-content" else {"type", "corresp"}
                valid = (
                    parent_kind == "p" and typ in (_ENGWEBPB_CONTINUATIONS | ({"usfm-q3", "usfm-pc"} if catholic else set())) | _ENGWEBPB_NONVERSE | _ENGWEBPB_EMPTY_MARKERS
                    or parent_kind == "note" and parent_type == "footnote" and typ in {"footnote-text", "alternate-reading", "quoted-reading"}
                    or parent_kind == "seg" and parent_type in {"usfm-q1", "usfm-q2"} and typ == "selah"
                    or parent_kind == "ab" and parent_type == "verse" and typ == "selah"
                )
                if typ in _ENGWEBPB_EMPTY_MARKERS and _norm("".join(node.itertext())):
                    valid = False
            elif kind == "w":
                allowed = {"n", "corresp"} | ({"type"} if typ == "usfm-plus-w" else set())
                valid = (
                    typ in {None, "usfm-plus-w"}
                    and (parent_kind == "ab" and parent_type == "verse"
                         or parent_kind == "seg" and parent_type in ({"usfm-q1", "usfm-q2", "usfm-p", "usfm-m", "usfm-pi1", "usfm-mi", "usfm-d", "selah"} | ({"usfm-q3", "usfm-pc"} if catholic else set()))
                         or parent_kind == "q" and parent_type == "words-of-Jesus"
                         or parent_kind == "title" and parent_type == "biblical-book")
                    and bool(re.fullmatch(r"[HG][0-9]+(?:[ ,;/]+[HG][0-9]+)*", node.get("n", "")))
                    and bool("".join(node.itertext()).strip()) and not list(node)
                )
            elif kind == "milestone":
                allowed = {"unit", "corresp"}
                valid = parent_kind == "div" and parent_type in ({"chapter"} | ({"usfm-section"} if catholic else set())) and node.get("unit") == "paragraph" and not list(node) and not _norm(node.text or "")
            elif kind == "head":
                allowed = {"type", "corresp"}
                valid = typ in head_types and parent_kind == "div" and (parent_type == "usfm-heading" or parent_type == "chapter" and typ in ({"usfm-ms1"} | ({"usfm-s1"} if catholic else set())) or catholic and parent_type == "usfm-section" and typ == "usfm-s1") and (not list(node) or catholic and typ == "usfm-s1" and all(_local(c.tag) == "note" and c.get("type") == "footnote" for c in node))
            elif kind == "q":
                allowed = {"type", "corresp"}
                valid = typ == "words-of-Jesus" and (parent_kind == "ab" and parent_type == "verse" or parent_kind == "seg" and parent_type in {"usfm-q1", "usfm-q2", "usfm-p"})
            elif kind == "note":
                allowed = {"type", "corresp"}
                valid = typ in {"footnote", "cross-reference"} and (parent_kind == "ab" and parent_type == "verse" or parent_kind == "seg" and parent_type in ({"usfm-q1", "usfm-q2", "usfm-p", "usfm-d", "usfm-ip"} | ({"usfm-q3", "usfm-pc"} if catholic else set())) or catholic and parent_kind == "head" and parent_type == "usfm-s1" and typ == "footnote")
            elif kind == "label":
                allowed = {"type", "corresp"} if catholic and typ == "footnote-label" else {"type"}
                valid = typ in ({"caller"} | ({"footnote-label"} if catholic else set())) and parent_kind == "note" and parent_type in {"footnote", "cross-reference"} and not list(node)
            elif kind == "ref":
                allowed = {"type", "corresp"}
                valid = parent_kind == "note" and (parent_type == "footnote" and typ == "source-label" or parent_type == "cross-reference" and typ in {"source-origin", "source-target"}) and not list(node)
            elif kind == "foreign":
                allowed = {"xml:lang", "corresp"}
                valid = parent_kind == "note" and parent_type == "footnote" and node.get(f"{{{XML_NS}}}lang") == "he" and not list(node)
            elif kind == "term":
                allowed = {"corresp"}
                valid = parent_kind == "seg" and parent_type == "usfm-ili" and not list(node)
            elif kind == "title":
                allowed = {"type", "corresp"}
                valid = typ == "biblical-book" and (parent_kind == "seg" and parent_type == "usfm-ip" or parent_kind == "ab" and parent_type == "verse" or catholic and parent_kind == "note" and parent_type == "footnote")
            else:
                raise UnsupportedStructure(f"unsupported-visible: engwebpb {kind} at {paths[node]}")
            if not valid or attrs != allowed:
                raise UnsupportedStructure(f"unsupported-visible: engwebpb {kind} shape at {paths[node]}")
            raw_pointer = node.get("corresp")
            if raw_pointer is not None:
                match = profile["corresp_pattern"].fullmatch(raw_pointer)
                if match is None or match.group(1) != filename:
                    raise UnsupportedStructure(f"unsupported-visible: engwebpb source pointer at {paths[node]}")
                line = int(match.group(2))
                if line > len(lines):
                    raise UnsupportedStructure(f"unsupported-visible: engwebpb source line at {paths[node]}")
                if catholic and kind == "ab":
                    source_label = re.match(r"\\v\s+(\S+)(?:\s|$)", lines[line - 1])
                    if source_label is None or source_label.group(1) != node.get("n"):
                        raise UnsupportedStructure("unsupported-visible: Catholic verse label differs from retained source")
                if kind == "ab" and _engwebpb_blank_note_only(node) and re.match(r"\\v\s+" + re.escape(node.get("n", "")) + r"\s+\\f\b", lines[line - 1]) is None:
                    raise UnsupportedStructure(f"unsupported-visible: engwebpb blank verse source line at {paths[node]}")
                start, end = match.group(3), match.group(4)
                needs_span = catholic and kind == "label" and typ == "footnote-label" or kind in {"w", "q", "ref", "note", "foreign", "term", "title"} or kind == "seg" and typ in {"footnote-text", "alternate-reading", "quoted-reading", "selah"}
                if (start is not None) != needs_span:
                    raise UnsupportedStructure(f"unsupported-visible: engwebpb source span shape at {paths[node]}")
                if start is None:
                    key = (filename, line)
                    if key in line_markers or line != expected_line:
                        raise UnsupportedStructure(f"unsupported-visible: engwebpb source line order at {paths[node]}")
                    line_markers.add(key)
                    expected_line += 1
                else:
                    if int(start) >= int(end) or int(end) > len(lines[line - 1]):
                        raise UnsupportedStructure(f"unsupported-visible: engwebpb source span bounds at {paths[node]}")
                    source_parent = parents.get(node)
                    while source_parent is not None and not profile["line_pattern"].fullmatch(source_parent.get("corresp", "")):
                        source_parent = parents.get(source_parent)
                    if source_parent is None or int(source_parent.get("corresp", "").rsplit("=", 1)[-1]) != line:
                        raise UnsupportedStructure(f"unsupported-visible: engwebpb source span line at {paths[node]}")
                    spans += 1
            counts[kind] = counts.get(kind, 0) + 1
        if expected_line != len(lines) + 1:
            raise UnsupportedStructure(f"unsupported-visible: engwebpb source line coverage differs for {filename}")
    if catholic:
        observed = [n.get("n") for n in root.iter() if n.get("type") == "usfm-section"]
        if observed != ["pre-heading", "s1-156", "s1-228"]:
            raise UnsupportedStructure("unsupported-visible: Catholic DAG3 flow sections differ")
    if len(line_markers) != profile["lines"] or spans != profile["spans"] or counts.get("ab") != profile["verses"] or counts.get("w") != profile["words"] or counts.get("note") != profile["notes"]:
        raise UnsupportedStructure("unsupported-visible: engwebpb complete source carrier accounting differs")





def _engwebpb_continuations(
    body: ET.Element, candidates: Sequence[ET.Element], parents: Mapping[ET.Element, ET.Element],
    paths: Mapping[ET.Element, str], profile: Mapping[str, Any] | None = None,
) -> dict[ET.Element, list[ET.Element]]:
    if profile is None:
        profile = _RETAINED_USFM_PROFILES["engwebpb"]
    catholic = profile["slug"] == "eng-web-c"
    selected = set(candidates)
    previous: dict[ET.Element, ET.Element] = {}
    result: dict[ET.Element, list[ET.Element]] = {}
    for node in body.iter():
        chapter = _nearest(node, parents, {"div"}, type_value="chapter")
        if chapter is None:
            continue
        if node in selected:
            previous[chapter] = node
        if _local(node.tag) != "p" or len(node) != 1 or node[0].get("type") not in (_ENGWEBPB_CONTINUATIONS | ({"usfm-q3", "usfm-pc"} if catholic else set())):
            continue
        segment = node[0]
        if any(child in selected for child in segment.iter()):
            raise UnsupportedStructure(f"unsupported-visible: engwebpb continuation contains a verse at {paths[segment]}")
        if not _has_visible_source_text(segment):
            continue
        verse = previous.get(chapter)
        if verse is None:
            if catholic and chapter.get("n") == "51" and segment.get("corresp") == "source-usfm:eng-web-c/46-SIReng-web-c.usfm#line=4780" and segment.get("type") == "usfm-p" and not list(segment) and segment.text == "A Prayer of Jesus the son of Sirach.  ":
                continue
            raise UnsupportedStructure(f"unsupported-visible: engwebpb continuation has no preceding verse at {paths[segment]}")
        result.setdefault(verse, []).append(segment)
    return result



def _engwebpb_blank_note_only(node: ET.Element) -> bool:
    children = list(node)
    return (bool(children) and all(_local(child.tag) == "note" for child in children)
            and not (node.text or "").strip() and all(not (child.tail or "").strip() for child in children))


def _engwebpb_account(
    body: ET.Element, selected: Sequence[ET.Element], continuations: Mapping[ET.Element, Sequence[ET.Element]],
    paths: Mapping[ET.Element, str], parents: Mapping[ET.Element, ET.Element], profile: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    if profile is None:
        profile = _RETAINED_USFM_PROFILES["engwebpb"]
    row_roots = set(selected) | {block for blocks in continuations.values() for block in blocks}
    inventory: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    for section in body:
        counts: dict[str, int] = {}
        retained: dict[str, int] = {}
        for node in section.iter():
            name = _local(node.tag)
            counts[name] = counts.get(name, 0) + 1
            if name == "note" and node not in row_roots and not any(
                ancestor in row_roots for ancestor in _ancestors(node, parents)
            ):
                retained["note"] = retained.get("note", 0) + 1
        inventory.append({"tei_path": paths[section], "disposition": "source-member-retained-only" if section.get("type") in {"front", "back"} else "source-member-retained-and-verse-projected", "attributes": _attributes(section), "element_counts": dict(sorted(counts.items())), "retained_only_counts": dict(sorted(retained.items()))})
    if sum(item["retained_only_counts"].get("note", 0) for item in inventory) != profile["retained_notes"]:
        raise UnsupportedStructure("unsupported-visible: engwebpb retained-only note accounting differs")
    warnings.append({"tei_path": paths[body], "reason": profile["warning"]})
    return inventory, [], warnings



def _render(node: ET.Element, paths: Mapping[ET.Element, str], *, omit_notes: bool = True, policy: Mapping[str, Any] | None = None) -> str:
    try:
        if policy is None:
            policy = json.loads(COMMON_SCHEMA_PATH.read_text(encoding="utf-8"))["x-ocd-projection-policy"]
        script_maps = policy["script"]["maps"]
        script_styles = set(policy["script"]["styles"])
        safe_punctuation = set(policy["script"]["safe_punctuation"])
        allow_whitespace = bool(policy["script"]["allow_whitespace"])
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PipelineError("cannot load controlled script rendering policy") from exc
    sentinel = "\x00"

    def visit(current: ET.Element, style: str | None = None) -> str:
        kind = _local(current.tag)
        current_style = style
        if kind == "hi" and current.get("rend") in script_styles:
            if style is not None:
                raise UnsupportedStructure(f"unsupported-visible: nested script styles at {paths[current]}")
            current_style = current.get("rend")
        value = current.text or ""
        if kind == "seg" and current.get("type") == "usfm-qs" and ("\\" in value or "|" in value):
            match = re.fullmatch(r'(\s*)\\\+w\s+([^\\|]+)\|strong="[HG][0-9]+"\\\+w\*(\s*)', value)
            if match is None or not match.group(2).strip():
                raise UnsupportedStructure(f"unsupported-visible: unsupported USFM word annotation at {paths[current]}")
            value = "".join(match.groups())
        if current_style:
            mapping = script_maps[current_style]
            converted: list[str] = []
            for char in value:
                if char in mapping:
                    converted.append(mapping[char])
                elif char.isspace() and allow_whitespace or char in safe_punctuation:
                    converted.append(char)
                else:
                    raise UnsupportedStructure(f"unsupported-visible: unsupported {current_style} character {char!r} at {paths[current]}")
            value = "".join(converted)
        output = [value]
        for child in list(current):
            child_kind = _local(child.tag)
            if child_kind == "note" and omit_notes or child_kind in {"pb", "anchor", "ptr"}:
                output.append(" " if child_kind == "note" and omit_notes and child.get("corresp") in ('source-usfm:eng-web-c/43-ESGeng-web-c.usfm#line=16&span=133:169', 'source-usfm:eng-web-c/43-ESGeng-web-c.usfm#line=226&span=345:399') else sentinel)
            elif child_kind == "lb":
                output.append("" if child.get("break") == "no" else " ")
            else:
                output.append(visit(child, current_style))
            output.append(child.tail or "")
        return "".join(output)

    value = visit(node)
    for index, char in enumerate(value):
        if char == sentinel:
            before = value[index - 1] if index else ""
            after = value[index + 1] if index + 1 < len(value) else ""
            if before.isalnum() and after.isalnum():
                raise UnsupportedStructure(f"unsupported-visible: omitted inline element creates ambiguous text at {paths[node]}")
    visible = value.replace(sentinel, "")
    return visible if node.get(XML_SPACE) == "preserve" else _norm(visible)



def _nearest(node: ET.Element, parents: Mapping[ET.Element, ET.Element], names: set[str], *, type_value: str | None = None) -> ET.Element | None:
    current: ET.Element | None = node
    while current is not None:
        if _local(current.tag) in names and (type_value is None or current.get("type") == type_value):
            return current
        current = parents.get(current)
    return None


def _book(node: ET.Element, parents: Mapping[ET.Element, ET.Element], paths: Mapping[ET.Element, str]) -> tuple[str, str]:
    container = _nearest(node, parents, {"div"}, type_value="book")
    if container is None:
        raise UnsupportedStructure(f"unsupported-visible: verse has no explicit book container at {paths[node]}")
    book = next((container.get(key, "").strip() for key in ("book", "book_name", "n") if container.get(key)), "")
    if not book:
        head = next((child for child in list(container) if _local(child.tag) == "head"), None)
        book = _norm("".join(head.itertext())) if head is not None else ""
    explicit = next((container.get(key, "").strip() for key in ("book_osis", "osis", "osisID") if container.get(key)), "")
    # The source's XML ID is the explicit edition-local book identity when a
    # separate OSIS attribute is absent.  It is retained in the private
    # mapping policy rather than inferred from the English heading.
    osis = explicit or (container.get(XML_ID) or "").strip()
    if not book or not osis:
        raise UnsupportedStructure(f"unsupported-visible: verse has no explicit book name/identity at {paths[node]}")
    return book, osis


def _chapter(node: ET.Element, parents: Mapping[ET.Element, ET.Element], paths: Mapping[ET.Element, str], *, allow_native_zero: bool = False) -> int:
    container = _nearest(node, parents, {"div", "chapter"}, type_value="chapter")
    if container is None:
        raise UnsupportedStructure(f"unsupported-visible: verse has no explicit chapter at {paths[node]}")
    source_label = container.get("n") or container.get("chapter") or ""
    raw = source_label.strip()
    if source_label == "0" and allow_native_zero:
        return 0
    if not re.fullmatch(r"[1-9][0-9]*", raw):
        raise UnsupportedStructure(f"unsupported-visible: chapter number is not positive at {paths[container]}")
    return int(raw)


def _label(node: ET.Element, paths: Mapping[ET.Element, str]) -> tuple[int | str, str | None]:
    raw = (node.get("n") or node.get("verse") or node.get("number") or "").strip()
    if not raw:
        raise UnsupportedStructure(f"unsupported-visible: verse has no source label at {paths[node]}")
    if re.fullmatch(r"[1-9][0-9]*", raw):
        return int(raw), None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", raw):
        raise UnsupportedStructure(f"unsupported-visible: invalid verse label {raw!r} at {paths[node]}")
    return raw, raw


def _explicit_verse(node: ET.Element) -> bool:
    kind = _local(node.tag)
    return kind == "verse" or (kind == "div" and node.get("type") == "verse") or (kind in {"p", "ab", "seg"} and node.get("type") == "verse")


def _implicit_verse(node: ET.Element, parents: Mapping[ET.Element, ET.Element], *, strict_types: bool = False) -> bool:
    return (
        _local(node.tag) in {"p", "ab", "seg"}
        and (not strict_types or node.get("type") in {None, "verse"})
        and bool(node.get("n") or node.get("verse") or node.get("number"))
        and _nearest(node, parents, {"div", "chapter"}, type_value="chapter") is not None
    )


def _candidates(body: ET.Element, parents: Mapping[ET.Element, ET.Element], *, strict_types: bool = False) -> list[ET.Element]:
    all_candidates = [node for node in body.iter() if _explicit_verse(node) or _implicit_verse(node, parents, strict_types=strict_types)]
    candidates: list[ET.Element] = []
    candidate_set = set(all_candidates)
    for node in all_candidates:
        # ElementTree has no iterancestors; compare through the parent map.
        current = parents.get(node)
        nested = False
        while current is not None:
            if current in candidate_set:
                nested = True
                break
            current = parents.get(current)
        if not nested:
            candidates.append(node)
    return candidates


def _continuations(
    bodies: Sequence[ET.Element], candidates: Sequence[ET.Element],
    parents: Mapping[ET.Element, ET.Element], paths: Mapping[ET.Element, str],
) -> dict[ET.Element, list[ET.Element]]:
    candidate_set = set(candidates)
    attached: dict[ET.Element, list[ET.Element]] = {}
    for body in bodies:
        previous_by_chapter: dict[ET.Element, ET.Element] = {}
        for node in body.iter():
            chapter = _nearest(node, parents, {"div", "chapter"}, type_value="chapter")
            if chapter is None:
                continue
            if node in candidate_set:
                previous_by_chapter[chapter] = node
                continue
            if (
                _local(node.tag) not in {"p", "ab", "seg"}
                or node.get("type") not in _CORPUS_CONTINUATIONS
                or _inside_note(node, parents)
                or any(ancestor in candidate_set for ancestor in _ancestors(node, parents))
                or any(ancestor.get("type") in _CORPUS_CONTINUATIONS for ancestor in _ancestors(node, parents))
            ):
                continue
            if any(child in candidate_set for child in node.iter() if child is not node):
                raise UnsupportedStructure(f"unsupported-visible: source continuation contains a verse at {paths[node]}")
            if not _has_visible_source_text(node):
                continue
            if not _corpus_marker_matches(node):
                raise UnsupportedStructure(f"unsupported-visible: source continuation marker mismatch at {paths[node]}")
            previous = previous_by_chapter.get(chapter)
            if previous is None and node.get("type") == "paragraph-break":
                continue
            if previous is None:
                raise UnsupportedStructure(f"unsupported-visible: source continuation has no preceding verse at {paths[node]}")
            attached.setdefault(previous, []).append(node)
    return attached


def _note_rows(node: ET.Element, paths: Mapping[ET.Element, str], policy: Mapping[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for note in (
        child for child in node.iter()
        if _local(child.tag) == "note" and child.get("type") != "source-usfm-raw"
    ):
        place = note.get("place", "unspecified")
        if place not in {"foot", "end", "unspecified"}:
            raise UnsupportedStructure(f"unsupported-visible: note/@place at {paths[note]}")
        result.append({"text": _render(note, paths, omit_notes=False, policy=policy), "place": place, "label": note.get("n", "")})
    return result


def _note_only_blank_verse(node: ET.Element) -> bool:
    """Recognize an explicitly numbered verse represented by an omission note."""
    if _local(node.tag) != "ab" or node.get("type") != "verse":
        return False
    children = list(node)
    return (
        bool(children)
        and all(_local(child.tag) == "note" and child.get("type") in {"source-usfm-raw", "footnote"} for child in children)
        and any(child.get("type") == "source-usfm-raw" for child in children)
        and any(child.get("type") == "footnote" for child in children)
        and not (node.text or "").strip()
        and all(not (child.tail or "").strip() for child in children)
    )


def _reference_rows(node: ET.Element, paths: Mapping[ET.Element, str], policy: Mapping[str, Any], *, source_fields: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    public: list[dict[str, Any]] = []
    receipt: list[dict[str, Any]] = []
    for ref in (child for child in node.iter() if _local(child.tag) == "ref"):
        if source_fields and ref.get("type") in {"source-label", "source-origin", "source-target"}:
            continue
        target = (ref.get("target") or ref.get("cRef") or "").strip()
        if not target:
            raise UnsupportedStructure(f"unsupported-visible: reference has no target at {paths[ref]}")
        label = _render(ref, paths, omit_notes=False, policy=policy)
        public.append({"label": label, "resolution": "external", "target_record_id": None, "target_note": None, "source_note": None})
        receipt.append({"tei_path": paths[ref], "original_target": target, "resolution": "external", "target_record_id": None, "target_note": None, "source_note": None})
    return public, receipt


def _attributes(node: ET.Element) -> dict[str, str]:
    return {"xml:" + _local(key) if key.startswith(f"{{{XML_NS}}}") else _local(key) if key.startswith("{") else key: value for key, value in sorted(node.attrib.items())}


def _account(root: ET.Element, candidates: Sequence[ET.Element], selected: Sequence[ET.Element], paths: Mapping[ET.Element, str], continuations: Mapping[ET.Element, Sequence[ET.Element]] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    selected_set = set(selected)
    candidate_set = set(candidates)
    row_nodes = {child for unit in selected for child in unit.iter()}
    continuations = continuations or {}
    attached_to = {
        child: verse
        for verse, blocks in continuations.items()
        for block in blocks
        for child in block.iter()
    }
    row_nodes.update(child for verse in selected for block in continuations.get(verse, ()) for child in block.iter())
    inventory: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    parents = _parents(root)
    for node in root.iter():
        kind = _local(node.tag)
        ancestors = _ancestors(node, parents)
        excluded = any(_local(item.tag) == "div" and item.get("type") in _EXCLUDED_TYPES for item in ancestors + [node])
        if any(_local(item.tag) == "teiHeader" for item in ancestors + [node]) or kind == "TEI":
            disposition = "private-header"
        elif excluded:
            disposition = "excluded-paratext"
        elif node in row_nodes:
            disposition = "row-content"
        elif node in attached_to:
            disposition = "outside-scope"
        elif node in candidate_set and node not in selected_set:
            disposition = "outside-scope"
        elif kind == "head":
            disposition = "locator-heading"
        else:
            disposition = "structure"
        item = {"tei_path": paths[node], "disposition": disposition, "attributes": _attributes(node), "text_sha256": _hash_text(node.text or ""), "tail_sha256": _hash_text(node.tail or "")}
        inventory.append(item)
        if disposition in {"outside-scope", "excluded-paratext"}:
            exclusions.append({"tei_path": paths[node], "reason": disposition})
        if disposition == "row-content" and kind in _WARNING_REASONS:
            warnings.append({"tei_path": paths[node], "reason": _WARNING_REASONS[kind]})
        if disposition == "row-content" and kind == "seg" and node.get("type") == "usfm-qs" and "\\" in (node.text or ""):
            warnings.append({"tei_path": paths[node], "reason": "source-usfm-word-annotation-rendered-to-surface"})
        if disposition in {"structure", "row-content"} and "ana" in node.attrib:
            warnings.append({"tei_path": paths[node], "reason": "source-analytic-classification-recorded-in-master"})
        if (disposition == "structure" and kind in {"p", "ab", "seg"}
                and node.get("type") in _CORPUS_MARKERS
                and _has_visible_source_text(node)):
            warnings.append({"tei_path": paths[node], "reason": "source-structural-text-not-projected-to-verse"})
    warnings.extend(
        {"tei_path": paths[block], "reason": "source-continuation-attached-to-preceding-verse"}
        for verse in selected for block in continuations.get(verse, ())
    )
    return inventory, exclusions, warnings


def _context(*, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str, versification: str) -> dict[str, str]:
    result = _identity(identity)
    if not isinstance(language, str) or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", language):
        raise PipelineError("invalid Bible language")
    for label, value in (("representation revision", representation_revision), ("edition title", edition_title), ("versification", versification)):
        if not isinstance(value, str) or not value.strip():
            raise PipelineError(f"missing Bible {label}")
    result.update(language=language, representation_revision=representation_revision, edition_title=edition_title, versification=versification)
    return result


def _validator() -> Any:
    try:
        import jsonschema
        from referencing import Registry, Resource
        import referencing.jsonschema
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        common = json.loads(COMMON_SCHEMA_PATH.read_text(encoding="utf-8"))
        resource = Resource.from_contents(common, default_specification=referencing.jsonschema.DRAFT202012)
        registry = Registry().with_resources([(common["$id"], resource)])
        validator = jsonschema.Draft202012Validator(schema, registry=registry, format_checker=jsonschema.FormatChecker())
        validator.check_schema(schema)
        return validator
    except (ImportError, OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise PipelineError("invalid Bible projection schema package") from exc


def _validate_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    validator = _validator()
    for index, row in enumerate(rows, 1):
        errors = sorted(validator.iter_errors(row), key=lambda error: list(error.path))
        if errors:
            record = row.get("record_id", f"row-{index}") if isinstance(row, Mapping) else f"row-{index}"
            raise PipelineError(f"invalid Bible public row {record}: {errors[0].message}")


def _projection(path: Path, *, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str, versification: str, scope_id: str | None, source_url: str | None, source_sha256: str | None, retained_sha256: str | None, accessed_at: str | None, _preloaded: tuple[ET.Element, bytes] | None = None, _already_validated: bool = False, _source_strict: bool = False) -> dict[str, Any]:
    context = _context(identity=identity, language=language, representation_revision=representation_revision, edition_title=edition_title, versification=versification)
    root, raw = _read(path) if _preloaded is None else _preloaded
    paths = _paths(root)
    parents = _parents(root)
    header = _header(root)
    engwebpb = _engwebpb_profile(identity, representation_revision, header)
    if not _already_validated:
        if engwebpb:
            _engwebpb_validate(root, paths, parents, _engwebpb_members(engwebpb), engwebpb)
        else:
            _validate_elements(root, paths)
    documents = [root, *(child for child in list(root) if _local(child.tag) == "TEI")] if _local(root.tag) == "teiCorpus" else [root]
    for document in documents:
        declared_language = document.get(f"{{{XML_NS}}}lang")
        if declared_language and declared_language.strip().lower() != language.strip().lower():
            raise UnsupportedStructure(f"unsupported-visible: source language {declared_language} differs from emitted language {language}")
    if source_url is not None and header["source_url"] != source_url:
        raise PipelineError(f"TEI source URL mismatch: {header['source_url']} != {source_url}")
    if source_sha256 is not None and header.get("source_sha256") != _valid_hash(source_sha256, field="source sha256"):
        raise PipelineError("TEI source sha256 mismatch")
    if retained_sha256 is not None and header["retained_sha256"] != _valid_hash(retained_sha256, field="retained source sha256"):
        raise PipelineError("TEI retained sha256 mismatch")
    for key in _IDENTITY_KEYS:
        actual = header["ids"].get(key)
        if actual is not None and actual != context[key]:
            raise PipelineError(f"TEI {key} mismatch")
    actual_revision = header["ids"].get("representation_revision")
    if actual_revision is not None and actual_revision != representation_revision:
        raise PipelineError("TEI representation revision mismatch")
    header_versification = header["ids"].get("versification") or header["ids"].get("bible_versification")
    if header_versification is not None and header_versification != versification:
        raise PipelineError(f"TEI versification mismatch: {header_versification} != {versification}")
    public_versification = versification
    if re.fullmatch(r"source-native:retained-member-set:[0-9a-f]{64}", versification):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", representation_revision):
            raise PipelineError("invalid public Bible representation revision")
        public_versification = f"source-native:retained-member-set:{identity['edition_id']}:{representation_revision}"
    bodies = _body_nodes(root)
    strict_types = _local(root.tag) == "teiCorpus" or _source_strict
    all_candidates = [candidate for body in bodies for candidate in _candidates(body, parents, strict_types=strict_types)]
    continuations = (_engwebpb_continuations(bodies[0], all_candidates, parents, paths, engwebpb) if engwebpb
                     else _continuations(bodies, all_candidates, parents, paths) if strict_types else {})
    if not all_candidates:
        raise UnsupportedStructure("unsupported-visible: no explicit Bible verse carriers")
    selected = list(all_candidates)
    if scope_id is not None:
        scopes = [node for body in bodies for node in body.iter() if node.get(XML_ID) == scope_id]
        if len(scopes) != 1:
            raise UnsupportedStructure(f"unsupported-visible: Bible scope not found: {scope_id}")
        scope = scopes[0]
        selected = [node for node in all_candidates if node is scope or scope in list(node.iter())]
        if not selected:
            raise UnsupportedStructure("unsupported-visible: Bible scope contains no verse carriers")
    ordinals = {node: index for index, node in enumerate(all_candidates, 1)}
    rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    blank_slot_paths: list[str] = []
    try:
        render_policy = json.loads(COMMON_SCHEMA_PATH.read_text(encoding="utf-8"))["x-ocd-projection-policy"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PipelineError("cannot load controlled script rendering policy") from exc
    codes = load_book_codes(BOOK_CODES_PATH)
    for sequence, node in enumerate(selected, 1):
        book, book_osis = _book(node, parents, paths)
        chapter = _chapter(node, parents, paths, allow_native_zero=(
            versification == _NATIVE_ZERO_VERSIFICATION
            and header["ids"].get("bible_native_chapter_policy") == _NATIVE_ZERO_POLICY
        ))
        verse, verse_label = _label(node, paths)
        verse = str(verse)
        blocks = continuations.get(node, ())
        text = _render(node, paths, policy=render_policy)
        if blocks:
            text = _norm(" ".join(
                part for part in [text, *(_render(block, paths, policy=render_policy) for block in blocks)]
                if part.strip()
            ))
        source_empty = (
            node.tag == f"{{{TEI_NS}}}ab" and node.get("type") == "verse"
            and node.get(XML_SPACE) == "preserve" and not list(node)
            and node.text in (None, "")
        ) or _note_only_blank_verse(node)
        if not text.strip() and not (
            source_empty or (engwebpb and _engwebpb_blank_note_only(node)) or (text and node.get(XML_SPACE) == "preserve" and not list(node))
        ):
            raise UnsupportedStructure(f"unsupported-visible: empty Bible verse at {paths[node]}")
        if not text.strip():
            blank_slot_paths.append(paths[node])
        public_refs, ref_receipts = _reference_rows(node, paths, render_policy, source_fields=engwebpb)
        for block in blocks:
            block_refs, block_receipts = _reference_rows(block, paths, render_policy, source_fields=engwebpb)
            public_refs.extend(block_refs)
            ref_receipts.extend(block_receipts)
        locator: dict[str, Any] = {"kind": "verse", "book": book, "book_osis": book_osis, "chapter": chapter, "verse": verse, "versification": public_versification, "source_order": ordinals[node]}
        locator['reference_origin'] = 'tei-verse-components'
        if locator['chapter'] == 0:
            locator['chapter_label'] = '0'
            locator['native_chapter_policy'] = _NATIVE_ZERO_POLICY
        try:
            if chapter == 0:
                raise PipelineError('Native source chapter zero has no normalized reference')
            locator['reference'] = normalize_explicit_target(f'{book_osis}.{chapter}.{verse}', book_codes=codes)
        except PipelineError:
            locator['reference_status'] = 'unsupported-verse-components'
        else:
            locator['reference_status'] = 'normalized-verse-components'
        if verse_label is not None:
            locator["verse_label"] = verse_label
        notes = _note_rows(node, paths, render_policy)
        for block in blocks:
            notes.extend(_note_rows(block, paths, render_policy))
        row = make_row(record_id=f"{context['edition_id']}:verse-{ordinals[node]:06d}", sequence=sequence, work_id=context["work_id"], textual_form_id=context["textual_form_id"], edition_id=context["edition_id"], category=CATEGORY, language=language, text=text, locator=locator, provenance={"edition_title": edition_title}, representation_revision=representation_revision, notes=notes)
        row["notes"] = row.get("notes", [])
        row["references"] = public_refs
        row["versification"] = public_versification
        rows.append(row)
        anchors.append({"record_id": row["record_id"], "tei_path": paths[node], "text_sha256": row_text_hash(text), "source_order": ordinals[node], "locator": copy.deepcopy(locator)})
        references.extend(ref_receipts)
    inventory, exclusions, warnings = (_engwebpb_account(bodies[0], selected, continuations, paths, parents, engwebpb) if engwebpb
                                      else _account(root, all_candidates, selected, paths, continuations))
    warnings.extend({"tei_path": path, "reason": "source-native-blank-verse-slot"} for path in blank_slot_paths)
    _validate_rows(rows)
    source_binding = _source_binding(header)
    result: dict[str, Any] = {"mapping_version": engwebpb["mapping_version"] if engwebpb else CORPUS_MAPPING_VERSION if _local(root.tag) == "teiCorpus" else MAPPING_VERSION, "assembler_version": ASSEMBLER_VERSION, "master_sha256": _hash_bytes(raw), "scope_id": scope_id, "rows": rows, "anchors": anchors, "inventory": inventory, "references": references, "warnings": warnings, "exclusions": exclusions, "unsupported": [], "source_binding": source_binding, "authority": {}}
    if header.get("source_sha256"):
        result["source_binding"]["source_sha256"] = header["source_sha256"]
    if accessed_at is not None:
        result["source_binding"]["accessed_at"] = accessed_at
    return result


def project_bible_document(tei_path: Path, *, identity: dict[str, str], language: str, representation_revision: str, edition_title: str, versification: str, scope_id: str | None = None, source_url: str | None = None, source_sha256: str | None = None, retained_sha256: str | None = None, accessed_at: str | None = None) -> dict[str, Any]:
    """Project a source-bound Bible TEI document without promoting acceptance."""
    result = _projection(Path(tei_path), identity=identity, language=language, representation_revision=representation_revision, edition_title=edition_title, versification=versification, scope_id=scope_id, source_url=source_url, source_sha256=source_sha256, retained_sha256=retained_sha256, accessed_at=accessed_at)
    result["receipt"] = build_bible_receipt(result, identity=identity)
    return result


project_bible = project_bible_document
project = project_bible_document
project_document = project_bible_document


def build_bible_receipt(projection: Mapping[str, Any], *, identity: Mapping[str, str], authority: Mapping[str, Any] | None = None) -> dict[str, Any]:
    rows = projection.get("rows")
    if not isinstance(rows, list):
        raise PipelineError("Bible projection rows must be a list")
    return {"schema_version": "2.0", "receipt_version": RECEIPT_VERSION, "mapping_version": projection.get("mapping_version", MAPPING_VERSION), "assembler_version": projection.get("assembler_version", ASSEMBLER_VERSION), "category": CATEGORY, "identity": copy.deepcopy(dict(identity)), "authority": copy.deepcopy(dict(authority if authority is not None else projection.get("authority", {}))), "master_sha256": projection.get("master_sha256"), "scope_id": projection.get("scope_id"), "source_binding": copy.deepcopy(projection.get("source_binding", {})), "output_sha256": _hash_bytes(canonical_row_bytes([dict(row) for row in rows])), "row_count": len(rows), "anchors": copy.deepcopy(projection.get("anchors")), "inventory": copy.deepcopy(projection.get("inventory")), "references": copy.deepcopy(projection.get("references")), "warnings": copy.deepcopy(projection.get("warnings")), "exclusions": copy.deepcopy(projection.get("exclusions")), "unsupported": copy.deepcopy(projection.get("unsupported")), "schema_sha256": _hash_bytes(SCHEMA_PATH.read_bytes()), "common_schema_sha256": _hash_bytes(COMMON_SCHEMA_PATH.read_bytes()), "book_codes_sha256": _hash_bytes(BOOK_CODES_PATH.read_bytes()), "policy_sha256": _hash_bytes(COMMON_SCHEMA_PATH.read_bytes()), "independent_check": {"status": "pending", "errors": []}}


def _checker_parse(path: Path) -> tuple[Any, bytes, dict[Any, str], dict[Any, Any]]:
    from lxml import etree
    try:
        raw = path.read_bytes()
        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False)
        tree = etree.fromstring(raw, parser=parser)
    except (OSError, etree.XMLSyntaxError) as exc:
        raise UnsupportedStructure(f"unsupported-visible: cannot parse Bible TEI: {exc}") from exc
    if tree.xpath("//comment() | //processing-instruction()[name() != 'xml']") or tree.getroottree().docinfo.doctype:
        raise UnsupportedStructure("unsupported-visible: declaration, entity, or comment")
    if etree.QName(tree).namespace != TEI_NS or etree.QName(tree).localname not in {"TEI", "teiCorpus"}:
        raise UnsupportedStructure("unsupported-visible: TEI P5 TEI or teiCorpus root required")
    paths: dict[Any, str] = {tree: f"/{etree.QName(tree).localname}[1]"}
    parents: dict[Any, Any] = {}
    for parent in tree.iter():
        counts: dict[str, int] = {}
        for child in parent:
            parents[child] = parent
            kind = etree.QName(child).localname
            counts[kind] = counts.get(kind, 0) + 1
            paths[child] = f"{paths[parent]}/{kind}[{counts[kind]}]"
    return tree, raw, paths, parents


def _checker_header(root: Any, paths: Mapping[Any, str]) -> dict[str, Any]:
    from lxml import etree
    common_headers = root.xpath("./tei:teiHeader", namespaces={"tei": TEI_NS})
    if len(common_headers) != 1:
        raise PipelineError("Bible TEI requires one common teiHeader")
    source_desc = common_headers[0].xpath(".//tei:sourceDesc", namespaces={"tei": TEI_NS})
    if len(source_desc) != 1:
        raise PipelineError("Bible TEI must contain one sourceDesc")
    targets = [
        (node, (node.get("target") or "").strip())
        for node in source_desc[0].iter()
        if (node.get("target") or "").strip()
    ]
    if etree.QName(root).localname == "teiCorpus":
        source_kind = source_desc[0].xpath(
            "string(.//tei:idno[translate(@type, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='ocd-source_kind' or translate(@type, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='source_kind'][1])",
            namespaces={"tei": TEI_NS},
        ).strip()
        source_refs = [
            value for node, value in targets
            if etree.QName(node).localname == "ref"
            and not any(
                etree.QName(ancestor).localname == "bibl"
                and (ancestor.get("type") or "") == "ocd-acceptance-binding"
                for ancestor in node.iterancestors()
            )
        ]
        package_ptrs = [
            value for node, value in targets
            if etree.QName(node).localname == "ptr"
            and any(
                etree.QName(ancestor).localname == "bibl"
                and (ancestor.get("type") or "") == "ocd-acceptance-binding"
                for ancestor in node.iterancestors()
            )
        ]
        all_ptrs = [value for node, value in targets if etree.QName(node).localname == "ptr"]
        unscoped_ptrs = [
            value for node, value in targets
            if etree.QName(node).localname == "ptr"
            and not any(
                etree.QName(ancestor).localname == "bibl"
                and (ancestor.get("type") or "") == "ocd-acceptance-binding"
                for ancestor in node.iterancestors()
            )
        ]
        if source_kind == "retained-member-set":
            if source_refs:
                if len(source_refs) != 1 or len(package_ptrs) != 1 or unscoped_ptrs:
                    raise UnsupportedStructure(
                        "unsupported-visible: retained member set requires one provider ref and one bound package ptr"
                    )
                if urlparse(source_refs[0]).path.casefold().endswith(".zip"):
                    raise UnsupportedStructure("unsupported-visible: provider ref points to a ZIP package")
                source_url = source_refs[0]
                package_url = package_ptrs[0]
            elif len(targets) == 1 and len(package_ptrs) == 1:
                package_url = package_ptrs[0]
                source_url = None if urlparse(package_url).path.casefold().endswith(".zip") else package_url
            else:
                raise UnsupportedStructure(
                    "unsupported-visible: retained member set requires one provider ref or one package ptr"
                )
        elif source_refs:
            if len(source_refs) != 1:
                raise UnsupportedStructure("unsupported-visible: Bible sourceDesc requires one provider source ref")
            if urlparse(source_refs[0]).path.casefold().endswith(".zip"):
                raise UnsupportedStructure("unsupported-visible: provider ref points to a ZIP package")
            if unscoped_ptrs:
                raise UnsupportedStructure("unsupported-visible: Bible sourceDesc has an unbound source ptr")
            source_url = source_refs[0]
            if len(package_ptrs) > 1:
                raise UnsupportedStructure("unsupported-visible: Bible acceptance binding requires one package ptr")
            package_url = package_ptrs[0] if package_ptrs else None
        elif len(all_ptrs) == 1:
            package_url = all_ptrs[0]
            source_url = None if urlparse(package_url).path.casefold().endswith(".zip") else package_url
        else:
            raise PipelineError("Bible TEI sourceDesc must identify one source page")
    else:
        source_kind = next((
            _norm("".join(node.itertext()))
            for node in source_desc[0].xpath(".//tei:idno", namespaces={"tei": TEI_NS})
            if (node.get("type") or "").strip().lower().replace("ocd-", "") == "source_kind"
        ), None)
        if source_kind == "retained-member-set":
            source_refs = [
                value for node, value in targets
                if etree.QName(node).localname == "ref"
                and not any(
                    etree.QName(ancestor).localname == "bibl"
                    and (ancestor.get("type") or "") == "ocd-acceptance-binding"
                    for ancestor in node.iterancestors()
                )
            ]
            package_ptrs = [
                value for node, value in targets
                if etree.QName(node).localname == "ptr"
            ]
            if source_refs:
                if len(targets) != 2 or len(source_refs) != 1 or len(package_ptrs) != 1:
                    raise UnsupportedStructure(
                        "unsupported-visible: retained member set requires one provider ref and one package ptr"
                    )
                if urlparse(source_refs[0]).path.casefold().endswith(".zip"):
                    raise UnsupportedStructure("unsupported-visible: provider ref points to a ZIP package")
                source_url = source_refs[0]
                package_url = package_ptrs[0]
            elif len(targets) == 1 and len(package_ptrs) == 1:
                package_url = package_ptrs[0]
                source_url = None if urlparse(package_url).path.casefold().endswith(".zip") else package_url
            else:
                raise UnsupportedStructure(
                    "unsupported-visible: retained member set requires one provider ref or one package ptr"
                )
        else:
            pointers = [value for _, value in targets]
            if len(pointers) != 1:
                raise UnsupportedStructure("unsupported-visible: Bible sourceDesc requires one source ptr")
            package_url = pointers[0]
            source_url = None if urlparse(package_url).path.casefold().endswith(".zip") else package_url
    ids: dict[str, str] = {}
    for node in source_desc[0].xpath(".//tei:idno", namespaces={"tei": TEI_NS}):
        kind = (node.get("type") or "").strip().lower().replace("ocd-", "")
        value = _norm("".join(node.itertext()))
        if not value:
            continue
        binding_key = "retained_sha256" if kind in {"sha256", "retained_sha256", "archive_sha256"} else "source_sha256" if kind in {"source_sha256", "origin_sha256"} else "versification" if kind == "bible_versification" else kind
        if binding_key in ids:
            raise UnsupportedStructure(f"unsupported-visible: duplicate source binding {binding_key}")
        if kind in {"sha256", "retained_sha256", "archive_sha256"}:
            ids["retained_sha256"] = _valid_hash(value, field="retained source sha256")
        elif kind in {"source_sha256", "origin_sha256"}:
            ids["source_sha256"] = _valid_hash(value, field="source sha256")
        elif kind in {"work_id", "textual_form_id", "edition_id", "acquisition_id", "representation_revision", "versification", "bible_versification", "bible_native_chapter_policy", "source_kind", "source_bytes"}:
            ids[binding_key] = value
    if "bible_native_chapter_policy" in ids and (
        ids["bible_native_chapter_policy"] != _NATIVE_ZERO_POLICY
        or ids.get("versification") != _NATIVE_ZERO_VERSIFICATION
    ):
        raise UnsupportedStructure("unsupported-visible: invalid native chapter policy")
    if "retained_sha256" not in ids:
        raise PipelineError("Bible TEI sourceDesc must bind retained source sha256")
    source_location = source_desc[0].xpath(
        "string(.//tei:note[@type='source-location'][1])", namespaces={"tei": TEI_NS}
    ).strip() or None
    return {"source_url": source_url, "package_url": package_url, "source_location": source_location, "retained_sha256": ids["retained_sha256"], "source_sha256": ids.get("source_sha256"), "ids": ids}


def _source_binding(header: Mapping[str, Any]) -> dict[str, Any]:
    binding = {"source_url": header["source_url"], "retained_sha256": header["retained_sha256"]}
    if header.get("package_url") and header["package_url"] != header["source_url"]:
        binding["package_url"] = header["package_url"]
    if header.get("source_sha256"):
        binding["source_sha256"] = header["source_sha256"]
    return binding


def _checker_marker_matches(node: Any) -> bool:
    from lxml import etree
    raw_notes = [
        "".join(child.itertext()).strip()
        for child in node
        if etree.QName(child).localname == "note" and child.get("type") == "source-usfm-raw"
    ]
    if len(raw_notes) != 1:
        return False
    match = re.match(r"^\\{1,2}([A-Za-z][A-Za-z0-9]*)(?=\s|$)", raw_notes[0])
    marker = match.group(1) if match else None
    expected = _CORPUS_MARKERS.get(node.get("type") or "")
    return bool(expected and marker in expected and (node.get("n") is None or node.get("n") == marker))


def _checker_has_visible_source_text(node: Any) -> bool:
    from lxml import etree
    if etree.QName(node).localname == "note" and node.get("type") == "source-usfm-raw":
        return False
    if (node.text or "").strip():
        return True
    return any(_checker_has_visible_source_text(child) or (child.tail or "").strip() for child in node)


def _checker_inside_note(node: Any, parents: Mapping[Any, Any]) -> bool:
    from lxml import etree
    return any(etree.QName(ancestor).localname == "note" for ancestor in _checker_ancestors(node, parents))


def _checker_validate(root: Any, paths: Mapping[Any, str], parents: Mapping[Any, Any]) -> None:
    from lxml import etree
    root_kind = etree.QName(root).localname
    if root_kind == "TEI":
        documents = [root]
    elif root_kind == "teiCorpus":
        children = list(root)
        if (not children or etree.QName(children[0]).localname != "teiHeader"
                or len(children) < 2
                or any(etree.QName(child).localname != "TEI" for child in children[1:])):
            raise UnsupportedStructure("unsupported-visible: teiCorpus requires one header followed by TEI documents")
        documents = children[1:]
    else:
        raise UnsupportedStructure("unsupported-visible: TEI P5 TEI or teiCorpus root required")
    for document in documents:
        if [etree.QName(child).localname for child in document] != ["teiHeader", "text"]:
            raise UnsupportedStructure("unsupported-visible: TEI document requires teiHeader then text")
        texts = document.xpath("./tei:text", namespaces={"tei": TEI_NS})
        if (len(texts) != 1 or any(etree.QName(child).localname not in _TEXT_PARTS for child in texts[0])
                or sum(etree.QName(child).localname == "body" for child in texts[0]) != 1):
            raise UnsupportedStructure("unsupported-visible: Bible TEI requires one body")
    seen: set[str] = set()
    for node in root.iter():
        kind = etree.QName(node).localname
        if node.get(f"{{{XML_NS}}}id"):
            value = node.get(f"{{{XML_NS}}}id")
            if value in seen:
                raise UnsupportedStructure(f"unsupported-visible: duplicate xml:id at {paths[node]}")
            seen.add(value)
        if etree.QName(node).namespace != TEI_NS:
            raise UnsupportedStructure(f"unsupported-visible: non-TEI element at {paths[node]}")
        ancestors = []
        current = parents.get(node)
        while current is not None:
            ancestors.insert(0, current)
            current = parents.get(current)
        if any(etree.QName(key).namespace not in {None, XML_NS} for key in node.attrib):
            raise UnsupportedStructure(f"unsupported-visible: attribute namespace at {paths[node]}")
        attrs = {"xml:" + etree.QName(key).localname if etree.QName(key).namespace == XML_NS else key for key in node.attrib}
        if kind == "teiCorpus":
            if node is not root:
                raise UnsupportedStructure(f"unsupported-visible: nested teiCorpus at {paths[node]}")
            if (node.text or "").strip() or any((child.tail or "").strip() for child in node):
                raise UnsupportedStructure(f"unsupported-visible: loose text in teiCorpus at {paths[node]}")
            unknown = attrs - {"xml:id", "xml:lang"}
            if unknown:
                raise UnsupportedStructure(f"unsupported-visible: teiCorpus/@{sorted(unknown)[0]} at {paths[node]}")
            continue
        if kind == "TEI":
            if root_kind == "teiCorpus" and parents.get(node) is not root:
                raise UnsupportedStructure(f"unsupported-visible: nested TEI document at {paths[node]}")
            if (node.text or "").strip() or any((child.tail or "").strip() for child in node):
                raise UnsupportedStructure(f"unsupported-visible: loose text in TEI at {paths[node]}")
            if (
                root_kind == "teiCorpus"
                and root.get(f"{{{XML_NS}}}lang")
                and node.get(f"{{{XML_NS}}}lang")
                and root.get(f"{{{XML_NS}}}lang") != node.get(f"{{{XML_NS}}}lang")
            ):
                raise UnsupportedStructure(f"unsupported-visible: conflicting TEI document language at {paths[node]}")
            allowed_tei_attrs = _ATTRS["TEI"]
            if node is root:
                allowed_tei_attrs = allowed_tei_attrs | {"xml:lang"}
            if node is root and node.get("ana") == "#retained-source-representation":
                allowed_tei_attrs = allowed_tei_attrs | {"ana"}
            if root_kind == "teiCorpus" and parents.get(node) is root:
                allowed_tei_attrs = allowed_tei_attrs | {"xml:lang"}
            unknown = attrs - allowed_tei_attrs
            if unknown:
                raise UnsupportedStructure(f"unsupported-visible: TEI/@{sorted(unknown)[0]} at {paths[node]}")
            continue
        if kind == "teiHeader" or any(etree.QName(item).localname == "teiHeader" for item in ancestors):
            header_attributes = _HEADER_ATTRS.get(kind)
            if header_attributes is None and kind in {"p", "hi", "foreign", "ref"}:
                header_attributes = _ATTRS[kind]
            if header_attributes is None or not attrs <= header_attributes:
                raise UnsupportedStructure(f"unsupported-visible: header element or attribute at {paths[node]}")
            if kind == "ref" and node.get("target") is not None and node.get("cRef") is not None:
                raise UnsupportedStructure(f"unsupported-visible: conflicting reference targets at {paths[node]}")
            continue
        if kind == "ref" and "target" in node.attrib and "cRef" in node.attrib:
            raise UnsupportedStructure(f"unsupported-visible: conflicting reference targets at {paths[node]}")
        if kind not in _ALLOWED_VISIBLE:
            raise UnsupportedStructure(f"unsupported-visible: {kind} at {paths[node]}")
        if root_kind == "teiCorpus" and kind == "ab" and node.get("type") == "introduction-paragraph" and not _checker_marker_matches(node):
            raise UnsupportedStructure(f"unsupported-visible: source introduction marker mismatch at {paths[node]}")
        if kind == "title" and any(
            etree.QName(ancestor).localname == "verse"
            or etree.QName(ancestor).localname == "div" and ancestor.get("type") == "verse"
            or etree.QName(ancestor).localname in {"p", "ab", "seg"} and (
                ancestor.get("type") == "verse"
                or ancestor.get("type") is None
                and any(re.fullmatch(r"[1-9][0-9]*", ancestor.get(key, "")) for key in ("n", "verse", "number"))
                and _checker_nearest(ancestor, parents, {"div", "chapter"}, "chapter") is not None
            )
            for ancestor in ancestors
        ):
            raise UnsupportedStructure(f"unsupported-visible: title inside verse carrier at {paths[node]}")
        if "ana" in attrs and (
            root_kind != "teiCorpus"
            or kind not in {"div", "ab"}
            or not any(etree.QName(ancestor).localname == "body" for ancestor in ancestors)
            or re.fullmatch(r"#[A-Za-z0-9_.-]+", node.get("ana", "")) is None
        ):
            raise UnsupportedStructure(f"unsupported-visible: {kind}/@ana at {paths[node]}")
        if (root_kind == "teiCorpus" and kind in {"p", "ab", "seg"}
                and _checker_nearest(node, parents, {"div", "chapter"}, "chapter") is not None
                and not _checker_inside_note(node, parents)):
            ancestors = _checker_ancestors(node, parents)
            in_verse = any(
                etree.QName(ancestor).localname == "verse"
                or etree.QName(ancestor).localname == "div" and ancestor.get("type") == "verse"
                or etree.QName(ancestor).localname in {"p", "ab", "seg"} and ancestor.get("type") == "verse"
                for ancestor in ancestors
            )
            inline_continuation = (
                kind == "seg" and node.get("type") == "usfm-qs" and not node.get("n")
                and any(etree.QName(ancestor).localname in {"p", "ab", "seg"}
                        and ancestor.get("type") in _CORPUS_CONTINUATIONS for ancestor in ancestors)
            )
            numeric = any(re.fullmatch(r"[1-9][0-9]*", node.get(key, "")) for key in ("n", "verse", "number"))
            valid_verse = (
                kind == "verse"
                or kind == "div" and node.get("type") == "verse"
                or kind in {"p", "ab", "seg"} and (node.get("type") == "verse" or node.get("type") is None and numeric)
            )
            raw_notes = [
                "".join(child.itertext()).strip()
                for child in node
                if etree.QName(child).localname == "note" and child.get("type") == "source-usfm-raw"
            ]
            if not in_verse and not valid_verse and not inline_continuation and not _checker_marker_matches(node) and (
                _checker_has_visible_source_text(node)
                or any(node.get(key) for key in ("n", "verse", "number"))
                or raw_notes
            ):
                raise UnsupportedStructure(f"unsupported-visible: unclassified typed verse carrier at {paths[node]}")
        if attrs - _ATTRS.get(kind, set()):
            raise UnsupportedStructure(f"unsupported-visible: {kind}/@{sorted(attrs - _ATTRS.get(kind, set()))[0]} at {paths[node]}")
        if kind == "ab" and node.get(XML_SPACE) not in {None, "preserve"}:
            raise UnsupportedStructure(f"unsupported-visible: ab/@xml:space at {paths[node]}")
        if kind in {"text", "front", "body", "back", "div", "chapter"} and (node.text or "").strip():
            raise UnsupportedStructure(f"unsupported-visible: loose text in {kind} at {paths[node]}")
        if kind in {"text", "front", "body", "back", "div", "chapter"} and any((child.tail or "").strip() for child in node):
            raise UnsupportedStructure(f"unsupported-visible: loose tail text in {kind} at {paths[node]}")
        if kind == "note" and node.get("place") not in {None, "foot", "end", "unspecified"}:
            raise UnsupportedStructure(f"unsupported-visible: note/@place at {paths[node]}")
        if kind == "lb" and node.get("break") not in {None, "yes", "no"}:
            raise UnsupportedStructure(f"unsupported-visible: lb/@break at {paths[node]}")


def _checker_ancestors(node: Any, parents: Mapping[Any, Any]) -> list[Any]:
    result: list[Any] = []
    current = parents.get(node)
    while current is not None:
        result.insert(0, current)
        current = parents.get(current)
    return result


def _checker_nearest(node: Any, parents: Mapping[Any, Any], names: set[str], type_value: str | None = None) -> Any | None:
    from lxml import etree
    current = node
    while current is not None:
        kind = etree.QName(current).localname
        if kind in names and (type_value is None or current.get("type") == type_value):
            return current
        current = parents.get(current)
    return None


def _checker_candidates(body: Any, parents: Mapping[Any, Any], *, strict_types: bool = False) -> list[Any]:
    from lxml import etree
    all_candidates: list[Any] = []
    for node in body.iter():
        kind = etree.QName(node).localname
        explicit = kind == "verse" or (kind == "div" and node.get("type") == "verse") or (kind in {"p", "ab", "seg"} and node.get("type") == "verse")
        implicit = (
            kind in {"p", "ab", "seg"}
            and (not strict_types or node.get("type") in {None, "verse"})
            and bool(node.get("n") or node.get("verse") or node.get("number"))
            and _checker_nearest(node, parents, {"div", "chapter"}, "chapter") is not None
        )
        if explicit or implicit:
            all_candidates.append(node)
    result: list[Any] = []
    candidate_set = set(all_candidates)
    for node in all_candidates:
        current = parents.get(node)
        nested = False
        while current is not None:
            if current in candidate_set:
                nested = True
                break
            current = parents.get(current)
        if not nested:
            result.append(node)
    return result


def _checker_continuations(
    bodies: Sequence[Any], candidates: Sequence[Any], parents: Mapping[Any, Any],
    paths: Mapping[Any, str],
) -> dict[Any, list[Any]]:
    from lxml import etree
    candidate_set = set(candidates)
    attached: dict[Any, list[Any]] = {}
    for body in bodies:
        previous_by_chapter: dict[Any, Any] = {}
        for node in body.iter():
            chapter = _checker_nearest(node, parents, {"div", "chapter"}, "chapter")
            if chapter is None:
                continue
            if node in candidate_set:
                previous_by_chapter[chapter] = node
                continue
            if (etree.QName(node).localname not in {"p", "ab", "seg"}
                    or node.get("type") not in _CORPUS_CONTINUATIONS
                    or _checker_inside_note(node, parents)
                    or any(ancestor in candidate_set for ancestor in _checker_ancestors(node, parents))
                    or any(ancestor.get("type") in _CORPUS_CONTINUATIONS for ancestor in _checker_ancestors(node, parents))
                     ):
                continue
            if any(child in candidate_set for child in node.iter() if child is not node):
                raise UnsupportedStructure(f"unsupported-visible: source continuation contains a verse at {paths[node]}")
            if not _checker_has_visible_source_text(node):
                continue
            if not _checker_marker_matches(node):
                raise UnsupportedStructure(f"unsupported-visible: source continuation marker mismatch at {paths[node]}")
            previous = previous_by_chapter.get(chapter)
            if previous is None and node.get("type") == "paragraph-break":
                continue
            if previous is None:
                raise UnsupportedStructure(f"unsupported-visible: source continuation has no preceding verse at {paths[node]}")
            attached.setdefault(previous, []).append(node)
    return attached


def _checker_note_only_blank_verse(node: Any) -> bool:
    from lxml import etree
    children = list(node)
    return (
        etree.QName(node).localname == "ab"
        and node.get("type") == "verse"
        and bool(children)
        and all(etree.QName(child).localname == "note" and child.get("type") in {"source-usfm-raw", "footnote"} for child in children)
        and any(child.get("type") == "source-usfm-raw" for child in children)
        and any(child.get("type") == "footnote" for child in children)
        and not (node.text or "").strip()
        and all(not (child.tail or "").strip() for child in children)
    )


def _checker_engwebpb_validate(root: Any, paths: Mapping[Any, str], parents: Mapping[Any, Any], members: Sequence[tuple[str, Sequence[str]]], profile: Mapping[str, Any] | None = None) -> None:
    """Check the retained single-TEI grammar and source pointers with lxml."""
    if profile is None:
        profile = _RETAINED_USFM_PROFILES["engwebpb"]
    catholic = profile is not None and profile["slug"] == "eng-web-c"
    from lxml import etree
    if etree.QName(root).localname != "TEI" or [etree.QName(child).localname for child in root] != ["teiHeader", "text"]:
        raise UnsupportedStructure("unsupported-visible: engwebpb requires one TEI header and text")
    body_nodes = root.xpath("./tei:text/tei:body", namespaces={"tei": TEI_NS})
    if len(body_nodes) != 1 or len(root[1]) != 1:
        raise UnsupportedStructure("unsupported-visible: engwebpb requires one body")
    if any(_norm(value or "") for value in (root.text, root[0].tail, root[1].text, root[1].tail, body_nodes[0].text, body_nodes[0].tail)):
        raise UnsupportedStructure("unsupported-visible: engwebpb loose body text")
    header_stub = etree.Element(root.tag, root.attrib)
    header_stub.append(copy.deepcopy(root[0]))
    text_stub = etree.SubElement(header_stub, f"{{{TEI_NS}}}text", root[1].attrib)
    etree.SubElement(text_stub, f"{{{TEI_NS}}}body")
    stub_paths: dict[Any, str] = {header_stub: "/TEI[1]"}
    stub_parents: dict[Any, Any] = {}
    for parent in header_stub.iter():
        indices: dict[str, int] = {}
        for child in parent:
            name = etree.QName(child).localname
            indices[name] = indices.get(name, 0) + 1
            stub_paths[child] = f"{stub_paths[parent]}/{name}[{indices[name]}]"
            stub_parents[child] = parent
    _checker_validate(header_stub, stub_paths, stub_parents)
    sections = list(body_nodes[0])
    if len(sections) != len(members):
        raise UnsupportedStructure("unsupported-visible: engwebpb source division count differs")
    if any(_norm(section.tail or "") for section in sections):
        raise UnsupportedStructure("unsupported-visible: engwebpb loose member text")
    seen_lines: set[tuple[str, int]] = set()
    counts: dict[str, int] = {}
    spans = 0
    heading_types = {"usfm-h", "usfm-is1", "usfm-ms1", "usfm-mt1", "usfm-mt2", "usfm-mt3", "usfm-toc1", "usfm-toc2", "usfm-toc3"} | ({"usfm-s1"} if catholic else set())
    for section, (filename, lines) in zip(sections, members, strict=True):
        expected_line = 1
        match_name = profile["filename_pattern"].fullmatch(filename)
        code = match_name.group(1) if match_name else ""
        expected_type = "front" if code == "FRT" else "back" if code == "GLO" else "book"
        if etree.QName(section).localname != "div" or section.get("type") != expected_type or section.get("n") != code or section.get(XML_ID) != f"{profile['slug']}-{code}":
            raise UnsupportedStructure(f"unsupported-visible: engwebpb member division at {paths[section]}")
        for node in section.iter():
            if etree.QName(node).namespace != TEI_NS:
                raise UnsupportedStructure(f"unsupported-visible: engwebpb foreign element at {paths[node]}")
            name = etree.QName(node).localname
            parent = parents.get(node)
            parent_name = etree.QName(parent).localname if parent is not None else ""
            parent_type = parent.get("type") if parent is not None else ""
            kind = node.get("type")
            attrs = set(_attributes(node))
            if name == "div":
                allowed = {"type", "n", "xml:id"} if node is section else {"type", "n", "corresp"} if kind == "chapter" else {"type", "n"}
                valid = node is section or parent_name == "div" and (parent_type == "book" and kind in {"chapter", "usfm-heading", "usfm-line"} or parent_type in {"front", "back"} and kind in {"usfm-heading", "usfm-line"} or catholic and parent_type == "chapter" and parent.get("n") == "3" and section.get("n") == "DAG" and kind == "usfm-section")
                valid = valid and bool(node.get("n")) and kind in ({"front", "back", "book", "chapter", "usfm-heading", "usfm-line"} | ({"usfm-section"} if catholic else set()))
                if kind == "chapter":
                    valid = valid and re.fullmatch(r"[1-9][0-9]*", node.get("n", "")) is not None
                valid = valid and not _norm(node.text or "") and not any(_norm(child.tail or "") for child in node)
            elif name == "p":
                allowed = set()
                valid = parent_name == "div" and parent_type in ({"chapter", "usfm-line"} | ({"usfm-section"} if catholic else set())) and len(node) == 1 and etree.QName(node[0]).localname == "seg" and not _norm(node.text or "") and not _norm(node[0].tail or "")
            elif name == "ab":
                allowed = {"type", "n", "corresp", "xml:space"}
                valid = parent_name == "div" and parent_type in ({"chapter"} | ({"usfm-section"} if catholic else set())) and kind == "verse" and node.get(XML_SPACE) == "preserve" and (re.fullmatch(r"[1-9][0-9]*", node.get("n", "")) is not None or catholic and (node.get("corresp"), node.get("n")) in {("source-usfm:eng-web-c/46-SIReng-web-c.usfm#line=972", "15-16"), ("source-usfm:eng-web-c/46-SIReng-web-c.usfm#line=1396", "15-16"), ("source-usfm:eng-web-c/46-SIReng-web-c.usfm#line=1691", "18-19"), ("source-usfm:eng-web-c/46-SIReng-web-c.usfm#line=1951", "9-10"), ("source-usfm:eng-web-c/46-SIReng-web-c.usfm#line=2394", "19-27")})
            elif name == "seg":
                allowed = {"type"} if kind == "usfm-c-content" else {"type", "corresp"}
                valid = (parent_name == "p" and kind in (_ENGWEBPB_CONTINUATIONS | ({"usfm-q3", "usfm-pc"} if catholic else set())) | _ENGWEBPB_NONVERSE | _ENGWEBPB_EMPTY_MARKERS or parent_name == "note" and parent_type == "footnote" and kind in {"footnote-text", "alternate-reading", "quoted-reading"} or parent_name == "seg" and parent_type in {"usfm-q1", "usfm-q2"} and kind == "selah" or parent_name == "ab" and parent_type == "verse" and kind == "selah")
                if kind in _ENGWEBPB_EMPTY_MARKERS and _norm("".join(node.itertext())):
                    valid = False
            elif name == "w":
                allowed = {"n", "corresp"} | ({"type"} if kind == "usfm-plus-w" else set())
                valid = kind in {None, "usfm-plus-w"} and (parent_name == "ab" and parent_type == "verse" or parent_name == "seg" and parent_type in ({"usfm-q1", "usfm-q2", "usfm-p", "usfm-m", "usfm-pi1", "usfm-mi", "usfm-d", "selah"} | ({"usfm-q3", "usfm-pc"} if catholic else set())) or parent_name == "q" and parent_type == "words-of-Jesus" or parent_name == "title" and parent_type == "biblical-book") and re.fullmatch(r"[HG][0-9]+(?:[ ,;/]+[HG][0-9]+)*", node.get("n", "")) is not None and bool("".join(node.itertext()).strip()) and len(node) == 0
            elif name == "milestone":
                allowed = {"unit", "corresp"}
                valid = parent_name == "div" and parent_type in ({"chapter"} | ({"usfm-section"} if catholic else set())) and node.get("unit") == "paragraph" and len(node) == 0 and not _norm(node.text or "")
            elif name == "head":
                allowed = {"type", "corresp"}
                valid = kind in heading_types and parent_name == "div" and (parent_type == "usfm-heading" or parent_type == "chapter" and kind in ({"usfm-ms1"} | ({"usfm-s1"} if catholic else set())) or catholic and parent_type == "usfm-section" and kind == "usfm-s1") and (len(node) == 0 or catholic and kind == "usfm-s1" and all(etree.QName(c).localname == "note" and c.get("type") == "footnote" for c in node))
            elif name == "q":
                allowed = {"type", "corresp"}
                valid = kind == "words-of-Jesus" and (parent_name == "ab" and parent_type == "verse" or parent_name == "seg" and parent_type in {"usfm-q1", "usfm-q2", "usfm-p"})
            elif name == "note":
                allowed = {"type", "corresp"}
                valid = kind in {"footnote", "cross-reference"} and (parent_name == "ab" and parent_type == "verse" or parent_name == "seg" and parent_type in ({"usfm-q1", "usfm-q2", "usfm-p", "usfm-d", "usfm-ip"} | ({"usfm-q3", "usfm-pc"} if catholic else set())) or catholic and parent_name == "head" and parent_type == "usfm-s1" and kind == "footnote")
            elif name == "label":
                allowed = {"type", "corresp"} if catholic and kind == "footnote-label" else {"type"}
                valid = kind in ({"caller"} | ({"footnote-label"} if catholic else set())) and parent_name == "note" and parent_type in {"footnote", "cross-reference"} and len(node) == 0
            elif name == "ref":
                allowed = {"type", "corresp"}
                valid = parent_name == "note" and (parent_type == "footnote" and kind == "source-label" or parent_type == "cross-reference" and kind in {"source-origin", "source-target"}) and len(node) == 0
            elif name == "foreign":
                allowed = {"xml:lang", "corresp"}
                valid = parent_name == "note" and parent_type == "footnote" and node.get(f"{{{XML_NS}}}lang") == "he" and len(node) == 0
            elif name == "term":
                allowed = {"corresp"}
                valid = parent_name == "seg" and parent_type == "usfm-ili" and len(node) == 0
            elif name == "title":
                allowed = {"type", "corresp"}
                valid = kind == "biblical-book" and (parent_name == "seg" and parent_type == "usfm-ip" or parent_name == "ab" and parent_type == "verse" or catholic and parent_name == "note" and parent_type == "footnote")
            else:
                raise UnsupportedStructure(f"unsupported-visible: engwebpb {name} at {paths[node]}")
            if not valid or attrs != allowed:
                raise UnsupportedStructure(f"unsupported-visible: engwebpb {name} shape at {paths[node]}")
            pointer = node.get("corresp")
            if pointer is not None:
                bound = profile["corresp_pattern"].fullmatch(pointer)
                if bound is None or bound.group(1) != filename:
                    raise UnsupportedStructure(f"unsupported-visible: engwebpb source pointer at {paths[node]}")
                line = int(bound.group(2))
                if line > len(lines):
                    raise UnsupportedStructure(f"unsupported-visible: engwebpb source line at {paths[node]}")
                if catholic and name == "ab":
                    source_label = re.match(r"\\v\s+(\S+)(?:\s|$)", lines[line - 1])
                    if source_label is None or source_label.group(1) != node.get("n"):
                        raise UnsupportedStructure("unsupported-visible: Catholic verse label differs from retained source")
                if name == "ab" and _checker_engwebpb_blank_note_only(node) and re.match(r"\\v\s+" + re.escape(node.get("n", "")) + r"\s+\\f\b", lines[line - 1]) is None:
                    raise UnsupportedStructure(f"unsupported-visible: engwebpb blank verse source line at {paths[node]}")
                needs_span = catholic and name == "label" and kind == "footnote-label" or name in {"w", "q", "ref", "note", "foreign", "term", "title"} or name == "seg" and kind in {"footnote-text", "alternate-reading", "quoted-reading", "selah"}
                start, end = bound.group(3), bound.group(4)
                if (start is not None) != needs_span:
                    raise UnsupportedStructure(f"unsupported-visible: engwebpb source span shape at {paths[node]}")
                if start is None:
                    marker = filename, line
                    if marker in seen_lines or line != expected_line:
                        raise UnsupportedStructure(f"unsupported-visible: engwebpb source line order at {paths[node]}")
                    seen_lines.add(marker)
                    expected_line += 1
                else:
                    if int(start) >= int(end) or int(end) > len(lines[line - 1]):
                        raise UnsupportedStructure(f"unsupported-visible: engwebpb source span bounds at {paths[node]}")
                    origin = parents.get(node)
                    while origin is not None and profile["line_pattern"].fullmatch(origin.get("corresp", "")) is None:
                        origin = parents.get(origin)
                    if origin is None or int(origin.get("corresp", "").rsplit("=", 1)[-1]) != line:
                        raise UnsupportedStructure(f"unsupported-visible: engwebpb source span line at {paths[node]}")
                    spans += 1
            counts[name] = counts.get(name, 0) + 1
        if expected_line != len(lines) + 1:
            raise UnsupportedStructure(f"unsupported-visible: engwebpb source line coverage differs for {filename}")
    if catholic:
        observed = [n.get("n") for n in root.iter() if n.get("type") == "usfm-section"]
        if observed != ["pre-heading", "s1-156", "s1-228"]:
            raise UnsupportedStructure("unsupported-visible: Catholic DAG3 flow sections differ")
    if len(seen_lines) != profile["lines"] or spans != profile["spans"] or counts.get("ab") != profile["verses"] or counts.get("w") != profile["words"] or counts.get("note") != profile["notes"]:
        raise UnsupportedStructure("unsupported-visible: engwebpb complete source carrier accounting differs")





def _checker_engwebpb_continuations(body: Any, candidates: Sequence[Any], parents: Mapping[Any, Any], paths: Mapping[Any, str], profile: Mapping[str, Any] | None = None) -> dict[Any, list[Any]]:
    if profile is None:
        profile = _RETAINED_USFM_PROFILES["engwebpb"]
    catholic = profile["slug"] == "eng-web-c"
    from lxml import etree
    verse_nodes = set(candidates)
    preceding: dict[Any, Any] = {}
    attached: dict[Any, list[Any]] = {}
    for node in body.iter():
        chapter = _checker_nearest(node, parents, {"div"}, "chapter")
        if chapter is None:
            continue
        if node in verse_nodes:
            preceding[chapter] = node
        if etree.QName(node).localname != "p" or len(node) != 1 or node[0].get("type") not in (_ENGWEBPB_CONTINUATIONS | ({"usfm-q3", "usfm-pc"} if catholic else set())):
            continue
        segment = node[0]
        if any(descendant in verse_nodes for descendant in segment.iter()):
            raise UnsupportedStructure(f"unsupported-visible: engwebpb continuation contains a verse at {paths[segment]}")
        if not _checker_has_visible_source_text(segment):
            continue
        prior = preceding.get(chapter)
        if prior is None:
            if catholic and chapter.get("n") == "51" and segment.get("corresp") == "source-usfm:eng-web-c/46-SIReng-web-c.usfm#line=4780" and segment.get("type") == "usfm-p" and not list(segment) and segment.text == "A Prayer of Jesus the son of Sirach.  ":
                continue
            raise UnsupportedStructure(f"unsupported-visible: engwebpb continuation has no preceding verse at {paths[segment]}")
        attached.setdefault(prior, []).append(segment)
    return attached



def _checker_engwebpb_blank_note_only(node: Any) -> bool:
    from lxml import etree
    children = list(node)
    return (bool(children) and all(etree.QName(child).localname == "note" for child in children)
            and not (node.text or "").strip() and all(not (child.tail or "").strip() for child in children))


def _checker_render(node: Any, paths: Mapping[Any, str], *, omit_notes: bool = True, policy: Mapping[str, Any] | None = None) -> str:
    from lxml import etree
    try:
        if policy is None:
            policy = json.loads(COMMON_SCHEMA_PATH.read_text(encoding="utf-8"))["x-ocd-projection-policy"]
        maps = policy["script"]["maps"]
        styles = set(policy["script"]["styles"])
        punctuation = set(policy["script"]["safe_punctuation"])
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PipelineError("cannot load controlled script rendering policy") from exc
    sentinel = "\x00"

    def visit(current: Any, style: str | None = None) -> str:
        kind = etree.QName(current).localname
        current_style = style
        if kind == "hi" and current.get("rend") in styles:
            if style is not None:
                raise UnsupportedStructure(f"unsupported-visible: nested script styles at {paths[current]}")
            current_style = current.get("rend")
        value = current.text or ""
        if kind == "seg" and current.get("type") == "usfm-qs" and ("\\" in value or "|" in value):
            match = re.fullmatch(r'(\s*)\\\+w\s+([^\\|]+)\|strong="[HG][0-9]+"\\\+w\*(\s*)', value)
            if match is None or not match.group(2).strip():
                raise UnsupportedStructure(f"unsupported-visible: unsupported USFM word annotation at {paths[current]}")
            value = "".join(match.groups())
        if current_style:
            converted: list[str] = []
            for char in value:
                if char in maps[current_style]:
                    converted.append(maps[current_style][char])
                elif char.isspace() or char in punctuation:
                    converted.append(char)
                else:
                    raise UnsupportedStructure(f"unsupported-visible: unsupported script character {char!r} at {paths[current]}")
            value = "".join(converted)
        out = [value]
        for child in current:
            ck = etree.QName(child).localname
            if ck == "note" and omit_notes or ck in {"pb", "anchor", "ptr"}:
                out.append(" " if ck == "note" and omit_notes and child.get("corresp") in ('source-usfm:eng-web-c/43-ESGeng-web-c.usfm#line=16&span=133:169', 'source-usfm:eng-web-c/43-ESGeng-web-c.usfm#line=226&span=345:399') else sentinel)
            elif ck == "lb":
                out.append("" if child.get("break") == "no" else " ")
            else:
                out.append(visit(child, current_style))
            out.append(child.tail or "")
        return "".join(out)

    value = visit(node)
    for index, char in enumerate(value):
        if char == sentinel and index and index + 1 < len(value) and value[index - 1].isalnum() and value[index + 1].isalnum():
            raise UnsupportedStructure(f"unsupported-visible: omitted inline boundary at {paths[node]}")
    visible = value.replace(sentinel, "")
    return visible if node.get(XML_SPACE) == "preserve" else _norm(visible)



def _checker_book(node: Any, parents: Mapping[Any, Any], paths: Mapping[Any, str]) -> tuple[str, str]:
    from lxml import etree
    container = _checker_nearest(node, parents, {"div"}, "book")
    if container is None:
        raise UnsupportedStructure(f"unsupported-visible: verse has no book container at {paths[node]}")
    book = next((container.get(key, "").strip() for key in ("book", "book_name", "n") if container.get(key)), "")
    if not book:
        heads = [child for child in container if etree.QName(child).localname == "head"]
        book = _norm("".join(heads[0].itertext())) if heads else ""
    osis = next((container.get(key, "").strip() for key in ("book_osis", "osis", "osisID") if container.get(key)), "") or (container.get(f"{{{XML_NS}}}id") or "").strip()
    if not book or not osis:
        raise UnsupportedStructure(f"unsupported-visible: verse has no explicit book identity at {paths[node]}")
    return book, osis


def _checker_account(root: Any, candidates: Sequence[Any], selected: Sequence[Any], paths: Mapping[Any, str], parents: Mapping[Any, Any], continuations: Mapping[Any, Sequence[Any]] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    from lxml import etree
    candidate_set = set(candidates)
    selected_set = set(selected)
    row_nodes = {child for unit in selected for child in unit.iter()}
    continuations = continuations or {}
    attached_to = {
        child: verse
        for verse, blocks in continuations.items()
        for block in blocks
        for child in block.iter()
    }
    row_nodes.update(child for verse in selected for block in continuations.get(verse, ()) for child in block.iter())
    inventory: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    for node in root.iter():
        kind = etree.QName(node).localname
        ancestors = _checker_ancestors(node, parents)
        excluded = any(etree.QName(item).localname == "div" and item.get("type") in _EXCLUDED_TYPES for item in ancestors + [node])
        if kind in {"TEI", "teiHeader"} or any(etree.QName(item).localname == "teiHeader" for item in ancestors):
            disposition = "private-header"
        elif excluded:
            disposition = "excluded-paratext"
        elif node in row_nodes:
            disposition = "row-content"
        elif node in attached_to:
            disposition = "outside-scope"
        elif node in candidate_set and node not in selected_set:
            disposition = "outside-scope"
        elif kind == "head":
            disposition = "locator-heading"
        else:
            disposition = "structure"
        attrs = {"xml:" + etree.QName(key).localname if etree.QName(key).namespace == XML_NS else etree.QName(key).localname if key.startswith("{") else key: value for key, value in sorted(node.attrib.items())}
        inventory.append({"tei_path": paths[node], "disposition": disposition, "attributes": attrs, "text_sha256": _hash_text(node.text or ""), "tail_sha256": _hash_text(node.tail or "")})
        if disposition in {"outside-scope", "excluded-paratext"}:
            exclusions.append({"tei_path": paths[node], "reason": disposition})
        if disposition == "row-content" and kind in _WARNING_REASONS:
            warnings.append({"tei_path": paths[node], "reason": _WARNING_REASONS[kind]})
        if disposition == "row-content" and kind == "seg" and node.get("type") == "usfm-qs" and "\\" in (node.text or ""):
            warnings.append({"tei_path": paths[node], "reason": "source-usfm-word-annotation-rendered-to-surface"})
        if disposition in {"structure", "row-content"} and "ana" in node.attrib:
            warnings.append({"tei_path": paths[node], "reason": "source-analytic-classification-recorded-in-master"})
        if (disposition == "structure" and kind in {"p", "ab", "seg"}
                and node.get("type") in _CORPUS_MARKERS
                and _checker_has_visible_source_text(node)):
            warnings.append({"tei_path": paths[node], "reason": "source-structural-text-not-projected-to-verse"})
    warnings.extend(
        {"tei_path": paths[block], "reason": "source-continuation-attached-to-preceding-verse"}
        for verse in selected for block in continuations.get(verse, ())
    )
    return inventory, exclusions, warnings


def _checker_engwebpb_account(body: Any, selected: Sequence[Any], continuations: Mapping[Any, Sequence[Any]], paths: Mapping[Any, str], parents: Mapping[Any, Any], profile: Mapping[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    if profile is None:
        profile = _RETAINED_USFM_PROFILES["engwebpb"]
    from lxml import etree
    row_roots = set(selected) | {segment for blocks in continuations.values() for segment in blocks}
    inventory: list[dict[str, Any]] = []
    for section in body:
        counts: dict[str, int] = {}
        retained: dict[str, int] = {}
        for node in section.iter():
            name = etree.QName(node).localname
            counts[name] = counts.get(name, 0) + 1
            if name == "note" and node not in row_roots and not any(parent in row_roots for parent in _checker_ancestors(node, parents)):
                retained["note"] = retained.get("note", 0) + 1
        inventory.append({"tei_path": paths[section], "disposition": "source-member-retained-only" if section.get("type") in {"front", "back"} else "source-member-retained-and-verse-projected", "attributes": _attributes(section), "element_counts": dict(sorted(counts.items())), "retained_only_counts": dict(sorted(retained.items()))})
    if sum(item["retained_only_counts"].get("note", 0) for item in inventory) != profile["retained_notes"]:
        raise UnsupportedStructure("unsupported-visible: engwebpb retained-only note accounting differs")
    return inventory, [], [{"tei_path": paths[body], "reason": profile["warning"]}]



def _checker_expected(path: Path, *, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str, versification: str, scope_id: str | None, source_url: str | None, source_sha256: str | None, retained_sha256: str | None, accessed_at: str | None, authority: Mapping[str, Any] | None = None, _preloaded: tuple[Any, bytes, Mapping[Any, str], Mapping[Any, Any]] | None = None, _source_strict: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from lxml import etree
    root, raw, paths, parents = _checker_parse(path) if _preloaded is None else _preloaded
    header = _checker_header(root, paths)
    engwebpb = _engwebpb_profile(identity, representation_revision, header)
    if engwebpb:
        _checker_engwebpb_validate(root, paths, parents, _engwebpb_members(engwebpb), engwebpb)
    else:
        _checker_validate(root, paths, parents)
    documents = [root, *root.xpath("./tei:TEI", namespaces={"tei": TEI_NS})] if etree.QName(root).localname == "teiCorpus" else [root]
    for document in documents:
        declared_language = document.get(f"{{{XML_NS}}}lang")
        if declared_language and declared_language.strip().lower() != language.strip().lower():
            raise UnsupportedStructure(f"unsupported-visible: source language {declared_language} differs from emitted language {language}")
    if source_url is not None and header["source_url"] != source_url:
        raise PipelineError("TEI source URL mismatch")
    if source_sha256 is not None and header.get("source_sha256") != _valid_hash(source_sha256, field="source sha256"):
        raise PipelineError("TEI source sha256 mismatch")
    if retained_sha256 is not None and header["retained_sha256"] != _valid_hash(retained_sha256, field="retained source sha256"):
        raise PipelineError("TEI retained sha256 mismatch")
    for key in _IDENTITY_KEYS:
        if header["ids"].get(key) is not None and header["ids"][key] != identity[key]:
            raise PipelineError(f"TEI {key} mismatch")
    if header["ids"].get("representation_revision") not in {None, representation_revision}:
        raise PipelineError("TEI representation revision mismatch")
    header_versification = header["ids"].get("versification") or header["ids"].get("bible_versification")
    if header_versification is not None and header_versification != versification:
        raise PipelineError("TEI versification mismatch")
    public_versification = versification
    if re.fullmatch(r"source-native:retained-member-set:[0-9a-f]{64}", versification):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", representation_revision):
            raise PipelineError("invalid public Bible representation revision")
        public_versification = f"source-native:retained-member-set:{identity['edition_id']}:{representation_revision}"
    if etree.QName(root).localname == "TEI":
        body_nodes = root.xpath("./tei:text/tei:body", namespaces={"tei": TEI_NS})
    else:
        body_nodes = root.xpath("./tei:TEI/tei:text/tei:body", namespaces={"tei": TEI_NS})
    if not body_nodes:
        raise UnsupportedStructure("unsupported-visible: Bible TEI requires one or more bodies")
    strict_types = etree.QName(root).localname == "teiCorpus" or _source_strict
    all_candidates = [
        candidate for body in body_nodes
        for candidate in _checker_candidates(body, parents, strict_types=strict_types)
    ]
    continuations = (_checker_engwebpb_continuations(body_nodes[0], all_candidates, parents, paths, engwebpb) if engwebpb
                     else _checker_continuations(body_nodes, all_candidates, parents, paths) if strict_types else {})
    if not all_candidates:
        raise UnsupportedStructure("unsupported-visible: no explicit Bible verse carriers")
    selected = list(all_candidates)
    if scope_id:
        scopes = root.xpath(".//*[@xml:id=$id]", namespaces={"xml": XML_NS}, id=scope_id)
        if len(scopes) != 1 or not any(scopes[0] in set(body.iter()) for body in body_nodes):
            raise UnsupportedStructure(f"unsupported-visible: Bible scope not found: {scope_id}")
        scope = scopes[0]
        selected = [node for node in all_candidates if node is scope or scope in list(node.iter())]
        if not selected:
            raise UnsupportedStructure("unsupported-visible: Bible scope contains no verse carriers")
    ordinals = {id(node): index for index, node in enumerate(all_candidates, 1)}
    expected: list[dict[str, Any]] = []
    receipt_refs: list[dict[str, Any]] = []
    blank_slot_paths: list[str] = []
    try:
        render_policy = json.loads(COMMON_SCHEMA_PATH.read_text(encoding="utf-8"))["x-ocd-projection-policy"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PipelineError("cannot load controlled script rendering policy") from exc
    codes = load_book_codes(BOOK_CODES_PATH)
    for sequence, node in enumerate(selected, 1):
        book, book_osis = _checker_book(node, parents, paths)
        chapter_node = _checker_nearest(node, parents, {"div", "chapter"}, "chapter")
        native_chapter_label = (chapter_node.get("n") or chapter_node.get("chapter") or "") if chapter_node is not None else ""
        raw_chapter = native_chapter_label.strip()
        native_zero = (native_chapter_label == "0"
                       and versification == _NATIVE_ZERO_VERSIFICATION
                       and header["ids"].get("bible_native_chapter_policy") == _NATIVE_ZERO_POLICY)
        if not re.fullmatch(r"[1-9][0-9]*", raw_chapter) and not native_zero:
            raise UnsupportedStructure(f"unsupported-visible: invalid chapter at {paths[node]}")
        label = (node.get("n") or node.get("verse") or node.get("number") or "").strip()
        if not label:
            raise UnsupportedStructure(f"unsupported-visible: verse has no label at {paths[node]}")
        numeric_verse = bool(re.fullmatch(r"[1-9][0-9]*", label))
        verse = label
        blocks = continuations.get(node, ())
        text = _checker_render(node, paths, policy=render_policy)
        if blocks:
            text = _norm(" ".join(
                part for part in [text, *(_checker_render(block, paths, policy=render_policy) for block in blocks)]
                if part.strip()
            ))
        empty_native_carrier = (
            node.tag == "{" + TEI_NS + "}ab" and node.get("type") == "verse"
            and node.get(XML_SPACE) == "preserve" and len(node) == 0
            and node.text in (None, "")
        )
        if not text.strip() and not (
            empty_native_carrier or _checker_note_only_blank_verse(node) or (engwebpb and _checker_engwebpb_blank_note_only(node))
            or (text and node.get(XML_SPACE) == "preserve" and not list(node))
        ):
            raise UnsupportedStructure(f"unsupported-visible: empty Bible verse at {paths[node]}")
        if not text.strip():
            blank_slot_paths.append(paths[node])
        locator: dict[str, Any] = {"kind": "verse", "book": book, "book_osis": book_osis, "chapter": int(raw_chapter), "verse": verse, "versification": public_versification, "source_order": ordinals[id(node)]}
        locator['reference_origin'] = 'tei-verse-components'
        if locator['chapter'] == 0:
            locator['chapter_label'] = '0'
            locator['native_chapter_policy'] = _NATIVE_ZERO_POLICY
        try:
            if native_zero:
                raise ValueError('Native source chapter zero has no normalized reference')
            locator['reference'] = observe_explicit_target(f'{book_osis}.{int(raw_chapter)}.{verse}', book_codes=codes)
        except ValueError:
            locator['reference_status'] = 'unsupported-verse-components'
        else:
            locator['reference_status'] = 'normalized-verse-components'
        if not numeric_verse:
            locator["verse_label"] = label
        notes: list[dict[str, str]] = []
        for unit in (node, *blocks):
            for note in unit.xpath(".//tei:note", namespaces={"tei": TEI_NS}):
                if note.get("type") == "source-usfm-raw":
                    continue
                place = note.get("place", "unspecified")
                if place not in {"foot", "end", "unspecified"}:
                    raise UnsupportedStructure(f"unsupported-visible: note/@place at {paths[note]}")
                notes.append({"text": _checker_render(note, paths, omit_notes=False, policy=render_policy), "place": place, "label": note.get("n", "")})
        public_refs: list[dict[str, Any]] = []
        for unit in (node, *blocks):
            for ref in unit.xpath(".//tei:ref", namespaces={"tei": TEI_NS}):
                if engwebpb and ref.get("type") in {"source-label", "source-origin", "source-target"}:
                    continue
                target = (ref.get("target") or ref.get("cRef") or "").strip()
                if not target:
                    raise UnsupportedStructure(f"unsupported-visible: reference has no target at {paths[ref]}")
                public_refs.append({"label": _checker_render(ref, paths, omit_notes=False, policy=render_policy), "resolution": "external", "target_record_id": None, "target_note": None, "source_note": None})
                receipt_refs.append({"tei_path": paths[ref], "original_target": target, "resolution": "external", "target_record_id": None, "target_note": None, "source_note": None})
        row = make_row(record_id=f"{identity['edition_id']}:verse-{ordinals[id(node)]:06d}", sequence=sequence, work_id=identity["work_id"], textual_form_id=identity["textual_form_id"], edition_id=identity["edition_id"], category=CATEGORY, language=language, text=text, locator=locator, provenance={"edition_title": edition_title}, representation_revision=representation_revision, notes=notes)
        row["notes"] = notes
        row["references"] = public_refs
        row["versification"] = public_versification
        expected.append(row)
    inventory, exclusions, warnings = (_checker_engwebpb_account(body_nodes[0], selected, continuations, paths, parents, engwebpb) if engwebpb
                                      else _checker_account(root, all_candidates, selected, paths, parents, continuations))
    warnings.extend({"tei_path": path, "reason": "source-native-blank-verse-slot"} for path in blank_slot_paths)
    binding: dict[str, Any] = {"source_url": header["source_url"], "retained_sha256": header["retained_sha256"]}
    if header.get("package_url") and header["package_url"] != header["source_url"]:
        binding["package_url"] = header["package_url"]
    if header.get("source_sha256"):
        binding["source_sha256"] = header["source_sha256"]
    if accessed_at is not None:
        binding["accessed_at"] = accessed_at
    receipt = {"schema_version": "2.0", "receipt_version": RECEIPT_VERSION, "mapping_version": engwebpb["mapping_version"] if engwebpb else CORPUS_MAPPING_VERSION if etree.QName(root).localname == "teiCorpus" else MAPPING_VERSION, "assembler_version": ASSEMBLER_VERSION, "category": CATEGORY, "identity": dict(identity), "authority": copy.deepcopy(dict(authority or {})), "master_sha256": _hash_bytes(raw), "scope_id": scope_id, "source_binding": binding, "output_sha256": _hash_bytes(canonical_row_bytes(expected)), "row_count": len(expected), "anchors": [{"record_id": row["record_id"], "tei_path": paths[selected[index]], "text_sha256": row_text_hash(row["text"]), "source_order": row["locator"]["source_order"], "locator": copy.deepcopy(row["locator"])} for index, row in enumerate(expected)], "inventory": inventory, "references": receipt_refs, "warnings": warnings, "exclusions": exclusions, "unsupported": [], "schema_sha256": _hash_bytes(SCHEMA_PATH.read_bytes()), "common_schema_sha256": _hash_bytes(COMMON_SCHEMA_PATH.read_bytes()), "book_codes_sha256": _hash_bytes(BOOK_CODES_PATH.read_bytes()), "policy_sha256": _hash_bytes(COMMON_SCHEMA_PATH.read_bytes()), "independent_check": {"status": "pending", "errors": []}}
    return expected, receipt


def verify_bible_document(tei_path: Path, rows: Sequence[Mapping[str, Any]] | Mapping[str, Any], receipt: Mapping[str, Any] | None = None, *, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str, versification: str, scope_id: str | None = None, source_url: str | None = None, source_sha256: str | None = None, retained_sha256: str | None = None, accessed_at: str | None = None, authority: Mapping[str, Any] | None = None, **_: Any) -> list[str]:
    """Independently compare rows and every source-bound receipt component."""
    errors: list[str] = []
    identity_value = _identity(identity)
    if isinstance(rows, Mapping):
        if "rows" not in rows:
            return ["checker requires a projection object with rows"]
        if receipt is None and isinstance(rows.get("receipt"), Mapping):
            receipt = rows["receipt"]
        provided = rows["rows"]
    else:
        provided = rows
    if not isinstance(provided, Sequence) or isinstance(provided, (str, bytes)):
        return ["checker requires a row sequence"]
    try:
        expected, expected_receipt = _checker_expected(Path(tei_path), identity=identity_value, language=language, representation_revision=representation_revision, edition_title=edition_title, versification=versification, scope_id=scope_id, source_url=source_url, source_sha256=source_sha256, retained_sha256=retained_sha256, accessed_at=accessed_at, authority=authority)
    except (PipelineError, OSError, TypeError, ValueError) as exc:
        return [str(exc)]
    if len(provided) != len(expected):
        errors.append(f"row count mismatch: {len(provided)} != {len(expected)}")
    validator = _validator()
    for index, (actual, wanted) in enumerate(zip(provided, expected), 1):
        if not isinstance(actual, Mapping):
            errors.append(f"row {index} is not an object")
            continue
        if dict(actual) != wanted:
            for key in sorted(set(actual) | set(wanted)):
                if actual.get(key) != wanted.get(key):
                    errors.append(f"row {index} {key} mismatch")
        schema_errors = sorted(validator.iter_errors(actual), key=lambda error: list(error.path))
        if schema_errors:
            errors.append(f"row {index} schema mismatch: {schema_errors[0].message}")
    if receipt is None:
        errors.append("Bible receipt is missing")
    elif not isinstance(receipt, Mapping):
        errors.append("Bible receipt must be an object")
    else:
        for key, wanted in expected_receipt.items():
            if receipt.get(key) != wanted:
                errors.append(f"Bible receipt {key} mismatch")
        if set(receipt) != set(expected_receipt):
            errors.append("Bible receipt fields mismatch")
    return sorted(set(errors))


check_bible_document = verify_bible_document
verify_document = verify_bible_document


def _accepted_authority(
    root: Path,
    *,
    acceptance_path: Path,
    work_path: Path,
    master_path: Path,
    acquisition_path: Path,
) -> dict[str, dict[str, str]]:
    """Bind accepted authority files by exact relative path and bytes hash."""

    base = Path(root).resolve()
    bindings: dict[str, dict[str, str]] = {}
    for name, value in (
        ("acceptance", acceptance_path),
        ("work", work_path),
        ("master", master_path),
        ("acquisition", acquisition_path),
    ):
        path = Path(value).resolve()
        if not path.is_file():
            raise PipelineError(f"accepted authority file is missing: {path}")
        try:
            relative = path.relative_to(base).as_posix()
        except (OSError, RuntimeError, ValueError) as exc:
            raise PipelineError(f"accepted authority file is outside root: {path}") from exc
        bindings[name] = {"path": relative, "sha256": _hash_bytes(path.read_bytes())}
    return bindings


def _accepted_metadata(root: Path, acceptance_path: Path) -> dict[str, Any]:
    """Validate accepted sidecars and derive the canonical edition context."""

    from ocd_kernel.library.acquisitions import acquisition_for_edition
    from ocd_kernel.library.identities import edition_by_id, resolve_edition_language
    from ocd_kernel.tei.acceptance import validate_acceptance

    base = Path(root).resolve()
    accepted_path = Path(acceptance_path).resolve()
    accepted = validate_acceptance(accepted_path, root=base)
    if accepted["promotion"]["status"] != "promoted":
        raise PipelineError("Bible projection requires a promoted accepted master")
    identity = {key: accepted["identity"][key] for key in _IDENTITY_KEYS}
    work, edition = edition_by_id(base, identity["edition_id"], work_id=identity["work_id"])
    category = edition.record.get("category", work.record.get("category"))
    if category != CATEGORY:
        raise PipelineError("accepted edition is not a Bible category")
    language = resolve_edition_language(work.record, edition.record, edition.textual_form_id)
    if not isinstance(language, str):
        raise PipelineError("accepted Bible edition has no language")
    acquisition_path, acquisition = acquisition_for_edition(
        base,
        identity["work_id"],
        identity["edition_id"],
        acquisition_id=accepted["identity"]["acquisition_id"],
    )
    master_path = Path(edition.path).resolve()
    authority = _accepted_authority(
        base,
        acceptance_path=accepted_path,
        work_path=work.path,
        master_path=master_path,
        acquisition_path=acquisition_path,
    )
    return {
        "root": base,
        "acceptance": accepted,
        "acceptance_path": accepted_path,
        "identity": identity,
        "work": work,
        "edition": edition,
        "master_path": master_path,
        "language": language,
        "acquisition": acquisition,
        "acquisition_path": acquisition_path,
        "authority": authority,
    }


def _validate_accepted_header(
    header: Mapping[str, Any], metadata: Mapping[str, Any]
) -> None:
    """Bind category TEI source facts to the validated acceptance record."""

    accepted = metadata["acceptance"]
    acquisition = metadata["acquisition"]
    source = accepted["source"]
    if source.get("source_kind") == "retained-member-set":
        if header.get("package_url") != acquisition.get("url"):
            raise PipelineError("accepted Bible master package URL does not bind acquisition")
        if header.get("source_location") != source.get("source_path"):
            raise PipelineError("accepted Bible master source-member-set path does not bind acceptance")
        if header["ids"].get("source_kind") != "retained-member-set":
            raise PipelineError("accepted Bible master does not identify its retained member set")
        try:
            header_bytes = int(header["ids"].get("source_bytes", ""))
        except (TypeError, ValueError) as exc:
            raise PipelineError("accepted Bible master source-member-set byte count is invalid") from exc
        if header_bytes != source.get("source_bytes"):
            raise PipelineError("accepted Bible master source-member-set byte count does not bind acceptance")
        if header.get("retained_sha256") != source.get("source_sha256"):
            raise PipelineError("accepted Bible master retained hash does not bind source-member-set")
    elif acquisition.get("url") not in {header.get("source_url"), header.get("package_url")}:
        raise PipelineError("accepted Bible master source URL does not bind acquisition")
    if header.get("source_sha256") != source["source_sha256"]:
        raise PipelineError("accepted Bible master source SHA-256 does not bind acquisition")
    included = accepted["scope"].get("included_members", [])
    if len(included) == 1 and header.get("retained_sha256") != included[0]["sha256"]:
        raise PipelineError("accepted Bible master retained hash does not bind source accounting")


def _validate_accepted_member_set(
    root: ET.Element, header: Mapping[str, Any], metadata: Mapping[str, Any]
) -> None:
    """Bind every accepted corpus document to one ordered retained text member."""

    accepted = metadata["acceptance"]
    source = accepted["source"]
    is_corpus = _local(root.tag) == "teiCorpus"
    if source.get("source_kind") != "retained-member-set":
        if is_corpus:
            raise PipelineError("accepted Bible teiCorpus requires retained-member-set accounting")
        return
    scope = accepted["scope"]
    included = scope.get("included_members")
    expected = scope.get("expected_members")
    if (
        not isinstance(included, list)
        or len(included) < 2
        or not isinstance(expected, list)
        or scope.get("excluded_members")
        or source.get("missing_members")
        or source.get("unknown_members")
        or len(expected) != len(included)
    ):
        raise PipelineError("accepted Bible retained-member-set scope is incomplete or not a corpus")
    if not is_corpus:
        if _local(root.tag) != "TEI" or len(_body_nodes(root)) != 1:
            raise PipelineError("accepted Bible member set requires one TEI body")
        retained = metadata["acquisition"].get("retained_files")
        if (metadata["acquisition"].get("source_kind") != "retained-member-set"
                or not isinstance(retained, list) or len(retained) != len(included)):
            raise PipelineError("accepted Bible single-TEI acquisition envelope differs")
        observed_paths: set[str] = set()
        for position, (member, wanted, acquired) in enumerate(zip(included, expected, retained), 1):
            if not all(isinstance(value, Mapping) for value in (member, wanted, acquired)):
                raise PipelineError(f"accepted Bible source member {position} is not an object")
            path = member.get("path")
            if not isinstance(path, str) or not path:
                raise PipelineError(f"accepted Bible source member {position} has no path")
            ensure_relative_path(path, field="accepted Bible member path")
            if (path.casefold() in observed_paths
                    or type(member.get("position")) is not int or member["position"] != position
                    or type(wanted.get("position")) is not int or wanted["position"] != position
                    or wanted.get("path") != path or acquired.get("path") != path
                    or type(member.get("bytes")) is not int or member["bytes"] < 0
                    or member["bytes"] != acquired.get("bytes")
                    or not re.fullmatch(r"[0-9a-f]{64}", str(member.get("sha256", "")))
                    or member["sha256"] != acquired.get("sha256")):
                raise PipelineError(f"accepted Bible source member {position} has invalid complete accounting")
            observed_paths.add(path.casefold())
        return
    documents = [child for child in list(root) if _local(child.tag) == "TEI"]
    if len(documents) != len(included):
        raise PipelineError("accepted Bible corpus document count does not match included source members")
    source_ids = parse_qs(urlparse(str(header.get("source_url", ""))).query).get("id", [])
    if len(source_ids) != 1 or not re.fullmatch(r"[A-Za-z0-9._-]+", source_ids[0]):
        raise PipelineError("accepted Bible source page does not bind a retained-member-set locator")
    source_id = source_ids[0]
    filenames: set[str] = set()
    for position, (member, expected_member, document) in enumerate(zip(included, expected, documents), 1):
        path = member.get("path") if isinstance(member, Mapping) else None
        filename = str(path).replace("\\", "/").rsplit("/", 1)[-1] if isinstance(path, str) else ""
        if (
            not filename
            or filename in filenames
            or member.get("position") != position
            or expected_member.get("position") != position
            or expected_member.get("path") != path
            or not isinstance(member.get("bytes"), int)
            or member["bytes"] < 0
            or not re.fullmatch(r"[0-9a-f]{64}", str(member.get("sha256", "")))
        ):
            raise PipelineError(f"accepted Bible source member {position} has invalid ordered accounting")
        filenames.add(filename)
        bodies = _body_nodes(document)
        if len(bodies) != 1:
            raise PipelineError(f"accepted Bible source member {position} must have one TEI body")
        books = [node for node in bodies[0].iter() if _local(node.tag) == "div" and node.get("type") == "book"]
        if len(books) != 1:
            raise PipelineError(f"accepted Bible source member {position} must bind one book division")
        corresp = books[0].get("corresp") or ""
        locator = re.fullmatch(r"source-usfm:([^/]+)/([^/#]+)#line=([1-9][0-9]*)", corresp)
        if (
            locator is None
            or locator.group(1) != source_id
            or locator.group(2) != filename
        ):
            raise PipelineError(f"accepted Bible corpus document {position} does not identify {filename}")


def _checker_validate_accepted_member_set(
    root: Any, header: Mapping[str, Any], metadata: Mapping[str, Any]
) -> None:
    """Independently bind corpus order to accepted member accounting."""

    from lxml import etree

    accepted = metadata["acceptance"]
    source = accepted["source"]
    is_corpus = etree.QName(root).localname == "teiCorpus"
    if source.get("source_kind") != "retained-member-set":
        if is_corpus:
            raise PipelineError("accepted Bible teiCorpus requires retained-member-set accounting")
        return
    scope = accepted["scope"]
    members = scope.get("included_members")
    expected = scope.get("expected_members")
    if (
        not isinstance(members, list) or len(members) < 2
        or not isinstance(expected, list) or len(expected) != len(members)
        or scope.get("excluded_members") or source.get("missing_members")
        or source.get("unknown_members")
    ):
        raise PipelineError("accepted Bible retained-member-set scope is incomplete or not a corpus")
    if not is_corpus:
        if etree.QName(root).localname != "TEI" or len(root.xpath("./tei:text/tei:body", namespaces={"tei": TEI_NS})) != 1:
            raise PipelineError("accepted Bible member set requires one TEI body")
        acquisition = metadata["acquisition"]
        retained = acquisition.get("retained_files")
        if (acquisition.get("source_kind") != "retained-member-set"
                or not isinstance(retained, list) or len(retained) != len(members)):
            raise PipelineError("accepted Bible single-TEI acquisition envelope differs")
        paths_seen: set[str] = set()
        for index in range(len(members)):
            present, wanted, acquired = members[index], expected[index], retained[index]
            if not all(isinstance(value, Mapping) for value in (present, wanted, acquired)):
                raise PipelineError(f"accepted Bible source member {index + 1} is not an object")
            label = present.get("path")
            if not isinstance(label, str) or not label:
                raise PipelineError(f"accepted Bible source member {index + 1} has no path")
            ensure_relative_path(label, field="accepted Bible member path")
            valid = (label.casefold() not in paths_seen
                     and type(present.get("position")) is int and present["position"] == index + 1
                     and type(wanted.get("position")) is int and wanted["position"] == index + 1
                     and label == wanted.get("path") == acquired.get("path")
                     and type(present.get("bytes")) is int and present["bytes"] >= 0
                     and present["bytes"] == acquired.get("bytes")
                     and re.fullmatch(r"[0-9a-f]{64}", str(present.get("sha256", ""))) is not None
                     and present["sha256"] == acquired.get("sha256"))
            if not valid:
                raise PipelineError(f"accepted Bible source member {index + 1} has invalid complete accounting")
            paths_seen.add(label.casefold())
        return
    documents = root.xpath("./tei:TEI", namespaces={"tei": TEI_NS})
    if len(documents) != len(members):
        raise PipelineError("accepted Bible corpus document count does not match included source members")
    source_ids = parse_qs(urlparse(str(header.get("source_url", ""))).query).get("id", [])
    if len(source_ids) != 1 or re.fullmatch(r"[A-Za-z0-9._-]+", source_ids[0]) is None:
        raise PipelineError("accepted Bible source page does not bind a retained-member-set locator")
    source_id = source_ids[0]
    observed_names: set[str] = set()
    for ordinal, member in enumerate(members, 1):
        path = member.get("path") if isinstance(member, Mapping) else None
        basename = str(path).replace("\\", "/").rsplit("/", 1)[-1] if isinstance(path, str) else ""
        if (
            not basename or basename in observed_names
            or member.get("position") != ordinal
            or expected[ordinal - 1].get("position") != ordinal
            or expected[ordinal - 1].get("path") != path
            or not isinstance(member.get("bytes"), int) or member["bytes"] < 0
            or not re.fullmatch(r"[0-9a-f]{64}", str(member.get("sha256", "")))
        ):
            raise PipelineError(f"accepted Bible source member {ordinal} has invalid ordered accounting")
        observed_names.add(basename)
        bodies = documents[ordinal - 1].xpath("./tei:text/tei:body", namespaces={"tei": TEI_NS})
        if len(bodies) != 1:
            raise PipelineError(f"accepted Bible source member {ordinal} must have one TEI body")
        divisions = bodies[0].xpath(".//tei:div[@type='book']", namespaces={"tei": TEI_NS})
        if len(divisions) != 1:
            raise PipelineError(f"accepted Bible source member {ordinal} must bind one book division")
        corresp = divisions[0].get("corresp") or ""
        locator = re.fullmatch(r"source-usfm:([^/]+)/([^/#]+)#line=([1-9][0-9]*)", corresp)
        if (
            locator is None
            or locator.group(1) != source_id
            or locator.group(2) != basename
        ):
            raise PipelineError(f"accepted Bible corpus document {ordinal} does not identify {basename}")


def _accepted_versification(header: Mapping[str, Any], metadata: Mapping[str, Any]) -> str:
    """Use a stated standard, or label the exact accepted source's native order."""
    explicit = header["ids"].get("versification") or header["ids"].get("bible_versification")
    declared = metadata["edition"].record.get("versification")
    if explicit is not None:
        if declared is not None and declared != explicit:
            raise PipelineError("accepted Bible versification disagrees with source-attested TEI")
        return explicit
    source = metadata["acceptance"]["source"]
    included = metadata["acceptance"]["scope"]["included_members"]
    if source.get("source_kind") == "retained-member-set":
        digest = _valid_hash(str(source.get("source_sha256", "")), field="retained member-set sha256")
        if (
            len(included) < 2
            or header["ids"].get("source_kind") != "retained-member-set"
            or header.get("source_sha256") != digest
            or header.get("retained_sha256") != digest
        ):
            raise PipelineError("accepted Bible has no exact retained-member-set source binding")
        native = f"source-native:retained-member-set:{digest}"
        if declared is not None and declared != native:
            raise PipelineError("accepted Bible versification disagrees with retained member set")
        return native
    retained = metadata["acquisition"].get("retained_files")
    if (
        source.get("source_kind") is not None
        or len(included) != 1
        or not isinstance(retained, list)
        or len(retained) != 1
        or source.get("source_path") != included[0].get("path")
        or source.get("source_sha256") != included[0].get("sha256")
        or retained[0].get("path") != included[0].get("path")
        or retained[0].get("sha256") != included[0].get("sha256")
    ):
        raise PipelineError("accepted Bible has no singular source-native versification binding")
    native = f"source-native:{Path(source['source_path']).name}"
    if declared is not None and declared != native:
        raise PipelineError("accepted Bible versification disagrees with source-native witness")
    return native


def _engwebpb_accepted_members(root: Any, metadata: Mapping[str, Any], profile: Mapping[str, Any] | None = None, *, checker: bool = False) -> None:
    """Bind all accepted members to the exact installed single-TEI edition."""
    if profile is None:
        profile = _RETAINED_USFM_PROFILES["engwebpb"]
    from lxml import etree
    accepted = metadata["acceptance"]
    source = accepted["source"]
    scope = accepted["scope"]
    if (source.get("source_kind") != "retained-member-set"
            or source.get("source_path") != str((ROOT / profile["member_set"]).relative_to(ROOT)).replace("\\", "/")
            or source.get("source_sha256") != profile["source_sha256"]
            or scope.get("excluded_members") or source.get("missing_members") or source.get("unknown_members")):
        raise PipelineError("engwebpb acceptance does not bind the complete retained member set")
    manifest = json.loads((ROOT / profile["member_set"]).read_text(encoding="utf-8"))
    members = manifest.get("members")
    included = scope.get("included_members")
    expected = scope.get("expected_members")
    if not isinstance(members, list) or not isinstance(included, list) or not isinstance(expected, list) or len(members) != profile["members"] or len(included) != profile["members"] or len(expected) != profile["members"]:
        raise PipelineError("engwebpb accepted member inventory differs")
    for index, (native, present, wanted) in enumerate(zip(members, included, expected, strict=True), 1):
        if any(not isinstance(item, Mapping) for item in (native, present, wanted)) or any(
            present.get(field) != native.get(field) for field in ("position", "path", "bytes", "sha256")
        ) or any(wanted.get(field) != native.get(field) for field in ("position", "path")):
            raise PipelineError(f"engwebpb accepted member {index} differs")
    if checker:
        sections = root.xpath("./tei:text/tei:body/tei:div", namespaces={"tei": TEI_NS})
        if etree.QName(root).localname != "TEI" or len(sections) != profile["members"]:
            raise PipelineError("engwebpb accepted TEI member count differs")
    else:
        sections = list(_body_nodes(root)[0])
        if _local(root.tag) != "TEI" or len(sections) != profile["members"]:
            raise PipelineError("engwebpb accepted TEI member count differs")
    for index, (section, native) in enumerate(zip(sections, members, strict=True), 1):
        match = profile["filename_pattern"].fullmatch(Path(native["path"]).name)
        code = match.group(1) if match else ""
        if not code or section.get("n") != code or section.get(XML_ID) != f"{profile['slug']}-{code}":
            raise PipelineError(f"engwebpb accepted TEI member {index} differs")



def _checker_accepted_versification(header: Mapping[str, Any], metadata: Mapping[str, Any]) -> str:
    """Independently derive the source-native namespace from accepted files."""
    ids = header["ids"]
    stated = ids.get("versification") or ids.get("bible_versification")
    edition_label = metadata["edition"].record.get("versification")
    if stated:
        if edition_label is not None and edition_label != stated:
            raise PipelineError("accepted Bible versification disagrees with source-attested TEI")
        return stated
    acceptance = metadata["acceptance"]
    members = acceptance["scope"]["included_members"]
    if acceptance["source"].get("source_kind") == "retained-member-set":
        digest = _valid_hash(str(acceptance["source"].get("source_sha256", "")), field="retained member-set sha256")
        if (len(members) < 2 or ids.get("source_kind") != "retained-member-set"
                or header.get("source_sha256") != digest or header.get("retained_sha256") != digest):
            raise PipelineError("accepted Bible has no exact retained-member-set source binding")
        label = f"source-native:retained-member-set:{digest}"
        if edition_label is not None and edition_label != label:
            raise PipelineError("accepted Bible versification disagrees with retained member set")
        return label
    acquisition_members = metadata["acquisition"].get("retained_files")
    if acceptance["source"].get("source_kind") is not None or len(members) != 1 or not isinstance(acquisition_members, list) or len(acquisition_members) != 1:
        raise PipelineError("accepted Bible has no singular source-native versification binding")
    member = members[0]
    origin = acceptance["source"]
    witness = acquisition_members[0]
    if any(value != member[key] for value, key in ((origin.get("source_path"), "path"), (origin.get("source_sha256"), "sha256"), (witness.get("path"), "path"), (witness.get("sha256"), "sha256"))):
        raise PipelineError("accepted Bible has no singular source-native versification binding")
    label = "source-native:" + Path(member["path"]).name
    if edition_label is not None and edition_label != label:
        raise PipelineError("accepted Bible versification disagrees with source-native witness")
    return label


def project_accepted_bible(root: Path, *, acceptance_path: Path) -> dict[str, Any]:
    """Project a promoted Bible using stated or exact-source-native numbering.

    The source-native label identifies this accepted witness only; it asserts
    no equivalence to an external versification standard. No caller override
    is accepted.
    """
    metadata = _accepted_metadata(root, acceptance_path)
    if metadata["identity"]["work_id"] == "brenton-septuagint":
        from .brenton_native_bible import project_accepted
        return project_accepted(root, acceptance_path=acceptance_path, metadata=metadata)

    if metadata["identity"]["work_id"] == "open-english-bible":
        from .oeb_native_bible import project_accepted
        return project_accepted(root, acceptance_path=acceptance_path)

    if metadata["identity"]["work_id"] == "world-english-bible-classic":
        from .web_classic_native_bible import project_accepted
        return project_accepted(root, acceptance_path=acceptance_path)

    if metadata["identity"]["work_id"] == "tyndale-new-testament-1534":
        from .tyndale_native_bible import project_accepted
        return project_accepted(root, acceptance_path=acceptance_path)

    if metadata["identity"]["work_id"] == "isaac-leeser-tanakh":
        from .leeser_native_bible import project_accepted
        return project_accepted(root, acceptance_path=acceptance_path)

    if metadata["identity"]["work_id"] == "geneva-bible-1599":
        from .geneva_native_bible import project_accepted
        return project_accepted(root, acceptance_path=acceptance_path)

    accepted = metadata["acceptance"]
    identity = metadata["identity"]
    edition = metadata["edition"]
    edition_path = metadata["master_path"]
    root_tei, raw = _read(edition_path)
    header = _header(root_tei)
    engwebpb = _engwebpb_profile(identity, accepted["representation_revision"]["id"], header)
    if engwebpb:
        _engwebpb_validate(root_tei, _paths(root_tei), _parents(root_tei), _engwebpb_members(engwebpb), engwebpb)
    else:
        _validate_elements(root_tei, _paths(root_tei))
    _validate_accepted_header(header, metadata)
    if engwebpb:
        _engwebpb_accepted_members(root_tei, metadata, engwebpb)
    else:
        _validate_accepted_member_set(root_tei, header, metadata)
    versification = _accepted_versification(header, metadata)
    result = _projection(
        edition_path,
        identity=identity,
        language=metadata["language"],
        representation_revision=accepted["representation_revision"]["id"],
        edition_title=edition.title,
        versification=versification,
        scope_id=None,
        source_url=header["source_url"],
        source_sha256=header.get("source_sha256"),
        retained_sha256=header["retained_sha256"],
        accessed_at=None,
        _preloaded=(root_tei, raw),
        _already_validated=True,
    )
    result["authority"] = copy.deepcopy(metadata["authority"])
    result["receipt"] = build_bible_receipt(result, identity=identity, authority=result["authority"])
    return result


project_accepted = project_accepted_bible


def verify_accepted_bible(root: Path, *, acceptance_path: Path, rows: Sequence[Mapping[str, Any]] | Mapping[str, Any], receipt: Mapping[str, Any] | None = None) -> list[str]:
    """Verify accepted rows without invoking the category producer."""
    try:
        metadata = _accepted_metadata(root, acceptance_path)
        if metadata["identity"]["work_id"] == "brenton-septuagint":
            from .brenton_native_bible import verify_accepted
            return verify_accepted(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt, metadata=metadata)

        if metadata["identity"]["work_id"] == "open-english-bible":
            from .oeb_native_bible import verify_accepted
            return verify_accepted(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt)

        if metadata["identity"]["work_id"] == "world-english-bible-classic":
            from .web_classic_native_bible import verify_accepted
            return verify_accepted(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt)

        if metadata["identity"]["work_id"] == "tyndale-new-testament-1534":
            from .tyndale_native_bible import verify_accepted
            return verify_accepted(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt)

        if metadata["identity"]["work_id"] == "isaac-leeser-tanakh":
            from .leeser_native_bible import verify_accepted
            return verify_accepted(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt)

        if metadata["identity"]["work_id"] == "geneva-bible-1599":
            from .geneva_native_bible import verify_accepted
            return verify_accepted(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt)

        master_path = metadata["master_path"]
        checker_root, _raw, checker_paths, checker_parents = _checker_parse(master_path)
        header = _checker_header(checker_root, checker_paths)
        engwebpb = _engwebpb_profile(metadata["identity"], metadata["acceptance"]["representation_revision"]["id"], header)
        if engwebpb:
            _checker_engwebpb_validate(checker_root, checker_paths, checker_parents, _engwebpb_members(engwebpb), engwebpb)
        else:
            _checker_validate(checker_root, checker_paths, checker_parents)
        _validate_accepted_header(header, metadata)
        if engwebpb:
            _engwebpb_accepted_members(checker_root, metadata, engwebpb, checker=True)
        else:
            _checker_validate_accepted_member_set(checker_root, header, metadata)
        versification = _checker_accepted_versification(header, metadata)
        accepted = metadata["acceptance"]
        return verify_bible_document(
            master_path,
            rows,
            receipt,
            identity=metadata["identity"],
            language=metadata["language"],
            representation_revision=accepted["representation_revision"]["id"],
            edition_title=metadata["edition"].title,
            versification=versification,
            source_url=header["source_url"],
            source_sha256=header.get("source_sha256"),
            retained_sha256=header["retained_sha256"],
            authority=metadata["authority"],
        )
    except (PipelineError, OSError, KeyError, TypeError, ValueError) as exc:
        return [str(exc)]


__all__ = [
    "ASSEMBLER_VERSION", "CATEGORY", "MAPPING_VERSION", "RECEIPT_VERSION", "UnsupportedStructure",
    "build_bible_receipt", "check_bible_document", "project", "project_accepted", "project_accepted_bible",
    "project_bible", "project_bible_document", "project_document", "verify_accepted_bible", "verify_bible_document",
    "verify_document",
]
