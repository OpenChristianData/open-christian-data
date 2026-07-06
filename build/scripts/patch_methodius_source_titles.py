"""
Patch source_title for Methodius of Olympus blank entries (39 entries).

Sources used:
- TOML quote content (explicit resurrection/virginity/Simeon themes)
- Adjacent populated entries in the JSON (verse-sibling analysis)
- Methodius's major works: Symposium/Banquet of the Ten Virgins (Discourses I-XI),
  On the Resurrection, Oration Concerning Simeon and Anna, Oration on the Psalms

Confidence tiers:
  HIGH   = content definitively matches specific work; or both adjacent entries confirm
  MEDIUM = content consistent with work + at least one adjacent entry confirms
  LOW    = best-guess from single adjacent entry or content theme only

Run twice to verify idempotency (TEST-05).
"""

import json
from collections import Counter
from pathlib import Path

INPUT_FILE = Path(__file__).parent.parent.parent / "data" / "church-fathers" / "methodius-of-olympus.json"
OUTPUT_FILE = INPUT_FILE  # patch in place

HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"

OVERRIDES: dict[str, tuple[str, str]] = {

    # ==========================================================================
    # 1 CORINTHIANS
    # ==========================================================================

    # "let us ask him to explain what was the evil which the apostle hated and willed not to do"
    # Paul's will/sin discussion (Rom 7 context). Adjacent after: 1Cor.11.7 = From Disc Resurrection.
    "methodius-of-olympus.1Cor.11.1.unknown": ("Methodius From the Discourse on the Resurrection", MEDIUM),

    # "kingdom of heaven and the resurrection, when that which is in part shall be done away"
    # Eschatological/resurrection content. Adjacent before: From Disc Resurrection (1Cor.11.7).
    "methodius-of-olympus.1Cor.13.10.unknown": ("Methodius From the Discourse on the Resurrection", MEDIUM),

    # "shadows and figures have ceased; we hasten on to the truth... know in part through a glass"
    # Typological/eschatological language; adjacent after: 1Cor.13.2 = Disc IX Tusiane.
    "methodius-of-olympus.1Cor.13.12.unknown": ("Methodius Discourse IX. Tusiane", MEDIUM),

    # "the corruptible and mortal putting on incorruption and immortality"
    # Resurrection body content; between 1Cor.15.41 = Disc VII and 1Cor.15.49 = From Disc Resurrection.
    "methodius-of-olympus.1Cor.15.42.unknown": ("Methodius From the Discourse on the Resurrection", MEDIUM),

    # "In Christ Jesus I have begotten you through the Gospel."
    # Brief quote; between 1Cor.3.7 = From Disc Resurrection and 1Cor.7.1 = Disc III.
    # LOW -- single adjacent match.
    "methodius-of-olympus.1Cor.4.15.unknown": ("Methodius From the Discourse on the Resurrection", LOW),

    # "not 'the world' but the 'fashion of this world' passeth away" (1Cor 7:31)
    # Virginity/world-passing argument; adjacent 1Cor.7.29 = Disc III, 1Cor.7.34 = Disc V.
    # Same argument appears verbatim in Mark.13.31.unknown (see below).
    "methodius-of-olympus.1Cor.7.31.unknown": ("Methodius Discourse III. Thaleia", MEDIUM),

    # "challenging them to the same things... powerfully supporting the state of virginity"
    # Explicit virginity content; adjacent Disc III entries (7.29, 7.34).
    "methodius-of-olympus.1Cor.7.32.unknown": ("Methodius Discourse III. Thaleia", MEDIUM),

    # "the higher praise which Paul accords to chastity"
    # Explicit chastity content; between Disc V (7.34) and Disc III (7.36).
    "methodius-of-olympus.1Cor.7.35.unknown": ("Methodius Discourse III. Thaleia", MEDIUM),

    # "in marriage doeth well; but he that giveth her not in marriage doeth better"
    # Virginity theme; flanked by 1Cor.7.36/7.37 = Disc III.
    "methodius-of-olympus.1Cor.7.38.unknown": ("Methodius Discourse III. Thaleia", MEDIUM),

    # ==========================================================================
    # 1 JOHN
    # ==========================================================================

    # "when the days of our present life shall fail... world which lieth in wickedness"
    # World-passing theme; adjacent after: 1Pet.2.10 = Disc III.
    # LOW -- single adjacent + ambiguous content.
    "methodius-of-olympus.1John.5.19.unknown": ("Methodius Discourse III. Thaleia", LOW),

    # ==========================================================================
    # 1 THESSALONIANS
    # ==========================================================================

    # "Then we which are alive shall be caught up... meaning our souls"
    # Rapture/resurrection theme; adjacent before: 1Thess.4.16 = Disc VI Agathe.
    "methodius-of-olympus.1Thess.4.17.unknown": ("Methodius Discourse VI. Agathe", MEDIUM),

    # ==========================================================================
    # 1 TIMOTHY
    # ==========================================================================

    # "God will have all men to be saved, and to come unto the knowledge of the truth"
    # Brief; adjacent before: 1Tim.1.17 = Oration Concerning Simeon and Anna.
    "methodius-of-olympus.1Tim.2.4.unknown": ("Methodius Oration Concerning Simeon and Anna", MEDIUM),

    # ==========================================================================
    # 2 CORINTHIANS
    # ==========================================================================

    # "the followers of Origen bring forward this passage 'if our earthly house were dissolved'"
    # Explicitly debates Origen's resurrection doctrine -- core argument of On the Resurrection.
    "methodius-of-olympus.2Cor.5.1.unknown": ("Methodius From the Discourse on the Resurrection", HIGH),

    # "The apostle here calls 'clothing'" — resurrection body clothing metaphor (2Cor 5:2).
    # Content = resurrection body; adjacent Oration Concerning Simeon entries on either side.
    "methodius-of-olympus.2Cor.5.2.unknown": ("Methodius From the Discourse on the Resurrection", MEDIUM),

    # "our souls shall be with God, until we shall receive the new house... the resurrection"
    # Explicit intermediate state / resurrection body doctrine.
    "methodius-of-olympus.2Cor.5.4.unknown": ("Methodius From the Discourse on the Resurrection", HIGH),

    # "immortality... every weakness and mortality will be entirely 'swallowed up'"
    # Resurrection body / immortality; immediately adjacent after: 2Cor.7.4 = Oration Concerning Simeon.
    "methodius-of-olympus.2Cor.5.7.unknown": ("Methodius From the Discourse on the Resurrection", HIGH),

    # ==========================================================================
    # ACTS
    # ==========================================================================

    # "holds the helm of the universe; the very Principle of all good order" — doxological.
    # Adjacent before: 2Cor.7.4 = Oration Concerning Simeon; after: Acts.28.26 = Oration Concerning Simeon.
    "methodius-of-olympus.Acts.18.28.unknown": ("Methodius Oration Concerning Simeon and Anna", MEDIUM),

    # ==========================================================================
    # COLOSSIANS
    # ==========================================================================

    # "Blotted out the handwriting which was against us." — very brief; cross/redemption.
    # Adjacent before: Bar.3.14-15 = Symposium 8:2-3; after: Col.1.15 = Disc III.
    # LOW -- single adjacent match.
    "methodius-of-olympus.Col.2.4.unknown": ("Methodius Discourse III. Thaleia", LOW),

    # ==========================================================================
    # EPHESIANS
    # ==========================================================================

    # "together with the Son, who was made man for our sakes, according to the good pleasure"
    # Christological; adjacent after: Eph.1.21 = Disc III.
    "methodius-of-olympus.Eph.1.5.unknown": ("Methodius Discourse III. Thaleia", MEDIUM),

    # "transformation into the image of the Word" — ecclesial/Christological.
    # Between blank Eph entries flanked by Eph.1.21 = Disc III and Eph.5.28 = Disc III.
    "methodius-of-olympus.Eph.3.14.unknown": ("Methodius Discourse III. Thaleia", MEDIUM),

    # "present the Church to Himself glorious... having cleansed her by the laver" — bride/baptism.
    # Immediately adjacent after: Eph.5.28 = Disc III.
    "methodius-of-olympus.Eph.5.26.unknown": ("Methodius Discourse III. Thaleia", MEDIUM),

    # ==========================================================================
    # GALATIANS
    # ==========================================================================

    # "a plaster with a lump of figs, that is, the fruit of the Spirit, that he may be healed"
    # Isaiah 38:21 fig-plaster applied to Hezekiah; Isa healing theme.
    # Adjacent after: Hab.2.20 = ORATION CONCERNING SIMEON AND ANNA 4.
    "methodius-of-olympus.Gal.5.22.unknown": ("Methodius Oration Concerning Simeon and Anna", MEDIUM),

    # ==========================================================================
    # HEBREWS
    # ==========================================================================

    # "Is the Spirit of truth, the Paraclete, of whom the illuminated" — pneumatology.
    # Both adjacent entries are Disc V: Heb.10.1 and Heb.11.10 = Disc V Thallousa.
    "methodius-of-olympus.Heb.10.32.unknown": ("Methodius Discourse V. Thallousa", HIGH),

    # "most beautiful flower; the mother of the Creator; the nurse of the Nourisher"
    # Explicitly Marian/Theotokos language about Christ's birth -- heart of the Oration
    # Concerning Simeon and Anna (a homily on the Presentation at the Temple).
    # Adjacent after: Heb.2.16 = Oration Concerning Simeon and Anna.
    "methodius-of-olympus.Heb.1.3.unknown": ("Methodius Oration Concerning Simeon and Anna", HIGH),

    # ==========================================================================
    # JONAH
    # ==========================================================================

    # "the whale signifies Time... Jonah = first man who fled from God after sin...
    #  so shall we all rise again" — extended resurrection typology of Jonah story.
    "methodius-of-olympus.Jonah.1.1.unknown": ("Methodius From the Discourse on the Resurrection", HIGH),

    # "as Jonah spent three days... so shall we all rise again... the resurrection,
    #  which is the beginning of the future age" — explicit resurrection typology.
    "methodius-of-olympus.Jonah.2.1.unknown": ("Methodius From the Discourse on the Resurrection", HIGH),

    # ==========================================================================
    # LUKE
    # ==========================================================================

    # "your Father's good pleasure to give you the kingdom, tread upon necks of enemies"
    # Brief; adjacent after: Luke.12.35 = Disc V Thallousa.
    "methodius-of-olympus.Luke.12.32.unknown": ("Methodius Discourse V. Thallousa", MEDIUM),

    # "the rich man says: 'I have five brethren; lest they also come into this place of torment'"
    # Rich Man / Lazarus passage (Lk 16:28); adjacent after: Luke.16.9 = From Disc Resurrection.
    "methodius-of-olympus.Luke.16.28.unknown": ("Methodius From the Discourse on the Resurrection", MEDIUM),

    # "leaping for joy... chanted his hymn of thanksgiving... proclaimed the Light to lighten
    #  the Gentiles" — extended description of Simeon at the Temple. Definitively from the
    # Oration Concerning Simeon and Anna (the homily about this very event).
    # Adjacent before: Luke.2.22 = Oration Concerning Simeon and Anna.
    "methodius-of-olympus.Luke.2.32.unknown": ("Methodius Oration Concerning Simeon and Anna", HIGH),

    # "They heard that the demons had been put to flight; the sick restored to health" — brief.
    # Adjacent after: Mark.11.8 = Oration on Palms; before: Luke.2.38 = Oration Concerning Simeon.
    # LOW -- mixed adjacent signals.
    "methodius-of-olympus.Luke.8.29.unknown": ("Methodius Oration Concerning Simeon and Anna", LOW),

    # ==========================================================================
    # MARK
    # ==========================================================================

    # "Scripture's habit to call the passing from worse to better as 'destruction'...
    #  Paul says it is not the world as such but the 'fashion of this world' that passes away"
    # Content nearly verbatim identical to 1Cor.7.31 above (same passage, dual reference).
    # LOW -- no adjacent Symposium entries; parallel assigned to Disc III above.
    "methodius-of-olympus.Mark.13.31.unknown": ("Methodius Discourse III. Thaleia", LOW),

    # "Thou hast graciously given unto us a return to Paradise... by means of Him who hath
    #  power to forgive sins" — doxological; Christological redemption.
    # Adjacent after: Mark.1.22 = Oration Concerning Simeon and Anna.
    "methodius-of-olympus.Mark.2.10.unknown": ("Methodius Oration Concerning Simeon and Anna", MEDIUM),

    # ==========================================================================
    # PHILIPPIANS
    # ==========================================================================

    # "Christ having risen again the third day... by all created things equally adored;
    #  for to Him every knee shall bow" — resurrection and universal lordship.
    # Adjacent after: Phil.2.5 = Methodius Fragments. LOW -- no clear adjacent match.
    "methodius-of-olympus.Phil.2.10.unknown": ("Methodius From the Discourse on the Resurrection", LOW),

    # "these promises, it is evident, will be fulfilled after the resurrection"
    # Explicit resurrection; immediately adjacent after: Phil.3.21 = From Disc Resurrection.
    "methodius-of-olympus.Phil.3.11.unknown": ("Methodius From the Discourse on the Resurrection", HIGH),

    # ==========================================================================
    # REVELATION
    # ==========================================================================

    # "the company of virgins always follow the Lord... John signifies in the commemoration
    #  of the hundred and forty-four thousand" — 144,000 virgins = core Banquet of Ten Virgins
    # theme. Adjacent: Rev.2.7 = BANQUET OF TEN VIRGINS 9.3 (twice, immediately before).
    "methodius-of-olympus.Rev.7.4.unknown": ("BANQUET OF THE TEN VIRGINS", HIGH),

    # ==========================================================================
    # ROMANS
    # ==========================================================================

    # "But the females to be preserved alive. For the devil, ruling" — very brief fragment.
    # Adjacent after: Rom.6.4 = From Disc Resurrection. LOW -- fragment only.
    "methodius-of-olympus.Rom.5.14.unknown": ("Methodius From the Discourse on the Resurrection", LOW),

    # "Was then that which is good made death unto me?" — law/sin discussion (Rom 7:13).
    # Flanked on both sides: Rom.7.12 = From Disc Resurrection; Rom.7.14 = From Disc Resurrection.
    "methodius-of-olympus.Rom.7.13.unknown": ("Methodius From the Discourse on the Resurrection", HIGH),

    # "delivered from the bondage of corruption into the glorious liberty of the children of God"
    # Flanked on both sides: Rom.7.9 = From Disc Resurrection; Rom.8.2 = From Disc Resurrection.
    "methodius-of-olympus.Rom.8.19.unknown": ("Methodius From the Discourse on the Resurrection", HIGH),

    # "the wondrous condescension to us men of the awful glory of Him who is God over all"
    # Christological doxology (Rom 9:5). Adjacent before: chain of From Disc Resurrection.
    # LOW -- chain adjacency only.
    "methodius-of-olympus.Rom.9.5.unknown": ("Methodius From the Discourse on the Resurrection", LOW),
}

_EXPECTED_PATCH_COUNT = 39


def main() -> None:
    assert len(OVERRIDES) == _EXPECTED_PATCH_COUNT, (
        f"OVERRIDES has {len(OVERRIDES)} entries, expected {_EXPECTED_PATCH_COUNT}. "
        "Update _EXPECTED_PATCH_COUNT after adding or removing entries."
    )

    print(f"Loading {INPUT_FILE}")
    with open(INPUT_FILE, encoding="utf-8") as f:
        data = json.load(f)

    entries = data["data"]
    blank_before = sum(1 for e in entries if not e.get("source_title"))
    print(f"Blank source_title entries before patch: {blank_before}")

    patched = 0
    skipped = 0
    confidence_counts: Counter = Counter()
    patched_titles: Counter = Counter()
    unresolved: list[str] = []

    for entry in entries:
        entry_id = entry["entry_id"]
        if entry.get("source_title"):
            skipped += 1
            continue
        if entry_id in OVERRIDES:
            title, confidence = OVERRIDES[entry_id]
            entry["source_title"] = title
            patched += 1
            confidence_counts[confidence] += 1
            patched_titles[title] += 1
        else:
            unresolved.append(entry_id)

    blank_after = sum(1 for e in entries if not e.get("source_title"))

    print(f"Already populated (skipped): {skipped}")
    print(f"Patched: {patched}")
    print(f"  HIGH confidence:   {confidence_counts[HIGH]}")
    print(f"  MEDIUM confidence: {confidence_counts[MEDIUM]}")
    print(f"  LOW confidence:    {confidence_counts[LOW]}")
    print(f"Blank source_title entries after patch: {blank_after}")

    if unresolved:
        print(f"UNRESOLVED ({len(unresolved)}):")
        for eid in unresolved:
            print(f"  {eid}")
    else:
        print("All blank entries resolved.")

    if patched == 0 and not unresolved:
        print("No changes needed -- all entries already fully patched (idempotent re-run).")
        return

    if patched_titles:
        print("\nAssignment summary (titles patched this run):")
        for title, count in sorted(patched_titles.items(), key=lambda x: -x[1]):
            print(f"  {count:3d}  {title}")

    print(f"\nWriting {OUTPUT_FILE}")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("Done.")


if __name__ == "__main__":
    main()
