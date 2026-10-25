"""Copy only the frozen Douay source/data notice pairs after accepted install."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _files

from build.tools.stage_original_douay_current import ROOT, WORK, EDITION


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def install(promoted: Path, freeze_path: Path, freeze_sha256: str, evidence: Path) -> dict:
    promoted = promoted.resolve(strict=True)
    freeze_bytes = freeze_path.read_bytes()
    if sha(freeze_bytes) != freeze_sha256:
        raise ValueError("Exact Douay install freeze changed")
    freeze = json.loads(freeze_bytes)
    if (freeze["status"] != "pass" or freeze["work_id"] != "original-douay-rheims"
            or Path(freeze["durable_promoted"]).resolve(strict=True) != promoted
            or _files(ROOT / WORK) != freeze["after"]):
        raise ValueError("Frozen Douay work is not installed unchanged")
    binding_bytes = (promoted / "original-douay-notice-bindings.json").read_bytes()
    if sha(binding_bytes) != freeze["notice_bindings_sha256"]:
        raise ValueError("Douay notice bindings changed")
    bindings = json.loads(binding_bytes)["bindings"]
    if len(bindings) != 170:
        raise ValueError("Complete Douay notice set required")
    acceptance = ROOT / EDITION / "acceptance.json"
    source_notice_texts = notice_texts_for_item(promoted, {
        "item_id": "original-douay-rheims", "work_id": "original-douay-rheims",
        "public_notices": bindings,
    }, promoted / EDITION / "acceptance.json")
    if len(source_notice_texts) != 170:
        raise ValueError("Promoted source/notice preflight differs")
    targets: list[tuple[Path, bytes]] = []
    seen = set()
    for item in bindings:
        for kind in ("source", "notice"):
            relative = item[kind + "_path"]
            digest = item[kind + "_sha256"]
            if relative in seen:
                raise ValueError("Duplicate Douay notice target: " + relative)
            seen.add(relative)
            source = promoted / relative
            target = ROOT / relative
            payload = source.read_bytes()
            if sha(payload) != digest or not str(source.resolve(strict=True)).startswith(str(promoted)):
                raise ValueError("Source notice differs: " + relative)
            if target.exists() and target.read_bytes() != payload:
                raise ValueError("Existing canonical notice differs: " + relative)
            targets.append((target, payload))
    if evidence.exists():
        raise FileExistsError("Fresh Douay notice installation evidence required")
    evidence.mkdir(parents=True)
    created: list[Path] = []
    try:
        for target, payload in targets:
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            created.append(target)
        notice_texts = notice_texts_for_item(ROOT, {
            "item_id": "original-douay-rheims", "work_id": "original-douay-rheims",
            "public_notices": bindings,
        }, acceptance)
        if len(notice_texts) != 170 or _files(ROOT / WORK) != freeze["after"]:
            raise ValueError("Canonical Douay notices or installed work differ")
    except Exception:
        for target in reversed(created):
            target.unlink()
        raise
    report = {
        "status": "pass", "work_id": "original-douay-rheims",
        "installed_notice_pairs": len(bindings), "new_files": len(created),
        "notice_bindings_sha256": sha(binding_bytes),
        "installed_work_master_sha256": freeze["bound_master_sha256"],
        "canonical_notice_texts": len(notice_texts),
    }
    (evidence / "notices-installation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--promoted", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--freeze-sha256", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.promoted, args.freeze, args.freeze_sha256, args.evidence)))


if __name__ == "__main__":
    main()
