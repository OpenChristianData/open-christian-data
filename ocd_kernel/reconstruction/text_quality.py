"""Verify optional advisory screening evidence without rerunning the screen."""

import hashlib
from pathlib import Path
import stat

from .contract import _canonical, _strict_json


def verify_text_quality(path: Path, expected_sha256, source_manifest, candidate) -> None:
    """Keep historical reports valid; verify new evidence against exact inputs."""
    if expected_sha256 is None and not path.exists() and not path.is_symlink():
        return
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    if path.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) or not path.is_file():
        raise ValueError("text-quality report must be an ordinary file")
    content = path.read_bytes()
    if expected_sha256 != hashlib.sha256(content).hexdigest():
        raise ValueError("text-quality report digest mismatch")
    record = _strict_json(content, "text-quality report")
    if content != _canonical(record):
        raise ValueError("text-quality.json is not canonical JSON")
    expected_inputs = [(a["path"], a["sha256"], a["role"]) for a in source_manifest.record["authorities"]]
    expected_inputs.append(("package/content.tei.xml", hashlib.sha256(candidate.member_bytes("content.tei.xml")).hexdigest(), "candidate-tei"))
    inputs = record.get("inputs")
    if (record.get("contract") != "ocd-reconstruction-text-screen-v1"
        or record.get("status") != "completed"
        or record.get("candidate_sha256") != candidate.sha256
        or record.get("source_manifest_sha256") != source_manifest.sha256
        or not isinstance(inputs, list)
        or any(not isinstance(row, dict) or row.get("status") not in ("screened", "not_screened") for row in inputs)
        or [(row.get("path"), row.get("sha256"), row.get("role")) for row in inputs] != expected_inputs):
        raise ValueError("text-quality report input binding mismatch")
