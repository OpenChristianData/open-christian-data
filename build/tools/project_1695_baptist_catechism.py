"""Project the accepted 1695 Baptist Catechism electronic witness.

The generic catechism projector rejects this faithful LIB062 text vocabulary
(source-number labels and proof-bearing answers). The existing LIB062 native
mapper and its separate lxml verifier read the actual accepted master, so no
temporary text-changing view or shared mapping-policy change is used here.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from lxml import etree

from build.tei.lib062_json_catechisms_oracle import _strict_json
from ocd_kernel.projection.categories.catechisms import _validate_rows
from ocd_kernel.projection.categories.creeds_json_lib062_remaining import (
    TEI,
    _check_unit,
    _row,
)
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "1695-baptist-catechism"
FORM_ID = "1695-baptist-catechism-retained-electronic"
EDITION_ID = "1695-baptist-catechism-creeds-json"
SOURCE = Path("raw/Creeds.json/creeds/1695_baptist_catechism.json")
SOURCE_README = Path("raw/Creeds.json/README.md")
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
MASTER = EDITION / "master.tei.xml"
ACCEPTANCE = EDITION / "acceptance.json"
STATE = WORK / "state.json"
ORIGINAL = WORK / "integration/creeds-json-electronic-v1/inputs/package/content.tei.xml"
PUBLICATION = EDITION / "publication"
SOURCE_SHA256 = "24a665ee89840330e35f34dfca4ed28b2f7c9148deae4f9df1b39129d2b45438"
MASTER_SHA256 = "6295e2c9d53418441620f6db8416fc09c531fc8bb8b7864cb69d7bb7e61495b4"
ORIGINAL_SHA256 = "fd120d5691468dbaff6ad88e8e1864fd57864689ee141178a2ac1792a276ad13"
EMPTY_ANSWER_QUESTIONS = frozenset({43, 59, 60})


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _read(root: Path, relative: Path) -> bytes:
    return _io_path(root / relative).read_bytes()


def _json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _body(value: bytes) -> bytes:
    boundary = b"</teiHeader>"
    if value.count(boundary) != 1:
        raise ValueError("accepted master TEI header boundary differs")
    return value.split(boundary, 1)[1]


def _source_credit() -> bytes:
    return (
        "# Source and credit — 1695 Baptist Catechism\n\n"
        "This electronic text comes from [NonlinearFruit/Creeds.json]"
        "(https://github.com/NonlinearFruit/Creeds.json), retained member "
        "`creeds/1695_baptist_catechism.json`. The retained repository README "
        "places this member under the Unlicense; it is absent from the README's "
        "eight named exceptions. The member supplies a historical-source URL "
        "in its metadata; that link is source evidence, not independent rights "
        "clearance.\n\n"
        "This projection represents the accepted retained electronic witness. "
        "Full visual collation, human acceptance, rights clearance, and "
        "publication authorization remain open.\n"
    ).encode("utf-8")


def _source_units(document: dict[str, Any]) -> list[dict[str, Any]]:
    rows = document.get("Data")
    if not isinstance(rows, list) or len(rows) != 114:
        raise ValueError("retained source question census differs")
    for index, row in enumerate(rows, 1):
        if (not isinstance(row, dict) or set(row) != {"Number", "Question", "Answer", "AnswerWithProofs", "Proofs"}
                or row["Number"] != index or not isinstance(row["Question"], str) or not row["Question"]
                or not isinstance(row["Answer"], str) or not isinstance(row["AnswerWithProofs"], str)
                or not isinstance(row["Proofs"], list)):
            raise ValueError(f"retained source question {index} fields differ")
    blanks = [index for index, row in enumerate(rows, 1) if not row["Answer"]]
    if blanks != sorted(EMPTY_ANSWER_QUESTIONS) or any(not rows[index - 1]["AnswerWithProofs"] for index in blanks):
        raise ValueError("source empty Answer scope differs")
    if sum(len(row["Proofs"]) for row in rows) != 245:
        raise ValueError("source proof census differs")
    if sum(len(proof["References"]) for row in rows for proof in row["Proofs"]) != 433:
        raise ValueError("source reference census differs")
    return rows


def _project_rows(context: dict[str, Any], master_bytes: bytes) -> list[dict[str, Any]]:
    source_rows = _source_units(context["document"])
    root = ET.fromstring(master_bytes)
    body = root.find(f"{TEI}text/{TEI}body")
    if root.tag != TEI + "TEI" or body is None or len(body) != 1 or body[0].get("type") != "catechism":
        raise ValueError("accepted TEI catechism envelope differs")
    units = list(body[0])
    if len(units) != len(source_rows):
        raise ValueError("accepted TEI question census differs")
    result = []
    for index, (unit, source) in enumerate(zip(units, source_rows, strict=True), 1):
        if unit.tag != TEI + "div" or unit.get("type") != "question-unit":
            raise ValueError(f"accepted TEI question {index} structure differs")
        anchor = _check_unit(unit, source, index, parser="etree")
        row = _row(context, source, anchor, index)
        if index in EMPTY_ANSWER_QUESTIONS:
            row["text"] = f"Q: {source['Question']} A: {source['AnswerWithProofs']}"
        result.append(row)
    _validate_rows(result)
    return result


def verify_correspondence(context: dict[str, Any], rows: object, master_bytes: bytes) -> list[str]:
    """Independently parse the actual TEI and compare every source field and row."""
    try:
        source_rows = _source_units(context["document"])
        if not isinstance(rows, list) or len(rows) != len(source_rows):
            return ["public row census differs"]
        root = etree.fromstring(master_bytes, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        if root.getroottree().docinfo.doctype or root.xpath("//comment() | //processing-instruction()"):
            return ["accepted TEI contains an unsupported declaration or comment"]
        ns = {"t": TEI[1:-1]}
        units = root.xpath("./t:text/t:body/t:div[@type='catechism']/t:div[@type='question-unit']", namespaces=ns)
        if len(units) != len(source_rows):
            return ["accepted TEI question census differs"]
        for index, (source, unit, row) in enumerate(zip(source_rows, units, rows, strict=True), 1):
            anchor = _check_unit(unit, source, index, parser="lxml")
            proof_rows = [
                {"id": proof["Id"], "references": [{"raw": ref, "osis": [ref]} for ref in proof["References"]]}
                for proof in source["Proofs"]
            ]
            expected = {
                "work_id": WORK_ID,
                "textual_form_id": FORM_ID,
                "edition_id": EDITION_ID,
                "record_id": f"{EDITION_ID}:question-{index}",
                "sequence": index,
                "category": "catechisms",
                "language": "en",
                "text": f"Q: {source['Question']} A: {source['AnswerWithProofs'] if index in EMPTY_ANSWER_QUESTIONS else source['Answer']}",
                "representation_revision": context["representation_revision"],
                "provenance": {"edition_title": context["edition_title"]},
                "item_id": str(source["Number"]),
                "sort_key": index,
                "question": source["Question"],
                "answer": source["Answer"],
                "answer_with_proofs": source["AnswerWithProofs"],
                "proofs": proof_rows,
                "group": None,
                "sub_questions": None,
                "locator": {"kind": "question", "text_part": "body", "part_titles": [],
                            "divisions": [], "question": anchor, "source_order": index},
            }
            if row != expected:
                return [f"public row {index} differs from the retained source or accepted TEI"]
        _validate_rows(rows)
        return []
    except (ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc:
        return [str(exc)]


def _authority_context(root: Path = ROOT) -> dict[str, Any]:
    """Verify the exact accepted witness without running the row producer."""
    root = root.absolute()
    acceptance_bytes = _read(root, ACCEPTANCE)
    accepted = validate_acceptance(_io_path(root / ACCEPTANCE), root=_io_path(root))
    identity = accepted["identity"]
    if identity != {
        "work_id": WORK_ID,
        "textual_form_id": FORM_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": "1695-baptist-catechism-creeds-json-member",
    } or accepted["promotion"]["status"] != "promoted":
        raise ValueError("acceptance identity or promotion differs")
    state = json.loads(_read(root, STATE))
    targets = [target for target in state["targets"] if target["target_type"] == "edition" and target["target_id"] == EDITION_ID]
    if len(targets) != 1 or targets[0]["stage"] != "accepted":
        raise ValueError("canonical edition state is not accepted")
    source_bytes = _read(root, SOURCE)
    master_bytes = _read(root, MASTER)
    original_bytes = _read(root, ORIGINAL)
    if (_sha(source_bytes) != SOURCE_SHA256 or _sha(master_bytes) != MASTER_SHA256
            or _sha(original_bytes) != ORIGINAL_SHA256):
        raise ValueError("source, accepted master, or source-oracle candidate hash differs")
    if accepted["source"]["source_sha256"] != _sha(source_bytes) or accepted["promotion"]["master"]["sha256"] != _sha(master_bytes):
        raise ValueError("acceptance does not bind the current source and master")
    if _body(master_bytes) != _body(original_bytes):
        raise ValueError("accepted master text subtree differs from verified candidate")
    readme = _read(root, SOURCE_README).decode("utf-8")
    if "Unlicense" not in readme or "1695_baptist_catechism.json" not in readme:
        raise ValueError("retained provider README no longer supports source credit")
    document = _strict_json(source_bytes, "1695 Baptist Catechism retained member")
    if document["Metadata"].get("CreedFormat") != "Catechism":
        raise ValueError("retained source category differs")
    context = {
        "work_id": WORK_ID,
        "identity": {key: identity[key] for key in ("work_id", "textual_form_id", "edition_id")},
        "representation_revision": accepted["representation_revision"]["id"],
        "edition_title": "Retained Creeds.json electronic witness",
        "document": document,
    }
    return {
        "context": context,
        "master_bytes": master_bytes,
        "source_bytes": source_bytes,
        "acceptance_sha256": _sha(acceptance_bytes),
        "state_sha256": _sha(_read(root, STATE)),
        "source_readme_sha256": _sha(_read(root, SOURCE_README)),
        "original_sha256": _sha(original_bytes),
        "text_subtree_sha256": _sha(_body(master_bytes)),
    }


def prepare(root: Path = ROOT) -> dict[str, Any]:
    """Verify exact authority and derive rows without writing any files."""
    prepared = _authority_context(root)
    rows = _project_rows(prepared["context"], prepared["master_bytes"])
    errors = verify_correspondence(prepared["context"], rows, prepared["master_bytes"])
    if errors:
        raise ValueError(f"independent LIB062 row correspondence failed: {errors[0]}")
    prepared["rows"] = rows
    return prepared


def _accepted_path(root: Path, acceptance_path: Path) -> None:
    if Path(acceptance_path).resolve() != (Path(root).absolute() / ACCEPTANCE).resolve():
        raise ValueError("1695 Baptist Catechism route requires its exact acceptance path")


def _release_receipt(prepared: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "contract": "ocd-1695-baptist-catechism-accepted-release-v1",
        "identity": prepared["context"]["identity"],
        "source_sha256": _sha(prepared["source_bytes"]),
        "acceptance_sha256": prepared["acceptance_sha256"],
        "actual_master_sha256": _sha(prepared["master_bytes"]),
        "text_subtree_sha256": prepared["text_subtree_sha256"],
        "row_count": len(rows),
        "rows_sha256": _sha(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")),
        "empty_source_answer_questions": sorted(EMPTY_ANSWER_QUESTIONS),
        "readable_text_mapping": "For source-empty Answer at Q43, Q59, and Q60 only, text uses the source-attested AnswerWithProofs; answer preserves the empty Answer field.",
        "warnings": [],
        "rights": "uncleared",
        "publication": "unauthorized",
    }


def project_accepted(root: Path, *, acceptance_path: Path) -> dict[str, Any]:
    """Exact one-work adapter for the standard offline release assembler."""
    _accepted_path(root, acceptance_path)
    prepared = prepare(root)
    rows = prepared["rows"]
    return {"rows": rows, "receipt": _release_receipt(prepared, rows)}


def verify_accepted(root: Path, *, acceptance_path: Path, rows: object, receipt: object) -> list[str]:
    """Independently check release rows against retained JSON and accepted TEI."""
    try:
        _accepted_path(root, acceptance_path)
        prepared = _authority_context(root)
        if not isinstance(rows, list) or not isinstance(receipt, dict):
            return ["1695 Baptist Catechism release rows or receipt have the wrong type"]
        errors = verify_correspondence(prepared["context"], rows, prepared["master_bytes"])
        if errors:
            return errors
        if receipt != _release_receipt(prepared, rows):
            return ["1695 Baptist Catechism release receipt differs"]
        return []
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return [str(exc)]


def run(root: Path = ROOT) -> dict[str, Any]:
    prepared = prepare(root)
    rows = prepared["rows"]
    rows_bytes = b"".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n" for row in rows)
    credit = _source_credit()
    receipt = {
        "contract": "ocd-1695-baptist-catechism-projection-v1",
        "status": "projected",
        "category": "catechisms",
        "identity": prepared["context"]["identity"],
        "source_path": SOURCE.as_posix(),
        "source_sha256": _sha(prepared["source_bytes"]),
        "source_readme_sha256": prepared["source_readme_sha256"],
        "acceptance_sha256": prepared["acceptance_sha256"],
        "state_sha256": prepared["state_sha256"],
        "actual_master_sha256": _sha(prepared["master_bytes"]),
        "verified_candidate_sha256": prepared["original_sha256"],
        "text_subtree_sha256": prepared["text_subtree_sha256"],
        "view_transformation": "none; the actual accepted master is passed intact to the LIB062 native mapper",
        "empty_source_answer_questions": sorted(EMPTY_ANSWER_QUESTIONS),
        "readable_text_mapping": "For source-empty Answer at Q43, Q59, and Q60 only, text uses the source-attested AnswerWithProofs; answer preserves the empty Answer field.",
        "row_count": len(rows),
        "rows_sha256": _sha(rows_bytes),
        "source_credit_sha256": _sha(credit),
        "rights": "uncleared",
        "publication": "unauthorized",
    }
    publication = _io_path(root.absolute() / PUBLICATION)
    publication.mkdir(parents=True, exist_ok=True)
    (publication / "catechisms.jsonl").write_bytes(rows_bytes)
    (publication / "SOURCE_CREDIT.md").write_bytes(credit)
    (publication / "projection-receipt.json").write_bytes(_json(receipt))
    check = {
        "status": "pass",
        "method": "Separate lxml traversal compares every public Q/A field, proof, reference, source number, and row anchor against the retained JSON and actual accepted TEI master, including three source-empty Answer fields; accepted master text bytes also match the verified source-oracle candidate.",
        "row_count": len(rows),
        "rows_sha256": _sha(rows_bytes),
        "receipt_sha256": _sha(_json(receipt)),
        "actual_master_sha256": _sha(prepared["master_bytes"]),
        "source_sha256": _sha(prepared["source_bytes"]),
        "acceptance_sha256": prepared["acceptance_sha256"],
        "text_subtree_sha256": prepared["text_subtree_sha256"],
        "errors": [],
        "holds": ["full visual collation", "human acceptance", "rights clearance", "publication authorization"],
    }
    (publication / "independent-correspondence.json").write_bytes(_json(check))
    return {"receipt": receipt, "check": check}


if __name__ == "__main__":
    print(json.dumps(run()["receipt"], sort_keys=True))
