"""
Cloud OCR runner -- GCV, Textract, and Azure for Schaff-Herzog page images.

Reads page JPEGs from raw/internet-archive/schaff-herzog-pages/vol_NN/ and
writes per-engine sidecar JSON alongside each image.

CLI usage:
  py -3 build/tools/run_cloud_ocr.py --volume 1 --engines gcv,textract,azure --pages all
  py -3 build/tools/run_cloud_ocr.py --volume 3 --engines gcv --pages 42-49 --dry-run
  py -3 build/tools/run_cloud_ocr.py --volume 1 --parallel
"""

import argparse
import json
import logging
import os
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

from PIL import Image as _PILImage

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parents[2]
RAW_PAGES = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
SECRETS = REPO_ROOT / "secrets"
QUOTA_STATE = REPO_ROOT / "build" / "tools" / "quota_state.json"
QUOTA_POLICY = REPO_ROOT / "build" / "tools" / "quota_policy.json"
LOG_FILE = REPO_ROOT / "logs" / "cloud_ocr.log"
AZURE_OUTPUT_DIR = (
    REPO_ROOT / "data" / "reference" / "schaff" / "encyclopedia" / "1908-1914" / "azure-v1"
)

DRY_RUN = False  # set by --dry-run CLI flag; used in main() via if DRY_RUN:

logger = logging.getLogger("run_cloud_ocr")


def _setup_logging() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class QuotaCapError(Exception):
    """Monthly soft cap reached; no quota was consumed."""


class FreeTrialExpiredError(Exception):
    """Textract 90-day free tier has expired."""


# ---------------------------------------------------------------------------
# Azure rate-limit and retry helpers  (Azure F0: 20 transactions/min)
# ---------------------------------------------------------------------------
_AZURE_MIN_INTERVAL: float = 3.05   # seconds between calls; 60/20 + 2% buffer
_AZURE_RETRY_CODES = frozenset([500, 502, 503])
_AZURE_RETRY_DELAYS = [2, 4, 8]     # seconds; API-04 exponential backoff
_AZURE_RETRY_AFTER_CAP = 300        # abort 429 if Retry-After exceeds this
_azure_lock = threading.Lock()
_azure_last_call: float = 0.0       # monotonic timestamp of last Azure API call


def _azure_rate_limit() -> None:
    """Block until >= _AZURE_MIN_INTERVAL has elapsed since the previous Azure call."""
    global _azure_last_call
    with _azure_lock:
        elapsed = time.monotonic() - _azure_last_call
        if elapsed < _AZURE_MIN_INTERVAL:
            time.sleep(_AZURE_MIN_INTERVAL - elapsed)
        _azure_last_call = time.monotonic()


def _azure_call_with_retry(call_fn) -> dict:
    """API-04 retry: 429+Retry-After (abort >300s); 500/502/503 at 2/4/8s backoff.

    HTTP 403 (Azure quota exhausted) raises QuotaCapError immediately — no
    retry, no partial sidecar. This propagates through process_page to
    run_volume where the azure engine is added to capped and skipped for all
    remaining pages in the run.
    """
    for attempt in range(4):  # initial + 3 retries
        try:
            return call_fn()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                ra = int((exc.headers or {}).get("Retry-After", 60))
                if ra > _AZURE_RETRY_AFTER_CAP:
                    raise RuntimeError(
                        f"[azure] 429 Retry-After={ra}s exceeds cap {_AZURE_RETRY_AFTER_CAP}s"
                    ) from exc
                logger.warning("[azure] 429, retrying in %ds (attempt %d/4)", ra, attempt + 1)
                time.sleep(ra)
            elif exc.code == 403:
                # Azure monthly quota exhausted — hard stop, no retry.
                # run_volume catches QuotaCapError and marks the engine as
                # capped so no further pages are attempted this run.
                raise QuotaCapError(
                    "[azure] HTTP 403: monthly quota exhausted"
                ) from exc
            elif exc.code in _AZURE_RETRY_CODES:
                if attempt == 3:
                    raise RuntimeError(
                        f"[azure] HTTP {exc.code} after 4 attempts"
                    ) from exc
                delay = _AZURE_RETRY_DELAYS[attempt]
                logger.warning(
                    "[azure] HTTP %d, retry in %ds (attempt %d/4)", exc.code, delay, attempt + 1
                )
                time.sleep(delay)
            else:
                raise
    raise RuntimeError("[azure] exhausted retries")


# ---------------------------------------------------------------------------
# Quota helpers  (mirror run_b22_probe_matrix.py pattern)
# ---------------------------------------------------------------------------
def load_quota_state() -> dict:
    if QUOTA_STATE.exists():
        return json.loads(QUOTA_STATE.read_text(encoding="utf-8"))
    return {}


def save_quota_state(state: dict) -> None:
    QUOTA_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUOTA_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, QUOTA_STATE)


def load_quota_policy() -> dict:
    return json.loads(QUOTA_POLICY.read_text(encoding="utf-8"))


def quota_ok(state: dict, policy: dict, provider: str) -> bool:
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    pstate = state.get(provider, {})
    if pstate.get("month") != current_month:
        return True
    used = pstate.get("pages_used_this_month", 0)
    cap = policy.get("providers", {}).get(provider, {}).get("monthly_soft_cap", 0)
    return used < cap


def increment_quota(state: dict, provider: str, count: int = 1) -> dict:
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    pstate = state.setdefault(provider, {})
    if pstate.get("month") != current_month:
        pstate["pages_used_this_month"] = 0
        pstate["month"] = current_month
    pstate["pages_used_this_month"] = pstate.get("pages_used_this_month", 0) + count
    return state


# ---------------------------------------------------------------------------
# Format metadata
# ---------------------------------------------------------------------------
# Sidecar format version. Bump when a non-backward-compatible field shape change
# lands. coordinate_unit/coordinate_frame self-describe the bbox semantics so a
# future reader doesn't have to guess.
SIDECAR_FORMAT_VERSION = 1


def _format_metadata() -> dict:
    """Per-engine metadata shared across every sidecar this module writes."""
    return {
        "format_version": SIDECAR_FORMAT_VERSION,
        "coordinate_unit": "pixel",
        "coordinate_frame": "source_image",
    }


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _polygon_to_bbox(polygon: list[dict]) -> dict | None:
    """Convert Azure 4-point boundingPolygon to axis-aligned {x, y, w, h} bbox."""
    if not polygon:
        return None
    xs = [p["x"] for p in polygon]
    ys = [p["y"] for p in polygon]
    x0, y0 = min(xs), min(ys)
    return {"x": x0, "y": y0, "w": max(xs) - x0, "h": max(ys) - y0}


def _union_bbox(bboxes: list[dict]) -> dict | None:
    """Smallest axis-aligned bbox enclosing all input bboxes."""
    valid = [b for b in bboxes if b]
    if not valid:
        return None
    x0 = min(b["x"] for b in valid)
    y0 = min(b["y"] for b in valid)
    x1 = max(b["x"] + b["w"] for b in valid)
    y1 = max(b["y"] + b["h"] for b in valid)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def _jpeg_size_from_header(path: Path) -> list[int]:
    """Return [width, height] from JPEG SOF metadata without decoding pixels."""
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    with path.open("rb") as fh:
        if fh.read(2) != b"\xff\xd8":
            return []
        while True:
            marker_prefix = fh.read(1)
            if not marker_prefix:
                return []
            if marker_prefix != b"\xff":
                continue
            marker = fh.read(1)
            while marker == b"\xff":
                marker = fh.read(1)
            if not marker:
                return []
            marker_value = marker[0]
            if marker_value in {0xD8, 0xD9}:
                continue
            segment_length_bytes = fh.read(2)
            if len(segment_length_bytes) != 2:
                return []
            segment_length = int.from_bytes(segment_length_bytes, "big")
            if segment_length < 2:
                return []
            if marker_value in sof_markers:
                frame_header = fh.read(5)
                if len(frame_header) != 5:
                    return []
                height = int.from_bytes(frame_header[1:3], "big")
                width = int.from_bytes(frame_header[3:5], "big")
                return [width, height] if width > 0 and height > 0 else []
            fh.seek(segment_length - 2, os.SEEK_CUR)


def _group_words_into_lines(words: list[dict], y_tolerance_factor: float = 0.5) -> list[list[dict]]:
    """Cluster words into physical printed lines by y-coordinate proximity.

    Used to reconstruct line structure from engines that don't expose lines
    natively (e.g. GCV, which only returns blocks/paragraphs/words). Two words
    belong to the same physical line if their y-centers are within
    y_tolerance_factor * word_height of the running line center.
    """
    if not words:
        return []
    sorted_words = sorted(
        words,
        key=lambda w: (w["bbox"]["y"] + w["bbox"]["h"] / 2.0, w["bbox"]["x"]),
    )
    lines: list[list[dict]] = []
    current: list[dict] = []
    current_y: float | None = None
    for w in sorted_words:
        wy = w["bbox"]["y"] + w["bbox"]["h"] / 2.0
        wh = w["bbox"]["h"] or 1
        if current_y is None or abs(wy - current_y) <= wh * y_tolerance_factor:
            current.append(w)
            current_y = sum(
                c["bbox"]["y"] + c["bbox"]["h"] / 2.0 for c in current
            ) / len(current)
        else:
            current.sort(key=lambda c: c["bbox"]["x"])
            lines.append(current)
            current = [w]
            current_y = wy
    if current:
        current.sort(key=lambda c: c["bbox"]["x"])
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Sidecar helpers
# ---------------------------------------------------------------------------
def write_sidecar(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _sidecar_path(jpeg_path: Path, engine: str) -> Path:
    return jpeg_path.parent / (jpeg_path.stem + f".{engine}.json")


def _raw_response_path(jpeg_path: Path, engine: str) -> Path:
    """Path for the raw API response, sibling to the parsed sidecar."""
    return jpeg_path.parent / (jpeg_path.stem + f".{engine}.raw.json")


def _write_raw_response(jpeg_path: Path, engine: str, raw: dict | list | str) -> None:
    """Persist the unmodified API response next to the parsed sidecar.

    Storing the raw response is cheap relative to re-OCRing. Any field the
    parser doesn't currently extract stays available for future enrichment —
    no need to re-call the API to recover hyphenation breaks (GCV),
    paragraph semantics (DocInt), or any other field downstream.
    """
    path = _raw_response_path(jpeg_path, engine)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".raw.json.tmp")
    if isinstance(raw, str):
        tmp.write_text(raw, encoding="utf-8")
    else:
        tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_env_file(path: Path) -> dict:
    env_vars: dict = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env_vars[k.strip()] = v.strip().strip('"')
    return env_vars


# ---------------------------------------------------------------------------
# OCR drivers
# ---------------------------------------------------------------------------
def ocr_gcv(jpeg_path: Path, state: dict, policy: dict, *, _client=None) -> dict:
    """Google Cloud Vision DOCUMENT_TEXT_DETECTION. Raises QuotaCapError at soft cap."""
    provider = "google_cloud_vision"
    if not quota_ok(state, policy, provider):
        raise QuotaCapError(f"GCV monthly soft cap reached ({provider})")

    with jpeg_path.open("rb") as f:
        content = f.read()

    if _client is None:
        sa_path = SECRETS / "gcp-vision-sa.json"
        if not sa_path.exists():
            raise RuntimeError("[GCV] gcp-vision-sa.json not found in secrets/")
        from google.cloud import vision  # type: ignore[import-not-found]
        from google.oauth2 import service_account  # type: ignore[import-not-found]
        creds = service_account.Credentials.from_service_account_file(
            str(sa_path), scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        _client = vision.ImageAnnotatorClient(credentials=creds)
        image = vision.Image(content=content)
    else:
        # Test injection: mock client receives raw bytes; no SDK import needed.
        image = content

    increment_quota(state, provider)
    save_quota_state(state)

    response = _client.document_text_detection(image=image)
    if response.error.message:
        raise RuntimeError(f"GCV API error: {response.error.message}")

    # Persist raw response. GCV returns a protobuf; convert to dict.
    try:
        from google.protobuf.json_format import MessageToDict  # type: ignore[import-not-found]
        raw_dict = MessageToDict(response._pb if hasattr(response, "_pb") else response)
        _write_raw_response(jpeg_path, "gcv", raw_dict)
    except Exception as exc:
        logger.warning("[gcv] could not persist raw response for %s: %s", jpeg_path.name, exc)

    raw_text: str = response.full_text_annotation.text
    image_size: list[int] = []
    blocks_out: list[dict] = []
    all_confs: list[float] = []

    # GCV BlockType enum -> string label. Block-level type lets us flag
    # PICTURE / TABLE / RULER / BARCODE regions that would otherwise OCR as noise.
    # Enum values: 0=UNKNOWN, 1=TEXT, 2=TABLE, 3=PICTURE, 4=RULER, 5=BARCODE.
    _GCV_BLOCK_TYPES = {0: "UNKNOWN", 1: "TEXT", 2: "TABLE",
                        3: "PICTURE", 4: "RULER", 5: "BARCODE"}
    # Symbol.property.detectedBreak.type enum -> string label.
    # 0=UNKNOWN, 1=SPACE, 2=SURE_SPACE, 3=EOL_SURE_SPACE, 4=HYPHEN, 5=LINE_BREAK.
    _GCV_BREAKS = {0: "UNKNOWN", 1: "SPACE", 2: "SURE_SPACE",
                   3: "EOL_SURE_SPACE", 4: "HYPHEN", 5: "LINE_BREAK"}

    # GCV returns page -> block -> paragraph -> word. Paragraphs are semantic
    # groupings that can span multiple printed lines, so we collect all words
    # per block and re-cluster them into physical lines by y-coordinate. This
    # keeps "line" semantically consistent with Azure/Textract/Tesseract.
    for pg in response.full_text_annotation.pages:
        if not image_size:
            image_size = [pg.width, pg.height]
        for block in pg.blocks:
            block_polygon = [
                {"x": int(v.x), "y": int(v.y)}
                for v in block.bounding_box.vertices
            ]
            block_type_id = int(getattr(block, "block_type", 0))
            block_type = _GCV_BLOCK_TYPES.get(block_type_id, "UNKNOWN")
            block_words: list[dict] = []
            for para in block.paragraphs:
                for word in para.words:
                    text = "".join(s.text for s in word.symbols)
                    conf = float(getattr(word, "confidence", 0.0)) * 100
                    polygon = [
                        {"x": int(v.x), "y": int(v.y)}
                        for v in word.bounding_box.vertices
                    ]
                    bbox = _polygon_to_bbox(polygon)
                    if bbox is None:
                        continue
                    all_confs.append(conf)

                    # Per-word languages — list of (language_code, confidence).
                    languages: list[dict] = []
                    word_prop = getattr(word, "property", None)
                    if word_prop is not None:
                        for lang in getattr(word_prop, "detected_languages", []):
                            languages.append({
                                "language_code": getattr(lang, "language_code", ""),
                                "confidence": float(getattr(lang, "confidence", 0.0)),
                            })

                    # Break after this word — read the LAST symbol's detectedBreak.
                    # HYPHEN means the word continues on the next line (re-join target);
                    # LINE_BREAK / EOL_SURE_SPACE end the line; SPACE / SURE_SPACE
                    # are intra-line word separators.
                    break_after: str | None = None
                    if word.symbols:
                        last_sym = word.symbols[-1]
                        sym_prop = getattr(last_sym, "property", None)
                        det_break = getattr(sym_prop, "detected_break", None) if sym_prop else None
                        if det_break is not None and getattr(det_break, "type", None) is not None:
                            break_after = _GCV_BREAKS.get(int(det_break.type), "UNKNOWN")

                    word_record: dict = {
                        "text": text,
                        "confidence": round(conf, 1),
                        "bbox": bbox,
                        "bbox_polygon": polygon,
                        "low_confidence": conf < 50,
                    }
                    if languages:
                        word_record["languages"] = languages
                    if break_after:
                        word_record["break_after"] = break_after
                    block_words.append(word_record)

            lines_out: list[dict] = []
            for line_words in _group_words_into_lines(block_words):
                line_text = " ".join(w["text"] for w in line_words)
                line_bboxes = [w["bbox"] for w in line_words if w["bbox"]]
                lines_out.append({
                    "text": line_text,
                    "bbox": _union_bbox(line_bboxes),
                    "words": line_words,
                })

            if lines_out:
                block_bboxes = [ln["bbox"] for ln in lines_out if ln.get("bbox")]
                blocks_out.append({
                    "bbox": _union_bbox(block_bboxes),
                    "bbox_polygon": block_polygon,
                    "block_type": block_type,
                    "lines": lines_out,
                })

    mean_conf = sum(all_confs) / len(all_confs) if all_confs else 0.0

    return {
        **_format_metadata(),
        "engine": "google-cloud-vision",
        "engine_version": "v1",
        "run_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "image_size": image_size,
        "page_rotation": 0.0,  # GCV document_text_detection does not expose rotation
        "confidence_mean": round(mean_conf, 1),
        "raw_text": raw_text,
        "blocks": blocks_out,
    }


def ocr_textract(jpeg_path: Path, state: dict, policy: dict, *, _client=None) -> dict:
    """AWS Textract DetectDocumentText. Raises QuotaCapError or FreeTrialExpiredError."""
    provider = "aws_textract"
    if not quota_ok(state, policy, provider):
        raise QuotaCapError("Textract monthly soft cap reached")

    pstate = state.get(provider, {})
    first_used = pstate.get("first_used_date")
    if first_used:
        first_dt = date.fromisoformat(first_used)
        if (date.today() - first_dt).days > 90:
            raise FreeTrialExpiredError(
                f"Textract 90-day free tier expired (started {first_used})"
            )

    with jpeg_path.open("rb") as f:
        image_bytes = f.read()

    if _client is None:
        env_path = SECRETS / "aws-textract.env"
        if not env_path.exists():
            raise RuntimeError("[Textract] aws-textract.env not found in secrets/")
        env_vars = _read_env_file(env_path)
        import boto3  # type: ignore[import-not-found]
        _client = boto3.client(
            "textract",
            region_name=env_vars.get("AWS_DEFAULT_REGION", "us-east-1"),
            aws_access_key_id=env_vars.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=env_vars.get("AWS_SECRET_ACCESS_KEY"),
        )

    increment_quota(state, provider)
    save_quota_state(state)

    response = _client.detect_document_text(Document={"Bytes": image_bytes})
    raw_blocks = response.get("Blocks", [])
    _write_raw_response(jpeg_path, "textract", response)

    # Textract returns geometry in normalized (0-1) coordinates. We MUST know
    # the source image dimensions to project them onto pixels. If PIL cannot
    # decode the file (truncated download, wrong magic bytes), fail closed —
    # never write a sidecar with zero-pixel or fabricated coordinates. The
    # caller's partial-sidecar path will record the failure for retry.
    try:
        with _PILImage.open(jpeg_path) as _img:
            img_w, img_h = _img.size
            image_size: list[int] = [img_w, img_h]
    except Exception as exc:
        raise RuntimeError(
            f"[Textract] Cannot read image dimensions from {jpeg_path.name}: {exc}. "
            "Refusing to write sidecar with un-projected coordinates."
        ) from exc

    # Page-level rotation: Textract exposes RotationAngle on the PAGE block
    # (degrees, -180 to 180). Coordinates are reported in the rotated frame,
    # so a non-zero angle means the renderer must apply inverse rotation when
    # drawing on the un-rotated source JPEG.
    page_block = next((b for b in raw_blocks if b.get("BlockType") == "PAGE"), None)
    page_rotation = float(
        page_block.get("Geometry", {}).get("RotationAngle", 0.0)
        if page_block else 0.0
    )

    def _tx_bbox(geo: dict) -> dict | None:
        bb = geo.get("BoundingBox")
        if not bb:
            return None
        return {
            "x": round(bb["Left"] * img_w),
            "y": round(bb["Top"] * img_h),
            "w": round(bb["Width"] * img_w),
            "h": round(bb["Height"] * img_h),
        }

    def _tx_polygon(geo: dict) -> list[dict]:
        return [
            {"x": round(p["X"] * img_w), "y": round(p["Y"] * img_h)}
            for p in geo.get("Polygon", [])
        ]

    block_by_id = {b["Id"]: b for b in raw_blocks}
    lines_raw = [b for b in raw_blocks if b.get("BlockType") == "LINE"]

    all_confs: list[float] = []
    raw_lines: list[str] = []
    lines_out: list[dict] = []

    for line_block in lines_raw:
        child_ids: list[str] = []
        for rel in line_block.get("Relationships", []):
            if rel.get("Type") == "CHILD":
                child_ids = rel.get("Ids", [])
                break

        words_out: list[dict] = []
        for word_id in child_ids:
            word_block = block_by_id.get(word_id)
            if word_block is None or word_block.get("BlockType") != "WORD":
                continue
            text = word_block.get("Text", "")
            conf = float(word_block.get("Confidence", 0.0))
            geo = word_block.get("Geometry", {})
            all_confs.append(conf)
            words_out.append({
                "text": text,
                "confidence": round(conf, 1),
                "bbox": _tx_bbox(geo),
                "bbox_polygon": _tx_polygon(geo),
                "low_confidence": conf < 50,
                "text_type": word_block.get("TextType", "PRINTED"),  # PRINTED | HANDWRITING
            })

        if words_out:
            line_text = line_block.get("Text", " ".join(w["text"] for w in words_out))
            line_geo = line_block.get("Geometry", {})
            raw_lines.append(line_text)
            lines_out.append({
                "text": line_text,
                "bbox": _tx_bbox(line_geo),
                "bbox_polygon": _tx_polygon(line_geo),
                "words": words_out,
            })

    mean_conf = sum(all_confs) / len(all_confs) if all_confs else 0.0

    # Textract has no native block grouping in detect_document_text — one block per page.
    blocks_out: list[dict] = []
    if lines_out:
        line_bboxes = [ln["bbox"] for ln in lines_out if ln.get("bbox")]
        blocks_out.append({"bbox": _union_bbox(line_bboxes), "lines": lines_out})

    # Use Textract's actual model version when reported; fall back to label.
    model_version = response.get("DetectDocumentTextModelVersion", "detect-document-text-v1")

    return {
        **_format_metadata(),
        "engine": "aws-textract",
        "engine_version": model_version,
        "run_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "image_size": image_size,
        "page_rotation": page_rotation,
        "confidence_mean": round(mean_conf, 1),
        "raw_text": "\n".join(raw_lines),
        "blocks": blocks_out,
    }


def ocr_azure(jpeg_path: Path, state: dict, policy: dict, *, _http_post=None) -> dict:
    """Azure Image Analysis v4.0 Read — synchronous, returns 200 directly.

    Endpoint: POST {endpoint}/computervision/imageanalysis:analyze?features=read&api-version=2024-02-01
    Response: readResult.blocks[].lines[].words[].confidence (0-1 scale)
    Test hook (_http_post): called with (url, img_bytes, key), return value used
    directly as the result dict.

    Quota is enforced by Azure: HTTP 403 from _azure_call_with_retry raises
    QuotaCapError, which run_volume catches to stop further azure calls.
    No local quota counter is maintained for Azure AI Vision — the API
    response is the authoritative signal (the local quota_state.json counter
    proved unreliable in practice; see cloud_ocr.log for actual usage history).
    """
    # state and policy are accepted for API compatibility with other drivers
    # but are not used — Azure quota tracking is API-driven, not local.

    env_path = SECRETS / "azure-vision.env"
    if not env_path.exists():
        raise RuntimeError("[Azure] azure-vision.env not found in secrets/")

    env_vars = _read_env_file(env_path)
    endpoint = env_vars.get("AZURE_VISION_ENDPOINT", "")
    key = env_vars.get("AZURE_VISION_KEY", "")
    if not endpoint or not key:
        raise RuntimeError("[Azure] AZURE_VISION_ENDPOINT or AZURE_VISION_KEY missing")

    with jpeg_path.open("rb") as f:
        img_bytes = f.read()

    _azure_rate_limit()

    url = (
        endpoint.rstrip("/")
        + "/computervision/imageanalysis:analyze"
        + "?features=read&api-version=2024-02-01"
    )

    def _make_call() -> dict:
        if _http_post is not None:
            return _http_post(url, img_bytes, key)
        import urllib.request as _ureq
        req = _ureq.Request(
            url,
            data=img_bytes,
            headers={
                "Ocp-Apim-Subscription-Key": key,
                "Content-Type": "application/octet-stream",
            },
            method="POST",
        )
        with _ureq.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    result = _azure_call_with_retry(_make_call)
    _write_raw_response(jpeg_path, "azure", result)

    try:
        with _PILImage.open(jpeg_path) as _img:
            image_size: list[int] = list(_img.size)
    except Exception:
        image_size = _jpeg_size_from_header(jpeg_path)

    blocks: list[dict] = []
    all_confs: list[float] = []
    raw_lines: list[str] = []
    api_version = result.get("modelVersion", "2024-02-01")

    for raw_block in result.get("readResult", {}).get("blocks", []):
        lines: list[dict] = []
        for raw_line in raw_block.get("lines", []):
            words: list[dict] = []
            for word in raw_line.get("words", []):
                conf = float(word.get("confidence", 0.0)) * 100
                word_polygon = word.get("boundingPolygon", [])
                bbox = _polygon_to_bbox(word_polygon)
                text = word.get("text", "")
                if not text:
                    continue
                all_confs.append(conf)
                words.append({
                    "text": text,
                    "confidence": round(conf, 1),
                    "bbox": bbox,
                    "bbox_polygon": word_polygon,
                    "low_confidence": conf < 50,
                })
            if words:
                line_text = raw_line.get("text", " ".join(w["text"] for w in words))
                line_polygon = raw_line.get("boundingPolygon", [])
                line_bbox = _polygon_to_bbox(line_polygon)
                lines.append({"text": line_text, "bbox": line_bbox, "bbox_polygon": line_polygon, "words": words})
                raw_lines.append(line_text)
        if lines:
            line_bboxes = [ln["bbox"] for ln in lines if ln.get("bbox")]
            blocks.append({"bbox": _union_bbox(line_bboxes), "lines": lines})
        raw_lines.append("")

    mean_conf = sum(all_confs) / len(all_confs) if all_confs else 0.0

    return {
        **_format_metadata(),
        "engine": "azure-ai-vision",
        "engine_version": api_version,
        "run_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "image_size": image_size,
        "page_rotation": 0.0,  # Image Analysis v4.0 does not expose rotation
        "confidence_mean": round(mean_conf, 1),
        "raw_text": "\n".join(raw_lines).rstrip(),
        "blocks": blocks,
    }


# ---------------------------------------------------------------------------
# Azure Document Intelligence (prebuilt-read) — async polling driver
# ---------------------------------------------------------------------------
# Document Intelligence is a separate Azure service from AI Vision. It uses an
# async submit-then-poll pattern: POST returns 202 + Operation-Location header,
# we GET that URL until status=succeeded. The operation runs server-side and
# we burn the quota the moment it's accepted, NOT per poll.
#
# Resumability (Codex Attack 7): the Operation-Location is persisted to a
# .docint-pending.json file BEFORE polling starts. If the run crashes or the
# poll times out, the next invocation finds the pending file and resumes
# polling the same operation — no second submission, no second quota charge.
# Operation URLs are valid for ~24h on Azure's side.
#
# Free tier: 500 pages/month (separate from Azure AI Vision's 5000). Reserve
# for difficult pages that AI Vision flagged as low-confidence.

_DOCINT_POLL_DELAYS = [1, 2, 2, 4, 4, 4, 8, 8, 8, 8, 8, 8, 8]  # ~75s total


def _docint_pending_path(jpeg_path: Path) -> Path:
    """File that holds the in-flight Operation-Location for this page."""
    return jpeg_path.parent / (jpeg_path.stem + ".docint-pending.json")


def _docint_polygon_to_points(polygon_flat: list, scale_x: float, scale_y: float) -> list[dict]:
    """Convert [x1,y1,x2,y2,...] flat list to [{x,y},...] in pixels.

    polygon_flat is in the page's native unit (pixel for JPEG, inch for PDF);
    scale_x and scale_y convert to source-image pixels (1.0 when already in pixels).
    """
    points: list[dict] = []
    for i in range(0, len(polygon_flat) - 1, 2):
        points.append({
            "x": round(float(polygon_flat[i]) * scale_x),
            "y": round(float(polygon_flat[i + 1]) * scale_y),
        })
    return points


def _docint_poll_operation(op_location: str, key: str, *, _http_get=None) -> dict:
    """Poll the Operation-Location URL until status=succeeded or terminal failure."""
    import urllib.request as _ureq

    for attempt, delay in enumerate(_DOCINT_POLL_DELAYS, 1):
        time.sleep(delay)
        if _http_get is not None:
            data = _http_get(op_location, key)
        else:
            req = _ureq.Request(
                op_location,
                headers={"Ocp-Apim-Subscription-Key": key},
                method="GET",
            )
            with _ureq.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))

        status = data.get("status", "").lower()
        if status == "succeeded":
            return data
        if status == "failed":
            err = data.get("error", {})
            raise RuntimeError(
                f"[DocInt] Analysis failed: {err.get('message', 'unknown error')}"
            )
        logger.debug("[DocInt] poll %d: status=%s", attempt, status)

    raise RuntimeError(
        f"[DocInt] Operation did not complete after {len(_DOCINT_POLL_DELAYS)} polls. "
        f"Pending file preserved for resume: {op_location}"
    )


def ocr_docint(
    jpeg_path: Path,
    state: dict,
    policy: dict,
    *,
    _http_post=None,
    _http_get=None,
) -> dict:
    """Azure Document Intelligence prebuilt-read — async submit + poll.

    On first call: POSTs the JPEG, persists Operation-Location to disk, polls
    until done. On resume (pending file exists): skips submission and resumes
    polling the existing operation — no quota re-charge.

    Test hooks:
        _http_post(url, img_bytes, key) -> operation_location string
        _http_get(url, key)             -> result dict (returns status=succeeded)
    """
    provider = "azure_document_intelligence"
    pending_path = _docint_pending_path(jpeg_path)

    # Credentials. DocInt and Image Analysis share a single endpoint + key
    # on a multi-service Azure AI Services resource — read from azure-vision.env.
    def _load_creds() -> tuple[str, str]:
        env_path = SECRETS / "azure-vision.env"
        if not env_path.exists():
            raise RuntimeError("[DocInt] azure-vision.env not found in secrets/")
        env_vars = _read_env_file(env_path)
        ep = env_vars.get("AZURE_VISION_ENDPOINT", "")
        k = env_vars.get("AZURE_VISION_KEY", "")
        if not ep or not k:
            raise RuntimeError(
                "[DocInt] AZURE_VISION_ENDPOINT or AZURE_VISION_KEY missing"
            )
        return ep, k

    # ---- Resume path: pending operation already submitted ----
    if pending_path.exists():
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
        op_location = pending["operation_location"]
        _, key = _load_creds()
        logger.info("[DocInt] Resuming pending operation for %s", jpeg_path.name)
        result_envelope = _docint_poll_operation(op_location, key, _http_get=_http_get)
    else:
        # ---- Fresh submission path ----
        if not quota_ok(state, policy, provider):
            raise QuotaCapError("Azure Document Intelligence monthly soft cap reached")

        endpoint, key = _load_creds()

        with jpeg_path.open("rb") as f:
            img_bytes = f.read()

        analyze_url = (
            endpoint.rstrip("/")
            + "/documentintelligence/documentModels/prebuilt-read:analyze"
            + "?api-version=2024-11-30"
        )

        if _http_post is not None:
            op_location = _http_post(analyze_url, img_bytes, key)
        else:
            import urllib.request as _ureq
            req = _ureq.Request(
                analyze_url,
                data=img_bytes,
                headers={
                    "Ocp-Apim-Subscription-Key": key,
                    "Content-Type": "application/octet-stream",
                },
                method="POST",
            )
            with _ureq.urlopen(req, timeout=60) as resp:
                op_location = (
                    resp.getheader("Operation-Location")
                    or resp.getheader("operation-location")
                )
                if not op_location:
                    raise RuntimeError(
                        "[DocInt] POST response missing Operation-Location header"
                    )

        # Persist BEFORE polling — Codex Attack 7 fix. Increment quota only after
        # we've durably recorded the operation, so a crash before the file write
        # doesn't double-charge on the next retry.
        pending_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = pending_path.with_suffix(".pending.tmp")
        tmp.write_text(json.dumps({
            "operation_location": op_location,
            "submitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "jpeg": jpeg_path.name,
        }), encoding="utf-8")
        os.replace(tmp, pending_path)

        increment_quota(state, provider)
        save_quota_state(state)

        logger.info("[DocInt] Submitted %s, polling %s", jpeg_path.name, op_location)
        result_envelope = _docint_poll_operation(op_location, key, _http_get=_http_get)

    # Persist raw response now that we have the terminal envelope.
    _write_raw_response(jpeg_path, "docint", result_envelope)

    # ---- Parse the analyzeResult ----
    analyze = result_envelope.get("analyzeResult", {})
    api_version = analyze.get("apiVersion", "2024-11-30")

    try:
        with _PILImage.open(jpeg_path) as _img:
            img_w, img_h = _img.size
            image_size: list[int] = [img_w, img_h]
    except Exception as exc:
        raise RuntimeError(
            f"[DocInt] Cannot read image dimensions from {jpeg_path.name}: {exc}"
        ) from exc

    blocks_out: list[dict] = []
    all_confs: list[float] = []
    raw_lines_text: list[str] = []
    # Aggregate rotation across pages — for single-page JPEGs there's only one.
    page_rotations: list[float] = []
    # Page-level spans (offset mapping back to analyzeResult.content).
    page_spans_out: list[list[dict]] = []
    # Per-page scale factors so paragraph regions can be projected to pixels too.
    page_scales: dict[int, tuple[float, float]] = {}

    for page in analyze.get("pages", []):
        unit = page.get("unit", "pixel")
        page_w = float(page.get("width", img_w))
        page_h = float(page.get("height", img_h))
        page_rotations.append(float(page.get("angle", 0.0)))
        page_spans_out.append(page.get("spans", []) or [])
        if unit == "pixel":
            scale_x = scale_y = 1.0
        else:
            # inch (PDF input) — scale to source-image pixels
            scale_x = img_w / page_w if page_w else 1.0
            scale_y = img_h / page_h if page_h else 1.0
        page_scales[int(page.get("pageNumber", 1))] = (scale_x, scale_y)

        # Build word records keyed by content + span for line lookup
        page_words: list[dict] = []
        for word in page.get("words", []):
            text = word.get("content", "")
            if not text:
                continue
            conf = float(word.get("confidence", 0.0)) * 100
            polygon = _docint_polygon_to_points(word.get("polygon", []), scale_x, scale_y)
            bbox = _polygon_to_bbox(polygon)
            if bbox is None:
                continue
            all_confs.append(conf)
            page_words.append({
                "text": text,
                "confidence": round(conf, 1),
                "bbox": bbox,
                "bbox_polygon": polygon,
                "low_confidence": conf < 50,
            })

        # Lines as returned by DocInt — keeps native line grouping
        lines_out: list[dict] = []
        for line in page.get("lines", []):
            line_text = line.get("content", "")
            line_polygon = _docint_polygon_to_points(line.get("polygon", []), scale_x, scale_y)
            line_bbox = _polygon_to_bbox(line_polygon)
            # Match words to this line by y-overlap with line bbox
            line_words = []
            if line_bbox is not None:
                ly0, ly1 = line_bbox["y"], line_bbox["y"] + line_bbox["h"]
                for w in page_words:
                    wy_center = w["bbox"]["y"] + w["bbox"]["h"] / 2.0
                    if ly0 <= wy_center <= ly1:
                        line_words.append(w)
                line_words.sort(key=lambda w: w["bbox"]["x"])
            raw_lines_text.append(line_text)
            lines_out.append({
                "text": line_text,
                "bbox": line_bbox,
                "bbox_polygon": line_polygon,
                "words": line_words,
            })

        if lines_out:
            line_bboxes = [ln["bbox"] for ln in lines_out if ln.get("bbox")]
            blocks_out.append({
                "bbox": _union_bbox(line_bboxes),
                "lines": lines_out,
            })

    mean_conf = sum(all_confs) / len(all_confs) if all_confs else 0.0

    # Semantic paragraphs with role classification — this is DocInt's killer
    # feature. role values: "title", "sectionHeading", "pageHeader",
    # "pageFooter", "pageNumber", "footnote" (or absent for body paragraphs).
    paragraphs_out: list[dict] = []
    for para in analyze.get("paragraphs", []):
        para_record: dict = {"content": para.get("content", "")}
        role = para.get("role")
        if role:
            para_record["role"] = role
        # boundingRegions[0] gives the polygon on the source page.
        regions = para.get("boundingRegions", []) or []
        if regions:
            r0 = regions[0]
            pg_num = int(r0.get("pageNumber", 1))
            scale_x, scale_y = page_scales.get(pg_num, (1.0, 1.0))
            polygon = _docint_polygon_to_points(r0.get("polygon", []), scale_x, scale_y)
            if polygon:
                para_record["bbox_polygon"] = polygon
                para_bbox = _polygon_to_bbox(polygon)
                if para_bbox is not None:
                    para_record["bbox"] = para_bbox
        spans = para.get("spans", []) or []
        if spans:
            para_record["spans"] = spans
        paragraphs_out.append(para_record)

    # Per-span style annotations — handwriting detection, font hints.
    styles_out: list[dict] = analyze.get("styles", []) or []

    # Full flat content text — useful for span-offset lookups against paragraphs.
    full_content = analyze.get("content", "")

    # Clean up pending marker only after successful parse — if parsing raises,
    # the next retry will find the pending file and re-poll (operation result
    # is cached server-side for 24h).
    if pending_path.exists():
        try:
            pending_path.unlink()
        except OSError:
            logger.warning("[DocInt] Could not remove pending file %s", pending_path)

    out: dict = {
        **_format_metadata(),
        "engine": "azure-document-intelligence",
        "engine_version": api_version,
        "model_id": analyze.get("modelId", "prebuilt-read"),
        "run_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "image_size": image_size,
        "page_rotation": page_rotations[0] if page_rotations else 0.0,
        "confidence_mean": round(mean_conf, 1),
        "raw_text": "\n".join(raw_lines_text),
        "content": full_content,
        "blocks": blocks_out,
    }
    if paragraphs_out:
        out["paragraphs"] = paragraphs_out
    if styles_out:
        out["styles"] = styles_out
    if any(page_spans_out):
        out["page_spans"] = page_spans_out
    return out


# ---------------------------------------------------------------------------
# Volume assembly (Azure)
# ---------------------------------------------------------------------------

def _is_partial_sidecar(path: Path) -> bool:
    """True if the sidecar was written with partial=True (driver failure)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return bool(data.get("partial"))
    except (json.JSONDecodeError, OSError):
        return False


def assemble_azure_volume_json(
    volume_num: int,
    *,
    vol_dir: Path | None = None,
    out_dir: Path | None = None,
) -> Path:
    """Read per-page azure sidecars and write assembled per-volume JSON.

    Output: <out_dir>/vol_NN.json (default out_dir = AZURE_OUTPUT_DIR).
    Caller must satisfy the writer-manifest gate before committing the output.
    """
    if vol_dir is None:
        vol_dir = RAW_PAGES / f"vol_{volume_num:02d}"
    if out_dir is None:
        out_dir = AZURE_OUTPUT_DIR

    if not vol_dir.exists():
        raise FileNotFoundError(f"Vol dir not found: {vol_dir}")

    all_sidecars = sorted(vol_dir.glob("page_*.azure.json"))
    sidecars = [s for s in all_sidecars if not _is_partial_sidecar(s)]
    if not sidecars:
        raise ValueError(f"No valid azure sidecar files found in {vol_dir}")

    pages = []
    all_confs: list[float] = []
    engine_version = "2024-02-01"

    for sidecar in sidecars:
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping corrupt sidecar %s: %s", sidecar.name, exc)
            continue

        # Extract page number from page_NNNN.azure.json filename
        page_num = int(sidecar.name.split(".")[0].split("_")[1])
        conf = float(data.get("confidence_mean", 0.0))
        # raw_text (new format) or text (old thin sidecars / test fixtures)
        text = data.get("raw_text") or data.get("text", "")
        word_count = len(text.split()) if text else 0

        if conf > 0.0:
            all_confs.append(conf)
        if data.get("engine_version"):
            engine_version = data["engine_version"]

        pages.append({
            "page": page_num,
            "confidence_mean": conf,
            "word_count": word_count,
            "text": text,
        })

    volume_conf = round(sum(all_confs) / len(all_confs), 1) if all_confs else 0.0
    output = {
        "rendering_id": "azure-ai-vision/schaff/encyclopedia/1908-1914/v1",
        "volume": volume_num,
        "assembled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "engine_alias": "azure",
        "engine_version": engine_version,
        "page_count": len(pages),
        "pages_with_data": len(all_confs),
        "confidence_mean": volume_conf,
        "pages": pages,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"vol_{volume_num:02d}.json"
    write_sidecar(out_path, output)
    logger.info(
        "Assembled azure vol %02d: %d pages (%d with data), mean conf %.1f -> %s",
        volume_num, len(pages), len(all_confs), volume_conf, out_path,
    )
    return out_path


# Dispatch table — patch this dict in tests to replace individual drivers.
DRIVERS: dict = {
    "gcv": ocr_gcv,
    "textract": ocr_textract,
    "azure": ocr_azure,
    "docint": ocr_docint,
}


# ---------------------------------------------------------------------------
# Page-level processor
# ---------------------------------------------------------------------------
def process_page(
    jpeg_path: Path,
    engines: list,
    state: dict,
    policy: dict,
    *,
    force: bool = False,
    dry_run: bool = False,
    parallel: bool = False,
) -> dict:
    """Run enabled engines on one page. Returns {engine: status_str}."""

    def _run_one(engine: str) -> str:
        sidecar = _sidecar_path(jpeg_path, engine)
        if sidecar.exists() and not force and not _is_partial_sidecar(sidecar):
            logger.info("[%s] %s -- sidecar exists, skipping", engine, jpeg_path.name)
            return "skipped"
        if dry_run:
            logger.info("[dry-run] would call %s on %s", engine, jpeg_path.name)
            return "dry-run"
        try:
            result = DRIVERS[engine](jpeg_path, state, policy)
            write_sidecar(sidecar, result)
            logger.info("[%s] %s -- conf %.1f", engine, jpeg_path.name, result["confidence_mean"])
            return "written"
        except (QuotaCapError, FreeTrialExpiredError):
            raise
        except Exception as exc:
            logger.warning("[%s] %s -- failed: %s", engine, jpeg_path.name, exc)
            write_sidecar(sidecar, {"partial": True, "engine": engine, "error": str(exc)})
            return "partial"

    results: dict = {}

    if parallel:
        with ThreadPoolExecutor(max_workers=3) as pool:
            future_to_engine = {pool.submit(_run_one, e): e for e in engines}
            for fut in as_completed(future_to_engine):
                eng = future_to_engine[fut]
                try:
                    results[eng] = fut.result()
                except (QuotaCapError, FreeTrialExpiredError):
                    results[eng] = "capped"
    else:
        for engine in engines:
            try:
                results[engine] = _run_one(engine)
            except (QuotaCapError, FreeTrialExpiredError):
                results[engine] = "capped"

    return results


# ---------------------------------------------------------------------------
# Volume runner
# ---------------------------------------------------------------------------
def run_volume(
    vol_dir: Path,
    page_paths: list,
    engines: list,
    state: dict,
    policy: dict,
    *,
    force: bool = False,
    dry_run: bool = False,
    parallel: bool = False,
) -> None:
    capped: set = set()
    total = len(page_paths)
    written = skipped = partial = 0

    for i, jpeg_path in enumerate(page_paths, 1):
        active = [e for e in engines if e not in capped]
        if not active:
            logger.info("All engines capped -- stopping at page %d/%d", i, total)
            break
        logger.info("[vol] page %d/%d: %s", i, total, jpeg_path.name)
        results = process_page(
            jpeg_path, active, state, policy,
            force=force, dry_run=dry_run, parallel=parallel,
        )
        for engine, status in results.items():
            if status == "capped":
                logger.warning("[%s] quota cap reached, skipping remaining pages", engine)
                capped.add(engine)
            elif status == "written":
                written += 1
            elif status == "skipped":
                skipped += 1
            elif status == "partial":
                partial += 1

    logger.info(
        "Volume done -- written: %d, skipped: %d, partial: %d",
        written, skipped, partial,
    )


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------
def _parse_pages(spec: str, all_pages: list) -> list:
    if spec == "all":
        return all_pages
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        return [
            p for p in all_pages
            if int(lo) <= int(p.stem.split("_")[1]) <= int(hi)
        ]
    target = int(spec)
    return [p for p in all_pages if int(p.stem.split("_")[1]) == target]


def main() -> None:
    global DRY_RUN

    ap = argparse.ArgumentParser(
        description="Cloud OCR runner -- GCV + Textract + Azure AI + Azure DocInt"
    )
    ap.add_argument("--volume", type=int, required=True, help="Volume number")
    ap.add_argument(
        "--engines", default="gcv,textract,azure",
        help="Comma-separated engine list. Choices: gcv, textract, azure, docint. "
             "Default 'gcv,textract,azure' — docint must be requested explicitly "
             "(500 pages/month, reserve for hard pages)",
    )
    ap.add_argument("--parallel", action="store_true",
                    help="Run engines concurrently per page")
    ap.add_argument("--pages", default="all",
                    help="Page range: '42-49', single page '42', or 'all'")
    ap.add_argument("--force", action="store_true",
                    help="Re-OCR pages even if sidecar exists")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print planned API calls without executing")
    ap.add_argument("--assemble", action="store_true",
                    help="Assemble per-page azure sidecars into per-volume JSON (run after OCR completes)")
    ap.add_argument("--raw-pages", default=None, type=Path,
                    help="Override the default raw page image directory (default: raw/internet-archive/schaff-herzog-pages). "
                         "Must contain vol_NN/ subdirectories with page_NNNN.jpg files.")
    args = ap.parse_args()

    DRY_RUN = args.dry_run
    _setup_logging()

    if args.assemble:
        if DRY_RUN:
            logger.info("dry-run mode -- skipping assembly")
            return
        out_path = assemble_azure_volume_json(args.volume)
        logger.info("Assembly complete: %s", out_path)
        return

    if DRY_RUN:
        logger.info("dry-run mode -- no files will be written or API calls made")

    engines = [e.strip() for e in args.engines.split(",")]
    unknown = [e for e in engines if e not in DRIVERS]
    if unknown:
        raise SystemExit(
            f"Unknown engines: {unknown}. Valid: gcv, textract, azure, docint"
        )

    raw_pages_root = Path(args.raw_pages) if args.raw_pages else RAW_PAGES
    vol_dir = raw_pages_root / f"vol_{args.volume:02d}"
    if not vol_dir.exists():
        raise SystemExit(f"Volume directory not found: {vol_dir}")

    all_jpegs = sorted(vol_dir.glob("page_????.jpg"))
    if not all_jpegs:
        raise SystemExit(f"No JPEG pages found in {vol_dir}")

    page_paths = _parse_pages(args.pages, all_jpegs)
    if not page_paths:
        raise SystemExit(f"No pages matched spec '{args.pages}'")

    state = load_quota_state()
    policy = load_quota_policy()

    logger.info(
        "vol %02d | engines: %s | pages: %d | parallel: %s | force: %s | dry-run: %s",
        args.volume, engines, len(page_paths), args.parallel, args.force, DRY_RUN,
    )

    run_volume(
        vol_dir, page_paths, engines, state, policy,
        force=args.force, dry_run=DRY_RUN, parallel=args.parallel,
    )


if __name__ == "__main__":
    main()
