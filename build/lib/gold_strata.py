"""Shared strata contract for B7 gold sample selection."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from numbers import Real
import re
from typing import Any, Iterable, Mapping, Sequence

from build.lib import historical_lexicon

DOMINANT_FAILURE_MIN = 20
DOMINANT_FAILURE_MAX = 50
MIN_PER_OBSERVED_VALUE = 2
CALIBRATION_MIN = 500
CALIBRATION_MAX = 1000

COVERAGE_COVERED = "covered"
COVERAGE_EMPTY_REQUIRED_UNCOVERED = "empty_required_value_uncovered"
COVERAGE_NO_SOURCE_DATA = "no_source_data"


@dataclass(frozen=True)
class StrataDimension:
    name: str
    source: str
    availability: str
    buckets: tuple[str, ...]
    hard_required: bool


@dataclass(frozen=True)
class PageStrataRecord:
    page_path: str
    strata: Mapping[str, Any]


@dataclass(frozen=True)
class SampleStratum:
    stratum_key: dict[str, Any]
    target_count: int
    actual_count: int
    selected_pages: tuple[str, ...]
    coverage_flag: str


@dataclass(frozen=True)
class SampleResult:
    selected_pages: tuple[str, ...]
    strata: tuple[SampleStratum, ...]


# These proxies all come from S1 sidecars because the gold sampler must run
# before Phase 1 adjudication exists. They are risk-routing signals, not verdicts.
STRATA_DIMENSIONS: tuple[StrataDimension, ...] = (
    StrataDimension(
        "zone_type",
        "sidecar-page-v1 blocks[].block_type",
        "derived_at_s1",
        ("text", "diagnostic"),
        True,
    ),
    StrataDimension(
        "script",
        "observed_word.source_raw via Unicode block scan (Greek/Hebrew/Latin ranges)",
        "derived_at_s1",
        ("latin", "greek", "hebrew", "mixed", "other"),
        True,
    ),
    StrataDimension(
        "scan_quality",
        "observed_word.confidence distribution proxy",
        "derived_at_s1",
        ("high", "medium", "low"),
        True,
    ),
    StrataDimension(
        "engine_coverage",
        "count of engine families present for the page",
        "derived_at_s1",
        ("single", "pair", "multi"),
        True,
    ),
    StrataDimension(
        "confidence_bucket",
        "page aggregate of observed_word.confidence",
        "derived_at_s1",
        ("high", "medium", "low", "null_conf"),
        True,
    ),
    StrataDimension(
        "dictionary_pass",
        "historical_lexicon plus minimal common-word proxy",
        "derived_at_s1",
        ("pass", "fail", "mixed"),
        True,
    ),
    StrataDimension(
        "bbox_agreement",
        "cross-engine block bbox intersection-over-union proxy",
        "derived_at_s1",
        ("high", "medium", "low", "single_engine"),
        True,
    ),
    StrataDimension(
        "consensus_disagreement_pattern",
        "S1 page-level exact-match-rate proxy across engines",
        "derived_at_s1",
        ("agree", "minor_disagree", "major_disagree", "single"),
        False,
    ),
    StrataDimension(
        "engine_family_set",
        "literal set of engine families present for the page",
        "derived_at_s1",
        (),
        False,
    ),
)
STRATA_CONTRACT = STRATA_DIMENSIONS
HARD_REQUIRED_DIMENSIONS = tuple(dimension.name for dimension in STRATA_DIMENSIONS if dimension.hard_required)

_LATIN_RE = re.compile(r"[A-Za-zÀ-ɏ]")
_TOKEN_RE = re.compile(r"[\wÀ-ɏ]+", re.UNICODE)

# The historical lexicon is a variant detector, not a full dictionary. This
# small list prevents routine theological English from being misrouted as risk.
_MINIMAL_DICTIONARY = frozenset(
    {
        "and",
        "christ",
        "church",
        "doctrine",
        "faith",
        "god",
        "grace",
        "holy",
        "jesus",
        "lord",
        "man",
        "peace",
        "spirit",
        "truth",
        "word",
    }
)

_RISKY_VALUES: Mapping[str, frozenset[str]] = {
    "zone_type": frozenset({"diagnostic"}),
    "script": frozenset({"greek", "hebrew", "mixed", "other"}),
    "scan_quality": frozenset({"low"}),
    "confidence_bucket": frozenset({"low", "null_conf"}),
    "dictionary_pass": frozenset({"fail", "mixed"}),
    "bbox_agreement": frozenset({"low"}),
    "consensus_disagreement_pattern": frozenset({"major_disagree"}),
}


def _all_blocks(page: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    blocks = page.get("blocks", [])
    if isinstance(blocks, list):
        for block in blocks:
            if isinstance(block, Mapping):
                yield block


def _all_words(page: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for block in _all_blocks(page):
        lines = block.get("lines", [])
        if not isinstance(lines, list):
            continue
        for line in lines:
            if not isinstance(line, Mapping):
                continue
            words = line.get("words", [])
            if not isinstance(words, list):
                continue
            for word in words:
                if isinstance(word, Mapping):
                    yield word


def _word_texts(pages: Iterable[Mapping[str, Any]]) -> list[str]:
    texts: list[str] = []
    for page in pages:
        for word in _all_words(page):
            source_raw = word.get("source_raw")
            if isinstance(source_raw, str) and source_raw:
                texts.append(source_raw)
    return texts


def _page_text(page: Mapping[str, Any]) -> str:
    texts: list[str] = []
    for block in _all_blocks(page):
        lines = block.get("lines", [])
        if not isinstance(lines, list):
            continue
        for line in lines:
            if isinstance(line, Mapping) and isinstance(line.get("source_raw"), str):
                texts.append(str(line["source_raw"]))
    if texts:
        return " ".join(texts)
    return " ".join(_word_texts([page]))


def _normalized_page_text(page: Mapping[str, Any]) -> str:
    return re.sub(r"\s+", " ", _page_text(page)).strip().casefold()


def _confidence_values(pages: Iterable[Mapping[str, Any]]) -> list[float]:
    values: list[float] = []
    for page in pages:
        for word in _all_words(page):
            confidence = word.get("confidence")
            if isinstance(confidence, Real) and not isinstance(confidence, bool):
                values.append(float(confidence))
    return values


def _confidence_bucket(values: Sequence[float]) -> str:
    if not values:
        return "null_conf"
    average = sum(values) / len(values)
    if average >= 85.0:
        return "high"
    if average >= 60.0:
        return "medium"
    return "low"


def _scan_quality(values: Sequence[float]) -> str:
    if not values:
        return "low"
    average = sum(values) / len(values)
    low_share = len([value for value in values if value < 60.0]) / len(values)
    if average >= 85.0 and low_share == 0:
        return "high"
    if average >= 60.0 and low_share < 0.5:
        return "medium"
    return "low"


def _script_for_token(token: str) -> str:
    scripts: set[str] = set()
    for char in token:
        codepoint = ord(char)
        if 0x0370 <= codepoint <= 0x03FF or 0x1F00 <= codepoint <= 0x1FFF:
            scripts.add("greek")
        elif 0x0590 <= codepoint <= 0x05FF:
            scripts.add("hebrew")
        elif _LATIN_RE.match(char):
            scripts.add("latin")
    if len(scripts) > 1:
        return "mixed"
    if scripts:
        return next(iter(scripts))
    return "other"


def _script_bucket(words: Sequence[str]) -> str:
    # Script is derived purely from Unicode code-point ranges per token; this is a
    # routing signal, not a verdict. The richer lang_classifier (block-level, prose-
    # oriented) does not resolve per-token script for short OCR fragments, so it is
    # not used here.
    token_scripts = {_script_for_token(token) for token in words if token}
    significant = token_scripts.difference({"other"})
    if len(significant) > 1:
        return "mixed"
    if len(significant) == 1:
        return next(iter(significant))
    if "other" in token_scripts:
        return "other"
    return "other"


def _dictionary_pass(words: Sequence[str]) -> str:
    if not words:
        return "fail"
    joined = " ".join(words)
    historical_surfaces = {
        match.surface.casefold()
        for match in historical_lexicon.scan_historical_variants(joined)
    }
    outcomes: list[bool] = []
    for token in _TOKEN_RE.findall(joined):
        if _script_for_token(token) not in {"latin", "mixed"}:
            outcomes.append(False)
            continue
        lowered = token.casefold()
        outcomes.append(lowered in _MINIMAL_DICTIONARY or lowered in historical_surfaces)
    if not outcomes:
        return "fail"
    if all(outcomes):
        return "pass"
    if any(outcomes):
        return "mixed"
    return "fail"


def _zone_type(pages: Iterable[Mapping[str, Any]]) -> str:
    block_types = {
        str(block.get("block_type"))
        for page in pages
        for block in _all_blocks(page)
    }
    if "diagnostic" in block_types:
        return "diagnostic"
    return "text"


def _engine_coverage(engine_count: int) -> str:
    if engine_count <= 1:
        return "single"
    if engine_count == 2:
        return "pair"
    return "multi"


def _block_bboxes(page: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    bboxes: list[Mapping[str, Any]] = []
    for block in _all_blocks(page):
        bbox = block.get("bbox_native")
        if isinstance(bbox, Mapping):
            bboxes.append(bbox)
    return bboxes


def _bbox_iou(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    try:
        lx = float(left["x"])
        ly = float(left["y"])
        lw = float(left["w"])
        lh = float(left["h"])
        rx = float(right["x"])
        ry = float(right["y"])
        rw = float(right["w"])
        rh = float(right["h"])
    except (KeyError, TypeError, ValueError):
        return 0.0
    if lw <= 0 or lh <= 0 or rw <= 0 or rh <= 0:
        return 0.0
    inter_left = max(lx, rx)
    inter_top = max(ly, ry)
    inter_right = min(lx + lw, rx + rw)
    inter_bottom = min(ly + lh, ry + rh)
    if inter_right <= inter_left or inter_bottom <= inter_top:
        return 0.0
    intersection = (inter_right - inter_left) * (inter_bottom - inter_top)
    union = lw * lh + rw * rh - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _bbox_agreement(pages_by_engine: Mapping[str, Mapping[str, Any]]) -> str:
    if len(pages_by_engine) <= 1:
        return "single_engine"
    primary_boxes = [
        bboxes[0]
        for _engine, page in sorted(pages_by_engine.items())
        for bboxes in [_block_bboxes(page)]
        if bboxes
    ]
    if len(primary_boxes) < 2:
        return "low"
    scores: list[float] = []
    for left_index, left in enumerate(primary_boxes):
        for right in primary_boxes[left_index + 1 :]:
            scores.append(_bbox_iou(left, right))
    average = sum(scores) / len(scores) if scores else 0.0
    if average >= 0.80:
        return "high"
    if average >= 0.30:
        return "medium"
    return "low"


def _consensus_pattern(pages_by_engine: Mapping[str, Mapping[str, Any]]) -> str:
    if len(pages_by_engine) <= 1:
        return "single"
    texts = [_normalized_page_text(page) for _engine, page in sorted(pages_by_engine.items())]
    if len(set(texts)) == 1:
        return "agree"
    most_common = Counter(texts).most_common(1)[0][1]
    if most_common / len(texts) >= 2 / 3:
        return "minor_disagree"
    return "major_disagree"


def derive_page_strata(pages_by_engine: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    pages = list(pages_by_engine.values())
    words = _word_texts(pages)
    confidence_values = _confidence_values(pages)
    return {
        "zone_type": _zone_type(pages),
        "script": _script_bucket(words),
        "scan_quality": _scan_quality(confidence_values),
        "engine_coverage": _engine_coverage(len(pages_by_engine)),
        "confidence_bucket": _confidence_bucket(confidence_values),
        "dictionary_pass": _dictionary_pass(words),
        "bbox_agreement": _bbox_agreement(pages_by_engine),
        "consensus_disagreement_pattern": _consensus_pattern(pages_by_engine),
        "engine_family_set": tuple(sorted(pages_by_engine)),
    }


def _page_path(record: Mapping[str, Any]) -> str:
    for key in ("page_path", "selected_page_path", "sidecar_page_path"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    raise ValueError("page strata record is missing page_path")


def _page_strata(record: Mapping[str, Any]) -> Mapping[str, Any]:
    strata = record.get("strata")
    if isinstance(strata, Mapping):
        return strata
    return record


def _normalise_records(all_page_strata: Iterable[Mapping[str, Any]]) -> list[PageStrataRecord]:
    records: list[PageStrataRecord] = []
    for record in all_page_strata:
        records.append(PageStrataRecord(page_path=_page_path(record), strata=_page_strata(record)))
    return sorted(records, key=lambda item: item.page_path)


def _jsonable_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    return value


def _hashable_value(value: Any) -> Any:
    if isinstance(value, set):
        return tuple(sorted(value))
    if isinstance(value, list):
        return tuple(value)
    return value


def enumerate_observed_values(all_page_strata: Iterable[Mapping[str, Any]]) -> dict[str, set[Any]]:
    observed: dict[str, set[Any]] = {dimension.name: set() for dimension in STRATA_DIMENSIONS}
    for record in _normalise_records(all_page_strata):
        for dimension in STRATA_DIMENSIONS:
            if dimension.name in record.strata:
                observed[dimension.name].add(_hashable_value(record.strata[dimension.name]))
    return observed


def _risk_score(record: PageStrataRecord) -> int:
    score = 0
    for dimension, risky_values in _RISKY_VALUES.items():
        if record.strata.get(dimension) in risky_values:
            score += 10
    if record.strata.get("engine_coverage") == "single":
        score += 1
    return score


def _candidate_sort_key(record: PageStrataRecord) -> tuple[int, str]:
    return (-_risk_score(record), record.page_path)


def _bucket_values_for_dimension(
    dimension: StrataDimension,
    observed: Mapping[str, set[Any]],
) -> tuple[Any, ...]:
    values = set(dimension.buckets)
    values.update(observed.get(dimension.name, set()))
    return tuple(sorted(values, key=lambda value: str(value)))


def select_stratified_sample(
    all_page_strata: Iterable[Mapping[str, Any]],
    observed: Mapping[str, set[Any]],
    target_total: int,
    min_per_value: int,
) -> SampleResult:
    records = _normalise_records(all_page_strata)
    selected: set[str] = set()

    # Cover each observed hard-required value, RISKY values first. Risk priority
    # runs across values, not just within a value's candidates: under a tight
    # budget this starves safe body text (e.g. Latin paragraphs) before it starves
    # rare risk cells (Greek/Hebrew, low confidence, dictionary-fail) — the brief's
    # anti-oversampling requirement. Lexical value order would let a safe value
    # consume the budget before a later risky value is reached.
    value_pairs: list[tuple[int, str, str, Any]] = []
    for dimension_name in HARD_REQUIRED_DIMENSIONS:
        risky_values = _RISKY_VALUES.get(dimension_name, frozenset())
        for value in observed.get(dimension_name, set()):
            risk_rank = 0 if value in risky_values else 1
            value_pairs.append((risk_rank, dimension_name, str(value), value))

    for _risk_rank, dimension_name, _value_str, value in sorted(
        value_pairs, key=lambda pair: (pair[0], pair[1], pair[2])
    ):
        candidates = [
            record
            for record in records
            if record.strata.get(dimension_name) == value
        ]
        wanted = min(max(min_per_value, 0), len(candidates))
        current = len([record for record in candidates if record.page_path in selected])
        for candidate in sorted(candidates, key=_candidate_sort_key):
            if len(selected) >= target_total or current >= wanted:
                break
            if candidate.page_path in selected:
                continue
            selected.add(candidate.page_path)
            current += 1

    while len(selected) < target_total:
        remaining = [record for record in records if record.page_path not in selected]
        if not remaining:
            break
        selected.add(sorted(remaining, key=_candidate_sort_key)[0].page_path)

    strata: list[SampleStratum] = []
    for dimension in STRATA_DIMENSIONS:
        if not dimension.hard_required:
            continue
        for value in _bucket_values_for_dimension(dimension, observed):
            candidates = [
                record
                for record in records
                if record.strata.get(dimension.name) == value
            ]
            selected_for_value = tuple(
                sorted(record.page_path for record in candidates if record.page_path in selected)
            )
            if not candidates:
                flag = COVERAGE_NO_SOURCE_DATA
                target_count = 0
            elif not selected_for_value:
                flag = COVERAGE_EMPTY_REQUIRED_UNCOVERED
                target_count = min(max(min_per_value, 0), len(candidates))
            else:
                flag = COVERAGE_COVERED
                target_count = min(max(min_per_value, 0), len(candidates))
            strata.append(
                SampleStratum(
                    stratum_key={dimension.name: _jsonable_value(value)},
                    target_count=target_count,
                    actual_count=len(selected_for_value),
                    selected_pages=selected_for_value,
                    coverage_flag=flag,
                )
            )

    return SampleResult(selected_pages=tuple(sorted(selected)), strata=tuple(strata))


def classify_comparison_tolerances(
    baseline: Mapping[str, Any],
    compared: Mapping[str, Any],
    tolerance_bands: Mapping[str, Any],
) -> dict[str, str]:
    results: dict[str, str] = {}
    for indicator, tolerance in tolerance_bands.items():
        baseline_value = baseline.get(indicator)
        compared_value = compared.get(indicator)
        if not _is_number(tolerance):
            raise ValueError(f"{indicator} tolerance must be a number")
        if not _is_number(baseline_value):
            raise ValueError(f"{indicator} baseline value must be a number")
        if not _is_number(compared_value):
            raise ValueError(f"{indicator} compared value must be a number")
        delta = abs(float(compared_value) - float(baseline_value))
        results[indicator] = "within_tolerance" if delta <= float(tolerance) else "outside_tolerance"
    return results


def _is_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)
