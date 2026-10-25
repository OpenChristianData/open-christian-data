"""Prepare source-bound future MGH/BSB data credit for Ansbert hymn; do not publish."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from ocd_kernel.release.notices import _utf8_markdown
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
HOME = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb752-ansbert-hymn-public-notice-20260928-v3")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb752-ansbert-hymn-stage-20260928-v3")
RECEIPT = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb752-ansbert-hymn-stage-20260928-v3/stage-receipt.json")
RECEIPT_SHA = "463a3d5af5955997b9b3dc15b1e2de6c2ce8255c1d5b1496c10cf70b510ba19f"
SOURCE = Path("raw/openmgh/bsb00000752/tei/bsb00000752.xml")
SOURCE_SHA = "620b80ade431a814ebf41296cdf88476d9a39741cdba1925c0cd75fb9772c98a"
WORK_ID = "ymnus-de-sancto-ansberto"
NOTE = Path("sources/openmgh/ymnus-de-sancto-ansberto/README.source.md")
NOTICE = Path("data/structured-text/ymnus-de-sancto-ansberto/README.md")


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
        raise ValueError("Ansbert hymn stage receipt differs")
    if _sha(_io_path(ROOT / SOURCE).read_bytes()) != SOURCE_SHA:
        raise ValueError("Ansbert hymn retained XML differs")
    edition = (Path("library/works") / WORK_ID / "forms" / f"{WORK_ID}-openmgh-retained"
               / "editions" / f"{WORK_ID}-openmgh-electronic")
    credit = _io_path(STAGE / edition / "README.source.md").read_bytes()
    if b"Monumenta Germaniae Historica" not in credit or b"Bavarian State Library" not in credit:
        raise ValueError("staged work-local MGH/BSB credit differs")
    note = (
        "# Electronic source for ymnus-de-sancto-ansberto\n\n"
        f"The exact retained textual witness is `{SOURCE.as_posix()}` (SHA-256 `{SOURCE_SHA}`). "
        "The retained ZIP is an acquisition package, not another text witness. The selected "
        "electronic hymn is source work division 19, native part 2. The two preceding "
        "prose parts belong to Vita Ansberti and remain excluded. All 70 line and two "
        "page milestones stay in source order. No print witness was collated.\n\n"
        "The source header asks distributors of the electronic file or derivatives to name "
        "Monumenta Germaniae Historica (MGH) and the Bavarian State Library, Munich (BSB). "
        "Its CC BY 4.0 statement concerns added annotations; it describes the underlying "
        "text as believed public domain. This note does not independently establish rights. "
        f"For any public data release, install the human-visible notice at `{NOTICE.as_posix()}` "
        "and bind both exact hashes through `public_notices`.\n"
    ).encode("utf-8")
    notice = (
        "# Source and rights notice for ymnus-de-sancto-ansberto\n\n"
        "Electronic file source: Monumenta Germaniae Historica (MGH) and the Bavarian State "
        "Library, Munich (BSB), digital MGH bsb00000752.\n\n"
        "The retained source states that annotations added by MGH and BSB are distributed "
        "under [Creative Commons Attribution 4.0 International]"
        "(http://creativecommons.org/licenses/by/4.0/). It says MGH and BSB do not claim "
        "rights to the text itself, which they believe is in the public domain.\n"
    ).encode("utf-8")
    _utf8_markdown(note, label="Ansbert hymn source note")
    rendered = _utf8_markdown(notice, label="Ansbert hymn future data notice")
    issues = _scan(rendered, "Ansbert hymn future data notice")
    if issues:
        raise ValueError(f"private material in future data notice: {issues}")
    _put(ROOT / NOTE, note)
    _put(HOME / NOTICE, notice)
    index = {
        "contract": "ocd-openmgh-bsb752-ansbert-hymn-public-notice-handoff-v1",
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
