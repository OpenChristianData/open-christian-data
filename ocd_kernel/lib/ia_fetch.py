"""Internet Archive JP2 download helpers shared across NSH pipeline tools.

Extracted from the OCR fetcher now routed at
../EzraOCR/ezra/tools/fetch_ia_pages.py so multiple tools can import these
without a dynamic importlib.util coupling.
"""
from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from remotezip import RemoteZip
from requests.exceptions import HTTPError as RequestsHTTPError

MAX_RETRY_AFTER = 300   # abort if Retry-After exceeds this many seconds (API-04)
MAX_RETRIES = 3

logger = logging.getLogger(__name__)


def find_jp2_zip(files_xml_root: ET.Element, volume: int) -> str:
    """Find the JP2 ZIP filename for a volume from a parsed _files.xml root."""
    vol_prefix = f"{volume:02d}."
    candidates = []
    for f in files_xml_root.findall("file"):
        name = f.get("name", "")
        if not name.endswith("_jp2.zip"):
            continue
        candidates.append(name)
        if name.startswith(vol_prefix):
            return name
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(f"No JP2 ZIP found for volume {volume} in _files.xml")


def _open_remote_zip(
    zip_url: str,
    internal_path: str,
    headers: dict,
    timeout: int = 60,
) -> bytes:
    """Open a remote ZIP via range requests and read one internal file."""
    with RemoteZip(zip_url, headers=headers, timeout=timeout) as rz:
        return rz.read(internal_path)


def _parse_retry_after(value: str) -> int:
    """Parse a Retry-After header value to seconds.

    Accepts integer strings ("30") and HTTP-dates
    ("Fri, 01 Jan 2021 00:00:00 GMT"). Returns a default of 5 on parse
    failure so the caller can decide whether to retry.
    """
    if not value:
        return 5
    value = value.strip()
    try:
        return int(value)
    except ValueError:
        pass
    return MAX_RETRY_AFTER + 1


def fetch_url_bytes(url: str, headers: dict, timeout: int = 60) -> bytes:
    """Fetch URL bytes with 429 Retry-After cap and 5xx exponential backoff."""
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code == 429:
                retry_after_raw = exc.hdrs.get("Retry-After", "5") if exc.hdrs else "5"
                retry_after = _parse_retry_after(retry_after_raw)
                if retry_after > MAX_RETRY_AFTER:
                    raise RuntimeError(
                        f"Retry-After {retry_after}s exceeds maximum {MAX_RETRY_AFTER}s; "
                        f"aborting {url}"
                    ) from exc
                logger.warning(
                    "HTTP 429 -- Retry-After %ds (attempt %d/%d): %s",
                    retry_after, attempt + 1, MAX_RETRIES, url,
                )
                time.sleep(retry_after)
            elif 500 <= exc.code < 600:
                if attempt < MAX_RETRIES - 1:
                    delay = 2 ** (attempt + 1)
                    logger.warning(
                        "HTTP %d -- retrying in %ds (attempt %d/%d): %s",
                        exc.code, delay, attempt + 1, MAX_RETRIES, url,
                    )
                    time.sleep(delay)
                else:
                    raise
            else:
                raise
    raise RuntimeError(f"Failed to fetch {url} after {MAX_RETRIES} attempts") from last_exc


def _download_jp2(
    zip_url: str,
    internal_path: str,
    headers: dict,
    max_retries: int = MAX_RETRIES,
) -> bytes:
    """Download one JP2 from a remote ZIP. Handles 429 Retry-After and 5xx backoff."""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return _open_remote_zip(zip_url, internal_path, headers)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code == 429:
                retry_after_raw = exc.hdrs.get("Retry-After", "5") if exc.hdrs else "5"
                retry_after = _parse_retry_after(retry_after_raw or "")
                if retry_after > MAX_RETRY_AFTER:
                    raise RuntimeError(
                        f"Retry-After {retry_after}s exceeds maximum {MAX_RETRY_AFTER}s; "
                        f"aborting {internal_path}"
                    ) from exc
                logger.warning(
                    "HTTP 429 -- Retry-After %ds (attempt %d/%d): %s",
                    retry_after, attempt + 1, max_retries, internal_path,
                )
                time.sleep(retry_after)
            elif 500 <= exc.code < 600:
                if attempt < max_retries - 1:
                    delay = 2 ** (attempt + 1)
                    logger.warning(
                        "HTTP %d -- retrying in %ds (attempt %d/%d): %s",
                        exc.code, delay, attempt + 1, max_retries, internal_path,
                    )
                    time.sleep(delay)
                else:
                    raise
            else:
                raise
        except RequestsHTTPError as exc:
            last_exc = exc
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code is not None and 500 <= status_code < 600:
                if attempt < max_retries - 1:
                    delay = 2 ** (attempt + 1)
                    logger.warning(
                        "HTTP %d -- retrying in %ds (attempt %d/%d): %s",
                        status_code, delay, attempt + 1, max_retries, internal_path,
                    )
                    time.sleep(delay)
                else:
                    raise
            else:
                raise
    raise RuntimeError(
        f"Failed to download {internal_path} after {max_retries} attempts"
    ) from last_exc
