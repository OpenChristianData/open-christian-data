# JE vol_02 WCT rebuild stability - adversarial review

## Verdict

PASS. The stability proof is strong enough for the reviewer architecture assumption:
`(edition_page_key, edition_position_ordinal)` remained stable across the r2 rebuild for all
44,626 old tokens.

## Attack lines checked

- Ordinal drift without split/merge: not observed. Every old canonical token id had the same
  canonical token id in r2, and the comparator also required matching text key plus bbox overlap
  before counting it as identical. Corpus totals are old=44,626, new=44,626, identical=44,626.
- Bbox-match false positives: not exercised in production because no token needed a rebind. The
  matcher requires same text plus bbox IoU >= 0.50 for stable IDs, and the unit test
  `test_compare_pages_does_not_rebind_same_text_far_from_bbox` guards the false-positive case.
- Reading-order differences between builds: not observed. Page-level identity rate is 100% across
  all 34 pages; the dry-run rebind/orphan event file is empty.

## Residual risk

The 10 spot checks are programmatic image-bound checks, not human visual adjudications. They verify
that the sampled source images exist and sampled bboxes sit inside image bounds. With zero exceptions,
there were no split/merge cases requiring visual explanation.
