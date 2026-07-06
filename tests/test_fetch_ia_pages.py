"""Tests for build/tools/fetch_ia_pages.py.

TDD per TEST-16 / OCD convention. All 9 required test cases from the B2
task spec. Fixtures are real IA data trimmed to a handful of pages.
"""
import hashlib
import io
import json
import logging
import os
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
import jsonschema
from PIL import Image

REPO_ROOT = Path(__file__).parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "fetch_ia_pages"

# ---------------------------------------------------------------------------
# Import module under test
# ---------------------------------------------------------------------------
import importlib.util
import sys

_spec = importlib.util.spec_from_file_location(
    "fetch_ia_pages",
    REPO_ROOT / "build" / "tools" / "fetch_ia_pages.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

find_jp2_zip = _mod.find_jp2_zip
load_page_to_leaf = _mod.load_page_to_leaf
parse_pages_arg = _mod.parse_pages_arg
load_manifest = _mod.load_manifest
write_manifest_atomic = _mod.write_manifest_atomic
fetch_page = _mod.fetch_page
IA_ITEM_ID = _mod.IA_ITEM_ID


# ---------------------------------------------------------------------------
# Test 1: parse _files.xml fixture and extract JP2 leaf IDs via scandata
# ---------------------------------------------------------------------------
def test_find_jp2_zip_from_files_xml():
    """Parses the fixture _files.xml and finds the correct JP2 ZIP for vol 3."""
    files_xml = FIXTURE_DIR / f"{IA_ITEM_ID}_files.xml"
    root = ET.parse(str(files_xml)).getroot()
    zip_name = find_jp2_zip(root, volume=3)
    assert zip_name == (
        "03.NewSchaffHerzogEncycReligKnowl.v3.1909.Jackson.Sherman.Gilmore.1909._jp2.zip"
    )


def test_find_jp2_zip_accepts_single_alternate_item_archive():
    """Alternate IA scans can expose one item-level JP2 ZIP without a volume prefix."""
    root = ET.fromstring(
        "<files><file name='newschaffherzog37haucgoog_jp2.zip'/></files>"
    )

    assert find_jp2_zip(root, volume=1) == "newschaffherzog37haucgoog_jp2.zip"


def test_load_page_to_leaf_from_scandata():
    """Parses the fixture vol_03_scandata.xml and extracts correct page->leaf map."""
    scandata_xml = FIXTURE_DIR / "vol_03_scandata.xml"
    root = ET.parse(str(scandata_xml)).getroot()
    mapping = load_page_to_leaf(root)
    # Confirmed from real IA data
    assert mapping[75] == 97
    assert mapping[100] == 122
    assert mapping[164] == 186
    assert mapping[300] == 322
    assert mapping[331] == 353


# ---------------------------------------------------------------------------
# Test 2: skip page when manifest sha256 matches (idempotent per REL-04)
# ---------------------------------------------------------------------------
def test_skip_page_when_sha256_matches(tmp_path):
    """fetch_page returns None and makes no download when manifest sha256 matches."""
    # Create a fake JPEG on disk and record its sha256 in the manifest
    jpeg_path = tmp_path / "vol_03" / "page_0075.jpg"
    jpeg_path.parent.mkdir(parents=True)
    fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # minimal JPEG-like bytes
    jpeg_path.write_bytes(fake_jpeg)
    digest = "sha256:" + hashlib.sha256(fake_jpeg).hexdigest()

    manifest = {
        "ia_item_id": IA_ITEM_ID,
        "volume": 3,
        "pages": [
            {
                "page_num": 75,
                "sha256": digest,
                "local_path": str(jpeg_path),
                "image_mode": "L",
                "image_size": [5000, 6984],
                "ia_leaf_id": "0097",
                "ia_filename": "dummy",
                "fetched_at": "2026-05-24T00:00:00+00:00",
            }
        ],
    }
    manifest_path = tmp_path / "vol_03.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with patch.object(_mod, "_download_jp2", side_effect=AssertionError("should not download")):
        result = fetch_page(
            volume=3,
            page_num=75,
            leaf_num=97,
            zip_name="03._jp2.zip",
            out_dir=tmp_path / "vol_03",
            manifest_path=manifest_path,
            dry_run=False,
            force=False,
        )

    assert result is None  # skipped


# ---------------------------------------------------------------------------
# Test 3: re-fetches when --force is passed
# ---------------------------------------------------------------------------
def test_refetch_with_force(tmp_path):
    """fetch_page calls _download_jp2 even when manifest sha256 matches, if force=True."""
    jpeg_path = tmp_path / "vol_03" / "page_0075.jpg"
    jpeg_path.parent.mkdir(parents=True)
    fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    jpeg_path.write_bytes(fake_jpeg)
    digest = "sha256:" + hashlib.sha256(fake_jpeg).hexdigest()

    manifest = {
        "ia_item_id": IA_ITEM_ID,
        "volume": 3,
        "pages": [
            {
                "page_num": 75,
                "sha256": digest,
                "local_path": str(jpeg_path),
                "image_mode": "L",
                "image_size": [5000, 6984],
                "ia_leaf_id": "0097",
                "ia_filename": "dummy",
                "fetched_at": "2026-05-24T00:00:00+00:00",
            }
        ],
    }
    manifest_path = tmp_path / "vol_03.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    # Create a small grayscale image to return from mock download
    buf = io.BytesIO()
    Image.new("L", (100, 100)).save(buf, format="JPEG")
    fake_jp2_bytes = buf.getvalue()

    download_called = []

    def mock_download(zip_url, internal_path, headers, max_retries):
        download_called.append(internal_path)
        return fake_jp2_bytes

    with patch.object(_mod, "_download_jp2", side_effect=mock_download):
        fetch_page(
            volume=3,
            page_num=75,
            leaf_num=97,
            zip_name="03._jp2.zip",
            out_dir=tmp_path / "vol_03",
            manifest_path=manifest_path,
            dry_run=False,
            force=True,
        )

    assert len(download_called) == 1


# ---------------------------------------------------------------------------
# Test 4: honors Retry-After on a mocked 429 response
# ---------------------------------------------------------------------------
def test_retry_after_respected_on_429(tmp_path):
    """_download_jp2 sleeps for Retry-After seconds on a 429 before retrying."""
    import urllib.error
    import urllib.request

    call_count = [0]

    def mock_remote_zip(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            # Simulate 429 with Retry-After header
            headers = {"Retry-After": "2"}
            raise urllib.error.HTTPError(
                url="http://x", code=429, msg="Too Many Requests",
                hdrs=MagicMock(**{"get.side_effect": lambda k, d=None: headers.get(k, d)}),
                fp=None,
            )
        # Second attempt succeeds: return minimal grayscale JP2 bytes
        buf = io.BytesIO()
        Image.new("L", (10, 10)).save(buf, format="JPEG")
        return buf.getvalue()

    sleep_calls = []
    with patch("build.lib.ia_fetch._open_remote_zip", side_effect=mock_remote_zip):
        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            result = _mod._download_jp2(
                zip_url="http://fake/item/vol.zip",
                internal_path="vol_jp2/vol_0097.jp2",
                headers={"User-Agent": "test"},
                max_retries=3,
            )

    assert call_count[0] == 2
    assert any(s >= 2 for s in sleep_calls), f"Expected sleep >= 2s, got {sleep_calls}"


# ---------------------------------------------------------------------------
# Test 5: aborts page when Retry-After > 300
# ---------------------------------------------------------------------------
def test_abort_on_retry_after_over_300(tmp_path):
    """_download_jp2 raises RuntimeError if Retry-After exceeds MAX_RETRY_AFTER (300s)."""
    import urllib.error

    def mock_remote_zip(*args, **kwargs):
        headers = {"Retry-After": "301"}
        raise urllib.error.HTTPError(
            url="http://x", code=429, msg="Too Many Requests",
            hdrs=MagicMock(**{"get.side_effect": lambda k, d=None: headers.get(k, d)}),
            fp=None,
        )

    with patch("build.lib.ia_fetch._open_remote_zip", side_effect=mock_remote_zip):
        with pytest.raises(RuntimeError, match="Retry-After"):
            _mod._download_jp2(
                zip_url="http://fake/item/vol.zip",
                internal_path="vol_jp2/vol_0097.jp2",
                headers={"User-Agent": "test"},
                max_retries=3,
            )


def test_parse_retry_after_integer():
    from build.lib import ia_fetch

    assert ia_fetch._parse_retry_after("30") == 30


def test_parse_retry_after_http_date_exceeds_cap():
    from build.lib import ia_fetch

    result = ia_fetch._parse_retry_after("Fri, 01 Jan 2021 00:00:00 GMT")
    assert result > ia_fetch.MAX_RETRY_AFTER


def test_parse_retry_after_empty():
    from build.lib import ia_fetch

    assert ia_fetch._parse_retry_after("") == 5


# ---------------------------------------------------------------------------
# Test 5b: retries requests HTTP 5xx responses and propagates other statuses
# ---------------------------------------------------------------------------
def _requests_http_error(status_code):
    response = requests.Response()
    response.status_code = status_code
    response.url = "http://fake/item/vol.zip"
    return requests.exceptions.HTTPError(response=response)


def test_requests_http_error_500_retries_then_succeeds():
    """_download_jp2 retries requests HTTP 5xx failures before succeeding."""
    buf = io.BytesIO()
    Image.new("L", (10, 10)).save(buf, format="JPEG")
    jpeg_bytes = buf.getvalue()
    remote_open = MagicMock(
        side_effect=[
            _requests_http_error(500),
            _requests_http_error(500),
            jpeg_bytes,
        ]
    )

    with patch("build.lib.ia_fetch._open_remote_zip", remote_open):
        with patch.object(_mod.time, "sleep") as sleep:
            result = _mod._download_jp2(
                zip_url="http://fake/item/vol.zip",
                internal_path="vol_jp2/vol_0097.jp2",
                headers={"User-Agent": "test"},
                max_retries=3,
            )

    assert result == jpeg_bytes
    assert remote_open.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [2, 4]


def test_requests_http_error_404_does_not_retry():
    """_download_jp2 propagates requests HTTP 404 failures without retrying."""
    remote_open = MagicMock(side_effect=_requests_http_error(404))

    with patch("build.lib.ia_fetch._open_remote_zip", remote_open):
        with pytest.raises(requests.exceptions.HTTPError):
            _mod._download_jp2(
                zip_url="http://fake/item/vol.zip",
                internal_path="vol_jp2/vol_0097.jp2",
                headers={"User-Agent": "test"},
                max_retries=3,
            )

    assert remote_open.call_count == 1


# ---------------------------------------------------------------------------
# Test 6: writes manifest atomically (temp file + os.replace)
# ---------------------------------------------------------------------------
def test_manifest_written_atomically(tmp_path):
    """write_manifest_atomic uses a temp file then os.replace; no partial write on crash."""
    manifest_path = tmp_path / "vol_03.manifest.json"
    data = {"ia_item_id": IA_ITEM_ID, "volume": 3, "pages": []}

    replace_calls = []
    original_replace = os.replace

    def tracking_replace(src, dst):
        replace_calls.append((src, dst))
        original_replace(src, dst)

    with patch("os.replace", side_effect=tracking_replace):
        write_manifest_atomic(manifest_path, data)

    # Exactly one replace call
    assert len(replace_calls) == 1
    src, dst = replace_calls[0]
    # Source must be a temp path (not the final path)
    assert src != str(manifest_path)
    assert dst == str(manifest_path)
    # Final file exists and is valid JSON
    assert manifest_path.exists()
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == data

    # Simulate crash mid-write: os.replace raises; no partial file at final path
    manifest_path.unlink()
    with patch("os.replace", side_effect=OSError("simulated crash")):
        with pytest.raises(OSError):
            write_manifest_atomic(manifest_path, data)
    assert not manifest_path.exists()


def test_validate_manifest_flags_duplicate_leaf_id():
    errors, warnings = _mod.validate_manifest(
        {
            "pages": [
                {"page_num": 1, "ia_leaf_id": "0000"},
                {"page_num": 2, "ia_leaf_id": "0000"},
            ]
        }
    )

    assert errors == []
    assert any("duplicate ia_leaf_id" in warning and "0000" in warning for warning in warnings)


def test_validate_manifest_flags_duplicate_page_num():
    errors, warnings = _mod.validate_manifest(
        {
            "pages": [
                {"page_num": 1, "ia_leaf_id": "0000"},
                {"page_num": 1, "ia_leaf_id": "0001"},
            ]
        }
    )

    assert any("duplicate page_num" in error and "1" in error for error in errors)
    assert warnings == []


def test_validate_manifest_flags_first_page_above_2():
    errors, warnings = _mod.validate_manifest(
        {"pages": [{"page_num": 10, "ia_leaf_id": "0046"}]}
    )

    assert errors == []
    assert any("lowest page_num is 10" in warning for warning in warnings)


def test_validate_manifest_flags_leaf_gap():
    errors, warnings = _mod.validate_manifest(
        {
            "pages": [
                {"page_num": 1, "ia_leaf_id": "0040"},
                {"page_num": 2, "ia_leaf_id": "0042"},
            ]
        }
    )

    assert errors == []
    assert any("leaf gap" in warning and "0040" in warning and "0042" in warning for warning in warnings)


def test_validate_manifest_flags_leaf_gap_when_page_numbers_jump():
    errors, warnings = _mod.validate_manifest(
        {
            "pages": [
                {"page_num": 1, "ia_leaf_id": "0040"},
                {"page_num": 3, "ia_leaf_id": "0042"},
            ]
        }
    )

    assert errors == []
    assert any("leaf gap" in warning and "0040" in warning and "0042" in warning for warning in warnings)


def test_validate_manifest_clean_returns_empty_list():
    assert _mod.validate_manifest(
        {
            "pages": [
                {"page_num": 1, "ia_leaf_id": "0040"},
                {"page_num": 2, "ia_leaf_id": "0041"},
            ]
        }
    ) == ([], [])


def test_validate_manifest_duplicate_page_num_is_error():
    manifest = {
        "pages": [
            {"page_num": 5, "ia_leaf_id": "0010"},
            {"page_num": 5, "ia_leaf_id": "0011"},
        ]
    }
    errors, warnings = _mod.validate_manifest(manifest)
    assert any("duplicate page_num 5" in error for error in errors), errors
    assert any("lowest page_num is 5" in warning for warning in warnings)


def test_write_manifest_atomic_raises_on_duplicate_page(tmp_path):
    manifest_path = tmp_path / "vol_01.manifest.json"
    data = {
        "ia_item_id": "TestItem",
        "pages": [
            {"page_num": 3, "ia_leaf_id": "0005"},
            {"page_num": 3, "ia_leaf_id": "0006"},
        ],
        "gaps": [],
    }
    with pytest.raises(ValueError, match="duplicate"):
        _mod.write_manifest_atomic(manifest_path, data)
    assert not manifest_path.exists()


def test_manifest_write_includes_warnings_field(tmp_path, caplog):
    manifest_path = tmp_path / "vol_03.manifest.json"
    manifest = {
        "pages": [
            {"page_num": 1, "ia_leaf_id": "0040"},
            {"page_num": 2, "ia_leaf_id": "0042"},
        ]
    }

    with caplog.at_level(logging.WARNING, logger="fetch_ia_pages"):
        write_manifest_atomic(manifest_path, manifest)

    written = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert written["manifest_warnings"] == manifest["manifest_warnings"]
    assert any("leaf gap" in warning for warning in written["manifest_warnings"])
    assert "leaf gap" in caplog.text


def test_replace_with_retry_retries_winerror_32(tmp_path):
    src = tmp_path / "src.tmp"
    dst = tmp_path / "dst.json"
    src.write_text("data", encoding="utf-8")
    calls = {"n": 0}

    original_replace = os.replace

    def flaky_replace(s, d):
        calls["n"] += 1
        if calls["n"] < 2:
            err = OSError("sharing violation")
            err.winerror = 32
            raise err
        return original_replace(s, d)

    with patch.object(_mod.os, "replace", side_effect=flaky_replace):
        _mod._replace_with_retry(str(src), str(dst), retries=3, base_delay=0)

    assert dst.read_text(encoding="utf-8") == "data"
    assert calls["n"] == 2


def test_shared_manifest_lock_preserves_concurrent_entries(tmp_path):
    """Concurrent fetches with a shared lock keep every manifest page entry."""
    buf = io.BytesIO()
    Image.new("L", (10, 10)).save(buf, format="JPEG")
    image_bytes = buf.getvalue()
    manifest_path = tmp_path / "vol_03.manifest.json"
    out_dir = tmp_path / "vol_03"
    manifest_lock = threading.Lock()

    def fetch(page_num):
        return fetch_page(
            volume=3,
            page_num=page_num,
            leaf_num=page_num,
            zip_name="03._jp2.zip",
            out_dir=out_dir,
            manifest_path=manifest_path,
            dry_run=False,
            force=True,
            manifest_lock=manifest_lock,
        )

    with patch.object(_mod, "_download_jp2", return_value=image_bytes):
        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(fetch, range(1, 11)))

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [entry["page_num"] for entry in manifest["pages"]] == list(range(1, 11))


# ---------------------------------------------------------------------------
# Test 7: records image.mode from PIL before conversion to JPEG
# ---------------------------------------------------------------------------
def test_records_image_mode_before_conversion(tmp_path):
    """fetch_page stores the original image.mode in the manifest entry."""
    # Create a 1-bit (bitonal) test image to verify mode is captured pre-conversion
    buf = io.BytesIO()
    img = Image.new("1", (100, 100))
    img.save(buf, format="PNG")  # save as PNG since JPEG doesn't support mode 1
    bitonal_bytes = buf.getvalue()

    manifest_path = tmp_path / "vol_03.manifest.json"
    out_dir = tmp_path / "vol_03"
    out_dir.mkdir()

    with patch.object(_mod, "_download_jp2", return_value=bitonal_bytes):
        entry = fetch_page(
            volume=3,
            page_num=75,
            leaf_num=97,
            zip_name="03._jp2.zip",
            out_dir=out_dir,
            manifest_path=manifest_path,
            dry_run=False,
            force=True,
        )

    assert entry is not None
    assert entry["image_mode"] == "1"


# ---------------------------------------------------------------------------
# Test 8: local_path uses forward slashes (no backslashes on Windows)
# ---------------------------------------------------------------------------
def test_local_path_uses_forward_slashes(tmp_path):
    """local_path in the manifest entry contains no backslashes."""
    buf = io.BytesIO()
    Image.new("L", (10, 10)).save(buf, format="JPEG")
    fake_bytes = buf.getvalue()

    manifest_path = tmp_path / "vol_03.manifest.json"
    out_dir = tmp_path / "vol_03"

    with patch.object(_mod, "_download_jp2", return_value=fake_bytes):
        entry = fetch_page(
            volume=3,
            page_num=75,
            leaf_num=97,
            zip_name="03._jp2.zip",
            out_dir=out_dir,
            manifest_path=manifest_path,
            dry_run=False,
            force=False,
        )

    assert entry is not None
    assert "\\" not in entry["local_path"], (
        f"Backslash in local_path: {entry['local_path']!r}"
    )


# ---------------------------------------------------------------------------
# Test 9: page_count is populated after fetch
# ---------------------------------------------------------------------------
def test_page_count_is_highest_body_page_after_fetch(tmp_path):
    """page_count = highest TRUE printed body page (Model B), not len(pages).

    Fetching page 75 alone sets page_count to 75, because page_num is the real
    printed page number and the body total is the highest body page that exists.
    The old len(pages)==1 semantics would under-count any gapped volume.
    """
    buf = io.BytesIO()
    Image.new("L", (10, 10)).save(buf, format="JPEG")
    fake_bytes = buf.getvalue()

    manifest_path = tmp_path / "vol_03.manifest.json"
    out_dir = tmp_path / "vol_03"

    with patch.object(_mod, "_download_jp2", return_value=fake_bytes):
        fetch_page(
            volume=3,
            page_num=75,
            leaf_num=97,
            zip_name="03._jp2.zip",
            out_dir=out_dir,
            manifest_path=manifest_path,
            dry_run=False,
            force=False,
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["page_count"] == 75


# ---------------------------------------------------------------------------
# Test 8: --dry-run writes nothing to disk
# ---------------------------------------------------------------------------
def test_dry_run_writes_nothing(tmp_path):
    """fetch_page in dry_run mode makes no downloads and creates no files."""
    out_dir = tmp_path / "vol_03"
    manifest_path = tmp_path / "vol_03.manifest.json"

    with patch.object(_mod, "_download_jp2", side_effect=AssertionError("no download in dry-run")):
        result = fetch_page(
            volume=3,
            page_num=75,
            leaf_num=97,
            zip_name="03._jp2.zip",
            out_dir=out_dir,
            manifest_path=manifest_path,
            dry_run=True,
            force=False,
        )

    assert result is None
    assert not out_dir.exists() or list(out_dir.iterdir()) == []
    assert not manifest_path.exists()


def test_dry_run_logs_skip_for_cached_page(tmp_path, caplog):
    """Dry-run logs its action even when a matching cached page exists."""
    out_dir = tmp_path / "vol_03"
    out_dir.mkdir()
    jpeg_path = out_dir / "page_0075.jpg"
    jpeg_path.write_bytes(b"cached")
    manifest_path = tmp_path / "vol_03.manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_num": 75,
                        "sha256": "sha256:" + hashlib.sha256(b"cached").hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with caplog.at_level(logging.INFO, logger="fetch_ia_pages"):
        result = fetch_page(
            volume=3,
            page_num=75,
            leaf_num=97,
            zip_name="03._jp2.zip",
            out_dir=out_dir,
            manifest_path=manifest_path,
            dry_run=True,
            force=False,
        )

    assert result is None
    assert "[vol_03] page 0075 -- dry-run, skipping" in caplog.text


# ---------------------------------------------------------------------------
# Test 9: accepts comma-separated explicit page lists
# ---------------------------------------------------------------------------
def test_parse_pages_arg_comma_separated():
    """parse_pages_arg handles '75,100,164,300,331' (probe fetch format)."""
    pages = parse_pages_arg("75,100,164,300,331", total_pages=531)
    assert pages == [75, 100, 164, 300, 331]


def test_parse_pages_arg_range():
    """parse_pages_arg handles '42-49' range format."""
    pages = parse_pages_arg("42-49", total_pages=531)
    assert pages == [42, 43, 44, 45, 46, 47, 48, 49]


def test_parse_pages_arg_mixed_comma_and_range():
    result = _mod.parse_pages_arg("1,3-5,8", 20)
    assert result == [1, 3, 4, 5, 8]


def test_parse_pages_arg_all():
    """parse_pages_arg handles 'all' to return all page numbers."""
    pages = parse_pages_arg("all", total_pages=5)
    assert pages == [1, 2, 3, 4, 5]


def test_parallel_main_writes_same_jpegs_as_sequential_run(tmp_path):
    """Parallel CLI fetching writes the same JPEG files as one worker."""
    buf = io.BytesIO()
    Image.new("L", (10, 10)).save(buf, format="JPEG")
    image_bytes = buf.getvalue()
    page_to_leaf = {1: 11, 2: 12, 3: 13}

    def run_fetch(label, workers):
        out_dir = tmp_path / label
        manifest_path = tmp_path / f"{label}.manifest.json"
        argv = [
            "fetch_ia_pages.py",
            "--volume",
            "3",
            "--pages",
            "1,2,3",
            "--workers",
            str(workers),
            "--out-dir",
            str(out_dir),
            "--manifest",
            str(manifest_path),
        ]
        scandata_info = {
            "page_to_leaf": page_to_leaf,
            "duplicates": {},
            "numbered_range": (1, 3),
            "missing_pages": [],
        }
        with patch.object(
            _mod,
            "_resolve_volume",
            return_value=("03._jp2.zip", page_to_leaf, len(page_to_leaf), scandata_info),
        ):
            with patch("build.lib.ia_fetch._open_remote_zip", return_value=image_bytes):
                with patch.object(_mod, "CRAWL_DELAY", 0):
                    with patch.object(sys, "argv", argv):
                        assert _mod.main() == 0
        return {path.name: path.read_bytes() for path in out_dir.glob("*.jpg")}

    sequential_files = run_fetch("sequential", workers=1)
    parallel_files = run_fetch("parallel", workers=3)

    assert sorted(sequential_files) == ["page_0001.jpg", "page_0002.jpg", "page_0003.jpg"]
    assert parallel_files == sequential_files


def _test_image_bytes(size=(100, 80)):
    buf = io.BytesIO()
    Image.new("L", size).save(buf, format="PNG")
    return buf.getvalue()


def test_include_unnumbered_fetches_front_and_back_matter(tmp_path):
    out_dir = tmp_path / "vol_01"
    manifest_path = tmp_path / "vol_01.manifest.json"
    unnumbered = [
        {"leaf_num": 2, "page_type": "Title", "section": "front_matter"},
        {"leaf_num": 535, "page_type": "Normal", "section": "back_matter"},
    ]
    argv = [
        "fetch_ia_pages.py",
        "--volume",
        "1",
        "--pages",
        "10",
        "--include-unnumbered",
        "--workers",
        "2",
        "--out-dir",
        str(out_dir),
        "--manifest",
        str(manifest_path),
    ]

    scandata_info = {
        "page_to_leaf": {10: 20},
        "duplicates": {},
        "numbered_range": (10, 10),
        "missing_pages": [],
    }
    with patch.object(
        _mod, "_resolve_volume", return_value=("01._jp2.zip", {10: 20}, 1, scandata_info)
    ):
        with patch.object(_mod, "_resolve_unnumbered_leaves", return_value=unnumbered):
            with patch.object(_mod, "_download_jp2", return_value=_test_image_bytes()):
                with patch.object(_mod, "CRAWL_DELAY", 0):
                    with patch.object(sys, "argv", argv):
                        assert _mod.main() == 0

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [
        (entry["leaf_num"], entry["section"], entry["page_type"])
        for entry in manifest["unnumbered_leaves"]
    ] == [(2, "front_matter", "Title"), (535, "back_matter", "Normal")]
    assert (out_dir / "leaf_0002.jpg").exists()
    assert (out_dir / "leaf_0535.jpg").exists()


def test_from_alternate_item_writes_structured_provenance(tmp_path):
    with patch.object(_mod, "_download_jp2", return_value=_test_image_bytes()):
        entry = _mod.fetch_alternate_page(
            volume=1,
            page_num=96,
            leaf_num=64,
            crop=None,
            zip_name="alternate_jp2.zip",
            out_dir=tmp_path / "vol_01",
            manifest_path=tmp_path / "vol_01.manifest.json",
            dry_run=False,
            force=True,
            item_id="alternate-item",
            validation_status="bibliographic_matched",
            primary_image_size=[100, 80],
        )

    assert entry["ia_item_id"] == "alternate-item"
    assert entry["provenance"] == {
        "source_item_id": "alternate-item",
        "source_leaf": 64,
        "derivation": "direct",
        "crop_box": None,
        "replacement_reason": "missing from primary scan; fetched from alternate Internet Archive item",
        "validation_status": "bibliographic_matched",
        "dimension_variance": False,
    }


def test_from_alternate_item_crop_left_saves_left_half_with_correct_box(tmp_path):
    with patch.object(_mod, "_download_jp2", return_value=_test_image_bytes((200, 80))):
        entry = _mod.fetch_alternate_page(
            volume=1,
            page_num=96,
            leaf_num=64,
            crop="left",
            zip_name="alternate_jp2.zip",
            out_dir=tmp_path / "vol_01",
            manifest_path=tmp_path / "vol_01.manifest.json",
            dry_run=False,
            force=True,
            item_id="alternate-item",
            validation_status="visual_header_only",
            primary_image_size=[100, 80],
        )

    assert entry["image_size"] == [70, 80]
    assert entry["provenance"]["derivation"] == "crop_2up_left"
    assert entry["provenance"]["crop_box"] == {"l": 0, "t": 0, "r": 70, "b": 80}
    assert entry["provenance"]["dimension_variance"] is True


def test_from_alternate_item_bibliographic_check_sets_validation_status(caplog):
    primary = {"metadata": {"publisher": "Funk and Wagnalls", "year": "1908", "editor": "S. M. Jackson"}}
    matching = {"metadata": {"publisher": "Funk and Wagnalls", "year": "1908", "editor": "S. M. Jackson"}}
    mismatch = {"metadata": {"publisher": "Other Publisher", "year": "1908", "editor": "S. M. Jackson"}}

    assert _mod.bibliographic_validation_status(primary, matching) == "bibliographic_matched"
    with caplog.at_level(logging.WARNING, logger="fetch_ia_pages"):
        assert _mod.bibliographic_validation_status(primary, mismatch) == "visual_header_only"
    assert "bibliographic metadata does not match" in caplog.text


@pytest.mark.skipif(
    not (REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages" / "vol_01.manifest.json").exists(),
    reason="raw/internet-archive/schaff-herzog-pages/vol_01.manifest.json not downloaded",
)
def test_schema_validates_retrofitted_vol_01_manifest():
    manifest_path = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages" / "vol_01.manifest.json"
    schema_path = REPO_ROOT / "schemas" / "v1" / "source_manifest.schema.json"

    jsonschema.validate(
        json.loads(manifest_path.read_text(encoding="utf-8")),
        json.loads(schema_path.read_text(encoding="utf-8")),
    )


@pytest.mark.parametrize("vol", [1, 2, 5, 6, 8])
def test_schema_validates_rebuilt_nsh_manifest(vol):
    """Every rebuilt NSH manifest must validate against the source manifest
    schema -- exercises the Model-B gap statuses (absent_from_primary_scan,
    permanently_missing) and vol_06's duplicate-adjudication provenance
    (duplicate_leaves / kept_leaf / discarded_leaves)."""
    manifest_path = (
        REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
        / f"vol_{vol:02d}.manifest.json"
    )
    if not manifest_path.exists():
        pytest.skip(f"{manifest_path.name} not downloaded")
    schema_path = REPO_ROOT / "schemas" / "v1" / "source_manifest.schema.json"
    jsonschema.validate(
        json.loads(manifest_path.read_text(encoding="utf-8")),
        json.loads(schema_path.read_text(encoding="utf-8")),
    )


def _synthetic_manifest_with_alternate_page() -> dict:
    """Minimal schema-valid manifest: one primary page + one alternate-sourced
    page carrying provenance (derivation 'direct', crop_box null). Returns a
    fresh dict each call so a test can mutate it. Synthetic so these schema-rule
    tests do not depend on real data -- no rebuilt volume has an alternate page
    (front pages pp1-9 are now fetched from the primary scan)."""
    return {
        "ia_item_id": "PrimaryItem",
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": 1,
        "created_at": "2026-01-01T00:00:00Z",
        "page_count": 2,
        "pages": [
            {"page_num": 1, "ia_leaf_id": "0037", "ia_filename": "leaf0037.jp2"},
            {
                "page_num": 2,
                "ia_leaf_id": "0038",
                "ia_filename": "leaf0038.jp2",
                "ia_item_id": "AlternateItem",
                "provenance": {
                    "source_item_id": "AlternateItem",
                    "source_leaf": 50,
                    "derivation": "direct",
                    "crop_box": None,
                    "replacement_reason": "primary scan gap",
                    "validation_status": "text_continuity_verified",
                    "dimension_variance": False,
                },
            },
        ],
    }


def _source_manifest_schema() -> dict:
    return json.loads(
        (REPO_ROOT / "schemas" / "v1" / "source_manifest.schema.json").read_text(encoding="utf-8")
    )


def test_schema_rejects_alternate_page_without_provenance():
    schema = _source_manifest_schema()
    manifest = _synthetic_manifest_with_alternate_page()
    jsonschema.validate(manifest, schema)  # baseline is valid
    # An alternate-sourced page (per-page ia_item_id) MUST carry provenance.
    alternate_page = next(p for p in manifest["pages"] if p.get("ia_item_id"))
    alternate_page.pop("provenance")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(manifest, schema)


def test_schema_rejects_crop_box_for_direct_derivation():
    schema = _source_manifest_schema()
    manifest = _synthetic_manifest_with_alternate_page()
    alternate_page = next(p for p in manifest["pages"] if p.get("ia_item_id"))
    assert alternate_page["provenance"]["derivation"] == "direct"
    # derivation 'direct' requires crop_box null; a crop box must be rejected.
    alternate_page["provenance"]["crop_box"] = {"l": 0, "t": 0, "r": 100, "b": 100}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(manifest, schema)


# --- v4 dual-shape schema (P0.5) -------------------------------------------
# The schema accepts two top-level shapes during the migration window: the
# legacy two-list shape (tested above against vols 1,2,5,6,8) and the new
# leaf-sequence shape. A manifest carrying BOTH must reject (mixed-shape).


def _synthetic_v4_manifest() -> dict:
    """Minimal schema-valid v4 leaf-sequence manifest exercising all five kinds.
    Fresh dict each call so a test can mutate it."""
    return {
        "ia_item_id": "PrimaryItem",
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": 99,
        "created_at": "2026-06-11T00:00:00+00:00",
        "leaves": [
            {"leaf_num": 0, "page_num": None, "kind": "front_matter", "image_state": "pending"},
            {
                "leaf_num": 23, "page_num": 1, "kind": "body", "image_state": "present",
                "local_path": "raw/x/page_0001.jpg", "ia_leaf_id": "0023",
                "ia_filename": "x.jp2", "ia_item_id": "PrimaryItem",
                "sha256": "sha256:" + "a" * 64, "fetched_at": "2026-06-11T00:00:00+00:00",
                "image_mode": "L", "image_size": [100, 200],
            },
            {
                "leaf_num": 24, "page_num": None, "kind": "plate", "after_page_num": 1,
                "image_state": "present", "local_path": "raw/x/plate_0001_01.jpg",
                "ia_leaf_id": "0024", "ia_filename": "x.jp2", "ia_item_id": "PrimaryItem",
                "sha256": "sha256:" + "b" * 64, "fetched_at": "2026-06-11T00:00:00+00:00",
                "image_mode": "RGB", "image_size": [100, 200],
            },
            {
                "leaf_num": 50, "page_num": None, "kind": "discarded",
                "image_state": "not_imaged", "discard_reason": "exact duplicate of printed 1",
                "duplicate_of_page": 1,
            },
            {"leaf_num": 99, "page_num": None, "kind": "back_matter", "image_state": "pending"},
        ],
    }


def test_schema_validates_v4_leaf_sequence_manifest():
    jsonschema.validate(_synthetic_v4_manifest(), _source_manifest_schema())


def test_schema_rejects_mixed_shape_manifest():
    # A manifest carrying BOTH leaves[] and the legacy pages[] is ambiguous and
    # must reject (the new-shape oneOf branch not-excludes pages/unnumbered).
    schema = _source_manifest_schema()
    manifest = _synthetic_v4_manifest()
    manifest["page_count"] = 1
    manifest["pages"] = [{"page_num": 1, "ia_leaf_id": "0023", "ia_filename": "x.jp2"}]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(manifest, schema)


def test_schema_v4_plate_requires_after_page_num():
    schema = _source_manifest_schema()
    manifest = _synthetic_v4_manifest()
    plate = next(leaf for leaf in manifest["leaves"] if leaf["kind"] == "plate")
    plate.pop("after_page_num")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(manifest, schema)


def test_schema_v4_discarded_requires_discard_reason():
    schema = _source_manifest_schema()
    manifest = _synthetic_v4_manifest()
    disc = next(leaf for leaf in manifest["leaves"] if leaf["kind"] == "discarded")
    disc.pop("discard_reason")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(manifest, schema)


def test_schema_v4_local_path_requires_provenance_fields():
    schema = _source_manifest_schema()
    manifest = _synthetic_v4_manifest()
    body = next(leaf for leaf in manifest["leaves"] if leaf["kind"] == "body")
    body.pop("sha256")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(manifest, schema)


def test_gap_ledger_records_unresolved_pages_after_run(tmp_path):
    manifest_path = tmp_path / "vol_01.manifest.json"
    manifest_path.write_text(
        json.dumps({"ia_item_id": IA_ITEM_ID, "volume": 1, "pages": [{"page_num": 10}]}),
        encoding="utf-8",
    )

    _mod.record_unresolved_gaps(manifest_path, [9, 10, 11])

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["gaps"] == [
        {
            "page_num": 9,
            "status": "unresolved",
            "investigation_note": "no leaf mapping or fetched page image found for requested page",
        },
        {
            "page_num": 11,
            "status": "unresolved",
            "investigation_note": "no leaf mapping or fetched page image found for requested page",
        },
    ]


def test_gap_ledger_skips_out_of_range_pages_when_coverage_present(tmp_path):
    """Phantom-gap guard: a requested page beyond ABBYY pages_parsed is not
    recorded; an in-range missing page still is. Prevents regenerating the
    out-of-range phantom gaps (vol_03 pp501-531, etc.)."""
    manifest_path = tmp_path / "vol_03.manifest.json"
    manifest_path.write_text(
        json.dumps({"ia_item_id": IA_ITEM_ID, "volume": 3, "pages": [{"page_num": 1}]}),
        encoding="utf-8",
    )
    vol_dir = tmp_path / "vol_03"
    vol_dir.mkdir()
    (vol_dir / "coverage.ia-abbyy.json").write_text(
        json.dumps({"pages_parsed": 500}), encoding="utf-8"
    )

    _mod.record_unresolved_gaps(manifest_path, [2, 501, 531])

    recorded = {
        g["page_num"]
        for g in json.loads(manifest_path.read_text(encoding="utf-8")).get("gaps", [])
    }
    assert 2 in recorded         # in-range missing page still recorded
    assert 501 not in recorded   # out-of-range phantom skipped
    assert 531 not in recorded


def test_existing_parallel_lock_behaviour_unchanged(tmp_path):
    test_shared_manifest_lock_preserves_concurrent_entries(tmp_path)


# ---------------------------------------------------------------------------
# Model-B fetcher fixes: scandata duplicate/gap detection, page_count semantics,
# --pages all enumeration, and scan-gap recording.
# ---------------------------------------------------------------------------
def _scandata_xml(rows):
    """Build a minimal scandata XML from (leaf, pageNumber-or-None) rows."""
    parts = ["<book><pageData>"]
    for leaf, pn in rows:
        if pn is None:
            parts.append(f'<page leafNum="{leaf}"></page>')
        else:
            parts.append(f'<page leafNum="{leaf}"><pageNumber>{pn}</pageNumber></page>')
    parts.append("</pageData></book>")
    return ET.fromstring("".join(parts))


def test_load_scandata_pages_detects_duplicates_and_gaps():
    """A duplicate pageNumber and an in-range gap are both surfaced, not dropped."""
    # leaves 1..5 -> pages 10,11,(gap 12),13 on two leaves
    root = _scandata_xml([(1, 10), (2, 11), (3, 13), (4, 13), (5, 14)])
    info = _mod.load_scandata_pages(root)
    # Duplicate page 13 keeps both leaves for adjudication
    assert info["duplicates"] == {13: [3, 4]}
    # page 12 is in [10,14] but has no leaf -> a real scan gap
    assert info["missing_pages"] == [12]
    assert info["numbered_range"] == (10, 14)
    # Back-compat: page_to_leaf is last-wins, single leaf per page
    assert info["page_to_leaf"][13] == 4


def test_load_page_to_leaf_wrapper_matches_structured_map():
    root = _scandata_xml([(1, 10), (2, 11), (3, 13), (4, 13)])
    assert _mod.load_page_to_leaf(root) == _mod.load_scandata_pages(root)["page_to_leaf"]


def test_compute_page_count_includes_permanently_missing_tail():
    """vol_13-shape: last body pages missing -> page_count reaches the body max."""
    data = {
        "pages": [{"page_num": 206}, {"page_num": 207}, {"page_num": 208}],
        "gaps": [
            {"page_num": 209, "status": "permanently_missing"},
            {"page_num": 210, "status": "permanently_missing"},
            {"page_num": 211, "status": "permanently_missing"},
        ],
    }
    assert _mod._compute_page_count(data) == 211


def test_compute_page_count_ignores_unresolved_backmatter_gap():
    """An 'unresolved'/back-matter gap above the body must not inflate page_count."""
    data = {
        "pages": [{"page_num": p} for p in range(1, 501)],
        "gaps": [{"page_num": 999, "status": "unresolved"}],
    }
    assert _mod._compute_page_count(data) == 500


def test_write_manifest_atomic_raises_on_v4_manifest(tmp_path):
    """write_manifest_atomic must not silently corrupt v4 (leaves[]) manifests."""
    manifest_path = tmp_path / "vol_01.manifest.json"
    data = {
        "ia_item_id": IA_ITEM_ID,
        "volume": 1,
        "page_count": 500,
        "leaves": [{"leaf_num": 1, "kind": "body", "page_num": 1}],
    }
    with pytest.raises(ValueError, match="v4"):
        _mod.write_manifest_atomic(manifest_path, data)


def test_record_scandata_gaps_records_absent_and_duplicate(tmp_path):
    manifest_path = tmp_path / "vol_01.manifest.json"
    manifest_path.write_text(
        json.dumps({"ia_item_id": IA_ITEM_ID, "volume": 1, "pages": [{"page_num": 95}]}),
        encoding="utf-8",
    )

    _mod.record_scandata_gaps(manifest_path, missing_pages=[96, 97], duplicates={})
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_page = {g["page_num"]: g for g in manifest["gaps"]}
    assert by_page[96]["status"] == "absent_from_primary_scan"
    assert by_page[97]["status"] == "absent_from_primary_scan"

    _mod.record_scandata_gaps(manifest_path, missing_pages=[], duplicates={478: [505, 506]})
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dup = {g["page_num"]: g for g in manifest["gaps"]}[478]
    assert dup["status"] == "duplicate_needs_adjudication"
    assert dup["duplicate_leaves"] == [505, 506]


def test_record_scandata_gaps_is_idempotent(tmp_path):
    manifest_path = tmp_path / "vol_01.manifest.json"
    manifest_path.write_text(
        json.dumps({"ia_item_id": IA_ITEM_ID, "volume": 1, "pages": [{"page_num": 95}]}),
        encoding="utf-8",
    )
    _mod.record_scandata_gaps(manifest_path, missing_pages=[96, 97], duplicates={})
    first = json.loads(manifest_path.read_text(encoding="utf-8"))["gaps"]
    _mod.record_scandata_gaps(manifest_path, missing_pages=[96, 97], duplicates={})
    second = json.loads(manifest_path.read_text(encoding="utf-8"))["gaps"]
    assert first == second


def test_pages_all_enumerates_numbered_keys_and_records_gap(tmp_path):
    """--pages all fetches only real printed pages (gap at 3 stays a hole)."""
    buf = io.BytesIO()
    Image.new("L", (10, 10)).save(buf, format="JPEG")
    image_bytes = buf.getvalue()
    # printed pages 1,2,4 present; page 3 missing from scan
    page_to_leaf = {1: 11, 2: 12, 4: 14}
    scandata_info = {
        "page_to_leaf": page_to_leaf,
        "duplicates": {},
        "numbered_range": (1, 4),
        "missing_pages": [3],
    }
    out_dir = tmp_path / "vol_03"
    manifest_path = tmp_path / "vol_03.manifest.json"
    argv = [
        "fetch_ia_pages.py", "--volume", "3", "--pages", "all",
        "--workers", "1", "--out-dir", str(out_dir), "--manifest", str(manifest_path),
    ]
    with patch.object(
        _mod, "_resolve_volume",
        return_value=("03._jp2.zip", page_to_leaf, 4, scandata_info),
    ):
        with patch("build.lib.ia_fetch._open_remote_zip", return_value=image_bytes):
            with patch.object(_mod, "CRAWL_DELAY", 0):
                with patch.object(sys, "argv", argv):
                    assert _mod.main() == 0

    files = sorted(p.name for p in out_dir.glob("page_*.jpg"))
    assert files == ["page_0001.jpg", "page_0002.jpg", "page_0004.jpg"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    gap3 = {g["page_num"]: g for g in manifest.get("gaps", [])}.get(3)
    assert gap3 is not None and gap3["status"] == "absent_from_primary_scan"
    # page_count = highest body page (4), present + the recorded gap
    assert manifest["page_count"] == 4


# ---------------------------------------------------------------------------
# Phase 0: primary-item explicit-leaf fetch (front body pages unnumbered in
# scandata). These map a primary leaf -> printed page name with NO alternate
# provenance block -- they are real primary pages, not alternate-sourced ones.
# ---------------------------------------------------------------------------
def test_primary_leaf_page_spec_fetches_front_pages_without_provenance(tmp_path):
    """--primary-leaf-page-spec fetches PRIMARY leaves under printed-page names.

    The front body pages (pp1..min-1) carry no scandata pageNumber but are real
    body pages at a constant leaf offset. They must land as page_NNNN.jpg with no
    alternate-provenance block (that block tags a page as alternate-sourced; a
    front page is from the primary item).
    """
    buf = io.BytesIO()
    Image.new("L", (10, 10)).save(buf, format="JPEG")
    image_bytes = buf.getvalue()
    page_to_leaf = {10: 46}  # one numbered page via --pages all
    scandata_info = {
        "page_to_leaf": page_to_leaf,
        "duplicates": {},
        "numbered_range": (10, 10),
        "missing_pages": [],
    }
    out_dir = tmp_path / "vol_01"
    manifest_path = tmp_path / "vol_01.manifest.json"
    argv = [
        "fetch_ia_pages.py", "--volume", "1", "--pages", "all",
        "--primary-leaf-page-spec", "37:1,45:9",
        "--workers", "1", "--out-dir", str(out_dir), "--manifest", str(manifest_path),
    ]
    with patch.object(
        _mod, "_resolve_volume",
        return_value=("01._jp2.zip", page_to_leaf, 50, scandata_info),
    ):
        with patch("build.lib.ia_fetch._open_remote_zip", return_value=image_bytes):
            with patch.object(_mod, "CRAWL_DELAY", 0):
                with patch.object(sys, "argv", argv):
                    assert _mod.main() == 0

    files = sorted(p.name for p in out_dir.glob("page_*.jpg"))
    assert files == ["page_0001.jpg", "page_0009.jpg", "page_0010.jpg"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_page = {p["page_num"]: p for p in manifest["pages"]}
    # Front pages map to their primary leaves ...
    assert by_page[1]["ia_leaf_id"] == "0037"
    assert by_page[9]["ia_leaf_id"] == "0045"
    # ... and carry NO alternate-provenance markers (they are primary pages).
    assert "provenance" not in by_page[1]
    assert "ia_item_id" not in by_page[1]
    assert "provenance" not in by_page[9]


def test_primary_leaf_page_spec_runs_without_pages(tmp_path):
    """--primary-leaf-page-spec can run alone (front-only top-up of an existing dir)."""
    buf = io.BytesIO()
    Image.new("L", (10, 10)).save(buf, format="JPEG")
    image_bytes = buf.getvalue()
    page_to_leaf = {10: 46}
    scandata_info = {
        "page_to_leaf": page_to_leaf,
        "duplicates": {},
        "numbered_range": (10, 10),
        "missing_pages": [],
    }
    out_dir = tmp_path / "vol_01"
    manifest_path = tmp_path / "vol_01.manifest.json"
    argv = [
        "fetch_ia_pages.py", "--volume", "1",
        "--primary-leaf-page-spec", "37:1",
        "--workers", "1", "--out-dir", str(out_dir), "--manifest", str(manifest_path),
    ]
    with patch.object(
        _mod, "_resolve_volume",
        return_value=("01._jp2.zip", page_to_leaf, 50, scandata_info),
    ):
        with patch("build.lib.ia_fetch._open_remote_zip", return_value=image_bytes):
            with patch.object(_mod, "CRAWL_DELAY", 0):
                with patch.object(sys, "argv", argv):
                    assert _mod.main() == 0

    assert (out_dir / "page_0001.jpg").exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert {p["page_num"] for p in manifest["pages"]} == {1}
