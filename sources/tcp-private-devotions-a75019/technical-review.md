# TCP A75019 technical review boundary

The source is the single retained 178,256-byte EEBO-TCP A75019 TEI P5 XML item
(SHA-256 `800bae82b44a6c45ef3d49af85e1e0dd046ace2741055a078acc9be808d69aec`).
Its acquisition receipt and one-member inventory are bound as support evidence.
The source metadata identifies the 1660 London printing and attributes authorship
to Richard Allestree through a Wing note; that qualification is preserved. The
text's CC0 statement does not convey rights to the externally linked images.

The v2 candidate at
`candidate-reviews/manifest-acquisition-20260923/tcp-private-devotions-a75019-v2`
contains the exact original XML bytes, so all 1,583 source elements and their
attributes, text, tails, header, front/body, 115 divisions, 96 page milestones,
420 glyph carriers, nine gaps, and five notes are conserved. There are zero
source XML IDs and zero internal fragment refs; the independent oracle requires
the candidate to retain those zero counts and rejects an introduced link or ID.
The 96 `pb/@facs` references remain pointers; no image bytes are packaged.

The producer reads the bound member and emits it unchanged after a source
census check. The independent oracle rereads the retained bytes, compares
the actual candidate bytes, checks source title/qualified authorship/date/CC0
metadata and ordered division/heading/page relations against the profile,
checks unique source and candidate IDs and fragment closure, and validates
the candidate against the vendored P5 XSD. Both use lxml to parse the same
source; byte equality independently corroborates conservation against any
shared parsing or traversal assumption. Profile expectations were inventoried
from the source before candidate generation. No print-facsimile comparison
was performed.

The v2 package manifest is
`233de4d2dad5a67d099ff9b70a83545abdfc9b0e838e9d465164e81bffc89a09`;
independent validation is pass with report SHA-256
`ee2c77b603360fc47404db4abd3b6008f0f91658f7ceb459f1da57b664f40bff`.
All seven candidate files reproduce byte-identically in a clean second
process. The focused mutation suite passed 11/11 (exit 0) after routing
pytest's temporary directory outside an inaccessible F: scratch root. The
first run's 3-pass/8-setup-error result was environmental and is superseded
by the successful retry.

Selected review patterns: RP-03 (one of four L788 works), RP-04 and RP-06
(exact whole-TEI conservation and independent oracle), RP-11 (worktree raw
route), RP-12 (print and image limits), RP-14 (TCP rights/attribution header),
and RP-15 (bound P5). Technical review readiness is not CVW visual review,
print collation, broader rights clearance, human acceptance, or publication.
The earlier v1 candidate is provisional and superseded by v2.
