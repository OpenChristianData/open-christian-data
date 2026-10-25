"""Stage source-bound, plain Markdown Douay context and credit notice pairs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ocd_kernel.release.public_allowlist import _scan


ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "reports/_logs/original-douay-rheims-current-reconciliation-20261002-v1"
COMPANION = LOG / "readable-companion-v2-release"
WORK_ID = "original-douay-rheims"
MAIN_SOURCE = Path("sources/original-douay-existing-native-current/original-douay-rheims/README.source.md")
MAIN_DATA = Path("data/bible/original-douay-rheims/README.md")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def put(root: Path, relative: Path, data: bytes) -> None:
    target = root / relative
    if target.exists():
        raise FileExistsError(f"Notice target already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def binding(source_path: Path, source: bytes, notice_path: Path, notice: bytes) -> dict[str, str]:
    return {"source_path": source_path.as_posix(), "source_sha256": digest(source), "notice_path": notice_path.as_posix(), "notice_sha256": digest(notice)}


def stage(destination: Path) -> dict:
    manifest_bytes = (COMPANION / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    proof = json.loads((LOG / "readable-companion-v2-proof.json").read_bytes())
    if (manifest["status"] != "pass" or proof["status"] != "pass"
            or manifest["notice_parts"] != 169 or manifest["nonverse_fields"] != 25145
            or proof["literal_nonverse_bytes"] != 3781838
            or manifest["source_manifest_sha256"] != proof["manifest_sha256"]
            or manifest["source_crosswalk_sha256"] != proof["crosswalk_sha256"]):
        raise ValueError("Complete readable source and plain Markdown bindings required")
    if not destination.is_dir():
        raise FileNotFoundError("Existing isolated stage root required")
    notices = []
    main_source = (ROOT / MAIN_SOURCE).read_bytes()
    main_data = (ROOT / MAIN_DATA).read_bytes()
    if main_source != main_data or f"`{MAIN_DATA.as_posix()}`" not in main_source.decode("utf-8"):
        raise ValueError("Maintained data-path credit differs")
    put(destination, MAIN_SOURCE, main_source)
    put(destination, MAIN_DATA, main_data)
    notices.append(binding(MAIN_SOURCE, main_source, MAIN_DATA, main_data))
    for number, entry in enumerate(manifest["parts"], 1):
        relative = Path(entry["path"])
        body = (COMPANION / relative).read_bytes()
        if digest(body) != entry["sha256"] or len(body) != entry["bytes"] or len(body) > 65536:
            raise ValueError(f"Readable release notice changed: {relative}")
        value = body.decode("utf-8")
        if "<" in value or ">" in value or _scan(value, relative.as_posix()):
            raise ValueError(f"Readable release notice violates public notice rules: {relative}")
        data_path = Path("data/bible/original-douay-rheims/context-v2") / relative.parent / relative.stem / "README.md"
        source_path = Path(f"sources/original-douay-context-v2-{number:04d}/original-douay-rheims/README.source.md")
        source_text = (
            "# Original Douay-Rheims readable source context\n\n"
            f"Retained electronic member: `{entry['member']}`. "
            f"This source-context part is presented at `{data_path.as_posix()}`.\n\n"
            "The pinned janvier-s/original-douay-rheims v1.0 release declares CC0 1.0 Universal. "
            "Primary title material credits the English College of Rheims and the English College "
            "of Doway; Gregory Martin and contemporary revisers/annotators are retained provider "
            "attributions. Edition and print-collation claims remain qualified. "
            "The Bible rows retain verse wording; this notice supplies source-native apparatus "
            "and context without claiming new verses.\n"
        ).encode("utf-8")
        put(destination, source_path, source_text)
        put(destination, data_path, body)
        notices.append(binding(source_path, source_text, data_path, body))
    report = {"status": "pass", "source_candidate_sha256": manifest["source_candidate_sha256"], "companion_manifest_sha256": digest(manifest_bytes), "notice_count": len(notices), "context_parts": len(notices) - 1, "literal_nonverse_bytes": 3781838, "bindings": notices}
    (destination / "original-douay-notice-bindings.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    report = stage(args.destination)
    print(json.dumps({key: value for key, value in report.items() if key != "bindings"}, indent=2))


if __name__ == "__main__":
    main()
