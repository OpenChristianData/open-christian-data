# Open Christian Data -- Schema Red Team Brief

**Purpose:** Review these 13 schema designs against real data samples. Propose your own schema designs based on the data. Find structural flaws, missing fields, wrong assumptions, unnecessary complexity, and better alternatives. Be adversarial.

**Context:** This project processes public domain Christian literature into structured, machine-readable datasets (JSON, SQLite, Parquet) for developers and AI training. All data is CC0/public domain. Published on GitHub and HuggingFace.

---

## Shared Design Principles

1. One schema per content type (verse-keyed commentary != date-keyed devotional)
2. Shared metadata envelope at file level (author, license, provenance, tradition)
3. Per-record provenance: `source_license`, `source_url`, `translation_year` on every record
4. OSIS verse references everywhere (e.g., `Gen.1.1`, `Rom.9.1-Rom.9.5`)
5. BSB (Berean Standard Bible, CC0) as verse text source

---

## Schema 1: `bible_text`

**Proposed schema:**
```json
{
  "book": "Genesis", "book_osis": "Gen", "book_number": 1,
  "chapter": 1, "verse": 1,
  "text": "In the beginning God created the heavens and the earth.",
  "source_license": "cc0-1.0",
  "source_url": "https://github.com/scrollmapper/bible_databases",
  "translation_year": 2023
}
```

**Real data (BSB.json):**
```json
{
  "translation": "BSB: Berean Standard Bible",
  "book_sample": {
    "name": "Genesis",
    "chapter": 1,
    "verses": [
      {"verse": 1, "text": " In the beginning God created the heavens and the earth. "},
      {"verse": 2, "text": "Now the earth was formless and void, and darkness was over the surface of the deep. And the Spirit of God was hovering over the surface of the waters. "},
      {"verse": 3, "text": " And God said, \"Let there be light,\" and there was light. "}
    ]
  }
}
```

---

## Schema 2: `commentary` (EXISTING -- in production)

**Proposed schema:**
```json
{
  "entry_id": "matthew-henry-complete.Ezek.1.1-3",
  "book": "Ezekiel", "book_osis": "Ezek", "book_number": 26,
  "chapter": 1, "verse_range": "1-3",
  "verse_range_osis": "Ezek.1.1-Ezek.1.3",
  "verse_text": "In the thirtieth year...",
  "commentary_text": "The book of the prophet Ezekiel...",
  "summary": null, "summary_review_status": "withheld",
  "summary_source_span": null, "summary_reviewer": null,
  "key_quote": null, "key_quote_source_span": null,
  "key_quote_selection_criteria": null,
  "cross_references": ["Jer.29.1", "Dan.1.1-Dan.1.6"],
  "word_count": 1523
}
```

**Real data (existing ezekiel.json, 132 entries, 232k words):**
```json
{
  "meta": {
    "id": "matthew-henry-complete",
    "title": "Matthew Henry's Complete Commentary on the Whole Bible",
    "author": "Matthew Henry",
    "author_birth_year": 1662,
    "author_death_year": 1714,
    "contributors": ["Matthew Henry (died 1714, completed Genesis through Acts)", "13 nonconformist ministers (completed Romans through Revelation, published 1714)"],
    "original_publication_year": 1706,
    "language": "en",
    "tradition": ["reformed", "puritan", "nonconformist"],
    "tradition_notes": "Henry was a Nonconformist minister shaped by Puritan covenant theology.",
    "license": "cc0-1.0",
    "schema_type": "commentary",
    "schema_version": "1.0.0",
    "verse_text_source": "BSB",
    "verse_reference_standard": "OSIS",
    "completeness": "partial",
    "provenance": {
      "source_url": "https://bible.helloao.org/api/c/matthew-henry/EZK",
      "source_format": "JSON",
      "source_edition": "HelloAO Bible API - Matthew Henry Bible Commentary (Public Domain Mark 1.0)",
      "download_date": "2026-03-26",
      "source_hash": "sha256:106a8d06f3b1676a676552b7307ab07b8d0b69a742d3b0a6e281cb5b4655d3dc",
      "processing_method": "automated",
      "processing_script_version": "build/parsers/matthew_henry_helloao.py@v1.0.0",
      "processing_date": "2026-03-26",
      "notes": "Sourced from HelloAO Bible API."
    },
    "summary_metadata": null
  },
  "first_entry": {
    "entry_id": "matthew-henry-complete.Ezek.1.1-3",
    "book": "Ezekiel",
    "book_osis": "Ezek",
    "book_number": 26,
    "chapter": 1,
    "verse_range": "1-3",
    "verse_range_osis": "Ezek.1.1-Ezek.1.3",
    "verse_text": "In the thirtieth year, on the fifth day of the fourth month, while I was among the exiles by the River Kebar...",
    "commentary_text": "The circumstances of the vision which Ezekiel saw, and in which he received his commission and instructions...",
    "summary": null,
    "summary_review_status": "withheld",
    "summary_source_span": null,
    "summary_reviewer": null,
    "key_quote": null,
    "key_quote_source_span": null,
    "key_quote_selection_criteria": null,
    "cross_references": [],
    "word_count": 2042
  }
}
```

---

## Schema 3: `confession`

**Proposed schema:**
```json
{
  "document_id": "westminster-confession",
  "chapter": 1, "chapter_title": "Of the Holy Scriptures",
  "sections": [
    {
      "section": 1,
      "content": "Although the light of nature...",
      "content_with_proofs": "Although the light of nature...[1]",
      "proofs": [{"id": 1, "references": ["Ps.19.1-Ps.19.3", "Rom.1.19-Rom.1.20"]}]
    }
  ],
  "source_license": "unlicense",
  "source_url": "https://github.com/NonlinearFruit/Creeds.json",
  "translation_year": null
}
```

**Real data -- TWO incompatible structures in Creeds.json:**

Structure A -- WCF (Confession format, 33 chapters with nested sections and proofs):
```json
{
  "Metadata": {
    "Title": "Westminster Confession of Faith",
    "Year": "1647",
    "Authors": ["Westminster Assembly"],
    "Location": "London, England",
    "OriginalLanguage": "English",
    "SourceAttribution": "Public Domain",
    "CreedFormat": "Confession"
  },
  "Data": [{
    "Chapter": "1",
    "Title": "Of the Holy Scriptures",
    "Sections": [{
      "Section": "1",
      "Content": "Although the light of nature, and the works of creation and providence, do so far manifest the goodness, wisdom, and power of God, as to leave men inexcusable; yet are they not sufficient to give that knowledge of God, and of his will, which is necessary unto salvation...",
      "ContentWithProofs": "Although the light of nature...[1] yet are they not sufficient...[2]",
      "Proofs": [
        {"Id": 1, "References": ["Ps.19.1-Ps.19.3", "Rom.1.19-Rom.1.20", "Rom.1.32", "Rom.2.1", "Rom.2.14-Rom.2.15"]},
        {"Id": 2, "References": ["1Cor.1.21", "1Cor.2.13-1Cor.2.14"]}
      ]
    }]
  }]
}
```

Structure B -- Belgic Confession (Canon format, 37 flat articles, no sections, no proofs):
```json
{
  "Metadata": {
    "Title": "Belgic Confession",
    "Year": "1561",
    "Authors": ["Guido de Bres"],
    "Location": "Low Countries",
    "OriginalLanguage": "French",
    "SourceAttribution": "Public Domain",
    "CreedFormat": "Canon"
  },
  "Data": [{
    "Article": "1",
    "Title": "The Only God",
    "Content": "We all believe in our hearts and confess with our mouths that there is a single and simple spiritual being, whom we call God- eternal, incomprehensible, invisible, unchangeable, infinite, almighty; completely wise, just, and good, and the overflowing source of all good."
  }]
}
```

**All Creeds.json format types and their structures:**
- `Confession` (WCF, LBC 1689, Dort, 2nd Helvetic): Chapter > Sections > Proofs
- `Canon` (Belgic, Scots, Council of Orange, Basel, Berne, Zwingli's 67 Articles, etc.): Article > Content (flat)
- `Creed` (Apostles', Nicene, Athanasian, Chalcedonian): Short statement, single Content block
- `Catechism`: See Schema 4
- `HenrysCatechism`: See Schema 4

---

## Schema 4: `catechism_qa`

**Proposed schema:**
```json
{
  "document_id": "westminster-shorter-catechism",
  "question_number": 1,
  "lords_day": null, "part": null,
  "question": "What is the chief end of man?",
  "answer": "Man's chief end is to glorify God, and to enjoy him for ever.",
  "answer_with_proofs": null,
  "proofs": [],
  "source_license": "unlicense",
  "source_url": "https://github.com/NonlinearFruit/Creeds.json",
  "translation_year": null
}
```

**Real data -- THREE different structures in Creeds.json:**

WSC (107 entries, NO proofs):
```json
{"Number": 1, "Question": "What is the chief end of man?", "Answer": "Man's chief end is to glorify God, and to enjoy him for ever."}
```

Heidelberg (129 entries, WITH proofs, but NO Lord's Day grouping in data):
```json
{
  "Number": 1,
  "Question": "What is your only comfort in life and death?",
  "Answer": "That I am not my own, but belong with body and soul...",
  "AnswerWithProofs": "That I am not my own,[1] but belong with body and soul...[2]",
  "Proofs": [
    {"Id": 1, "References": ["1Cor.6.19,1Cor.6.2"]},
    {"Id": 2, "References": ["Rom.14.7-Rom.14.9"]}
  ]
}
```

HenrysCatechism (107 entries, with NESTED SUB-QUESTIONS):
```json
{
  "Number": "1",
  "Question": "What is the chief end of man?",
  "Answer": "Man's chief end is to glorify God, and enjoy him forever.",
  "SubQuestions": [
    {"Number": "1a", "Question": "Is man a reasonable creature?", "Answer": "Yes: For there is a spirit in man, and the inspiration of the Almighty giveth him understanding, Job 32:8."},
    {"Number": "1b", "Question": "Has he greater capacities than the brutes?", "Answer": "Yes: God teacheth us more than the beasts of the earth, and maketh us wiser than the fowls of heaven, Job 35:11."}
  ]
}
```

---

## Schema 5: `catechism_prose`

**Proposed schema:**
```json
{
  "document_id": "luthers-large-catechism",
  "part": "The Ten Commandments",
  "chapter": 1, "chapter_title": "The First Commandment",
  "paragraphs": [
    {"paragraph_number": 1, "text": "A god is that to which we look for all good..."}
  ],
  "scripture_references": ["Exod.20.3"],
  "word_count": 2340,
  "source_license": "public_domain",
  "source_url": "https://www.gutenberg.org/ebooks/1722",
  "translation_year": 1921
}
```

**Real data (PG #1722, Luther's Large Catechism, 4,886 lines):**

5 major parts: Ten Commandments, Creed, Lord's Prayer, Baptism, Lord's Supper. Each commandment/article is continuous theological prose -- NOT Q&A. Structure within each section: biblical text quoted, then extended explanation, practical application, warnings.

---

## Schema 6: `church_fathers`

**Proposed schema:**
```json
{
  "entry_id": "augustine.Gen.1.1.on-literal-interpretation-3-10",
  "author": "Augustine of Hippo",
  "book_osis": "Gen", "chapter": 1, "verse": 1,
  "quote": "Scripture called heaven and earth that formless matter...",
  "source_title": "ON THE LITERAL INTERPRETATION OF GENESIS 3.10",
  "source_url": "",
  "append_to_author_name": null,
  "word_count": 42,
  "source_license": "public_domain",
  "translation_year": null
}
```

**Real data (Commentaries-Database, 58,675 TOML files, 335+ authors):**

Augustine of Hippo / 1 Chronicles 11_17.toml:
```toml
[[commentary]]
quote='''
The observance of Lent becomes not the curbing of old passions but an opportunity for new pleasures. Take measures in advance with as much diligence as possible to prevent these attitudes from creeping on you. Let frugality be joined to fasting...
'''
source_title="SERMON 207.2"
```

John Chrysostom / 1 Corinthians 10_1-5.toml:
```toml
[[commentary]]
quote='''
"That our fathers," saith he, "were all under the cloud, and all passed through the sea; and were all baptized unto Moses in the cloud and in the sea; and did all eat the same spiritual meat..."
'''
source_title='Homily on 1 Corinthians 23'
```

Ambrose of Milan / 1 Corinthians 10_17.toml:
```toml
[[commentary]]
quote='''
Wherefore every soul which receives that bread which comes down from heaven is the house of bread, that is, the Bread of Christ, being nourished and supported and having its heart strengthened by that heavenly bread which dwells within it...
'''
source_title="Letter 63"
```

Notes: Author = directory name. Verse = filename. Some files have multiple `[[commentary]]` entries. Directory structure mixes Bible book dirs (cross-refs) and author dirs (quotes).

---

## Schema 7: `theological_work`

**Proposed schema:**
```json
{
  "work_id": "calvins-institutes",
  "volume": 1, "part": "Book I",
  "chapter": 1, "chapter_title": "The Connection Between The Knowledge Of God And The Knowledge Of Ourselves",
  "content": "Full chapter text...",
  "summary": null, "summary_review_status": "withheld",
  "key_quote": null,
  "scripture_references": ["2Tim.3.16"],
  "word_count": 5200,
  "source_license": "public_domain",
  "source_url": "https://www.gutenberg.org/ebooks/45001",
  "translation_year": 1845
}
```

**Real data (PG #45001, Calvin's Institutes, 31,174 lines):**

Structure: 2 volumes, 4 Books, 18+ chapters per book.

Table of contents:
```
Book I. On The Knowledge Of God The Creator.
   Argument.
   Chapter I. The Connection Between The Knowledge Of God And The Knowledge Of Ourselves.
   Chapter II. The Nature And Tendency Of The Knowledge Of God.
   ...
   Chapter XVIII. God Uses The Agency Of The Impious...
Book II. On The Knowledge Of God The Redeemer In Christ...
   Chapter I. The Fall And Defection Of Adam...
   ...
   Chapter VIII. An Exposition Of The Moral Law
      The First Commandment.
      The Second Commandment.
      ...
Book III. On The Manner Of Receiving The Grace Of Christ...
Book IV. On The External Means Or Helps By Which God...
```

Note: Chapter VIII has sub-divisions (individual commandments). Translator is John Allen (not in schema). Translation year 1813 (not 1845 as initially assumed).

---

## Schema 8: `sermon`

**Proposed schema:**
```json
{
  "collection_id": "spurgeons-sermons",
  "sermon_number": 1,
  "title": "The Immutability Of God",
  "date_preached": null, "location": null,
  "scripture_ref_osis": "Mal.3.6",
  "verse_text": "For I am the LORD, I do not change...",
  "content": "Full sermon text...",
  "summary": null, "summary_review_status": "withheld",
  "key_quote": null,
  "word_count": 4250,
  "series": null,
  "tags": ["attributes of God", "immutability"],
  "source_license": "public_domain",
  "source_url": "https://thekingdomcollective.com/spurgeon/sermon/1/",
  "translation_year": null
}
```

**Real data (Spurgeon sermon #1 from The Kingdom Collective):**
- HTML page provides: title ("The Immutability Of God"), scripture reference (Malachi 3:6 with verse text), full sermon body
- **Missing from source:** date preached, location, series info
- Collection is 3,000+ sermons by Spurgeon

**Wesley sermons (CCEL):** 141 sermons across 5 series. TOC shows title only. No scripture ref in TOC. First two series organized by doctrinal topic.

---

## Schema 9: `devotional`

**Proposed schema:**
```json
{
  "collection_id": "spurgeons-morning-evening",
  "date": "01-01", "period": "morning",
  "title": "January 1 -- Morning",
  "verse_ref_osis": "Gen.1.1",
  "verse_text": "In the beginning...",
  "content": "Devotional text...",
  "key_quote": null,
  "word_count": 412,
  "source_license": "public_domain",
  "source_url": "...",
  "translation_year": null
}
```

**Real data: NOT YET AVAILABLE.** SWORD binary module needs `diatheke` CLI extraction. Known structure: 730 entries (365 days x 2 readings), AM/PM split.

---

## Schema 10: `prayer` (standalone prayers only)

**Proposed schema:**
```json
{
  "collection_id": "didache-prayers",
  "title": "Eucharistic Prayer over the Cup",
  "author": null,
  "year": null,
  "occasion": "Eucharist",
  "content": "We thank thee, our Father, for the holy vine of David Thy servant, which Thou madest known to us through Jesus Thy Servant; to Thee be the glory for ever.",
  "scripture_references": [],
  "tags": ["eucharist", "thanksgiving"],
  "word_count": 35,
  "source_license": "public_domain",
  "source_url": "https://en.wikisource.org/wiki/Ante-Nicene_Fathers/Volume_VII/...",
  "translation_year": 1886
}
```

**For:** Didache prayers, Puritan prayers from collected works, individual collects, standalone historical prayers. Simple: title, occasion, text, optional scripture refs.

---

## Schema 10b: `liturgical_service` (structured worship orders -- SEPARATE TYPE)

**Proposed schema:** TBD -- needs design. Key structural elements from real data: rubrics, speakers, sequence position, alternatives, canticles, versicles/responses.

**Real data (BCP 1662 Morning Prayer):**

The BCP is NOT a list of individual prayers. It is a structured liturgical ORDER OF SERVICE with rubrics, responses, and sequence:

```
THE ORDER FOR MORNING PRAYER, Daily Throughout the Year.

================================================================================
SENTENCES OF SCRIPTURE
================================================================================

[Rubric: At the beginning of Morning Prayer the Minister shall read with a loud
voice some one or more of these Sentences of the Scriptures that follow.]

WHEN the wicked man turneth away from his wickedness that he hath committed,
and doeth that which is lawful and right, he shall save his soul alive.
  -- Ezek. xviii. 27.

I acknowledge my transgressions, and my sin is ever before me.
  -- Psalm li. 3.

[...8 more scripture sentences...]

================================================================================
EXHORTATION
================================================================================

DEARLY beloved brethren, the Scripture moveth us, in sundry places, to
acknowledge and confess our manifold sins and wickedness...

================================================================================
GENERAL CONFESSION
================================================================================

[Rubric: A general Confession to be said of the whole Congregation after the
Minister, all kneeling.]

ALMIGHTY and most merciful Father; We have erred, and strayed from thy ways
like lost sheep. We have followed too much the devices and desires of our own
hearts. We have offended against thy holy laws. We have left undone those things
which we ought to have done; And we have done those things which we ought not to
have done; And there is no health in us. But thou, O Lord, have mercy upon us,
miserable offenders...

================================================================================
ABSOLUTION
================================================================================

[continues with: Lord's Prayer, Versicles, Venite, Psalms, Lessons, Te Deum,
Benedictus, Creed, More Versicles, Collects, Prayers for King/Clergy...]
```

**Didache prayers (simpler structure):**
```
CHAPTER VIII -- Concerning Fasting and Prayer (the Lord's Prayer)

1. But let not your fasts be with the hypocrites; for they fast on the second
and fifth day of the week; but do ye fast on the fourth day and the Preparation.

2. Neither pray as the hypocrites; but as the Lord commanded in His Gospel,
thus pray:

  Our Father who art in heaven, hallowed be Thy name...

CHAPTER IX -- The Thanksgiving (Eucharist)

2. First, concerning the cup:
  We thank thee, our Father, for the holy vine of David Thy servant...

3. And concerning the broken bread:
  We thank thee, our Father, for the life and knowledge which Thou madest
  known to us through Jesus Thy Servant...
```

---

## Schema 11: `reference_entry`

**Proposed schema:**
```json
{
  "dictionary_id": "eastons-bible-dictionary",
  "term": "Atonement",
  "content": "Full dictionary entry text...",
  "scripture_references": [],
  "related_terms": ["Propitiation", "Expiation"],
  "word_count": 1240,
  "source_license": "public_domain",
  "source_url": "https://huggingface.co/datasets/JWBickel/BibleDictionaries",
  "translation_year": null
}
```

**Real data (JWBickel Easton's Bible Dictionary, JSONL, 3,960 entries):**
```json
{"term": "A", "definitions": ["Alpha, the first letter of the Greek alphabet..."]}
{"term": "Aaron", "definitions": ["The eldest son of Amram and Jochebed...", "When the ransomed tribes fought their first battle...", "Afterwards, when encamped before Sinai...", "On the mount, Moses received instructions...", "When Israel had reached Hazeroth...", "Twenty years after this...", "Aaron was implicated in the sin of his brother...", "The Arabs still show with veneration...", "He was the first anointed priest..."]}
{"term": "Aaronites", "definitions": ["The descendants of Aaron, and therefore priests..."]}
{"term": "Abaddon", "definitions": ["Destruction, the Hebrew name (equivalent to the Greek Apollyon)..."]}
{"term": "Abagtha", "definitions": ["One of the seven eunuchs in Ahasuerus's court (Esther 1:10; 2:21)."]}
```

Notes:
- Schema has `content: string` but real data has `definitions: string[]` (array of paragraphs)
- Scripture references are INLINE in definition text, not structured separately
- Related terms appear as inline cross-refs like `(See [1]MOSES.)`
- Hitchcock's is name etymologies only: `{"term": "Aaron", "definitions": ["a teacher; lofty; mountain of strength"]}`
- **Torrey's is NOT a dictionary** -- it's a topical verse index: `{"term": "Access to God", "definitions": ["Is of God -- Ps 65:4.", "Is by Christ -- Joh 10:7..."]}`. Different schema type.

---

## Schema 12: `topical_reference`

**Proposed schema:**
```json
{
  "dictionary_id": "naves-topical-bible",
  "topic_number": 1, "topic_name": "Aaron",
  "subtopics": [
    {"label": "Lineage of", "references": ["Exod.6.16-Exod.6.20"]}
  ],
  "cross_references": ["Moses", "Priesthood"],
  "source_license": "public_domain",
  "source_url": "...",
  "translation_year": null
}
```

**Real data (Torrey's from JWBickel, partial):**
```json
{"term": "Access to God", "definitions": ["Is of God -- Ps 65:4.", "Is by Christ -- Joh 10:7, 14:6, Eph 2:13, 3:12, Heb 7:19,25, 10:19,20.", "Is by the Holy Spirit -- Eph 2:18."]}
```

Notes: Verse references are inline text, not structured OSIS. No subtopic labels -- each "definition" is a claim + verse ref. Schema assumes structured data that doesn't exist in the source.

---

## Schema 13: `hymn`

**Proposed schema:**
```json
{
  "collection_id": "olney-hymns",
  "title": "Amazing Grace",
  "author": "John Newton",
  "year": 1779,
  "metre": "C.M. (8.6.8.6)",
  "tune": "NEW BRITAIN",
  "scripture_references": ["Eph.2.8-Eph.2.9"],
  "stanzas": [{"number": 1, "text": "Amazing grace! how sweet the sound..."}],
  "source_hymnal": "Olney Hymns",
  "tags": [],
  "word_count": 180,
  "source_license": "public_domain",
  "source_url": "...",
  "translation_year": null
}
```

**Real data (Watts, PG #13341, Hymns and Spiritual Songs, 3 books):**
```
Hymn 1:1.
A new song to the Lamb that was slain.
Rev. 5. 6 8 9 10 12.

1 Behold the glories of the Lamb
Amidst his Father's throne
Prepare new honours for his name,
And songs before unknown.

2 Let elders worship at his feet,
The church adore around,
With vials full of odours sweet,
And harps of sweeter sound.

[...6 more stanzas...]


Hymn 1:2.
The deity and humanity of Christ, John 1. 1-3 14.
Col. 9. 16. Eph. 3, 9 10.

1 Ere the blue heavens were stretch'd abroad,
From everlasting was the Word;
With God he was; the Word was God,
And must divinely be ador'd.

[...5 more stanzas...]


Hymn 1:3.
The nativity of Christ, Luke 1. 30 &c. Luke 2, 10 &c.

1 Behold, the grace appears,
The promise is fulfill'd;
Mary the wondrous virgin bears,
And Jesus is the child.

[...8 more stanzas...]
```

Source provides: hymn number (within book), title/description, scripture reference (non-OSIS format), numbered stanzas.
Source does NOT provide: metre, tune name, author per hymn (Watts is collection-level), year per hymn, tags.

---

## Questions for the Red Team

1. Are there schema types that should be merged? (e.g., `catechism_prose` is structurally similar to `theological_work`)
2. Are there schema types that should be split? (e.g., `confession` needs to handle flat articles AND nested sections)
3. Is per-record provenance (`source_license`, `source_url`, `translation_year`) the right granularity, or should it be per-file only?
4. Should the `prayer` schema model individual prayers or liturgical services?
5. Should `reference_entry.content` be a string or array of strings?
6. Are there unnecessary fields that will be null for most records?
7. Is the OSIS reference format the right choice, or would something simpler work?
8. Should schemas be designed for the data we HAVE, or for ideal data we MIGHT get?
9. Look at each proposed schema alongside the real data. Where does the schema not fit the data? Where is the schema over-engineered for data that's simpler than assumed?
10. Propose your own schema design for each type based on what the real data actually looks like.
