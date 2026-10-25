# Maclaren PG #8381 constituent pilot (nonaccepted)

The retained text is `raw/gutenberg/sermons/maclaren/pg8381.txt`, SHA-256
`9666a51d24dfcfff7b23d2ddfb2e2fe143a1b742f8951143a9fbde2c67f26841`.
It is the **extracted TXT** bound by the existing
`maclaren-expositions-11-pg8381-acquired` sidecar; an archive is only a package.
The source title identifies *Expositions of Holy Scripture: St. John Chaps. XV
to XXI* (lines 1 and 11), and line 11881 prints `END OF VOL. III.`. These are
observed source labels; no publisher, year, or complete print-edition lineage
is inferred.

`content.tei.xml` is an independently validatable **volume constituent** with
three ordered source regions: electronic front and contents (lines 1–155), 45
exposition divisions (156–11880), and volume ending plus the complete
Gutenberg license (11881–12244). Each physical line has a stable source-line
ID and literal text; blank lines have milestones. Exposition titles are TEI
heads; nonheading uppercase quotations remain body text. Source blank lines
separate TEI paragraphs, while line breaks retain the printed electronic
wrapping. The electronic title and contents remain readable source content,
and the volume ending and license are outside the exposition body.

The source contains title differences which this candidate preserves rather
than silently fixing: contents `THE JOYS OP 'THAT DAY'` at line 94 versus body
`THE JOYS OF 'THAT DAY'` at 4497; contents `'ART THOU A KING?'` at 116 versus
unquoted body `ART THOU A KING?` at 7053; a leading space on `THOMAS AND
JESUS` at 9470; and contents `'IT IS THE LORD'` at 146 versus body `'IT IS THE
LORD!'` at 10651. The uppercase quotation at 7930 and `1-16.` at 7318 are
body text, not exposition headings. The contents reference for Thomas says
John xx. 28 while its body epigraph says JOHN xx. 26; both remain literal.

The independent oracle derives the 45 expected heads in source order from
the contents and body, compares every readable line, checks region and paragraph
ownership, rejects all unaccounted candidate text and tails, and validates the
pinned TEI P5 XSD. It does not import the producer or its hardcoded heading
positions. `validation.json` and `source-accounting.json` bind the checks and
hashes. Seven focused mutations reject a changed heading, wrong exposition
attachment, license-line deletion, invented paragraph text, invented carrier
tail, a paragraph split without a source blank line, and an invented semantic
attribute. A fresh Python process reproduced the candidate bytes exactly.

Generate and verify from the repository root:

```powershell
py -3 -m build.tei.maclaren_pg8381_constituent_v1 --output sources/sermons/maclaren-expositions/pg8381-constituent-v1/content.tei.xml
py -3 -m build.tei.maclaren_pg8381_constituent_oracle_v1 --candidate sources/sermons/maclaren-expositions/pg8381-constituent-v1/content.tei.xml --receipt sources/sermons/maclaren-expositions/pg8381-constituent-v1/validation.json
py -3 -m pytest -p no:cacheprovider tests/test_maclaren_pg8381_constituent_v1.py -v
```

The current `work.json` still declares one fifteen-file cohort edition and
15 acquisitions. This pilot is bound to the existing PG #8381 acquisition,
but the proposed single-acquisition constituent edition has **not** been
installed. Review its identity, source relationship, and whether the 45
expositions need separate work identities before any sidecar transition or
agent acceptance. The older cohort candidate remains nonaccepted. Human
review, print comparison, rights clearance, release selection, and publication
have not been performed.
