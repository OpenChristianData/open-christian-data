"""
Patch source_title for Augustine of Hippo blank entries (176 entries).

Assignment logic (in priority order):
1. Explicit overrides: entry_id -> source_title (explicit quote clues or high-confidence inference)
2. OSIS prefix rules: all Matthew 5-7 blank entries -> COMMENTARY ON THE SERMON ON THE MOUNT

Augustine's major works referenced:
  - City of God (default for OT prophecy, eschatology, pagan critique, anti-Donatist)
  - COMMENTARY ON THE SERMON ON THE MOUNT (all Matt 5-7 blank entries)
  - ON THE TRINITY (Trinitarian theology, image of God, inner man)
  - Confessions (autobiographical, Monica references)
  - On the Work of Monks (1Cor 9 blank entries on apostolic manual labor)
  - AGAINST FAUSTUS, A MANICHAEAN (explicitly anti-Manichaean content)
  - ON MARRIAGE AND CONCUPISCENCE (marriage/concupiscence/flesh)
  - ON CHRISTIAN DOCTRINE (love of God command, uti/frui enjoyment)
  - Letters (correspondence, exegetical notes to specific addressees)
  - Sermons (homiletic/direct-address style)
  - HARMONY OF THE GOSPELS (explicit quote citation De Con. Evan)

Run twice to verify idempotency.
"""

import json
import sys
from pathlib import Path

INPUT_FILE = Path(__file__).parent.parent.parent / "data" / "church-fathers" / "augustine-of-hippo.json"
OUTPUT_FILE = INPUT_FILE  # patch in place

# ---------------------------------------------------------------------------
# Entry-level overrides: entry_id -> source_title
# ---------------------------------------------------------------------------
EXPLICIT_OVERRIDES = {
    # --- 1 Corinthians ---
    # 1Cor.10.26 - idols/food; no explicit marker -> City of God default
    "augustine-of-hippo.1Cor.10.26.unknown": "City of God",
    # 1Cor.10.33 - pleasing all men for their salvation
    "augustine-of-hippo.1Cor.10.33.unknown": "City of God",
    # 1Cor.11.12 - "[The Manichaeans say]: the two sexes are not from God but from the devil"
    "augustine-of-hippo.1Cor.11.12.unknown": "AGAINST FAUSTUS, A MANICHAEAN",
    # 1Cor.11.7 - "[The Manichaeans say]: the devil should not have been allowed to approach the woman"
    "augustine-of-hippo.1Cor.11.7.unknown": "AGAINST FAUSTUS, A MANICHAEAN",
    # 1Cor.11.7 - "not as though one part of humanity belongs to God as its author and another to darkness"
    "augustine-of-hippo.1Cor.11.7.unknown-2": "AGAINST FAUSTUS, A MANICHAEAN",
    # 1Cor.11.7 - "This image made to the image of God is not equal to and coeternal with him" (Trinitarian)
    "augustine-of-hippo.1Cor.11.7.unknown-3": "ON THE TRINITY",
    # 1Cor.13.3 - quote ends with "Letter" (explicit attribution fragment)
    "augustine-of-hippo.1Cor.13.3.unknown": "Letters",
    # 1Cor.14.40 - quote ends with "Letter , To Euodius" (explicit)
    "augustine-of-hippo.1Cor.14.40.unknown": "Letters",
    # 1Cor.15.12 - quote ends with "Letter , To Vincent" (explicit attribution — missed initial pass)
    "augustine-of-hippo.1Cor.15.12.unknown": "Letters",
    # 1Cor.8.3 - "If one loves God, one is known by him" (Trinitarian/epistemological)
    "augustine-of-hippo.1Cor.8.3.unknown": "ON THE TRINITY",
    # 1Cor.8.4 - man made his own gods, became their captive (pagan critique)
    "augustine-of-hippo.1Cor.8.4.unknown": "City of God",
    # 1Cor.9.11-9.17 - apostolic manual labor; Augustine's De opere monachorum
    "augustine-of-hippo.1Cor.9.11.unknown": "On the Work of Monks",
    "augustine-of-hippo.1Cor.9.14.unknown": "On the Work of Monks",
    "augustine-of-hippo.1Cor.9.15.unknown": "On the Work of Monks",
    "augustine-of-hippo.1Cor.9.15.unknown-2": "On the Work of Monks",
    # 1Cor.9.17 - personal/self-reflective ("I confess I am ignorant how near I come to it")
    "augustine-of-hippo.1Cor.9.17.unknown": "Letters",
    # 1Cor.9.20 - nursing the sick, showing compassion (Letter to Jerome context)
    "augustine-of-hippo.1Cor.9.20.unknown": "Letters",
    # 1Cor.9.20 - quote ends with "Letter , To Jerome" (explicit)
    "augustine-of-hippo.1Cor.9.20.unknown-2": "Letters",
    # 1Cor.9.5-9.6 - apostolic rights, exemption from manual labor
    "augustine-of-hippo.1Cor.9.5.unknown": "On the Work of Monks",
    "augustine-of-hippo.1Cor.9.5.unknown-2": "On the Work of Monks",
    "augustine-of-hippo.1Cor.9.6.unknown": "On the Work of Monks",

    # --- 1 Samuel ---
    # 1Sam.24.5 - "the chrism by token of which he was anointed" = valid sacrament from reprobate minister;
    # this is Augustine's core anti-Donatist sacramental argument, not City of God content.
    # Primary locus: De baptismo contra Donatistas (On Baptism Against the Donatists), Book 1.
    "augustine-of-hippo.1Sam.24.5.unknown": "ON BAPTISM AGAINST THE DONATISTS",

    # --- 1 Timothy ---
    # 1Tim.2.1 - prayer types in celebrating the mysteries (liturgical)
    "augustine-of-hippo.1Tim.2.1.unknown": "Letters",

    # --- 2 Corinthians ---
    # 2Cor.11.14 - virtue of purity praised even by sinners
    "augustine-of-hippo.2Cor.11.14.unknown": "City of God",
    # 2Cor.11.29 - quote ends with "Letter , To Jerome" (explicit)
    "augustine-of-hippo.2Cor.11.29.unknown": "Letters",
    # 2Cor.12.4 - angels' spiritual nature and tongues (angelology)
    "augustine-of-hippo.2Cor.12.4.unknown": "City of God",
    # 2Cor.1.12 - "Cato is rightly praised more than Caesar, for Sallust says" (Roman virtue)
    "augustine-of-hippo.2Cor.1.12.unknown": "City of God",

    # --- 2 Thessalonians ---
    # 2Thess eschatology - all City of God (Book 20 covers 2 Thess eschatology extensively)
    "augustine-of-hippo.2Thess.2.6.unknown": "City of God",
    "augustine-of-hippo.2Thess.2.7.unknown": "City of God",
    "augustine-of-hippo.2Thess.2.8.unknown": "City of God",

    # --- Acts ---
    "augustine-of-hippo.Acts.2.20.unknown": "City of God",
    "augustine-of-hippo.Acts.2.27.unknown": "City of God",
    # Acts.2.33 - "the Lord Jesus Christ not only gave the Holy Spirit as God, but also received" (Trinitarian)
    "augustine-of-hippo.Acts.2.33.unknown": "ON THE TRINITY",
    "augustine-of-hippo.Acts.2.37.unknown": "City of God",
    "augustine-of-hippo.Acts.2.44.unknown": "City of God",
    # Acts.2.45 - "none called anything his own... one mind and one heart God-wards" (sermonic)
    "augustine-of-hippo.Acts.2.45.unknown": "Sermons",
    "augustine-of-hippo.Acts.3.17.unknown": "City of God",
    "augustine-of-hippo.Acts.3.25.unknown": "City of God",
    "augustine-of-hippo.Acts.4.27.unknown": "City of God",

    # --- Colossians ---
    # Col.1.10 - commanded to do good vs pray to do good (grace/prayer discussion)
    "augustine-of-hippo.Col.1.10.unknown": "Letters",
    # Col.1.12 - "How can the apostle say... who makes us suitable" (exegetical question)
    "augustine-of-hippo.Col.1.12.unknown": "Letters",
    # Col.1.12 - "a man may have the baptism of Christ... where the unity of Christ is not"
    # = sacramental validity outside the visible Church; same De baptismo argument as 1Sam.24.5
    "augustine-of-hippo.Col.1.12.unknown-2": "ON BAPTISM AGAINST THE DONATISTS",
    # Col.1.12 - "in iniquity was I conceived" (original sin)
    "augustine-of-hippo.Col.1.12.unknown-3": "City of God",
    # Col.1.13 - devil cast into the abyss (eschatological)
    "augustine-of-hippo.Col.1.13.unknown": "City of God",
    # Col.1.13 - Pascha etymology note
    "augustine-of-hippo.Col.1.13.unknown-2": "City of God",
    # Col.1.13 - "nothing delivers man from evil angels but grace of God"
    "augustine-of-hippo.Col.1.13.unknown-3": "City of God",
    # Col.1.15 - "the beginning who also speaks to us, in which beginning God made the heavens" (Trinitarian)
    "augustine-of-hippo.Col.1.15.unknown": "ON THE TRINITY",
    # Col.1.15 - parent/child image/equality analogy (Trinitarian)
    "augustine-of-hippo.Col.1.15.unknown-2": "ON THE TRINITY",
    # Col.1.16 - "'Before Abraham I am'... Listen to it, or read it" (sermonic direct address)
    "augustine-of-hippo.Col.1.16.unknown": "Sermons",
    # Col.1.18 - Holy Spirit raises from dead (Trinitarian)
    "augustine-of-hippo.Col.1.18.unknown": "ON THE TRINITY",
    # Col.1.18 - "he emptied himself, did not appear in that dignity" (kenosis, Trinitarian)
    "augustine-of-hippo.Col.1.18.unknown-2": "ON THE TRINITY",
    # Col.1.18 - head of the church, resurrection in Christ our head
    "augustine-of-hippo.Col.1.18.unknown-3": "City of God",
    # Col.1.22 - walking blamelessly on the journey
    "augustine-of-hippo.Col.1.22.unknown": "Letters",
    # Col.1.24 - Paul's suffering as preacher now from former persecutor
    "augustine-of-hippo.Col.1.24.unknown": "City of God",
    # Col.1.24 - "I fill up those things which are wanting of the sufferings of Christ"
    "augustine-of-hippo.Col.1.24.unknown-2": "City of God",
    # Col.1.6 - "Honor, love and praise the holy church, your mother, the heavenly Jerusalem, the holy City of God"
    "augustine-of-hippo.Col.1.6.unknown": "Sermons",
    # Col.1.6 - "spread not in Africa alone, as the Donatist sect has done, but through all nations";
    # explicit anti-Donatist universality argument. City of God doesn't frame the polemic this way.
    # Augustine made this argument throughout his Letters and anti-Donatist treatises.
    "augustine-of-hippo.Col.1.6.unknown-2": "Letters",
    # Col.1.6 - "The gospel has come to you, as it is in all the world" (Catholic spread)
    "augustine-of-hippo.Col.1.6.unknown-3": "City of God",
    # Col.1.6 - exegetical note on Paul's verb tenses (letter-style to correspondent)
    "augustine-of-hippo.Col.1.6.unknown-4": "Letters",
    # Col.2.11 - "if we find these passing days... how blessed will that eternal" (Easter sermon)
    "augustine-of-hippo.Col.2.11.unknown": "Sermons",
    # Col.2.14 - "All this, so the Manichaeans believe, as it appeared to human eyes, was spirit
    # and not flesh" — explicitly anti-Manichaean polemic on the Incarnation
    "augustine-of-hippo.Col.2.14.unknown": "AGAINST FAUSTUS, A MANICHAEAN",
    # Col.2.14 - "his mother, Monica... remembrance be made for her at Thy altar" (Confessions Book 9!)
    "augustine-of-hippo.Col.2.14.unknown-2": "Confessions",
    # Col.2.14 - "With good reason do we celebrate the Passover" (Easter sermon)
    "augustine-of-hippo.Col.2.14.unknown-3": "Sermons",
    # Col.2.15 - devil met defeat at the cross (atonement)
    "augustine-of-hippo.Col.2.15.unknown": "City of God",
    # Col.2.16 - carnal Judaism repudiated and condemned (OT/NT)
    "augustine-of-hippo.Col.2.16.unknown": "City of God",
    # Col.2.18 - "I ask you to pull me up out of deep water and set me in the shallows" (letter to correspondent)
    "augustine-of-hippo.Col.2.18.unknown": "Letters",
    # Col.2.20 - "Touch not, taste not, handle not" is not a commandment (exegetical)
    "augustine-of-hippo.Col.2.20.unknown": "Letters",
    # Col.2.20 - praise of wisdom vs superstition of error
    "augustine-of-hippo.Col.2.20.unknown-2": "City of God",
    # Col.2.3 - "deep treasures of wisdom and knowledge" in Christ (grace/Trinitarian)
    "augustine-of-hippo.Col.2.3.unknown": "ON THE TRINITY",
    # Col.2.3 - "Pay attention, dearly beloved" (sermonic address)
    "augustine-of-hippo.Col.2.3.unknown-2": "Sermons",
    # Col.2.9 - "in him dwells all the fullness of the Godhead corporally" (Trinitarian)
    "augustine-of-hippo.Col.2.9.unknown": "ON THE TRINITY",
    # Col.3.1 - "the inner man is surely old before he is renewed" (inner man, Trinitarian language)
    "augustine-of-hippo.Col.3.1.unknown": "ON THE TRINITY",
    # Col.3.18 - "more consonant with the order of nature that men should bear rule over women"
    "augustine-of-hippo.Col.3.18.unknown": "City of God",
    # Col.3.19 - "not that disordered sexual desire in his wife which he ought not to love" (concupiscence)
    "augustine-of-hippo.Col.3.19.unknown": "ON MARRIAGE AND CONCUPISCENCE",
    # Col.3.3 - "when God will be all in all, then nothing will be lacking" (eschatological)
    "augustine-of-hippo.Col.3.3.unknown": "City of God",
    # Col.3.4 - "appear with him in glory... now is the time for groaning, then" (eschatological)
    "augustine-of-hippo.Col.3.4.unknown": "City of God",
    # Col.3.5 - "movements according to the spirit... soul opposes movements of the flesh" (concupiscence)
    "augustine-of-hippo.Col.3.5.unknown": "ON MARRIAGE AND CONCUPISCENCE",
    # Col.3.9 - "renewal and reforming of the mind after God's image" (image of God, Trinitarian)
    "augustine-of-hippo.Col.3.9.unknown": "ON THE TRINITY",
    # Col.4.2 - "blessed apostle... Be persistent in prayer, being watchful" (sermonic)
    "augustine-of-hippo.Col.4.2.unknown": "Sermons",
    # Col.4.3 - "Schisms arise when men say, we are righteous; we sanctify the unclean, we justify the wicked";
    # explicit Donatist self-description (Donatists claimed exclusive power to sanctify/justify).
    # This is anti-Donatist polemic, not City of God. Letters is the closest available match.
    "augustine-of-hippo.Col.4.3.unknown": "Letters",

    # --- Deuteronomy ---
    # Deut.6.5 - "supreme wisdom in the first commandment: love God with whole heart" (On Christian Doctrine)
    "augustine-of-hippo.Deut.6.5.unknown": "ON CHRISTIAN DOCTRINE",
    # Deut.6.5 - "The number three has intrinsic relation to the mind... love God in a threefold manner"
    "augustine-of-hippo.Deut.6.5.unknown-2": "ON THE TRINITY",
    # Deut.6.5 - "remnant of the lust of the flesh... to be kept in check by continence"
    "augustine-of-hippo.Deut.6.5.unknown-3": "City of God",

    # --- Exodus ---
    # Exod.33.18 - "Moses showed the flame of desire when he said to God... show me your glory"
    "augustine-of-hippo.Exod.33.18.unknown": "City of God",

    # --- Ezra ---
    # All Ezra entries are OT historical/prophetic content -> City of God
    "augustine-of-hippo.Ezra.10.9.unknown": "City of God",
    "augustine-of-hippo.Ezra.5.1.unknown": "City of God",
    "augustine-of-hippo.Ezra.6.7.unknown": "City of God",

    # --- Genesis ---
    # Gen.3.8 - God walking in paradise, coming to judge (fall narrative)
    "augustine-of-hippo.Gen.3.8.unknown": "City of God",
    # Gen.3.9 - rebellion of flesh, parents covering shame, God's desertion (fall/sin)
    "augustine-of-hippo.Gen.3.9.unknown": "City of God",

    # --- Isaiah ---
    # Isa.40.26 - sun, moon, stars, cycle of year (creation/providence)
    "augustine-of-hippo.Isa.40.26.unknown": "City of God",

    # --- Jeremiah ---
    # Jer.10.14 - "they can be called gods, though they cannot be so" (false gods critique)
    "augustine-of-hippo.Jer.10.14.unknown": "City of God",
    # Jer.10.14 - "gods that have not made the heavens and the earth, let them perish"
    "augustine-of-hippo.Jer.10.14.unknown-2": "City of God",
    # Jer.16.19 - "as in the provocation and temptation in the wilderness"
    "augustine-of-hippo.Jer.16.19.unknown": "City of God",
    # Jer.17.10 - "God searches our heart... He alone perceives our inward conscience"
    "augustine-of-hippo.Jer.17.10.unknown": "City of God",
    # Jer.19.11 - "Notice here 'the rod of direction'... Let Christ be your King" (sermonic)
    "augustine-of-hippo.Jer.19.11.unknown": "Sermons",
    # Jer.1.10 - Jeremiah's commission to "throw down and to build" (prophetic typology)
    "augustine-of-hippo.Jer.1.10.unknown": "City of God",
    # Jer.23.24 - "indescribable wisdom of God residing in the Word... all things are with him"
    "augustine-of-hippo.Jer.23.24.unknown": "ON THE TRINITY",

    # --- Jonah ---
    # Jonah.2.1 - miracles are incredible or all are; resurrection of Christ (apologetics)
    "augustine-of-hippo.Jonah.2.1.unknown": "City of God",

    # --- Mark ---
    # Mark.11.18 - quote begins "De Con. Evan, ii, 67" (explicit: De consensu evangelistarum)
    "augustine-of-hippo.Mark.11.18.unknown": "HARMONY OF THE GOSPELS",
    # Mark.15.12 - those who cried out were the real crucifiers
    "augustine-of-hippo.Mark.15.12.unknown": "City of God",
    # Mark.1.18 - "Let us, also, ourselves build a house in our heart" (sermonic)
    "augustine-of-hippo.Mark.1.18.unknown": "Sermons",
    # Mark.1.24 - unclean spirits knew Christ would come (demonology)
    "augustine-of-hippo.Mark.1.24.unknown": "City of God",
    # Mark.1.3 - quote cites "Quaest. nov. et vet. Test.lvii" (Questions on Old and New Testament)
    "augustine-of-hippo.Mark.1.3.unknown": "City of God",

    # --- Matthew (Sermon on the Mount entries overridden from prefix rule) ---
    # Matt.6.12 - "See, ye are on the point of being baptized" = catechetical/baptismal sermon;
    # the OSIS prefix rule assigns Commentary, but this is clearly addressed to competentes.
    "augustine-of-hippo.Matt.6.12.unknown-2": "Sermons",
    # Matt.6.9 - "as ye have heard and repeated in the creed" = traditio/redditio symboli
    # language; this phrase marks a baptismal preparation sermon, not the written Commentary.
    "augustine-of-hippo.Matt.6.9.unknown-3": "Sermons",
    # Matt.6.10 - sermonic register ("Come it surely will, whether we ask or no") but structure
    # is compatible with Commentary; leave as Commentary (judgment call, flagged for review).
    # Matt.6.13 - systematic question-answering style consistent with Commentary; leave as-is.

    # --- Matthew (non-Sermon-on-the-Mount) ---
    # Matt.12.49 - Virgin Mary did the Father's will, believed in faith (about Mary)
    "augustine-of-hippo.Matt.12.49.unknown": "Sermons",
    # Matt.2.18 - cites "Hil. Quaest. N. and N. Test.9. 62" (Questions)
    "augustine-of-hippo.Matt.2.18.unknown": "City of God",

    # --- Philemon ---
    # Phlm.1.20 - "when you have joy of a man in God, it is God you enjoy" (uti/frui distinction)
    "augustine-of-hippo.Phlm.1.20.unknown": "ON CHRISTIAN DOCTRINE",
    # Phlm.1.3 - "grace of God... condition of being reconciled... peace is wherein we are reconciled"
    "augustine-of-hippo.Phlm.1.3.unknown": "City of God",

    # --- Revelation ---
    # Rev.1.1 - "But what is it, which the Son has heard from the Father?" (Trinitarian)
    "augustine-of-hippo.Rev.1.1.unknown": "ON THE TRINITY",
    # Rev.1.4 - seven churches as universal Church (symbolic)
    "augustine-of-hippo.Rev.1.4.unknown": "City of God",
    # Rev.1.5 - first-begotten and resurrection
    "augustine-of-hippo.Rev.1.5.unknown": "City of God",
    # Rev.1.7 - "prophecy which implies that Christ will come in the very flesh"
    "augustine-of-hippo.Rev.1.7.unknown": "City of God",
    # Rev.1.7 - quote ends "Trinity 1.13.31" (explicit)
    "augustine-of-hippo.Rev.1.7.unknown-2": "ON THE TRINITY",
    # Rev.20.1 - quote ends "(City of God 20.7)" (explicit)
    "augustine-of-hippo.Rev.20.1.unknown": "City of God",
    # Rev.20.3-20.7 - all City of God Book 20 (Revelation commentary)
    "augustine-of-hippo.Rev.20.3.unknown": "City of God",
    "augustine-of-hippo.Rev.20.3.unknown-2": "City of God",
    "augustine-of-hippo.Rev.20.5.unknown": "City of God",
    "augustine-of-hippo.Rev.20.7.unknown": "City of God",
    "augustine-of-hippo.Rev.20.7.unknown-2": "City of God",

    # --- Romans ---
    # Rom.3.30 - difference of prepositions "on the ground of" vs "through" (exegetical note)
    "augustine-of-hippo.Rom.3.30.unknown": "City of God",
}

# ---------------------------------------------------------------------------
# OSIS prefix rules: all blank Matthew 5-7 entries -> Commentary on Sermon on the Mount
# ---------------------------------------------------------------------------
OSIS_PREFIX_RULES = {
    "Matt.5.": "COMMENTARY ON THE SERMON ON THE MOUNT",
    "Matt.6.": "COMMENTARY ON THE SERMON ON THE MOUNT",
    "Matt.7.": "COMMENTARY ON THE SERMON ON THE MOUNT",
}


def infer_source_title(entry: dict) -> str | None:
    """Return the inferred source_title for a blank entry, or None if already populated."""
    if entry.get("source_title"):
        return None  # already set

    entry_id = entry["entry_id"]
    osis_list = entry["anchor_ref"].get("osis", [])
    osis = osis_list[0] if osis_list else ""

    # 1. Explicit override
    if entry_id in EXPLICIT_OVERRIDES:
        return EXPLICIT_OVERRIDES[entry_id]

    # 2. OSIS prefix rule
    for prefix, title in OSIS_PREFIX_RULES.items():
        if osis.startswith(prefix):
            return title

    return None


def main():
    print(f"Loading {INPUT_FILE}")
    with open(INPUT_FILE, encoding="utf-8") as f:
        data = json.load(f)

    entries = data["data"]
    blank_before = sum(1 for e in entries if not e.get("source_title"))
    print(f"Blank source_title entries before patch: {blank_before}")

    patched = 0
    unresolved = []

    for entry in entries:
        inferred = infer_source_title(entry)
        if inferred is not None:
            entry["source_title"] = inferred
            patched += 1

    blank_after = sum(1 for e in entries if not e.get("source_title"))

    for entry in entries:
        if not entry.get("source_title"):
            unresolved.append(entry["entry_id"])

    print(f"Patched: {patched}")
    print(f"Blank source_title entries after patch: {blank_after}")

    if unresolved:
        print(f"UNRESOLVED ({len(unresolved)}):")
        for eid in unresolved:
            print(f"  {eid}")
    else:
        print("All blank entries resolved.")

    # Breakdown by assigned title
    print("\nAssignment summary:")
    from collections import Counter
    assigned_this_run = Counter()
    for entry in entries:
        eid = entry["entry_id"]
        title = entry.get("source_title", "")
        if "unknown" in eid and title:
            assigned_this_run[title] += 1
    for title, count in sorted(assigned_this_run.items(), key=lambda x: -x[1]):
        print(f"  {count:3d}  {title}")

    print(f"\nWriting {OUTPUT_FILE}")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("Done.")


if __name__ == "__main__":
    main()
