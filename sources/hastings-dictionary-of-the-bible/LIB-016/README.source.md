# LIB-016 Hastings *Dictionary of the Bible* source accountability

This route reads five retained Internet Archive DjVuTXT OCR files from
`D:/Library/Open Christian Data/raw/ia/hastings-dictionary`. It neither copies
the witnesses into this repository nor writes a canonical candidate.

The frozen identity is the five UTF-8 files concatenated in lexicographic
filename order with no invented separator: 44,374,718 bytes, SHA-256
`1cd0f245927973e5f84db7bad42c71aa1dfb259e5aad026a40dd5f0d6238f7a7`.
The candidate preserves every byte after strict UTF-8 decoding, every literal
LF boundary, and every OCR reading without Unicode normalization or cleanup.

The work is James Hastings (editor), *Dictionary of the Bible*. Volumes I-IV
are the Scribner/T. & T. Clark 1911 reprint; the fifth retained member is the
1909 Extra Volume. The Extra Volume OCR was generated incorrectly: it contains
zero Latin letters and 4,057,175 Greek-classified alphabetic characters. That
defect is preserved verbatim and recorded as requiring exact scan-bound
EzraOCR handling; this packet does not repair it.

Existing derived JSON is partial diagnostic evidence only and is not source
authority. Underlying publication, worldwide rights, scan/OCR-layer terms,
edition identity, textual readings, editorial decisions, acceptance, and
publication remain human decisions. The candidate is nonaccepted and
publication is not authorized.
