"""Prepare future visible MGH/BSB notice for two distinct Passio electronic editions."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tei import openmgh_passio_dormientium_dual as source
from build.tools import freeze_openmgh_passio_dormientium_dual as freezing
from build.tools.install_openmgh_passio_dormientium_dual import FREEZE_SHA
from ocd_kernel.tei.install_accepted import _io_path


HOME = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-passio-dormientium-dual-public-notice-20260928-v2")


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def main() -> None:
    if _io_path(HOME / "notice-index.json").exists():
        raise ValueError("Passio public notice handoff already exists")
    raw = _io_path(freezing.FREEZE).read_bytes()
    frozen = json.loads(raw)
    if (_sha(raw) != FREEZE_SHA or frozen.get("contract") != freezing.CONTRACT
            or {item["code"] for item in frozen.get("editions", [])} != set(source.WITNESSES)):
        raise ValueError("Passio reviewed freeze differs")
    work_id = source.WORK_ID
    source_note_path = Path("sources/openmgh") / work_id / "README.source.md"
    notice_path = Path("data/structured-text") / work_id / "README.md"
    listed = "\n".join(f"- `{item['code']}`: `{item['source_path']}` (SHA-256 `{item['source_sha256']}`)."
                       for item in sorted(frozen["editions"], key=lambda e: e["code"]))
    source_note = (
        f"# Electronic sources for {work_id}\n\n"
        "Two distinct retained openMGH electronic editions supply the separately staged masters:\n"
        f"{listed}\n\n"
        "Each extracted XML is text authority; its corresponding ZIP is acquisition packaging. Both "
        "source headers identify Monumenta Germaniae Historica (MGH) and the Bavarian State Library, "
        "Munich (BSB), and ask distributors of copies or derivatives to name them as the file source. "
        "Their CC BY 4.0 statement covers added annotations and says the editors claim no rights in "
        "the text itself. For a public release, bind the exact visible notice at "
        f"`{notice_path.as_posix()}` through `public_notices`. This is an attribution handoff, not "
        "a rights-clearance or publication decision.\n"
    ).encode("utf-8")
    target = source.ROOT / source_note_path
    if _io_path(target).exists():
        if _io_path(target).read_bytes() != source_note:
            raise ValueError("Passio existing source note differs")
    else:
        _io_path(target).parent.mkdir(parents=True, exist_ok=True)
        _io_path(target).write_bytes(source_note)
    notice = (
        f"# Source and rights notice for {work_id}\n\n"
        "Electronic file sources: Monumenta Germaniae Historica (MGH) and the Bavarian State Library, "
        "Munich (BSB), digital MGH. The two retained editions are MGH SS rer. Merov. 7 "
        "(`bsb00000754`) and MGH SS rer. Merov. 1,2 (`bsb00050862`). They are distinct electronic "
        "editions and are displayed separately.\n\n"
        "Both electronic source headers state that MGH and BSB annotations are distributed under "
        "[Creative Commons Attribution 4.0 International](http://creativecommons.org/licenses/by/4.0/). "
        "They say MGH and BSB claim no rights in the text itself, which they believe is in the public domain.\n"
    ).encode("utf-8")
    external = HOME / notice_path
    _io_path(external).parent.mkdir(parents=True, exist_ok=True)
    _io_path(external).write_bytes(notice)
    index = dict(contract="ocd-openmgh-passio-dormientium-dual-public-notice-handoff-v1",
                 status="future-release-notice-only", freeze_sha256=FREEZE_SHA,
                 work_id=work_id, source_path=source_note_path.as_posix(),
                 source_sha256=_sha(source_note), notice_path=notice_path.as_posix(),
                 notice_sha256=_sha(notice), external_notice_path=external.as_posix(),
                 editions=[dict(code=item["code"], retained_xml_sha256=item["source_sha256"])
                           for item in sorted(frozen["editions"], key=lambda e: e["code"])])
    _io_path(HOME / "notice-index.json").write_bytes(
        (json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    print(json.dumps(dict(index=(HOME / "notice-index.json").as_posix(),
                          index_sha256=_sha(_io_path(HOME / "notice-index.json").read_bytes())), sort_keys=True))


if __name__ == "__main__":
    main()
