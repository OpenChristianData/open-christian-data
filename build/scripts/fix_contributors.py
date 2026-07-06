"""
fix_contributors.py -- Convert string contributors to object form.

Schema requires meta.contributors to be a list of objects with a "name" key.
Many files have contributors as bare strings. This script converts them in-place.
"""

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
SKIP_DIRS = {"authors"}

fixed_files = 0
skipped_files = 0

for root, dirs, files in os.walk(DATA_DIR):
    root_path = Path(root)
    parts = root_path.relative_to(DATA_DIR).parts
    if parts and parts[0] in SKIP_DIRS:
        dirs.clear()
        continue

    for filename in sorted(files):
        if not filename.endswith(".json"):
            continue
        if filename in {"_manifest.json", "registry.json"}:
            continue

        filepath = root_path / filename
        with open(filepath, encoding="utf-8") as f:
            doc = json.load(f)

        meta = doc.get("meta") or {}
        contributors = meta.get("contributors")
        if not isinstance(contributors, list):
            continue

        needs_fix = any(isinstance(c, str) for c in contributors)
        if not needs_fix:
            continue

        meta["contributors"] = [
            {"name": c} if isinstance(c, str) else c
            for c in contributors
        ]

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")

        print(f"Fixed: {filepath.relative_to(PROJECT_ROOT)}")
        fixed_files += 1

print(f"\nDone: {fixed_files} files fixed, {skipped_files} skipped.")
