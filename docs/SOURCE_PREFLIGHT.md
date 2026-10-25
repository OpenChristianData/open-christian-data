# Source preflight for new acquisitions

Run this read-only discovery before writing a converter for retained JSON or
strict XML, XHTML, or ThML. It does not use producer preprocessing or build TEI.
It is additive tooling: existing acquisition, reconstruction, and acceptance
contracts remain authoritative.

From the checkout, use an explicit retained file or directory:

```powershell
py -3 -m build.tools.preflight_source C:/retained/acquisition
py -3 -m build.tools.preflight_source C:/retained/source.xml --encoding windows-1252
py -3 -m build.tools.preflight_source C:/retained/source.json --policy C:/review/feature-policy.json
```

The command prints deterministic JSON to stdout and never writes input files.
To retain the report, redirect stdout to a separately selected evidence path
outside the input directory. Do not overwrite a source or policy with the report.
For repository logical paths, pass `--repository-root <reviewed-checkout>`.
The existing storage resolver checks containment and resolves configured
`raw/`, `reports/`, and `exports/` roots without creating provider junctions.
Without that option the input is an explicit filesystem path.

## Read the report

- `members`: every file encountered, byte length, SHA-256 when read, detected
  format, and inventory status. Directory traversal is sorted; symlinks and
  junctions are reported without traversal. Unsupported files remain listed.
- `occurrences`: every observed element, attribute, text event, comment,
  processing instruction, namespace declaration, JSON field and typed value.
  Ordinals preserve traversal order. XML line/column locations are one-based
  lines and zero-based columns; structural addresses are occurrence addresses,
  not XPath or JSON Pointer. JSON field names appear separately from addresses,
  so repeated keys have distinct locations. Numbers retain their original
  lexical spelling; null, false, zero, empty strings and empty containers differ.
- `features`: counts by exact kind and name. XML `class` and EPUB `type` tokens
  are also enumerated individually. This is not an exhaustive semantic vocabulary;
  other attributes retain their values for source-specific interpretation.
- `diagnostics`: all observed decoding, parsing, duplicate-key, unsupported-file,
  unreadable-input, and resource-limit failures. Parsing stops within a malformed
  member, but remaining members are still inspected. Partial inventories are
  never reported as complete.
- `unresolved_occurrences`: every location without a declared disposition or
  explicitly marked unsupported. Without a policy, all occurrences are undeclared.

Strict decoding defaults to UTF-8. Use an explicit source-supported encoding;
there is no guessing or replacement decoding. XML declarations must agree with
that choice. DTD-bearing XML is deliberately blocked, with no entity expansion
or external access: use a source-specific independent reader for those sources.
XML event values reflect XML parser rules, including XML newline normalization;
this is not lexical byte conservation or independent parser corroboration.

The per-member byte limit defaults to 64 MiB (`--max-bytes` changes it). This is
an in-memory discovery tool with occurrence-level output; choose a bounded
acquisition rather than an entire library. ZIP inputs use the separate archive census below. Binary formats, standalone
HTML, CSV and plain text remain unsupported by the occurrence reader. Empty directories, unreadable files, duplicate JSON keys, invalid JSON
constants, and parsing failures block a clear result.

## Declare handling deliberately

The optional policy is a JSON array of exact feature rules:

```json
[
  {"kind": "xml-element", "name": "p", "disposition": "mapped", "reason": "Paragraph mapping is defined in the acquisition profile."},
  {"kind": "xml-attribute", "name": "title", "disposition": "unsupported", "reason": "Determine whether this source uses navigation titles or body headings."}
]
```

Each rule requires `kind`, `name`, `disposition`, and a nonempty `reason`.
Dispositions are `mapped`, `excluded`, or `unsupported`. Duplicate or malformed
rules fail. No wildcard or implicit blanket pass exists. Namespaces use expanded
`{URI}local` names. Empty namespace prefixes use an empty name. Inspect the report
for exact feature names rather than constructing rules from guesses.

A rule applies to that feature throughout the chosen input. Split inputs or
leave a feature unsupported when its meaning varies by context. Do not generate
and adopt an all-mapped policy from the feature list: that would declare the very
coverage this tool is meant to expose. Policy identity is bound by the canonical
rule digest; source bytes are bound per member.

Exit codes:

| Code | Report status | Meaning |
|---|---|---|
| 0 | `inventoried` | Discovery completed without diagnostics; no policy supplied. |
| 0 | `declared` | Every observed feature has a mapped/excluded declaration. |
| 1 | `needs-disposition` | Inventory is usable but policy leaves located features unresolved. |
| 2 | `blocked` or stderr error | Input, parser, encoding, policy or resource problem. |

`declared` does not mean the converter implements those declarations. Every
report explicitly says `source_fidelity: not-assessed` and
`acquisition_completeness: not-assessed`. A census of retained files cannot prove
that an upstream publication, archive or website was completely acquired.

## Continue source-to-TEI verification

Use this inventory to identify retained members, source relationships, ordering,
attachments, exclusions and unknown features before planning a conversion.
Then independently establish source relationships and check actual readable TEI,
including meaningful ownership, order, exclusions and generated content. Preserve
existing P5/Schematron, identity, mutation, reproduction and review checks.
This tool does not replace a family oracle, interpret unfamiliar semantics,
check assets/links for closure, decide rights, or grant human acceptance.

The initial regression tests are `tests/test_source_preflight.py`. They exercise
XML and JSON behavior, unfamiliar-feature mutations, empty/duplicate occurrences,
strict decoding and parsing, policy failures, and fresh-process/different-CWD
CLI determinism. They do not demonstrate whole-corpus fidelity.


## ZIP and source-media census

`py -3 -m build.tools.preflight_source <source.zip> --html-member <exact/member.html>`
hashes every readable file member and reports directory entries separately. The
optional selected HTML member supplies ordered literal `img/src` occurrences,
including missing versus empty alt values and whether an explicit body was open.
An HTML base element requires a source-specific resolver rather than guessed paths. Each local image reference must resolve
to exactly one hashed member. Repeated occurrences remain separate; unreferenced
artwork remains an other-retained member, not inferred body content. No files are
extracted. Duplicate names, missing targets and unreadable/oversized members block
an unqualified inventory. Feature policies apply to XML/JSON, not ZIPs.

This parser does not establish browser-recovered HTML topology, CSS/SVG/picture
media, complete source semantics, or rendered image equivalence. Inspect its
explicit limits and use the source-local oracle for those claims. External image
references and `srcset` require additional source evidence.

## Candidate link closure

`py -3 -m build.tools.check_tei_links <candidate.tei.xml>` checks simple local
URI fragments and document-wide `xml:id` uniqueness. It covers `target`, `corresp`,
`next`, `prev`, `sameAs`, `copyOf`, `synch`, `facs`, and `spanTo`, including lists
of references. Other attribute types are outside this check. Nonfragment URLs
are counted separately without fetching; `xml:base` and complex fragment schemes
are explicit unsupported cases. Exit 0 is a bounded pass, 1 failed/incomplete,
and 2 blocked input. No package or source bytes change.

For new or reopened routes, run this check alongside the existing source oracle
and retain its report. A closed link can still reach the wrong existing target:
verify source-ID-to-TEI-carrier identity independently and challenge retargeting.
Historical candidates are not silently revalidated or resealed by adoption.

## Profile-based fidelity comparison

`py -3 -m build.tools.check_source_fidelity --source <file>
--source-sha256 <declared-source-sha256> --candidate <tei>
--profile <profile.json> --mutations` compares independently read source carriers
with actual TEI. Supported profiles are selected XML mappings, LIB-062 catechism
JSON, TEI readable-body identity, and explicitly incomplete plain-text line
comparison. The checker's command help and focused tests describe supported
profiles; dated real-case review receipts remain maintainer evidence.
For an already bound candidate, also pass `--candidate-sha256 <declared-candidate-sha256>`.
The command also checks document-local links. Unknown source features prevent
a complete pass. Body-only checks exclude the header; text-line equality does not
prove hierarchy. Input snapshots are checked again before reporting. A malformed
candidate leaves unexamined claims unassessed. Plain-text line profiles compare
decoded content and order, but exclude physical line-ending bytes and terminal
newline state from TEI fidelity; source-unsupported hierarchy and attachment
remain explicit. Readable TEI text outside declared line carriers fails. Mutation
qualification runs only when the comparison and link baseline both pass.
For XML source mappings, each local fragment token is rebound to its selected
source carrier even in a mixed URL/fragment list. A referenced native ID that
occurs more than once in the retained document blocks the comparison; external
URL tokens are preserved literally and are not fetched or target-verified.

Use source-derived assertions for heading/note/verse roles, body boundaries,
attribute values, empty carriers and attachment. Profile declarations themselves
are reviewed interpretation; producer/checker agreement does not validate them.

## Advisory text observations

For each new or repaired reconstruction, retain text-quality evidence alongside
source accounting and fidelity validation:

1. **Screen inputs.** Include retained text and authored correction-map readings
   or other text overrides. Bind each screen to exact bytes and locations. For a
   format needing a dedicated reader, record that reader's coverage or retain an
   explicit unassessed gap. Done when every text-bearing input is accounted for.
2. **Screen actual TEI.** The supported `reconstruct_candidate` runner now writes
   `text-quality.json` beside `package/` and `validation.json` automatically before
   handoff. It screens every bound manifest authority with a supported reader
   (all JSON string values, plain text, XML text/tails) and actual candidate TEI.
   Its validation sidecar and deterministic summary bind the screen hash; the report binds source
   manifest, candidate package, implementation and individual input hashes.
   A failed candidate screen or binding drift prevents handoff. Other routes
   retain equivalent screens explicitly. Done when the report binds the actual
   candidate and identifies every unsupported or failed input screen.
3. **Disposition findings.** Compare located source, override and TEI passages.
   Record evidence and disposition for every occurrence or explicitly bounded
   group in the existing review report. Distinguish inherited readings, supported
   typography/language, introduced damage and unresolved readings. Carry remaining
   uncertainty and coverage gaps into the acceptance review's existing uncertainty
   or residual fields, with the screen path/hash in its evidence. Done when every
   finding and every text-bearing coverage gap is accounted for before a review or
   acceptance handoff. Zero findings establish only the stated screening coverage.

The report's `completed` status means the screening operation finished;
`coverage: partial` and `review_status: required` expose unsupported inputs or
observations. Schema files and binary assets may be outside character coverage;
account for their roles rather than treating them as missing prose. Source text
above 64 MiB, non-UTF-8 plain/JSON text, HTML and containers need
source-specific readers. XML supports bounded internal general entities and inert
external DOCTYPE identifiers without retrieving external bytes. Referenced
external or parameter entities remain explicit reader gaps. Every authority
remains listed. The six-member candidate
package and fidelity validation remain unchanged. Historical packages keep their
original evidence; this automatic sidecar applies to new runner invocations.

`py -3 -m build.tools.lint_text <source.txt>` reports character observations.
JSON requires explicit repeated `--pointer` selections; English lexical rules
require `--language en`. `--profile standard-ebooks` recognizes only its documented
word-joiner case. These observations never assert that a reading is wrong.

`py -3 -m build.tools.lint_text <source.xml> --xml-segments` scans every element
text and child tail independently, including headers, notes and alternatives.
It preserves segment locators and reports parent roles. Comments, processing
instruction values and attributes are outside its coverage. XML normalization
applies, including internal entity expansion. The report binds reader code,
parser versions and limits. External DTD validity/default attributes and ID
uniqueness are not assessed; duplicate IDs do not prevent character screening.
Unsupported dependencies or malformed XML fail closed. XML mode deliberately runs
only character checks, so it cannot create false repeated words across markup or
infer a preferred reading branch. Patterns split across segments may be missed.

Exit 0 means observation completed, even when findings exist. Invalid inputs exit
2. Zero findings do not certify clean text. Keep exact source hashes and use
edition/witness evidence for editorial decisions. Earlier bounded text-quality
evaluations are calibration evidence, not corpus precision estimates or
correction rules.

### Current accepted-library screen

For every discoverable TEI rather than accepted masters alone, run
`py -3 -m build.tools.lint_tei_tree --root <checkout> --root <physical-library>
--root <other-candidate-root> --output <fresh-report-directory>`. It classifies
XML by root element, includes XML/TEI members in ZIPs, retains every path and
screens each unique byte sequence once. `files.json` maps duplicates to their
screen; `observations.jsonl` retains locations. Discovery considers `.xml`,
`.tei`, `.sgm` and `.sgml` filenames and corresponding ZIP members; it does not
sniff arbitrary extensions for embedded TEI. Explicit inaccessible paths,
unclassified XML, unsupported archives, unresolved entity dependencies or detected input drift
make the report partial (exit 1). Reparse directories are excluded and reported;
pass their approved physical targets as explicit roots. Development dependencies
and Git metadata are excluded by name. The report records its non-atomic snapshot
limits. This broader screen changes no accepted-master or candidate status.

`py -3 -m build.tools.lint_library_text --output <fresh-report-directory>`
discovers current declared editions from work sidecars and binds each promoted
acceptance to its exact master path, size and hash. It records unaccepted
editions separately. Invalid authorities, orphan acceptances, failed scans or
inputs changed during execution make the scan incomplete (exit 2). A completed
screen exits 0 even when observations exist. It does not rerun the full
acceptance or source-fidelity gates.

The report retains every located observation and groups counts by header,
front/body/back region and original `sic` versus corrected `corr` reading.
Preserved damaged originals and historical proposal notes remain evidence;
they are not automatically defects in the corrected reading. Legitimate text
can also match a signature: Czech `náš` is a known example. Invisible characters
often represent intentional typography. Do not auto-decode or delete matches.

For future acquisitions, screen retained source text with `lint_text` during
preflight, retain its hashes and locations, then screen the resulting TEI again.
Use explicit JSON string selections or XML segment mode as appropriate. Compare
the same source passages to distinguish inherited damage from conversion loss.
Screen authored correction-map readings and other text overrides too: a clean
retained witness cannot expose encoding damage introduced in a shared correction
map that both producer and checker trust.
For reviewed authored fields, bind a separate source-backed expected-reading
artifact and check it before reconstruction. Preserve the old map and manifest
when a reviewed reading changes. For repairs to accepted TEI, pin the complete
work generation before reading the master, keep prior bytes, prove only reviewed
spans changed, and reject concurrent drift before journaled installation.
The library command provides the repeatable inventory after installation; it
does not replace source accounting, hierarchy, attachment, link or fidelity checks.

When a correction is supported, preserve the retained bytes and original reading,
bind the exact source field and offsets, and retain a hash-bound comparison
witness. A matching word elsewhere is insufficient: compare its passage or
the same numbered note. Verify the actual TEI choice placement independently,
recover the previous master by selecting originals, reproduce the revised master,
and check acceptance and existing consumers before a guarded installation.
The finite October 8 CCEL repair tool demonstrates that process for its four
declared editions; it is not a general unattended correction interface.
