"""Package exact accepted Douay rows and context privately without type coercion."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ocd_kernel.projection.categories.bible import _validator
from ocd_kernel.tei.install_accepted import _files

from build.tools.stage_original_douay_current import ROOT, WORK, EDITION


INPUT = ROOT / "reports/_logs/original-douay-rheims-current-reconciliation-20261002-v1"
LOG = ROOT / "reports/_logs/original-douay-rheims-private-offline-20261002-v1"
RELEASE = LOG / "lossless-release"
WORK_ID = "original-douay-rheims"


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    if RELEASE.exists():
        raise FileExistsError("Fresh exact Douay lossless release root required")
    freeze = json.loads((INPUT / "coordinator-install-freeze.json").read_bytes())
    final = json.loads((INPUT / "final-private-release-notice-bindings.json").read_bytes())
    projection_bytes = (LOG / "actual-master-projection.json").read_bytes()
    projection = json.loads(projection_bytes)
    linked = json.loads((LOG / "independent-projection-linkage.json").read_bytes())
    master = ROOT / EDITION / "master.tei.xml"
    acceptance = ROOT / EDITION / "acceptance.json"
    if (_files(ROOT / WORK) != freeze["after"] or sha(master.read_bytes()) != freeze["bound_master_sha256"]
            or projection["receipt"]["master_sha256"] != freeze["bound_master_sha256"]
            or linked["status"] != "pass" or not linked["producer_disabled"]
            or linked["saved_projection_sha256"] != sha(projection_bytes)
            or len(projection["rows"]) != 37181 or final["notice_count"] != 170):
        raise ValueError("Installed Douay authority or producer-disabled projection differs")
    category_types = Counter(type(row["locator"]["verse"]).__name__ for row in projection["rows"])
    if category_types != {"int": 37132, "str": 49} or any(
        row["locator"]["verse"] != "0" for row in projection["rows"]
        if isinstance(row["locator"]["verse"], str)
    ):
        raise ValueError("Expected source-native verse-zero type boundary differs")
    validator = _validator()
    errors = [str(error) for row in projection["rows"] for error in validator.iter_errors(row)]
    if errors:
        raise ValueError("Installed Douay Bible row schema differs: " + str(errors[:3]))
    RELEASE.mkdir(parents=True)
    row_path = RELEASE / "data/bible/train.jsonl"
    row_path.parent.mkdir(parents=True)
    row_bytes = b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in projection["rows"]
    )
    row_path.write_bytes(row_bytes)
    if [json.loads(line) for line in row_path.read_bytes().splitlines()] != projection["rows"]:
        raise ValueError("Private JSONL changed an installed projection value")
    shutil.copyfile(master, RELEASE / "master.tei.xml")
    shutil.copyfile(acceptance, RELEASE / "acceptance.json")
    notices = []
    for binding in final["bindings"]:
        for kind in ("source", "notice"):
            relative = binding[kind + "_path"]
            content = (ROOT / relative).read_bytes()
            if sha(content) != binding[kind + "_sha256"] or not content.endswith(b"\n") or content.endswith(b"\n\n"):
                raise ValueError("Source-bound final notice changed: " + relative)
            target = RELEASE / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            notices.append({"path": relative, "sha256": sha(content), "bytes": len(content)})
    selection = {
        "schema_version": "2.0", "release_id": "original-douay-rheims-private-lossless-20261002-v1",
        "items": [{"item_id": WORK_ID, "category": "bible", "acceptance_path": (EDITION / "acceptance.json").as_posix(), "public_notices": final["bindings"]}],
    }
    (RELEASE / "selection.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme = (
        "# Original Douay-Rheims — private lossless release\n\n"
        "This private package preserves 37,181 accepted Bible rows in source order, the accepted TEI master, "
        "and 170 paired source/data notices. The verse text is in `data/bible/train.jsonl`; "
        "source-native nonverse context is under `data/bible/original-douay-rheims/context-v2/`. "
        "The complete provider and source-use credit is at `data/bible/original-douay-rheims/README.md`.\n\n"
        "This is a private JSONL package, not a standard Hugging Face/Arrow release. The current "
        "typed companion cannot encode the source-native mix of integer verse locators and 49 string `0` locators "
        "without changing their types. Both Tobias chapter-zero carriers remain in the rows. "
        "Human acceptance, printed-witness collation, rights clearance, and public publication remain separate.\n"
    )
    (RELEASE / "README.md").write_text(readme, encoding="utf-8")
    manifest = {
        "status": "pass", "format": "private-lossless-jsonl-v1", "work_id": WORK_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "accepted_master_sha256": sha(master.read_bytes()), "acceptance_sha256": sha(acceptance.read_bytes()),
        "actual_projection_sha256": sha(projection_bytes),
        "producer_disabled_linkage_sha256": sha((LOG / "independent-projection-linkage.json").read_bytes()),
        "source_native_context_proof_sha256": freeze["markdown_derivative_proof_sha256"],
        "final_notice_bindings_sha256": sha((INPUT / "final-private-release-notice-bindings.json").read_bytes()),
        "rows": len(projection["rows"]), "row_characters": sum(len(row["text"]) for row in projection["rows"]),
        "verse_locator_types": dict(category_types), "verse_zero_string_rows": 49,
        "jsonl_path": "data/bible/train.jsonl", "jsonl_sha256": sha(row_bytes),
        "notice_pairs": len(final["bindings"]), "notices": notices,
        "standard_hf_arrow_assembly": "failed-closed: incompatible configuration feature types: int64 / string",
        "public_publication": False,
    }
    (RELEASE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for entry in notices:
        if sha((RELEASE / entry["path"]).read_bytes()) != entry["sha256"]:
            raise ValueError("Private notice readback differs")
    if (sha((RELEASE / "master.tei.xml").read_bytes()) != manifest["accepted_master_sha256"]
            or sha((RELEASE / "data/bible/train.jsonl").read_bytes()) != manifest["jsonl_sha256"]):
        raise ValueError("Private release master or rows readback differs")
    report = {key: value for key, value in manifest.items() if key not in {"notices"}}
    (LOG / "lossless-release-completion.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
