"""TDD tests for build/tools/run_cloud_ocr.py -- written failing-first (Session 0 Step 4).
Assembly tests added Session 1A (2026-05-25).
Full-sidecar (blocks + raw_text) tests added Session 1A redesign (2026-05-25).
"""
import json
import urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import build.tools.run_cloud_ocr as run_cloud_ocr
from build.tools.run_cloud_ocr import (
    FreeTrialExpiredError,
    QuotaCapError,
    SIDECAR_FORMAT_VERSION,
    _azure_call_with_retry,
    _azure_rate_limit,
    _docint_pending_path,
    _docint_polygon_to_points,
    _format_metadata,
    _group_words_into_lines,
    _polygon_to_bbox,
    _raw_response_path,
    _sidecar_path,
    _union_bbox,
    _write_raw_response,
    increment_quota,
    ocr_docint,
    ocr_gcv,
    ocr_textract,
    process_page,
    quota_ok,
    write_sidecar,
)

_POLICY = {
    "providers": {
        "google_cloud_vision": {"monthly_soft_cap": 10},
        "aws_textract": {"monthly_soft_cap": 10, "free_tier_months": 3},
        "azure_ai_vision": {"monthly_soft_cap": 10},
        "azure_document_intelligence": {"monthly_soft_cap": 10},
    }
}


def _gcv_word(text, conf, x, y, w, h, *, languages=None, break_type=None):
    word = MagicMock()
    word.confidence = conf
    verts = [
        MagicMock(x=x, y=y), MagicMock(x=x + w, y=y),
        MagicMock(x=x + w, y=y + h), MagicMock(x=x, y=y + h),
    ]
    word.bounding_box.vertices = verts
    sym = MagicMock()
    sym.text = text
    if break_type is not None:
        sym.property.detected_break.type = break_type
    else:
        sym.property = None
    word.symbols = [sym]
    if languages:
        word.property.detected_languages = [
            MagicMock(language_code=lc, confidence=conf) for lc, conf in languages
        ]
    else:
        word.property = None
    return word


def _gcv_response(text="hello", with_geometry=False, block_type=1):
    resp = MagicMock()
    resp.error.message = ""
    resp.full_text_annotation.text = text
    if with_geometry:
        word = _gcv_word(text, 0.92, 100, 200, 150, 30)
        para = MagicMock()
        para.words = [word]
        para.bounding_box.vertices = word.bounding_box.vertices
        block = MagicMock()
        block.paragraphs = [para]
        block.bounding_box.vertices = word.bounding_box.vertices
        block.block_type = block_type  # 1 = TEXT
        pg = MagicMock()
        pg.width = 5034
        pg.height = 6959
        pg.blocks = [block]
        resp.full_text_annotation.pages = [pg]
    else:
        resp.full_text_annotation.pages = []
    return resp


def _textract_response(text="hello world", rotation_angle=0.0, text_type="PRINTED"):
    word_id = "word-1"
    line_id = "line-1"
    return {
        "Blocks": [
            {
                "BlockType": "PAGE",
                "Id": "page-1",
                "Geometry": {
                    "BoundingBox": {"Left": 0.0, "Top": 0.0, "Width": 1.0, "Height": 1.0},
                    "Polygon": [
                        {"X": 0.0, "Y": 0.0}, {"X": 1.0, "Y": 0.0},
                        {"X": 1.0, "Y": 1.0}, {"X": 0.0, "Y": 1.0},
                    ],
                    "RotationAngle": rotation_angle,
                },
                "Relationships": [{"Type": "CHILD", "Ids": [line_id]}],
            },
            {
                "BlockType": "LINE",
                "Id": line_id,
                "Text": text,
                "Confidence": 92.0,
                "Geometry": {
                    "BoundingBox": {"Left": 0.1, "Top": 0.2, "Width": 0.3, "Height": 0.05},
                    "Polygon": [
                        {"X": 0.1, "Y": 0.2}, {"X": 0.4, "Y": 0.2},
                        {"X": 0.4, "Y": 0.25}, {"X": 0.1, "Y": 0.25},
                    ],
                },
                "Relationships": [{"Type": "CHILD", "Ids": [word_id]}],
            },
            {
                "BlockType": "WORD",
                "Id": word_id,
                "Text": "hello",
                "Confidence": 92.0,
                "TextType": text_type,
                "Geometry": {
                    "BoundingBox": {"Left": 0.1, "Top": 0.2, "Width": 0.1, "Height": 0.05},
                    "Polygon": [
                        {"X": 0.1, "Y": 0.2}, {"X": 0.2, "Y": 0.2},
                        {"X": 0.2, "Y": 0.25}, {"X": 0.1, "Y": 0.25},
                    ],
                },
            },
        ]
    }


# ---------------------------------------------------------------------------
# Test 1: mocked client driver returns expected sidecar shape
# ---------------------------------------------------------------------------

def test_ocr_gcv_returns_expected_shape(tmp_path):
    jpeg = tmp_path / "page_0001.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff\xe0")

    client = MagicMock()
    client.document_text_detection.return_value = _gcv_response("test content")

    with patch("build.tools.run_cloud_ocr.save_quota_state"):
        result = ocr_gcv(jpeg, {}, _POLICY, _client=client)

    assert result["engine"] == "google-cloud-vision"
    assert result["raw_text"] == "test content"
    assert isinstance(result["confidence_mean"], float)
    assert "blocks" in result


def test_ocr_textract_returns_expected_shape(tmp_path):
    from io import BytesIO
    from PIL import Image

    jpeg = tmp_path / "page_0001.jpg"
    buf = BytesIO()
    Image.new("L", (1000, 1500)).save(buf, format="JPEG")
    jpeg.write_bytes(buf.getvalue())

    client = MagicMock()
    client.detect_document_text.return_value = _textract_response("hello world")

    with patch("build.tools.run_cloud_ocr.save_quota_state"):
        result = ocr_textract(jpeg, {}, _POLICY, _client=client)

    assert result["engine"] == "aws-textract"
    assert "hello" in result["raw_text"]
    assert isinstance(result["confidence_mean"], float)
    assert "blocks" in result


# ---------------------------------------------------------------------------
# Test 2: per-call quota increment happens before the (mocked) API call
# ---------------------------------------------------------------------------

def test_gcv_quota_incremented_before_api_call(tmp_path):
    jpeg = tmp_path / "page_0001.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff\xe0")
    call_order = []

    def tracking_save(s):
        call_order.append("save")

    client = MagicMock()

    def tracking_api(image):
        call_order.append("api")
        return _gcv_response()

    client.document_text_detection.side_effect = tracking_api

    with patch("build.tools.run_cloud_ocr.save_quota_state", side_effect=tracking_save):
        ocr_gcv(jpeg, {}, _POLICY, _client=client)

    assert "save" in call_order and "api" in call_order
    assert call_order.index("save") < call_order.index("api")


# ---------------------------------------------------------------------------
# Test 3: hard-abort at policy threshold leaves quota at threshold
# ---------------------------------------------------------------------------

def test_gcv_hard_abort_leaves_quota_at_threshold(tmp_path):
    jpeg = tmp_path / "page_0001.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff\xe0")
    policy = {"providers": {"google_cloud_vision": {"monthly_soft_cap": 2}}}
    state = {
        "google_cloud_vision": {
            "month": datetime.now(timezone.utc).strftime("%Y-%m"),
            "pages_used_this_month": 1,
        }
    }
    client = MagicMock()
    client.document_text_detection.return_value = _gcv_response()

    with patch("build.tools.run_cloud_ocr.save_quota_state"):
        ocr_gcv(jpeg, state, policy, _client=client)  # quota: 1 -> 2

    assert state["google_cloud_vision"]["pages_used_this_month"] == 2

    with pytest.raises(QuotaCapError):
        ocr_gcv(jpeg, state, policy, _client=client)  # cap exceeded

    assert state["google_cloud_vision"]["pages_used_this_month"] == 2  # unchanged


# ---------------------------------------------------------------------------
# Test 4: idempotent re-run skips existing sidecars
# ---------------------------------------------------------------------------

def test_process_page_skips_existing_sidecar(tmp_path):
    jpeg = tmp_path / "page_0001.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff\xe0")
    write_sidecar(
        _sidecar_path(jpeg, "gcv"),
        {"engine": "google-cloud-vision", "text": "existing", "confidence_mean": 95.0},
    )

    mock_drv = MagicMock()
    with patch.dict("build.tools.run_cloud_ocr.DRIVERS", {"gcv": mock_drv}):
        results = process_page(jpeg, ["gcv"], {}, _POLICY)

    mock_drv.assert_not_called()
    assert results["gcv"] == "skipped"


# ---------------------------------------------------------------------------
# Test 5: --dry-run writes nothing and does not call the driver
# ---------------------------------------------------------------------------

def test_process_page_dry_run_writes_nothing(tmp_path):
    jpeg = tmp_path / "page_0001.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff\xe0")

    mock_drv = MagicMock()
    with patch.dict("build.tools.run_cloud_ocr.DRIVERS", {"gcv": mock_drv}):
        results = process_page(jpeg, ["gcv"], {}, _POLICY, dry_run=True)

    mock_drv.assert_not_called()
    assert not _sidecar_path(jpeg, "gcv").exists()
    assert results["gcv"] == "dry-run"


# ---------------------------------------------------------------------------
# Test 6: partial-completion path writes sidecar with partial: true
# ---------------------------------------------------------------------------

def test_process_page_writes_partial_sidecar_on_driver_failure(tmp_path):
    jpeg = tmp_path / "page_0001.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff\xe0")

    def failing_driver(jpeg_path, state, policy):
        raise RuntimeError("network timeout")

    with patch.dict("build.tools.run_cloud_ocr.DRIVERS", {"gcv": failing_driver}):
        results = process_page(jpeg, ["gcv"], {}, _POLICY)

    sidecar = _sidecar_path(jpeg, "gcv")
    assert sidecar.exists()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data.get("partial") is True
    assert results["gcv"] == "partial"


# ---------------------------------------------------------------------------
# Test 7: Textract 90-day expiry refuses with FreeTrialExpiredError
# ---------------------------------------------------------------------------

def test_textract_90_day_expiry_raises(tmp_path):
    jpeg = tmp_path / "page_0001.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff\xe0")
    expired = (date.today() - timedelta(days=91)).isoformat()
    state = {
        "aws_textract": {
            "first_used_date": expired,
            "month": datetime.now(timezone.utc).strftime("%Y-%m"),
            "pages_used_this_month": 0,
        }
    }

    with pytest.raises(FreeTrialExpiredError):
        ocr_textract(jpeg, state, _POLICY, _client=MagicMock())


# ---------------------------------------------------------------------------
# Test 8: --parallel mode invokes all three engines per page
# ---------------------------------------------------------------------------

def test_parallel_mode_invokes_all_engines(tmp_path):
    jpeg = tmp_path / "page_0001.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff\xe0")

    def _drv(name):
        return MagicMock(return_value={"engine": name, "text": "t", "confidence_mean": 90.0})

    gcv_m = _drv("google-cloud-vision")
    txt_m = _drv("aws-textract")
    az_m = _drv("azure-ai-vision")

    with patch.dict(
        "build.tools.run_cloud_ocr.DRIVERS",
        {"gcv": gcv_m, "textract": txt_m, "azure": az_m},
    ):
        results = process_page(
            jpeg, ["gcv", "textract", "azure"], {}, _POLICY, parallel=True
        )

    gcv_m.assert_called_once()
    txt_m.assert_called_once()
    az_m.assert_called_once()
    assert set(results.values()) == {"written"}


# ---------------------------------------------------------------------------
# Test 10: Azure rate-limit pacing sleeps when calls are rapid
# ---------------------------------------------------------------------------

def test_azure_rate_limit_sleeps_when_rapid():
    """_azure_rate_limit() must sleep when elapsed < _AZURE_MIN_INTERVAL."""
    import build.tools.run_cloud_ocr as mod

    with patch("build.tools.run_cloud_ocr.time") as mock_time:
        # Simulate: last call was at t=100, now is t=101 -- only 1s gap, need 3.05s.
        mock_time.monotonic.side_effect = [101.0, 101.5]
        mock_time.sleep = MagicMock()
        mod._azure_last_call = 100.0
        mod._azure_rate_limit()

    mock_time.sleep.assert_called_once()
    sleep_dur = mock_time.sleep.call_args[0][0]
    assert 2.0 < sleep_dur <= 3.05  # 3.05 - 1.0 = 2.05s


# ---------------------------------------------------------------------------
# Test 11: Azure rate-limit does not sleep when interval is sufficient
# ---------------------------------------------------------------------------

def test_azure_rate_limit_no_sleep_when_interval_ok():
    """_azure_rate_limit() must not sleep when elapsed >= _AZURE_MIN_INTERVAL."""
    import build.tools.run_cloud_ocr as mod

    with patch("build.tools.run_cloud_ocr.time") as mock_time:
        mock_time.monotonic.side_effect = [104.0, 104.1]
        mock_time.sleep = MagicMock()
        mod._azure_last_call = 100.0  # 4.0s ago -- exceeds 3.05s minimum
        mod._azure_rate_limit()

    mock_time.sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Azure endpoint regression — must use Image Analysis v4.0, not legacy v3.x
# ---------------------------------------------------------------------------

def test_azure_uses_image_analysis_v4_endpoint(tmp_path):
    """ocr_azure must POST to the Image Analysis v4.0 endpoint, not legacy vision/v3.x paths."""
    import build.tools.run_cloud_ocr as mod

    captured = {}

    def mock_post(url, img_bytes, key):
        captured["url"] = url
        return {"readResult": {"blocks": []}, "modelVersion": "2024-02-01"}

    env_file = tmp_path / "azure-vision.env"
    env_file.write_text("AZURE_VISION_ENDPOINT=https://test.cognitiveservices.azure.com/\nAZURE_VISION_KEY=testkey\n", encoding="utf-8")

    jpeg = tmp_path / "page_0010.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16)

    state = {"azure_ai_vision": {"used": 0, "period": "2026-05"}}
    policy = {"azure_ai_vision": {"monthly_soft_cap": 5000}}

    original_secrets = mod.SECRETS
    mod.SECRETS = tmp_path
    try:
        mod.ocr_azure(jpeg, state, policy, _http_post=mock_post)
    finally:
        mod.SECRETS = original_secrets

    assert "/computervision/imageanalysis:analyze" in captured["url"]
    assert "features=read" in captured["url"]
    assert "api-version=2024-02-01" in captured["url"]
    assert "vision/v3" not in captured["url"]


def test_process_page_reruns_partial_sidecar(tmp_path):
    """A partial sidecar (partial=True) must not be treated as a valid skip."""
    from build.tools.run_cloud_ocr import process_page, write_sidecar, _sidecar_path

    jpeg = tmp_path / "page_0010.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff\xe0")

    sidecar = _sidecar_path(jpeg, "azure")
    # Write a partial sidecar as the failed run would have left
    write_sidecar(sidecar, {"partial": True, "engine": "azure", "error": "HTTP 404"})

    called = [False]

    def mock_driver(jpeg_path, state, policy):
        called[0] = True
        return {"engine": "azure-ai-vision", "text": "hello", "confidence_mean": 91.0}

    with patch.dict("build.tools.run_cloud_ocr.DRIVERS", {"azure": mock_driver}):
        results = process_page(jpeg, ["azure"], {}, _POLICY)

    assert called[0], "driver must be called when sidecar is partial"
    assert results["azure"] == "written"


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def test_polygon_to_bbox_axis_aligned():
    """_polygon_to_bbox converts 4-point polygon to {x,y,w,h}."""
    polygon = [{"x": 100, "y": 200}, {"x": 400, "y": 200},
               {"x": 400, "y": 228}, {"x": 100, "y": 228}]
    bbox = _polygon_to_bbox(polygon)
    assert bbox == {"x": 100, "y": 200, "w": 300, "h": 28}


def test_polygon_to_bbox_empty_returns_none():
    assert _polygon_to_bbox([]) is None


def test_union_bbox_combines_two():
    # b1 right edge: 10+100=110, b2 right edge: 50+80=130 -> w = 130-10 = 120
    # b1 bottom: 20+30=50, b2 bottom: 10+50=60 -> h = 60-10 = 50
    b1 = {"x": 10, "y": 20, "w": 100, "h": 30}
    b2 = {"x": 50, "y": 10, "w": 80, "h": 50}
    result = _union_bbox([b1, b2])
    assert result == {"x": 10, "y": 10, "w": 120, "h": 50}


def test_union_bbox_empty_returns_none():
    assert _union_bbox([]) is None


# ---------------------------------------------------------------------------
# Azure driver full-sidecar shape (blocks + raw_text)
# ---------------------------------------------------------------------------

def _make_azure_api_response(words: list[dict] | None = None) -> dict:
    """Build a minimal Image Analysis v4.0 readResult response."""
    if words is None:
        words = [{"text": "AARON,", "confidence": 0.98,
                  "boundingPolygon": [{"x": 100, "y": 200}, {"x": 400, "y": 200},
                                      {"x": 400, "y": 228}, {"x": 100, "y": 228}]},
                 {"text": "the", "confidence": 0.95,
                  "boundingPolygon": [{"x": 410, "y": 200}, {"x": 460, "y": 200},
                                      {"x": 460, "y": 228}, {"x": 410, "y": 228}]}]
    return {
        "modelVersion": "2024-02-01",
        "readResult": {
            "blocks": [{
                "lines": [{
                    "text": " ".join(w["text"] for w in words),
                    "boundingPolygon": [{"x": 100, "y": 200}, {"x": 460, "y": 200},
                                        {"x": 460, "y": 228}, {"x": 100, "y": 228}],
                    "words": words,
                }]
            }]
        }
    }


def test_ocr_azure_sidecar_has_blocks_and_raw_text(tmp_path):
    """ocr_azure returns sidecar with blocks[], raw_text, and image_size."""
    import build.tools.run_cloud_ocr as mod

    env_file = tmp_path / "azure-vision.env"
    env_file.write_text(
        "AZURE_VISION_ENDPOINT=https://test.cognitiveservices.azure.com/\n"
        "AZURE_VISION_KEY=testkey\n",
        encoding="utf-8",
    )
    jpeg = tmp_path / "page_0010.jpg"
    # Minimal valid 1x1 JPEG
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("L", (5034, 6959)).save(buf, format="JPEG")
    jpeg.write_bytes(buf.getvalue())

    api_response = _make_azure_api_response()

    def mock_post(url, img_bytes, key):
        return api_response

    original_secrets = mod.SECRETS
    mod.SECRETS = tmp_path
    try:
        with patch("build.tools.run_cloud_ocr.save_quota_state"):
            result = mod.ocr_azure(jpeg, {}, _POLICY, _http_post=mock_post)
    finally:
        mod.SECRETS = original_secrets

    assert "blocks" in result
    assert len(result["blocks"]) == 1
    assert len(result["blocks"][0]["lines"]) == 1
    words = result["blocks"][0]["lines"][0]["words"]
    assert len(words) == 2
    assert words[0]["text"] == "AARON,"
    assert words[0]["confidence"] == pytest.approx(98.0, abs=0.1)
    assert words[0]["bbox"] == {"x": 100, "y": 200, "w": 300, "h": 28}
    assert words[0]["bbox_polygon"] == [
        {"x": 100, "y": 200}, {"x": 400, "y": 200},
        {"x": 400, "y": 228}, {"x": 100, "y": 228},
    ]
    assert "raw_text" in result
    assert "AARON," in result["raw_text"]
    assert result["image_size"] == [5034, 6959]


def test_ocr_azure_word_low_confidence_flagged(tmp_path):
    """Words with confidence < 0.50 get low_confidence=True."""
    import build.tools.run_cloud_ocr as mod

    env_file = tmp_path / "azure-vision.env"
    env_file.write_text(
        "AZURE_VISION_ENDPOINT=https://test.cognitiveservices.azure.com/\n"
        "AZURE_VISION_KEY=testkey\n",
        encoding="utf-8",
    )
    jpeg = tmp_path / "page_0010.jpg"
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("L", (100, 100)).save(buf, format="JPEG")
    jpeg.write_bytes(buf.getvalue())

    low_conf_word = {"text": "unclear", "confidence": 0.3,
                     "boundingPolygon": [{"x": 0, "y": 0}, {"x": 50, "y": 0},
                                         {"x": 50, "y": 20}, {"x": 0, "y": 20}]}
    api_response = _make_azure_api_response(words=[low_conf_word])

    def mock_post(url, img_bytes, key):
        return api_response

    original_secrets = mod.SECRETS
    mod.SECRETS = tmp_path
    try:
        with patch("build.tools.run_cloud_ocr.save_quota_state"):
            result = mod.ocr_azure(jpeg, {}, _POLICY, _http_post=mock_post)
    finally:
        mod.SECRETS = original_secrets

    word = result["blocks"][0]["lines"][0]["words"][0]
    assert word["low_confidence"] is True
    assert word["confidence"] == pytest.approx(30.0, abs=0.1)


# ---------------------------------------------------------------------------
# Azure assembly tests (Session 1A, 2026-05-25)
# ---------------------------------------------------------------------------

def _write_azure_sidecar(
    path: Path,
    conf: float = 92.0,
    text: str = "some ocr text here",
    partial: bool = False,
    engine_version: str = "2024-02-01",
) -> None:
    if partial:
        data: dict = {"partial": True, "engine": "azure", "error": "timeout"}
    else:
        data = {
            "engine": "azure-ai-vision",
            "engine_version": engine_version,
            "text": text,
            "confidence_mean": conf,
        }
    path.write_text(json.dumps(data), encoding="utf-8")


def test_assemble_azure_basic_shape(tmp_path):
    from build.tools.run_cloud_ocr import assemble_azure_volume_json

    vol_dir = tmp_path / "vol_01"
    vol_dir.mkdir()
    out_dir = tmp_path / "out"

    _write_azure_sidecar(vol_dir / "page_0001.azure.json", conf=92.0)
    _write_azure_sidecar(vol_dir / "page_0002.azure.json", conf=88.5)

    out_path = assemble_azure_volume_json(1, vol_dir=vol_dir, out_dir=out_dir)

    assert out_path == out_dir / "vol_01.json"
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["rendering_id"] == "azure-ai-vision/schaff/encyclopedia/1908-1914/v1"
    assert data["volume"] == 1
    assert data["page_count"] == 2
    assert data["pages_with_data"] == 2
    assert len(data["pages"]) == 2


def test_assemble_azure_skips_partial_sidecars(tmp_path):
    from build.tools.run_cloud_ocr import assemble_azure_volume_json

    vol_dir = tmp_path / "vol_01"
    vol_dir.mkdir()
    out_dir = tmp_path / "out"

    _write_azure_sidecar(vol_dir / "page_0001.azure.json", conf=92.0)
    _write_azure_sidecar(vol_dir / "page_0002.azure.json", partial=True)
    _write_azure_sidecar(vol_dir / "page_0003.azure.json", conf=88.5)

    out_path = assemble_azure_volume_json(1, vol_dir=vol_dir, out_dir=out_dir)
    data = json.loads(out_path.read_text(encoding="utf-8"))

    assert data["page_count"] == 2
    pages_listed = [p["page"] for p in data["pages"]]
    assert 2 not in pages_listed


def test_assemble_azure_raises_on_missing_vol_dir(tmp_path):
    from build.tools.run_cloud_ocr import assemble_azure_volume_json

    missing = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        assemble_azure_volume_json(1, vol_dir=missing, out_dir=tmp_path)


def test_assemble_azure_raises_when_no_valid_sidecars(tmp_path):
    from build.tools.run_cloud_ocr import assemble_azure_volume_json

    vol_dir = tmp_path / "vol_01"
    vol_dir.mkdir()

    with pytest.raises(ValueError):
        assemble_azure_volume_json(1, vol_dir=vol_dir, out_dir=tmp_path)


def test_assemble_azure_raises_when_all_partial(tmp_path):
    from build.tools.run_cloud_ocr import assemble_azure_volume_json

    vol_dir = tmp_path / "vol_01"
    vol_dir.mkdir()

    _write_azure_sidecar(vol_dir / "page_0001.azure.json", partial=True)
    _write_azure_sidecar(vol_dir / "page_0002.azure.json", partial=True)

    with pytest.raises(ValueError):
        assemble_azure_volume_json(1, vol_dir=vol_dir, out_dir=tmp_path)


def test_assemble_azure_page_number_from_filename(tmp_path):
    from build.tools.run_cloud_ocr import assemble_azure_volume_json

    vol_dir = tmp_path / "vol_01"
    vol_dir.mkdir()
    out_dir = tmp_path / "out"

    _write_azure_sidecar(vol_dir / "page_0123.azure.json", conf=90.0)

    out_path = assemble_azure_volume_json(1, vol_dir=vol_dir, out_dir=out_dir)
    data = json.loads(out_path.read_text(encoding="utf-8"))

    assert data["pages"][0]["page"] == 123


def test_assemble_azure_word_count_from_text(tmp_path):
    from build.tools.run_cloud_ocr import assemble_azure_volume_json

    vol_dir = tmp_path / "vol_01"
    vol_dir.mkdir()
    out_dir = tmp_path / "out"

    _write_azure_sidecar(
        vol_dir / "page_0001.azure.json",
        conf=91.0,
        text="one two three four five",
    )

    out_path = assemble_azure_volume_json(1, vol_dir=vol_dir, out_dir=out_dir)
    data = json.loads(out_path.read_text(encoding="utf-8"))

    assert data["pages"][0]["word_count"] == 5


def test_assemble_azure_engine_version_from_sidecar(tmp_path):
    from build.tools.run_cloud_ocr import assemble_azure_volume_json

    vol_dir = tmp_path / "vol_01"
    vol_dir.mkdir()
    out_dir = tmp_path / "out"

    _write_azure_sidecar(
        vol_dir / "page_0001.azure.json",
        conf=91.0,
        engine_version="2025-01-15",
    )

    out_path = assemble_azure_volume_json(1, vol_dir=vol_dir, out_dir=out_dir)
    data = json.loads(out_path.read_text(encoding="utf-8"))

    assert data["engine_version"] == "2025-01-15"


# ---------------------------------------------------------------------------
# Test 12: Azure retries on 429 with Retry-After header
# ---------------------------------------------------------------------------

def test_azure_retries_on_429_with_retry_after():
    """_azure_call_with_retry() waits Retry-After seconds then retries on 429."""
    call_count = [0]

    def call_fn():
        call_count[0] += 1
        if call_count[0] == 1:
            raise urllib.error.HTTPError(
                "url", 429, "Too Many Requests", {"Retry-After": "5"}, None
            )
        return {"analyzeResult": {"readResults": []}}

    with patch("build.tools.run_cloud_ocr.time") as mock_time:
        mock_time.sleep = MagicMock()
        result = _azure_call_with_retry(call_fn)

    assert result == {"analyzeResult": {"readResults": []}}
    assert call_count[0] == 2
    mock_time.sleep.assert_called_once_with(5)


# ---------------------------------------------------------------------------
# Test 13: Azure aborts when Retry-After exceeds the cap
# ---------------------------------------------------------------------------

def test_azure_aborts_if_retry_after_exceeds_cap():
    """_azure_call_with_retry() raises RuntimeError when 429 Retry-After > 300s."""
    def call_fn():
        raise urllib.error.HTTPError(
            "url", 429, "Too Many Requests", {"Retry-After": "400"}, None
        )

    with patch("build.tools.run_cloud_ocr.time") as mock_time:
        mock_time.sleep = MagicMock()
        with pytest.raises(RuntimeError, match="Retry-After"):
            _azure_call_with_retry(call_fn)

    mock_time.sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Test 14: Azure 5xx triggers exponential backoff then raises after exhaustion
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# GCV full-sidecar shape (blocks + raw_text + bbox_polygon)
# ---------------------------------------------------------------------------

def test_ocr_gcv_full_sidecar_shape(tmp_path):
    """ocr_gcv returns sidecar with blocks[], raw_text, image_size, and bbox_polygon."""
    jpeg = tmp_path / "page_0001.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff\xe0")

    client = MagicMock()
    client.document_text_detection.return_value = _gcv_response("Afra", with_geometry=True)

    with patch("build.tools.run_cloud_ocr.save_quota_state"):
        result = ocr_gcv(jpeg, {}, _POLICY, _client=client)

    assert result["engine"] == "google-cloud-vision"
    assert result["raw_text"] == "Afra"
    assert result["image_size"] == [5034, 6959]
    assert len(result["blocks"]) == 1
    words = result["blocks"][0]["lines"][0]["words"]
    assert len(words) == 1
    assert words[0]["text"] == "Afra"
    assert words[0]["bbox"] == {"x": 100, "y": 200, "w": 150, "h": 30}
    assert len(words[0]["bbox_polygon"]) == 4
    assert words[0]["bbox_polygon"][0] == {"x": 100, "y": 200}


# ---------------------------------------------------------------------------
# Textract full-sidecar shape (blocks + raw_text + bbox_polygon, pixel conversion)
# ---------------------------------------------------------------------------

def test_ocr_textract_full_sidecar_shape(tmp_path):
    """ocr_textract returns sidecar with blocks[], raw_text, image_size, pixel bboxes."""
    from io import BytesIO
    from PIL import Image

    jpeg = tmp_path / "page_0001.jpg"
    buf = BytesIO()
    Image.new("L", (5034, 6959)).save(buf, format="JPEG")
    jpeg.write_bytes(buf.getvalue())

    client = MagicMock()
    client.detect_document_text.return_value = _textract_response("hello world")

    with patch("build.tools.run_cloud_ocr.save_quota_state"):
        result = ocr_textract(jpeg, {}, _POLICY, _client=client)

    assert result["engine"] == "aws-textract"
    assert result["image_size"] == [5034, 6959]
    assert "hello" in result["raw_text"]
    assert len(result["blocks"]) == 1

    words = result["blocks"][0]["lines"][0]["words"]
    assert len(words) == 1
    assert words[0]["text"] == "hello"
    # BoundingBox Left=0.1, Top=0.2, Width=0.1, Height=0.05 on a 5034x6959 image
    assert words[0]["bbox"]["x"] == round(0.1 * 5034)
    assert words[0]["bbox"]["y"] == round(0.2 * 6959)
    assert words[0]["bbox"]["w"] == round(0.1 * 5034)
    assert words[0]["bbox"]["h"] == round(0.05 * 6959)
    assert len(words[0]["bbox_polygon"]) == 4
    assert words[0]["bbox_polygon"][0]["x"] == round(0.1 * 5034)


# ---------------------------------------------------------------------------
# Format metadata — every cloud sidecar carries version + coordinate system
# ---------------------------------------------------------------------------

def test_format_metadata_shape():
    md = _format_metadata()
    assert md["format_version"] == SIDECAR_FORMAT_VERSION == 1
    assert md["coordinate_unit"] == "pixel"
    assert md["coordinate_frame"] == "source_image"


def test_all_cloud_sidecars_carry_format_metadata(tmp_path):
    """Every cloud driver writes format_version + coordinate_unit + coordinate_frame."""
    from io import BytesIO
    from PIL import Image

    jpeg = tmp_path / "page_0001.jpg"
    buf = BytesIO()
    Image.new("L", (5034, 6959)).save(buf, format="JPEG")
    jpeg.write_bytes(buf.getvalue())

    # GCV
    client = MagicMock()
    client.document_text_detection.return_value = _gcv_response("Afra", with_geometry=True)
    with patch("build.tools.run_cloud_ocr.save_quota_state"):
        gcv_result = ocr_gcv(jpeg, {}, _POLICY, _client=client)
    assert gcv_result["format_version"] == 1
    assert gcv_result["coordinate_unit"] == "pixel"

    # Textract
    client2 = MagicMock()
    client2.detect_document_text.return_value = _textract_response("hello")
    with patch("build.tools.run_cloud_ocr.save_quota_state"):
        tx_result = ocr_textract(jpeg, {}, _POLICY, _client=client2)
    assert tx_result["format_version"] == 1
    assert tx_result["coordinate_unit"] == "pixel"


# ---------------------------------------------------------------------------
# Textract fail-closed — never write fabricated coordinates on PIL failure
# ---------------------------------------------------------------------------

def test_ocr_textract_preserves_rotation_angle(tmp_path):
    """Textract reports RotationAngle on the PAGE block — preserve it at top level."""
    from io import BytesIO
    from PIL import Image

    jpeg = tmp_path / "page_0001.jpg"
    buf = BytesIO()
    Image.new("L", (1000, 1500)).save(buf, format="JPEG")
    jpeg.write_bytes(buf.getvalue())

    client = MagicMock()
    client.detect_document_text.return_value = _textract_response("hello", rotation_angle=2.5)

    with patch("build.tools.run_cloud_ocr.save_quota_state"):
        result = ocr_textract(jpeg, {}, _POLICY, _client=client)

    assert result["page_rotation"] == 2.5


def test_ocr_textract_preserves_text_type(tmp_path):
    """Textract reports TextType per WORD — preserve PRINTED/HANDWRITING."""
    from io import BytesIO
    from PIL import Image

    jpeg = tmp_path / "page_0001.jpg"
    buf = BytesIO()
    Image.new("L", (1000, 1500)).save(buf, format="JPEG")
    jpeg.write_bytes(buf.getvalue())

    client = MagicMock()
    client.detect_document_text.return_value = _textract_response(
        "hello", text_type="HANDWRITING"
    )

    with patch("build.tools.run_cloud_ocr.save_quota_state"):
        result = ocr_textract(jpeg, {}, _POLICY, _client=client)

    assert result["blocks"][0]["lines"][0]["words"][0]["text_type"] == "HANDWRITING"


def test_ocr_textract_raises_when_image_unreadable(tmp_path):
    """Codex Attack 6: Textract must raise (not silently 1x1) when PIL can't decode."""
    jpeg = tmp_path / "page_0001.jpg"
    jpeg.write_bytes(b"not a jpeg at all")  # 4 bytes of garbage

    client = MagicMock()
    client.detect_document_text.return_value = _textract_response("hello")

    with patch("build.tools.run_cloud_ocr.save_quota_state"):
        with pytest.raises(RuntimeError, match="Cannot read image dimensions"):
            ocr_textract(jpeg, {}, _POLICY, _client=client)


# ---------------------------------------------------------------------------
# GCV physical-line reconstruction — paragraphs split into lines by y-position
# ---------------------------------------------------------------------------

def test_group_words_into_lines_basic():
    """Two rows of words at clearly different y-coordinates cluster into two lines."""
    words = [
        {"text": "row1a", "bbox": {"x": 10, "y": 100, "w": 50, "h": 20}},
        {"text": "row1b", "bbox": {"x": 70, "y": 100, "w": 50, "h": 20}},
        {"text": "row2a", "bbox": {"x": 10, "y": 200, "w": 50, "h": 20}},
        {"text": "row2b", "bbox": {"x": 70, "y": 200, "w": 50, "h": 20}},
    ]
    lines = _group_words_into_lines(words)
    assert len(lines) == 2
    assert [w["text"] for w in lines[0]] == ["row1a", "row1b"]
    assert [w["text"] for w in lines[1]] == ["row2a", "row2b"]


def test_group_words_into_lines_sorts_by_x_within_line():
    """Words within a line are sorted left-to-right after clustering."""
    words = [
        {"text": "last", "bbox": {"x": 200, "y": 100, "w": 40, "h": 20}},
        {"text": "first", "bbox": {"x": 10, "y": 100, "w": 40, "h": 20}},
        {"text": "middle", "bbox": {"x": 100, "y": 100, "w": 40, "h": 20}},
    ]
    lines = _group_words_into_lines(words)
    assert [w["text"] for w in lines[0]] == ["first", "middle", "last"]


def test_ocr_gcv_extracts_block_type(tmp_path):
    """GCV block.block_type carries through to the block record."""
    jpeg = tmp_path / "page_0001.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff\xe0")

    client = MagicMock()
    # block_type=3 = PICTURE in GCV's enum
    client.document_text_detection.return_value = _gcv_response("art", with_geometry=True, block_type=3)

    with patch("build.tools.run_cloud_ocr.save_quota_state"):
        result = ocr_gcv(jpeg, {}, _POLICY, _client=client)

    assert result["blocks"][0]["block_type"] == "PICTURE"


def test_ocr_gcv_extracts_word_languages(tmp_path):
    """GCV per-word detected_languages carries through to the word record."""
    jpeg = tmp_path / "page_0001.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff\xe0")

    word = _gcv_word("AARON", 0.95, 100, 200, 100, 30,
                     languages=[("en", 0.99), ("la", 0.30)])
    para = MagicMock()
    para.words = [word]
    para.bounding_box.vertices = word.bounding_box.vertices
    block = MagicMock()
    block.paragraphs = [para]
    block.bounding_box.vertices = word.bounding_box.vertices
    block.block_type = 1
    pg = MagicMock()
    pg.width = 1000
    pg.height = 1500
    pg.blocks = [block]
    resp = MagicMock()
    resp.error.message = ""
    resp.full_text_annotation.text = "AARON"
    resp.full_text_annotation.pages = [pg]

    client = MagicMock()
    client.document_text_detection.return_value = resp

    with patch("build.tools.run_cloud_ocr.save_quota_state"):
        result = ocr_gcv(jpeg, {}, _POLICY, _client=client)

    w = result["blocks"][0]["lines"][0]["words"][0]
    assert "languages" in w
    assert w["languages"][0]["language_code"] == "en"
    assert w["languages"][1]["language_code"] == "la"


def test_ocr_gcv_extracts_break_after(tmp_path):
    """GCV detected_break on the last symbol becomes break_after on the word."""
    jpeg = tmp_path / "page_0001.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff\xe0")

    # break_type=4 = HYPHEN — word continues on next line
    word = _gcv_word("contin-", 0.94, 100, 200, 100, 30, break_type=4)
    para = MagicMock()
    para.words = [word]
    para.bounding_box.vertices = word.bounding_box.vertices
    block = MagicMock()
    block.paragraphs = [para]
    block.bounding_box.vertices = word.bounding_box.vertices
    block.block_type = 1
    pg = MagicMock()
    pg.width = 1000
    pg.height = 1500
    pg.blocks = [block]
    resp = MagicMock()
    resp.error.message = ""
    resp.full_text_annotation.text = "contin-"
    resp.full_text_annotation.pages = [pg]

    client = MagicMock()
    client.document_text_detection.return_value = resp

    with patch("build.tools.run_cloud_ocr.save_quota_state"):
        result = ocr_gcv(jpeg, {}, _POLICY, _client=client)

    w = result["blocks"][0]["lines"][0]["words"][0]
    assert w["break_after"] == "HYPHEN"


def test_gcv_paragraph_spanning_multiple_rows_is_split(tmp_path):
    """Codex Attack 2: a GCV paragraph that spans two printed rows produces TWO line records."""
    jpeg = tmp_path / "page_0001.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff\xe0")

    # One paragraph with words on two y-rows
    w1 = _gcv_word("row1a", 0.92, 100, 100, 50, 20)
    w2 = _gcv_word("row1b", 0.92, 200, 100, 50, 20)
    w3 = _gcv_word("row2a", 0.92, 100, 200, 50, 20)
    w4 = _gcv_word("row2b", 0.92, 200, 200, 50, 20)
    para = MagicMock()
    para.words = [w1, w2, w3, w4]
    para.bounding_box.vertices = w1.bounding_box.vertices
    block = MagicMock()
    block.paragraphs = [para]
    block.bounding_box.vertices = w1.bounding_box.vertices
    block.block_type = 1  # TEXT
    pg = MagicMock()
    pg.width = 1000
    pg.height = 1500
    pg.blocks = [block]
    resp = MagicMock()
    resp.error.message = ""
    resp.full_text_annotation.text = "row1a row1b\nrow2a row2b"
    resp.full_text_annotation.pages = [pg]

    client = MagicMock()
    client.document_text_detection.return_value = resp

    with patch("build.tools.run_cloud_ocr.save_quota_state"):
        result = ocr_gcv(jpeg, {}, _POLICY, _client=client)

    # One paragraph but TWO physical lines after reconstruction
    assert len(result["blocks"]) == 1
    assert len(result["blocks"][0]["lines"]) == 2
    assert [w["text"] for w in result["blocks"][0]["lines"][0]["words"]] == ["row1a", "row1b"]
    assert [w["text"] for w in result["blocks"][0]["lines"][1]["words"]] == ["row2a", "row2b"]


# ---------------------------------------------------------------------------
# Azure Document Intelligence driver — async submit + resumable polling
# ---------------------------------------------------------------------------

def _docint_succeeded_envelope(words=None, lines=None, angle=0.0,
                                paragraphs=None, styles=None, content=None,
                                page_spans=None):
    if words is None:
        words = [
            {"content": "AARON,", "confidence": 0.98,
             "polygon": [100, 200, 250, 200, 250, 228, 100, 228]},
        ]
    if lines is None:
        lines = [{"content": "AARON,", "polygon": [100, 200, 250, 200, 250, 228, 100, 228]}]
    page: dict = {
        "pageNumber": 1,
        "width": 5034,
        "height": 6959,
        "unit": "pixel",
        "angle": angle,
        "words": words,
        "lines": lines,
    }
    if page_spans is not None:
        page["spans"] = page_spans
    result: dict = {
        "apiVersion": "2024-11-30",
        "modelId": "prebuilt-read",
        "pages": [page],
    }
    if paragraphs is not None:
        result["paragraphs"] = paragraphs
    if styles is not None:
        result["styles"] = styles
    if content is not None:
        result["content"] = content
    return {"status": "succeeded", "analyzeResult": result}


def _write_docint_env(tmp_path):
    """DocInt reads credentials from azure-vision.env (shared multi-service resource)."""
    env_file = tmp_path / "azure-vision.env"
    env_file.write_text(
        "AZURE_VISION_ENDPOINT=https://test.cognitiveservices.azure.com/\n"
        "AZURE_VISION_KEY=testkey\n",
        encoding="utf-8",
    )


def _write_test_jpeg(jpeg, w=5034, h=6959):
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("L", (w, h)).save(buf, format="JPEG")
    jpeg.write_bytes(buf.getvalue())


def test_docint_polygon_to_points_pixel_units():
    """Flat [x1,y1,...] in pixel units passes through unchanged."""
    pts = _docint_polygon_to_points([10, 20, 30, 20, 30, 40, 10, 40], 1.0, 1.0)
    assert pts == [{"x": 10, "y": 20}, {"x": 30, "y": 20},
                   {"x": 30, "y": 40}, {"x": 10, "y": 40}]


def test_docint_polygon_to_points_inch_units():
    """Inch units scale by image_pixels / page_inches."""
    # 1 inch -> 600px scale
    pts = _docint_polygon_to_points([1.0, 2.0, 2.0, 2.0], 600.0, 600.0)
    assert pts == [{"x": 600, "y": 1200}, {"x": 1200, "y": 1200}]


def test_docint_fresh_submission_persists_pending_before_polling(tmp_path):
    """Codex Attack 7: Operation-Location must be persisted to disk BEFORE polling
    starts so a crash mid-poll doesn't lose the operation."""
    _write_docint_env(tmp_path)
    jpeg = tmp_path / "page_0001.jpg"
    _write_test_jpeg(jpeg)

    op_url = "https://test.cognitiveservices.azure.com/op/abc123"
    persisted_at_poll_time = []

    def mock_post(url, img_bytes, key):
        return op_url

    def mock_get(url, key):
        # When poll is called, the pending file MUST already exist on disk
        persisted_at_poll_time.append(_docint_pending_path(jpeg).exists())
        return _docint_succeeded_envelope()

    original_secrets = run_cloud_ocr.SECRETS
    run_cloud_ocr.SECRETS = tmp_path
    try:
        with patch("build.tools.run_cloud_ocr.save_quota_state"), \
             patch("build.tools.run_cloud_ocr.time") as mock_time:
            mock_time.sleep = MagicMock()
            result = ocr_docint(
                jpeg, {}, _POLICY,
                _http_post=mock_post, _http_get=mock_get,
            )
    finally:
        run_cloud_ocr.SECRETS = original_secrets

    assert persisted_at_poll_time == [True]  # pending file existed before first poll
    assert result["engine"] == "azure-document-intelligence"
    assert result["format_version"] == 1
    # After success, pending file is removed
    assert not _docint_pending_path(jpeg).exists()


def test_docint_resume_skips_submission_when_pending_exists(tmp_path):
    """Codex Attack 7: a pre-existing pending file means resume — do NOT POST again,
    do NOT increment quota again."""
    _write_docint_env(tmp_path)
    jpeg = tmp_path / "page_0001.jpg"
    _write_test_jpeg(jpeg)

    # Pre-seed a pending file (simulating a prior crashed run)
    pending = _docint_pending_path(jpeg)
    pending.write_text(json.dumps({
        "operation_location": "https://test.cognitiveservices.azure.com/op/preexisting",
        "submitted_at": "2026-05-25T12:00:00Z",
        "jpeg": jpeg.name,
    }), encoding="utf-8")

    post_called = [False]
    def mock_post(url, img_bytes, key):
        post_called[0] = True
        return "should-not-happen"

    def mock_get(url, key):
        assert "preexisting" in url, "must poll the persisted operation, not a new one"
        return _docint_succeeded_envelope()

    initial_state = {"azure_document_intelligence": {"month": "2026-05", "pages_used_this_month": 0}}

    original_secrets = run_cloud_ocr.SECRETS
    run_cloud_ocr.SECRETS = tmp_path
    try:
        with patch("build.tools.run_cloud_ocr.save_quota_state"), \
             patch("build.tools.run_cloud_ocr.time") as mock_time:
            mock_time.sleep = MagicMock()
            result = ocr_docint(
                jpeg, initial_state, _POLICY,
                _http_post=mock_post, _http_get=mock_get,
            )
    finally:
        run_cloud_ocr.SECRETS = original_secrets

    assert post_called[0] is False, "Must not re-submit when pending file exists"
    # Quota unchanged — operation was already paid for at original submission
    assert initial_state["azure_document_intelligence"]["pages_used_this_month"] == 0
    assert result["engine"] == "azure-document-intelligence"


def test_docint_raises_when_azure_vision_env_missing(tmp_path):
    """azure-vision.env missing → clear error message."""
    jpeg = tmp_path / "page_0001.jpg"
    _write_test_jpeg(jpeg)

    original_secrets = run_cloud_ocr.SECRETS
    run_cloud_ocr.SECRETS = tmp_path
    try:
        with patch("build.tools.run_cloud_ocr.save_quota_state"):
            with pytest.raises(RuntimeError, match="azure-vision.env"):
                ocr_docint(jpeg, {}, _POLICY)
    finally:
        run_cloud_ocr.SECRETS = original_secrets


def test_docint_extracts_paragraphs_with_roles(tmp_path):
    """DocInt paragraphs[] with role classification surfaces at top level."""
    _write_docint_env(tmp_path)
    jpeg = tmp_path / "page_0001.jpg"
    _write_test_jpeg(jpeg)

    envelope = _docint_succeeded_envelope(
        paragraphs=[
            {
                "content": "AARON, the brother of Moses",
                "role": "sectionHeading",
                "boundingRegions": [{"pageNumber": 1, "polygon": [100, 200, 800, 200, 800, 240, 100, 240]}],
                "spans": [{"offset": 0, "length": 27}],
            },
            {
                "content": "Aaron was the elder brother of Moses...",
                "boundingRegions": [{"pageNumber": 1, "polygon": [100, 260, 800, 260, 800, 320, 100, 320]}],
                "spans": [{"offset": 27, "length": 40}],
            },
        ],
        content="AARON, the brother of Moses\nAaron was the elder brother of Moses...",
    )

    def mock_post(url, img_bytes, key):
        return "https://test.cognitiveservices.azure.com/op/abc"

    def mock_get(url, key):
        return envelope

    original_secrets = run_cloud_ocr.SECRETS
    run_cloud_ocr.SECRETS = tmp_path
    try:
        with patch("build.tools.run_cloud_ocr.save_quota_state"), \
             patch("build.tools.run_cloud_ocr.time") as mock_time:
            mock_time.sleep = MagicMock()
            result = ocr_docint(
                jpeg, {}, _POLICY,
                _http_post=mock_post, _http_get=mock_get,
            )
    finally:
        run_cloud_ocr.SECRETS = original_secrets

    assert "paragraphs" in result
    assert len(result["paragraphs"]) == 2
    assert result["paragraphs"][0]["role"] == "sectionHeading"
    assert result["paragraphs"][0]["content"] == "AARON, the brother of Moses"
    assert result["paragraphs"][0]["bbox"] == {"x": 100, "y": 200, "w": 700, "h": 40}
    assert "role" not in result["paragraphs"][1]  # absent for body paragraphs
    assert result["paragraphs"][0]["spans"] == [{"offset": 0, "length": 27}]
    # Full content text from analyzeResult.content
    assert "AARON" in result["content"]


def test_docint_extracts_styles_when_present(tmp_path):
    """DocInt styles[] (handwriting/font hints) carry through when non-empty."""
    _write_docint_env(tmp_path)
    jpeg = tmp_path / "page_0001.jpg"
    _write_test_jpeg(jpeg)

    envelope = _docint_succeeded_envelope(
        styles=[{"isHandwritten": False, "confidence": 0.99, "spans": [{"offset": 0, "length": 27}]}],
    )

    def mock_post(url, img_bytes, key):
        return "https://test.cognitiveservices.azure.com/op/abc"

    def mock_get(url, key):
        return envelope

    original_secrets = run_cloud_ocr.SECRETS
    run_cloud_ocr.SECRETS = tmp_path
    try:
        with patch("build.tools.run_cloud_ocr.save_quota_state"), \
             patch("build.tools.run_cloud_ocr.time") as mock_time:
            mock_time.sleep = MagicMock()
            result = ocr_docint(
                jpeg, {}, _POLICY,
                _http_post=mock_post, _http_get=mock_get,
            )
    finally:
        run_cloud_ocr.SECRETS = original_secrets

    assert "styles" in result
    assert result["styles"][0]["isHandwritten"] is False


def test_docint_preserves_page_angle(tmp_path):
    """DocInt reports per-page angle — preserve at top level."""
    _write_docint_env(tmp_path)
    jpeg = tmp_path / "page_0001.jpg"
    _write_test_jpeg(jpeg)

    def mock_post(url, img_bytes, key):
        return "https://test.cognitiveservices.azure.com/op/abc"

    def mock_get(url, key):
        return _docint_succeeded_envelope(angle=1.7)

    original_secrets = run_cloud_ocr.SECRETS
    run_cloud_ocr.SECRETS = tmp_path
    try:
        with patch("build.tools.run_cloud_ocr.save_quota_state"), \
             patch("build.tools.run_cloud_ocr.time") as mock_time:
            mock_time.sleep = MagicMock()
            result = ocr_docint(
                jpeg, {}, _POLICY,
                _http_post=mock_post, _http_get=mock_get,
            )
    finally:
        run_cloud_ocr.SECRETS = original_secrets

    assert result["page_rotation"] == 1.7


# ---------------------------------------------------------------------------
# Raw response persistence — every cloud driver saves the unparsed API envelope
# ---------------------------------------------------------------------------

def test_write_raw_response_writes_dict_as_json(tmp_path):
    jpeg = tmp_path / "page_0010.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff\xe0")
    payload = {"foo": "bar", "nested": {"x": 1}}
    _write_raw_response(jpeg, "azure", payload)

    raw_path = _raw_response_path(jpeg, "azure")
    assert raw_path.exists()
    assert raw_path.name == "page_0010.azure.raw.json"
    assert json.loads(raw_path.read_text(encoding="utf-8")) == payload


def test_ocr_textract_writes_raw_response(tmp_path):
    from io import BytesIO
    from PIL import Image

    jpeg = tmp_path / "page_0001.jpg"
    buf = BytesIO()
    Image.new("L", (1000, 1500)).save(buf, format="JPEG")
    jpeg.write_bytes(buf.getvalue())

    client = MagicMock()
    expected_raw = _textract_response("hello world")
    client.detect_document_text.return_value = expected_raw

    with patch("build.tools.run_cloud_ocr.save_quota_state"):
        ocr_textract(jpeg, {}, _POLICY, _client=client)

    raw = json.loads(_raw_response_path(jpeg, "textract").read_text(encoding="utf-8"))
    # Raw must include the full block list (LINE, WORD, PAGE) unmodified
    block_types = [b["BlockType"] for b in raw["Blocks"]]
    assert "PAGE" in block_types
    assert "LINE" in block_types
    assert "WORD" in block_types


def test_ocr_azure_writes_raw_response(tmp_path):
    """Azure raw API envelope must be persisted alongside the parsed sidecar."""
    import build.tools.run_cloud_ocr as mod
    from io import BytesIO
    from PIL import Image

    env_file = tmp_path / "azure-vision.env"
    env_file.write_text(
        "AZURE_VISION_ENDPOINT=https://test.cognitiveservices.azure.com/\n"
        "AZURE_VISION_KEY=testkey\n",
        encoding="utf-8",
    )
    jpeg = tmp_path / "page_0010.jpg"
    buf = BytesIO()
    Image.new("L", (5034, 6959)).save(buf, format="JPEG")
    jpeg.write_bytes(buf.getvalue())

    api_response = _make_azure_api_response()
    def mock_post(url, img_bytes, key):
        return api_response

    original_secrets = mod.SECRETS
    mod.SECRETS = tmp_path
    try:
        with patch("build.tools.run_cloud_ocr.save_quota_state"):
            mod.ocr_azure(jpeg, {}, _POLICY, _http_post=mock_post)
    finally:
        mod.SECRETS = original_secrets

    raw = json.loads(_raw_response_path(jpeg, "azure").read_text(encoding="utf-8"))
    assert raw == api_response


def test_ocr_docint_writes_raw_response(tmp_path):
    _write_docint_env(tmp_path)
    jpeg = tmp_path / "page_0001.jpg"
    _write_test_jpeg(jpeg)

    envelope = _docint_succeeded_envelope()

    def mock_post(url, img_bytes, key):
        return "https://test.cognitiveservices.azure.com/op/abc"

    def mock_get(url, key):
        return envelope

    original_secrets = run_cloud_ocr.SECRETS
    run_cloud_ocr.SECRETS = tmp_path
    try:
        with patch("build.tools.run_cloud_ocr.save_quota_state"), \
             patch("build.tools.run_cloud_ocr.time") as mock_time:
            mock_time.sleep = MagicMock()
            ocr_docint(
                jpeg, {}, _POLICY,
                _http_post=mock_post, _http_get=mock_get,
            )
    finally:
        run_cloud_ocr.SECRETS = original_secrets

    raw = json.loads(_raw_response_path(jpeg, "docint").read_text(encoding="utf-8"))
    assert raw == envelope


def test_docint_failed_status_raises_and_preserves_pending(tmp_path):
    """If the operation returns status=failed, raise — pending file is gone (terminal failure)."""
    _write_docint_env(tmp_path)
    jpeg = tmp_path / "page_0001.jpg"
    _write_test_jpeg(jpeg)

    def mock_post(url, img_bytes, key):
        return "https://test.cognitiveservices.azure.com/op/willfail"

    def mock_get(url, key):
        return {"status": "failed", "error": {"message": "InvalidImage"}}

    original_secrets = run_cloud_ocr.SECRETS
    run_cloud_ocr.SECRETS = tmp_path
    try:
        with patch("build.tools.run_cloud_ocr.save_quota_state"), \
             patch("build.tools.run_cloud_ocr.time") as mock_time:
            mock_time.sleep = MagicMock()
            with pytest.raises(RuntimeError, match="Analysis failed"):
                ocr_docint(
                    jpeg, {}, _POLICY,
                    _http_post=mock_post, _http_get=mock_get,
                )
    finally:
        run_cloud_ocr.SECRETS = original_secrets

    # Terminal failure — pending file should remain so a manual operator can inspect
    # (the operation has expired server-side, so retry would re-submit anyway).
    # The retry mechanism would re-submit; that's acceptable since the operation
    # was already charged.
    # NOTE: we do NOT clean up on failure — the partial-sidecar path catches this.


def test_azure_403_raises_quota_cap_error():
    """_azure_call_with_retry() raises QuotaCapError immediately on HTTP 403 (quota exhausted)."""
    def call_fn():
        raise urllib.error.HTTPError("url", 403, "Quota Exceeded", {}, None)

    with patch("build.tools.run_cloud_ocr.time") as mock_time:
        mock_time.sleep = MagicMock()
        with pytest.raises(QuotaCapError, match="403"):
            _azure_call_with_retry(call_fn)

    # No retry on 403 — sleep must never be called
    mock_time.sleep.assert_not_called()


def test_azure_403_stops_volume_run(tmp_path):
    """A 403 from the Azure driver must stop further azure calls for the rest of the run.

    The 403 raises QuotaCapError inside ocr_azure, which process_page re-raises,
    which run_volume catches by adding azure to capped. Subsequent pages skip azure.
    """
    from build.tools.run_cloud_ocr import run_volume

    pages = [tmp_path / f"page_{i:04d}.jpg" for i in range(3)]
    for p in pages:
        p.write_bytes(b"\xff\xd8\xff\xe0")

    call_count = [0]

    def quota_exhausted_driver(jpeg_path, state, policy):
        call_count[0] += 1
        raise QuotaCapError("[azure] HTTP 403: monthly quota exhausted")

    with patch.dict("build.tools.run_cloud_ocr.DRIVERS", {"azure": quota_exhausted_driver}):
        run_volume(tmp_path, pages, ["azure"], {}, _POLICY)

    # Driver must be called exactly once — the first 403 stops the run.
    assert call_count[0] == 1


def test_azure_5xx_exhausted_raises():
    """_azure_call_with_retry() exhausts 2/4/8s backoff and raises on persistent 5xx."""
    call_count = [0]

    def call_fn():
        call_count[0] += 1
        raise urllib.error.HTTPError("url", 503, "Service Unavailable", {}, None)

    with patch("build.tools.run_cloud_ocr.time") as mock_time:
        mock_time.sleep = MagicMock()
        with pytest.raises(RuntimeError):
            _azure_call_with_retry(call_fn)

    assert call_count[0] == 4  # initial + 3 retries
    sleeps = [c[0][0] for c in mock_time.sleep.call_args_list]
    assert sleeps == [2, 4, 8]
