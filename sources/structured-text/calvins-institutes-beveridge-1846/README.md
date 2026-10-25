# Calvin's *Institutes* — Beveridge OLL source route

This source-local route reconstructs John Calvin's *The Institutes of the Christian Religion*, translated by Henry Beveridge, from the exact retained Online Library of Liberty electronic package. OLL cites the expression as Edinburgh: Calvin Translation Society, 1846, two volumes in one. It is a distinct Beveridge-expression candidate and does not replace or relabel the repository's existing John Allen expression.

## Exact retained sources

- OLL title record: <https://oll.libertyfund.org/titles/calvin-the-institutes-of-the-christian-religion>
- Official EPUB: <https://oll-resources.s3.us-east-2.amazonaws.com/oll3/store/titles/535/calvin-the-institutes-of-the-christian-religion.epub>
- Official text-based eBook PDF: <https://oll-resources.s3.us-east-2.amazonaws.com/oll3/store/titles/535/Calvin_0038_EBk_v6.0.pdf>
- Official facsimile PDF: <https://oll-resources.s3.us-east-2.amazonaws.com/oll3/store/titles/535/0038_Bk.pdf>
- Archived title record: <https://web.archive.org/web/20260226203439/https://oll.libertyfund.org/titles/calvin-the-institutes-of-the-christian-religion>

The live title page returned a WAF block to automated retrieval. Following the blocked-page recovery route, acquisition used the title-page archive for metadata and the direct official OLL S3 download URLs for the current bytes. Exact response headers were retained. The two session-cookie values in the Wayback response headers were replaced with an explicit redaction marker; all other header evidence remains unchanged.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| EPUB | 1,594,912 | `4a7bfc603c2e9f460c4b48a12389f3ec9b0ef00f8864416d0fcd87168813d0d1` |
| EPUB `Calvin_0038.html` member | 4,973,706 | `43409edd7da6a1db1478f5c8b3740d3d747b01b5daea47ef1d143a217ada72cb` |
| Text-based eBook PDF | 4,209,367 | `8015510ce3c79ddf086ce3bd5f117c2cc0244410d98f7a87dbc05c9e725d6e75` |
| Facsimile PDF | 104,898,478 | `bfb1cde92d58eadabb068eb7b11ee0bfd13bcb4c5b0a6c8993f4ce5712c1cc4c` |
| Facsimile General Index extraction | 98,865 | `03099add1e81f17f7a834570d48651ed57d3e9c1a5a991581d6adeb934a35fe3` |
| Archived title-page HTML | 24,067 | `6b1c2ae3b73b012ffdce769b97f2297629a500ab18ce4b00cc9176ae63cf1ad8` |

## Edition and rights evidence

The 2026-02-26 archived OLL title page identifies John Calvin, Henry Beveridge as translator, the citation “Edinburgh: Calvin Translation Society, 1846,” “2 vols. in 1,” the eBook and facsimile downloads, and the statement “The text is in the public domain.” The retained EPUB title matter is the later Wm. B. Eerdmans single-volume electronic witness, including the John Murray introduction, its publisher's note, the statement that the Beveridge translation was originally published in two volumes, retained two-volume pagination, and a 2001 reprint notice. The facsimile title page visibly identifies Calvin and Beveridge but does not itself print the 1846 OLL citation. These layers are retained and reported separately rather than silently reconciled.

## Fidelity and facsimile boundary

The EPUB contains one 4,973,706-byte book HTML member with all four books and eighty chapters, four book arguments, 2,822 numbered-section divisions, 3,970 paragraphs, 660 linked note bodies and references, 67 tables, 65 captions, 135 list items, Scripture and Apocrypha tables, Hebrew and Greek tables, the chapter index, author index, one hundred aphorisms, and the terminal William Pringle attribution. All 3,865 internal references resolve. The converter preserves source wording, capitalization, punctuation, IDs, order, language and typographic spans, page milestones, quotations, tables, lists, gaps, and internal links. Its normalized visible-text SHA-256 is identical on the EPUB and TEI sides: `afb4bb26b464247917d9f1e27d9529ec2302b2e14f17ffacfc14b73d292f80b1`.

The EPUB and text-based eBook PDF omit the facsimile's terminal **General Index**, printed pages 691–704 (PDF pages 1298–1311). The facsimile's embedded searchable text was extracted with `pypdf 6.10.0`, retaining one exact text string and SHA-256 per page. The converter encodes those pages in a separate `div` with fourteen `pb`/`surface` boundaries and `cert="low"`; the extracted-text SHA-256 matches the corresponding TEI layer at `62819d2013691517f096272677a56b4b3551aa1a2f7d33dd9fc6ded889dfd0d4`. It is uncorrected OCR/search text, not an exact human transcription. Visual evidence confirms the page sequence through the printed terminal entries **ZEPHYRINUS** and **ZIPPORAH**, while also demonstrating material OCR corruption that still needs human textual review.

## Exclusions and status

Project Gutenberg 45001 and 64392 are John Allen translations and were not used. The incomplete Wikisource layer, CCEL, and Sacred Texts were not used as acquisition or transcription authorities. This is a provisional, source/edition-upgrade TEI candidate only. It does not write canonical data, IR, schemas, kernel, viewer, or WorkCatalog state; import, acceptance, publication, and human rights/editorial decisions were not performed.
