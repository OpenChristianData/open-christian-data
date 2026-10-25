"""Record the exact Virgin Mary accepted-master projection and release holds."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.acceptance import validate_acceptance


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "pg77576-ignatius-virgin-mary"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms/pg77576-ignatius-virgin-mary-english/editions/pg77576-ignatius-virgin-mary-pg77576-edition"
EVIDENCE = WORK / "integration/pg77576-html-v1/publication-v3"
SOURCE_NOTE = Path("sources/gutenberg") / WORK_ID / "README.source.md"
PUBLIC_NOTICE = Path("data/structured-text") / WORK_ID / "README.md"
MASTER_SHA = "ad7b9d02f056797d62f1bc2b7b79867b769b106168108ad7285a654491117665"
ACCEPTANCE_SHA = "978cd563f2048cd03ef657df1dad8004cdc8391707e822c4c2125947b99ab220"
PG_1E1_NOTICE = (
    "This eBook is for the use of anyone anywhere in the United States and most other parts of the world "
    "at no cost and with almost no restrictions whatsoever. You may copy it, give it away or re-use it under "
    "the terms of the [Project Gutenberg License](https://www.gutenberg.org/policy/license) included with "
    "this eBook or online at [www.gutenberg.org](https://www.gutenberg.org). If you are not located in the "
    "United States, you'll have to check the laws of the country where you are located before using this ebook."
)


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _write_once(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise PipelineError(f"existing publication evidence differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def prepare() -> dict:
    root = ROOT.resolve(strict=True)
    acceptance = root / EDITION / "acceptance.json"
    master = root / EDITION / "master.tei.xml"
    if _sha(acceptance.read_bytes()) != ACCEPTANCE_SHA or _sha(master.read_bytes()) != MASTER_SHA:
        raise PipelineError("installed acceptance or master differs from guarded install")
    validated = validate_acceptance(acceptance, root=root)
    if validated["identity"]["work_id"] != WORK_ID or validated["promotion"]["status"] != "promoted":
        raise PipelineError("accepted work identity differs")
    projected = project_accepted_prose(root, acceptance_path=acceptance)
    rows, receipt = projected["rows"], projected["receipt"]
    errors = verify_accepted_prose(root, acceptance_path=acceptance, rows=rows, receipt=receipt)
    if errors or len(rows) != 2 or receipt["master_sha256"] != MASTER_SHA:
        raise PipelineError(f"actual-master independent projection failed: {errors[:3]}")
    note_binding = dict(source_path=SOURCE_NOTE.as_posix(),
                        source_sha256=_sha((root / SOURCE_NOTE).read_bytes()),
                        notice_path=PUBLIC_NOTICE.as_posix(),
                        notice_sha256=_sha((root / PUBLIC_NOTICE).read_bytes()))
    visible = notice_texts_for_item(root, {"work_id": WORK_ID, "public_notices": [note_binding]}, acceptance)
    if (len(visible) != 1 or PG_1E1_NOTICE not in visible[0]
            or "[original electronic formats](https://www.gutenberg.org/ebooks/77576)" not in visible[0]):
        raise PipelineError("source-bound public notice lacks the required license notice or original-format access")
    rows_bytes = b"".join(_json_bytes(row) for row in rows)
    receipt_bytes = _json_bytes(receipt)
    empty_rows = [dict(record_id=row["record_id"], sequence=row["sequence"],
                       locator=row["locator"], structure_present=bool(row["structure"]))
                  for row in rows if not row["text"].strip()]
    if empty_rows:
        raise PipelineError(f"public prose row has empty readable text: {empty_rows}")
    _write_once(root / EVIDENCE / "rows.jsonl", rows_bytes)
    _write_once(root / EVIDENCE / "projection-receipt.json", receipt_bytes)
    result = dict(contract="ocd-pg77576-virgin-mary-publication-technical-v3",
                  work_id=WORK_ID, status="technically-projected",
                  acceptance_sha256=ACCEPTANCE_SHA, master_sha256=MASTER_SHA,
                  category="prose", row_count=len(rows),
                  rows_path=(EVIDENCE / "rows.jsonl").as_posix(), rows_sha256=_sha(rows_bytes),
                  receipt_path=(EVIDENCE / "projection-receipt.json").as_posix(),
                  receipt_sha256=_sha(receipt_bytes), independent_verifier_errors=errors,
                  empty_readable_text_rows=empty_rows, cvw_linked=False,
                  public_notice=note_binding, public_notice_binding_check="pass",
                  human_verification="not-recorded", rights_clearance="not-recorded",
                  publication_authorization="not-recorded")
    _write_once(root / EVIDENCE / "technical-readiness.json", _json_bytes(result))
    return result


if __name__ == "__main__":
    print(json.dumps(prepare(), sort_keys=True))
