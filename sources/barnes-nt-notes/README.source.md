# Barnes Notes on the New Testament — retained source route

The retained CrossWire `raw/sword_modules/Barnes.zip` (SHA-256
`9e8edc0333875c214124371b3862df118ad3a76ade7753cb2faeed3484615baf`)
is the acquisition package, not the textual source. The coordinated extracted
SWORD inputs `nt.czv` (verse index), `nt.czz` (compressed data), and `nt.czs`
(block index) are the textual source members; each is hash-bound in the source
manifest. The extracted `barnes.conf` describes the module and is not a
textual source member. The route traverses every chapter-block index slot in
order. It does not use generated JSON as source authority or fetch another
witness.

For valid UTF-8 carriers, the route preserves text order and maps only the
source-evidenced ThML elements: `i` to italic TEI emphasis, `br` to a TEI line
break, `scripRef` to a scripture reference with its literal `passage` in `n`
and optional `version` in `subtype`, and `blockquote` to a block quote. It does
not derive a target or map SWORD slots to book/chapter/verse locations.
Unrecognized tags and unsupported attributes remain visible as escaped source
markup and are listed in the accountability member. Four source block-quote
starts are unclosed within three BZV slots; their TEI quote wrappers end at the
slot boundary and the exact loci are recorded as structural warnings.

The 60 carriers that are not valid UTF-8 and 76 additional carriers containing
XML 1.0-forbidden controls are not repaired, normalized, or replacement-decoded:
their TEI positions contain explicit gaps, while the accountability member
retains the exact bytes as hex and hashes. These 136 gaps prevent a complete
readable transcription until a source-local resolution is available.

The SWORD module's description is not adopted as a claim about print edition,
original textual form, or volumes. Rights review, human acceptance, release,
and publication are not decided by this technical candidate.
