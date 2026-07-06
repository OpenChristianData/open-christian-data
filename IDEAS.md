# Ideas — Open Christian Data

Forward-looking notes, deferred ideas, and external projects to revisit later.

## Future cross-reference enrichment — Theographic Bible Metadata

**Repo:** https://github.com/robertrouse/theographic-bible-metadata
**License:** CC BY-SA 4.0 (compatible with OCD's open-data goals — requires attribution + share-alike)
**Maintainer:** Robert Rouse (robert@viz.bible / @bibleviz). Actively maintained, last commit April 2026. Uses Claude Code.

A knowledge graph of the Bible linking people, places, periods, and passages.

### Data available (JSON + CSV)

| File | Size | Content |
|------|------|---------|
| verses.json | 37 MB | All Bible verses with metadata |
| people.json | 5 MB | Biblical people with birth/death years (ISO 8601), relationships |
| places.json | 2.4 MB | Biblical places with geo data |
| events.json | 1.7 MB | Biblical events linked to passages |
| chapters.json | 1.8 MB | Chapter-level metadata |
| books.json | 1.2 MB | Book-level metadata |
| easton.json | 6.2 MB | Easton's Bible Dictionary entries (PD, already structured) |
| peopleGroups.json | 44 KB | Tribal/ethnic groupings |
| WordIndex.csv | 77 MB | Full word index across all verses |

Also includes `neo4j/` for graph DB import, `geo/` for geographic data, `api/` for GraphQL schema. GraphQL API live at viz.bible — could query directly rather than hosting data.

### When to revisit

After OCD literature coverage is comprehensive. The people/places/events graph would add the most value as a cross-reference layer on top of scripture content — e.g. "people mentioned in this passage", "events at this location". Easton's Dictionary entries could integrate directly. Collaboration with the maintainer may be worth exploring.
