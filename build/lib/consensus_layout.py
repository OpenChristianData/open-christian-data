"""Consensus geometry column detection for OCR word boxes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _EngineLayout:
    n_columns: int
    gutter_x: float | None
    separation: float
    body_boxes: list[dict]


@dataclass
class LayoutResult:
    n_columns: int
    gutter_x: float | None
    separation: float
    provider_count: int
    per_engine_gutter: dict[str, float | None]
    flags: list[str]
    escalate: bool

    def column_of(self, box: dict) -> int:
        """Return 0 for left/single-column, 1 for right."""
        if self.n_columns == 1 or self.gutter_x is None:
            return 0
        center_x = float(box["x"]) + float(box["w"]) / 2
        return 0 if center_x < self.gutter_x else 1


def _center_x(box: dict) -> float:
    return float(box["x"]) + float(box["w"]) / 2


def _center_y(box: dict) -> float:
    return float(box["y"]) + float(box["h"]) / 2


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _body_boxes(
    boxes: list[dict],
    page_height: int,
    header_frac: float,
    footer_frac: float,
) -> list[dict]:
    y_min = header_frac * page_height
    y_max = footer_frac * page_height
    return [
        box for box in boxes
        if y_min <= _center_y(box) <= y_max
    ]


def _histogram_counts(centers: list[float], page_width: int, bins: int = 80) -> list[int]:
    counts = [0 for _ in range(bins)]
    if page_width <= 0:
        return counts
    for center in centers:
        index = int(center / page_width * bins)
        index = max(0, min(bins - 1, index))
        counts[index] += 1
    return counts


def _density_at(x_value: float, counts: list[int], page_width: int) -> int:
    if not counts or page_width <= 0:
        return 0
    index = int(x_value / page_width * len(counts))
    index = max(0, min(len(counts) - 1, index))
    return counts[index]


def _separation(
    centers: list[float],
    gutter_x: float,
    page_width: int,
) -> float:
    counts = _histogram_counts(centers, page_width)
    left_peak = max(
        (_density_at(center, counts, page_width) for center in centers if center < gutter_x),
        default=0,
    )
    right_peak = max(
        (_density_at(center, counts, page_width) for center in centers if center >= gutter_x),
        default=0,
    )
    peak = min(left_peak, right_peak)
    if peak <= 0:
        return 0.0
    valley_density = _density_at(gutter_x, counts, page_width)
    return max(0.0, min(1.0, 1.0 - valley_density / peak))


def _engine_layout(boxes: list[dict], page_width: int) -> _EngineLayout:
    if not boxes:
        return _EngineLayout(1, None, 0.0, boxes)
    centers = sorted(_center_x(box) for box in boxes)
    if len(centers) < 4:
        return _EngineLayout(1, None, 0.0, boxes)

    counts = _histogram_counts(centers, page_width)
    max_count = max(counts) if counts else 0
    significant_density = max(3, int(max_count * 0.05))
    dense_centers = [
        center for center in centers
        if _density_at(center, counts, page_width) >= significant_density
    ]
    if len(dense_centers) < 4:
        return _EngineLayout(1, None, 1.0, boxes)

    min_gap = 0.015 * page_width
    central_min = 0.38 * page_width
    central_max = 0.62 * page_width
    gaps: list[tuple[float, float, float, float]] = []
    for left, right in zip(dense_centers, dense_centers[1:]):
        gap = right - left
        midpoint = (left + right) / 2
        if gap >= min_gap and central_min <= midpoint <= central_max:
            gaps.append((gap, midpoint, left, right))
    if not gaps:
        return _EngineLayout(1, None, 1.0, boxes)

    gap, midpoint, left_edge, right_edge = max(
        gaps,
        key=lambda item: (item[0], -abs(item[1] - page_width / 2), item[1], item[2], item[3]),
    )
    left_count = sum(1 for center in centers if center <= left_edge)
    right_count = sum(1 for center in centers if center >= right_edge)
    if left_count == 0 or right_count == 0:
        return _EngineLayout(1, None, 0.0, boxes)
    separation = _separation(centers, midpoint, page_width)
    return _EngineLayout(2, midpoint, separation, boxes)


def _column_band(values: list[float]) -> tuple[float, float]:
    """5th--95th percentile x-extent of a column's word centres.

    A real column spans a band, not a point. Modelling it as a median (the prior
    version) made every wide column flag itself as a third cluster, because its own
    edge words sit > main_band from its median. Using the band kills that false
    positive while still catching a genuine out-of-column cluster (marginalia)."""
    ordered = sorted(values)
    n = len(ordered)
    lo = ordered[max(0, int(0.05 * n))]
    hi = ordered[min(n - 1, int(0.95 * n))]
    return lo, hi


def _has_third_cluster(
    boxes: list[dict],
    page_width: int,
    gutter_x: float | None,
) -> bool:
    if gutter_x is None or not boxes:
        return False
    centers = [_center_x(box) for box in boxes]
    left_centers = [center for center in centers if center < gutter_x]
    right_centers = [center for center in centers if center >= gutter_x]
    if not left_centers or not right_centers:
        return False
    counts = _histogram_counts(centers, page_width)
    max_count = max(counts) if counts else 0
    if max_count == 0:
        return False
    significant = max(4, int(max_count * 0.18))
    bin_width = page_width / len(counts)
    l_lo, l_hi = _column_band(left_centers)
    r_lo, r_hi = _column_band(right_centers)
    margin = 0.05 * page_width
    for index, count in enumerate(counts):
        if count < significant:
            continue
        center = (index + 0.5) * bin_width
        in_left = l_lo - margin <= center <= l_hi + margin
        in_right = r_lo - margin <= center <= r_hi + margin
        # Only a SUBSTANTIAL density peak that falls inside neither column band is
        # a real third cluster (marginalia, a third column). A normal wide column
        # keeps all its significant bins inside its own [p5,p95]+margin band.
        if not in_left and not in_right:
            return True
    return False


def _has_spanning_lines(
    boxes: list[dict],
    page_width: int,
    gutter_x: float | None,
) -> bool:
    """Flag a page where a word box physically CROSSES the gutter.

    On a clean two-column page no word box straddles the empty gutter -- the
    columns are separated. A word whose extent [x, x+w] contains gutter_x is
    either a genuine full-width element (rule, centred heading, table line) or an
    OCR column-merge error; both should escalate (left-then-right reading order is
    unsafe). This is deliberately conservative: it has near-zero false positives on
    normal justified body text, where earlier x-centre/straddle-gap heuristics
    tripped on every line. A multi-cell spanning row of separate tokens with gaps
    is NOT caught here -- such pages instead surface via engine_disagreement /
    weak_gutter (e.g. the page-381 table), which is the intended catch."""
    if gutter_x is None:
        return False
    # Require the box to extend a real margin past the gutter on BOTH sides, so a
    # right-column word whose left edge merely nicks an off-centre gutter line does
    # not trip. A genuine full-width token spans the whole gutter region.
    margin = 0.03 * page_width
    for box in boxes:
        x0 = float(box["x"])
        x1 = x0 + float(box["w"])
        if x0 < gutter_x - margin and x1 > gutter_x + margin:
            return True
    return False


def detect_columns(
    engine_boxes: dict[str, list[dict]],
    page_width: int,
    page_height: int,
    *,
    header_frac: float = 0.09,
    footer_frac: float = 0.86,
) -> LayoutResult:
    """Detect one or two body columns from OCR word-box geometry."""
    providers = {
        engine_id: boxes
        for engine_id, boxes in sorted(engine_boxes.items())
        if boxes
    }
    provider_count = len(providers)
    if provider_count == 0:
        return LayoutResult(
            n_columns=1,
            gutter_x=None,
            separation=0.0,
            provider_count=0,
            per_engine_gutter={},
            flags=["zero_geometry"],
            escalate=True,
        )

    flags: set[str] = set()
    if provider_count == 1:
        flags.add("single_provider")

    per_engine: dict[str, _EngineLayout] = {}
    for engine_id, boxes in providers.items():
        body = _body_boxes(boxes, page_height, header_frac, footer_frac)
        per_engine[engine_id] = _engine_layout(body, page_width)

    if all(not layout.body_boxes for layout in per_engine.values()):
        flags.add("zero_geometry")

    per_engine_gutter = {
        engine_id: layout.gutter_x
        for engine_id, layout in sorted(per_engine.items())
    }
    counts = [layout.n_columns for layout in per_engine.values()]
    two_count = sum(1 for count in counts if count == 2)
    one_count = sum(1 for count in counts if count == 1)
    n_columns = 2 if two_count >= one_count and two_count > 0 else 1
    if one_count and two_count:
        flags.add("engine_disagreement")

    two_layouts = [layout for layout in per_engine.values() if layout.n_columns == 2]
    gutter_x: float | None = None
    separation = 1.0 if n_columns == 1 else 0.0
    if two_layouts:
        gutters = [layout.gutter_x for layout in two_layouts if layout.gutter_x is not None]
        gutter_x = _median(gutters) if gutters else None
        separation = _median([layout.separation for layout in two_layouts])
        if len(gutters) >= 2 and max(gutters) - min(gutters) > 0.04 * page_width:
            flags.add("engine_disagreement")

    all_body_boxes = [
        box
        for layout in per_engine.values()
        for box in layout.body_boxes
    ]
    if n_columns == 2 and gutter_x is not None:
        left_count = sum(1 for box in all_body_boxes if _center_x(box) < gutter_x)
        right_count = len(all_body_boxes) - left_count
        smaller = min(left_count, right_count)
        larger = max(left_count, right_count)
        if larger and smaller / larger < 0.15:
            flags.add("imbalanced_columns")
        if separation < 0.5:
            flags.add("weak_gutter")
            n_columns = 1
            gutter_x = None
        else:
            if _has_third_cluster(all_body_boxes, page_width, gutter_x):
                flags.add("third_cluster")
            if _has_spanning_lines(all_body_boxes, page_width, gutter_x):
                flags.add("spanning_lines")

    escalate_flags = {
        "zero_geometry",
        "engine_disagreement",
        "weak_gutter",
        "third_cluster",
        "spanning_lines",
    }
    sorted_flags = sorted(flags)
    escalate = any(flag in escalate_flags for flag in sorted_flags)
    return LayoutResult(
        n_columns=n_columns,
        gutter_x=gutter_x,
        separation=separation,
        provider_count=provider_count,
        per_engine_gutter=per_engine_gutter,
        flags=sorted_flags,
        escalate=escalate,
    )


def _bounding_rect(boxes: list[dict]) -> dict:
    min_x = min(float(box["x"]) for box in boxes)
    min_y = min(float(box["y"]) for box in boxes)
    max_x = max(float(box["x"]) + float(box["w"]) for box in boxes)
    max_y = max(float(box["y"]) + float(box["h"]) for box in boxes)
    return {"x": min_x, "y": min_y, "w": max_x - min_x, "h": max_y - min_y}


def _column_dict(column: int, boxes: list[dict]) -> dict:
    return {
        "column": column,
        "assign_x": _median([_center_x(box) for box in boxes]),
        "native": _bounding_rect(boxes),
    }


def column_zones(
    engine_boxes: dict[str, list[dict]],
    page_width: int,
    page_height: int,
    *,
    header_frac: float = 0.09,
    footer_frac: float = 0.86,
) -> tuple[LayoutResult, list[dict]]:
    result = detect_columns(
        engine_boxes,
        page_width,
        page_height,
        header_frac=header_frac,
        footer_frac=footer_frac,
    )
    if result.provider_count == 0:
        return result, []

    pooled = [
        box
        for boxes in engine_boxes.values()
        for box in boxes
    ]
    body_boxes = _body_boxes(pooled, page_height, header_frac, footer_frac)
    if not body_boxes:
        return result, []

    if result.n_columns == 1 or result.gutter_x is None:
        return result, [_column_dict(1, body_boxes)]

    columns: list[dict] = []
    for side in (0, 1):
        side_boxes = [box for box in body_boxes if result.column_of(box) == side]
        if side_boxes:
            columns.append(_column_dict(len(columns) + 1, side_boxes))
    return result, columns
