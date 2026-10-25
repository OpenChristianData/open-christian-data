"""Prepare the future data-path MGH/BSB credit for bsb754 Vita abbatum."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tools import prepare_openmgh_bsb754_vita_abbatum as source
from ocd_kernel.release.notices import _utf8_markdown
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb754-vita-abbatum-freeze-20260928-v1.json"
FREEZE_SHA = "268916f2c8742973f1d029509c2008c9213cdd1a41250a7acc237b4ce73deccf"
HOME = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb754-vita-abbatum-public-notices-20260928-v2")


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _put(path: Path, data: bytes) -> None:
    target = _io_path(path)
    if target.exists():
        if target.read_bytes() != data:
            raise ValueError(f"bsb754 Vita abbatum notice path differs: {path}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def prepare() -> dict:
    freeze_bytes = _io_path(FREEZE).read_bytes()
    frozen = json.loads(freeze_bytes)
    if (_sha(freeze_bytes) != FREEZE_SHA
            or frozen.get("status") != "review-ready-staged-only"
            or frozen.get("work_id") != source.WORK_ID
            or frozen.get("edition_id") != source.EDITION_ID
            or frozen.get("other_edition_id") != source.OTHER_EDITION_ID
            or frozen.get("source_path") != source.SOURCE.as_posix()
            or frozen.get("source_sha256") != source.SOURCE_SHA256
            or _sha(_io_path(ROOT / source.SOURCE).read_bytes()) != source.SOURCE_SHA256):
        raise ValueError("bsb754 Vita abbatum reviewed freeze differs")
    stage = Path(frozen["stage_root"])
    if _sha(_io_path(Path(frozen["stage_receipt"])).read_bytes()) != frozen["stage_receipt_sha256"]:
        raise ValueError("bsb754 Vita abbatum stage receipt differs")
    edition = (Path("library/works") / source.WORK_ID / "forms" / source.FORM_ID /
               "editions" / source.EDITION_ID)
    credit = _io_path(stage / edition / "README.source.md").read_bytes()
    if b"Monumenta Germaniae Historica" not in credit or b"Bavarian State Library" not in credit:
        raise ValueError("bsb754 staged source credit differs")
    source_path = Path("sources/openmgh") / source.WORK_ID / "README.source.md"
    notice_path = Path("data/structured-text") / source.WORK_ID / "README.md"
    source_note = (
        f"# Electronic source for {source.WORK_ID}, bsb00000754 edition\n\n"
        f"The retained text source is `{source.SOURCE.as_posix()}` (SHA-256 `{source.SOURCE_SHA256}`). "
        "Its ZIP is acquisition packaging, not another text witness. "
        "This edition selects the complete native `div type=work` in bsb00000754, "
        "from `bsb00000754_00339_35` through `bsb00000754_00346_5`, ending `Amen.` "
        "The separately acquired bsb00000750 edition has a distinct three-part source carrier "
        "and remains unaccepted by this stage. No print witness was collated.\n\n"
        "The source header asks distributors of the electronic file or derivatives to name "
        "Monumenta Germaniae Historica (MGH) and the Bavarian State Library, Munich (BSB). "
        "Its CC BY 4.0 statement concerns added annotations; it describes the underlying "
        "text as believed public domain. This note does not independently establish rights. "
        f"For any public data release, install the human-visible notice at `{notice_path.as_posix()}` "
        "and bind both exact hashes through `public_notices`.\n"
    ).encode("utf-8")
    notice = (
        f"# Source and rights notice for {source.WORK_ID} (bsb00000754 edition)\n\n"
        "Electronic file source: Monumenta Germaniae Historica (MGH) and the Bavarian State "
        "Library, Munich (BSB), digital MGH bsb00000754.\n\n"
        "The retained source states that annotations added by MGH and BSB are distributed "
        "under [Creative Commons Attribution 4.0 International]"
        "(http://creativecommons.org/licenses/by/4.0/). It says MGH and BSB do not claim "
        "rights to the text itself, which they believe is in the public domain.\n"
    ).encode("utf-8")
    _utf8_markdown(source_note, label="bsb754 Vita abbatum source note")
    rendered = _utf8_markdown(notice, label="bsb754 Vita abbatum future data notice")
    if issues := _scan(rendered, "bsb754 Vita abbatum future data notice"):
        raise ValueError(f"private material in future notice: {issues}")
    _put(ROOT / source_path, source_note)
    _put(HOME / notice_path, notice)
    entry = {
        "work_id": source.WORK_ID, "edition_id": source.EDITION_ID,
        "stage_receipt_sha256": frozen["stage_receipt_sha256"],
        "source_path": source_path.as_posix(), "source_sha256": _sha(source_note),
        "notice_path": notice_path.as_posix(), "notice_sha256": _sha(notice),
        "external_notice_path": (HOME / notice_path).as_posix(),
    }
    index = {
        "contract": "ocd-openmgh-bsb754-vita-abbatum-public-notices-v1",
        "status": "future-release-notices-only", "freeze_sha256": FREEZE_SHA,
        "items": [entry],
    }
    content = (json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    _put(HOME / "notice-index.json", content)
    return {"index": (HOME / "notice-index.json").as_posix(), "index_sha256": _sha(content),
            "items": [{"work_id": entry["work_id"], "edition_id": entry["edition_id"],
                       "source_sha256": entry["source_sha256"],
                       "notice_sha256": entry["notice_sha256"]}]}


if __name__ == "__main__":
    print(json.dumps(prepare(), sort_keys=True))
