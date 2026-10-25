"""Prepare future data-path MGH/BSB credits for the source-bound three whole-volume works."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tools import prepare_openmgh_three_whole as source
from ocd_kernel.release.notices import _utf8_markdown
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "plans/2026-09-22-source-preflight/openmgh-three-whole-freeze-20260928-v1.json"
FREEZE_SHA = "81105af841b006a19ad71e7bbfdde318d91a868664f3d3054c73010d1c7c85e2"
HOME = Path("D:/Library/Open Christian Data/candidate-reviews/three-whole-public-notices-20260928-v1")


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _put(path: Path, data: bytes) -> None:
    target = _io_path(path)
    if target.exists():
        if target.read_bytes() != data:
            raise ValueError(f"three-volume notice path differs: {path}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def prepare() -> dict:
    freeze_bytes = _io_path(FREEZE).read_bytes()
    frozen = json.loads(freeze_bytes)
    if (_sha(freeze_bytes) != FREEZE_SHA
            or frozen.get("status") != "review-ready-staged-only"
            or {item["work_id"] for item in frozen.get("works", [])} != set(source.WORKS)):
        raise ValueError("three-volume reviewed freeze differs")
    entries = []
    for pin in frozen["works"]:
        work_id = pin["work_id"]
        spec = source.SOURCES[work_id]
        xml, package, acquired_receipt = source._paths(work_id)
        if (pin["source_path"] != xml.as_posix() or pin["source_sha256"] != spec["sha256"]
                or pin["package_path"] != package.as_posix()
                or pin["package_sha256"] != spec["zip_sha256"]
                or pin["acquisition_receipt"] != acquired_receipt.as_posix()
                or pin["acquisition_receipt_sha256"] != spec["receipt_sha256"]
                or _sha(_io_path(ROOT / xml).read_bytes()) != spec["sha256"]):
            raise ValueError(f"three-volume retained source differs: {work_id}")
        stage = Path(pin["stage_root"])
        receipt_bytes = _io_path(Path(pin["stage_receipt"])).read_bytes()
        if _sha(receipt_bytes) != pin["stage_receipt_sha256"]:
            raise ValueError(f"three-volume stage receipt differs: {work_id}")
        edition = (Path("library/works") / work_id / "forms" / f"{work_id}-openmgh-retained" /
                   "editions" / f"{work_id}-openmgh-electronic")
        credit = _io_path(stage / edition / "README.source.md").read_bytes()
        if b"Monumenta Germaniae Historica" not in credit or b"Bavarian State Library" not in credit:
            raise ValueError(f"three-volume staged source credit differs: {work_id}")
        source_path = Path("sources/openmgh") / work_id / "README.source.md"
        notice_path = Path("data/structured-text") / work_id / "README.md"
        source_note = (
            f"# Electronic source for {work_id}\n\n"
            f"The retained text source is `{xml.as_posix()}` (SHA-256 `{spec['sha256']}`). "
            "Its ZIP is acquisition packaging, not another text witness. "
            f"This work selects the sole complete `div type=work` in {spec['bsb']}, "
            f"from heading `{spec['heading_id']}` through final line `{spec['end_id']}`, "
            f"retaining all {spec['parts']} native parts. "
            "No print witness was collated.\n\n"
            "The source header asks distributors of the electronic file or derivatives to name "
            "Monumenta Germaniae Historica (MGH) and the Bavarian State Library, Munich (BSB). "
            "Its CC BY 4.0 statement concerns added annotations; it describes the underlying "
            "text as believed public domain. This note does not independently establish rights. "
            f"For any public data release, install the human-visible notice at `{notice_path.as_posix()}` "
            "and bind both exact hashes through `public_notices`.\n"
        ).encode("utf-8")
        notice = (
            f"# Source and rights notice for {work_id}\n\n"
            "Electronic file source: Monumenta Germaniae Historica (MGH) and the Bavarian State "
            f"Library, Munich (BSB), digital MGH {spec['bsb']}.\n\n"
            "The retained source states that annotations added by MGH and BSB are distributed "
            "under [Creative Commons Attribution 4.0 International]"
            "(http://creativecommons.org/licenses/by/4.0/). It says MGH and BSB do not claim "
            "rights to the text itself, which they believe is in the public domain.\n"
        ).encode("utf-8")
        _utf8_markdown(source_note, label=f"{work_id} source note")
        rendered = _utf8_markdown(notice, label=f"{work_id} future data notice")
        if issues := _scan(rendered, f"{work_id} future data notice"):
            raise ValueError(f"private material in {work_id} notice: {issues}")
        _put(ROOT / source_path, source_note)
        _put(HOME / notice_path, notice)
        entries.append({
            "work_id": work_id, "stage_receipt_sha256": pin["stage_receipt_sha256"],
            "source_path": source_path.as_posix(), "source_sha256": _sha(source_note),
            "notice_path": notice_path.as_posix(), "notice_sha256": _sha(notice),
            "external_notice_path": (HOME / notice_path).as_posix(),
        })
    index = {
        "contract": "ocd-openmgh-three-whole-public-notices-v1",
        "status": "future-release-notices-only", "freeze_sha256": FREEZE_SHA,
        "items": entries,
    }
    content = (json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    _put(HOME / "notice-index.json", content)
    return {"index": (HOME / "notice-index.json").as_posix(), "index_sha256": _sha(content),
            "items": [{"work_id": item["work_id"], "source_sha256": item["source_sha256"],
                       "notice_sha256": item["notice_sha256"]} for item in entries]}


if __name__ == "__main__":
    print(json.dumps(prepare(), sort_keys=True))
