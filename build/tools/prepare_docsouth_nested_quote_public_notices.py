"""Prepare source-bound, human-visible public notice handoff without publishing."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tools import freeze_docsouth_tei2_nested_quote as freezing
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
HOME = Path("D:/Library/Open Christian Data/candidate-reviews/docsouth-nested-public-notices-20260927-v1")


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def main() -> None:
    index_path = HOME / "notice-index.json"
    if _io_path(index_path).exists():
        raise ValueError("DocSouth public notice handoff already exists")
    frozen = json.loads(_io_path(freezing.FREEZE).read_bytes())
    if frozen.get("contract") != freezing.CONTRACT or len(frozen.get("works", [])) != 3:
        raise ValueError("DocSouth three-work freeze differs")
    items = []
    for item in frozen["works"]:
        work_id = item["work_id"]
        source_path = Path("sources/docsouth") / work_id / "README.source.md"
        notice_path = Path("data/structured-text") / work_id / "README.md"
        content = (
            f"# Electronic source for {work_id}\n\n"
            f"The retained electronic source is `{item['source_path']}` (SHA-256 `{item['source_sha256']}`). "
            "This TEI.2 text was prepared by Documenting the American South at the University of North Carolina "
            "at Chapel Hill. Its header names the transcribers, encoders, and National Endowment for the Humanities "
            "funding; preserve those credits in the TEI master.\n\n"
            "The source labels its rights as [No Copyright - United States]"
            "(http://rightsstatements.org/vocab/NoC-US/1.0/) with status `unknown`, and says no copyright "
            "determination was made for other countries. This notice does not grant worldwide rights clearance.\n\n"
            f"For any public data release, include the corresponding visible notice at `{notice_path.as_posix()}` "
            "and bind its exact hash with this source note through `public_notices`.\n"
        ).encode("utf-8")
        target = ROOT / source_path
        if _io_path(target).exists():
            if _io_path(target).read_bytes() != content:
                raise ValueError(f"DocSouth source note differs: {target}")
        else:
            _io_path(target).parent.mkdir(parents=True, exist_ok=True)
            _io_path(target).write_bytes(content)
        notice = (
            f"# Source and rights notice for {work_id}\n\n"
            "Electronic text source: Documenting the American South, University of North Carolina at Chapel Hill. "
            "The source header credits its named transcribers and encoders and National Endowment for the Humanities funding.\n\n"
            "The source states [No Copyright - United States](http://rightsstatements.org/vocab/NoC-US/1.0/) "
            "and makes no determination under the laws of other countries.\n"
        ).encode("utf-8")
        external = HOME / notice_path
        _io_path(external).parent.mkdir(parents=True, exist_ok=True)
        _io_path(external).write_bytes(notice)
        items.append(dict(work_id=work_id, source_path=source_path.as_posix(), source_sha256=_sha(content),
                          notice_path=notice_path.as_posix(), notice_sha256=_sha(notice),
                          external_notice_path=external.as_posix(), retained_xml_sha256=item["source_sha256"],
                          retained_rights_text_sha256=item["source_rights_text_sha256"]))
    index = dict(contract="ocd-docsouth-tei2-nested-quote-public-notice-handoff-v1",
                 status="future-release-notice-only", freeze_sha256=_sha(_io_path(freezing.FREEZE).read_bytes()),
                 items=items)
    _io_path(index_path).write_bytes(json.dumps(index, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n")
    print(json.dumps(dict(index=index_path.as_posix(), index_sha256=_sha(_io_path(index_path).read_bytes()),
                          items=len(items)), sort_keys=True))


if __name__ == "__main__":
    main()
