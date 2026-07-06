# ADR-0008: Built once; no "designed-for-not-built" lane

**Status:** Accepted (2026-05-15)

## Context

During the rearchitecture grilling session, several capabilities surfaced as candidates for the "design now, ship later" treatment: inline-Latin-in-English segment detection, multi-engine OCR ensemble, cross-edition variant apparatus, advanced bounding-box scan mapping. The default assumption of phased software work is to schedule these as v2 / future work — keep the architectural slot open, fill the slot later.

The decision was: no v2 lane. Either the capability is in scope and built, or it is out of scope and not in the architecture.

## Decision

The rearchitecture is **built once**. The architecture is complete at launch. Every pipeline stage exists; every schema field has a producer that fills it and a consumer that uses it; every Reviewer adjudication path is wired up. No half-built modules. No "TODO: implement detector later."

Three categories of work are recognised:

1. **In scope (built at launch).** Foundational pieces: multi-source Reconcile, per-block provenance, the universal block schema, multi-language detection (Unicode script + lexicon + cld3), modernisation framework, two-output strategy, migration of all 688 existing records.
2. **Architecturally supported; quality grows over time.** Schema fields exist and have basic implementations from day one. Quality of individual components improves through replacement-in-place, not slot creation. Examples: Latin-phrase detection (basic lexicon ships at launch; grows as edge cases surface); modernisation rules (small initial ruleset; grows with experience); per-language OCR error models (start minimal; populate when problems arise).
3. **Out of scope (not in the architecture).** Cross-edition variant apparatus, our-own scholarly editions, facsimile reproduction, automated translation, on-demand cloud OCR as default. Anything in the non-goals list.

The dataset and quality grow over time; the architecture does not.

## Consequences

**Positive**
- No half-built features. New contributors do not encounter empty architectural slots with TODO comments.
- Quality improvements have a clean home — they replace existing implementations in their slots, not "fill in stubs."
- Scope discipline is enforced architecturally. A request to add a feature is either "this is in scope already" or "this is out of scope; add a new ADR if you want to change that."
- The rearchitecture has a real "done" state. It is not perpetually under construction.

**Negative**
- Upfront cost is higher. Phase 1 must ship more capability than a "minimal viable architecture" would.
- Some capabilities ship in basic form when richer versions would be possible with more time. The Latin-phrase detector ships with a curated initial list, not a comprehensive one.
- New capabilities require explicit architectural extension via a new ADR. Lightweight extension via "we always intended to add this slot" is unavailable.

## Alternatives considered

- **Conventional phased v1 / v2 / v3 with deferred capabilities.** Rejected. Deferred work rots; half-shipped features become permanent technical debt; the project's coherence suffers.
- **Built once for the core; "experimental modules" for extensions.** Rejected because an experimental module with no production timeline is just a v2 with different framing. Same problem.
- **Built once for the architecture; quality is explicitly continuous.** Accepted; this is the chosen framing. The architecture is the locked thing; quality grows within it.
