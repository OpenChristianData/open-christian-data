# ADR-0004: Single public repo for code, schemas, dataset, and review machinery

**Status:** Accepted (2026-05-15, rewritten 2026-05-17)

## Context

The build pipeline, dataset records, schemas, audit log, and Reviewer machinery can live in a single repo or be split — typically into a development repo (in-progress editorial state, intermediate research, working notes) and a dataset-only repo for downstream consumers.

The trade-off is one source of truth and contributor velocity versus the operational separation a two-repo structure would give. Splitting forces a sync-publish step on every change, doubles the maintenance surface, and dilutes social proof across two repos. A single repo keeps the full build pipeline visible — anyone can re-run it from a clean clone — at the cost of exposing in-progress editorial files alongside the published dataset.

## Decision

Keep everything in one public repo: `OpenChristianData/open-christian-data` on GitHub.

The repo holds the build pipeline, schemas, dataset records, audit log, change log, retry queue, Reviewer machinery, tests, and project documentation. The HuggingFace dataset (`openchristiandata/open-christian-data`) is the consumer-facing surface; this GitHub repo is the upstream that produces it.

Working-state files that should not appear in the index — local scans, per-rendering parses, draft reports, raw source caches, `LAST_SESSION_*.md`, `plans/`, `prompts/`, exported HuggingFace artefacts — are kept out via `.gitignore`.

## Consequences

**Positive**
- One source of truth for the build pipeline, schemas, dataset records, and audit machinery.
- The full pipeline is reproducible from a clean clone. A reader can verify the dataset by re-running it.
- Stars, forks, issues, and PRs concentrate on one surface.
- No sync-publish flow to maintain; no cross-repo drift risk.

**Negative**
- Detailed editorial work (`review/state/`, `review/corrections/`, `review/audit.jsonl`) is visible. A reader can see specific reconciliation decisions and Reviewer rationale.
- A future hard separation, if ever warranted, would be a real workstream. The cost is accepted in exchange for contributor accessibility today.

## Alternatives considered

- **Private development repo + public dataset-only repo.** Rejected. It forfeits contributor visibility into the build pipeline and adds permanent sync-publish overhead.
- **Private editorial state, public toolchain.** Rejected. The maintenance overhead (two repos, sync-publish flow) outweighs the benefit; working state can be kept out of the index via `.gitignore`.
- **No structural decision; track ad hoc.** Rejected. The editorial-thinking files and exploratory research warranted an explicit policy — either separate them out of the repo or document the inclusion explicitly.
