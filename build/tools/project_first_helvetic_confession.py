"""Project the installed First Helvetic Confession master and bind its visible source notice."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.doctrinal_documents import (
    project_accepted_doctrinal_documents,
    verify_accepted_doctrinal_documents,
)
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "first-helvetic-confession"
SOURCE = Path("raw/Creeds.json/creeds/first_helvetic_confession.json")
SOURCE_SHA256 = "69acace9d7ee0728d93abd000ad7c257be3284a63e45d3e6ba847854c42a9e04"
README = Path("raw/Creeds.json/README.md")
README_SHA256 = "caa2a135ceb89bdea2baf411bcb2897b03c34d24473de7c43ca373c9d9008bef"
EDITION = Path(
    "library/works/first-helvetic-confession/forms/"
    "first-helvetic-confession-retained-electronic/editions/first-helvetic-confession-creeds-json"
)
ACCEPTANCE = EDITION / "acceptance.json"
MASTER = EDITION / "master.tei.xml"
MASTER_SHA256 = "44eb246a0a5131c490edb81a6b5e196c433e1157ce045269964cff938e04fafa"
ACCEPTANCE_SHA256 = "bbdcfb36cc2c9d3379c986dea082b3fc23a63dc8d44b5eaca46839cae3a591da"
SOURCE_NOTE = Path("sources/doctrinal-documents/first-helvetic-confession/README.source.md")
PUBLIC_NOTICE = Path("data/doctrinal-documents/first-helvetic-confession/README.md")
SOURCE_CREDIT = EDITION / "SOURCE_CREDIT.md"
PUBLICATION = EDITION / "publication"
NOTICE_BINDING = Path("library/works/first-helvetic-confession/publication/notice-binding.json")


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_publication(root: Path = ROOT) -> dict[str, Any]:
    root = Path(root).resolve(strict=True)
    checks = {
        SOURCE: SOURCE_SHA256,
        README: README_SHA256,
        MASTER: MASTER_SHA256,
        ACCEPTANCE: ACCEPTANCE_SHA256,
    }
    for relative, expected in checks.items():
        if _sha(root / relative) != expected:
            raise ValueError(f"First Helvetic Confession authority binding changed: {relative}")
    for relative in (SOURCE_NOTE, PUBLIC_NOTICE, SOURCE_CREDIT):
        if not (root / relative).is_file():
            raise ValueError(f"First Helvetic Confession visible source credit is missing: {relative}")
    accepted = validate_acceptance(_io_path(root / ACCEPTANCE), root=_io_path(root))
    if accepted["identity"]["work_id"] != WORK_ID or accepted["promotion"]["status"] != "promoted":
        raise ValueError("First Helvetic Confession accepted identity or promotion differs")
    validate_state(_io_path(root / "library/works" / WORK_ID / "state.json"), root=_io_path(root))
    errors = validate_file(_io_path(root / MASTER))
    if errors:
        raise ValueError(f"First Helvetic Confession accepted master fails TEI P5: {errors[0]}")
    projection = project_accepted_doctrinal_documents(
        _io_path(root), acceptance_path=_io_path(root / ACCEPTANCE)
    )
    errors = verify_accepted_doctrinal_documents(
        _io_path(root), acceptance_path=_io_path(root / ACCEPTANCE),
        rows=projection["rows"], receipt=projection["receipt"],
    )
    if errors:
        raise ValueError(f"First Helvetic Confession independent correspondence failed: {errors[0]}")
    rows = projection["rows"]
    if len(rows) != 19 or [row["number"] for row in rows] != [str(i) for i in range(1, 20)]:
        raise ValueError("First Helvetic Confession projected thesis count or order differs")
    rows_bytes = b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in rows
    )
    binding = {
        "work_id": WORK_ID,
        "edition_id": accepted["identity"]["edition_id"],
        "acceptance_path": ACCEPTANCE.as_posix(),
        "preparation_status": "accepted master installed; source-bound notice prepared; release selection not recorded",
        "public_notices": [{
            "source_path": SOURCE_NOTE.as_posix(),
            "source_sha256": _sha(root / SOURCE_NOTE),
            "notice_path": PUBLIC_NOTICE.as_posix(),
            "notice_sha256": _sha(root / PUBLIC_NOTICE),
        }],
    }
    notice_texts_for_item(root, {"public_notices": binding["public_notices"]}, root / ACCEPTANCE)
    destination = root / PUBLICATION
    work_publication = (root / NOTICE_BINDING).parent
    if destination.exists() or work_publication.exists():
        raise FileExistsError("First Helvetic Confession publication destination already exists")
    destination.mkdir()
    work_publication.mkdir()
    rows_path = destination / "doctrinal-documents.jsonl"
    rows_path.write_bytes(rows_bytes)
    receipt_path = destination / "projection-receipt.json"
    _write_json(receipt_path, projection["receipt"])
    independent = {
        "schema_version": "ocd-first-helvetic-confession-correspondence-v1",
        "status": "pass", "errors": [],
        "source_sha256": SOURCE_SHA256,
        "source_readme_sha256": README_SHA256,
        "master_sha256": MASTER_SHA256,
        "acceptance_sha256": ACCEPTANCE_SHA256,
        "projection_view": "actual accepted master; no temporary transformation required",
        "projection_view_sha256": MASTER_SHA256,
        "row_count": len(rows),
        "rows_sha256": _sha(rows_path),
        "receipt_sha256": _sha(receipt_path),
        "method": "Accepted Creeds.json tree projector plus its independent source/master/row verifier.",
    }
    _write_json(destination / "independent-correspondence.json", independent)
    _write_json(root / NOTICE_BINDING, binding)
    return independent | {
        "rows_path": PUBLICATION.joinpath(rows_path.name).as_posix(),
        "receipt_path": PUBLICATION.joinpath(receipt_path.name).as_posix(),
        "correspondence_path": PUBLICATION.joinpath("independent-correspondence.json").as_posix(),
        "notice_binding_path": NOTICE_BINDING.as_posix(),
    }


if __name__ == "__main__":
    print(json.dumps(build_publication(), ensure_ascii=False, sort_keys=True))
