# Source record: Evangelische Gezangen (1806)

This is a nonaccepted technical TEI candidate for the single titled work *Evangelische Gezangen, om nevens het Boek der Psalmen bij den openbaren godsdienst in de Nederlandsche Hervormde Gemeenten gebruikt te worden*, identified by DBNL as the first edition of 1806 (title code `_eva005evan01_01`). Its assigned witness is the retained DBNL TEI.2 XML at `raw/dbnl/evangelische-gezangen-1806/evangelische-gezangen-1806.xml` (574,306 bytes; SHA-256 `d8132943dd20b1053d1d77bda57cab2b69c9dc567e38ea4450baab914925abb9`). The printed title page names Amsterdam and Johannes Allart, and states that the songs were collected and arranged during 1803–1805.

## Retained source and identity

The source-only receipt identifies DBNL record `_eva005evan01`, manifest row L741, the work title, edition, and official record/XML endpoints. The retained source folder contains five direct bundle files: the XML transcription, its original acquisition receipt, a supplemental score-image receipt, the source README, and a member inventory. The source also includes 68 exact DBNL score GIFs under `score-images/`, acquired only after confirming each referenced target was absent locally. The source profile and manifest pin every file by byte length and SHA-256. These GIFs are score resources, not scans of the printed pages.

The TEI.2 title statement, edition statement, title-page matter, provider record identifier, and receipt jointly identify the one 1806 work. This package contains one direct TEI P5 root. It does not package each hymn, tune, or register as a separate work.

## Representation

The candidate maps every source-body element one-to-one to a P5 element and links each mapped element to the retained XML witness. It preserves all source-body character data, tails, element order, 414 page-break markers and labels, 265 poem groups, all tune/song `interp` values, the song register and 26 index tables, 68 figure positions and their 68 retained score-image targets, and the final errata division. The title-page matter and two prefatory divisions are placed in `front`, the source’s 192 hymn divisions in `body`, and the source’s four index/tune/errata divisions in `back`, keeping their original order within each section and preserving the complete concatenated source text stream. The exact TEI.2 header byte slice is retained as escaped source text in the P5 header; the original external DTD identifier is recorded without loading that DTD.

The source header’s three DBNL editorial intervention statements for pp. 151, 352, and 386 are preserved verbatim in the TEI header and source accounting. They are not silently applied as new editorial corrections.

## Limits

The 68 source GIF resources are retained locally, hash-bound, and linked by file URIs to the retained raw source paths. The oracle resolves each URI to the exact retained target and verifies its byte count and SHA-256. The bundle has no scan images of the printed pages. DBNL describes its TEI.2 file as a diplomatic representation but also records the three interventions above. Independent visual comparison to the print witness remains unresolved because no page images are retained.

The receipt records DBNL’s provider label “Auteursrechtvrij.” That is recorded as the provider’s statement only; it is not broader rights clearance. This technical candidate links the exact existing WorkCatalog work, retained form, electronic edition, and acquisition sidecars; the lifecycle state remains acquired. Human acceptance, broader rights clearance, and publication authorization are not asserted.