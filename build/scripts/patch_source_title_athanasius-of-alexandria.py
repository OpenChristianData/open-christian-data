# standards: author id slug
"""Patch missing source_title for athanasius-of-alexandria church_fathers entries.

9 of 22 missing entries are patched here with HIGH confidence.
12 entries are left blank (MEDIUM or LOW confidence only).
(Note: original script said 13 blank; the Matt.1.1.unknown entry listed as LOW/misattribution
has since been removed from the dataset, leaving 12 blanks.)

--- Background ---

All 22 missing entries have empty body, verse_ref, and source_url -- they are
skeleton entries with no metadata beyond the entry_id. Source attribution must
be inferred from the raw TOML files in:
  raw/Commentaries-Database/Athanasius of Alexandria/

--- Evidence groups ---

GROUP A -- Inline citation in TOML quote field (4 entries):
  Gal.2.20, John.14.23, John.14.6, Rom.8.15
  All four TOML files contain the same passage ending with:
    "Letters to Separion On the Spirit, Letter 1, Chapter 19"
  This is a verbatim inline citation embedded in the quote by the transcriber.
  Source_title normalised to match existing dataset format ("Letter to Serapion 1.20",
  "Letter to Serapion 1.25", etc.) => "Letter to Serapion 1.19". HIGH.

GROUP B -- Inline citation in TOML quote field (1 entry):
  Eph.4.6
  TOML quote ends with: "Letters to Serapion on The Holy Spirit, 1.28"
  Normalised to: "Letter to Serapion 1.28". HIGH.

GROUP C -- Inline citation + cross-reference match (2 entries):
  Gal.4.6, Gen.1.26
  Both TOML files contain the same passage ending with: "Against the Arians, 2.59"
  The John.1.12.toml in the same directory has an identical passage (same text,
  same discourse) with explicit:
    source_title="Four Discourses Against the Arians, Discourse 2, Chapter 59"
    source_url="https://historicalchristian.faith/by_father.php?file=..."
  This cross-reference confirms the exact title format. HIGH.

GROUP D -- Inline citation in TOML quote field (1 entry):
  Rev.20.2
  TOML quote ends with: "(Life of Antony 24)"
  "Life of St. Anthony 24" already exists as a source_title in this dataset
  (e.g. athanasius-of-alexandria.Luke.4.31-41.life-of-st-anthony-26 uses
  "Life of St. Anthony 26"). Format confirmed. HIGH.

GROUP E -- Existing curated cross-reference (1 entry):
  Luke.10.22
  The Luke.10.22.toml is a long numbered treatise (sections 1-6) on the text
  Luke 10:22 ("all things were delivered to me"). Section 6 contains the
  Trisagion passage.
  An existing curated entry athanasius-of-alexandria.Rev.4.8.on-luke-1022
  uses source_title="On Luke 10:22" for a passage extracted from section 6
  of this same work (the Trisagion text is nearly identical).
  This confirms the title. HIGH.

--- Entries left blank ---

Acts.2.24, Acts.3.20:
  Short quotes, no inline attribution, no TOML source_url.
  Single-signal inference only (stylistic resemblance to On the Incarnation).
  NewAdvent/primary source lookup attempted 2026-04-23 but could not confirm
  exact section numbers (NewAdvent pages load partial content only).
  MEDIUM -- left blank.

Col.1.15 (x2), Col.1.16, Col.1.17, Col.2.15, Col.2.9, Col.3.5:
  No inline attribution, no TOML source_url.
  Colossians passages on the Firstborn and the Word creating all things are
  consistent with Discourses Against the Arians Discourse 2. Col.1.16 phrase
  "For the Word of God was not made for us but rather we for him, and in him
  all things were created" confirmed in NewAdvent Discourse II Section 31 by
  meaning -- but the TOML uses a different translation and section numbers
  may not align across editions, so section number cannot be confirmed HIGH.
  Col.1.17, Col.1.15, Col.2.9, Col.2.15, Col.3.5 not locatable via NewAdvent
  partial-page loads.
  MEDIUM -- all left blank.

Ezra.1.1, Neh.1.1:
  TOML quotes begin with "[Synopsis on Ezra]" / "[Synopsis on Nehemiah]"
  section labels from the "Synopsis Scripturae Sacrae" (CPG 2249).
  That work is universally attributed to Pseudo-Athanasius (post-6th cent.),
  not the historical Athanasius of Alexandria. Attribution dispute means
  source_title cannot be assigned to athanasius-of-alexandria.json with HIGH
  confidence. Upstream bug logged in UPSTREAM_BUGS.md (2026-04-23):
  these entries should be in pseudo-athanasius.json.
  MEDIUM -- left blank.

Song.1.1:
  Long synoptic commentary on the Song of Solomon, same format as Ezra/Neh
  synopsis entries. Also from the Synopsis Scripturae Sacrae (Pseudo-Athanasius).
  No inline citation. Upstream bug logged in UPSTREAM_BUGS.md (2026-04-23).
  MEDIUM -- left blank.

Matt.1.1 (no longer in dataset):
  TOML quote began "Vigil. Tapsens. (ibid. p. 644)" -- misattribution to
  Vigilius of Thapsus. Entry has since been removed from the dataset entirely.

--- Spot-checked against primary source ---

  - athanasius-of-alexandria.Gal.4.6.unknown
    Cross-reference: athanasius-of-alexandria.John.1.12.four-discourses-against-the-arians-discourse-2-cha
    (data/church-fathers/athanasius-of-alexandria.json) -- the John.1.12 TOML
    (raw/Commentaries-Database/Athanasius of Alexandria/John 1_12.toml) has the
    same passage with source_title="Four Discourses Against the Arians, Discourse 2,
    Chapter 59" and URL https://historicalchristian.faith/by_father.php?file=
    Athanasius%2520of%2520Alexandria%2FFour%2520Discourses%2520Against%2520the%2520Arians
    %2FDiscourse%25202.html -- confirmed HIGH.

  - athanasius-of-alexandria.Rev.20.2.unknown
    Inline citation "(Life of Antony 24)" confirmed against existing dataset:
    "Life of St. Anthony 24" is an established source_title (present in the
    JSON for Life of St. Anthony entries). Format match confirmed. HIGH.

  - athanasius-of-alexandria.Luke.10.22.unknown
    Cross-reference: athanasius-of-alexandria.Rev.4.8.on-luke-1022 uses
    source_title="On Luke 10:22". The Rev.4.8 TOML also has source_title="ON LUKE
    10:22" (stored as Title Case in JSON). The Luke.10.22 TOML is the full treatise
    of which Rev.4.8 quotes only section 6. Title confirmed. HIGH.

  --- 2026-04-23 re-investigation of 12 remaining blank entries ---

  All 12 remaining entries investigated via NewAdvent primary-source lookup.
  None elevated to HIGH confidence. Key findings:

  - Col.1.16: phrase "For the Word of God was not made for us" confirmed by
    meaning in NewAdvent Discourse II Section 31. However, TOML uses a
    different translation and section numbering varies across editions.
    Could not confirm section number is consistent. MEDIUM.

  - Ezra.1.1, Neh.1.1, Song.1.1: Content confirmed from Synopsis Scripturae
    Sacrae (CPG 2249, Pseudo-Athanasius, post-6th century). Wrong author file.
    Upstream bug logged in UPSTREAM_BUGS.md. MEDIUM.

  - All other 9 blank entries: Colossians passages not locatable in partial
    NewAdvent page loads; Acts passages too short for single-work attribution.
    MEDIUM.

  Result: 0 new HIGH entries. 12 entries remain blank.

Run twice to verify idempotency (TEST-05).
"""

import json
import subprocess
from pathlib import Path

# Project root is two levels up from build/scripts/
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "athanasius-of-alexandria.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # GROUP A -- Letter to Serapion 1.19 (inline citation in TOML)
    "athanasius-of-alexandria.Gal.2.20.unknown": "Letter to Serapion 1.19",
    "athanasius-of-alexandria.John.14.23.unknown": "Letter to Serapion 1.19",
    "athanasius-of-alexandria.John.14.6.unknown": "Letter to Serapion 1.19",
    "athanasius-of-alexandria.Rom.8.15.unknown": "Letter to Serapion 1.19",
    # GROUP B -- Letter to Serapion 1.28 (inline citation in TOML)
    "athanasius-of-alexandria.Eph.4.6.unknown": "Letter to Serapion 1.28",
    # GROUP C -- Four Discourses Against the Arians, Discourse 2, Chapter 59
    #            (inline citation + cross-reference to John.1.12 TOML)
    "athanasius-of-alexandria.Gal.4.6.unknown": "Four Discourses Against the Arians, Discourse 2, Chapter 59",
    "athanasius-of-alexandria.Gen.1.26.unknown": "Four Discourses Against the Arians, Discourse 2, Chapter 59",
    # GROUP D -- Life of St. Anthony 24 (inline citation in TOML)
    "athanasius-of-alexandria.Rev.20.2.unknown": "Life of St. Anthony 24",
    # GROUP E -- On Luke 10:22 (cross-reference to existing curated Rev.4.8 entry)
    "athanasius-of-alexandria.Luke.10.22.unknown": "On Luke 10:22",
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

    # Build lookup by entry_id
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
    print(f"  (12 entries intentionally left blank -- MEDIUM or LOW confidence)")

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
             "data/church-fathers/athanasius-of-alexandria.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 9, f"Expected 9 patch entries, got {len(PATCH)}"
    main()
