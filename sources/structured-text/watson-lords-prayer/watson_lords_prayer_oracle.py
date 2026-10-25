"""Independent route adapter for Watson's retained The Lord's Prayer source.

The selected-ThML checker independently walks the retained source and actual
TEI. This ticket-local adapter adds the exact work/profile binding and rebases
the attestation to this oracle's own implementation and import closure.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from build.tei.selected_thml_oracle import (
    CLOSURE as SELECTED_THML_CLOSURE,
    _oracle as _selected_thml_oracle,
)
from ocd_kernel.reconstruction.contract import _canonical


WORK_ID = "watson-lords-prayer"
CLOSURE = (
    "build/tei/selected_thml_oracle.py",
    *SELECTED_THML_CLOSURE,
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _closure_digest(root: Path) -> str:
    rows = [
        {"path": path, "sha256": _sha((root / path).read_bytes())}
        for path in CLOSURE
    ]
    return _sha(_canonical(rows))


def _read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not readable UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _oracle(manifest, candidate):
    """Run the independent selected-ThML source/TEI walk for this route."""

    if manifest.record.get("work_id") != WORK_ID:
        raise ValueError("Watson The Lord's Prayer oracle received another work")
    manifest.verify()
    profile = _read_json(manifest.authority_path("profile"), "route profile")
    if profile.get("work_id") != WORK_ID:
        raise ValueError("Watson The Lord's Prayer profile work differs")
    result = dict(_selected_thml_oracle(manifest, candidate))
    result["implementation_sha256"] = _sha(Path(__file__).read_bytes())
    result["import_closure_sha256"] = _closure_digest(manifest.repository_root)
    digest_record = {
        key: value for key, value in result.items() if key != "result_sha256"
    }
    result["result_sha256"] = _sha(_canonical(digest_record))
    return result


_oracle.oracle_id = "ocd-watson-lords-prayer-selected-thml-independent-check"
_oracle.oracle_version = "1"
