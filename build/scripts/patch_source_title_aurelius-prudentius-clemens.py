# standards: author id slug
"""Patch missing source_title for aurelius-prudentius-clemens church_fathers entries.

9 of 10 missing entries are patched here with HIGH confidence.
1 entry (2Corinthians 6:14) is left blank -- MEDIUM confidence only.

--- Background ---

All 10 entries in aurelius-prudentius-clemens.json are missing source_title.
A parallel Prudentius/ directory exists in the raw Commentaries-Database with
source_title values set in each TOML. The same quotes also appear in
data/church-fathers/prudentius.json with curated source_titles, providing
cross-reference evidence.

Prudentius's known works cited here:
  - Psychomachia ("The Spiritual Combat"): allegorical poem, ~1000 lines
  - Cathemerinon ("Hymns For Every Day" / "The Daily Round"): 12 hymns
  - Dittochaeon / Tituli Historiarum ("Scenes from Sacred History"): 49 quatrains

All attributions verified against the H.J. Thomson Loeb Classical Library
editions via archive.org:
  - Vol. I: https://archive.org/details/prudentiuswithen01pruduoft
    (Cathemerinon + Psychomachia)
  - Vol. II: https://archive.org/details/L398PrudentiusIISymmachusCrownsOfMartyrdomScenesFromHistory
    (Dittochaeon / Scenes from History)
  - R. Martin Pope translation of Cathemerinon (Gutenberg):
    https://www.gutenberg.org/files/14959/14959-h/14959-h.htm

--- Evidence for source_title assignment ---

For 4 entries: the quote text itself contains a trailing self-attribution
(e.g., '- "The Spiritual Combat 804-22"') embedded by the ACCS source compiler.
These serve as direct signals confirmed against the primary text.

For 5 more entries: the parallel Prudentius/ raw TOML (same database) has
source_title set; the same quote also appears in prudentius.json (curated
in this project). For each, the attribution was verified against the primary
text (see Spot-check block below).

For 1 entry (2 Corinthians 6:14): the TOML says "HYMNS 1.58-60" and
prudentius.json says "Hymns 1.58-60". However, lines 58-60 of Cathemerinon
Hymn I contain Peter's denial passage, not the mammon/celestial-flame quote.
The ACCS may use a different line-numbering system. Without successful
primary-source verification, this is MEDIUM confidence -- left blank.

--- Confidence ratings ---

HIGH (9 entries):
  1Kgs.5.5    -- "The Spiritual Combat 804-22"
    Self-attributed in TOML. Psychomachia lines 800-822 (Solomon/temple)
    confirmed in Thomson Loeb vol. I, pp. 334-335.
  Josh.4.4    -- "Hymns For Every Day 177.180"
    Self-attributed in TOML. Cathemerinon XII lines 177-180 ('qui ter
    quaternas denique / refluentis amnis alveo / fundavit et fixit
    petras / apostolorum stemmata') confirmed in Thomson Loeb vol. I.
  Josh.7.1    -- "The Spiritual Combat 536.46"
    Self-attributed in TOML. Psychomachia lines 530-546 (Jericho/Achar)
    confirmed in Thomson Loeb vol. I, p. 316.
  Judg.15.5   -- "Scenes from Sacred History 17.18"
    Self-attributed in TOML. Dittochaeon sections XVII (Samson/lion/honey)
    and XVIII (Samson/foxes/firebrands) confirmed in Thomson Loeb vol. II.
  Luke.8.28   -- "Scenes from Sacred History 36"
    TOML cross-ref + prudentius.json. Dittochaeon section XXXVI 'Daemon
    missus in Porcos' confirmed in Thomson Loeb vol. II, p. 363.
  Luke.8.43   -- "Hymn For Every Day 9.33-44"
    TOML cross-ref + prudentius.json. Cathemerinon IX line 40 ('furtim
    mulier attigit') -- woman touching garment, confirmed in Thomson Loeb
    vol. I (Hymnus omnis Horae).
  Luke.9.17   -- "Hymns For Every Day 9.58-63"
    TOML cross-ref + prudentius.json. Cathemerinon IX lines 56-63 ('quin-
    que saturavit panes gemellosque pisces / ... / tu cibus panisque
    noster') confirmed in Thomson Loeb vol. I.
  Luke.9.17-2 -- "Scenes from Sacred History 37"
    TOML cross-ref + prudentius.json. Dittochaeon section XXXVII 'Quinque
    Panes et duo Pisces' confirmed in Thomson Loeb vol. II, p. 364.
  Prov.8.28   -- "Hymns For Every Day 11"
    TOML cross-ref + prudentius.json. Cathemerinon XI (Christmas Hymn)
    'Wisdom, whereby the heavens were made / And light's foundations first
    were laid: / Creative Word! all flows from Thee! / The Word is God
    eternally.' confirmed in Pope translation (Gutenberg).

MEDIUM (1 entry, skipped): aurelius-prudentius-clemens.2Cor.6.14.unknown
  TOML says "HYMNS 1.58-60"; prudentius.json says "Hymns 1.58-60". But
  lines 58-60 of Cathemerinon Hymn I (cock-crow hymn) contain Peter's
  denial, not the mammon/celestial-flame passage. ACCS may use a different
  line-numbering system. Cannot verify against primary source.

--- Spot-checked against primary source ---

  - aurelius-prudentius-clemens.1Kgs.5.5.unknown
    https://archive.org/details/prudentiuswithen01pruduoft (Psychomachia
    lines 800-822, Thomson Loeb) -- "One task alone, ye captains, now that
    war is over, remains for a noble effort to perform; the task that
    Solomon, the peaceful heir of a warlike throne..." -- confirmed. HIGH.

  - aurelius-prudentius-clemens.Luke.8.28.unknown
    https://archive.org/details/L398PrudentiusIISymmachusCrownsOfMartyrdomScenesFromHistory
    (Dittochaeon XXXVI, Thomson Loeb vol. II) -- "XXXVI. The Devil Sent
    into the Swine / A devil had broken his bonds of iron in the prison of
    a tomb; he bursts out and throws himself at Jesus' feet. But the Lord
    claims the man for himself and bids his enemy drive the herds of swine
    mad and plunge into the sea." -- confirmed. HIGH.

  - aurelius-prudentius-clemens.Luke.9.17.unknown
    https://archive.org/details/prudentiuswithen01pruduoft (Cathemerinon
    IX line 60, Thomson Loeb vol. I) -- Latin line 60: 'sis et gemellis
    piscibus' + surrounding lines about baskets of fragments and Christ as
    bread -- confirmed. HIGH.

Run twice to verify idempotency (TEST-05).
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "aurelius-prudentius-clemens.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# Title Case per project convention (matches prudentius.json source_titles).
# 2Cor.6.14 intentionally omitted -- MEDIUM confidence, see docstring.
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # Psychomachia ("The Spiritual Combat") entries
    "aurelius-prudentius-clemens.1Kgs.5.5.unknown": "The Spiritual Combat 804-22",
    "aurelius-prudentius-clemens.Josh.7.1.unknown": "The Spiritual Combat 536.46",
    # Cathemerinon ("Hymns For Every Day") entries
    "aurelius-prudentius-clemens.Josh.4.4.unknown": "Hymns For Every Day 177.180",
    "aurelius-prudentius-clemens.Luke.8.43.unknown": "Hymn For Every Day 9.33-44",
    "aurelius-prudentius-clemens.Luke.9.17.unknown": "Hymns For Every Day 9.58-63",
    "aurelius-prudentius-clemens.Prov.8.28.unknown": "Hymns For Every Day 11",
    # Dittochaeon ("Scenes from Sacred History") entries
    "aurelius-prudentius-clemens.Judg.15.5.unknown": "Scenes from Sacred History 17.18",
    "aurelius-prudentius-clemens.Luke.8.28.unknown": "Scenes from Sacred History 36",
    "aurelius-prudentius-clemens.Luke.9.17.unknown-2": "Scenes from Sacred History 37",
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
    print(f"  (1 entry intentionally left blank -- 2Cor.6.14.unknown, MEDIUM confidence)")

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
             "data/church-fathers/aurelius-prudentius-clemens.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 9, f"Expected 9 patch entries, got {len(PATCH)}"
    main()
