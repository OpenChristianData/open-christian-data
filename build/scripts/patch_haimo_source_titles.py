"""Patch missing source_title for haimo-of-auxerre church_fathers entries.

All 27 entries had empty source_title. All 27 are patched here with HIGH confidence.

Two works cover the entire file:
  - 9 entries from 2 Thessalonians -> "Commentary on 2 Thessalonians"
    Latin: "In divi Pauli epistolas expositio" (PL 117:361-938)
    English: published as "Second Thessalonians: Two Early Medieval Apocalyptic
    Commentaries" (Cartwright & Hughes, Medieval Institute Publications, 2001)
    Per-epistle title used per project convention for Pauline commentaries.

  - 18 entries from Jonah -> "Commentary on Jonah"
    Latin: "Enarratio in Duodecim Prophetas Minores" (PL 117:11-294)
    English: published as "Commentary on the Book of Jonah"
    (Everhart, Medieval Institute Publications, 1993; ISBN 1-879288-36-2)
    Haimo's Jonah section extracted and published as a standalone TEAMS volume.

No section-specific numbering used -- prose exegesis, not a homily series.
Title format matches existing OCD conventions: "Commentary on 2 Thessalonians"
(see theophylact-of-ohrid, thomas-aquinas) and "Commentary on Jonah" (shorter
form consistent with project style).

Spot-checked against primary source:
  - haimo-of-auxerre.Jonah.1.1.unknown (historicalchristian.faith/jonah/1/all):
    confirmed -- search result returned exact TOML text "HAIMO They say that
    Jonah's grave is in Geth, which is in Ophir" attributed to Haimo; work is
    "Enarratio in Duodecim Prophetas Minores" = TEAMS "Commentary on the Book
    of Jonah". The preceding paragraph summarises Jerome within Haimo's text,
    consistent with TEAMS description of Haimo's method (incorporating Jerome).
  - haimo-of-auxerre.2Thess.1.1.unknown (TEAMS vol. Cartwright & Hughes, 2001):
    confirmed -- full-length introductory commentary block matches TEAMS volume
    description of Haimo as discussing "the Day of Judgment was not yet imminent"
    and "announcing the coming and death of the Antichrist"; work is "In divi
    Pauli epistolas expositio" (PL 117:361-938).
  - haimo-of-auxerre.Jonah.3.2.unknown: confirmed by exclusion -- Haimo's only
    surviving work covering Jonah 3:2 is the Minor Prophets commentary; no
    competing Haimo works exist for this verse; TEAMS standalone edition confirms
    the commentary covers all four Jonah chapters including 3:2.

Run twice to verify idempotency (TEST-05).
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "haimo-of-auxerre.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # ---- 2 Thessalonians (9 entries) ----
    # Haimo's "In divi Pauli epistolas expositio" (PL 117:361-938).
    # TEAMS English: "Exposition of the Second Letter to the Thessalonians"
    # (Cartwright & Hughes, 2001). Per-epistle title per project convention.
    "haimo-of-auxerre.2Thess.1.1.unknown": "Commentary on 2 Thessalonians",
    "haimo-of-auxerre.2Thess.1.5.unknown": "Commentary on 2 Thessalonians",
    "haimo-of-auxerre.2Thess.1.6.unknown": "Commentary on 2 Thessalonians",
    "haimo-of-auxerre.2Thess.1.7.unknown": "Commentary on 2 Thessalonians",
    "haimo-of-auxerre.2Thess.1.8.unknown": "Commentary on 2 Thessalonians",
    "haimo-of-auxerre.2Thess.2.6.unknown": "Commentary on 2 Thessalonians",
    "haimo-of-auxerre.2Thess.2.15.unknown": "Commentary on 2 Thessalonians",
    "haimo-of-auxerre.2Thess.3.5.unknown": "Commentary on 2 Thessalonians",
    "haimo-of-auxerre.2Thess.3.17.unknown": "Commentary on 2 Thessalonians",

    # ---- Jonah (18 entries) ----
    # Haimo's "Enarratio in Duodecim Prophetas Minores" (PL 117:11-294).
    # TEAMS English: "Commentary on the Book of Jonah" (Everhart, 1993).
    # Short-form title consistent with project style.
    "haimo-of-auxerre.Jonah.1.1.unknown": "Commentary on Jonah",
    "haimo-of-auxerre.Jonah.1.3.unknown": "Commentary on Jonah",
    "haimo-of-auxerre.Jonah.1.3.unknown-2": "Commentary on Jonah",
    "haimo-of-auxerre.Jonah.1.5.unknown": "Commentary on Jonah",
    "haimo-of-auxerre.Jonah.1.5.unknown-2": "Commentary on Jonah",
    "haimo-of-auxerre.Jonah.1.5.unknown-3": "Commentary on Jonah",
    "haimo-of-auxerre.Jonah.1.7.unknown": "Commentary on Jonah",
    "haimo-of-auxerre.Jonah.2.1.unknown": "Commentary on Jonah",
    "haimo-of-auxerre.Jonah.2.3.unknown": "Commentary on Jonah",
    "haimo-of-auxerre.Jonah.2.5.unknown": "Commentary on Jonah",
    "haimo-of-auxerre.Jonah.2.7.unknown": "Commentary on Jonah",
    "haimo-of-auxerre.Jonah.2.10.unknown": "Commentary on Jonah",
    "haimo-of-auxerre.Jonah.3.1.unknown": "Commentary on Jonah",
    "haimo-of-auxerre.Jonah.3.2.unknown": "Commentary on Jonah",
    "haimo-of-auxerre.Jonah.3.10.unknown": "Commentary on Jonah",
    "haimo-of-auxerre.Jonah.4.2.unknown": "Commentary on Jonah",
    "haimo-of-auxerre.Jonah.4.4.unknown": "Commentary on Jonah",
    "haimo-of-auxerre.Jonah.4.11.unknown": "Commentary on Jonah",
}


def main() -> None:
    print(f"Loading {DATA_FILE}")
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    entries = data["data"]
    blank_before = sum(1 for e in entries if not e.get("source_title"))
    print(f"Blank source_title entries before patch: {blank_before}")

    set_count = 0
    skipped_already_set = 0
    skipped_not_in_data = []

    # Build lookup
    entry_map = {e["entry_id"]: e for e in entries}

    for entry_id, title in PATCH.items():
        if entry_id not in entry_map:
            skipped_not_in_data.append(entry_id)
            continue
        entry = entry_map[entry_id]
        if entry.get("source_title"):
            skipped_already_set += 1  # idempotent skip
        else:
            entry["source_title"] = title
            set_count += 1

    blank_after = sum(1 for e in entries if not e.get("source_title"))

    print(f"Set:                    {set_count}")
    print(f"Skipped (already set):  {skipped_already_set}")
    if skipped_not_in_data:
        print(f"WARNING: entry_ids not found in data ({len(skipped_not_in_data)}):")
        for eid in skipped_not_in_data:
            print(f"  {eid}")
    print(f"Blank source_title entries after patch: {blank_after}")

    print(f"\nWriting {DATA_FILE}")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("Done.")

    # Run validator
    print("\nRunning validate.py ...")
    try:
        subprocess.run(
            ["py", "-3", str(VALIDATE_SCRIPT),
             "data/church-fathers/haimo-of-auxerre.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 27, f"Expected 27 patch entries, got {len(PATCH)}"
    main()
