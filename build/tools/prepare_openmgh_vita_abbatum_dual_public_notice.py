"""Prepare one future MGH/BSB data notice for the two accepted Vita editions."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tools import install_openmgh_bsb750_vita_abbatum as vita
from ocd_kernel.release.notices import _utf8_markdown
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
HOME = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-vita-abbatum-dual-public-notice-20260930-v1")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb750-vita-abbatum-stage-20260930-v3")
STAGE_RECEIPT_SHA = "70e77b85a4187f13a6d7a8dd4fa53f537f4d78ba8943091bac9ace0cc430bd43"
OLD_NOTE_SHA = "0e2e3315e0e1b1a7ab8741fdb33ce84058424d2e7a6a1f3a742da793381c94cf"
SOURCE_NOTE = Path("sources/openmgh") / vita.WORK_ID / "README.source.md"
NOTICE = Path("data/structured-text") / vita.WORK_ID / "README.md"


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _put(path: Path, data: bytes, *, previous_sha: str | None = None) -> None:
    target = Path(_io_path(path))
    if target.exists():
        existing = target.read_bytes()
        if existing == data:
            return
        if previous_sha is None or _sha(existing) != previous_sha:
            raise ValueError(f"unreviewed notice preimage: {path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def prepare() -> dict:
    if vita._sha(STAGE / "stage-receipt.json") != STAGE_RECEIPT_SHA:
        raise ValueError("installed bsb750 stage receipt changed")
    record = json.loads(_io_path(STAGE / "stage-receipt.json").read_bytes())
    if record["work_id"] != vita.WORK_ID or vita._files(ROOT / "library/works" / vita.WORK_ID) != record["after"]:
        raise ValueError("installed two-edition work differs from reviewed stage")
    work = Path("library/works") / vita.WORK_ID / "forms" / vita.FORM_ID / "editions"
    editions = []
    for code, source_path, source_sha, master_sha in (
        ("bsb00000750", vita.SOURCE, vita.SOURCE_SHA, record["master_sha256"]),
        ("bsb00000754", vita.OTHER_SOURCE, vita.OTHER_SOURCE_SHA,
         "45a3b85edf85686524bb35acdbf8408ea72523e34c4805b37c7590de506c27f0"),
    ):
        edition_id = f"{vita.WORK_ID}-{code}-electronic"
        edition = work / edition_id
        if (vita._sha(ROOT / source_path) != source_sha
                or vita._sha(ROOT / edition / "master.tei.xml") != master_sha
                or not Path(_io_path(ROOT / edition / "acceptance.json")).is_file()):
            raise ValueError(f"accepted {code} authority differs")
        editions.append({"edition_id": edition_id, "source_path": source_path.as_posix(),
                         "source_sha256": source_sha, "master_sha256": master_sha})
    source_note = (
        f"# Electronic sources for {vita.WORK_ID}\n\n"
        "Two distinct retained openMGH electronic editions have accepted TEI masters:\n\n"
        f"- bsb00000750 (MGH SS rer. Merov. 3): `{vita.SOURCE.as_posix()}` "
        f"(SHA-256 `{vita.SOURCE_SHA}`). Its accepted scope is the first native part, "
        "ending at `bsb00000750_00189_21`; the separately headed Probus verses and "
        "abbot catalog remain outside that selection.\n"
        f"- bsb00000754 (MGH SS rer. Merov. 7): `{vita.OTHER_SOURCE.as_posix()}` "
        f"(SHA-256 `{vita.OTHER_SOURCE_SHA}`). Its accepted scope is the complete "
        "native Vita abbatum work division, ending at `bsb00000754_00346_5`.\n\n"
        "Each extracted XML is text authority; its ZIP is acquisition packaging. "
        "Both electronic source headers ask distributors of copies or derivatives "
        "to name Monumenta Germaniae Historica (MGH) and the Bavarian State Library, "
        "Munich (BSB). Their CC BY 4.0 statement concerns added annotations; they "
        "describe the underlying text as believed public domain. No print witness "
        "was collated, and this note does not establish rights clearance. For a "
        f"public release, bind the human-visible `{NOTICE.as_posix()}` through "
        "`public_notices` using the exact hashes below.\n"
    ).encode("utf-8")
    notice = (
        f"# Source and rights notice for {vita.WORK_ID}\n\n"
        "Electronic file sources: Monumenta Germaniae Historica (MGH) and the Bavarian "
        "State Library, Munich (BSB), digital MGH. The two retained electronic editions "
        "are MGH SS rer. Merov. 3 (bsb00000750) and MGH SS rer. Merov. 7 "
        "(bsb00000754).\n\n"
        "Both electronic source headers state that annotations added by MGH and BSB "
        "are distributed under [Creative Commons Attribution 4.0 International]"
        "(http://creativecommons.org/licenses/by/4.0/). They say MGH and BSB claim "
        "no rights in the text itself, which they believe is in the public domain.\n"
    ).encode("utf-8")
    _utf8_markdown(source_note, label="Vita abbatum dual source note")
    rendered = _utf8_markdown(notice, label="Vita abbatum future data notice")
    if issues := _scan(rendered, "Vita abbatum future data notice"):
        raise ValueError(f"private material in future notice: {issues}")
    _put(ROOT / SOURCE_NOTE, source_note, previous_sha=OLD_NOTE_SHA)
    _put(HOME / NOTICE, notice)
    index = {"contract": "ocd-openmgh-vita-abbatum-dual-public-notice-v1",
             "status": "future-release-notice-only", "work_id": vita.WORK_ID,
             "stage_receipt_sha256": STAGE_RECEIPT_SHA,
             "source_path": SOURCE_NOTE.as_posix(), "source_sha256": _sha(source_note),
             "notice_path": NOTICE.as_posix(), "notice_sha256": _sha(notice),
             "external_notice_path": (HOME / NOTICE).as_posix(), "editions": editions}
    _put(HOME / "notice-index.json", vita._json(index))
    return {"index": (HOME / "notice-index.json").as_posix(),
            "index_sha256": vita._sha(HOME / "notice-index.json"),
            "source_note_sha256": index["source_sha256"],
            "notice_sha256": index["notice_sha256"]}


if __name__ == "__main__":
    print(json.dumps(prepare(), sort_keys=True))
