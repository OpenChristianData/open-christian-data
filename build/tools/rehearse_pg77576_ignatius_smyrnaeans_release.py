"""Assemble and verify a local one-work Smyrnaeans release rehearsal."""

from __future__ import annotations

import json
import tempfile
from hashlib import sha256
from pathlib import Path

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.acceptance import validate_acceptance

from build.tools.project_pg77576_ignatius_smyrnaeans import (
    ACCEPTANCE,
    ACCEPTANCE_SHA256,
    EDITION,
    MASTER_SHA256,
    PUBLICATION,
    PUBLIC_NOTICE,
    RECEIPT,
    ROOT,
    ROWS,
    SOURCE_NOTE,
    WORK_ID,
    _json_bytes,
    verify_rows,
)


EVIDENCE = PUBLICATION / "release-rehearsal"
CAPTURED_RECEIPT = "receipt.json"
NOTICE_SENTENCE = (
    "This eBook is for the use of anyone anywhere in the United States and most other parts of the world "
    "at no cost and with almost no restrictions whatsoever. You may copy it, give it away or re-use it under "
    "the terms of the [Project Gutenberg License](https://www.gutenberg.org/policy/license) included with "
    "this eBook or online at [www.gutenberg.org](https://www.gutenberg.org). If you are not located in the "
    "United States, you'll have to check the laws of the country where you are located before using this ebook."
)
RELEASE_FILES = (
    "public/README.md",
    "public/data/prose/train.jsonl",
    "public/data/prose/train.arrow",
    "internal/release-selection.json",
    "internal/release-report.json",
    "internal/checks/independent-check.json",
    f"internal/projection-receipts/{WORK_ID}.json",
)
PREVIOUS_EVIDENCE_HASHES = {
    "selection.json": "418b5536f2aa7f2e62bd6921ce9dc3b70f69cd209820057f5c9c6d9d44ee34b0",
    "public/README.md": "45f3b6a5736dcb63c5623d71e72b222d11e7b323b0c58937dd8eba53c93ddb12",
    "public/data/prose/train.jsonl": "6e0ca16ce9103bb405a73bd9659c0de6fdcfd44f1eda1e253080452af414ff69",
    "public/data/prose/train.arrow": "c55dc619b3b6d3e1721b3609ba71b0af96ed436d54f2d17d5459274c6a5c76af",
    "internal/release-selection.json": "418b5536f2aa7f2e62bd6921ce9dc3b70f69cd209820057f5c9c6d9d44ee34b0",
    "internal/release-report.json": "a3af492da5706112c0537a9e8eaa5c29914035317b306c5f73e0c90aa0b16069",
    "internal/checks/independent-check.json": "f33cf9c4155c57255ccae9846d79fe9d4e469f088f69727e337b3495513210ad",
}
PREVIOUS_REHEARSAL_INDEX_SHA256 = "a8d055311019906704abb8d4a109e74b7d1b89227aba9db85426974c88bc9ed6"


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _write_once(path: Path, content: bytes, *, previous_sha256: str | None = None) -> None:
    if path.exists() and path.read_bytes() != content:
        if previous_sha256 is None or _sha(path.read_bytes()) != previous_sha256:
            raise PipelineError(f"existing release rehearsal artifact differs: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _verify_captured_release(root: Path, evidence: Path, selection: dict) -> dict:
    """Recheck the captured release tree while keeping sidecar evidence outside it."""
    with tempfile.TemporaryDirectory(prefix="ocd-pg77576-smyrnaeans-verify-") as scratch:
        release = Path(scratch) / "assembled"
        release.mkdir()
        for name in RELEASE_FILES:
            if name == RELEASE_FILES[-1]:
                source = (evidence / name if (evidence / name).is_file()
                          else evidence / CAPTURED_RECEIPT if (evidence / CAPTURED_RECEIPT).is_file()
                          else root / RECEIPT)
            else:
                source = evidence / name
            if not source.is_file():
                raise PipelineError(f"captured release artifact is missing: {name}")
            target = release / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        return verify_release_v2(root, release, selection=selection)


def run(root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    master = root / EDITION / "master.tei.xml"
    acceptance = root / ACCEPTANCE
    master_sha = _sha(master.read_bytes())
    acceptance_sha = _sha(acceptance.read_bytes())
    if master_sha != MASTER_SHA256 or acceptance_sha != ACCEPTANCE_SHA256:
        raise PipelineError("installed accepted master or acceptance differs from the projection binding")
    accepted = validate_acceptance(acceptance, root=root)
    if accepted.get("identity", {}).get("work_id") != WORK_ID:
        raise PipelineError("release rehearsal acceptance identity differs")

    rows = [json.loads(line) for line in (root / ROWS).read_text(encoding="utf-8").splitlines() if line]
    receipt = json.loads((root / RECEIPT).read_text(encoding="utf-8"))
    if errors := verify_rows(rows, receipt, root=root):
        raise PipelineError(f"persisted public rows fail actual-master verification: {errors[:3]}")
    if len(rows) != 2:
        raise PipelineError("persisted Smyrnaeans projection must contain two rows")

    notice_binding = {
        "source_path": SOURCE_NOTE.as_posix(),
        "source_sha256": _sha((root / SOURCE_NOTE).read_bytes()),
        "notice_path": PUBLIC_NOTICE.as_posix(),
        "notice_sha256": _sha((root / PUBLIC_NOTICE).read_bytes()),
    }
    visible_notices = notice_texts_for_item(
        root,
        {"work_id": WORK_ID, "public_notices": [notice_binding]},
        acceptance,
    )
    if (len(visible_notices) != 1 or NOTICE_SENTENCE not in visible_notices[0]
            or "[Project Gutenberg eBook 77576](https://www.gutenberg.org/ebooks/77576)" not in visible_notices[0]):
        raise PipelineError("source-bound Project Gutenberg license/original-format notice differs")

    selection = {
        "schema_version": "2.0",
        "release_id": "pg77576-smyrnaeans-offline-rehearsal-v1",
        "items": [{
            "item_id": WORK_ID,
            "category": "prose",
            "acceptance_path": ACCEPTANCE.as_posix(),
            "public_notices": [notice_binding],
        }],
    }
    evidence = root / EVIDENCE
    _write_once(
        evidence / "selection.json",
        _json_bytes(selection),
        previous_sha256=PREVIOUS_EVIDENCE_HASHES["selection.json"],
    )

    # Recover cleanly if assembly and independent verification completed but
    # copying one of the nested durable artifacts was interrupted.
    receipt_relative = f"internal/projection-receipts/{WORK_ID}.json"
    if (not (evidence / receipt_relative).is_file()
            and json.loads((root / RECEIPT).read_bytes()) != receipt):
        raise PipelineError("canonical projection receipt changed during release rehearsal")
    if not (evidence / receipt_relative).is_file():
        _write_once(evidence / CAPTURED_RECEIPT, (root / RECEIPT).read_bytes())
    captured_files = [name for name in RELEASE_FILES if name != receipt_relative]
    report_path = evidence / "internal/release-report.json"
    report_matches_selection = (
        report_path.is_file()
        and json.loads(report_path.read_bytes()).get("selection_sha256") == _sha(_json_bytes(selection))
    )
    if (all((evidence / name).is_file() for name in captured_files)
            and (evidence / CAPTURED_RECEIPT).is_file()
            and report_matches_selection):
        check = _verify_captured_release(root, evidence, selection)
        if check != {"status": "pass", "errors": []}:
            raise PipelineError(f"captured offline release verification failed: {check}")
        report = json.loads((evidence / "internal/release-report.json").read_bytes())
        if (report.get("status") != "pass" or len(report.get("items", [])) != 1
                or report["items"][0].get("row_count") != 2):
            raise PipelineError("captured offline release report differs")
        file_hashes = {
            name: _sha((root / RECEIPT).read_bytes()) if name == receipt_relative
            else _sha((evidence / name).read_bytes())
            for name in RELEASE_FILES
        }
        file_hashes["selection.json"] = _sha((evidence / "selection.json").read_bytes())
        result = {
            "contract": "ocd-pg77576-smyrnaeans-offline-release-rehearsal-v1",
            "work_id": WORK_ID,
            "status": "offline-verified-not-authorized-for-publication",
            "master_sha256": master_sha,
            "acceptance_sha256": acceptance_sha,
            "row_count": 2,
            "notice_binding": notice_binding,
            "selection": selection,
            "files": file_hashes,
            "evidence_path_map": {receipt_relative: CAPTURED_RECEIPT},
            "independent_check": check,
            "human_verification": "not-recorded",
            "rights_clearance": "not-recorded",
            "publication_authorization": "not-recorded",
        }
        _write_once(
            evidence / "rehearsal-index.json",
            _json_bytes(result),
            previous_sha256=PREVIOUS_REHEARSAL_INDEX_SHA256,
        )
        return result

    with tempfile.TemporaryDirectory(prefix="ocd-pg77576-smyrnaeans-release-") as scratch:
        release = Path(scratch) / "assembled"
        report = assemble_release_v2(root, release, selection=selection)
        independent_check = verify_release_v2(root, release, selection=selection)
        if report.get("status") != "pass" or independent_check != {"status": "pass", "errors": []}:
            raise PipelineError(f"offline release verification failed: {independent_check}")
        if len(report.get("items", [])) != 1 or report["items"][0].get("row_count") != 2:
            raise PipelineError("offline release item or row accounting differs")
        public_card = (release / "public/README.md").read_text(encoding="utf-8")
        if visible_notices[0] not in public_card:
            raise PipelineError("offline public card omits the complete source-bound notice")

        file_hashes = {}
        for name in RELEASE_FILES:
            source_path = release / name
            if not source_path.is_file():
                raise PipelineError(f"offline release artifact is missing: {name}")
            content = source_path.read_bytes()
            if name != receipt_relative:
                target = evidence / name
                previous_sha256 = PREVIOUS_EVIDENCE_HASHES.get(name)
                _write_once(target, content, previous_sha256=previous_sha256)
            else:
                _write_once(evidence / CAPTURED_RECEIPT, content)
            file_hashes[name] = _sha(content)

    result = {
        "contract": "ocd-pg77576-smyrnaeans-offline-release-rehearsal-v1",
        "work_id": WORK_ID,
        "status": "offline-verified-not-authorized-for-publication",
        "master_sha256": master_sha,
        "acceptance_sha256": acceptance_sha,
        "row_count": len(rows),
        "notice_binding": notice_binding,
        "selection": selection,
        "files": file_hashes,
        "evidence_path_map": {receipt_relative: CAPTURED_RECEIPT},
        "independent_check": independent_check,
        "human_verification": "not-recorded",
        "rights_clearance": "not-recorded",
        "publication_authorization": "not-recorded",
    }
    _write_once(
        evidence / "rehearsal-index.json",
        _json_bytes(result),
        previous_sha256=PREVIOUS_REHEARSAL_INDEX_SHA256,
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
