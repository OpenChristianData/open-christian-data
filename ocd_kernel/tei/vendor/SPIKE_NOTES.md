# TEI validation under lxml — spike results (2026-07-02)

Measured on the real City of God IR (`ir/augustine/city-of-god.ccel-npnf102.tei.xml`, ~4 MB source),
lxml 6.0.2, Python 3.14, Windows.

| Approach | Schema parse | Per-doc validate | Works? |
|---|---|---|---|
| `lxml.etree.XMLSchema` on `xsd/tei_all.xsd` | 13.7 s | 0.1 s | yes |
| `lxml.etree.RelaxNG` on `relaxng/tei_all.rng` | 14.0 s | 0.1 s | yes |

- Both flavors work; the feared libxml2/tei_all RelaxNG failure did not materialize on 4.11.0.
- Schema parse dominates: cache the compiled schema at module scope; validation itself is cheap.
- Both validators agreed on the same error set (initial teiHeader bugs), so either is fine as the
  gate. The pipeline standardizes on the XSD flavor (marginally faster parse, identical verdicts);
  the RNG stays vendored as the reference flavor TEI itself treats as canonical.
- Any real-suite validation test should be marked `slow` (the 14 s schema parse dwarfs the fast
  suite budget) or share one compiled schema per session.
