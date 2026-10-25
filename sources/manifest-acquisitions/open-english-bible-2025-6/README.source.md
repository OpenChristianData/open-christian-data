# L605: Open English Bible 2025.6 source description

This directory binds a retained-source reconstruction candidate for the exact
Open English Bible 2025.6 USFM release recorded by acquisition row L605. The
retained US and Cth packages remain separate textual witnesses under one TEI
root. Their wording and differences are preserved independently; the candidate
does not select, merge, or normalize one variant into the other.

The declared source scope is Genesis, all 27 New Testament books, Psalms, and
selected Old Testament books (Joshua, Ruth, Esther, Hosea, Joel, Amos, Obadiah,
Jonah, Micah, Nahum, Habakkuk, Zephaniah, Haggai, Zechariah, and Malachi). This
is a partial biblical corpus, not a complete Bible. Each retained package also
contains its USFM front page and AppleDouble metadata members; the archive and
extraction accounting covers the full member envelope.

Source package and extraction locations are bound by
`reconstruction-source-manifest.json` through the configured `raw/` route.
`profile.json` records archive order, every archive entry, extracted-file
linkage, physical USFM lines, controls, chapters, verses, and known source
features. `policy.json` defines their TEI representation and independent check.

The retained USFM has one unmatched `\wj` start in each variant at
`42-Luke.usfm` line 815. The control is retained as an explicit TEI marker and
reported in the unresolved ledger; no source repair is inferred. No human
acceptance, rights decision, or publication authorization is recorded by this
technical candidate.
