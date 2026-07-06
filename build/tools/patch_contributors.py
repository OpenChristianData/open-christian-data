"""Patch contributors field onto BSB (66 files) and Schaff-Herzog (12 files).

One-shot, idempotent. Also removes the incorrectly-added `author` field
from both sets (the reconciled_record and bible_text schemas don't define
`author`; the previous session's patch introduced a schema violation).

Sources:
  BSB: bible.hub.org — Berean Standard Bible, translation committee.
  Schaff-Herzog: Philip Schaff founded the original (1882-1884) series;
    Samuel Macaulay Jackson was General Editor of the 1908-1914 edition.
"""

import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def _patch_file(path: pathlib.Path, remove_author: bool, contributors: list[dict]) -> bool:
    """Return True if the file was modified."""
    raw = path.read_bytes()
    data = json.loads(raw)
    meta = data["meta"]

    changed = False

    # Remove schema-invalid `author` field if present
    if remove_author and "author" in meta:
        del meta["author"]
        changed = True

    # Add contributors if not already set (idempotent)
    if not meta.get("contributors"):
        meta["contributors"] = contributors
        changed = True

    if not changed:
        return False

    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return True


BSB_CONTRIBUTORS = [
    {
        "name": "Berean Bible",
        "role": "translator",
        "note": "Translation committee; Berean Standard Bible first published 2016, CC0 since April 2023"
    }
]

SCHAFF_CONTRIBUTORS = [
    {
        "name": "Philip Schaff",
        "role": "series_editor",
        "note": "Founded the original Schaff-Herzog Encyclopedia (1882-1884); namesake of 1908-1914 revised edition"
    },
    {
        "name": "Samuel Macaulay Jackson",
        "role": "editor",
        "note": "General Editor, 1908-1914 edition"
    }
]


def main() -> None:
    bsb_dir = DATA / "bible-text" / "bsb"
    schaff_dir = DATA / "reference" / "schaff" / "encyclopedia" / "1908-1914" / "original"

    bsb_files = sorted(bsb_dir.glob("*.json"))
    schaff_files = sorted(schaff_dir.glob("vol_*.json"))

    print(f"BSB files found:         {len(bsb_files)}")
    print(f"Schaff-Herzog files found: {len(schaff_files)}")

    bsb_modified = 0
    for path in bsb_files:
        if _patch_file(path, remove_author=True, contributors=BSB_CONTRIBUTORS):
            bsb_modified += 1

    schaff_modified = 0
    for path in schaff_files:
        if _patch_file(path, remove_author=True, contributors=SCHAFF_CONTRIBUTORS):
            schaff_modified += 1

    print(f"BSB modified:            {bsb_modified}")
    print(f"Schaff-Herzog modified:  {schaff_modified}")
    print("Done.")


if __name__ == "__main__":
    main()
