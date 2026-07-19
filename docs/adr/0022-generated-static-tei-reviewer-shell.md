# ADR-0022: Generated static shell for the TEI reviewer

**Status:** Accepted (2026-07-06). Follows ADR-0020.

## Context

ADR-0020 reopened the reviewer UI shell decision after the surface grew to three modes and eight queues.
The binding criteria were:

- the reviewer must stay `file://`-openable for routine use;
- dependencies must be light, pinned, and vendored;
- the shell must carry Word, Block, and Page modes over named queues without brittle DOM state;
- the review-patch download plus CLI apply contract must stay unchanged;
- browser code must not derive canonical token identity.

Batch 06 also changed the practical input shape. The UI now renders materialised TEI plus WCT geometry
and emits review decisions that `apply_review_patch.py` turns into decision-event ledger appends before
re-materialising TEI.

## Decision

Use a **generated static HTML shell with vanilla JavaScript modules** for the v1 TEI reviewer.

`build/tools/render_tei_reviewer_ui.py` reads a page's WCT, decision ledger, and IA manifest, materialises
the TEI, builds a page-scoped browser model, and writes one local HTML file. That file embeds the page
model and loads only vendored local scripts:

- CETEIcean from `viewer/vendor/CETEI.js`;
- OpenSeadragon 6.0.2 from `viewer/vendor/openseadragon/`;
- `ReviewPatchSink` from `build/lib/review_ui_js/decision_sink.js`;
- the reviewer shell from `build/lib/review_ui_js/tei_reviewer.js`.

The browser receives token IDs, XML IDs, candidate metadata, queue routes, and bbox geometry from the
generated model. It records decisions only. The CLI remains the single writer.

## Consequences

- Routine review stays a no-install local file workflow: generate HTML, open it from disk, download a
  patch, run the CLI apply step.
- State stays explicit and page-scoped. That is enough for Word, Block, Page, and the eight named queues
  without adopting a framework or build pipeline.
- The shell can be served over HTTP for testing, but that is not required for review.
- Block and Page modes currently use WCT geometry contracts. Their missing producers are visible in the
  model and UI instead of being implied by placeholder data.
- The older ADR-0012 affordance files stay with the older `render_review_html.py` surface. The TEI
  reviewer shell uses `ReviewPatchSink` and `tei_reviewer.js`; no framework bundle is introduced.

## Alternatives considered

- **Minimal reactive framework.** Rejected for v1. It would still need a generated data model for
  `file://` reliability, and the remaining state does not justify vendoring another runtime.
- **Small SPA with build output.** Rejected. A build step is acceptable under ADR-0020, but it does not
  buy enough for a page-scoped local reviewer and would add install/build drift.
- **Hand-authored static page that fetches WCT/TEI files.** Rejected. Browser `file://` fetch behaviour is
  inconsistent and already documented as a failure mode in `viewer/index.html`.
