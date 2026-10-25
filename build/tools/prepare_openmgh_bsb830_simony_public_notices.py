"""Prepare source-bound public attribution notices for seven bsb830 poems."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tools import freeze_openmgh_bsb830_simony_seven as freezing
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
HOME = Path("D:/Library/Open Christian Data/candidate-reviews/bsb830-simony-seven-public-notices-20260927-v1")
FREEZE_SHA = "a41feeab825f74141dc534fe79c3f36d666ba2ed6825f4c1909e6b3315cb88f4"


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def main() -> None:
    index_path = HOME / "notice-index.json"
    if _io_path(index_path).exists():
        raise ValueError("bsb830 public notice handoff already exists")
    freeze_bytes = _io_path(freezing.FREEZE).read_bytes()
    frozen = json.loads(freeze_bytes)
    if (_sha(freeze_bytes) != FREEZE_SHA or frozen.get("contract") != freezing.CONTRACT
            or len(frozen.get("works", [])) != 7):
        raise ValueError("bsb830 seven-work freeze differs")
    items = []
    for item in frozen["works"]:
        work_id = item["work_id"]
        source_path = Path("sources/openmgh") / work_id / "README.source.md"
        notice_path = Path("data/structured-text") / work_id / "README.md"
        source_note = (
            f"# Electronic source for {work_id}\n\n"
            f"The retained text source is `{item['source_path']}` (SHA-256 `{item['source_sha256']}`). "
            "The ZIP is an acquisition package, not a second text witness. The source TEI header credits "
            "Monumenta Germaniae Historica (MGH) and the Bavarian State Library, Munich (BSB); "
            "its CC BY 4.0 statement covers their added annotations and disclaims a claim on the text itself. "
            "It expressly asks distributors of copies or derivatives to name MGH and BSB as the file source.\n\n"
            f"For a public data release, include the corresponding visible notice at `{notice_path.as_posix()}` "
            "and bind its exact hash with this source note through `public_notices`. The notice is a "
            "source attribution handoff, not a rights-clearance or publication decision.\n"
        ).encode("utf-8")
        target = ROOT / source_path
        if _io_path(target).exists():
            if _io_path(target).read_bytes() != source_note:
                raise ValueError(f"bsb830 source note differs: {target}")
        else:
            _io_path(target).parent.mkdir(parents=True, exist_ok=True)
            _io_path(target).write_bytes(source_note)
        notice = (
            f"# Source and rights notice for {work_id}\n\n"
            "Electronic file source: Monumenta Germaniae Historica (MGH) and the Bavarian State Library, "
            "Munich (BSB), digital MGH, MGH Ldl 3, bsb00000830.\n\n"
            "The retained source states that the annotations added by MGH and BSB are distributed under "
            "[Creative Commons Attribution 4.0 International](http://creativecommons.org/licenses/by/4.0/). "
            "It says MGH and BSB do not claim rights to the text itself, which they believe is in the public domain.\n"
        ).encode("utf-8")
        external = HOME / notice_path
        _io_path(external).parent.mkdir(parents=True, exist_ok=True)
        _io_path(external).write_bytes(notice)
        items.append(dict(work_id=work_id, source_path=source_path.as_posix(), source_sha256=_sha(source_note),
                          notice_path=notice_path.as_posix(), notice_sha256=_sha(notice),
                          external_notice_path=external.as_posix(), retained_xml_sha256=item["source_sha256"]))
    index = dict(contract="ocd-openmgh-bsb830-simony-seven-public-notice-handoff-v1",
                 status="future-release-notice-only", freeze_sha256=FREEZE_SHA, items=items)
    _io_path(index_path).write_bytes(json.dumps(index, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n")
    print(json.dumps(dict(index=index_path.as_posix(), index_sha256=_sha(_io_path(index_path).read_bytes()),
                          items=len(items)), sort_keys=True))


if __name__ == "__main__":
    main()
