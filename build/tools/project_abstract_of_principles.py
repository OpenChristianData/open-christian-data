"""Project the accepted Abstract of Principles master to work-local public rows."""

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
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "abstract-of-principles"
SOURCE = Path("raw/Creeds.json/creeds/abstract_of_principles.json")
SOURCE_SHA256 = "3fcb6447826ccbbf3b8b2c23bacc769f6ad0df8b5449f2a0c7925623afed242c"
README = Path("raw/Creeds.json/README.md")
README_SHA256 = "caa2a135ceb89bdea2baf411bcb2897b03c34d24473de7c43ca373c9d9008bef"
EDITION = Path(
    "library/works/abstract-of-principles/forms/"
    "abstract-of-principles-retained-electronic/editions/"
    "abstract-of-principles-creeds-json"
)
ACCEPTANCE = EDITION / "acceptance.json"
MASTER = EDITION / "master.tei.xml"
EXPECTED_MASTER_SHA256 = "f5b39fdfd9acd5f13c12a7e8b34800272681b8f4153e1fd65cffb738c661de1b"
EXPECTED_ACCEPTANCE_SHA256 = "bc7544cfd5b3c2b4693b979f7084d3908d477a6b27f13b27f58413aaf564dc79"
EXPECTED_ROW_COUNT = 20


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _credit() -> str:
    return """# Source credit and rights status

This electronic edition is reconstructed from the retained
`NonlinearFruit/Creeds.json` member `raw/Creeds.json/creeds/abstract_of_principles.json`.

- Provider repository: https://github.com/NonlinearFruit/Creeds.json
- Retained source SHA-256: `3fcb6447826ccbbf3b8b2c23bacc769f6ad0df8b5449f2a0c7925623afed242c`
- Retained README SHA-256: `caa2a135ceb89bdea2baf411bcb2897b03c34d24473de7c43ca373c9d9008bef`
- Represented scope: all 20 ordered articles in the retained provider rendering.

The source and public notice handoff is recorded in
`sources/doctrinal-documents/abstract-of-principles/README.source.md`; its
human-visible release notice is
`data/doctrinal-documents/abstract-of-principles/README.md`.

The retained README says that documents outside its eight named copyright
exceptions are offered under the Unlicense. It lists *Abstract of Principles*
and does not name it as an exception. The official provider repository showed
the same terms when checked on 2026-09-30. The member's `SourceAttribution`
value, “Public Domain,” is retained provider metadata rather than independent
rights clearance. Human rights review and publication authorization remain
required.
"""


def build_publication(
    root: Path = ROOT,
    *,
    output_dir: Path | None = None,
    credit_path: Path | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    acceptance_path = root / ACCEPTANCE
    master_path = root / MASTER
    source_path = root / SOURCE
    readme_path = root / README
    if _sha(source_path) != SOURCE_SHA256 or _sha(readme_path) != README_SHA256:
        raise ValueError("retained source or README binding changed")
    if _sha(master_path) != EXPECTED_MASTER_SHA256 or _sha(acceptance_path) != EXPECTED_ACCEPTANCE_SHA256:
        raise ValueError("accepted master or acceptance binding changed")
    accepted = validate_acceptance(_io_path(acceptance_path), root=_io_path(root))
    validate_state(_io_path(root / "library/works" / WORK_ID / "state.json"), root=_io_path(root))
    errors = validate_file(_io_path(master_path))
    if errors:
        raise ValueError(f"accepted master fails TEI P5: {errors[0]}")
    projection = project_accepted_doctrinal_documents(
        _io_path(root), acceptance_path=_io_path(acceptance_path)
    )
    correspondence = verify_accepted_doctrinal_documents(
        _io_path(root),
        acceptance_path=_io_path(acceptance_path),
        rows=projection["rows"],
        receipt=projection["receipt"],
    )
    if correspondence:
        raise ValueError(f"independent correspondence failed: {correspondence[0]}")
    if len(projection["rows"]) != EXPECTED_ROW_COUNT:
        raise ValueError("projected article count differs")
    destination = Path(output_dir) if output_dir is not None else root / EDITION / "publication"
    notice = Path(credit_path) if credit_path is not None else root / EDITION / "SOURCE_CREDIT.md"
    destination.mkdir(parents=True, exist_ok=True)
    rows_path = destination / "doctrinal-documents.jsonl"
    rows_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for row in projection["rows"]
        ),
        encoding="utf-8",
        newline="\n",
    )
    _write_json(destination / "projection-receipt.json", projection["receipt"])
    independent = {
        "schema_version": "ocd-abstract-of-principles-correspondence-v1",
        "status": "pass",
        "errors": [],
        "source_sha256": SOURCE_SHA256,
        "source_readme_sha256": README_SHA256,
        "master_sha256": _sha(master_path),
        "acceptance_sha256": _sha(acceptance_path),
        "projection_view_sha256": _sha(master_path),
        "projection_view": "actual accepted master; no temporary transformation required",
        "row_count": len(projection["rows"]),
        "rows_sha256": _sha(rows_path),
        "receipt_sha256": _sha(destination / "projection-receipt.json"),
        "method": "Accepted Creeds.json tree projector plus its independent source/master/row verifier.",
    }
    _write_json(destination / "independent-correspondence.json", independent)
    notice.parent.mkdir(parents=True, exist_ok=True)
    notice.write_text(_credit(), encoding="utf-8", newline="\n")
    return independent | {
        "rows_path": rows_path.as_posix(),
        "receipt_path": (destination / "projection-receipt.json").as_posix(),
        "correspondence_path": (destination / "independent-correspondence.json").as_posix(),
        "credit_path": notice.as_posix(),
        "accepted_identity": accepted["identity"],
    }


if __name__ == "__main__":
    print(json.dumps(build_publication(), ensure_ascii=False, indent=2))
