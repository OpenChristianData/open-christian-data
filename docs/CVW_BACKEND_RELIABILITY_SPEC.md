# CVW visual-verification efficiency and reliability spec

> **Historical record.** The design, status and commands below describe their recorded checkpoint. For current text work, use the [contribution workflow](TEXT_CONTRIBUTIONS.md) and its governing contracts.

**Status:** All tickets 01–16 approved for implementation, ready-for-agent within their dependencies, orchestration plan gate, and design boundaries. Updated 2026-09-03.
**Tracker:** Durable local files; not published to an external tracker.

**Execution approval:** The user approved the complete packet, requested saving
it in Git, and requested a new visible implementation master using
multi-stage-orchestration. The master owns the current cross-stage plan, Claude
adversarial plan review, worker dispatch, independent gates, and final integration.
This supersedes all earlier backend breakdown-review holds.

**Approval update, 2026-09-03:** The latest direction expands planning to all
useful efficiency avenues, approves compact Compare, and explicitly rejects an
overbuilt testing harness. Agent focus is a toggleable, viewport-filling version
of existing Compare; the human default stays intact. This supersedes the earlier
compact-only restriction for the image-delivery and agent-integration work below,
not for unrelated redesigns. New design changes still require proposal images
before implementation. This update changes planning documents only.

## Problem Statement

An agent needs a trustworthy local CVW session before it can visually compare a
retained source witness with a candidate master. The runtime-usability branch
improves launch isolation and diagnostics, but its optional diagnostics can write
into protected inputs, obscure the original failure, and leave an incomplete
receipt. Its implementation fingerprint does not identify everything that
produces the served representation. The observed small-candidate speedup does
not explain earlier long launches.

The earlier packet overemphasized runtime reliability and omitted much of the
original efficiency problem: original image reads/hashes/transfers, progressive
image delivery, structured evidence, and selection of images sent to the agent.
These are three different costs: backend I/O/CPU, browser transfer/decode/render,
and model input. Improving one does not establish improvement in the others.
Reliable HTTP responses and runtime receipts are not visual verification.

## Solution

Repair the existing protected launcher and session diagnostics in place. A caller
gets an isolated loopback session, trustworthy identity, complete machine-readable
diagnostics when persistence works, and an honest degraded-diagnostics state when
it does not. Protected inputs remain unchanged. Measure remaining launch latency
before deciding whether more performance changes are justified.

For original reliability tickets 01–08, use complete backend slices from launcher
inputs through HTTP or saved output to observable tests. The UI is not part of
those repairs. Preserve their public response semantics unless a documented
identity correction requires a contract change. Efficiency tickets separately
own the narrow image/projection interface extensions below.

Use exact identity → bounded structured evidence → an appropriate preview or
region → original-resolution detail when needed. Text/DOM helps choose evidence;
it does not replace inspection of source and candidate pixels.

The approved frontend slice presents the same artifacts in existing Compare,
with a toggleable agent-focus layout. It adds zero screens or independent
frontends. The ordinary human view remains the default. The live interface may
retain the approved slim strip for orientation and recovery; a bound inspection
crop need not send routine labels or controls to the model. Use readable content,
not reduced font sizes, to judge success.

## User Stories

1. As an operator, I want unsafe diagnostic destinations rejected before any write, so that source witnesses and candidate masters remain unchanged.
2. As an operator, I want path aliases and Windows junctions checked against the resolved storage roots, so that lexical path differences cannot bypass protection.
3. As an operator, I want an omitted diagnostics destination to create no persistent output, so that a normal review does not create a new state store.
4. As an agent, I want an invalid launch to preserve its original cause, so that a logging failure cannot mislead the recovery decision.
5. As an agent, I want each HTTP request to produce exactly one response even if logging fails, so that successful content remains usable.
6. As an operator, I want diagnostics degradation reported through an independent bounded channel, so that lost evidence is visible without recursive failures.
7. As an operator, I want server shutdown to finish despite diagnostics failures, so that a failed log volume does not strand a listener.
8. As a receipt reader, I want the latest receipt to be either the old complete version or the new complete version, so that concurrent reads never consume truncated JSON.
9. As a receipt reader, I want failed receipt replacement to preserve the last good snapshot, so that evidence remains interpretable.
10. As an agent, I want a declared implementation fingerprint covering the backend and served frontend artifacts, so that I can distinguish sessions that produce different representations.
11. As an agent, I want changed serving artifacts detected or refused, so that a launch-time identity cannot silently describe different response bytes later.
12. As an operator, I want fingerprint rules independent of machine-specific absolute paths, so that identical implementations have comparable identities.
13. As an operator, I want browser-open attempts, success, false results, and exceptions distinguished, so that readiness is not confused with browser visibility.
14. As an agent, I want phase durations and terminal phase outcomes, so that I can locate a slow launch without guessing.
15. As an operator, I want readiness timeout and shutdown results attributed correctly, so that recovery targets the actual failing phase.
16. As an operator, I want two concurrent sessions to expose their own origins and identities, so that a port collision cannot silently cross-wire reviews.
17. As an agent, I want a request ID to correlate the response with its diagnostic record, so that a failure report identifies the exact request.
18. As an operator, I want representative cold and repeated launch measurements, so that optimization decisions reflect real candidate sizes and execution contexts.
19. As a maintainer, I want the final member-integrity check retained after preflight de-duplication, so that performance work does not serve changed candidate bytes.
20. As the reviewer, I want backend completion explicitly distinguished from visual verification, so that passing runtime tests cannot become a claim about unseen pixels.
21. As the user, I want backend progress independent of my deferred UI decision, so that I can return to presentation choices later.
22. As a future assessment consumer, I want runtime diagnostics to remain distinct from agent assessment and human review, so that no diagnostic receipt creates acceptance or publication authority.
23. As a visual-review agent, I want the two artifact renderings to occupy almost all of the normal capture view, so that incidental UI does not dominate the evidence frame.
24. As a visual-review agent, I want each pane's role, location, and status supplied with its image, so that I do not have to read repeated UI labels from pixels.
25. As an agent, I want exact structured identity and deterministic existing Compare navigation, so that full hashes and large selectors need not occupy every frame.
26. As an agent or operator, I want existing independent controls available through a small accessible disclosure, so that the minimal presentation remains operable without inventing a second API.
27. As an agent, I want correspondence and material warnings inseparable from the inspection evidence, so that a clean crop cannot hide missing, unsupported, or mismatched content.
28. As a human reviewer, I want ordinary Library, Read, and Compare unchanged by default, so that an agent-oriented density choice does not replace my normal UI.
29. As a reviewer, I want compact and ordinary views checked against the same inputs and renderer, so that layout simplification cannot silently change the content being compared.
30. As the user, I want efficiency work separated from unrelated redesigns, so that the approved compact direction does not become a new application.
31. As an operator, I want a short baseline separating disk, transfer, render, and model costs, so that effort follows an observed bottleneck.
32. As an agent, I want one bounded evidence brief with exact-pair references and current exceptions, so that I need not repeatedly ingest full response bodies.
33. As an agent, I want image dimensions, format, and identity-bound handles before loading pixels, so that I can choose a suitable representation.
34. As a reviewer, I want a lightweight overview with an explicit original-resolution fallback, so that orientation is fast without claiming tiny text was verified.
35. As an agent, I want an exact source-coordinate crop with its provenance, so that I can examine fine detail without resending an entire page.
36. As a reviewer, I want image space reserved before decode, so that asynchronous loading does not move my target out of the frame.
37. As an operator, I want repeated image work reused safely where measured, so that validation does not cause unnecessary repeated reads, decodes, or transfers.
38. As a reviewer, I want changed input identities rejected even after reuse, so that an old image cannot masquerade as current evidence.
39. As an agent, I want stale requests and image completions ignored or canceled, so that rapid navigation does not mix two review states.
40. As an agent, I want a capture bound to the rendered pair and current pane geometry, so that cropped pixels remain interpretable without repeated chrome.
41. As an agent, I want the smallest legible image for the actual question, so that layout checks and punctuation checks do not pay the same cost automatically.
42. As a reviewer, I want relevant collapsed content expanded and in view before capture, so that invisible JSON or lazy images cannot count as inspected.
43. As an agent, I want already inspected unchanged frames referenced instead of redundantly attached, so that repeated reasoning need not repeat image input.
44. As a reviewer, I want exception-first review plus declared ordinary/boundary samples, so that efficiency does not erase coverage limits or miss systematic errors silently.
45. As the user, I want existing tests and a few real comparisons to prove the changes, so that testing infrastructure does not exceed the product work.

## Implementation Decisions

- **Existing seams:** use the protected launcher, recorder, review contract/HTTP service, existing Compare components, and supported agent browser. Extend existing interfaces narrowly for image metadata/derivatives where needed. Add no second service, renderer, registry, database, or independent frontend.
- **Safe output:** resolve candidate, catalog, configured storage, retained-source, frontend, and repository-protected locations before creating any diagnostic output. Reject destinations or existing output targets that resolve into protected inputs; use the existing storage-topology authority. Handle nonexisting descendants through resolved existing parents. Document the supported local threat model rather than claiming universal protection against hostile concurrent filesystem mutation.
- **Failure policy:** unsafe or initially unusable requested destinations fail launch before writes. After successful initialization, persistence failures degrade diagnostics without replacing the primary error, corrupting an HTTP response, or skipping cleanup. Degradation must be explicit and bounded; unrelated programmer errors remain visible.
- **Atomic snapshots:** serialize before replacement, use a uniquely named same-directory temporary file, and atomically replace the latest receipt. Preserve the prior receipt on failure. Keep append-only diagnostic events separate from current runtime state; neither is a workflow ledger.
- **Implementation identity:** define a deterministic, versioned manifest of backend modules that influence the review contract and the exact frontend entrypoint/assets served. Hash stable relative member identities plus content digests. Identify missing, changed, or unsupported members explicitly. Do not use a Git commit alone or an incomplete two-file digest as full implementation identity.
- **Serving continuity:** bind identity to observed serving bytes or reject detected artifact drift and require relaunch. Choose the smallest demonstrably correct approach; do not create a persistent build cache or packaging system. Backend identity ticket 04 identifies frontend assets; it does not authorize frontend edits itself.
- **Lifecycle truth:** distinguish readiness from browser-open outcome. Success means only that the opener accepted the request, not that a human or agent saw pixels. Preserve the manual URL and correct terminal state.
- **Timing:** measure elapsed phase durations with a monotonic clock and event timestamps in UTC. Cover resolution, candidate validation, identity, bind, readiness, browser-open dispatch, and shutdown as applicable, including failed phases. No tracing server or global telemetry system.
- **Latency investigation:** measure a current-valid small pair and an available representative long or multi-segment candidate in the correct host/sandbox context. Record observable first versus repeated runs; claim an OS-cold cache only if controlled. Preserve final serving integrity checks. Stop with a documented no-change result when no repeated bottleneck is established.
- **Authority:** runtime receipts describe sessions, not visual coverage. The existing CVW visual-receipt contract remains separate. PIPE-016 owns future durable agent-assessment/human-review separation; this spec does not implement it.

### Approved compact presentation

- **Scope:** one optional, viewport-filling agent-focus mode of existing Compare, not a new top-level route, screen, or renderer. Full-screen means an application layout first; an OS/browser Fullscreen API is unnecessary. Preserve the ordinary default view and return path. The approved v3 image remains the live layout proposal, not source evidence.
- **Live layout versus model input:** two readable content panes separated by a thin divider. The v3 slim strip keeps role, useful locus, native status, compact correspondence, and disclosure available for interaction. These are not intrinsically required image pixels. Ticket 15 may supply an artifact-region crop plus accompanying bound structured state; this avoids another UI state solely to remove a few labels. Until that contract is working, retain the visible strip in evidence frames.
- **Remove repeated chrome:** no global page title, sidebar, explanatory cards, separate availability cards, large location rows, previous/next rows, full hashes, session banner, or full-width routine correspondence tutorial in the normal compact frame. Do not shrink artifact text or remove source content to meet a density target.
- **Controls on demand:** one small labeled, keyboard-operable disclosure reveals existing controls, including independent pane navigation and return to normal view. It may sit outside an inspection crop. Controls remain reachable, not hover-only or dependent on guessed shortcuts/private browser state. Reuse existing exact URL navigation; new image-region parameters are separately bounded by ticket 13.
- **Route change is real:** the current parser rejects unknown parameters. Explicitly allow and validate the compact presentation flag in Compare only, reject unsupported/duplicate values, and preserve it across the relevant route serialization, navigation, Back/Forward, and reload paths. This is primarily presentation work, not literally CSS-only.
- **Material exceptions:** keep loading, failed/missing/unsupported content, location-outside-range, and correspondence problems visible in the live UI. The capture packet always supplies relevant warnings as text. A blocking state refuses a normal ready capture; retain an explicitly invalid diagnostic frame if useful. For a qualified-but-reviewable state, include the relevant warning in the evidence frame rather than silently cropping it away. Routine healthy badges need not consume pixels. Absent correspondence permits independent inspection, never inferred alignment.
- **Semantics:** the mockup's short Ready label illustrates a healthy state; implementation must retain truthful current status semantics and must not imply image decode, visible pixels, fidelity, or acceptance from availability alone. No new artificial readiness verdict.
- **Boundary:** preserve human layout/navigation and renderer meaning. The efficiency slices may improve delivery and agent-driven expansion/readiness, not rewrite artifact content or change human expansion defaults. A genuinely different visible design needs an image-first decision; a new backend route is not a new UI screen.

### Efficiency work across the full path

- **Small baseline (10):** use one representative image pair and one long text pair, first and repeated access. Record elapsed time, observed read/hash work where accessible, HTTP requests/transferred bytes, decoded/rendered dimensions, ready-to-inspect time, and frames actually supplied to the model. Include model/provider/detail and token usage only when exposed; label estimates and unavailable measurements. A short report is sufficient. No telemetry dashboard, benchmark framework, corpus-scale matrix, or new paid-provider integration.
- **Bounded evidence brief (11):** derive one read-only projection from existing exact Compare/identity data: pane roles and exact artifact references, candidate/validation bindings, independent ranges/loci, correspondence, current warnings, and image metadata/available handles. Keep full content and diagnostics on demand; return explicit bounds/continuations rather than silently dropping warnings. Stable hashes may be referenced after introduction, but a hash alone is not readable context. Do not include base64 images or duplicate complete bodies. This is derived session evidence, not a registry, fidelity verdict, or browser-readiness claim.
- **Progressive image delivery (12):** serve identity-bound size-limited previews and consume them in agent Compare, with original-resolution access on demand. Return intrinsic dimensions, media type, source digest, derivative dimensions, and transformation identity. Choose a small number of justified sizes; use responsive hints only if multiple variants are needed. Reserve aspect ratio; wait for the selected image's actual decode and paint before inspection. Preview is for orientation, not fine-text acceptance. Reuse browser behavior and existing components; preserve human defaults.
- **Exact region inspection (13):** accept a bounded crop in a declared coordinate space, with page/member identity, original dimensions, orientation, crop box, output dimensions/scale, and transform version. Normalize orientation explicitly; reject invalid/out-of-bounds coordinates rather than silently substituting another region. Use lossless detail by default for text-bearing crops. No generative enhancement, OCR replacement, inferred counterpart crop, or custom tile/zoom application. Agent navigation can request the region through validated existing-route extensions; human crop tooling is not required.
- **Safe reuse (14):** measure duplicate resolve/read/hash, decode, derivative generation, and browser transfer separately. Prefer sharing a verified buffer within one request, bounded session derivative reuse, and conditional delivery where sufficient. Keys bind source/member/content identity and every transformation parameter. Revalidate mutable inputs before reuse or conditional success under the current fail-closed contract; size/mtime alone is not identity. Every request need not repeat every internal operation, but stale bytes must not be reported as current. An immutable snapshot contract would be a distinct semantic decision, not a silent removal of integrity checks. Bound memory/disk lifetime, isolate sessions, and use approved non-input storage if persistence is necessary. Retaining rehash costs is acceptable when no smaller safe alternative is justified.
- **Capture binding (15):** reuse the supported browser and existing visual-receipt shape. At capture, bind route/response identity, rendered generation, per-pane role/ranges, current warnings/correspondence, viewport/device scale, scroll/crop bounds, image variant, and capture time to the actual screenshot bytes. Recheck state around capture and reject navigation/identity changes. Check actual visible anchors; fresh DOM or a matching metadata hash alone cannot prove fresh paint. Retain the parent frame and deterministic crop transform when the model receives a cropped frame, and supply the compact state beside that image. File metadata alone is insufficient if it is not supplied to the model.
- **Protocol compatibility (15):** current visual-verification guidance includes visible status requirements, with particularly strict simultaneous native-anchor/terminal-status rules. Those are current evidence rules, not immutable vision requirements. Align the existing guidance/receipt population profile narrowly before using status-free crops as completed evidence. Preserve legacy frames and provide a labeled-frame fallback where equivalent binding is unproven. Do not invent a second validator, schema, or acceptance record. Planning approval does not make an existing status-free screenshot compliant retroactively.
- **Evidence selection and model input (16):** use structured facts to choose risky features and the declared ordinary/boundary sample. Capture only requested native regions, expanding relevant content and independently navigating panes. Use an overview only when orientation is needed, then legible detail; do not force every request through a thumbnail. Select resolution/detail for the actual provider and question, prefer lossless text captures, avoid giant contact sheets, and escalate when readability is insufficient. Reuse exact unchanged prior frames only when the agent already inspected them and the current context supports references; otherwise resend the needed image. File handles/upload reuse reduce transport, not automatically model-token cost. Keep original evidence locally while sending only needed pixels. Record scope honestly; sampling is not exhaustive verification.
- **Already present / conditional avenues:** preserve bounded JSON responses, independent paging, request abort/timeout behavior already on the usability branch, and transport-only retry rules. Extend cancellation/stale-result guards to new image flows rather than ticketing the existing work twice. Evaluate text payload deduplication in 11 and capture reuse in 16. Compression formats, request coalescing, renderer memoization, prefetching, virtualization, and tiles are options only when the small baseline shows a remaining need; prefer no change when costs exceed benefit. Do not prefetch an entire work or shrink text to hit a token target.

## Testing Decisions

- Prefer the highest existing useful seam: protected launcher input to actual loopback HTTP response, process cleanup, and persisted receipt/event outputs.
- Use the existing launcher and service tests as prior art. Keep deterministic filesystem failure injection at the recorder boundary where an HTTP-only test cannot reliably create a full disk or interrupted replacement.
- Good tests assert external outcomes: protected trees unchanged, one complete response, original error retained, old-or-new complete receipt, correct identity, correct origin/request correlation, and released listener. Avoid asserting incidental call order or private helper structure.
- Use synthetic temporary protected trees and candidate fixtures for rejection tests. Never deliberately write into real retained sources to prove protection.
- Cover Windows aliases/junctions in the supported host context; report unavailable permissions as an untested capability rather than passing the case.
- Fingerprint controls change one renderer, contract, or served asset at a time in fixtures and verify identity/drift behavior. Unchanged bytes and a moved checkout should remain deterministic under the declared identity rules.
- Run the smallest affected test set for each ticket, expanding to launcher/service integration where warranted. The final backend canary is not a repository-wide corpus gate.
- A backend test cannot attest browser pixels, screenshot coverage, token savings, or human review. The dedicated capture slices need actual supported-browser and image inspection evidence for those claims.

For ticket 09, use existing route/component tests plus a live browser canary of
ordinary and compact Compare against the same exact inputs. Verify that both
artifact pixels and their native statuses/loci are visible, controls remain
reachable, and relevant warnings survive the reduction. Test reload and
Back/Forward with asymmetric pane locations and ranges. Check representative
desktop sizes and an honest narrow-width fallback without changing the human
default. No blanket corpus test is required for a presentation-only change.

For 10–16, reuse existing contract/HTTP/route/component seams plus the supported
browser. Each slice adds only its relevant cases: wrong identity, invalid crop,
changed source despite cached output, stale navigation/decode, unavailable image,
or warning dropped by a crop. Use existing synthetic fixtures and a few real
before/after observations; no new generic harness, screenshot-diff platform,
provider simulator, or exhaustive cross-product matrix. A thin local helper is
justified only if it removes repeated manual work and remains smaller than the
behavior it checks. Reuse the same representative pair across slices.

Record visible content area, capture count, and actual usage when available.
Tiny or compressed screenshots are not a success if required details cannot be
read. The backend canary does not gate independent UI/image slices; each ticket
declares real dependencies. No fixed performance claim is an acceptance target.

## Out of Scope

- New screens/frontends, human-default redesign, global navigation overhaul, changed human expansion defaults, or unrelated styling. Compact mode and its scoped progressive image/region delivery are in scope; design changes beyond the shown concept remain image-first.
- The pre-existing TEI line-break renderer changes; preserve and coordinate their ownership separately.
- General browser automation platforms, a new visual-receipt validation framework, new provider integrations, and automatic provider/model selection. Thin capture and evidence-selection work in 15–16 is explicitly agent integration, not backend repair.
- PIPE-016 schemas or acceptance logic, acquisition changes, reconstruction, canonical source/candidate/data/master changes, publication, deployment, and unrelated Git changes. Saving/importing this approved planning packet is separately authorized.
- Speculative caches, broad refactors, duplicate state stores, tile infrastructure without a demonstrated need, or arbitrary latency/token targets.

## Further Notes

This specification synthesizes the 2026-09-02 adversarial review and 2026-09-03
read-only recheck of branch codex/cvw-usability-20260902 at ac5b78e2. Recheck the
implementation before starting a ticket. The canonical checkout contains other
unrelated work, and the usability worktree contains another owner's line-break
changes. Neither is an invitation to merge or overwrite work.

The latest branch-tip check found 82bc5c26, whose committed delta from ac5b78e2
changes only the usability plan. Its historical broader/sequential test gates
are superseded by this spec's scoped tickets and minimum sufficient verification.

The stable filename is retained for existing links despite the broader title.
All sixteen tickets are approved for implementation. Execution follows their
real blockers, the multi-stage-orchestration plan/review gates, and any image-first
design gate. This packet records implementation authority, not completed work or
candidate/human acceptance.

The UI guidance informed progressive disclosure, accessible escape/navigation,
and stable image sizing, not a new theme. Browser image dimensions and responsive
hints follow [MDN's image element guidance](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/img).
Model image handling is provider-specific: [Claude's vision guidance](https://platform.claude.com/docs/en/build-with-claude/vision)
distinguishes resolution/token cost from compression/request latency and warns
about illegible text. Refresh the actual provider's rules at implementation time;
this spec deliberately hardcodes no universal image-token formula.
