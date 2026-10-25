"""Prepare source-bound future MGH/BSB data credit for Reimundi; do not publish."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from ocd_kernel.release.notices import _utf8_markdown
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
HOME = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb720-reimundi-public-notice-20260928-v2")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb720-reimundi-stage-20260928-v2")
RECEIPT = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb720-reimundi-stage-receipt-20260928-v2.json")
RECEIPT_SHA = "cc4eb6c13d532bc269e4e2c2f4cb2aa68e76663336579760b9f3fe9c1ea33c37"
SOURCE = Path("raw/openmgh/bsb00000720/tei/bsb00000720.xml")
SOURCE_SHA = "2a096d80ae17e4f701fdce91585d77afb5d69e385167a46f45173e887dc38ce5"
WORK_ID = "lambertus-epitaphium-reimundi"
NOTE = Path("sources/openmgh/lambertus-epitaphium-reimundi/README.source.md")
NOTICE = Path("data/structured-text/lambertus-epitaphium-reimundi/README.md")


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _put(path: Path, data: bytes) -> None:
    target = _io_path(path)
    if target.exists():
        if target.read_bytes() != data:
            raise ValueError(f"future notice path differs: {path}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def prepare() -> dict:
    receipt_bytes = _io_path(RECEIPT).read_bytes()
    receipt = json.loads(receipt_bytes)
    if (_sha(receipt_bytes) != RECEIPT_SHA or receipt.get("work_id") != WORK_ID
            or receipt.get("status") != "staged-only" or receipt.get("installation") != "not-performed"
            or receipt.get("source_sha256") != SOURCE_SHA):
        raise ValueError("Reimundi stage receipt differs")
    if _sha(_io_path(ROOT / SOURCE).read_bytes()) != SOURCE_SHA:
        raise ValueError("Reimundi retained XML differs")
    edition = (Path("library/works") / WORK_ID / "forms" / f"{WORK_ID}-openmgh-retained"
               / "editions" / f"{WORK_ID}-openmgh-electronic")
    credit = _io_path(STAGE / edition / "README.source.md").read_bytes()
    if b"Monumenta Germaniae Historica" not in credit or b"Bavarian State Library" not in credit:
        raise ValueError("staged work-local MGH/BSB credit differs")
    note = (
        "# Electronic source for lambertus-epitaphium-reimundi\n\n"
        f"The exact retained textual witness is `{SOURCE.as_posix()}` (SHA-256 `{SOURCE_SHA}`). "
        "The retained ZIP is an acquisition package, not another text witness. The selected "
        "electronic poem is child 123 through 130 of the volume's Carmina block, including "
        "internal page break `bsb00000720_00273` at child 126. The shared Carmina heading "
        "and adjacent poems are not part of this work. No print witness was collated.\n\n"
        "The source header asks distributors of the electronic file or derivatives to name "
        "Monumenta Germaniae Historica (MGH) and the Bavarian State Library, Munich (BSB). "
        "Its CC BY 4.0 statement concerns added annotations; it describes the underlying "
        "text as believed public domain. This note does not independently establish rights. "
        f"For any public data release, install the human-visible notice at `{NOTICE.as_posix()}` "
        "and bind both exact hashes through `public_notices`.\n"
    ).encode("utf-8")
    notice = (
        "# Source and rights notice for lambertus-epitaphium-reimundi\n\n"
        "Electronic file source: Monumenta Germaniae Historica (MGH) and the Bavarian State "
        "Library, Munich (BSB), digital MGH bsb00000720.\n\n"
        "The retained source states that annotations added by MGH and BSB are distributed "
        "under [Creative Commons Attribution 4.0 International]"
        "(http://creativecommons.org/licenses/by/4.0/). It says MGH and BSB do not claim "
        "rights to the text itself, which they believe is in the public domain.\n"
    ).encode("utf-8")
    _utf8_markdown(note, label="Reimundi source note")
    rendered = _utf8_markdown(notice, label="Reimundi future data notice")
    issues = _scan(rendered, "Reimundi future data notice")
    if issues:
        raise ValueError(f"private material in future data notice: {issues}")
    _put(ROOT / NOTE, note)
    _put(HOME / NOTICE, notice)
    index = {
        "contract": "ocd-openmgh-bsb720-reimundi-public-notice-handoff-v1",
        "status": "future-release-notice-only",
        "work_id": WORK_ID,
        "stage_receipt_sha256": RECEIPT_SHA,
        "retained_xml_path": SOURCE.as_posix(),
        "retained_xml_sha256": SOURCE_SHA,
        "source_path": NOTE.as_posix(),
        "source_sha256": _sha(note),
        "notice_path": NOTICE.as_posix(),
        "notice_sha256": _sha(notice),
        "external_notice_path": (HOME / NOTICE).as_posix(),
    }
    content = (json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    _put(HOME / "notice-index.json", content)
    return {"index": (HOME / "notice-index.json").as_posix(), "index_sha256": _sha(content),
            "notice_sha256": _sha(notice), "source_sha256": _sha(note)}


if __name__ == "__main__":
    print(json.dumps(prepare(), sort_keys=True))
