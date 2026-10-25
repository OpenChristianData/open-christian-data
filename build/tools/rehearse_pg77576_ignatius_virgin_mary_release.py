"""Assemble a single-work offline release rehearsal without publishing."""

from __future__ import annotations

import json
import shutil
import tempfile
from hashlib import sha256
from pathlib import Path

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2

from build.tools.prepare_pg77576_ignatius_virgin_mary_publication import (
    ACCEPTANCE_SHA, EDITION, EVIDENCE, MASTER_SHA, PG_1E1_NOTICE, PUBLIC_NOTICE, ROOT, SOURCE_NOTE, WORK_ID,
)


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _json(path: Path, value: object) -> None:
    content = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if path.exists() and path.read_bytes() != content:
        raise PipelineError(f"existing rehearsal evidence differs: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def main() -> None:
    root = ROOT.resolve(strict=True)
    if (_sha(root / EDITION / "master.tei.xml") != MASTER_SHA
            or _sha(root / EDITION / "acceptance.json") != ACCEPTANCE_SHA):
        raise PipelineError("single-work release source authority changed")
    notice = dict(source_path=SOURCE_NOTE.as_posix(), source_sha256=_sha(root / SOURCE_NOTE),
                  notice_path=PUBLIC_NOTICE.as_posix(), notice_sha256=_sha(root / PUBLIC_NOTICE))
    selection = dict(schema_version="2.0", release_id="pg77576-virgin-mary-offline-rehearsal-v2",
                     items=[dict(item_id=WORK_ID, category="prose",
                                 acceptance_path=(EDITION / "acceptance.json").as_posix(),
                                 public_notices=[notice])])
    evidence = root / EVIDENCE / "release-rehearsal"
    _json(evidence / "selection.json", selection)
    with tempfile.TemporaryDirectory(prefix="ocd-pg77576-virgin-mary-release-") as scratch:
        release = Path(scratch) / "assembled"
        report = assemble_release_v2(root, release, selection=selection)
        check = verify_release_v2(root, release, selection=selection)
        if report["status"] != "pass" or check != {"status": "pass", "errors": []}:
            raise PipelineError(f"single-work offline release verification differs: {check}")
        if len(report["items"]) != 1 or report["items"][0]["row_count"] != 2:
            raise PipelineError("single-work release row accounting differs")
        card = (release / "public/README.md").read_text(encoding="utf-8")
        if PG_1E1_NOTICE not in card or "[original electronic formats](https://www.gutenberg.org/ebooks/77576)" not in card:
            raise PipelineError("offline public card omits the required Project Gutenberg notice or original formats")
        paths = ["public/README.md", "public/data/prose/train.jsonl", "public/data/prose/train.arrow",
                 "internal/release-selection.json",
                 "internal/release-report.json", "internal/checks/independent-check.json",
                 f"internal/projection-receipts/{WORK_ID}.json"]
        files = {}
        for name in paths:
            source = release / name
            target = evidence / name
            if not source.is_file():
                raise PipelineError(f"offline release file missing: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != source.read_bytes():
                raise PipelineError(f"existing offline release evidence differs: {name}")
            shutil.copy2(source, target)
            files[name] = _sha(target)
        files["selection.json"] = _sha(evidence / "selection.json")
    result = dict(contract="ocd-pg77576-virgin-mary-offline-release-rehearsal-v2",
                  work_id=WORK_ID, status="offline-verified-not-authorized-for-publication",
                  master_sha256=MASTER_SHA, acceptance_sha256=ACCEPTANCE_SHA,
                  row_count=2, selection=selection, files=files, independent_check=check,
                  rights_clearance="not-recorded", human_verification="not-recorded",
                  publication_authorization="not-recorded")
    _json(evidence / "rehearsal-index.json", result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
