"""
One-time patch: remove invalid OSIS cross-refs from Expositor's Bible JSON files.

These refs were identified during post-run validation. The root cause (bad source data)
is already fixed in _CCEL_OSISREF_CORRECTIONS in the parser, but merge logic (add-new-only)
means the already-written JSON entries are not updated on re-run.
"""
import json
from pathlib import Path

REPO = Path(__file__).parent.parent.parent
DATA_DIR = REPO / "data" / "commentaries" / "expositors-bible"

# Map: entry_id -> list of bad cross_reference OSIS strings to remove
PATCHES = {
    "expositors-bible.2Kgs-36-1":        ["Ezek.17.25"],
    "expositors-bible.2Sam-4-1":         ["1Sam.29.12"],
    "expositors-bible.Deut-1-1":         ["Exod.24.20"],
    "expositors-bible.Heb-6-1":          ["Ps.24.14"],
    "expositors-bible.Isa-5-1":          ["Ps.131.7"],
    "expositors-bible.Jer-1-1":          ["Ps.21.14"],
    "expositors-bible.Jer-25-15":        ["Isa.50.13"],
    "expositors-bible.Josh-26-1":        ["1Sam.9.31"],
    "expositors-bible.Lev-1-1":          ["Exod.30.39", "Exod.30.40"],
    "expositors-bible.Ps-77-1-Ps-77-20": ["Hab.5.10"],
    "expositors-bible.Rev-15-1":         ["Ps.14.9-Ps.14.15"],
}

def patch_file(path: Path, entry_patches: dict) -> int:
    """Patch a single JSON file; return count of refs removed."""
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)

    removed = 0
    for entry in doc["data"]:
        eid = entry.get("entry_id", "")
        if eid not in entry_patches:
            continue
        bad_refs = entry_patches[eid]
        before = len(entry.get("cross_references", []))
        entry["cross_references"] = [
            r for r in entry.get("cross_references", [])
            if r not in bad_refs
        ]
        after = len(entry["cross_references"])
        removed += before - after

    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

    return removed

def main():
    # Group patches by file
    file_patches: dict[str, dict] = {}
    for entry_id, bad_refs in PATCHES.items():
        # Infer book from entry_id: expositors-bible.{Book}-... -> book OSIS prefix
        # e.g. "expositors-bible.2Kgs-36-1" -> "2Kgs" -> "2kgs.json"
        mid = entry_id.split(".", 1)[1]           # "2Kgs-36-1"
        book_osis = mid.split("-")[0]              # "2Kgs"
        filename = book_osis.lower() + ".json"     # "2kgs.json"
        file_patches.setdefault(filename, {})[entry_id] = bad_refs

    total = 0
    for filename, ep in sorted(file_patches.items()):
        path = DATA_DIR / filename
        if not path.exists():
            print(f"  MISSING: {filename}", flush=True)
            continue
        removed = patch_file(path, ep)
        total += removed
        print(f"  {filename}: removed {removed} ref(s) from {len(ep)} entry/entries", flush=True)

    print(f"\nTotal refs removed: {total}", flush=True)


if __name__ == "__main__":
    main()
