# LESSONS — Open Christian Data

Dated entries from sessions where a reusable pattern emerged but didn't warrant a full skill.
Most recent first.

---

## 2026-06-11 — Cross-volume comparison as isolation test for data anomalies

**Pattern:** When the header verifier (or any content-vs-label check) flags an anomaly in one volume, pick a structurally similar volume and run the same check before concluding the tool is broken or the rebuild introduced a class-level bug. If the similar volume passes cleanly, the problem is volume-specific. If it also fails, the tool or rebuild logic is the suspect.

**Trigger:** Any "is this a tool bug or an isolated data defect?" question when multiple volumes share a structural profile (same leaf-offset formula, same rebuild path, same manifest schema). One failing vol, one clean vol = isolated defect; both fail = class-level.

**Why it mattered:** Vol_01 showed delta=+2 on pp94-95 (running-header number 2 ahead of image label). Vol_08 has an identical gap structure (primary scan physically skipped two pages; alternate scan fills them). Running the verifier on vol_08 — one 90-second check — gave a 1.0 match rate, ruling out a systematic rebuild tool bug and confirming the defect was vol_01-specific. Without this, debugging would have chased the rebuild tool rather than the vol_01 scandata mislabeling.

**Fingerprint for FTS5:** "cross-volume comparison", "comparison volume", "isolation test", "similar vol passes cleanly", "class-level vs isolated".


---

## 2026-05-20 — Multi-reviewer audit divergence: read the artifact before accepting a negative

**Pattern:** When two independent review passes disagree MISSING vs SHIPPED (or any existence/quality contradiction), read the actual file before accepting either verdict. Classify the root cause specifically:
- **Methodology threshold** — one reviewer applies a stricter "substantive" cutoff (e.g. Codex treating a 3-line intentional stub as non-substantive)
- **Gitignored artifact** — `git ls-files` misses files that are intentionally untracked (runtime output dirs, session artifacts)
- **Renamed item** — a function or file was refactored; coverage is equivalent but the name no longer matches

**Why it mattered:** Codex's A5 pass produced 7 MISSING verdicts. Accepting them at face value would have propagated 7 false defects into A7's carry-forward table. File content reads resolved all 7 in minutes.

**Meta principle:** This is a specific application of `feedback_primary_source_first.md` — the primary artifact (the actual file, the actual function name) overrules any reviewer's classification of it. In a multi-reviewer context the artifact is the tiebreaker, not the reviewer with higher apparent authority.

**Fingerprint for FTS5:** "MISSING vs SHIPPED", "false negative", "methodology threshold", "Codex pass", "resolver".

---

## 2026-06-01 — Synthetic-green TDD is necessary but not sufficient; run a real-data end-to-end pass before "done"

**Pattern:** After a pipeline tool passes synthetic-fixture TDD, run it through the full real-data chain before declaring it done. Synthetic fixtures validate your mental model of the data, not the data itself.

**Why it mattered:** Across two consecutive sessions the first real-data run surfaced bugs every green unit test missed — the four build_wct bugs (NW float-`==` crash, boxless-token drop, bbox corners-vs-WH, line-block zone granularity), and this session: the aligner's agreement-vs-distance design flaw (visual proximity treated as textual agreement — fixtures didn't catch it because they used clean distinct words), a cross-stage mismatch (CCEL proposal was page 1 while the WCT was page 10), and emergent alignment drift that only appears at real scale.

**Meta principle:** Three bug classes only surface on real input — design flaws (a wrong abstraction the fixtures happened to satisfy), cross-component mismatches (stage A's output keyed differently than stage B expects), and emergent noise (un-tuned behaviour that's invisible on tiny inputs). This extends TEST-13 (fixtures from real files) and TEST-01 (run against the real dataset): even real-derived *unit* fixtures don't substitute for a real *end-to-end* integration run.

**Fingerprint for FTS5:** "synthetic fixtures pass real data fails", "agreement vs distance", "end-to-end integration bug", "design flaw not caught by unit tests".

---


---

## 2026-06-03 — Adversarial parser audit: 6-checkpoint structure produces systematic coverage

**Pattern:** When auditing a set of data parsers for silent failures and correctness bugs, use this checkpoint sequence: (1) attack surface map — categorise every parser by fragility class (XML/ThML, plain-text OCR, HTML scrape, TOML, JSON, normaliser); (2) silent-failure attacks — empty sections, orphan-filter gaps, word_count:0 on live content, source-evidence weakness; (3) schema-validity attacks — vacuous-pass cases, enum drift between hardcoded values and schema; (4) content-accuracy attacks — heading-regex misses, reroute edge cases, section detection gaps; (5) output sampling — read ≥5 actual data/ files and spot-check against the logic that produced them; (6) all findings triaged — every finding gets REAL or FALSE-POSITIVE with specific file:line evidence and severity.

**Why it mattered:** Running all 6 checkpoints across 9 parsers in one session produced 11 REAL findings and 3 FALSE-POSITIVE discharges. The most productive checkpoints were silent-failure attacks and output sampling — reading actual data/ files revealed the church_fathers source_hash bug (checkpoint 5) and confirmed the Burroughs Roman numeral false-alarm (checkpoint 5). Without checkpoint 5, the FALSE-POSITIVEs would have become wasted fix work.

**Fingerprint for FTS5:** "adversarial parser audit", "attack surface map", "silent failure attack", "REAL FALSE-POSITIVE verdict", "output sampling parser".

---

## 2026-06-03 — Windows Modern Standby silently kills long-running processes

**Pattern:** When a long-running process stops unexpectedly on Windows with no error in logs and no crash record, check for a Modern Standby sleep cycle before assuming a code bug. The OS suspends and often kills CPU-intensive subprocesses during standby without logging anything at the process level.

**Diagnostic:** `wevtutil qe System /c:20 /rd:true /f:text "/q:*[System[Provider[@Name='Microsoft-Windows-Kernel-Power']]]"` — look for EventID 506 (enter standby) and EventID 507 (exit standby). Timestamps are UTC. Cross-reference the entry event against the last file the process wrote.

**Why it mattered:** The Kraken OCR pipeline ran 4 times today and stopped each time. Final run (18:48 AEST) stopped at 18:54 with no error. EventID 506 at 19:10 AEST confirmed the PC went to sleep 16 minutes later — the subprocess was suspended, Kraken's batch process was killed during standby transition, and no new output was written after the wake at 22:22.

**Fix for unattended long jobs:** `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` via ctypes at process start, `atexit` to release. This prevents idle sleep for the process lifetime without requiring global `powercfg` changes. Now wired into `run_ocr_pipeline.py`.

**Fingerprint for FTS5:** "Modern Standby", "wevtutil Kernel-Power", "EventID 506 507", "SetThreadExecutionState", "process stopped no error sleep".
