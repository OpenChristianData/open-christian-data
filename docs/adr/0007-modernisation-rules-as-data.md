# ADR-0007: Modernisation rules as data files

**Status:** Accepted (2026-05-15); amended 2026-05-16 (canonical `test_cases` field name, shape, and coverage requirements added during reconciliation walkthrough verification).

## Context

The Modernise stage applies transformations to the original reconciled text to produce a modernised sibling: `hath → has`, long `ſ → s`, archaic spellings, etc. The implementation question is whether these rules are:

1. **Code** — Python functions per rule, registered with the modernisation engine.
2. **Data** — declarative entries in a YAML/JSON file per language, loaded by a small engine.

The choice shapes how contributors propose new rules, how the audit trail records which rule fired, and how easy it is to inspect or disable rules without code changes.

## Decision

Modernisation rules live in **versioned per-language YAML files** at `build/lib/modernisation/rulesets/<lang>.yaml`. Each rule is a declarative entry with `rule_id`, `description`, `pattern`, `replacement`, `exceptions`, `enabled`, `version_added`, `test_cases`. A small engine (~50 lines of Python) loads the ruleset and applies enabled rules to each block.

### Test cases — canonical field shape

Every rule carries an inline `test_cases` array. Shape: `[{input, expected, note?}]`. Semantics: `expected == input` means "the rule does not fire on this input" (negative case); `expected != input` means "the rule fires and produces `expected`" (positive case). `note` is optional free text explaining what the case proves.

Coverage requirements:

- **All rules:** at least one positive `test_cases` entry (the rule fires and produces the documented behaviour).
- **Rules with an `exceptions` list:** one negative case per exception (the rule does not fire on the exception). Without this, the exceptions list rots silently when the pattern is refactored.
- **Lookup-table rules** (`kind: lookup`): one case per `table` row — every mapping is independently verified.
- **`enabled: false` rules:** test cases still required. A disabled rule may be flipped on later; tests prove the behaviour the flip would produce.

Editorial modernisations (`rule_id: null`, `kind: editorial`) live in the per-block `modernisations` array, not the ruleset YAML, and are out of scope for `test_cases` (they are not rules).

Per-block modernisation records reference rules by stable `rule_id` (e.g. `en.archaic_verb_eth_to_s`). The ruleset has a semantic version per language (e.g. `en@1.0.0`); each modernised record records the ruleset version that produced it.

Editorial modernisations (the ~20% of judgement calls that do not fit a rule) live in the same per-block `modernisations` array with `rule_id: null` and a `kind: editorial` flag plus rationale. Same audit trail; same shape.

## Consequences

**Positive**
- Anyone can read the ruleset YAML without Python knowledge. Modernisation strategy is visible content, not buried logic.
- Adding, disabling, or modifying a rule does not require code changes — just a YAML edit and a ruleset-version bump.
- Diffs are readable. A PR that changes `en.yaml` is a content diff, not a code diff.
- `rule_id` is a stable identifier. Code reorganisations do not rename it; a modernised record's audit trail always resolves to the same logical rule.
- Engine and rules are separately testable. The engine is one small piece of code; rules are content tested against expected outputs.
- Contributors who want to propose new rules can do so without touching Python — lowers the contribution barrier.

**Negative**
- Pattern syntax is regex (or whatever the engine supports), which has its own correctness traps. We lose the type-safety net that compiled Python would provide. Mitigation: the `test_cases` coverage requirement above (positive per rule, negative per exception, one per lookup-table row).
- Engine constraints become rule-author constraints. If a rule needs logic the engine does not support (lookarounds, multi-token context, conditional replacement), the rule cannot be expressed in YAML alone. We accept this; the cases that need real code (`<1%` likely) escalate to editorial modernisations.
- One more file format in the project. YAML loading and validation are infrastructure to maintain.

## Alternatives considered

- **Rules as code (Python functions).** Rejected because rules are content, not logic. Treating them as code obscures them behind programming, raises the contribution barrier, and couples rules to engine implementation.
- **Rules as code with a registry pattern** (each rule is a decorated Python function the engine discovers). Rejected for the same reason; the registry decoration is bookkeeping that adds no value over a YAML entry.
- **Rules in JSON instead of YAML.** Considered. YAML wins on readability (comments, multi-line strings, less punctuation). JSON wins on tooling. The audit trail value of readable rules tips toward YAML.
- **Rules expressed as the engine's input but also generated from code at build time.** Rejected as unnecessary indirection. The data file IS the source of truth; no generator needed.
