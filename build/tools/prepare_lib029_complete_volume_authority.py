"""Freeze a separate complete-volume Schaff source route from live retained authorities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from build.tei.lib029_complete_volume_oracle import _import_closure_sha256


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "sources/structured-text/creeds-of-christendom-vol-1"
DESTINATION = BASE / "complete-volume-v8"
DIVISIONS = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_json(path: Path, value: object) -> None:
    content = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.exists() and path.read_bytes() != content:
        raise FileExistsError(f"refusing to replace frozen authority: {path}")
    path.write_bytes(content)


def main() -> None:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    profile = json.loads((BASE / "lib029.reconstruction-profile.json").read_bytes())
    profile["profile_id"] = "lib029-ccel-complete-volume-v8"
    profile["selected_div1_ids"] = list(DIVISIONS)
    profile["projection"]["scope"] = "complete twelve-division retained volume in source order"
    profile["projection"]["excluded_div1_ids"] = []
    profile["projection"]["paratext"] = {"front": ["i", "ii"], "body": list(DIVISIONS[2:10]), "back": ["xi", "xii"]}
    profile["requirements"].append("complete-front-body-back-source-envelope")
    profile_path = DESTINATION / "reconstruction-profile.json"
    _write_json(profile_path, profile)
    schema = json.loads((BASE / "lib029.source-accountability.schema.json").read_bytes())
    schema["properties"]["profile_id"]["const"] = profile["profile_id"]
    schema["properties"]["document_accounting"]["items"]["properties"]["disposition"]["const"] = "complete-volume-with-front-body-back"
    schema_path = DESTINATION / "source-accountability.schema.json"
    _write_json(schema_path, schema)
    manifest = json.loads((BASE / "lib029.source-manifest.json").read_bytes())
    manifest["source_id"] = "ccel-lib029-complete-volume-v8-retained-thml"
    manifest["work_id"] = "creeds-of-christendom-vol-1"
    for row in manifest["authorities"]:
        if row["name"] in ("reconstruction-profile", "source-accountability-schema"):
            path = profile_path if row["name"] == "reconstruction-profile" else schema_path
            content = path.read_bytes()
            row.update(path=path.relative_to(ROOT).as_posix(), bytes=len(content), sha256=_sha(content))
    converter_path = ROOT / "build/tei/lib029_complete_volume.py"
    manifest["converter"] = {
        "id": "ocd-lib029-complete-volume-to-tei",
        "version": "1",
        "callable": "_convert",
        "implementation_path": converter_path.relative_to(ROOT).as_posix(),
        "implementation_sha256": _sha(converter_path.read_bytes()),
    }
    oracle_path = ROOT / "build/tei/lib029_complete_volume_oracle.py"
    manifest["validator"] = {
        "id": "ocd-lib029-complete-volume-source-oracle",
        "version": "1",
        "callable": "_oracle",
        "implementation_path": oracle_path.relative_to(ROOT).as_posix(),
        "implementation_sha256": _sha(oracle_path.read_bytes()),
        "import_closure_sha256": _import_closure_sha256(ROOT),
    }
    _write_json(DESTINATION / "source-manifest.json", manifest)


if __name__ == "__main__":
    main()
