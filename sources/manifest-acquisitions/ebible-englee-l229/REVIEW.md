# L229 Leeser Tanakh technical assessment

**Scope:** current source-bound technical reconstruction and sidecar linkage for the eBible `englee` witness. This is an agent technical assessment. No visual or human review was performed, and it records no acceptance, rights, or publication decision.

## Work boundary and retained source

The retained ZIP is `raw/ebible/englee/englee_usfm.zip` (1,105,058 bytes; SHA-256 `d5db94a37321ba613a2f8ac9b3039064a6560a0e115dc42221195afc9b7053de`). Its `copr.htm` page titles the top-level work “Isaac Leeser Tanakh” and names Isaac Leeser as translator. The archive contains 39 ordered USFM book members, Genesis through Malachi, plus `copr.htm`, `keys.asc`, and `dejavuserif.css`. The three ancillary members are hash-bound support evidence; they are not scripture body text.

The source title and member structure resolve one Tanakh work. The 39 book members are nested in one TEI document; none is treated as a separate work. The complete member set was CRC-checked and extracted, without redownloading, to `raw/ebible/englee/usfm/`. The current source manifest binds every text and support member and the exact archive.

## Candidate and checks

The current nonaccepted candidate is at `D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260923\ebible-englee-l229-current-20260930-v2`. Its package manifest SHA-256 is `740885c1bed2339b6851d3c3909e9ff486be0a8fe47d4627c0ac24b323f3affa`; the TEI SHA-256 is `e2e8e76a1fea103d779fc772903976ab07c2abf0c5c0a26a7ca5fb22c72343a9`. The current independent oracle passed vendored TEI P5 validation and compared all 25,239 source lines against the readable TEI, including member order, book placement, chapter labels, line order, exact line text, and source pointers. It reported zero findings. Accounting covers 39 books, 929 chapters, 23,145 verse markers, all support members, and no intentional text exclusions.

Two resealed mutations were rejected for the intended reasons: removing a source-line carrier failed the completeness check; changing the first book identity failed the source/book identity check. Two fresh-process reconstructions each reproduced every one of the six package files and `validation.json` byte-for-byte. Exact hashes and validation receipts are in the linked current technical closeout JSON.

## Canonical linkage and limits

The canonical work identity, acquisition record, ordered source-member-set sidecar, and state targets now link the retained source and this technical evidence. The edition target is at `review`; the candidate remains nonaccepted. The electronic witness has not been collated against the 1853 print. CVW visual comparison and human acceptance remain unperformed. Rights are not assessed here, and publication is not authorized.
