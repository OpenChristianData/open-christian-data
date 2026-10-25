# Real prose fixture extracts

These fixtures test an offline TEI-to-row contract. They do not establish human
acceptance, rights clearance, or publication. `manifest.json` binds exact retained
sources, selected native units, upstream TEI where used, and all fixture files.
Pipeline identity strings beginning `fixture-` are explicitly test context;
retained source IDs and titles identify the real works without inventing new
canonical library identities.

- Augustine: two complete native chapters from City of God, Book I. The existing
  TEI's chapter and paragraph IDs are preserved. The ancestor book heading stays;
  prose and other chapters outside the selection are excluded from this fixture.
  The retained ThML contains the exact two complete chapter elements under a
  serialization-only `sourceExcerpt` wrapper.
- Athanasius: the existing four-paragraph On the Incarnation opening-section
  fixture and its retained ThML, copied without changing bytes.
- Boethius: two complete paragraphs from tractate `iv.ii`, Whether Father, Son,
  and Holy Spirit may be Substantially Predicated of the Divinity. The retained
  source fixture contains the WHOLE tractate: 17 direct paragraphs, no internal
  divisions. Paragraphs 11 and 15 are selected in source order; the other 15 are
  enumerated as outside this sample. `div type=work` describes the source's whole
  tractate, not an invented section. Its source title attribute supplies the head.
  Source `sync` becomes an ID-preserving TEI anchor; full source sync attributes
  remain in the retained excerpt. These selected paragraphs have no unsupported
  source styling or layout attributes to discard.

The source oracle selects the native ThML paragraphs independently of TEI
traversal, compares text and attached notes, and reconciles counts/order.
Round-trip claims concern normalized paragraph text and attached notes; the JSON
is not a replacement for the TEI's complete typography or inline note positions.
The common TEI-004 limitations and follow-up register remain applicable.

The accepted entry point is tested separately using an isolated temporary
Athanasius acceptance/promotion simulation. The real source excerpts above are
not represented as human-approved masters. Legacy acceptance-header spelling
integration remains the existing shared-contract limit.
