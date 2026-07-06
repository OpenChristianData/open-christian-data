# Hymnary.org Public Domain Hymns

A collection of **34,904** public-domain hymn texts, sourced directly from
[Hymnary.org](https://hymnary.org) at Calvin University.

## Credit

This dataset was provided by Hymnary.org for inclusion in Open Christian Data.
**If you build something using this dataset, please:**

1. **Link back to [https://hymnary.org](https://hymnary.org)** in your application
   or publication.
2. **Submit your application to Hymnary at
   [https://hymnary.org/contact](https://hymnary.org/contact)** — they love seeing
   what people build with their data.

## Contents

- `collection.json` — single OCD `hymn_collection` file, ~48.6 MB
- Each record represents the **oldest known public-domain hymnal instance** of a
  given hymn text

## Coverage

| Field | Coverage |
|---|---|
| Total entries | 34,904 |
| Has author name | 86% (29,786 / 34,904) |
| Has author birth year | 65% |
| Has hymn-written year | 19% |
| Has hymnal publication year | 100% (less 13 missing) |
| English | 87% (~30,089) |
| Non-English (`mul`) | 13% (~4,815) — German, Norwegian, Danish, Polish, Spanish, Arabic |

## Schema

Validates against
[`schemas/v1/hymn_collection.schema.json`](../../../schemas/v1/hymn_collection.schema.json).

Each entry has:

```json
{
  "entry_id": "abba-lieber-vater-hore",
  "collection_id": "hymnary-pd",
  "title": "Abba, lieber Vater, höre",
  "author": "Schmolck, Benjamin, 1672-1737",
  "author_birth_year": 1672,
  "author_death_year": 1737,
  "year_written": null,
  "stanzas": ["1 Abba, lieber Vater, höre,\\n...", "2 ...", "..."],
  "language": "mul",
  "hymnal_title": "Evang.-Lutherisches Gesangbuch",
  "hymnal_year": 1872,
  "word_count": 261,
  "token_count": 463
}
```

### Notes on the data

- **`stanzas`** — hymn text split on blank lines. Numbered stanzas, refrains, and
  choruses are separate strings within the array.
- **`language`** — `en` if the title and opening text contain no non-ASCII
  letters; `mul` otherwise (covers all non-English content). Typographic
  punctuation like curly quotes is ignored, so English hymns with `heav'n`
  are correctly classified as `en`.
- **`author`** — raw string from Hymnary, may contain multiple authors separated
  by `;`. For multi-author entries, `author_birth_year` and `author_death_year`
  are `null`.
- **`entry_id`** — kebab-case, unique within the collection. When the same title
  appears multiple times (~2,056 such titles, mostly different hymns sharing a
  name), the slug is disambiguated with the first author surname, then the
  hymnal year, then a numeric counter.

## License

- **Hymn texts** — public domain (Hymnary.org provided only PD content)
- **OCD curation and metadata** — CC0-1.0

## Provenance

- Source: Hymnary.org export (`oldest_pd_instances.csv`), 2026-04-22
- Parser: [`build/parsers/hymnary_pd.py`](../../../build/parsers/hymnary_pd.py)
- Tests: [`tests/test_hymnary_pd.py`](../../../tests/test_hymnary_pd.py) (39 tests, TDD)
