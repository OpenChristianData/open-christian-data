"""B9 family-independence measurement -> family-grouping map + policy version.

Wave-3 family-map readiness gate (arch D plan section 2 B9 row; lock section 3).
Consumes a bake-off sample of aligned positions (each carrying a gold reading and
the per-engine reading) and produces the family-grouping map for the active engine
set, tied to a matrix-policy version.

Independence is MEASURED, never assumed from "different software" (lock section 3):

  same-wrong-string by pair  -- fraction of gold-anchored positions where two
                                engines produce the SAME WRONG string. The
                                statistical heart of the dependence problem
                                (research R1 / section 5.2): correlated engines
                                share real-word errors, so a high same-wrong-string
                                rate means the pair is one family, not two votes.
  paired-disagreement by pair-- fraction of shared positions where the two engines
                                disagree at all (a gold-independent companion signal).
  gold-accuracy by engine    -- fraction of gold-anchored positions an engine reads
                                correctly.

Family grouping is two collapses: (1) the five ABBYY scan lineages (and any engines
sharing a declared engine_family) collapse to one block by declaration; (2) any two
declared-distinct families whose measured same-wrong-string clears the dependence
threshold collapse to one independence block. family_diversity_count is the number
of independence blocks AFTER both collapses.

family_map_readiness flips true ONLY when family_diversity_count >= 2 AND an
independent check (gold) anchored the measurement (lock section 3 conjuncts (i) and
(ii); the flag is conjunct (iii)). A map measuring fewer than two independent
families records a contingency and never flips: class-1 stays blocked, and the bar
is never relaxed to keep flowing (arch D section 4). The verdict on the REAL family
count is phase 2 (real vol_01 bake-off + real diagnostics); this module is the
measurement + map writer + readiness-flip logic, provable on fixtures.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from build.lib.atomic_io import write_json_atomic

# Same-wrong-string rate at or above which two declared-distinct families collapse
# to one independence block. The dependence threshold is [Needs local measurement]
# (research R1 evidence grade) -- this is an un-tuned v1 default whose tuning is
# gated by the first-diagnostics embargo, exactly as B6's alignment thresholds are.
DEFAULT_DEPENDENCE_THRESHOLD = 0.30

# Contingency vocabulary. These literals are validated against family-map-v1's
# enums by test_family_independence (the parser-schema-enums pattern); they are NOT
# a hardcoded frozenset mirror of the schema enum.
_CONTINGENCY_STATUS_FEWER_THAN_TWO = "fewer_than_two_independent_families"
_CONTINGENCY_ACTION_CALAMARI = "calamari_into_bakeoff"

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "v1" / "family-map-v1.schema.json"
FAMILY_MAP_SUBPATH = Path("reports") / "family_map"


@dataclass
class AlignedPosition:
    """One aligned bake-off position.

    gold is the independent-check reading (or None when no gold anchors this
    position -- excluded from same-wrong-string and gold-accuracy, which both need
    a known-correct string). engine_tokens maps engine_id -> the reading that
    engine produced at this position.
    """

    gold: str | None
    engine_tokens: Mapping[str, str] = field(default_factory=dict)


def _pair_key(engine_a: str, engine_b: str) -> str:
    low, high = sorted((engine_a, engine_b))
    return f"{low}__{high}"


# --------------------------------------------------------------------------- #
# Pure per-pair / per-engine measurements.
# --------------------------------------------------------------------------- #


def same_wrong_string_by_pair(positions: Sequence[AlignedPosition]) -> dict[str, float]:
    """Per engine pair, the fraction of gold-anchored shared positions where both
    engines produced the SAME WRONG string (equal to each other, unequal to gold)."""
    numerator: dict[str, int] = {}
    denominator: dict[str, int] = {}
    for position in positions:
        if position.gold is None:
            continue
        engines = sorted(position.engine_tokens)
        for i in range(len(engines)):
            for j in range(i + 1, len(engines)):
                engine_a, engine_b = engines[i], engines[j]
                key = _pair_key(engine_a, engine_b)
                denominator[key] = denominator.get(key, 0) + 1
                token_a = position.engine_tokens[engine_a]
                token_b = position.engine_tokens[engine_b]
                if token_a == token_b and token_a != position.gold:
                    numerator[key] = numerator.get(key, 0) + 1
    return {key: numerator.get(key, 0) / denominator[key] for key in sorted(denominator)}


def paired_disagreement_by_pair(positions: Sequence[AlignedPosition]) -> dict[str, float]:
    """Per engine pair, the fraction of shared positions where the two engines
    disagree at all (gold-independent)."""
    numerator: dict[str, int] = {}
    denominator: dict[str, int] = {}
    for position in positions:
        engines = sorted(position.engine_tokens)
        for i in range(len(engines)):
            for j in range(i + 1, len(engines)):
                engine_a, engine_b = engines[i], engines[j]
                key = _pair_key(engine_a, engine_b)
                denominator[key] = denominator.get(key, 0) + 1
                if position.engine_tokens[engine_a] != position.engine_tokens[engine_b]:
                    numerator[key] = numerator.get(key, 0) + 1
    return {key: numerator.get(key, 0) / denominator[key] for key in sorted(denominator)}


def gold_accuracy_by_engine(positions: Sequence[AlignedPosition]) -> dict[str, float]:
    """Per engine, the fraction of gold-anchored positions it read correctly."""
    numerator: dict[str, int] = {}
    denominator: dict[str, int] = {}
    for position in positions:
        if position.gold is None:
            continue
        for engine_id, token in position.engine_tokens.items():
            denominator[engine_id] = denominator.get(engine_id, 0) + 1
            if token == position.gold:
                numerator[engine_id] = numerator.get(engine_id, 0) + 1
    return {engine: numerator.get(engine, 0) / denominator[engine] for engine in sorted(denominator)}


# --------------------------------------------------------------------------- #
# Family grouping -- declared-family collapse + measured-dependence collapse.
# --------------------------------------------------------------------------- #


def _find(parent: dict[str, str], node: str) -> str:
    root = node
    while parent[root] != root:
        root = parent[root]
    # path compression
    while parent[node] != root:
        parent[node], node = root, parent[node]
    return root


def _union(parent: dict[str, str], a: str, b: str) -> None:
    root_a, root_b = _find(parent, a), _find(parent, b)
    if root_a != root_b:
        # deterministic: the lexicographically smaller root wins.
        low, high = sorted((root_a, root_b))
        parent[high] = low


def group_families(
    engine_families: Mapping[str, str],
    same_wrong_string_rates: Mapping[str, float],
    *,
    dependence_threshold: float = DEFAULT_DEPENDENCE_THRESHOLD,
) -> list[dict]:
    """Collapse engines into independence blocks.

    (1) Engines sharing a declared engine_family collapse first (the five ABBYY
        lineages -> one block). (2) Any two engines whose measured same-wrong-string
        rate clears the threshold collapse, even across declared families -- so
        nominal independence is never assumed without measurement.
    """
    engines = sorted(engine_families)
    parent = {engine: engine for engine in engines}

    # (1) declared-family collapse.
    by_family: dict[str, list[str]] = {}
    for engine in engines:
        by_family.setdefault(engine_families[engine], []).append(engine)
    for members in by_family.values():
        for other in members[1:]:
            _union(parent, members[0], other)

    # (2) measured-dependence collapse.
    for i in range(len(engines)):
        for j in range(i + 1, len(engines)):
            key = _pair_key(engines[i], engines[j])
            if same_wrong_string_rates.get(key, 0.0) >= dependence_threshold:
                _union(parent, engines[i], engines[j])

    blocks_by_root: dict[str, list[str]] = {}
    for engine in engines:
        blocks_by_root.setdefault(_find(parent, engine), []).append(engine)

    ordered = sorted(blocks_by_root.values(), key=lambda group: sorted(group)[0])
    blocks: list[dict] = []
    for index, group in enumerate(ordered, start=1):
        engine_ids = sorted(group)
        declared_families = sorted({engine_families[engine] for engine in engine_ids})
        blocks.append(
            {
                "block_id": f"family-block-{index}",
                "engine_ids": engine_ids,
                "declared_families": declared_families,
                # more than one declared family in one block can only happen via the
                # measured-dependence collapse (declared collapse merges same-family).
                "merged_by_dependence": len(declared_families) > 1,
            }
        )
    return blocks


def family_diversity_count(blocks: Sequence[Mapping]) -> int:
    """Number of independent families (independence blocks)."""
    return len(blocks)


def evaluate_readiness(*, family_diversity_count: int, independent_check_present: bool) -> bool:
    """The readiness flip (lock section 3): true ONLY when at least two independent
    families were measured AND an independent check anchored the measurement."""
    return family_diversity_count >= 2 and independent_check_present


# --------------------------------------------------------------------------- #
# Family-map builder + writer.
# --------------------------------------------------------------------------- #


def build_family_map(
    *,
    engine_families: Mapping[str, str],
    positions: Sequence[AlignedPosition],
    policy_version: str,
    input_sample_id: str,
    effective_date: str,
    dependence_threshold: float = DEFAULT_DEPENDENCE_THRESHOLD,
) -> dict:
    """Measure independence on the bake-off positions and assemble the family map.

    Fails closed (REL-02) on an empty engine set or no positions -- a map measured
    on nothing is a precondition error, not a "not ready" result.
    """
    if not engine_families:
        raise ValueError("cannot build a family map for an empty engine set")
    if not positions:
        raise ValueError("cannot build a family map with no measured positions")

    # "measured, never assumed" (lock section 3): only engines that actually appear
    # in the measured positions count as families. A declared-but-absent engine
    # produced no evidence, so it cannot be one of the independent families that
    # lift the gate (Codex B9 review attack 5). Drop it from the grouping and record
    # it so the omission is visible, never silent.
    present_engines = sorted({engine for position in positions for engine in position.engine_tokens})
    undeclared = [engine for engine in present_engines if engine not in engine_families]
    if undeclared:
        raise ValueError(
            f"measured engines have no declared family: {undeclared!r}"
        )
    measured_families = {engine: engine_families[engine] for engine in present_engines}
    unmeasured_declared_engines = sorted(set(engine_families) - set(present_engines))

    same_wrong = same_wrong_string_by_pair(positions)
    disagreement = paired_disagreement_by_pair(positions)
    gold_accuracy = gold_accuracy_by_engine(positions)
    gold_position_count = sum(1 for position in positions if position.gold is not None)
    independent_check_present = gold_position_count > 0

    blocks = group_families(
        measured_families, same_wrong, dependence_threshold=dependence_threshold
    )
    diversity = family_diversity_count(blocks)
    readiness = evaluate_readiness(
        family_diversity_count=diversity,
        independent_check_present=independent_check_present,
    )

    family_map: dict = {
        "schema_version": "family-map-v1",
        "policy_version": policy_version,
        "input_sample_id": input_sample_id,
        "effective_date": effective_date,
        "engine_set": present_engines,
        "family_groups": blocks,
        "family_diversity_count": diversity,
        "independent_check_present": independent_check_present,
        "family_map_readiness": readiness,
        "measurements": {
            "same_wrong_string_by_pair": same_wrong,
            "paired_disagreement_by_pair": disagreement,
            "gold_accuracy_by_engine": gold_accuracy,
            "gold_position_count": gold_position_count,
            "dependence_threshold": dependence_threshold,
        },
    }

    if unmeasured_declared_engines:
        family_map["unmeasured_declared_engines"] = unmeasured_declared_engines

    if diversity < 2:
        # < 2-independent-family contingency (arch D section 4): class-1 stays
        # blocked; first remedy is Calamari into the bake-off, then a re-measure.
        # The strict bar is never relaxed to keep flowing.
        family_map["contingency"] = {
            "status": _CONTINGENCY_STATUS_FEWER_THAN_TWO,
            "class1_blocked": True,
            "recommended_action": _CONTINGENCY_ACTION_CALAMARI,
            "detail": (
                "Fewer than two independent families measured. Bring Calamari into "
                "the bake-off and re-measure before any corpus scaling; if still "
                "< 2, the weak-evidence table carries everything and the strict bar "
                "becomes a v2 revisit trigger. Class-1 training stays blocked."
            ),
        }

    return family_map


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in value)


def _assert_gate_invariants(family_map: Mapping) -> None:
    """Defence in depth before persisting a gate-critical artifact (Codex B9 review
    attack 1): JSON Schema cannot assert family_diversity_count == len(family_groups)
    or the readiness conjuncts, so a hand-built or future-caller payload could
    otherwise persist a contradiction. Enforce the invariants here, fail-closed."""
    groups = family_map.get("family_groups", [])
    count = family_map.get("family_diversity_count")
    if count != len(groups):
        raise ValueError(
            f"family_diversity_count {count} != len(family_groups) {len(groups)}"
        )
    readiness = family_map.get("family_map_readiness")
    if readiness and (count is None or count < 2):
        raise ValueError("family_map_readiness is true with fewer than two families")
    if readiness and not family_map.get("independent_check_present"):
        raise ValueError("family_map_readiness is true without an independent check")


def write_family_map(reports_root: Path | str, family_map: Mapping) -> Path:
    """Write the family map to reports/family_map/<input_sample_id>_family_map.json,
    validating it against family-map-v1 atomically (reports/ is gitignored)."""
    _assert_gate_invariants(family_map)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report_dir = Path(reports_root) / FAMILY_MAP_SUBPATH
    name = f"{_safe_name(family_map['input_sample_id'])}_family_map.json"
    out_path = report_dir / name
    write_json_atomic(out_path, family_map, schema)
    return out_path
