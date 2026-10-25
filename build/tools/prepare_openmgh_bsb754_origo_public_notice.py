"""Prepare Origo's future source-bound MGH/BSB public data notice."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "plans/2026-09-22-source-preflight/openmgh-exact-bsb754-origo-freeze-20260927.json"
FREEZE_SHA = "c0f6fef6817f0d5abd8c62a5b5ef01b143d8d35aed1b9b1b532c43a8b1d4dfba"
HOME = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb754-origo-public-notice-20260927-v1")
WORK_ID = "origo-francorum"
EDITION = (Path("library/works") / WORK_ID / "forms/origo-francorum-openmgh-retained"
           / "editions/origo-francorum-openmgh-electronic")
MASTER_SHA = "2ef7242d2cdeb2477068d318989f6de88cb883978591ba61ce3699c93f0622df"
CREDIT_SHA = "51b33d5c5d5a69297ca88ba482f50d43ec74829ab2b205f4c42e43bee563d8c9"


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def prepare() -> dict:
    freeze_bytes = _io_path(FREEZE).read_bytes()
    frozen = json.loads(freeze_bytes)
    if (_sha(freeze_bytes) != FREEZE_SHA or frozen["works"][0]["work_id"] != WORK_ID
            or len(frozen["works"]) != 1 or frozen["works"][0]["accepted_master_sha256"] != MASTER_SHA):
        raise ValueError("Origo reviewed freeze differs")
    source = frozen["source"]
    package = frozen["package"]
    if (_sha(_io_path(ROOT / source["path"]).read_bytes()) != source["sha256"]
            or _sha(_io_path(ROOT / package["path"]).read_bytes()) != package["sha256"]
            or _sha(_io_path(ROOT / EDITION / "master.tei.xml").read_bytes()) != MASTER_SHA):
        raise ValueError("Origo source, package, or installed master differs")
    credit = _io_path(ROOT / EDITION / "README.source.md").read_bytes()
    if (_sha(credit) != CREDIT_SHA or b"Monumenta Germaniae Historica" not in credit
            or b"Bavarian State Library" not in credit):
        raise ValueError("Origo work-local source credit differs")
    source_path = Path("sources/openmgh/origo-francorum/README.source.md")
    notice_path = Path("data/structured-text/origo-francorum/README.md")
    source_note = (
        "# Electronic source for origo-francorum\n\n"
        f"The retained text source is `{source['path']}` (SHA-256 `{source['sha256']}`). "
        "The ZIP is an acquisition package, not a second text witness. The source TEI header credits "
        "Monumenta Germaniae Historica (MGH) and the Bavarian State Library, Munich (BSB); "
        "its CC BY 4.0 statement covers their added annotations and disclaims a claim on the text itself. "
        "It expressly asks distributors of copies or derivatives to name MGH and BSB as the file source.\n\n"
        f"For a public data release, include the corresponding visible notice at `{notice_path.as_posix()}` "
        "and bind its exact hash with this source note through `public_notices`. This is an attribution "
        "handoff, not a rights-clearance or publication decision.\n"
    ).encode("utf-8")
    notice = (
        "# Source and rights notice for origo-francorum\n\n"
        "Electronic file source: Monumenta Germaniae Historica (MGH) and the Bavarian State Library, "
        "Munich (BSB), digital MGH, MGH SS rer. Merov. 7, bsb00000754.\n\n"
        "The retained source states that the annotations added by MGH and BSB are distributed under "
        "[Creative Commons Attribution 4.0 International](http://creativecommons.org/licenses/by/4.0/). "
        "It says MGH and BSB do not claim rights to the text itself, which they believe is in the public domain.\n"
    ).encode("utf-8")
    note_target = ROOT / source_path
    if _io_path(note_target).exists() and _io_path(note_target).read_bytes() != source_note:
        raise ValueError("Origo existing source note differs")
    _io_path(note_target).parent.mkdir(parents=True, exist_ok=True)
    _io_path(note_target).write_bytes(source_note)
    external = HOME / notice_path
    if _io_path(external).exists() and _io_path(external).read_bytes() != notice:
        raise ValueError("Origo existing external notice differs")
    _io_path(external).parent.mkdir(parents=True, exist_ok=True)
    _io_path(external).write_bytes(notice)
    item = dict(work_id=WORK_ID, source_path=source_path.as_posix(), source_sha256=_sha(source_note),
                notice_path=notice_path.as_posix(), notice_sha256=_sha(notice),
                external_notice_path=external.as_posix(), retained_xml_sha256=source["sha256"])
    index = dict(contract="ocd-openmgh-bsb754-origo-public-notice-handoff-v1",
                 status="future-release-notice-only", freeze_sha256=FREEZE_SHA, items=[item])
    index_path = HOME / "notice-index.json"
    content = (json.dumps(index, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    if _io_path(index_path).exists() and _io_path(index_path).read_bytes() != content:
        raise ValueError("Origo existing notice index differs")
    _io_path(index_path).write_bytes(content)
    return dict(index=index_path.as_posix(), index_sha256=_sha(content), item=item)


def main() -> None:
    print(json.dumps(prepare(), sort_keys=True))


if __name__ == "__main__":
    main()
