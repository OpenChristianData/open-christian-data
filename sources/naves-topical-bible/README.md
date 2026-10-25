# Nave's Topical Bible retained source note

LIB-009 uses the retained CrossWire SWORD `Nave` module version 3.0 as a
source witness for a nonaccepted TEI candidate. CrossWire distributed the
module as `Nave.zip`; the archive contains exactly the five extracted module
members bound by this packet. The archive is an acquisition container, not a
second textual witness.

- Provider: CrossWire Bible Society, SWORD module repository
- Package URL: https://www.crosswire.org/ftpmirror/pub/sword/packages/rawzip/Nave.zip
- Package SHA-256: `52d9b7cde04c2abb5187ae804bcb97d93c7344a1358539f50ebc178ac0c945f0`
- Module: `Nave`, version 3.0, dated 2021-02-28
- Module driver and markup: zLD, ZIP compression, UTF-8, TEI source fragments
- Module `TextSource`: https://ccel.org/ccel/n/nave/bible.xml
- Module rights statement: `DistributionLicense=Public Domain`
- Primary current claim (`dict.zdt`): `e59669ea3a796a25eaf4dfc5c87127404663e14d2b51419be9660abcb9993007`

The candidate preserves all 5,322 dictionary keys in index order and all
5,322 uniquely addressed payloads. Source `ref/@osisRef` is represented as
TEI P5 `ref/@target` with `type="osisRef"`; source text, displayed reference
text, element order, lists, line breaks, cross-reference targets, and payload
`entryFree/@n` values are otherwise retained. The source-accountability member
records every key-to-payload-to-TEI mapping and every compressed block digest.

The supplied LIB-009 cohort note gave the 1,911-byte `nave.conf` digest as
`0a52fe9e016a8900434118be0cb021deed1dfb02b7d2b829bb0e094ff92049d`,
which is 63 hexadecimal characters. Both the retained file and the matching
member inside `Nave.zip` hash to
`0a52fe9e016a8900434118be0cb021deed1dfb02b7d2b829bb0e094ff92049e9`.
The packet binds the observed archive-confirmed digest and keeps the supplied
claim discrepancy explicit.

Credit CrossWire as the module distributor and CCEL as the module's stated
text source. Historic-work identity, exact edition lineage, rights judgment,
textual/editorial decisions, acceptance, and publication remain human
decisions. Candidate status is nonaccepted; publication is not authorized.
