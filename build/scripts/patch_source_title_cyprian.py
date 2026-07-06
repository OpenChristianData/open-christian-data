"""
Patch source_title for cyprian (8 of 9 blank entries, all HIGH confidence).

--- Background ---

Cyprian of Carthage (c. 200-258 AD) has 890 entries in the church-fathers dataset.
9 entries were missing source_title. All 9 TOML files had empty source_url and no
metadata -- attribution required matching quote text against primary sources.

Primary sources consulted:
  - NewAdvent Fathers: https://www.newadvent.org/fathers/0506.htm (Epistles)
  - NewAdvent Fathers: https://www.newadvent.org/fathers/0507.htm (Treatises)
  - Tertullian.org ANF Vol. V: https://www.tertullian.org/fathers2/ANF-05/

--- Attribution findings ---

1John.3.15 + 1Pet.2.21 -- BOTH in Treatise X On Jealousy and Envy, section 11.
  The full section 11 text runs: "Why do you rush into the darkness of jealousy?
  why do you enfold yourself in the cloud of malice?...he who is jealous of his
  brother...is bound by the guilt of homicide, the Apostle John declares in his
  epistle...Whosoever hateth his brother is a murderer...But he follows Christ who
  stands in His precepts...in accordance with what Peter also exhorts and warns,
  saying, Christ suffered for us, leaving you an example that ye should follow His
  steps." Both quotes are from the same contiguous section.

1John.4.3 -- Epistle LXXII (To Jubaianus Concerning the Baptism of Heretics),
  section 15. Verbatim: "how can either darkness illuminate, or unrighteousness
  justify? And when they say that they are not of God, but are of the spirit of
  Antichrist..."

1John.5.7 -- Treatise I On the Unity of the Church, section 6. Verbatim: "And
  again it is written of the Father, and of the Son, and of the Holy Spirit,
  And these three are one."

1Pet.2.11 -- Epistle VI (To Rogatianus the Presbyter, and the Other Confessors),
  section 3. Verbatim: "And similarly Peter exhorts: 'As strangers,' says he,
  'and pilgrims, abstain from fleshly lusts, which war against the soul, having
  your conversation honest among the Gentiles...'"

1Pet.4.15 -- Epistle VI, section 4. Verbatim: "another returns to that country
  whence he was banished, to perish when arrested, not now as being a Christian,
  but as being a criminal!" Both 1Pet.2.11 and 1Pet.4.15 confirmed in the same
  epistle (sections 3 and 4 respectively).

1Pet.5.5 -- LEFT BLANK. The TOML quote is a composite of two separate epistles:
  - "...Crementius the sub-deacon...I judged it well to stand by your judgment"
    appears in Epistle XIV (To the Presbyters and Deacons at Rome), section 3.
  - "To the number of five, that I wrote to the clergy and to the people...one
    mode of action and one agreement" appears in Epistle XIX (To Caldonius).
  A single source_title cannot be assigned without asserting a false attribution.
  NOTE: this entry appears to be a database artefact -- a collage
  of two epistle excerpts joined under a single verse reference.

2John.1.10 -- The Seventh Council of Carthage Under Cyprian. Quote is the
  statement of "Also another Aurelius of Chullabi said: John the apostle laid it
  down in his epistle, saying: 'If any one come unto you, and have not the doctrine
  of Christ, receive him not into your house, and say not to him, Hail. For he that
  saith to him, Hail, partakes with his evil deeds.'" The TOML renders "Also another
  Aurelius of Chullabi said:" as "Said:".

2Thess.2.10 -- Epistle LIV (To Cornelius, Against Fortunatus and Felicissimus),
  section 13. The adjacent entry cyprian.2Thess.2.11.epistle-liv13 already uses
  source_title "Epistle LIV.13", confirming section 13 of Epistle LIV.

--- Title format ---

Matches the dominant work-level convention established in this file:
  "Treatise I On the Unity of the Church"   (14 occurrences -- dominant)
  "Treatise X On Jealousy and Envy"          (7 occurrences -- dominant)
  "Epistle VI"                               (6 occurrences)
  "Epistle LIV"                              (10 occurrences -- dominant)
  "Epistle LXXII"                            (11 occurrences -- dominant)
  "The Seventh Council of Carthage Under Cyprian" (8 occurrences)

--- Confidence ratings ---

cyprian.1John.3.15.unknown  -- HIGH: section 11 text confirmed verbatim at
  https://www.tertullian.org/fathers2/ANF-05/anf05-120.htm
  ("darkness of jealousy", "cloud of malice", "Cain", "murderer" all in section 11)

cyprian.1John.4.3.unknown   -- HIGH: section 15 text confirmed verbatim at
  https://www.newadvent.org/fathers/050672.htm
  ("how can either darkness illuminate, or unrighteousness justify?" + "spirit of
  Antichrist" both in section 15)

cyprian.1John.5.7.unknown   -- HIGH: section 6 confirmed at
  https://www.newadvent.org/fathers/050701.htm
  ("And these three are one" appears in section 6's Trinity argument)

cyprian.1Pet.2.11.unknown   -- HIGH: section 3 text confirmed verbatim at
  https://www.tertullian.org/fathers2/ANF-05/anf05-31.htm
  ("As strangers, says he, and pilgrims, abstain from fleshly lusts" in section 3)

cyprian.1Pet.2.21.unknown   -- HIGH: section 11 text confirmed verbatim at
  https://www.tertullian.org/fathers2/ANF-05/anf05-120.htm
  ("He follows Christ who stands in His precepts...Christ suffered for us,
  leaving you an example" is in section 11, same block as 1John.3.15)

cyprian.1Pet.4.15.unknown   -- HIGH: section 4 text confirmed verbatim at
  https://www.tertullian.org/fathers2/ANF-05/anf05-31.htm
  ("another returns to that country whence he was banished, to perish when
  arrested, not now as being a Christian, but as being a criminal!")

cyprian.1Pet.5.5.unknown    -- BLANK: composite of Epistle XIV section 3 and
  Epistle XIX. Cannot assign single title in good conscience.

cyprian.2John.1.10.unknown  -- HIGH: confirmed at
  https://www.tertullian.org/fathers2/ANF-05/anf05-124.htm
  (Aurelius of Chullabi's statement verbatim in The Seventh Council of Carthage)

cyprian.2Thess.2.10.unknown -- HIGH: confirmed at
  https://www.newadvent.org/fathers/050654.htm
  ("And for this cause God shall send them strong delusion...they all might be
  judged who believed not the truth" is in section 13 of Epistle LIV)

--- Spot-checked against primary source ---

  - cyprian.1John.3.15.unknown
    (https://www.tertullian.org/fathers2/ANF-05/anf05-120.htm, section 11)
    Quote opens: "Why do you rush into the darkness of jealousy? why do you enfold
    yourself in the cloud of malice?...he who is jealous of his brother...is bound
    by the guilt of homicide, the Apostle John declares in his epistle, saying,
    Whosoever hateth his brother is a murderer; and ye know that no murderer hath
    life abiding in him."
    Confirmed verbatim in Treatise X, section 11.

  - cyprian.1Pet.2.21.unknown
    (https://www.tertullian.org/fathers2/ANF-05/anf05-120.htm, section 11)
    Quote: "He follows Christ who stands in His precepts, who walks in the way of
    His teaching, who follows His footsteps and His ways, who imitates that which
    Christ both did and taught; in accordance with what Peter also exhorts and
    warns, saying, Christ suffered for us, leaving you an example that ye should
    follow His steps."
    Confirmed verbatim in Treatise X, section 11. Same section as 1John.3.15 --
    Failure Mode B check: both 1John.3.15 and 1Pet.2.21 are from Treatise X
    section 11 (they are NOT from a third independent section -- verified by reading
    section 11 in full). No off-by-one risk.

  - cyprian.2John.1.10.unknown
    (https://www.tertullian.org/fathers2/ANF-05/anf05-124.htm, Seventh Council)
    Quote: "Also another Aurelius of Chullabi said: John the apostle laid it down
    in his epistle, saying: 'If any one come unto you, and have not the doctrine
    of Christ, receive him not into your house, and say not to him, Hail. For he
    that saith to him, Hail, partakes with his evil deeds.'"
    Confirmed verbatim in The Seventh Council of Carthage Under Cyprian.

Run twice to verify idempotency.
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "cyprian.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only, 8 of 9 entries)
# cyprian.1Pet.5.5.unknown is left blank: composite of Epistle XIV sect.3 and
# Epistle XIX -- cannot assign a single work title honestly.
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # Treatise X On Jealousy and Envy, section 11
    # "Why do you rush into the darkness of jealousy? why do you enfold yourself
    # in the cloud of malice?...Whosoever hateth his brother is a murderer;
    # and ye know that no murderer hath life abiding in him."
    "cyprian.1John.3.15.unknown": "Treatise X On Jealousy and Envy",

    # Epistle LXXII (To Jubaianus Concerning Baptism of Heretics), section 15
    # "how can either darkness illuminate, or unrighteousness justify?
    # And when they say that they are not of God, but are of the spirit of Antichrist"
    "cyprian.1John.4.3.unknown": "Epistle LXXII",

    # Treatise I On the Unity of the Church, section 6
    # "And again it is written of the Father, and of the Son, and of the Holy
    # Spirit, And these three are one."
    "cyprian.1John.5.7.unknown": "Treatise I On the Unity of the Church",

    # Epistle VI (To Rogatianus the Presbyter and the Other Confessors), section 3
    # "As strangers, says he, and pilgrims, abstain from fleshly lusts, which war
    # against the soul, having your conversation honest among the Gentiles..."
    "cyprian.1Pet.2.11.unknown": "Epistle VI",

    # Treatise X On Jealousy and Envy, section 11 (same section as 1John.3.15)
    # "He follows Christ who stands in His precepts, who walks in the way of His
    # teaching...in accordance with what Peter also exhorts and warns, saying,
    # Christ suffered for us, leaving you an example that ye should follow His steps."
    "cyprian.1Pet.2.21.unknown": "Treatise X On Jealousy and Envy",

    # Epistle VI (To Rogatianus the Presbyter and the Other Confessors), section 4
    # "another returns to that country whence he was banished, to perish when
    # arrested, not now as being a Christian, but as being a criminal!"
    "cyprian.1Pet.4.15.unknown": "Epistle VI",

    # The Seventh Council of Carthage Under Cyprian
    # Statement of Aurelius of Chullabi: "John the apostle laid it down in his
    # epistle, saying: If any one come unto you, and have not the doctrine of
    # Christ, receive him not into your house, and say not to him, Hail."
    "cyprian.2John.1.10.unknown": "The Seventh Council of Carthage Under Cyprian",

    # Epistle LIV (To Cornelius, Against Fortunatus and Felicissimus), section 13
    # "And for this cause God shall send them strong delusion, that they should
    # believe a lie: that they all might be judged who believed not the truth,
    # but had pleasure in unrighteousness."
    # Adjacent entry cyprian.2Thess.2.11.epistle-liv13 already uses Epistle LIV.13
    "cyprian.2Thess.2.10.unknown": "Epistle LIV",
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
    # Note: cyprian.1Pet.5.5.unknown intentionally left blank (composite quote)
    print("Note: cyprian.1Pet.5.5.unknown left blank intentionally -- composite")
    print("      of Epistle XIV section 3 + Epistle XIX. See docstring for detail.")

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
             "data/church-fathers/cyprian.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 8, f"Expected 8 patch entries, got {len(PATCH)}"
    main()
