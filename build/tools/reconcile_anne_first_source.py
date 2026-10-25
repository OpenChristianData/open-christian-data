"""Reconcile accepted Anne A22076 first text with the retained whole XML."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "library/works/anne-askew-first-examinacyon"
EDITION = WORK / "forms/anne-askew-first-examinacyon-tcp-retained/editions/anne-askew-first-examinacyon-tcp-electronic"
INTEGRATION = WORK / "integration/anne-a22076-first-scoped-v1"
SOURCE = ROOT / "raw/tcp/high-range/A22076/A22076.xml"
OUT = ROOT / "reports/_logs/anne-askew-first-private-release-20261002-v1"
TEI = "{http://www.tei-c.org/ns/1.0}"
SOURCE_SHA = "211a2c0d5029ca1dc6622b419fea356a0bba0ee28a363bd8c4e28331b3b6f92a"
MASTER_SHA = "e3012ca8c173057f609ae3a20645ed76ac6c17cd44dcfeca3b4cfcb074e0c446"
ACCEPTANCE_SHA = "8303c0900082c4711ffc1939d6e89f8e73ea6021f03c4cc01d81125379067869"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    master = EDITION / "master.tei.xml"
    acceptance = EDITION / "acceptance.json"
    if digest(SOURCE) != SOURCE_SHA or digest(master) != MASTER_SHA or digest(acceptance) != ACCEPTANCE_SHA:
        raise ValueError("Anne retained source or accepted master/acceptance drifted")
    validate_acceptance(acceptance, root=ROOT)
    validate_state(WORK / "state.json", root=ROOT)
    source_root = ET.fromstring(SOURCE.read_bytes())
    master_root = ET.fromstring(master.read_bytes())
    group = source_root.find(f"{TEI}text/{TEI}group")
    text = master_root.find(TEI + "text")
    if group is None or text is None or len(group) != 2:
        raise ValueError("A22076 first/second nested text structure differs")
    first, second = list(group)
    first_tree = ET.tostring(first, encoding="utf-8")
    master_tree = ET.tostring(text, encoding="utf-8")
    if first_tree != master_tree:
        raise ValueError("Accepted Anne first-work text tree differs from retained text 1")
    pages_first = list(first.iter(TEI + "pb"))
    pages_second = list(second.iter(TEI + "pb"))
    if (len(pages_first) != 118
            or first.find(f"{TEI}body/{TEI}trailer") is None
            or first.find(f"{TEI}back/{TEI}div[@type='appendix']") is None
            or any(page.get("facs") == "tcp:384:60" for page in pages_first)
            or not any(page.get("facs") == "tcp:384:60" for page in pages_second)):
        raise ValueError("Anne selected text boundary, ending or out-of-work page marker differs")
    original_accounting = json.loads((INTEGRATION / "inputs/package/source-accountability.json").read_text(encoding="utf-8"))
    if (original_accounting["included"]["selector"] != "/TEI/text/group/text[1]"
            or original_accounting["excluded"]["selector"] != "/TEI/text/group/text[2]"
            or original_accounting["excluded"]["physical_placement"] != "unverified"):
        raise ValueError("Anne retained accounting selection differs")
    evidence = {}
    for name in ("source-accounting.json", "fidelity.json", "closure.json", "validation.json", "review.json", "reproducibility.json"):
        path = INTEGRATION / name
        value = json.loads(path.read_text(encoding="utf-8"))
        if name != "source-accounting.json" and name != "review.json" and value.get("status") != "pass":
            raise ValueError(f"Anne existing integration evidence did not pass: {name}")
        evidence[path.relative_to(ROOT).as_posix()] = digest(path)
    report = {
        "contract": "ocd-anne-first-current-source-reconciliation-v1",
        "status": "pass",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "work_id": "anne-askew-first-examinacyon",
        "source_path": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": SOURCE_SHA,
        "source_bytes": SOURCE.stat().st_size,
        "accepted_master_sha256": MASTER_SHA,
        "acceptance_sha256": ACCEPTANCE_SHA,
        "nested_texts": 2,
        "selected": "text[1]",
        "excluded_accounted": "text[2]",
        "selected_text_tree_sha256": hashlib.sha256(first_tree).hexdigest(),
        "accepted_text_tree_sha256": hashlib.sha256(master_tree).hexdigest(),
        "selected_text_tree_exact": True,
        "selected_page_breaks": len(pages_first),
        "second_page_breaks": len(pages_second),
        "first_has_trailer": True,
        "first_has_psalm_appendix": True,
        "second_contains_image_60": True,
        "image_60_physical_placement": "unverified",
        "prior_evidence_sha256": evidence,
        "print_image_collation": "not-performed",
        "source_reconstruction_performed": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "source-context.json"
    with path.open("xb") as stream:
        stream.write((json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    print(json.dumps({"status": "pass", "source_context_sha256": digest(path), "selected_text_tree_sha256": report["selected_text_tree_sha256"], "page_breaks": len(pages_first)}))


if __name__ == "__main__":
    main()
