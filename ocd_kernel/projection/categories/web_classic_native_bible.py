"""Exact accepted WEB Classic source-line projection candidate."""

from __future__ import annotations

from collections import Counter
import copy
from hashlib import sha256
import json
from pathlib import Path
import re

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.envelope import make_row, row_text_hash
from ocd_kernel.projection.scripture_authority import BOOK_CODES_PATH, load_book_codes
from ocd_kernel.projection.scripture_targets import normalize_explicit_target
from ocd_kernel.projection.categories import bible

IDENTITY = {"work_id": "world-english-bible-classic",
            "textual_form_id": "world-english-bible-classic-retained-en",
            "edition_id": "world-english-bible-classic-electronic"}
REVISION = "world-english-bible-classic-eng-web-electronic-v2"
SOURCE_SHA = "faabd08ed1f4c7034c687def4c7bd8171984e9d88fafeb84037fdc543a395802"
MASTER_SHA = "65dfe3dea411239014e2bde8b7ee8dd7a60aa53b3c17e1cdbc5700c04bcb87ff"
MEMBER_SET = "library/works/world-english-bible-classic/forms/world-english-bible-classic-retained-en/editions/world-english-bible-classic-electronic/source-member-set.json"
N = "{" + bible.TEI_NS + "}"
X = bible.XML_ID
CONTINUATIONS = frozenset({"usfm-q1", "usfm-q2", "usfm-q3", "usfm-p", "usfm-m",
                           "usfm-mi", "usfm-pi1", "usfm-li1", "usfm-pc", "usfm-nb"})
HEADING = frozenset({"source-chapter-label", "usfm-ms1", "usfm-d", "usfm-sp",
                     "usfm-s1", "usfm-cp"})
EMPTY_MARKERS = frozenset({"usfm-b", "usfm-nb"})
CAPTION = ("SIR", "51", "source-usfm:eng-web/46-SIReng-web.usfm#line=4780",
           "A Prayer of Jesus the son of Sirach.")
MAPPING_VERSION = "ocd-web-classic-source-lines-v1"


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _context(root: Path, acceptance_path: Path) -> dict:
    metadata = bible._accepted_metadata(root, acceptance_path)
    accepted = metadata["acceptance"]
    source = accepted["source"]
    scope = accepted["scope"]
    if (metadata["identity"] != IDENTITY or metadata["language"] != "en"
            or accepted["representation_revision"]["id"] != REVISION
            or source["source_kind"] != "retained-member-set"
            or source["source_path"] != MEMBER_SET or source["source_sha256"] != SOURCE_SHA
            or len(scope["included_members"]) != 83 or len(scope["expected_members"]) != 83
            or scope["excluded_members"] or source["missing_members"] or source["unknown_members"]
            or _sha(metadata["master_path"].read_bytes()) != MASTER_SHA):
        raise PipelineError("WEB Classic exact accepted member set, identity, or master differs")
    return metadata


def _members(body, metadata):
    members = metadata["acceptance"]["scope"]["included_members"]
    if len(body) != 83:
        raise PipelineError("WEB Classic requires 83 source-ordered members")
    for member, node in zip(members, body, strict=True):
        name = Path(member["path"]).name
        match = re.fullmatch(r"[0-9]+-([A-Z0-9]+)eng-web\.usfm", name)
        if (match is None or node.tag != N + "div"
                or node.get("type") != ("paratext" if match.group(1) in {"FRT", "GLO"} else "book")
                or node.get("n") != match.group(1) or node.get(X) != "web-" + match.group(1)
                or node.get("corresp") != "source-usfm:eng-web/" + name):
            raise PipelineError(f"WEB Classic accepted member/carrier crosswalk differs: {name}")
        yield name, node


def _line(line, name: str, expected_number: int) -> tuple[str, str]:
    if line.tag != N + "ab" or not line.get("type"):
        raise PipelineError(f"WEB Classic unexpected source-line carrier in {name}")
    pointer = f"source-usfm:eng-web/{name}#line={expected_number}"
    if line.get("corresp") != pointer or len(line) < 1 or line[0].tag != N + "note" or line[0].get("type") != "source-usfm-raw":
        raise PipelineError(f"WEB Classic source line or raw evidence differs: {pointer}")
    if list(line).count(line[0]) != 1 or not (line[0].text or "").startswith("\\"):
        raise PipelineError(f"WEB Classic source raw marker differs: {pointer}")
    return line.get("type"), pointer


class _LinePaths(dict):
    def __missing__(self, node):
        return node.get("corresp") or node.get(X) or bible._local(node.tag)


def _line_paths(body):
    paths = _LinePaths()
    for member_index, member in enumerate(body, 1):
        member_path = f"/TEI[1]/text[1]/body[1]/div[{member_index}]"
        counts = Counter()
        for child in member:
            tag = bible._local(child.tag)
            counts[tag] += 1
            child_path = f"{member_path}/{tag}[{counts[tag]}]"
            if child.tag == N + "ab":
                paths[child] = child_path
            elif child.tag == N + "div":
                inner = Counter()
                for line in child:
                    kind = bible._local(line.tag)
                    inner[kind] += 1
                    paths[line] = f"{child_path}/{kind}[{inner[kind]}]"
    return paths


def _inventory(body, metadata, paths):
    """Account for every accepted source line and retained inline annotation."""
    types = Counter()
    note_types = Counter()
    inline_tags = Counter()
    words = 0
    raw_hash = sha256()
    strong_hash = sha256()
    for name, member in _members(body, metadata):
        lines = [node for node in member.iter() if node.tag == N + "ab"]
        for number, line in enumerate(lines, 1):
            typ, pointer = _line(line, name, number)
            types[typ] += 1
            raw_hash.update(json.dumps([pointer, line[0].text], ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
            for node in line.iter():
                kind = bible._local(node.tag)
                if kind == "note":
                    note_types[node.get("type") or ""] += 1
                elif kind in {"term", "title"}:
                    inline_tags[kind] += 1
                elif kind == "w":
                    words += 1
                    if node.get("type") not in {"w", "+w"} or not re.fullmatch(r"[HG][0-9]+(?:[ ,;/]+[HG][0-9]+)*", node.get("n") or ""):
                        raise PipelineError(f"WEB Classic Strong word shape differs at {paths[node]}")
                    strong_hash.update(json.dumps([pointer, node.get("type"), node.get("n"), "".join(node.itertext())], ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
    if (sum(types.values()) != 74297 or types["verse"] != 38058 or words != 677690
            or note_types["source-usfm-raw"] != 74297
            or inline_tags != Counter({"term": 94, "title": 47})):
        raise PipelineError("WEB Classic complete private source-line or Strong inventory differs")
    return {"source_members": 83, "source_lines": 74297, "verses": 38058,
            "word_annotations": words, "line_types": dict(sorted(types.items())),
            "note_types": dict(sorted(note_types.items())), "inline_tags": dict(sorted(inline_tags.items())),
            "raw_line_ledger_sha256": raw_hash.hexdigest(),
            "strong_annotation_ledger_sha256": strong_hash.hexdigest()}


def _render_visible(line, paths, policy):
    try:
        return bible._render(line, paths, policy=policy), False
    except bible.UnsupportedStructure as exc:
        if "omitted inline element creates ambiguous text" not in str(exc):
            raise
    sentinel = "\x00"

    def visit(node):
        value = node.text or ""
        if node.tag == N + "seg" and node.get("type") == "usfm-qs" and ("\\" in value or "|" in value):
            match = re.fullmatch(r'(\s*)\\\+w\s+([^\\|]+)\|strong="[HG][0-9]+"\\\+w\*(\s*)', value)
            if match is None or not match.group(2).strip():
                raise PipelineError(f"WEB Classic unsupported quoted word at {paths[node]}")
            value = "".join(match.groups())
        parts = [value]
        for child in node:
            parts.append(sentinel if child.tag == N + "note" else visit(child))
            parts.append(child.tail or "")
        return "".join(parts)

    raw = visit(line)
    visible = []
    for i, char in enumerate(raw):
        if char == sentinel:
            if i and i + 1 < len(raw) and raw[i - 1].isalnum() and raw[i + 1].isalnum():
                visible.append(" ")
        else:
            visible.append(char)
    return " ".join("".join(visible).split()), True


def _project(metadata: dict) -> dict:
    root_tei, raw = bible._read(metadata["master_path"])
    if _sha(raw) != MASTER_SHA:
        raise PipelineError("WEB Classic exact accepted master differs")
    header = bible._header(root_tei)
    bible._validate_accepted_header(header, metadata)
    bible._validate_accepted_member_set(root_tei, header, metadata)
    versification = bible._accepted_versification(header, metadata)
    if versification != "source-native:retained-member-set:" + SOURCE_SHA:
        raise PipelineError("WEB Classic accepted source-native versification differs")
    public_versification = f"source-native:retained-member-set:{IDENTITY['edition_id']}:{REVISION}"
    body = root_tei.find(N + "text/" + N + "body")
    if root_tei.tag != N + "TEI" or body is None or len(root_tei.findall(N + "text")) != 1:
        raise PipelineError("WEB Classic single TEI body differs")
    paths = _line_paths(body)
    inventory = _inventory(body, metadata, paths)
    policy = json.loads(bible.COMMON_SCHEMA_PATH.read_text(encoding="utf-8"))["x-ocd-projection-policy"]
    book_codes = load_book_codes(BOOK_CODES_PATH)
    rows, anchors = [], []
    nonverse = Counter()
    continuation = Counter()
    blank_verses = 0
    note_boundaries = 0
    chapters = 0
    for _name, member in _members(body, metadata):
        if member.get("type") == "paratext":
            nonverse["paratext-member"] += 1
            continue
        code = member.get("n")
        for child in member:
            if child.tag == N + "ab":
                nonverse[child.get("type") or "untyped"] += 1
                continue
            if child.tag != N + "div" or child.get("type") != "chapter":
                raise PipelineError(f"WEB Classic unsupported book child at {paths[child]}")
            chapter_label = child.get("n") or ""
            if not re.fullmatch(r"[1-9][0-9]*", chapter_label):
                raise PipelineError(f"WEB Classic invalid chapter at {paths[child]}")
            chapters += 1
            last = None
            for line in child:
                if line.tag != N + "ab":
                    raise PipelineError(f"WEB Classic unsupported chapter child at {paths[line]}")
                kind = line.get("type") or ""
                visible, repaired_boundary = _render_visible(line, paths, policy)
                note_boundaries += repaired_boundary
                if kind == "verse":
                    label = line.get("n") or ""
                    if not re.fullmatch(r"[1-9][0-9]*(?:-[1-9][0-9]*)?", label):
                        raise PipelineError(f"WEB Classic invalid verse label at {paths[line]}")
                    notes = bible._note_rows(line, paths, policy)
                    if not visible:
                        if not notes:
                            raise PipelineError(f"WEB Classic unsupported blank verse at {paths[line]}")
                        blank_verses += 1
                    number = len(rows) + 1
                    locator = {"kind": "verse", "book": code, "book_osis": member.get(X),
                               "chapter": int(chapter_label), "verse": label,
                               "versification": public_versification, "source_order": number,
                               "reference_origin": "tei-verse-components"}
                    try:
                        locator["reference"] = normalize_explicit_target(f"{member.get(X)}.{chapter_label}.{label}", book_codes=book_codes)
                    except PipelineError:
                        locator["reference_status"] = "unsupported-verse-components"
                    else:
                        locator["reference_status"] = "normalized-verse-components"
                    record_id = f"{IDENTITY['edition_id']}:verse-{number:06d}"
                    row = make_row(record_id=record_id, sequence=number, **IDENTITY, category="bible",
                                   language="en", text=visible, locator=locator,
                                   provenance={"edition_title": metadata["edition"].title},
                                   representation_revision=REVISION)
                    row.update(notes=notes, references=[], versification=public_versification)
                    rows.append(row)
                    anchors.append({"record_id": record_id, "tei_path": paths[line],
                                    "text_sha256": row_text_hash(visible), "source_order": number,
                                    "locator": copy.deepcopy(locator)})
                    last = number - 1
                elif kind in CONTINUATIONS and visible:
                    if last is None:
                        if (code, chapter_label, line.get("corresp"), visible) == CAPTION:
                            nonverse["sirach-51-opening-caption"] += 1
                            continue
                        raise PipelineError(f"WEB Classic orphan visible continuation at {paths[line]}")
                    row = rows[last]
                    row["text"] = " ".join((row["text"], visible)).strip()
                    row["notes"].extend(bible._note_rows(line, paths, policy))
                    anchors[last]["text_sha256"] = row_text_hash(row["text"])
                    continuation[kind] += 1
                elif kind in HEADING or kind in EMPTY_MARKERS or kind in CONTINUATIONS:
                    nonverse[kind] += 1
                else:
                    raise PipelineError(f"WEB Classic unaccounted source line at {paths[line]}: {kind}")
    if len(rows) != 38058 or chapters != 1402:
        raise PipelineError("WEB Classic verse/chapter coverage differs")
    inventory.update(chapters=chapters, continuation_blocks=sum(continuation.values()),
                     continuation_types=dict(sorted(continuation.items())),
                     blank_note_verses=blank_verses, note_boundary_spaces=note_boundaries,
                     nonverse_carriers=dict(sorted(nonverse.items())))
    bible._validate_rows(rows)
    result = {"mapping_version": MAPPING_VERSION, "assembler_version": bible.ASSEMBLER_VERSION,
              "master_sha256": MASTER_SHA, "scope_id": None, "rows": rows, "anchors": anchors,
              "inventory": inventory, "references": [],
              "warnings": [{"reason": "Verse rows include all visible source paragraph and poetry continuations; source headings, two paratext members, and exact private USFM/Strong markup remain in accepted master."}],
              "exclusions": [{"reason": "nonverse source carriers retained in accepted master", "counts": inventory["nonverse_carriers"]}],
              "unsupported": [], "source_binding": bible._source_binding(header),
              "authority": copy.deepcopy(metadata["authority"])}
    result["receipt"] = bible.build_bible_receipt(result, identity=IDENTITY, authority=result["authority"])
    return result


def project_accepted(root: Path, *, acceptance_path: Path) -> dict:
    metadata = _context(root, acceptance_path)
    result = _project(metadata)
    from .web_classic_native_bible_check import check_document
    errors = check_document(metadata["master_path"], result["rows"], result["receipt"], metadata=metadata)
    if errors:
        raise PipelineError("; ".join(errors))
    return result


def verify_accepted(root: Path, *, acceptance_path: Path, rows, receipt=None) -> list[str]:
    try:
        metadata = _context(root, acceptance_path)
        from .web_classic_native_bible_check import check_document
        return check_document(metadata["master_path"], rows, receipt, metadata=metadata)
    except (PipelineError, OSError, KeyError, TypeError, ValueError) as exc:
        return [str(exc)]
