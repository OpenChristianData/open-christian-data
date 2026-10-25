# Systematic Theology, Vol. 3 — retained source evidence

This ticket-local reconstruction candidate is derived only from the retained non-OCR Project Gutenberg text `raw/gutenberg/pg45283.txt`, eBook #45283. The title page identifies *Systematic Theology*, Volume 3 of 3, by Augustus Hopkins Strong, gives the subtitle *The Doctrine of Salvation*, and prints a Griffith & Rowland Press, Philadelphia, 1909 imprint. The set-level 1907–1909 span is separate; it does not establish this volume's original-publication year.

## Printed contents and body hierarchy

The printed `CONTENTS` heading is at line 62 and its outline occupies lines 65–234. The source's leading spaces establish parent/child relationships: 140 entries form a nested outline, and 29 entries continue across physical lines. The transcription represents each entry as one anchored paragraph inside a nested TEI list; wrapped lines remain joined by anchored `<lb>` elements, while indentation is represented by the source-derived nesting.

All 140 contents entries were matched, in order, to exact normalized text in standalone body source blocks. Those body headings are represented by nested TEI `<div>` and `<head>` elements following the printed contents parent relationships; 23 headings span more than one physical line and remain one `<head>` with line anchors. Part, chapter, section, subsection, and index labels come from the printed entry text. This is a deterministic source-text mapping, not full visual proofreading: structure not explicitly listed in the contents and any unrecognized relationships remain open for review.

An unheaded `div type="source-outline-body"` groups the source beginning with the `[Cover Art]` block at line 241, the adjacent transcriber note, the mapped outline divisions, and the Gutenberg trailer. It is a neutral TEI sequence container, not a heading or a claim of additional source hierarchy. The trailer has its own unheaded `div type="source-envelope-tail"` beginning at the Gutenberg end marker so the retained file order remains valid under TEI P5 block/division sequencing.

## Notes, figure placeholder, and emphasis

The two explicitly labeled transcriber notes at lines 243–244 and 271–272 are represented as `<note type="transcribers-note">`; the second is attached under the Part VI division whose heading begins at line 267. The `[Cover Art]` marker at line 241 remains a text placeholder, not an invented image. Citations, page references, and other prose that mentions a note remain in the source text; no separate scholarly note apparatus is inferred.

The retained text uses paired underscore delimiters within blank-delimited blocks. The source inventory contains 11,226 markers forming 5,613 spans, of which 1,974 cross physical lines. These balanced spans are represented as `<hi rend="italic">`; line breaks and physical-line anchors are retained inside spans where needed. Unmatched delimiters fail closed.

The route preserves every nonblank physical source line in order with a source anchor. Blank physical records are accounted for as separators. The Gutenberg wrapper and footer remain in the transcribed source envelope. The source is 1,868,543 bytes with SHA-256 `103dc623072326111214078015dfbe8cb8f97197cba6e5e6faffede8bb1a20fe`.

Gutenberg identifies this as Volume 3 of 3 files. Its rights notice is not worldwide rights clearance. The original-publication year remains unestablished. The candidate is nonaccepted, and publication is not ready.
