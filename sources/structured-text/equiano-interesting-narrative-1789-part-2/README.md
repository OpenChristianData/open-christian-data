# Olaudah Equiano — *Interesting Narrative*, second edition, part 2 (1789)

This folder documents the source-local, nonaccepted reconstruction candidate for part 2 of Olaudah Equiano's *The Interesting Narrative of the Life of Olaudah Equiano: or Gustavus Vassa, the African. Written by Himself*. The exact source identity is Michigan item `004837188.0001.002`, ECCO-TCP `K053415.002`, Gale document `CW3301535045`, image set `0324600502`, the second physical part of the same two-volume second edition printed in London in 1789 (ESTC `T61470`). It is a separate source/candidate unit, not a separate abstract work and not composited with part 1.

## Source and version

- Official TCP repository: https://github.com/Text-Creation-Partnership/ECCO-TCP
- Pinned repository commit: `4a3c025535ead1532d7ce4b80a6cfe8cedb5a1de`
- Pinned XML Git blob: `b855bc03d3eea7476d6392497eb05649643efb44`
- Pinned header Git blob: `59dd473e5f2ad6c375b34d1ce5135e2b5dba1451`
- Official Michigan item: https://name.umdl.umich.edu/004837188.0001.002
- Official Michigan IIIF manifest: https://quod.lib.umich.edu/cgi/t/text/api/manifest/ecco:004837188.0001.002
- Retained XML SHA-256: `f8898fcc3e788196168593f3c6bdd12e3ef9cbcba9328091917073ffa305c5ed`

The live Michigan item route returned HTTP 403 on 2026-08-31. Its response headers are retained with ephemeral values redacted. A Wayback snapshot dated 2025-12-13 is retained as archival identity context only; it is not represented as live evidence. The live official IIIF manifest returned 269 canvases and binds this item identifier. The pinned official TCP XML is the content authority.

## Rights and attribution

The pinned ECCO-TCP repository distributes its keyboarded and encoded texts under CC0 1.0 Universal. The license is bound to Git blob `670154e3538863b2d9891fd5483160fbdfc89164`. TCP and the Michigan item request source credit; this README preserves that request for anyone receiving the candidate folder.

The retained 2008 header also contains older distribution-permission wording. That historical header evidence is preserved rather than silently reconciled with the repository's current CC0 license. Human rights review must resolve the evidence before any public release. Commercial Gale page images were not acquired or redistributed, and no image rights are claimed.

## Faithful representation boundary

The retained source is TCP ETS XML, not TEI P5. `content.tei.xml` applies a deterministic, source-local element mapping. It preserves the complete outer source `<TEXT>` character stream and order; the frontispiece; chapters VII–XII; four embedded grant/order/petition documents; five letters; the chapter-X `MISCELLANEOUS VERSES` poem; 28 line groups; 124 verse lines; 269 page milestones; 36 explicit illegible gaps; six footnotes; 83 quotations; and the ending `THE END.` Embedded source `TEXT/BODY/DIV1` documents and letters become legal TEI `floatingText` structures so they remain at their source positions without flattening. All source page, gap, note, quotation, and emphasis attributes are carried into documented legal TEI attributes.

The source metadata identifies the transcription as keyed from page images and partially proofread for accuracy. This route preserves the retained transcription and explicit gaps; it performs no collation against the 1789 print witness.

This technical candidate is not human textual, identity, edition, rights, editorial, canonical, or publication acceptance. No canonical `data/`, `ir/`, or WorkCatalog state is changed.
