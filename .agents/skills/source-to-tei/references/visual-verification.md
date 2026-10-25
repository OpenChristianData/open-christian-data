# CVW visual verification

> Retained migration baseline. The current universal workflow is in
> [SKILL.md](../SKILL.md); the current project capture requirements are in the
> [CVW evidence profile](../../../../docs/SOURCE_TO_TEI_REVIEW_OPERATIONS.md#cvw-evidence-profile).
> The original text below is preserved for existing capture consumers and ticket
> 15 reconciliation, not as a second current reconstruction checklist. Consult
> the relevant capture case when that contract requires it. Retire this baseline
> only after its callers and evidence requirements have been reconciled.

Use this process after mechanical source/candidate verification passes and
before a candidate is presented for a human acceptance decision.

## 1. Name the exact review

Record the work, edition, named retained-source authority, source hash,
candidate package, TEI member, validation report, and visual scope. For multiple
source authorities, choose one deliberately from the verified source manifest.

Choose and name one coverage mode:

- `whole-candidate`: every unit in the declared candidate scope is traversed;
- `systematic-sample`: a declared rule covers the work from opening to ending;
- `targeted-exceptions`: every mechanically risky or unusual feature is checked;
- `partial`: the exact reached units are recorded without a whole-work claim.

Keep **artifact traversal** separate from **close comparison**. Traversal proves
that every declared bounded unit was served and reached; close comparison names
the exact source and TEI anchors a reviewer actually inspected. Do not describe
a traversed candidate as closely compared throughout unless that occurred.

Keep three large-family coverage layers distinct: all declared artifacts and
selections admitted/reached, all served segments traversed, and exact locations
closely proofread or compared. Reaching every artifact or selection is not all-
segment traversal, and traversing thousands of segments—such as a 2,408-segment
family—is not a claim that every segment was human-proofread.

Keep exhaustive mechanical accounting separate from a risk-based visual sample.
API traversal, exact carrier parsing, oracle, validation, and accountability may
prove every ordered unit mechanically while Browser evidence covers a declared
beginning/middle/end, source-structure, and risk-anchor sample. Do not inflate
mechanical API structure into per-unit visual claims or multiply screenshots to
mirror every mechanically proved unit.

Apply the coverage mode to the exact candidate scope, then record the broader
declared work/edition scope separately. Exhaustive traversal of one candidate does not
complete a work/edition scope that is declared partial, spans other candidates or
works, or still lacks routed members. Seal both scopes and their independent
completion states.

For a multi-work candidate, record candidate-wide traversal plus a per-work map
of work ID, source root and boundary, TEI root and boundary, source/TEI segment
spans, reached locations, and work-specific result. Enumerate the complete set
bound to the declared review cohort before review. A route through one work does not establish
coverage of its siblings. Also record retained-source carriers outside the
candidate projection and their explicit dispositions.

Keep a machine-readable per-work coverage ledger with separate states for
`selected`, `eligible`, `candidate-ready`, `visually-traversed`,
`closely-compared`, `dependency-complete`, and `human-accepted`. Never infer one
state from another. Record whether any earlier correction-status isolation was
explicitly resolved, remains active, or is not applicable.

Report textual-witness coverage separately from rights, license, attribution,
schema, and other support carriers. A CVW source-member count is not a witness
count unless every member's declared role matches the producer's actual use.

When conversion selects paragraphs or records from a larger HTML/XML/document
shell, name that projection as partial until the outer shell has its own carrier
census and dispositions. Matching the selected text does not account for title,
navigation, wrapper, footer, license, or other unmodeled material.

Short works should normally receive whole-candidate review. For long works,
make every segment reachable and traverse the entire work for coverage when
practical; perform close side-by-side comparison at every major boundary,
risky feature, and declared systematic sample. A narrower review remains
partial evidence.

For a multi-work `whole-candidate` claim, reach every declared source and TEI
segment and closely compare each work opening and ending, every major work
boundary and risky feature, and the declared systematic sample. Do not claim
that every segment was closely compared unless an explicit exhaustive-close-
comparison pass actually inspected every segment.

Complete when another reviewer can reopen the same artifacts and understand
exactly what was and was not inspected.

## 2. Admit only verified evidence

Start CVW through its protected Windows launcher with a caller-selected,
validated, nonaccepted candidate. Require exact source-manifest, candidate,
package-member, and validation bindings. Treat stale catalog/index state as a
red derived-view condition to reconcile, not as permission to reinterpret the
source or candidate.

Search configured durable scratch/review roots before declaring that no
candidate exists. Classify every discovered historical candidate by its exact
manifest, producer, checker, policy, schema, package, and validation identities;
discovery or prior technical approval does not make it fresh review evidence.
Seeded or approved correction ledgers remain unverified input until every
claimed fidelity axis is checked against source; they may preserve source
divergence rather than correction.

Also search configured reconstruction-report and acquisition-packet roots,
including `reports/_reconstruction` and retained acquisition report packets.
Before rebinding any discovered route, preflight its physical LF/CRLF forms and
exact recursive closure; a located packet is evidence to classify, not authority
to reseal current bytes.

Use a disposable runtime envelope and preflight every claimed work route through
the reviewed project's [declared review admission](../../../../docs/RECONSTRUCTION_CONTRACT.md#declared-review-admission).
Default CVW admission uses declared work/acquisition sidecars and candidate-bound
source identities. Historical review requires explicit `--catalog PATH` and a
freshly derived or explicitly reconciled catalog. Do not guess a source member
or silently reuse a historical candidate.

When a maintained runner requires an approved external staging root that the
Windows sandbox cannot write, treat a scoped host-context execution as an
environment boundary rather than a reconstruction failure. Record the exact
absolute destination, authorization scope, protected inputs, ownership, and
cleanup receipt; never broaden the write root or substitute an in-repository
candidate destination.

Choose a candidate/review root that is verified writable and readable from the
actual reviewing agent context, such as an approved shared workspace-writable or
campaign visualization/scratch root. When external staging is required, avoid an
ACL-isolated host temp directory that later agents cannot read. Immediately test
candidate envelope and member readability from the reviewing context and record
both lexical and resolved physical paths. Path existence in external temp is not
proof of reviewability.

Separate source-local candidate validity from CVW route admissibility. Before
launch, verify that the declared route cohort names exactly the candidate's
intended work set and source profile; reject legacy combined-work or partial-
cohort routes even when the fresh candidate is otherwise valid. Reconcile the
declared work/acquisition/source bindings—never invent a second registry or
hand-edit canonical data to force admission. The source manifest names one work
or an explicit ordered work cohort; scoped primary members must match the
declared acquisition for each work. The linked admission contract defines the
implemented checks.

When a reviewed candidate lacks the declared identity/member handoff, preserve
its bytes and record the gap in its work ticket. This is not by itself a TEI
fidelity failure. Do not start a new source review merely to complete pipeline
coverage when that work is outside the current task. Any later manifest change
requires fresh dependent candidate and validation bindings.

For an explicitly selected historical WorkCatalog route, the following retained
catalog-generation rules apply. They do not require default declared admission
to generate legacy JSON or WorkCatalog:

When a mechanically reconstructable work has no canonical WorkCatalog row, keep
CVW blocked until route creation is explicitly authorized. Use the maintained
producer and supported ordinary catalog/data/IR generator, bind the new row to
the exact work identity and source manifest, derive WorkCatalog afresh, and then
repeat candidate admission. Explicit authorization for that canonical change
does not authorize an ad hoc registry, manual row fabrication, or publication.

Inventory the maintained parsers and generators before taking that branch. If
no supported canonical generator exists, fail closed: preserve the valid source-
local candidate as evidence, record WorkCatalog/CVW as Rework, and write a
missing-generator contract naming exact input identity, intended output schema
and configuration, and source-hash provenance. Do not hand-author generated JSON
or an ad hoc catalog. Config-only exact-ID association is unverified until the
exact retained source hash participates in the generated route binding.

If the maintained system already provides a manifest-only transient review-row
seam, it may admit the exact noncanonical work for that disposable session after
binding work ID, source manifest/hash, candidate, validation, and nonaccepted
state. If no supported canonical generator or transient seam exists, hard-stop
CVW and preserve the candidate packet. Never synthesize a row, hand-edit
canonical data/IR, or relabel candidate readiness as visual completion merely to
unblock review.

Retain a preflight transcript naming the declared runtime root, protected
launcher and loopback binding, exact `package/` plus `validation.json` envelope,
absence of package/member reparse points, declared identity/acquisition hashes
(or the explicitly selected historical WorkCatalog hash and row count),
complete candidate-to-work set, source-manifest/candidate/validation/TEI hashes,
and passing validation state. Hash every protected input before and after review.
Keep the runtime protected until the receipt names when it becomes disposable,
the exact identities covered, and the cleanup authorization boundary.

For a multi-member family, verify the declared identities and every admitted producer route
against the same canonical ordered member-set receipt. Record each route's exact
subset digest and reject incidental concatenation identities or a `full` claim
whose governed member set is explicitly partial.

For one abstract work split across independent source manifests and candidates,
use an ordered cohort receipt bound to the single work identity. Each member
keeps its own manifest, candidate, validation, and exact identity; the cohort
receipt proves member order, completeness, and work membership. CVW admission
must preserve that scope without physically compositing candidates, weakening member
identities, or fabricating unsupported canonical data/IR.

Explicit historical WorkCatalog derivation may require a full catalog scan without frequent
output. Before running it, record a ticket-local expected duration, timeout, and
progress/checkpoint policy. Where the ticket needs only route readiness and the
contract supports it, prefer a narrow exact-route check; do not mistake silence
within the declared bound for a hung process or weaken the catalog gate.

Before classifying an authority failure as semantic drift, compare physical
bytes, declared size/hash, committed or accepted packet bytes, LF/CRLF form, and
recursive closure. Classify the result as newline-only materialization, stale
receipt, semantic content drift, or missing/conflicting authority. Never repair
it by blindly rehashing current files.

Give each review a unique loopback port, or prove the selected port is unused
before binding. Treat an access-denied or otherwise inconclusive port check as
unknown, not as "no listener." After launch, verify the listening PID and exact
launcher command in the same host context, then request one candidate-bound API
work identity before trusting browser navigation. On shutdown, stop only that
verified process tree and confirm that the same port is free.

Bind the runtime receipt to loopback port, process/session identity, and a digest
of the loaded implementation/import snapshot. After any restart, probe a
behavior or implementation identity unique to the intended new code; HTTP 200 or
a generic ready message does not prove which imports are serving. If the prior
listener cannot be proven terminated, fail closed and allocate a new port.

Seal the renderer/service implementation or import-closure snapshot in the
protected-server/API receipt at launch, before any browser is available. If an
accepted legacy receipt lacks that field, preserve only its supported PID,
session, and exact response-hash bindings and declare an explicit import-identity
limitation; do not infer which implementation served those responses.

Protected startup should emit one machine-readable launch snapshot covering the
renderer, service, review contract, launcher, built frontend assets, executable,
PID/start time, and every protected input identity. Hash implementation/import
closures and built assets there. A continuously running PID plus later on-disk
hashes is useful continuity context but cannot retroactively prove which imports
or assets were loaded at launch; receipts must label continuous-process evidence
separately from true import/asset-at-launch identity.

For an external launcher, pin the intended worktree/project root in the Python
import search path before importing `cvw_app`; launcher CWD alone is not import
authority. Immediately inspect every loaded CVW module origin and fail closed if
any resolves outside that exact root. Record the intended import root and each
loaded module's resolved path, byte count, and digest in the launch snapshot.

Allow a namespace package such as `cvw_app` to have `__file__ = None`; bind its
resolved `__path__` entries instead of inventing a package-file identity. Still
hash every concrete imported implementation module used by the service,
including `cvw_app/launch_windows.py` and `cvw_app/review_service.py`, and require
their origins to remain under the intended import root.

For a large exact-text artifact, do not infer cacheability or repeated-page
performance from nominal source-file size. Allow the first identity-bound page
request to finish, then require a second request to disclose
`cache_resident=true` and return promptly. A client timeout does not prove that
server rendering stopped; confirm completion before retrying so concurrent
duplicate renders do not become false performance evidence or exhaust memory.

Before browser review of a large TEI family, require appropriately bounded
multi-segment rendering, zero truncated segments, complete node reachability,
and a private-metadata scan with zero prohibited disclosure. A schema-valid
candidate is not visually ready when its renderer drops nodes, truncates content,
or exposes private metadata.

Inspect every served segment's `oversize` and `truncated` flags, not only total
segment count or first/last anchors. Reconcile exact counts of retained structural
markers and repeated literal carriers across all served nodes; reachable indices
do not prove conservation when oversized units lose content.

Treat every schema-supported dictionary-entry variant—including `entry`,
`entryFree`, and local equivalents—as a renderer-readiness seam. Verify that each
is atomic or safely bounded, keyed/addressable, reachable, and nontruncated, with
opening and terminal entry controls. Passing tests for one variant do not cover
another.

Declare every readable-presentation transform used by the renderer and account
for it in logical-row versus paged-output reconciliation. Case display changes,
such as uppercasing an `entryFree/@n` title, are presentation transforms rather
than source or TEI mutations only when wording and identity conservation remain
provable and the transform is receipt-bound.

Evaluate paging bounds per selected carrier. Slightly different per-selection
maxima are valid when every selection remains within its bound and preserves the
same declared logical rows, marker occurrences, order, and identities. Do not
require equal page maxima as a proxy for conservation.

Complete when CVW visibly identifies the exact nonaccepted source/candidate
pair and exposes all validation, rights, unresolved, location, and unsupported
states relevant to review.

Candidate-session and declared-identity (or explicit historical catalog) preflight
prove routing, not reviewability.
Before calling a ticket visually reviewable, explicitly open Source Read and
Compare for every authoritative member and confirm each remains available within
the exact-text/serialized-response budget. A routed multi-member binary family
whose authoritative members are all over budget remains unavailable for visual
review until a compliant presentation exists.

Likewise, successful server launch, API traversal, or segment accounting is not
visual verification. Visual completion requires an actual supported browser
backend and retained visible-pane evidence. If browser backend discovery remains
unavailable after the documented retry, leave the exact verified server live
when safe, retain its loopback URL, process/runtime identity, candidate and
receipt paths, and hand them to a review-capable reassignment. Record visual
verification as unavailable/pending; never count API-only traversal as visual
completion.

When the browser backend is unavailable, retain its exact discovery/launch error
and emit an empty screenshot list. API traversal cannot populate or stand in for
visual screenshot evidence.

Use a fail-closed continuation handoff: seal the immutable candidate, API
traversal receipt, listener/process/session, implementation/import snapshot, and
current acceptance state; enumerate every remaining artifact, segment, and
anchor; and transfer the exact live work to a browser-capable visible session.
Do not substitute standalone Playwright, raw HTTP, or screenshots outside the
supported browser backend. The transfer continues the same nonaccepted review;
it neither resets nor advances acceptance state.

Treat browser availability and bindings as task-local. A delegated worker's
`No browser is available` result establishes a delegation/session-binding
limitation only; preserve its API/readiness evidence and return the visual
continuation to a browser-capable master or visible task. Before classifying the
CVW application, candidate, or host Browser as blocked, the master session must
perform its own browser discovery attempt and record that result.

## 3. Read both sides independently

Read the retained source and rendered TEI separately before comparing them.
Inspect source-defined wording, punctuation, order, divisions, paragraphs or
lines, notes, lists, tables, references, images and captions, document shell,
and meaningful metadata present in the declared scope.

Before claiming visual completeness, perform a carrier-class presentation audit
mapping every governed source class to what the panes visibly expose. Check
structural/attribute carriers such as division titles; inline emphasis,
scripture-reference, and link semantics; empty milestones such as rules or index
insertion points; and comments or processing instructions. Readable text equality
does not prove that structure, attributes, empty carriers, or comment semantics
were visible. Classify missing presentation as unsupported/pending unless a
bounded alternate surface supplies exact evidence.

Keep verified machine-evidence ledgers outside the ordinary reading stream as a
summary or linked evidence surface. The reading pane must expose the readable
source-body-to-readable-TEI projection, not require a human to reconstruct the
text from base64 or JSON node records.

When TEI embeds a complete base64 evidence carrier, validate canonical encoding,
the declared and manifest/header-bound media type, decoded byte count, and
decoded digest against the enclosing identity. In ordinary CVW reading, render
only a bounded identity/accounting disclosure; preserve the literal exclusively
on the exact TEI route. Do not weaken generic atomic truncation, paginate the
base64 blob as reading text, or treat it as a substitute for readable TEI.

Generated paired excerpt sheets or reports are not CVW pane evidence merely
because they place source and candidate text together. Count them only as
separate review evidence after independently opening them and binding both sides
to exact source/candidate identities.

A requested segment can legitimately show a recorded-location-outside-range
warning when independent paging retains a stable location outside that window.
Keep the warning visible, verify the requested segment identity and content,
and do not substitute neighboring material. Record the warning once as expected
no-substitution behavior. Change the recorded location only when deliberately
re-anchoring that artifact, never to imply source/TEI correspondence.

If selecting an outside-range recorded location inserts an excerpt/warning and
vertically displaces the evidence panes, a screenshot may select an in-segment
recorded location so both source and TEI remain visible. Bind the actual segment
and DOM focus independently, record the selected label and explain any label/
focus mismatch. The layout workaround supplies visibility, not correspondence.

Classify a recorded-location-outside-range warning against the route contract.
When the route requires the one recorded location exactly once and that location
belongs to another bounded segment, retain the warning as truthful evidence,
state that no neighboring content was substituted and no replacement inferred,
and do not fail the frame merely because its warning list is nonempty.

Distinguish a source-visible title from TEI work hierarchy. A different TEI
nesting level can be faithful when the exact source heading is retained and the
mapping is declared. A shorter wrapper head is faithful only when source wording,
order, work attachment, and the mapped full-title carrier remain intact. Missing,
rewritten, reordered, or misattached title text remains a discrepancy.
Treat an additional TEI hierarchy heading as faithful only when that heading is
source-accounted and its mapping is declared. A heading inferred from WorkCatalog,
profile metadata, or reviewer expectation is not source evidence.

Distinguish readable-body coverage from retained-head metadata coverage. A
format renderer may deliberately project only the body while a governed title,
edition, creator, or provenance field exists only in the retained head. Verify
head-only fields through the identity-bound exact-source fallback or another
explicit metadata surface. Do not treat absence from the body view as a TEI
omission, and do not infer source metadata from WorkCatalog or candidate labels.

Inspect retained electronic-header claims about correction or proofreading as
evidence to evaluate, not as generic front matter or automatic quality proof.
Surface personal names, contact details, and similar header material as
privacy/publication anchors without silently promoting or deleting them.

Keep inline TEI `note` content visibly distinct at its source position. The
readable projection must not concatenate the note into surrounding body prose.
Maintain a regression with body text, an inline note, and following tail text to
prove order and visible separation.

Complete when both panes show the requested artifact and location and every
warning or unsupported presentation is visible.

## 4. Compare honestly

Use side-by-side Compare at source-defined boundaries. Keep panes unlinked
unless the candidate supplies explicit correspondence evidence. Never infer a
match from shared position, labels, or textual similarity. Page long works
independently within CVW's response bounds.

When the public UI loads one `/compare` response containing both source and TEI
panes, seal that response and reconcile both embedded sides independently.
Record the response identity plus each pane's selected artifact, segment,
visible content bounds, and warnings; do not invent separate stage-response
receipts for panes that were delivered together.

At minimum, compare:

- opening and ending;
- every major source-defined transition;
- every unusual or mechanically risky feature found during inventory;
- tables, lists, notes, references, images/captions, and layout where present;
- a declared systematic spread of ordinary content; and
- every unit required by the named coverage mode.

Never treat a substring found anywhere in a whole rendering as a source-defined
structural anchor. Bind every anchor receipt to the exact artifact identity,
structural unit ID or number, local field or child, and exact text hash. For
multi-witness variants, use provider-specific needles rather than one normalized
phrase. A match in an answer, note, or neighboring unit cannot prove wording in
the requested question, heading, or other field.

For a multi-artifact edition, compare the exact source-artifact order with the
TEI edition order. Reconcile every open structural-sidecar disposition against
the current TEI representation, including explicitly absent or evidence-only
carriers. Phrase presence and local adjacency are insufficient because they can
confuse the retained textual authority with a sidecar or derived-structure
authority and falsely report a clean candidate.

For retained web sources, inspect the visible preface and contents, assigned
content boundaries, typed-by/acquisition/history wrapper tails, site suffixes,
and terminal imprint. Confirm that each remains attached to its declared parent
or carries an explicit evidence-only disposition rather than merging into the
last article or section.

For readable TEI semantics, inspect material attributes and the closed
text/body/work/evidence topology as well as words. Where present, verify note
placement/number/responsibility/anchor mapping, scripture-comment
type/passage/target mapping, table aliases in later works, visible work heads,
and the declared disposition of comments and processing instructions.

Verify the terminal text and structure of the assigned scope separately from
the physical end of the retained artifact. Inspect and log subsequent indexes,
sibling works, wrappers, licenses, or other outer carriers with their exact
dispositions. Do not call explicitly out-of-scope material a candidate omission,
and do not let an "outside scope" label hide an unaccounted carrier.

For `teiCorpus` or another multi-work TEI container, start fresh segment
boundaries at every child work. A work-specific route must open on that work's
own content, never the preceding sibling's tail.

For a multi-volume work, review each part through its own exact candidate and
source authority, then compare the exact terminal of one part with the exact
opening of the next. Record continuity without compositing the parts into a new
source authority. Include each part's metadata shell and use red controls that
mutate metadata independently of body text.

Complete when every claimed unit is reachable and inspected and no implicit
correspondence supports the result.

## 5. Record observations, not silent fixes

For each material observation, record exact source and candidate locations and
classify it as:

- faithful at the inspected scope;
- source/candidate discrepancy;
- unresolved or ambiguous;
- unavailable or unsupported presentation; or
- outside the inspected scope.

Distinguish parser defects from source disagreement, edition identity, rights,
OCR accuracy, and editorial judgment. Generate a fresh candidate for rework;
CVW remains read-only.

Complete when every exception has a location, status, and next evidence action.

## 6. Recover the exact session

Loss of a browser tab does not prove loss of the protected server or candidate.
If the verified listener and candidate-bound identity remain live, reopen the
exact review URL and recheck source, candidate, validation, and nonaccepted
state before continuing. Re-select any explicit source and require a byte-
identical copied identity payload before continuing. Do not regenerate merely
because a tab handle vanished.

If the server is gone, restart through the full protected preflight on a newly
verified port. Never trust readiness output alone when another process may own
the port; confirm the candidate-bound API identity first. A server restart or a
changed declared identity/acquisition, selected historical catalog, source-manifest,
candidate, or validation identity starts a
new receipt rather than continuing the prior one.

Complete when resumed observations are demonstrably bound to the same reviewed
artifacts, or the record names a new runtime without implying identity continuity.

## 7. Hand off exact identity

Use CVW's identity-copy handoff after reopening the exact source and candidate.
The external review record carries the reviewed identities, coverage mode,
reached units, observations, and result. CVW stores no acceptance decision.

Retain an exact candidate locator plus source manifest, producer, checker,
package, validation-report, and relevant policy/schema hashes. Historical
technical acceptance without a retained loadable locator and identities is not
fresh visual-review evidence.

Retain one exact copied identity payload per selected carrier, artifact-
traversal counts, close-comparison anchors, outside-scope dispositions,
warnings, viewport/runtime,
and every screenshot's name, byte count, SHA-256, UTC capture time, viewport,
stable route path/query, displayed segment ranges, and visible warnings. Retain
the exact identity-copy JSON and its SHA-256 plus the preflight transcript hash.
A screenshot supports a named anchor only when the image actually shows that
locus; scroll the current segment until the distinctive heading or literal is
visible in the retained image. A segment/status label or off-screen DOM text is
not visual-anchor evidence. When governed correspondence exists and is claimed,
show the distinctive bound locus in both panes. When correspondence is absent,
record independent source and TEI coverage without implying alignment.
For a terminal anchor, show substantial alphabetic prose in each reviewed pane;
numeric index sequences or short matching tokens can satisfy automated string
checks without providing useful human terminal evidence. When the retained
terminal segment is genuinely index-only, permit a classified terminal-index
anchor only after the browser probe scrolls both artifact panes to their actual
ends and the screenshot visibly shows the shared terminal index content plus the
exact terminal segment statuses. An off-screen numeric match remains insufficient.
Probe-generated copies of a terminal literal are corroboration, not native pane
evidence. Require exactly one native text-node occurrence in each current
terminal segment; wrap or highlight that occurrence without copying, reordering,
or replacing it. Scroll the existing bounded pane containers independently and
capture one viewport where both native highlights and both exact terminal
statuses are simultaneously visible. Record per-pane match counts, scroll state,
final viewport bounds, and pane/root bounds; fail closed when any required native
content or status is off-screen.
For a target inside one huge element/root text node, scrolling the containing
element is insufficient because it can land at the element start. The probe must
assert that the screenshot's actually visible text contains the distinctive
anchor literal before retaining the image.

Detect stale browser text layers by reconciling the screenshot's visible pixels
with current DOM-visible text and route/segment state. On disagreement, discard
the screenshot and recapture; do not treat fresh DOM plus stale pixels as visual
evidence. A reliable fallback may use a fresh page per anchor, wait for paint to
settle, and apply isolated native-node highlight compositing before capture.
Screenshots corroborate presentation and are not artifact-identity authority.

Verify screenshot files from their bytes. Sniff the actual media type, require a
matching filename extension or explicitly transcode, and decode dimensions with
a trusted image library. Fail closed on decode errors, inconsistent formats, or
impossible/ridiculous dimensions; never interpret dimensions using a parser for
a format that magic bytes disproved. Record each frame's `captured_at_utc` and
requested CSS viewport, verify encoded dimensions, and seal protected-input plus
implementation/import identity again after capture. Independently inspect every
claimed anchor in the decoded image and
require it to be fully visible rather than nearby, clipped, or off-screen.

Preserve rejected receipt evidence immutably. Author a separately identity-
sealed superseding receipt after repair, link it to the rejected predecessor,
and require an independent gate over the new files, hashes, decoded dimensions,
per-frame metadata, and visible anchors before relying on the repaired evidence.

Record console or network claims only when those traces were captured. Attribute
each entry to CVW, browser instrumentation, or unknown origin. For example, a CSP
`Log.entryAdded` caused by the Codex-injected
`#codex-browser-sidebar-comments-root` inline style is an instrumentation warning,
not a CVW application exception; because the warning exists, the log is not
clean. Report the classified warning rather than either blaming CVW or claiming
zero console entries.

When the Browser tab lacks a high-level `logs()` helper, use its supported CDP
capabilities—`Network`, `Runtime`, and `Log`—to seal route/status traffic,
runtime exceptions, and browser log entries. Record which domains were enabled
and the capture interval; absence of the convenience method is not absence of
diagnostic evidence. State explicitly that no acceptance was created or stored.

Use [cvw-receipt-template.json](cvw-receipt-template.json) as the reusable
machine-readable probe/receipt shape. Populate every retained screenshot's
`captured_at_utc` and stable reopenable `route_url`/`route_path_query`; do not
infer those fields later from file timestamps or surrounding logs.

Mechanical verification, visual verification, human acceptance, canonical
promotion, and publication remain separate claims and authorities.

Complete when the handoff reopens the same artifacts without guessing and the
human result is either explicitly recorded elsewhere or explicitly pending.

## Unsupported presentation

CVW is the default surface, not a reason to hide source features it cannot yet
render. Record the limitation as unavailable or unsupported and use a bounded,
source-faithful alternate viewer for that feature. Preserve exact identities
and return the observation to the same handoff. Do not build another general
review application inside an ordinary source ticket.

For a binary or archive authority without an exact-text surface, provide a
manifest-bound readable derived presentation or a bounded exact-format renderer.
Bind its derivation to the original container/member bytes and logical-carrier
inventory. The presentation is review evidence, not a second source authority.

Fail closed when decoded text is the only presented artifact and the exact
binary carrier/member identities and derivation receipt are not visible or
bound. Decoded content alone is not the retained binary source.

For a derived multi-member presentation, bind the complete ordered textual-
member set and a deterministic transformation receipt. Preserve every original
source/member digest and expose member plus byte/record/range provenance for
each readable unit. Never relabel one binary member, a support/config member, or
the derived text as the whole source. Metadata/rights members remain separately
accounted support evidence rather than extra textual witnesses.

Seal one exact copied CVW identity for every selected source carrier. Multi-
member evidence may share candidate and validation identities, but the source
selection identity is intentionally different; do not demand one common copied
payload across selections.

When the candidate schema has no dedicated producer-import-closure field, store
the derived-presentation code/import closure in its deterministic transformation
receipt and reference that receipt from manifest/provenance support evidence.
Do not invent an unvalidated candidate field or omit the executable derivation
identity.
