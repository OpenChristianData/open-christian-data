# Batch 08 Evidence — Reference, Hymn, Sermon, and Miscellaneous Residuals

This file records the bounded evidence wave for batch 08. Counts below are
computed from the named raw witnesses or existing generated outputs. No
family-wide TEI claim is inferred from a proof wave.

## Spurgeon MTP — bounded TEI proof wave

Input is the raw HTML directory `raw/spurgeon_sermons/html`, not the JSON
projection. The directory contains 3,547 numbered sermon files. The proof
selection rule is deterministic:

> lowest-numbered sermon with at least two direct article lists; lowest-numbered sermon with a nested list; and lowest-numbered sermon with no article ol/ul, deduplicated and sorted

That selects sermons 1, 15, and 317. Sermon 1 is the first multi-list case,
317 is the first nested-list case, and 15 is the first plain article control.
The selected raw files are hash-pinned in
`ir/census/spurgeon-mtp.proof-wave.census.json`.

The family census found:

| Raw article feature | Count |
|---|---:|
| Sermon files / article tags | 3,547 / 3,547 |
| Article paragraphs | 178,407 |
| Article blockquotes | 13,597 |
| Article `ol` / `ul` / `li` | 3,766 / 0 / 3,767 |
| Files with article lists | 3,403 |
| Files without article `ol`/`ul` | 144 |
| Nested list elements | 9 |
| `ol[type=a]` / bare `ol` | 3,760 / 6 |

Every raw page also has a site-navigation `ul` outside the sermon article;
that navigation is excluded from the article census. The selected wave has
5 ordered lists, 0 bulleted lists, 5 list items, 1 nested list, 209 paragraphs,
13 blockquotes, 31 line breaks, and 3 scripture-reference spans. All five
selected list carriers are raw `ol[type=a]`; no selected sermon article has a
`ul`.

The TEI artifact `ir/spurgeon/spurgeon-mtp.proof-wave.tei.xml` preserves 3
sermons, 5 ordered lists, 0 bulleted lists, 5 items, 1 nested list, 13 quotes,
31 line breaks, and 3 scripture references. Projection to
`ir/spurgeon/hf/spurgeon-mtp.proof-wave.jsonl` retains the list text, while
`ir/spurgeon/hf/spurgeon-mtp.proof-wave.jsonl.loss.json` records the ledger.

**Status: proof works, 3 of 3,547.** This is a bounded proof wave and does not
establish a family-wide Spurgeon TEI migration.

## Westminster Standards HTML — successor acquisition disposition

The parser route is `build/parsers/westminster_standard_parser.py`, with six
canonical pages defined by `build/scrapers/westminster_standard_org.py`. A
successor retry on 2026-07-16 used the repository user agent
`OpenChristianData/1.0 (research; open-source data project; contact:
openchristiandata@gmail.com)`, ordinary redirects, a 30-second timeout, and
two-to-five-second delays. No access-control workaround was attempted.

The canonical URLs attempted were:

- `https://thewestminsterstandard.org/westminster-shorter-catechism/`
- `https://thewestminsterstandard.org/directory-for-the-publick-worship-of-god/`
- `https://thewestminsterstandard.org/directory-for-family-worship/`
- `https://thewestminsterstandard.org/form-of-presbyterial-church-government/`
- `https://thewestminsterstandard.org/the-solemn-league-and-covenant/`
- `https://thewestminsterstandard.org/the-sum-of-saving-knowledge/`

Reproduce one response and its pin with PowerShell (substitute each URL and
slug above, waiting at least two seconds between requests):

```powershell
$ua = 'OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)'
$url = 'https://thewestminsterstandard.org/directory-for-family-worship/'
$out = 'raw/westminster-standard-org/directory-for-family-worship.html'
Invoke-WebRequest -Uri $url -Headers @{'User-Agent' = $ua} -MaximumRedirection 5 -TimeoutSec 30 -OutFile $out
Get-FileHash -Algorithm SHA256 -LiteralPath $out
```

The parser-level verification loaded each cached page with BeautifulSoup,
called the slug's function from `PARSER_FN_MAP`, removed derived `token_count`
fields from the current JSON for comparison, and required exact unit equality.
The Shorter Catechism check called `extract_wsc_proofs_from_html` and required
exact equality with each question's current `proofs` array.

The host's responses were intermittent. The first successor pass returned 403
for the Shorter Catechism and 200 for the other five pages. The hash-pinning
pass returned 403 for the Directory for Publick Worship and 200 for the other
four. One final retry returned 200 for the Shorter Catechism and 403 again for
the Directory for Publick Worship. Five canonical witnesses were therefore
cached under `raw/westminster-standard-org/` and pinned in their configs:

| Config | Bytes | SHA-256 | Edition-match evidence | Disposition |
|---|---:|---|---|---|
| `westminster-shorter-catechism` | 98,505 | `8ffe7e7ae54c16066cce41456a8260d21e5dc3948568507ffbfc83658d10615a` | 107 questions, 400 references, zero parse errors, and every parsed proof object exactly matches the current output | acquired HTML secondary witness; Creeds.json remains the primary Q&A source |
| `directory-for-family-worship` | 63,341 | `b18780153306e2966aac28f5c677b6c47588dc0eec4123e393dcd4687aba1640` | exact match to all 14 current units and 2,100 words | acquired |
| `form-of-church-government` | 92,499 | `d5b31994e9ce43e7828ff65f3ac758e8974b0396d6ba03f991c785b8d92a3ac4` | exact match to all 19 current units and 5,257 words | acquired |
| `solemn-league-and-covenant` | 66,315 | `824dfd79c68a13d137ad6f7f7575e8af5c856287087c9694a3100f2c45b4cc5d` | exact match to all 7 current units and 1,404 words | acquired |
| `sum-of-saving-knowledge` | 135,684 | `6aa4907f6994d61ce3afeeea9b063cabf667b087185bc1cf7f7fd71fc19fee83` | exact match to all 9 current top-level units and 12,475 words | acquired |
| `directory-for-publick-worship` | - | - | canonical URL returned 403 during both pinning attempts; the HTTPS and HTTP Reformed.org alternatives returned 404, and the Puritannica alternative did not resolve | explicitly deferred and left `unknown` |

The exact alternative-witness probes were:

| Attempted URL | Observed result |
|---|---|
| `https://www.reformed.org/documents/wcf_standards/p369-direct_pub_worship.html` | Redirected to `https://reformed.org/documents/wcf_standards/p369-direct_pub_worship.html`; HTTP 404 |
| `http://www.reformed.org/documents/wcf_standards/p369-direct_pub_worship.html` | Redirected to `http://reformed.org/documents/wcf_standards/p369-direct_pub_worship.html`; HTTP 404 |
| `https://www.puritannica.com/front/demo/wk/StandardsWestminster/DirectoryPublicWorship/0000-0000.html` | DNS failure: `No such host is known` |

They were probed with the same repository user agent, ordinary redirect limit,
30-second timeout, and a three-second delay; the reproducible method was:

```powershell
$ua = 'OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)'
$urls = @(
  'https://www.reformed.org/documents/wcf_standards/p369-direct_pub_worship.html',
  'http://www.reformed.org/documents/wcf_standards/p369-direct_pub_worship.html',
  'https://www.puritannica.com/front/demo/wk/StandardsWestminster/DirectoryPublicWorship/0000-0000.html'
)
foreach ($url in $urls) {
  try {
    $response = Invoke-WebRequest -Uri $url -Headers @{'User-Agent' = $ua} -MaximumRedirection 5 -TimeoutSec 30
    [pscustomobject]@{Url = $url; Status = [int]$response.StatusCode; Final = $response.BaseResponse.RequestMessage.RequestUri.AbsoluteUri}
  } catch {
    [pscustomobject]@{Url = $url; Error = $_.Exception.Message}
  }
  Start-Sleep -Seconds 3
}
```

The new HTML byte hashes differ from the 2026-03-28 pins because the page
shell has changed, but the parser-level exact comparisons demonstrate that the
five accepted textual witnesses are edition-matched. The five configs now
record the current canonical URL, acquisition date, and byte hash. The
Directory for Publick Worship config remains unchanged rather than pretending
that a search-engine rendering or an inaccessible alternative is a local
witness.

The family classification remains `unknown`: one of the six HTML inputs is
still unavailable locally and no complete inline/structural apparatus census
has been run. A future unblock is a polite successful canonical fetch or a
locally acquired edition-matched alternative for the Directory for Publick
Worship, followed by hash pinning, exact parser comparison, and a six-page
apparatus census. This HTML route remains distinct from the `creeds-json`
route, which supplies the Shorter Catechism Q&A text and the Westminster
Confession source.

The candidacy inventory's repeatable checker currently counts 1,811 dataset
outputs, while `docs/TEI_CANDIDACY_INVENTORY.md` preserves the 1,814-output
campaign-integration snapshot. B07 regenerated four existing files in place
and added or removed no dataset output, so it did not cause that three-file
difference. The historical integration text was therefore not overwritten;
the current 1,811 count is reported by
`build/tools/build_tei_candidacy_inventory.py` and the discrepancy remains
unrelated concurrent repository state.

## P3 correction-only evidence

- **`bible-dictionaries-jsonl`** — `build/parsers/bible_dictionaries.py`
  constructs `alt_terms`, `scripture_references`, and `related_terms` as
  empty arrays. The source is already headword-plus-definition JSONL, so this
  is a correction/enrichment audit, not TEI evidence.
- **`schleitheim-confession`** — the cached witness is
  `raw/anabaptists.org/schleitheim-confession-1527.html`, pinned by
  `raw/anabaptists.org/schleitheim-confession-1527.manifest.json` with source
  hash `sha256:5a7f3b112e2bd074c9eb8626fd58d13086870ebb0be52a3036781ce9077f3750`.
  The parser recognizes seven article headers and bounds Article VII at the
  closing imprint “The Seven Articles of Schleitheim / Canton Schaffhausen,
  Switzerland, / February 24, 1527”. Remaining font/bold markup and site
  chrome are presentation/container concerns; no TEI migration is required.

## P4 honest evidence

- **`catholic-encyclopedia-html`** — current JSON correction evidence carries
  86/317 scripture references and 141/317 explicit related links for the
  vol01 audit. A future HTML census may justify inline/link carriers; status
  remains `tei-later` and no migration was attempted.
- **`versified-bible-json`** — the raw and output are flat book/chapter/verse
  text records: 66 books, 1,189 chapters, and 31,102 KJV verses; BSB has
  31,086 non-empty verses and 16 genuinely empty verses. The upstream format
  carries no nested apparatus, so status remains `json-native`.
- **`creeds-json`** — upstream JSON already declares catechism question/answer
  or confession units. Prior work is metadata correction, not TEI recovery;
  this is also the distinct route from the Westminster HTML parser.
- **`helloao-commentary-json`** — the API is already verse-keyed structured
  JSON at the commentary-record grain, so status remains `json-native`.
- **`church-fathers-toml`** — TOML blocks are flat quotations with Bible
  references and attribution, so status remains `json-native`.
- **`hymnary-csv`** — the 34,918-row, eight-column source yields 34,904
  records after 14 empty-text rows are skipped. It is a metadata table with
  no nested textual apparatus, so status remains `do-not-migrate`.
- **`didache-prayer-excerpts`** — the raw source has 16 chapters, 100 verse
  markers, and 10 Wikisource editorial references; the output intentionally
  contains four prayer records with `completeness="partial"`. Status remains
  `do-not-migrate`.
- **`logos-schaff-herzog`** — the source has 44 incomplete auxiliary
  fragments. The current parse records 44 fragments, 37 combined IDs, 100
  paragraphs, 64 Bible links, and 36 article links; it is not a complete
  edition witness. Status remains `do-not-migrate`.
- **`bcp-liturgy`** — 1549/1559/1662 services and 1928 collects already have
  census-gated TEI artifacts. It remains `proven/partial`; publication
  cutover belongs to batch 09, so no remigration was attempted here.

## Successor bugs and out-of-scope follow-up

The Bible-dictionary empty fields and the Westminster HTTP 403 acquisition
blocker are recorded for successor work. Neither was expanded into this
batch's migration scope.
