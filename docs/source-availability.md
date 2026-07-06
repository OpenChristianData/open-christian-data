# Source availability — known-not-on-CCEL index

A running list of works that are NOT available on CCEL and require alternative sources (Internet Archive, Google Books, manual transcription). Confirmed by URL probing or absence from CCEL author pages.

| Work | Author | Year | CCEL status | Alternative |
|---|---|---|---|---|
| The Mystery of Providence | John Flavel | 1678 | Confirmed absent 2026-05-06 — all 4 plausible URL patterns 404, not on CCEL Flavel author page | Internet Archive (search "Flavel Mystery of Providence" — verified public-domain edition) |

## How to use

Before opening a new acquisition session for any work, check this file. If the work is listed here as not on CCEL, skip the CCEL discovery step and go straight to the alternative source.

## When to extend

Add a row when a CCEL acquisition attempt confirms absence (all plausible URL patterns 404 + author page does not list the work). Include the URL patterns tried so a future investigator does not repeat the probe.

## Flavel — Mystery of Providence — acquisition notes

All four plausible CCEL URL patterns return 404 with no redirect:
- `https://ccel.org/ccel/flavel/providence.xml`
- `https://ccel.org/ccel/flavel/providence/providence.xml`
- `https://ccel.org/ccel/flavel/mystery.xml`
- `https://ccel.org/ccel/flavel/mystery/mystery.xml`

CCEL's Flavel author page does not list the work. Acquire from Internet Archive. Likely extension target: `build/parsers/gutenberg_systematics.py` (used for Hooker and Luther IA acquisitions) or a new IA-specific parser if the structure doesn't fit.
