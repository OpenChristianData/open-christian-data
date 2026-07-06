"""S2.5 alignment -> word-confusion-table builder (arch A Layer-1, batch B6).

Consumes the per-engine rendering-v1 records for one page image and emits one
word-confusion-table-v1 page (the frozen Layer-1 contract). This is the *un-tuned*
builder: every threshold here is a reconciled arch A default
(plans/2026-05-28-archA-alignment-reconciled-design.md section 10), and tuning is
gated by the B8 first-diagnostics verdict -- do not fit thresholds here.

What it does (arch A section 1, stages S0/S3/S4/S5/S7/S8/S9):
  S0  collect the engines that ran (available_engines); absent != skip.
  S3  zones come from the surya layout authority's blocks, clustered into body
      column zones (two-column NSH pages -> left + right) by x-centre. A geometry-
      bearing engine's word joins the column whose median block-centre is nearest
      its x (clustered unions can overlap, so nearest-centre beats raw overlap); a
      geometry-less engine's word joins the column nearest its block centre. The
      producing engine's self-reported zone_label is never used for assignment.
  S4  order positions within a column by a geometry-bearing engine's word (y then
      x); a position attested only by geometry-less engines inherits the previous
      geometry position's order key. Reading order = column 1 (left) then column 2.
  S5  hyphenation: a rendering-v1 derived_join_span (line_break) becomes an
      ambiguous hyphenation slot carrying both joined/unjoined hypotheses; the
      raw line-break evidence is preserved, never silently rejoined.
  S7  confusion-network alignment: progressive multiple-sequence alignment matched
      by confusion-weighted edit distance (arch A section 4). Geometry-bearing
      engines (Tesseract, re-pointed ABBYY) anchor positions; geometry-less engines
      (Surya, Kraken) contribute TEXT into matching positions but never open a new
      one. No truth choice, no LM/context scoring.
  S8  candidate-normalisation for grouping only (NFKC + ligature + hyphen keys);
      diplomatic raw text is never rewritten.
  S9  emit the WCT page.

Boundary (arch A section 3): Layer 1 makes no irreversible choice -- it emits all
candidates and all span evidence. Truth selection, calibration fitting, dehyphen
*decision*, and G/H *correction* are downstream layers.

Un-tuned limitations recorded for B8 (not bugs -- by design):
  * multi-character confusion costs are an un-tuned pre-B8 default loaded from
    the OCR error model YAML files; B8 may fit them later.
  * the surya glyph-level script classifier is downstream; image_level script is
    derived from the Unicode block here (text-level method), flagged accordingly.
  * non-body zone-label -> wct_zone_type mappings are defaults; only body is
    exercised by the vol_01 bake-off fixture.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib import _generated_enums, consensus_layout
from build.lib.nsh_leaf_model import set_leaf_or_exempt
from build.lib.schema_enums import get_enum

# --------------------------------------------------------------------------- #
# Config -- reconciled arch A section 10 defaults. Tuning is gated by B8.
# --------------------------------------------------------------------------- #

SAME_SLOT_THRESHOLD = 0.5       # confusion-weighted normalised distance for one slot.
GAP_PENALTY = 0.6               # alignment gap cost (skip / insertion).
LINE_BAND_PX = 40               # vertical tolerance for grouping positions to a line.

# arch A section 4 visual confusion costs. Single-character pairs + hyphen/space.
# Cost is the substitution cost (0 = identical); pairs cheaper than the unit 1.0.
MULTICHAR_SUB_COST = 0.25
_CONFUSION_PAIRS: dict[tuple[str, str], float] = {
    ("-", " "): 0.10,           # hyphenation join vs space (the central S5 case)
    ("0", "o"): 0.20, ("0", "O"): 0.20, ("o", "O"): 0.20,
    ("1", "l"): 0.20, ("1", "i"): 0.25, ("l", "i"): 0.25, ("1", "I"): 0.20,
    ("c", "e"): 0.30, ("s", "f"): 0.30,   # long-s confusion approximated
    ("u", "n"): 0.30, ("a", "o"): 0.35,
}
_CONFUSION = {frozenset(pair): cost for pair, cost in _CONFUSION_PAIRS.items()}
_MODEL_DIR = Path(__file__).resolve().parent / "ocr_error_models"


def _load_ocr_model(language: str) -> list[dict]:
    path = _MODEL_DIR / f"{language}.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or []


def _load_multichar_confusions() -> dict[tuple[str, str], float]:
    confusions: dict[tuple[str, str], float] = {}
    for language in ("en", "la"):
        for entry in _load_ocr_model(language):
            confusion = entry.get("confusion", {})
            source = confusion.get("source", "")
            target = confusion.get("target", "")
            if source and target and (len(source) > 1 or len(target) > 1):
                # Pre-B8 un-tuned default: cheaper than raw edit distance, not free.
                confusions[(source, target)] = MULTICHAR_SUB_COST
                confusions[(target, source)] = MULTICHAR_SUB_COST
    return confusions


_MULTICHAR_CONFUSIONS = _load_multichar_confusions()

# rendering-v1 engine_family -> word-confusion-table-v1 engine_family. A
# translation table between two schema enums (NOT a hardcoded enum mirror): its
# keys are validated against the rendering-v1 enum and its values against the WCT
# enum at import (PIPE-26 -- single source of truth stays the schemas).
_FAMILY_MAP = {
    "tesseract": "tesseract",
    "abbyy": "abbyy",
    "surya": "surya",
    "kraken": "kraken",
    "calamari": "calamari",
    "azure_read": "azure-ai-vision",
    "textract": "aws-textract",
}

# rendering-v1 zone_label -> word-confusion-table-v1 zone_type. Un-tuned defaults;
# only body is exercised by the bake-off fixture.
_ZONE_TYPE_MAP = {
    "body": "body",
    "running_header": "running-header",
    "footer_text": "running-header",
    "folio": "page-number",
    "footnote": "footnote",
    "marginalia": "marginalia",
    "caption": "figure",
    "drop_cap": "body",
    "column_rule_or_noise": "figure",
    "unknown": "body",
}

_RENDERING = "rendering-v1"
_WCT = "word-confusion-table-v1"

# Validate the translation tables against both schemas at import time so a schema
# change that drops a value fails loudly here rather than emitting an invalid WCT.
_RENDER_FAMILIES = get_enum(_RENDERING, "engine_family")
_WCT_FAMILIES = get_enum(_WCT, "available_engines", "family")
_WCT_ZONE_TYPES = get_enum(_WCT, "zones", "zone_type")
# normalisation_applied is an array whose items are a $ref; get_enum cannot reach
# that leaf, so read it from the generated constant (the freshness check keeps it
# in sync with the schema -- PIPE-26 permits _generated_enums as the source).
_NORMALISATION_OPS = frozenset(_generated_enums.WORD_CONFUSION_TABLE_V1__DEFS__NORMALISATION_OP)
_SCRIPT_LABELS = get_enum(_WCT, "positions", "script", "image_level", "label")
_SCRIPT_ROUTING = get_enum(_WCT, "positions", "script", "routing")

assert set(_FAMILY_MAP) <= _RENDER_FAMILIES, "family map key not in rendering-v1 enum"
assert set(_FAMILY_MAP.values()) <= _WCT_FAMILIES, "family map value not in WCT enum"
assert set(_ZONE_TYPE_MAP.values()) <= _WCT_ZONE_TYPES, "zone-type map value not in WCT enum"


class LayoutEscalation(Exception):
    """A page the consensus geometry could not resolve and that has no Surya
    rendering to fall back on. The driver runs Surya on these pages, then retries."""

    def __init__(self, page_id: str, flags: list[str]):
        super().__init__(f"layout escalation for {page_id}: {','.join(flags)}")
        self.page_id = page_id
        self.flags = list(flags)


# --------------------------------------------------------------------------- #
# Confusion-weighted edit distance (arch A section 4) -- slot membership only.
# --------------------------------------------------------------------------- #


def _sub_cost(a: str, b: str) -> float:
    if a == b:
        return 0.0
    return _CONFUSION.get(frozenset((a, b)), 1.0)


_WeightedEditMove = tuple[str, int, int]


def _weighted_edit_table(a: str, b: str) -> tuple[float, list[list[_WeightedEditMove | None]]]:
    """Confusion-weighted Levenshtein table plus fill-time backtrace pointers."""
    rows, cols = len(a) + 1, len(b) + 1
    dp = [[0.0] * cols for _ in range(rows)]
    ptr: list[list[_WeightedEditMove | None]] = [[None] * cols for _ in range(rows)]
    for i in range(1, rows):
        dp[i][0] = float(i)
        ptr[i][0] = ("delete", 1, 0)
    for j in range(1, cols):
        dp[0][j] = float(j)
        ptr[0][j] = ("insert", 0, 1)
    for i in range(1, rows):
        for j in range(1, cols):
            delete = dp[i - 1][j] + 1.0
            insert = dp[i][j - 1] + 1.0
            substitute = dp[i - 1][j - 1] + _sub_cost(a[i - 1], b[j - 1])
            best = min(delete, insert, substitute)
            if best == delete:
                move: _WeightedEditMove = ("delete", 1, 0)
            elif best == insert:
                move = ("insert", 0, 1)
            else:
                move = ("substitute", 1, 1)
            for (source, target), cost in _MULTICHAR_CONFUSIONS.items():
                src_len = len(source)
                tgt_len = len(target)
                if i >= src_len and j >= tgt_len:
                    if a[i - src_len:i] == source and b[j - tgt_len:j] == target:
                        multichar = dp[i - src_len][j - tgt_len] + cost
                        if multichar < best:
                            best = multichar
                            move = ("substitute", src_len, tgt_len)
            dp[i][j] = best
            ptr[i][j] = move
    return dp[-1][-1], ptr


def _weighted_edit(a: str, b: str) -> float:
    """Confusion-weighted Levenshtein distance between two strings."""
    distance, _ = _weighted_edit_table(a, b)
    return distance


def weighted_edit_backtrace(a: str, b: str) -> tuple[float, list[dict[str, str]]]:
    """Return the weighted edit distance and aligned character edit operations.

    The distance uses the same single-character confusion table, multi-character
    OCR model entries, and insertion/deletion costs as ``_weighted_edit``.
    """
    distance, ptr = _weighted_edit_table(a, b)
    ops: list[dict[str, str]] = []
    i, j = len(a), len(b)
    while i > 0 or j > 0:
        move = ptr[i][j]
        if move is None:
            raise RuntimeError("weighted edit backtrace reached an uninitialized cell")
        op_name, src_len, tgt_len = move
        source = a[i - src_len:i]
        target = b[j - tgt_len:j]
        if op_name == "substitute" and source == target:
            op_name = "match"
        ops.append({"op": op_name, "source": source, "target": target})
        i -= src_len
        j -= tgt_len
    ops.reverse()
    return distance, ops


@lru_cache(maxsize=200_000)
def confusion_distance(a: str, b: str) -> float:
    """Normalised confusion-weighted distance in [0, 1]. 0 = same slot."""
    if not a and not b:
        return 0.0
    return _weighted_edit(a, b) / max(len(a), len(b), 1)


# --------------------------------------------------------------------------- #
# Candidate normalisation for grouping only (arch A S8) -- never rewrites text.
# --------------------------------------------------------------------------- #

_LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
}


def normalise_candidate(raw_reading: str, *, hyphen_unjoined: bool) -> tuple[str, list[str]]:
    """Return (candidate_key, normalisation_applied[]) for grouping.

    NFKC is always recorded. ligature_expand when a ligature was expanded.
    hyphen_unjoined_key when the reading came from a line-break hyphenation join
    (the unjoined form is the grouping key).
    """
    applied = ["unicode_nfkc"]
    key = unicodedata.normalize("NFKC", raw_reading)
    expanded = key
    for lig, repl in _LIGATURES.items():
        expanded = expanded.replace(lig, repl)
    if expanded != key:
        applied.append("ligature_expand")
        key = expanded
    if hyphen_unjoined:
        applied.append("hyphen_unjoined_key")
    assert set(applied) <= _NORMALISATION_OPS, "emitted a non-schema normalisation op"
    return key, applied


# --------------------------------------------------------------------------- #
# Internal token / engine / column models.
# --------------------------------------------------------------------------- #


@dataclass
class _SourceSpan:
    token_id: str
    text: str
    bbox: dict
    line_id: str


@dataclass
class _LogicalToken:
    """One logical word an engine attests at a slot (1 source span, or n for a
    hyphenation split)."""
    key: str
    raw_reading: str
    source_spans: list[_SourceSpan]
    confidence: float | None
    span_type: str                      # exact | split | merge | insertion
    relation: str                       # 1:1 | 1:n | n:1
    normalisation_applied: list[str]
    hyphen_evidence: dict | None        # {token_ids, raw_tokens} when a line-break join
    y: float | None                     # primary bbox top; None for a geometry-less engine
    x: float | None                     # primary bbox left; None for a geometry-less engine


@dataclass
class _Engine:
    engine_id: str
    family: str                         # WCT family (mapped)
    lineage: str
    engine_version: str
    engine_run_id: str
    has_geometry: bool = True           # False for line-level engines (Surya, Kraken)
    tokens: list[_LogicalToken] = field(default_factory=list)


@dataclass
class _Column:
    attestations: dict[str, _LogicalToken] = field(default_factory=dict)  # engine_id -> token

    @property
    def rep_key(self) -> str:
        keys = [t.key for t in self.attestations.values()]
        if not keys:
            return ""
        # Count ties broken by key value so iteration order of the set never affects
        # the result (PYTHONHASHSEED-independent). Without this, NW alignment of
        # geometry-less engines is non-deterministic when two geometry engines disagree
        # at equal count, flipping alignment_confidence and chosen_reading in the WCT.
        return max(set(keys), key=lambda k: (keys.count(k), k))

    @property
    def order_key(self) -> tuple[float, float]:
        # Geometry-bearing attestations only -- a geometry-less token's y/x is None.
        ys = [t.y for t in self.attestations.values() if t.y is not None]
        xs = [t.x for t in self.attestations.values() if t.x is not None]
        return (min(ys), min(xs)) if ys else (0.0, 0.0)


# --------------------------------------------------------------------------- #
# Geometry.
# --------------------------------------------------------------------------- #


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text).strip("-").lower()


# --------------------------------------------------------------------------- #
# Stage S1/S2: zones from the surya layout authority.
# --------------------------------------------------------------------------- #


def _surya_rendering(renderings: list[dict]) -> dict:
    suryas = [r for r in renderings if r["engine_family"] == "surya"]
    if not suryas:
        raise ValueError("no surya rendering present -- surya is the mandatory layout authority")
    if len(suryas) > 1:
        # Two surya runs would make the layout authority ambiguous; input order
        # must not silently pick one (Codex review secondary finding).
        raise ValueError(
            f"{len(suryas)} surya renderings supplied -- the layout authority must be unambiguous"
        )
    return suryas[0]


def _zone_type_for(label: str | None) -> str:
    return _ZONE_TYPE_MAP.get(label or "unknown", "body")


# A horizontal gap between sorted body-block x-centres wider than this fraction of
# the page width is read as a column gutter. Real NSH pages are two-column with a
# ~0.4-page-width gap between column centres; single-column pages cluster tighter.
_COLUMN_GAP_FRACTION = 0.12


def _union_rect(a: dict, b: dict) -> dict:
    nx0 = min(a["x"], b["x"])
    ny0 = min(a["y"], b["y"])
    nx1 = max(a["x"] + a["w"], b["x"] + b["w"])
    ny1 = max(a["y"] + a["h"], b["y"] + b["h"])
    return {"x": nx0, "y": ny0, "w": nx1 - nx0, "h": ny1 - ny0}


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _cluster_body_columns(rects: list[dict], page_width: float) -> list[dict]:
    """Cluster body-block rectangles into column unions, left-to-right.

    Surya's body blocks are one-per-line; their x-centres are bimodal on a
    two-column page (the layout authority's columns). Split the sorted centres
    wherever the gap exceeds a page-width fraction; union each cluster. Each result
    carries ``assign_x`` = the MEDIAN member block-centre -- robust to a spanning
    running-header line that would otherwise inflate the union and make the gutter
    boundary wrong. Tokens assign to the nearest ``assign_x``, not by overlap (the
    unions can overlap once a wide line is folded in). One cluster per column, left
    first; a single-column page yields one.
    """
    if not rects:
        return []
    ordered = sorted(rects, key=lambda r: r["x"] + r["w"] / 2)
    threshold = _COLUMN_GAP_FRACTION * page_width
    clusters: list[list[dict]] = [[ordered[0]]]
    prev_center = ordered[0]["x"] + ordered[0]["w"] / 2
    for rect in ordered[1:]:
        center = rect["x"] + rect["w"] / 2
        if center - prev_center > threshold:
            clusters.append([rect])
        else:
            clusters[-1].append(rect)
        prev_center = center
    columns = []
    for members in clusters:
        union = members[0]
        for rect in members[1:]:
            union = _union_rect(union, rect)
        union = dict(union)
        union["assign_x"] = _median([r["x"] + r["w"] / 2 for r in members])
        columns.append(union)
    return columns


def _build_zones(surya: dict) -> list[dict]:
    """WCT zones from the surya layout authority. Polygons are corners.

    bbox_canonical is corners ``[x0, y0, x1, y1]`` normalised 0..1 -- the convention
    render_s2._bbox_canonical emits (index 2 is ``(x+w)/width``). Reading it as
    origin+size inflated every zone (bug 3).

    Surya emits one block per text line (real page_0010 = 137 body line-blocks), so
    one-zone-per-block left build_wct aligning inside a single line (bug 4). Body
    blocks are clustered into column zones by their x-centres (two-column NSH pages
    become a left + right column, reading order left-then-right); other furniture
    types (footnote, running-header) collapse to one zone per type.
    """
    page = surya["pages"][0]
    dims = page["page_dimensions_native"]
    width, height = dims["width"], dims["height"]
    body_rects: list[dict] = []
    furniture: dict[str, dict] = {}
    furniture_order: list[str] = []
    for block in page["blocks"]:
        x0, y0, x1, y1 = block["bbox_canonical"]   # corners, normalised 0..1
        rect = {"x": x0 * width, "y": y0 * height, "w": (x1 - x0) * width, "h": (y1 - y0) * height}
        zone_type = _zone_type_for(block.get("zone_label"))
        if zone_type == "body":
            body_rects.append(rect)
        elif zone_type in furniture:
            furniture[zone_type] = _union_rect(furniture[zone_type], rect)
        else:
            furniture[zone_type] = rect
            furniture_order.append(zone_type)

    zones = []
    for column_index, nat in enumerate(_cluster_body_columns(body_rects, width), start=1):
        zones.append(_zone_dict("body", column_index, column_index, nat, nat["assign_x"]))
    furniture_index = len(zones)
    for zone_type in furniture_order:
        furniture_index += 1
        zones.append(_zone_dict(zone_type, furniture_index, None, furniture[zone_type], None))
    return zones


def _page_dimensions(renderings: list[dict]) -> dict:
    for rendering in renderings:
        dims = rendering["pages"][0].get("page_dimensions_native") or {}
        if dims.get("width") is not None and dims.get("height") is not None:
            return dims
    raise ValueError("no rendering supplies page_dimensions_native width and height")


def _geometric_zones(renderings: list[dict]) -> tuple[list[dict], consensus_layout.LayoutResult]:
    engine_boxes: dict[str, list[dict]] = {}
    for rendering in renderings:
        if not _engine_has_word_geometry(rendering):
            continue
        boxes = [
            dict(word["bbox_native"])
            for _, word in _iter_words(rendering)
            if word["bbox_native"] is not None
        ]
        if boxes:
            engine_boxes[_slug(rendering["source_lineage_id"])] = boxes

    dims = _page_dimensions(renderings)
    result, columns = consensus_layout.column_zones(
        engine_boxes,
        int(dims["width"]),
        int(dims["height"]),
    )
    zones = []
    for column in columns:
        zone = _zone_dict(
            "body",
            column["column"],
            column["column"],
            column["native"],
            column["assign_x"],
        )
        zone["source"] = "geometric"
        zones.append(zone)
    return zones, result


def _zones_from_annotation(ann: dict) -> list[dict]:
    zones: list[dict] = []
    id_index = 1
    for ann_zone in ann.get("zones", []):
        if ann_zone.get("role") != "body":
            continue

        bbox = ann_zone["bbox_native"]
        bx, by, bw, bh = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
        column_count = int(ann_zone["column_count"])
        for column in range(1, column_count + 1):
            col_w = bw / column_count
            nat = {
                "x": bx + col_w * (column - 1),
                "y": by,
                "w": col_w,
                "h": bh,
            }
            assign_x = bx + col_w * (column - 0.5)
            zone = _zone_dict("body", id_index, column, nat, assign_x)
            zone["source"] = "manual-annotation"
            zones.append(zone)
            id_index += 1
    return zones


def _zone_dict(zone_type: str, id_index: int, column: int | None, nat: dict, assign_x: float | None) -> dict:
    x, y, w, h = nat["x"], nat["y"], nat["w"], nat["h"]
    return {
        "zone_id": f"z_{zone_type}_{id_index}",
        "zone_type": zone_type,
        "track_id": f"{zone_type}:c{id_index}",
        "column": column,
        "polygon": [
            {"x": x, "y": y},
            {"x": x + w, "y": y},
            {"x": x + w, "y": y + h},
            {"x": x, "y": y + h},
        ],
        "source": "surya",
        "_native": {"x": x, "y": y, "w": w, "h": h},   # stripped before emit
        "_assign_x": assign_x,                          # median block centre; stripped before emit
    }


# --------------------------------------------------------------------------- #
# Stage S3/S4/S5: engine tokens -> zones, ordered, hyphenation collapsed.
# --------------------------------------------------------------------------- #


def _engine_identity(rendering: dict) -> dict:
    family = rendering["engine_family"]
    if family not in _FAMILY_MAP:
        raise ValueError(f"engine_family {family!r} has no WCT family mapping")
    return {
        "engine_id": _slug(rendering["source_lineage_id"]),
        "family": _FAMILY_MAP[family],
        "lineage": rendering["source_lineage_id"],
        "engine_version": rendering["engine_version"],
        "engine_run_id": rendering["rendering_id"],
    }


def _join_index(rendering: dict) -> dict[str, dict]:
    """observation_token_id -> its derived_join_span (line-break hyphenation)."""
    index: dict[str, dict] = {}
    for spans in rendering.get("derived_spans_by_block", {}).values():
        for span in spans:
            for ot_id in span["contributor_observation_token_ids"]:
                index[ot_id] = span
    return index


def _iter_words(rendering: dict):
    for block in rendering["pages"][0]["blocks"]:
        for line in block["lines"]:
            for word in line["words"]:
                yield line, word


def _engine_has_word_geometry(rendering: dict) -> bool:
    """True if the engine carries at least one per-word bbox. Tesseract and
    re-pointed ABBYY do; Surya/Kraken are line-level and carry none."""
    return any(word["bbox_native"] is not None for _, word in _iter_words(rendering))


def _block_center_x(block: dict, width: float) -> float | None:
    canonical = block.get("bbox_canonical")   # corners [x0,y0,x1,y1] normalised
    if not canonical:
        return None
    return (canonical[0] + canonical[2]) / 2 * width


def _nearest_body_column(center_x: float, body_zones: list[dict]) -> int:
    """Column index of the body zone whose median block centre is nearest. Used
    instead of bbox overlap because clustered column unions can overlap once a
    page-spanning running-header line is folded into one of them."""
    return min(body_zones, key=lambda z: abs(center_x - z["_assign_x"]))["column"]


def _engine_body_tokens_by_column(
    rendering: dict, body_zones: list[dict], has_geometry: bool
) -> dict[int, list[_LogicalToken]]:
    """Assign one engine's body words to column tracks and build logical tokens.

    Geometry-bearing engine: a word is a body word if its centre falls in the body
    y-band; it joins the column whose median centre is nearest its x. Geometry-less
    engine: every word in a body-labelled block joins the column nearest that
    block's x-centre, carrying no per-word geometry -- its WCT span record gets
    empty source_spans (the schema's source_span requires a bbox, which it has none
    of), but its TEXT still participates in the alignment.
    """
    if not body_zones:
        return {}
    cols: dict[int, list[tuple[dict, dict]]] = {z["column"]: [] for z in body_zones}
    width = rendering["pages"][0]["page_dimensions_native"]["width"]
    y_lo = min(z["_native"]["y"] for z in body_zones)
    y_hi = max(z["_native"]["y"] + z["_native"]["h"] for z in body_zones)
    for block in rendering["pages"][0]["blocks"]:
        block_zone_type = _zone_type_for(block.get("zone_label"))
        block_cx = _block_center_x(block, width)
        for line in block["lines"]:
            for word in line["words"]:
                bbox = word["bbox_native"]
                if bbox is not None:
                    cy = bbox["y"] + bbox["h"] / 2
                    if not (y_lo <= cy <= y_hi):
                        continue   # furniture band (running header above / footnote below)
                    col = _nearest_body_column(bbox["x"] + bbox["w"] / 2, body_zones)
                else:
                    if block_zone_type != "body":
                        continue   # geometry-less: only body-labelled blocks feed the body track
                    col = (
                        _nearest_body_column(block_cx, body_zones)
                        if block_cx is not None
                        else body_zones[0]["column"]
                    )
                cols[col].append((line, word))
    join_index = _join_index(rendering)
    return {
        column: _build_column_tokens(word_list, join_index, has_geometry)
        for column, word_list in cols.items()
    }


def _build_column_tokens(
    body_words: list[tuple[dict, dict]], join_index: dict[str, dict], has_geometry: bool
) -> list[_LogicalToken]:
    """Collapse a column's words into logical tokens (line-break hyphenation joins
    kept as split tokens). Geometry-bearing engines order by (y, x); geometry-less
    engines keep document order -- their words carry no bbox to sort by, and the
    layout authority emits blocks in reading order."""
    tokens: list[_LogicalToken] = []
    consumed: set[str] = set()
    body_ids = {w["observation_token_id"] for _, w in body_words}
    for line, word in body_words:
        ot_id = word["observation_token_id"]
        if ot_id in consumed:
            continue
        join = join_index.get(ot_id)
        if join and all(cid in body_ids for cid in join["contributor_observation_token_ids"]):
            tokens.append(_split_token_from_join(join, body_words, consumed))
        else:
            tokens.append(_exact_token(line, word))
            consumed.add(ot_id)
    if has_geometry:
        tokens.sort(key=lambda t: (t.y, t.x))
    return tokens


def _exact_token(line: dict, word: dict) -> _LogicalToken:
    text = word["layers"]["structured"]
    bbox = word["bbox_native"]
    key, applied = normalise_candidate(text, hyphen_unjoined=False)
    if bbox is not None:
        spans = [_SourceSpan(word["observation_token_id"], text, dict(bbox), line["rendering_line_id"])]
        y: float | None = float(bbox["y"])
        x: float | None = float(bbox["x"])
    else:
        # Geometry-less engine: no bbox -> no source span (the schema requires one),
        # but the reading still attests its candidate. y/x None = not geometric.
        spans = []
        y = x = None
    return _LogicalToken(
        key=key, raw_reading=text, source_spans=spans, confidence=word.get("confidence_raw"),
        span_type="exact", relation="1:1", normalisation_applied=applied,
        hyphen_evidence=None, y=y, x=x,
    )


def _split_token_from_join(join: dict, body_words, consumed: set[str]) -> _LogicalToken:
    """A line-break hyphenation join -> one split (1:n) logical token. The raw
    contributor tokens survive as distinct source spans (never flattened). A
    geometry-less engine contributes no bbox, so its split carries no source spans."""
    by_id = {w["observation_token_id"]: (line, w) for line, w in body_words}
    spans: list[_SourceSpan] = []
    raw_tokens: list[str] = []
    confidences: list[float] = []
    ys: list[float] = []
    xs: list[float] = []
    for cid in join["contributor_observation_token_ids"]:
        line, word = by_id[cid]
        text = word["layers"]["structured"]
        bbox = word["bbox_native"]
        if bbox is not None:
            spans.append(_SourceSpan(cid, text, dict(bbox), line["rendering_line_id"]))
            ys.append(float(bbox["y"]))
            xs.append(float(bbox["x"]))
        raw_tokens.append(text)
        if word.get("confidence_raw") is not None:
            confidences.append(word["confidence_raw"])
        consumed.add(cid)
    structured = join["structured_text"]
    key, applied = normalise_candidate(structured, hyphen_unjoined=True)
    return _LogicalToken(
        key=key, raw_reading=" ".join(raw_tokens), source_spans=spans,
        confidence=min(confidences) if confidences else None,
        span_type="split", relation="1:n", normalisation_applied=applied,
        hyphen_evidence={
            "engine_token_ids": [s.token_id for s in spans] if spans
            else list(join["contributor_observation_token_ids"]),
            "raw_tokens": raw_tokens,
            "boundary_type": join["boundary_type"],
        },
        y=ys[0] if ys else None, x=xs[0] if xs else None,
    )


# --------------------------------------------------------------------------- #
# Stage S7: engine-agnostic progressive alignment.
# --------------------------------------------------------------------------- #


def _nw_align(spine_keys: list[str], token_keys: list[str]) -> list[tuple[int | None, int | None]]:
    """Needleman-Wunsch over keys with confusion-weighted substitution; returns
    ordered (spine_idx|None, token_idx|None) pairs."""
    n, m = len(spine_keys), len(token_keys)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    # Pointer matrix recorded during the fill: "diag" | "up" | "left". Recording
    # the chosen move at fill time (instead of re-deriving it with a float-`==`
    # comparison during the backtrace) is what keeps the walk on the array -- on a
    # long pure-gap column i*GAP_PENALTY drifts (e.g. 67*0.6 == 40.199999999999996
    # != 66*0.6 + 0.6), so the old re-derivation matched no branch and drove j < 0.
    ptr: list[list[str | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i * GAP_PENALTY
        ptr[i][0] = "up"
    for j in range(1, m + 1):
        dp[0][j] = j * GAP_PENALTY
        ptr[0][j] = "left"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            diag = dp[i - 1][j - 1] + confusion_distance(spine_keys[i - 1], token_keys[j - 1])
            up = dp[i - 1][j] + GAP_PENALTY
            left = dp[i][j - 1] + GAP_PENALTY
            best = min(diag, up, left)
            dp[i][j] = best
            # Tie-break precedence diagonal > deletion/up > insertion/left -- the
            # same order the prior `==` chain checked, so fixture outputs are
            # byte-identical. `best` is one of these freshly computed values, so
            # these equalities are exact (no accumulated-drift re-derivation).
            if best == diag:
                ptr[i][j] = "diag"
            elif best == up:
                ptr[i][j] = "up"
            else:
                ptr[i][j] = "left"
    ops: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        move = ptr[i][j]
        if move == "diag":
            ops.append((i - 1, j - 1)); i -= 1; j -= 1
        elif move == "up":
            ops.append((i - 1, None)); i -= 1
        else:
            ops.append((None, j - 1)); j -= 1
    ops.reverse()
    return ops


def _merge_engine(spine: list[_Column], engine: _Engine, *, allow_insert: bool) -> list[_Column]:
    """Align one engine's tokens to the spine. ``allow_insert`` controls whether a
    token that matches no spine column may open a new position: geometry-bearing
    engines may (they anchor positions); geometry-less engines may not (their text
    only corroborates an existing geometric position)."""
    if not spine:
        return [_Column({engine.engine_id: tok}) for tok in engine.tokens]
    ops = _nw_align([c.rep_key for c in spine], [t.key for t in engine.tokens])
    merged: list[_Column] = []
    for col_idx, tok_idx in ops:
        if col_idx is not None and tok_idx is not None:
            column = spine[col_idx]
            token = engine.tokens[tok_idx]
            if confusion_distance(column.rep_key, token.key) <= SAME_SLOT_THRESHOLD:
                column.attestations[engine.engine_id] = token
                merged.append(column)
            else:                                       # too dissimilar to merge
                merged.append(column)                   # engine skips this column
                if allow_insert:
                    merged.append(_Column({engine.engine_id: token}))   # insertion
        elif col_idx is not None:
            merged.append(spine[col_idx])               # engine skips this column
        elif allow_insert:
            merged.append(_Column({engine.engine_id: engine.tokens[tok_idx]}))  # insertion
        # else: geometry-less insertion -> dropped (no geometric anchor)
    return merged


def _align_engines(engines: list[_Engine]) -> list[_Column]:
    """Progressive MSA. Geometry-bearing engines (Tesseract, re-pointed ABBYY)
    anchor the positions -- they seed and merge first, each free to open columns.
    Geometry-less engines (Surya, Kraken) then merge their TEXT into matching
    columns but never open a new position (the prompt's correction: only
    geometry-bearing engines anchor positions). A geometry-less reading that matches
    nothing is dropped from the table, not given a fabricated geometric position."""
    geometry = sorted(
        (e for e in engines if e.has_geometry), key=lambda e: (-len(e.tokens), e.engine_id)
    )
    geometry_less = sorted(
        (e for e in engines if not e.has_geometry), key=lambda e: (-len(e.tokens), e.engine_id)
    )
    spine: list[_Column] = []
    for engine in geometry:
        spine = _merge_engine(spine, engine, allow_insert=True)
    if not spine:
        # Degenerate: no geometry engine ran (no Tesseract/ABBYY). Let geometry-less
        # engines anchor so the page is not empty -- should not happen in production.
        for engine in geometry_less:
            spine = _merge_engine(spine, engine, allow_insert=True)
        return spine
    for engine in geometry_less:
        spine = _merge_engine(spine, engine, allow_insert=False)
    return spine


def _order_columns(columns: list[_Column], geometry_engine_ids: list[str]) -> list[_Column]:
    """Order positions within a column by a geometry-bearing engine's word (y, x):
    only engines that carry per-word boxes anchor reading order (arch A S4). Surya
    is the layout authority for zones/columns but is line-level, so it cannot anchor
    word order. A position attested only by geometry-less engines inherits the
    previous geometry position's key (stable sort keeps it in its aligned place)
    instead of collapsing to (0, 0)."""
    keyed: list[tuple[tuple[float, float], int, _Column]] = []
    last_key = (0.0, 0.0)
    for idx, column in enumerate(columns):
        geo_key: tuple[float, float] | None = None
        for eid in geometry_engine_ids:
            token = column.attestations.get(eid)
            if token is not None and token.y is not None and token.x is not None:
                geo_key = (token.y, token.x)
                break
        if geo_key is None:
            geo_key = last_key
        else:
            last_key = geo_key
        keyed.append((geo_key, idx, column))
    keyed.sort(key=lambda t: (t[0], t[1]))
    return [column for _, _, column in keyed]


def _detect_merges(columns: list[_Column], engines: list[_Engine]) -> None:
    """Reclassify an engine's exact token as a merge (n:1) when it absorbed an
    adjacent slot that the engine skipped -- i.e. the token matches the
    concatenation of the two slots strictly better than its own slot alone. The
    tight inequality stops a genuine single-word token (a substring of the
    concatenation) being mis-flagged. Operates on reading-ordered columns and
    mutates the shared logical token in place."""
    for engine in engines:
        eid = engine.engine_id
        for i, column in enumerate(columns):
            token = column.attestations.get(eid)
            if token is None or token.span_type != "exact":
                continue
            own = confusion_distance(column.rep_key, token.key)
            for neighbour in (i - 1, i + 1):
                if not 0 <= neighbour < len(columns):
                    continue
                if eid in columns[neighbour].attestations:
                    continue                       # engine attested the neighbour; not absorbed
                left, right = (neighbour, i) if neighbour < i else (i, neighbour)
                concat = columns[left].rep_key + columns[right].rep_key
                merged_distance = confusion_distance(concat, token.key)
                if merged_distance <= SAME_SLOT_THRESHOLD and merged_distance < own:
                    token.span_type = "merge"
                    token.relation = "n:1"
                    break


# --------------------------------------------------------------------------- #
# Script detection (text-level Unicode block; image-level deferred to surya).
# --------------------------------------------------------------------------- #


def _script_label(text: str) -> str:
    blocks = set()
    for ch in text:
        if ch.isspace() or not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        if name.startswith("GREEK"):
            blocks.add("greek")
        elif name.startswith("HEBREW"):
            blocks.add("hebrew")
        elif name.startswith("COPTIC"):
            blocks.add("coptic")
        elif name.startswith("LATIN"):
            blocks.add("latin")
    if not blocks:
        return "unknown"
    if len(blocks) > 1:
        return "mixed"
    label = blocks.pop()
    return label if label in _SCRIPT_LABELS else "unknown"


def _routing_for(label: str) -> str:
    if label in {"greek", "hebrew", "coptic"}:
        return "biblical-language-lane"
    if label == "mixed":
        return "non-latin-review"
    return "normal-latin"


def _build_script(rep_text: str) -> dict:
    label = _script_label(rep_text)
    routing = _routing_for(label)
    assert routing in _SCRIPT_ROUTING
    return {
        # Un-tuned: the surya glyph classifier (image layer) is downstream; here
        # the image-level label mirrors the Unicode-block result, method-flagged.
        "image_level": {"label": label, "confidence": 1.0, "method": "unicode-block-fallback"},
        "text_level": {"label": label, "method": "unicode-block"},
        "routing": routing,
    }


# --------------------------------------------------------------------------- #
# Stage S9: emit the WCT page.
# --------------------------------------------------------------------------- #


def _conf_aggregation(token: _LogicalToken) -> str:
    if len(token.source_spans) > 1:
        return "min"
    return "single"


def _candidate_sets(column: _Column) -> tuple[list[dict], dict[str, str]]:
    """Group attestations by candidate_key -> candidate_set + engine->candidate_id."""
    groups: dict[str, list[tuple[str, _LogicalToken]]] = {}
    for engine_id, token in column.attestations.items():
        groups.setdefault(token.key, []).append((engine_id, token))
    # Order: more attesters first, then key (deterministic).
    ordered_keys = sorted(groups, key=lambda k: (-len(groups[k]), k))
    candidates: list[dict] = []
    engine_to_candidate: dict[str, str] = {}
    for index, key in enumerate(ordered_keys, start=1):
        members = groups[key]
        candidate_id = f"cand_{index:03d}"
        rep_token = members[0][1]
        candidates.append({
            "candidate_id": candidate_id,
            "raw_reading": rep_token.raw_reading,
            "candidate_key": key,
            "normalisation_applied": rep_token.normalisation_applied,
            "attesting_engines": sorted(e_id for e_id, _ in members),
            "_member_engines": [e_id for e_id, _ in members],
        })
        for engine_id, _ in members:
            engine_to_candidate[engine_id] = candidate_id
    return candidates, engine_to_candidate


def _hyphenation(column: _Column) -> dict:
    evidence = []
    has_line_break = False
    for engine_id, token in column.attestations.items():
        if token.hyphen_evidence and token.hyphen_evidence["boundary_type"] == "line_break":
            has_line_break = True
            evidence.append({
                "engine": engine_id,
                "token_ids": token.hyphen_evidence["engine_token_ids"],
                "raw_tokens": token.hyphen_evidence["raw_tokens"],
            })
    if has_line_break:
        return {
            "hyphenation_status": "ambiguous",
            "raw_line_break_evidence": evidence,
            "hypothesis_ids": ["h_joined", "h_unjoined"],
        }
    return {"hyphenation_status": "none", "raw_line_break_evidence": [], "hypothesis_ids": []}


def _reference_bbox(column: _Column, fallback: dict) -> tuple[dict, str]:
    """Reference box = union of the attesting engines' word boxes. A position
    attested only by geometry-less engines has no word boxes -- fall back to the
    body column zone box (coarse: "somewhere in this column") and flag the source."""
    xs0, ys0, xs1, ys1 = [], [], [], []
    for token in column.attestations.values():
        for span in token.source_spans:
            b = span.bbox
            xs0.append(b["x"]); ys0.append(b["y"])
            xs1.append(b["x"] + b["w"]); ys1.append(b["y"] + b["h"])
    if not xs0:
        nat = fallback["_native"]
        return {"x": nat["x"], "y": nat["y"], "w": nat["w"], "h": nat["h"]}, "body-column-zone-fallback"
    x, y = min(xs0), min(ys0)
    return {"x": x, "y": y, "w": max(xs1) - x, "h": max(ys1) - y}, "geometry-engine-word-union"


def build_wct_page(
    renderings: list[dict],
    *,
    work_id: str,
    volume_id: str,
    page_id: str,
    source_image: dict,
    canonical_leaf_id: int | None = None,
    edition_page_key: dict | None = None,
    layout_authority: str = "geometric",
) -> dict:
    """Build one word-confusion-table-v1 page from per-engine rendering-v1 records.

    ``canonical_leaf_id`` (R4b) is the engine-agnostic primary-scan leaf coordinate
    -- the first-class cross-engine / cross-stage page-level join key. It is emitted
    as a first-class field when supplied; callers with no leaf (JE, Track-C, the
    reviewer server, s3_reconciler) omit it and key on ``page_id``/filename as
    before. ``page_id`` stays display/provenance (design SS2), never the join key.
    """
    if not renderings:
        raise ValueError("no renderings supplied -- page fails the S0 integrity gate")

    if layout_authority == "surya":
        surya = _surya_rendering(renderings)
        dims = surya["pages"][0]["page_dimensions_native"]
        image_size = [dims["width"], dims["height"]]
        zones = _build_zones(surya)
        layout_authority_block = {
            "tool": "surya",
            "model_version": surya["engine_version"],
            "status": "rendered",
        }
    elif layout_authority == "geometric":
        ann_path = REPO_ROOT / "reports" / "layout-annotations" / volume_id / f"{page_id}.json"
        if ann_path.exists():
            try:
                ann = json.loads(ann_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"malformed annotation file {ann_path}: {exc}") from exc
            zones = _zones_from_annotation(ann)
            if not zones:
                raise LayoutEscalation(page_id, ["annotation-no-body-zones"])
            dims = _page_dimensions(renderings)
            image_size = [dims["width"], dims["height"]]
            layout_authority_block = {
                "tool": "manual-annotation",
                "model_version": "reviewer-v1",
                "status": "annotation-override",
            }
        else:
            zones, result = _geometric_zones(renderings)
            if result.escalate:
                suryas = [r for r in renderings if r["engine_family"] == "surya"]
                if not suryas:
                    raise LayoutEscalation(page_id, result.flags)
                surya = _surya_rendering(renderings)
                dims = surya["pages"][0]["page_dimensions_native"]
                image_size = [dims["width"], dims["height"]]
                zones = _build_zones(surya)
                layout_authority_block = {
                    "tool": "surya",
                    "model_version": surya["engine_version"],
                    "status": "escalated-fallback",
                }
            else:
                dims = _page_dimensions(renderings)
                image_size = [dims["width"], dims["height"]]
                layout_authority_block = {
                    "tool": "geometric",
                    "model_version": "consensus-geometry-v1",
                    "status": "rendered",
                }
    else:
        raise ValueError(f"unknown layout_authority {layout_authority!r}")

    body_zones = [z for z in zones if z["zone_type"] == "body"] or zones[:1]

    engines: list[_Engine] = []
    tokens_by_column: dict[str, dict[int, list[_LogicalToken]]] = {}
    for rendering in renderings:
        identity = _engine_identity(rendering)
        has_geometry = _engine_has_word_geometry(rendering)
        engine = _Engine(**identity, has_geometry=has_geometry)
        tokens_by_column[engine.engine_id] = _engine_body_tokens_by_column(
            rendering, body_zones, has_geometry
        )
        engines.append(engine)
    engines_by_id = {e.engine_id: e for e in engines}
    all_engine_ids = sorted(e.engine_id for e in engines)
    geometry_engine_ids = [e.engine_id for e in engines if e.has_geometry]
    # Engines with body text anywhere on the page (the comparable-engine set is
    # page-level, not per-column -- an engine with tokens in only one column is
    # still comparable at every body position).
    comparable_engines = sorted(
        eid for eid, cols in tokens_by_column.items() if any(cols.values())
    )

    # Process body columns left-to-right; reading order concatenates the columns
    # (left column top-to-bottom, then right). Each column numbers its own lines.
    positions: list[dict] = []
    reading_order: list[str] = []
    for body_zone in body_zones:
        column_index = body_zone["column"]
        for engine in engines:
            engine.tokens = tokens_by_column[engine.engine_id].get(column_index, [])
        columns = _align_engines(engines)
        columns = _order_columns(columns, geometry_engine_ids)
        _detect_merges(columns, engines)
        line_order = -1
        last_y: float | None = None
        position_in_line = -1
        for column in columns:
            if not column.attestations:
                continue
            ref, ref_source = _reference_bbox(column, body_zone)
            if last_y is None or abs(ref["y"] - last_y) > LINE_BAND_PX:
                line_order += 1
                position_in_line = 0
                last_y = ref["y"]
            else:
                position_in_line += 1
            position = _emit_position(
                column, engines_by_id, all_engine_ids, body_zone, comparable_engines,
                volume_id, page_id, line_order, position_in_line, ref, ref_source,
            )
            positions.append(position)
            reading_order.append(position["position_id"])

    page = {
        "schema_type": "word_confusion_table",
        "schema_version": "word-confusion-table-v1",
        "work_id": work_id,
        "volume_id": volume_id,
        "page_id": page_id,
        "source_image": dict(source_image),
        "coordinate_unit": "pixel",
        "coordinate_frame": "source_image",
        "image_size": image_size,
        "layout_authority": layout_authority_block,
        "available_engines": [_engine_ref(e) for e in engines],
        "zones": [_public_zone(z) for z in zones],
        "reading_order": reading_order,
        "positions": positions,
        "layer1_ops": _layer1_ops(),
    }
    if edition_page_key is not None:
        page["edition_page_key"] = dict(edition_page_key)
    # R5: a WCT page is keyed on the leaf, or explicitly exempt (recovered-gap /
    # non-body / 1:N duplicate-sha) -- exactly one (oneOf).
    set_leaf_or_exempt(page, canonical_leaf_id)
    return page


def _engine_ref(engine: _Engine) -> dict:
    return {
        "engine_id": engine.engine_id,
        "family": engine.family,
        "lineage": engine.lineage,
        "engine_version": engine.engine_version,
        "engine_run_id": engine.engine_run_id,
    }


def _public_zone(zone: dict) -> dict:
    return {k: v for k, v in zone.items() if not k.startswith("_")}


def _layer1_ops() -> list[dict]:
    stages = [
        ("S0", "integrity-gate", "confirm available engines; absent != skip"),
        ("S3", "column-assign", "token to surya body column zone by nearest median centre"),
        ("S7", "confusion-network", "progressive MSA; geometry engines anchor, geometry-less corroborate"),
        ("S9", "assembly", "emit word-confusion-table-v1 page"),
    ]
    return [
        {"op_id": f"op_{i:03d}", "stage": stage, "tool": tool, "detail": detail}
        for i, (stage, tool, detail) in enumerate(stages, start=1)
    ]


def _emit_position(
    column: _Column,
    engines_by_id: dict[str, _Engine],
    all_engine_ids: list[str],
    body_zone: dict,
    comparable_engines: list[str],
    volume_id: str,
    page_id: str,
    line_order: int,
    position_in_line: int,
    ref: dict,
    ref_source: str,
) -> dict:
    zone_type = body_zone["zone_type"]
    track_id = body_zone["track_id"]
    column_num = body_zone["column"]
    line_id = f"{body_zone['zone_id']}:l{line_order:03d}"
    position_id = (
        f"{volume_id}:{page_id}:{track_id}:l{line_order:03d}:p{position_in_line:03d}"
    )

    candidates, engine_to_candidate = _candidate_sets(column)
    attesting_ids = set(column.attestations)

    span_records: list[dict] = []
    families_by_engine = {e_id: eng.family for e_id, eng in engines_by_id.items()}
    # Attesting engines first, then skips for available engines that reached the
    # body track but produced nothing here.
    for engine_id, token in sorted(column.attestations.items()):
        span_records.append(
            _attesting_span_record(engine_id, token, engines_by_id, engine_to_candidate)
        )
    for engine_id in all_engine_ids:
        if engine_id in attesting_ids:
            continue
        # Every engine that RAN (is in available_engines) but did not attest here
        # is a skip -- including an engine with zero body tokens, which produced
        # nothing where it could have. Dropping it would leave it counting in the
        # coverage denominator with no span record (arch A section 5; Codex A1).
        span_records.append(_skip_span_record(engine_id, engines_by_id))

    comparable = list(comparable_engines)
    rep_text = candidates[0]["candidate_key"] if candidates else ""
    for candidate in candidates:
        candidate["attesting_families"] = sorted({
            families_by_engine[e_id] for e_id in candidate.pop("_member_engines")
        })

    available = sorted(all_engine_ids)
    coverage = len(attesting_ids) / len(available) if available else 0.0
    alignment_confidence = round(min(0.99, 0.5 + 0.5 * coverage), 4)

    return {
        "position_id": position_id,
        "zone": {
            "zone_id": body_zone["zone_id"],
            "zone_type": zone_type,
            "track_id": track_id,
            "column": column_num,
            "line_id": line_id,
            "line_order": line_order,
            "position_order": position_in_line,
        },
        "reference_bbox": ref,
        "reference_bbox_source": ref_source,
        "hyphenation": _hyphenation(column),
        "script": _build_script(rep_text),
        "candidate_set": candidates,
        "span_records": span_records,
        "available_engines": available,
        "comparable_engines": comparable,
        "unassigned_engines": [],
        "alignment_confidence": alignment_confidence,
    }


def _attesting_span_record(
    engine_id: str,
    token: _LogicalToken,
    engines_by_id: dict[str, _Engine],
    engine_to_candidate: dict[str, str],
) -> dict:
    engine = engines_by_id[engine_id]
    candidate_id = engine_to_candidate.get(engine_id)
    # A geometry-less engine attests with no source span, so key the id off its
    # candidate + normalised text instead of a (missing) source token id.
    id_suffix = token.source_spans[0].token_id[-12:] if token.source_spans else f"nogeom_{token.key}"
    record = {
        "span_record_id": f"span_{engine_id}_{id_suffix}",
        "engine_id": engine_id,
        "family": engine.family,
        "lineage": engine.lineage,
        "engine_version": engine.engine_version,
        "engine_run_id": engine.engine_run_id,
        "candidate_id": candidate_id,
        "token_span_type": token.span_type,
        "segmentation_relation": token.relation,
        "raw_text": token.raw_reading,
        "normalized_text": token.key,
        "was_normalized": token.raw_reading != token.key,
        "source_spans": [
            _public_source_span(span) for span in token.source_spans
        ],
        "raw_confidence": token.confidence,
        "calibrated_confidence": None,
        "visual_distance_to_candidate": round(confusion_distance(token.key, token.key), 4),
        "raw_confidence_aggregation": _conf_aggregation(token),
    }
    return record


def _public_source_span(span: _SourceSpan) -> dict:
    return {
        "token_id": span.token_id,
        "text": span.text,
        "bbox": span.bbox,
        "line_id": span.line_id,
    }


def _skip_span_record(engine_id: str, engines_by_id: dict[str, _Engine]) -> dict:
    engine = engines_by_id[engine_id]
    return {
        "span_record_id": f"span_{engine_id}_skip",
        "engine_id": engine_id,
        "family": engine.family,
        "lineage": engine.lineage,
        "engine_version": engine.engine_version,
        "engine_run_id": engine.engine_run_id,
        "candidate_id": None,
        "token_span_type": "skip",
        "segmentation_relation": "gap",
        "source_spans": [],
        "raw_confidence": None,
        "calibrated_confidence": None,
        "raw_confidence_aggregation": "none",
    }
