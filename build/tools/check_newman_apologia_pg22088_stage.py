"""Read-only preinstall guard for a frozen PG22088 review stage."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tools.stage_newman_apologia_pg22088 import EDITION, ROOT, SOURCE_RELATIVE, STAGE_PARENT, WORK
from ocd_kernel.tei.install_accepted import _files, _io_path


def check(stage: Path, receipt_sha256: str) -> dict:
    stage = stage.absolute()
    if (stage.parent.resolve(strict=True) != STAGE_PARENT.resolve(strict=True)
            or not stage.name.startswith("na-s")):
        raise ValueError("PG22088 guard requires the exact external review stage")
    receipt_bytes = _io_path(stage / "stage-receipt.json").read_bytes()
    if sha256(receipt_bytes).hexdigest() != receipt_sha256:
        raise ValueError("PG22088 frozen receipt digest differs")
    receipt = json.loads(receipt_bytes)
    if (receipt["contract"] != "ocd-newman-apologia-pg22088-stage-v1"
            or receipt["work_id"] != "newman-apologia-pro-vita-sua"
            or receipt["stage_root"] != stage.as_posix()
            or receipt["native_rows"] != 1):
        raise ValueError("PG22088 frozen receipt identity differs")
    if _files(stage / WORK) != receipt["after"]:
        raise ValueError("PG22088 staged work files differ")
    evidence = stage / WORK / "integration/pg22088-v1/inputs"
    for filename, field in (("work-text.tei.xml", "work_text_sha256"),
                            ("provider-header.tei.xml", "provider_header_sha256"),
                            ("provider-license.tei.xml", "provider_license_sha256")):
        if sha256(_io_path(evidence / filename).read_bytes()).hexdigest() != receipt[field]:
            raise ValueError(f"PG22088 partition evidence differs: {filename}")
    master = _io_path(stage / EDITION / "master.tei.xml").read_bytes()
    work_text = _io_path(evidence / "work-text.tei.xml").read_bytes()
    if (sha256(master).hexdigest() != receipt["accepted_master_sha256"]
            or master.split(b"</teiHeader>", 1)[1] != work_text.split(b"</teiHeader>", 1)[1]):
        raise ValueError("PG22088 staged master differs from work-only text")
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    root = etree.fromstring(master, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    divisions = root.xpath("./tei:text/tei:body/tei:div/tei:div", namespaces=ns)
    if [node.get("type") for node in divisions] != [
            "title-page", "preface", "contents", "main-text", "notes", "supplement", "additional-notes"]:
        raise ValueError("PG22088 staged master includes provider material or omits work divisions")
    if _files(ROOT / WORK) != receipt["before"]:
        raise ValueError("PG22088 canonical acquired preimages differ")
    if (_io_path(ROOT / EDITION / "acceptance.json").exists()
            or _io_path(ROOT / EDITION / "master.tei.xml").exists()):
        raise ValueError("PG22088 canonical edition already has acceptance or master")
    source = _io_path(ROOT / SOURCE_RELATIVE).read_bytes()
    if sha256(source).hexdigest() != receipt["source_sha256"]:
        raise ValueError("PG22088 retained source differs")
    if sha256(_io_path(stage / SOURCE_RELATIVE).read_bytes()).hexdigest() != receipt["source_sha256"]:
        raise ValueError("PG22088 staged retained source differs")
    for relative, expected in receipt["dependencies"].items():
        if sha256(_io_path(ROOT / relative).read_bytes()).hexdigest() != expected:
            raise ValueError(f"PG22088 dependency differs: {relative}")
    return dict(status="guard-pass", receipt_sha256=receipt_sha256,
                source_sha256=receipt["source_sha256"], before_files=len(receipt["before"]),
                after_files=len(receipt["after"]), native_rows=receipt["native_rows"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.stage, args.receipt_sha256), sort_keys=True))


if __name__ == "__main__":
    main()
