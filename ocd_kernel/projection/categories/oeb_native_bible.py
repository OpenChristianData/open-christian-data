"""Exact accepted OEB 2025.6 US/Cth witness projection candidate."""

from __future__ import annotations

from collections import Counter
import copy
from hashlib import sha256
from pathlib import Path
import re
from urllib.parse import unquote

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.envelope import make_row, row_text_hash
from ocd_kernel.projection.scripture_authority import BOOK_CODES_PATH, load_book_codes
from ocd_kernel.projection.scripture_targets import normalize_explicit_target

from ocd_kernel.projection.categories import bible

WORK = "open-english-bible"
IDENTITY = {"work_id": WORK, "textual_form_id": "oeb-english", "edition_id": "oeb-2025-6-us-cth"}
REVISION = "oeb-retained-install-20261003-v1"
SOURCE_SHA = "d800a3fbde13f7cf7418eb9e836d771b3add11448c8b6e7261130b6dd00140cd"
MASTER_SHA = "0399413acc6f940f8cb220a40732f7782bb841b0692c5cac194a1e55275d3aa7"
MEMBERS = "library/works/open-english-bible/forms/oeb-english/editions/oeb-2025-6-us-cth/source-member-set.json"
N = "{" + bible.TEI_NS + "}"
X = bible.XML_ID
WITNESSES = ("US", "Cth")
CONTINUATIONS = frozenset({"usfm-q", "usfm-q1", "usfm-q2", "usfm-q3", "usfm-p", "usfm-m", "usfm-pi", "source-continuation"})
BOOK_CODES = {
    "1JN":"1John", "HEB":"Heb", "EST":"Esth", "2TI":"2Tim", "COL":"Col", "2PE":"2Pet", "PHM":"Phlm", "MAT":"Matt", "MRK":"Mark", "GEN":"Gen", "MIC":"Mic", "JUD":"Jude", "JOL":"Joel", "HAG":"Hag", "REV":"Rev", "NAM":"Nah", "LUK":"Luke", "2JN":"2John", "PSA":"Ps", "ACT":"Acts", "ROM":"Rom", "MAL":"Mal", "AMO":"Amos", "EPH":"Eph", "JHN":"John", "HAB":"Hab", "1TH":"1Thess", "TIT":"Titus", "HOS":"Hos", "JON":"Jonah", "3JN":"3John", "2TH":"2Thess", "JOS":"Josh", "PHP":"Phil", "2CO":"2Cor", "ZEP":"Zeph", "1CO":"1Cor", "OBA":"Obad", "GAL":"Gal", "JAS":"Jas", "ZEC":"Zech", "1TI":"1Tim", "1PE":"1Pet", "RUT":"Ruth",
}


def _hash(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _context(root: Path, acceptance_path: Path) -> dict:
    metadata = bible._accepted_metadata(root, acceptance_path)
    accepted = metadata["acceptance"]
    if (metadata["identity"] != IDENTITY or metadata["language"] != "en"
            or accepted["representation_revision"]["id"] != REVISION
            or accepted["source"]["source_kind"] != "retained-member-set"
            or accepted["source"]["source_sha256"] != SOURCE_SHA
            or accepted["source"]["source_path"] != MEMBERS
            or len(accepted["scope"]["excluded_members"]) != 98
            or accepted["source"]["missing_members"] or accepted["source"]["unknown_members"]
            or len(accepted["scope"]["included_members"]) != 90
            or len(accepted["scope"]["expected_members"]) != 188
            or _hash(metadata["master_path"].read_bytes()) != MASTER_SHA):
        raise PipelineError("OEB exact accepted source, witness scope, or master differs")
    return metadata


def _source_member_order(root_tei, metadata, paths):
    if root_tei.tag != N + "TEI" or [child.tag for child in root_tei] != [N + "teiHeader", N + "text"]:
        raise PipelineError("OEB master requires one TEI header and one grouped text")
    outer = root_tei.find(N + "text")
    if outer is None or [child.tag for child in outer] != [N + "group"]:
        raise PipelineError("OEB master requires one text/group")
    group = outer[0]
    if len(group) != 2:
        raise PipelineError("OEB master requires exactly two witness branches")
    included = metadata["acceptance"]["scope"]["included_members"]
    expected_sources = []
    for member in included:
        match = re.fullmatch(r"raw/ebible/open-english-bible-2025\.6/(US|Cth)/usfm/usfm/([^/]+\.usfm)", member["path"])
        if not match or member["position"] < 1:
            raise PipelineError("OEB accepted textual member path differs")
        expected_sources.append((match.group(1), match.group(2)))
    observed_sources = []
    bodies = []
    for branch, witness in zip(group, WITNESSES, strict=True):
        if (branch.tag != N + "text" or branch.get("type") != "witness"
                or branch.get("n") != witness or branch.get(X) != f"oeb-2025-6-{witness.lower()}"
                or [child.tag for child in branch] != [N + "body"]):
            raise PipelineError(f"OEB {witness} witness identity or body differs")
        body = branch[0]
        if len(body) != 45:
            raise PipelineError(f"OEB {witness} requires 44 books and one front page")
        bodies.append((witness, body))
        kinds = Counter()
        for unit in body:
            if unit.tag != N + "div" or unit.get("type") not in {"book", "front-matter"}:
                raise PipelineError(f"OEB {witness} source member carrier differs at {paths[unit]}")
            kinds[unit.get("type")] += 1
            pointer = re.fullmatch(r"source-usfm:(US|Cth)/([^/#]+)", unit.get("corresp") or "")
            if pointer is None or pointer.group(1) != witness:
                raise PipelineError(f"OEB {witness} source member pointer differs at {paths[unit]}")
            observed_sources.append((witness, unquote(pointer.group(2))))
            if unit.get("type") == "book" and (unit.get("n") not in BOOK_CODES
                    or unit.get(X) != f"{witness}-{unit.get('n')}"):
                raise PipelineError(f"OEB {witness} book identity differs at {paths[unit]}")
        if kinds != Counter({"book": 44, "front-matter": 1}):
            raise PipelineError(f"OEB {witness} book/front member count differs")
    if observed_sources != expected_sources or len(set(observed_sources)) != 90:
        raise PipelineError("OEB source-ordered US/Cth member crosswalk differs")
    return bodies


def _project(metadata: dict) -> dict:
    path = metadata["master_path"]
    root_tei, raw = bible._read(path)
    if _hash(raw) != MASTER_SHA:
        raise PipelineError("OEB exact accepted master digest differs")
    paths = bible._paths(root_tei)
    parents = bible._parents(root_tei)
    header = bible._header(root_tei)
    bible._validate_accepted_header(header, metadata)
    bodies = _source_member_order(root_tei, metadata, paths)
    versification = bible._accepted_versification(header, metadata)
    if versification != f"source-native:retained-member-set:{SOURCE_SHA}":
        raise PipelineError("OEB accepted source-native versification differs")
    public_versification = f"source-native:retained-member-set:{IDENTITY['edition_id']}:{REVISION}"
    try:
        policy = __import__("json").loads(bible.COMMON_SCHEMA_PATH.read_text(encoding="utf-8"))["x-ocd-projection-policy"]
    except (OSError, KeyError, ValueError) as exc:
        raise PipelineError("OEB controlled render policy unavailable") from exc
    known_books = load_book_codes(BOOK_CODES_PATH)
    rows, anchors = [], []
    inventory = {"witnesses": 2, "textual_members": 90, "books": 88, "front_members": 2,
                 "chapters": 0, "verses": 0, "continuation_blocks": 0,
                 "blank_footnote_verses": 0, "nonverse_carriers": {}}
    excluded = Counter()
    for witness, body in bodies:
        for node in body.iter():
            pointer = node.get("corresp")
            if pointer is not None and not pointer.startswith(f"source-usfm:{witness}/"):
                raise PipelineError(f"OEB {witness} source pointer crosses witness at {paths[node]}")
        for book in body:
            if book.get("type") != "book":
                excluded["front-member"] += 1
                continue
            book_code = book.get("n")
            osis = BOOK_CODES[book_code]
            verses_by_id = {}
            if osis not in known_books:
                raise PipelineError(f"OEB unrecognized mapped book code: {book_code}")
            for chapter in book.iter():
                if chapter.tag != N + "div" or chapter.get("type") != "chapter":
                    continue
                chapter_label = chapter.get("n") or ""
                if not re.fullmatch(r"[1-9][0-9]*", chapter_label):
                    raise PipelineError(f"OEB invalid source chapter at {paths[chapter]}")
                chapter_no = int(chapter_label)
                inventory["chapters"] += 1
                preceding = None
                for child in chapter.iter():
                    if child.tag == N + "ab" and child.get("type") == "verse":
                        label = child.get("n") or ""
                        if not re.fullmatch(r"[1-9][0-9]*", label):
                            raise PipelineError(f"OEB invalid verse label at {paths[child]}")
                        preceding = {"node": child, "text": [bible._render(child, paths, policy=policy)],
                                     "notes": bible._note_rows(child, paths, policy), "label": label}
                        if not preceding["text"][0]:
                            if (len(child) != 1 or child[0].tag != N + "note"
                                    or child[0].get("type") != "usfm-footnote"
                                    or not preceding["notes"]):
                                raise PipelineError(f"OEB empty verse without a source footnote at {paths[child]}")
                            inventory["blank_footnote_verses"] += 1
                        sequence = len(rows) + 1
                        locator = {"kind": "verse", "book": book_code, "book_osis": osis,
                                   "chapter": chapter_no, "verse": label,
                                   "versification": public_versification, "source_order": sequence,
                                   "witness": witness, "reference_origin": "tei-verse-components"}
                        try:
                            locator["reference"] = normalize_explicit_target(
                                f"{osis}.{chapter_no}.{label}", book_codes=known_books)
                        except PipelineError:
                            locator["reference_status"] = "unsupported-verse-components"
                        else:
                            locator["reference_status"] = "normalized-verse-components"
                        record_id = f"{IDENTITY['edition_id']}:{witness}:verse-{sequence:06d}"
                        row = make_row(record_id=record_id, sequence=sequence, **IDENTITY,
                                       category="bible", language="en", text=preceding["text"][0],
                                       locator=locator, provenance={"edition_title": metadata["edition"].title},
                                       representation_revision=REVISION)
                        row.update(notes=preceding["notes"], references=[], versification=public_versification)
                        rows.append(row)
                        anchors.append({"record_id": record_id, "tei_path": paths[child],
                                        "text_sha256": row_text_hash(row["text"]),
                                        "source_order": sequence, "locator": copy.deepcopy(locator)})
                        if child.get(X) in verses_by_id or not child.get(X):
                            raise PipelineError(f"OEB duplicate or missing verse ID at {paths[child]}")
                        verses_by_id[child.get(X)] = sequence - 1
                        inventory["verses"] += 1
                    elif child.tag == N + "ab" and child.get("type") in CONTINUATIONS:
                        wording = bible._render(child, paths, policy=policy)
                        if wording:
                            if preceding is None:
                                raise PipelineError(f"OEB source continuation precedes verse at {paths[child]}")
                            target_index = len(rows) - 1
                            if child.get("type") == "source-continuation":
                                pointers = [node for node in child if node.tag == N + "ptr" and node.get("type") == "preceding-verse"]
                                if len(pointers) != 1 or not re.fullmatch(rf"#{witness}-[A-Z0-9]+-line-[1-9][0-9]*", pointers[0].get("target") or ""):
                                    raise PipelineError(f"OEB source-continuation pointer differs at {paths[child]}")
                                target_index = verses_by_id.get(pointers[0].get("target")[1:], -1)
                                if target_index < 0 or rows[target_index]["locator"]["chapter"] != chapter_no:
                                    raise PipelineError(f"OEB source-continuation does not bind a same-chapter verse at {paths[child]}")
                            row = rows[target_index]
                            row["text"] = " ".join((row["text"], wording)).strip()
                            row["notes"].extend(bible._note_rows(child, paths, policy))
                            anchors[target_index]["text_sha256"] = row_text_hash(row["text"])
                            inventory["continuation_blocks"] += 1
                    elif child.tag == N + "ab" and child.get("type") != "verse":
                        kind = child.get("type") or "untyped"
                        excluded[kind] += 1
                        if bible._render(child, paths, policy=policy) and kind not in CONTINUATIONS:
                            raise PipelineError(f"OEB unaccounted nonverse source wording at {paths[child]}")
    if (inventory["chapters"] != 1130 or inventory["verses"] != 27828
            or inventory["continuation_blocks"] != 12164
            or inventory["blank_footnote_verses"] != 38):
        raise PipelineError(f"OEB source carrier counts differ: {inventory}")
    inventory["nonverse_carriers"] = dict(sorted(excluded.items()))
    bible._validate_rows(rows)
    projection = {"mapping_version": "ocd-oeb-two-witness-source-native-v1",
                  "assembler_version": bible.ASSEMBLER_VERSION, "master_sha256": MASTER_SHA,
                  "scope_id": None, "rows": rows, "anchors": anchors, "inventory": inventory,
                  "references": [], "warnings": [{"reason": "Source US/Cth witnesses remain distinct; headings, front pages, source markers, and electronic support remain in accepted master."},
                                                 {"reason": "38 source-native footnote-only verse carriers retain their source footnotes."}],
                  "exclusions": [{"reason": "nonverse source carriers retained in accepted master", "counts": inventory["nonverse_carriers"]}],
                  "unsupported": [], "source_binding": bible._source_binding(header),
                  "authority": copy.deepcopy(metadata["authority"])}
    projection["receipt"] = bible.build_bible_receipt(
        projection, identity=IDENTITY, authority=projection["authority"])
    return projection


def project_accepted(root: Path, *, acceptance_path: Path) -> dict:
    metadata = _context(root, acceptance_path)
    result = _project(metadata)
    from .oeb_native_bible_check import check_document
    errors = check_document(metadata["master_path"], result["rows"], result["receipt"],
                            metadata=metadata)
    if errors:
        raise PipelineError("; ".join(errors))
    return result


def verify_accepted(root: Path, *, acceptance_path: Path, rows, receipt=None) -> list[str]:
    try:
        metadata = _context(root, acceptance_path)
        from .oeb_native_bible_check import check_document
        return check_document(metadata["master_path"], rows, receipt, metadata=metadata)
    except (PipelineError, OSError, KeyError, TypeError, ValueError) as exc:
        return [str(exc)]
