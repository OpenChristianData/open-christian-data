"""Retain a declared New Advent URL cohort without deriving or accepting text.

This acquisition helper repairs the legacy parser's discarded-response gap.
Its receipt is acquisition evidence, not a SourceManifest or completeness proof.
Each invocation needs a new destination, so a new web witness cannot replace an
earlier source. HTTP failures stop the cohort and leave an explicit partial
receipt. The default one-second delay applies between every pair of requests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


USER_AGENT = "OCD-Crawler/1.0 (Open Christian Data; public domain text research)"


def checked_url(url: str, *, allow_images: bool = False, allow_stylesheets: bool = False) -> str:
    parsed = urllib.parse.urlsplit(url)
    permitted_path = parsed.path.startswith("/cathen/") or (
        allow_images and parsed.path.startswith("/images/")
        and Path(parsed.path).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".tif", ".tiff"}
    ) or (allow_stylesheets and parsed.path.startswith("/utility/") and Path(parsed.path).suffix.lower() == ".css")
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.newadvent.org"
        or not permitted_path
        or parsed.query
        or parsed.fragment
        or "%" in parsed.path
        or "\\" in parsed.path
        or any(part in {".", ".."} for part in parsed.path.split("/"))
    ):
        raise ValueError(f"Not an exact HTTPS New Advent cathen URL: {url}")
    return url


class _BoundRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, *, allow_images=False, allow_stylesheets=False):
        super().__init__()
        self.allow_images = allow_images
        self.allow_stylesheets = allow_stylesheets

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl, allow_images=self.allow_images, allow_stylesheets=self.allow_stylesheets)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def retain(urls: list[str], destination: Path, *, opener=None, sleeper=time.sleep, allow_images: bool = False, allow_stylesheets: bool = False) -> dict:
    """Capture exact response bytes and account for every requested member.

    URLs are caller-declared in order. No volume membership is inferred from a
    filename prefix. A successful receipt only covers this explicit URL list.
    """
    if not urls or len(set(urls)) != len(urls):
        raise ValueError("A nonempty list of distinct URLs is required")
    urls = [checked_url(url, allow_images=allow_images, allow_stylesheets=allow_stylesheets) for url in urls]
    destination.mkdir(parents=True, exist_ok=False)
    transport = opener or urllib.request.build_opener(_BoundRedirects(allow_images=allow_images, allow_stylesheets=allow_stylesheets))
    receipt = {
        "contract": "ocd-newadvent-retained-cohort-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "caller-declared-urls-only",
        "status": "partial",
        "work_or_volume_completeness_established": False,
        "historical_source_claims_reconciled": False,
        "publication_authorized": False,
        "members": [{"url": url, "status": "not-attempted"} for url in urls],
    }
    with (destination / "request-plan.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump({"created_at": receipt["created_at"], "urls": urls}, stream, indent=2)
        stream.write("\n")
    try:
        for ordinal, member in enumerate(receipt["members"], 1):
            if ordinal > 1:
                sleeper(1.0)
            request = urllib.request.Request(member["url"], headers={"User-Agent": USER_AGENT})
            member["status"] = "attempting"
            try:
                with transport.open(request, timeout=30) as response:
                    final_url = checked_url(response.geturl(), allow_images=allow_images, allow_stylesheets=allow_stylesheets)
                    status = response.status
                    headers = [list(item) for item in response.headers.items()]
                    payload = response.read()
                member.update(http_status=status, final_url=final_url, headers=headers)
                if status != 200:
                    raise ValueError(f"Unexpected HTTP status {status}")
                source_path = urllib.parse.urlsplit(member["url"]).path
                extension = ".html" if source_path.startswith("/cathen/") else Path(source_path).suffix.lower()
                filename = f"{ordinal:06d}{extension}"
                with (destination / filename).open("xb") as stream:
                    stream.write(payload)
                member.update(
                    status="retained", path=filename, bytes=len(payload),
                    sha256=hashlib.sha256(payload).hexdigest(),
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                )
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                member.update(status="failed", error_type=type(exc).__name__, error=str(exc))
                if isinstance(exc, urllib.error.HTTPError):
                    member["http_status"] = exc.code
                    error_payload = exc.read()
                    error_filename = f"{ordinal:06d}.http-error.html"
                    with (destination / error_filename).open("xb") as stream:
                        stream.write(error_payload)
                    member["error_response"] = {"path": error_filename, "bytes": len(error_payload), "sha256": hashlib.sha256(error_payload).hexdigest(), "final_url": exc.geturl(), "headers": dict(exc.headers or {}), "retrieved_at": datetime.now(timezone.utc).isoformat()}
                break
            finally:
                # A terminated long crawl must not lose successful-response provenance.
                with (destination / "acquisition.events.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(json.dumps({"ordinal": ordinal, **member}, ensure_ascii=False) + "\n")
                    stream.flush()
        if all(member["status"] == "retained" for member in receipt["members"]):
            receipt["status"] = "declared-urls-retained"
    finally:
        with (destination / "acquisition.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(receipt, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", action="append", required=True, help="Exact URL; repeat in source order")
    parser.add_argument("--destination", type=Path, required=True, help="New dated durable raw directory")
    parser.add_argument("--allow-images", action="store_true")
    parser.add_argument("--allow-stylesheets", action="store_true")
    args = parser.parse_args()
    result = retain(args.url, args.destination, allow_images=args.allow_images, allow_stylesheets=args.allow_stylesheets)
    print(json.dumps({
        "status": result["status"],
        "requested_members": len(result["members"]),
        "retained_members": sum(member["status"] == "retained" for member in result["members"]),
        "receipt": str(args.destination / "acquisition.json"),
        "failures": [member for member in result["members"] if member["status"] == "failed"],
    }, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "declared-urls-retained" else 1


if __name__ == "__main__":
    raise SystemExit(main())
