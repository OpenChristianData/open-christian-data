"""Capture an exact live Compare into a fresh, self-contained evidence directory.

This external client records observations and bytes, never review acceptance.
Run with python -m cvw_app.capture_review --help. Playwright is optional until capture.
"""

from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from urllib.request import urlopen
from PIL import Image


class CaptureError(ValueError):
    pass


def canonical(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def session_identity(value):
    session = value.get("session", value)
    fields = (
        "session_id",
        "origin",
        "implementation_sha256",
        "catalog_sha256",
        "candidate_sha256",
    )
    if (
        any(not session.get(field) for field in fields if field != "catalog_sha256")
        or "catalog_sha256" not in session
        or (
            session["catalog_sha256"] is not None
            and not session["catalog_sha256"]
        )
    ):
        raise CaptureError("session receipt lacks exact identity fields")
    origin = urlsplit(session["origin"])
    if (
        origin.scheme != "http"
        or origin.hostname not in {"127.0.0.1", "localhost", "::1"}
        or origin.username
        or origin.password
        or origin.query
        or origin.fragment
        or origin.path not in {"", "/"}
    ):
        raise CaptureError("session origin must be an explicit loopback HTTP origin")
    return {field: session[field] for field in fields}


def verify_session(origin, expected):
    with urlopen(origin + "/api/review/v1/session", timeout=15) as response:
        value = json.loads(response.read(1000000))
    if (
        session_identity(value) != expected
        or value.get("session", value).get("state") != "ready"
    ):
        raise CaptureError("live CVW session differs from the supplied ready receipt")
    return value


def validate_route(route, identity):
    parsed = urlsplit(route)
    origin = urlsplit(identity["origin"])
    if (
        (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc)
        or not parsed.path.startswith("/review/works/")
        or parsed.fragment
    ):
        raise CaptureError("Compare URL must belong to the supplied session")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if query.get("mode") != ["compare"]:
        raise CaptureError("an explicit Compare route is required")
    for side in ("left", "right"):
        for field in ("Stage", "Artifact", "Version", "Location"):
            values = query.get(side + field, [])
            if len(values) != 1 or not values[0]:
                raise CaptureError(
                    "explicit pane identities and locations are required"
                )
    return query


def validate_targets(targets):
    """Validate optional left/right literal anchors before starting a browser."""
    if targets is None:
        return None
    if not isinstance(targets, dict) or set(targets) != {"left", "right"}:
        raise CaptureError("targets must specify exactly left and right")
    fields = {"scope_selector", "scope_prefix", "literal", "occurrence"}
    checked = {}
    for side, spec in targets.items():
        if not isinstance(spec, dict) or set(spec) != fields:
            raise CaptureError(f"{side} target must specify selector, prefix, literal, and occurrence")
        if any(not isinstance(spec[key], str) or not spec[key] for key in fields - {"occurrence"}):
            raise CaptureError(f"{side} target strings must be non-empty")
        if type(spec["occurrence"]) is not int or spec["occurrence"] < 0:
            raise CaptureError(f"{side} occurrence must be a non-negative zero-based integer")
        checked[side] = dict(spec)
    return checked


def locate_target(page, side, spec, *, scroll=True, require_visible=True):
    """Independently scroll one exact literal into its pane and return measured evidence."""
    result = page.evaluate("""({side, spec, scroll}) => {
      const scopes = Array.from(document.querySelectorAll(spec.scope_selector))
        .filter(node => (node.textContent || '').startsWith(spec.scope_prefix));
      if (scopes.length !== 1) return {error: scopes.length ? 'ambiguous scope' : 'scope absent', count: scopes.length};
      const scope = scopes[0], text = scope.textContent || '';
      const starts = [];
      for (let at = 0; (at = text.indexOf(spec.literal, at)) !== -1; at += spec.literal.length) starts.push(at);
      if (spec.occurrence >= starts.length) return {error: 'target occurrence absent', count: starts.length};
      const start = starts[spec.occurrence], walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
      let node, offset = 0, first = null, last = null, firstOffset = 0, lastOffset = 0;
      while ((node = walker.nextNode())) {
        const end = offset + node.nodeValue.length;
        if (first === null && start < end) { first = node; firstOffset = start - offset; }
        if (start + spec.literal.length <= end && start + spec.literal.length > offset) { last = node; lastOffset = start + spec.literal.length - offset; break; }
        offset = end;
      }
      if (!first || !last) return {error: 'literal does not map to rendered text'};
      const range = document.createRange(); range.setStart(first, firstOffset); range.setEnd(last, lastOffset);
      const rect = range.getBoundingClientRect(), article = document.querySelector(`[data-review-side="${side}"] article.artifact-content`);
      if (!article) return {error: 'pane content scroller absent'};
      const before = {scrollTop: article.scrollTop, scrollHeight: article.scrollHeight, clientHeight: article.clientHeight};
      const box = article.getBoundingClientRect();
      const targetTop = article.scrollTop + rect.top - box.top;
      if (scroll && (rect.top < box.top || rect.bottom > box.bottom)) article.scrollTop = Math.max(0, targetTop - Math.max(0, (article.clientHeight - rect.height) / 2));
      const afterRect = range.getBoundingClientRect(), afterBox = article.getBoundingClientRect();
      return {literal: spec.literal, scope_selector: spec.scope_selector, scope_prefix: spec.scope_prefix,
        match_count: starts.length, occurrence: spec.occurrence,
        rect: {x: afterRect.x, y: afterRect.y, width: afterRect.width, height: afterRect.height, top: afterRect.top, right: afterRect.right, bottom: afterRect.bottom, left: afterRect.left},
        scroll: {before, after: {scrollTop: article.scrollTop, scrollHeight: article.scrollHeight, clientHeight: article.clientHeight},
          viewport: {top: afterBox.top, bottom: afterBox.bottom, left: afterBox.left, right: afterBox.right}},
        browser_viewport: {width: window.innerWidth, height: window.innerHeight},
        visible: afterRect.height > 0 && afterRect.width > 0
          && afterRect.top >= Math.max(0, afterBox.top)
          && afterRect.bottom <= Math.min(window.innerHeight, afterBox.bottom)
          && afterRect.left >= Math.max(0, afterBox.left)
          && afterRect.right <= Math.min(window.innerWidth, afterBox.right)};
    }""", {"side": side, "spec": spec, "scroll": scroll})
    if result.get("error"):
        raise CaptureError(f"{side} target: {result['error']} (matches={result.get('count', 0)})")
    if require_visible and not result.get("visible"):
        raise CaptureError(f"{side} target remains clipped after independent scrolling")
    return result


def capture_target_frame(page, targets):
    """Position the pair, then measure both without scrolling before capture."""
    prepared = [
        locate_target(page, side, targets[side], require_visible=False)
        for side in ("left", "right")
    ]
    page.evaluate("""rects => {
      const top = Math.min(...rects.map(r => r.top));
      const bottom = Math.max(...rects.map(r => r.bottom));
      const left = Math.min(...rects.map(r => r.left));
      const right = Math.max(...rects.map(r => r.right));
      window.scrollBy({top: (top + bottom - innerHeight) / 2,
        left: (left + right - innerWidth) / 2, behavior: 'instant'});
    }""", [item["rect"] for item in prepared])
    page.evaluate(
        "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    )
    evidence = {
        side: locate_target(page, side, targets[side], scroll=False)
        for side in ("left", "right")
    }
    return evidence, page.screenshot(full_page=False)


def receipt_protected_roots(receipt_value, live_session):
    from cvw_app.serving_identity import digest_json

    snapshot = dict(receipt_value.get("startup_snapshot", {}))
    claimed = snapshot.pop("snapshot_sha256", None)
    live_digest = live_session.get("session", live_session).get(
        "startup_snapshot_sha256"
    )
    if not claimed or claimed != live_digest or digest_json(snapshot) != claimed:
        raise CaptureError("launch receipt snapshot differs from live session")
    roots = snapshot.get("protected_input_identities", {}).get("protected_roots")
    if (
        not isinstance(roots, list)
        or not roots
        or any(
            not isinstance(root, str) or not Path(root).is_absolute() for root in roots
        )
    ):
        raise CaptureError("launch receipt lacks absolute protected input roots")
    return roots


def fresh_directory(path, protected_roots=()):
    resolved = path.resolve()
    if any(
        resolved == Path(root).resolve() or Path(root).resolve() in resolved.parents
        for root in protected_roots
    ):
        raise CaptureError("evidence output is inside protected input storage")
    if path.exists() or path.is_symlink():
        raise CaptureError("evidence destination must be fresh")
    # Inputs are never evidence output destinations, even if a caller names a fresh child.
    for ancestor in (resolved, *resolved.parents):
        if (ancestor / "manifest.json").is_file() and (
            ancestor / "content.tei.xml"
        ).exists():
            raise CaptureError("evidence output cannot be inside a candidate package")
        if (ancestor / "package").is_dir() and (ancestor / "validation.json").is_file():
            raise CaptureError("evidence output cannot be inside a candidate session")
    resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def verify_bundle(path):
    if path.is_symlink() or path.is_junction():
        raise CaptureError("evidence root cannot be a link")
    record = json.loads((path / "capture.json").read_text(encoding="utf-8"))
    for name, expected in record["files"].items():
        if Path(name).name != name:
            raise CaptureError("invalid evidence member path")
        member = path / name
        if (
            member.is_symlink()
            or member.is_junction()
            or digest(member.read_bytes()) != expected
        ):
            raise CaptureError("evidence member digest differs")
    return record


def export_bundle(source, destination):
    record = verify_bundle(source)
    target = fresh_directory(destination, record.get("protected_roots", ()))
    for name in [*record["files"], "capture.json"]:
        payload = (source / name).read_bytes()
        (target / name).write_bytes(payload)
        if (target / name).read_bytes() != payload:
            raise CaptureError("evidence copy verification failed")
    verify_bundle(target)
    return target


def capture(*, receipt, route, destination, width=1440, height=1000, targets=None):
    if not (320 <= width <= 4096 and 240 <= height <= 4096):
        raise CaptureError("viewport dimensions are outside supported bounds")
    receipt_value = json.loads(receipt.read_text(encoding="utf-8"))
    expected = session_identity(receipt_value)
    query = validate_route(route, expected)
    targets = validate_targets(targets)
    before_session = verify_session(expected["origin"], expected)
    protected = receipt_protected_roots(receipt_value, before_session)
    target = fresh_directory(destination, protected)
    from playwright.sync_api import sync_playwright

    responses = []
    errors = []
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(
            viewport={"width": width, "height": height}, device_scale_factor=1
        )
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "response",
            lambda response: (
                responses.append(response)
                if "/compare?" in response.url and response.status == 200
                else None
            ),
        )
        page.goto(route, wait_until="domcontentloaded")
        main = page.locator('main[data-review-state="ready"][data-review-generation]')
        main.wait_for(timeout=120000)
        for side in ("left", "right"):
            pane = page.locator('[data-review-side="' + side + '"]')
            from playwright.sync_api import expect

            for field, attribute in (
                ("Stage", "data-review-stage"),
                ("Artifact", "data-artifact-id"),
                ("Version", "data-artifact-version"),
                ("Location", "data-location"),
            ):
                expect(pane).to_have_attribute(
                    attribute, query[side + field][0], timeout=120000
                )
            expect(pane).to_have_attribute("data-recorded-context", "exact")
        page.wait_for_function(
            "Array.from(document.querySelectorAll('[data-image-state]')).every(n => n.dataset.imageState === 'ready')",
            timeout=120000,
        )
        target_evidence = None
        page.evaluate(
            "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
        )
        state = {
            "url": page.url,
            "route": main.get_attribute("data-review-route"),
            "generation": main.get_attribute("data-review-generation"),
            "route_digest": main.get_attribute("data-compare-route-digest"),
        }
        if not responses:
            raise CaptureError("no actual Compare response observed")
        response = responses[-1]
        response_bytes = response.body()
        view = json.loads(response_bytes)
        if (
            not view.get("route_digest")
            or view["route_digest"] != state["route_digest"]
        ):
            raise CaptureError("observed response does not bind the displayed route")
        response_url = response.url
        request_id = response.headers.get("x-cvw-request-id")
        for side in ("left", "right"):
            pane = view[side]
            element = page.locator('[data-review-side="' + side + '"]')
            if (
                pane["stage"]["id"] != query[side + "Stage"][0]
                or element.get_attribute("data-artifact-sha256")
                != pane["artifact"]["sha256"]
            ):
                raise CaptureError("displayed artifact identity differs from response")
            paging = pane.get("paging") or {}
            if paging.get("mode") == "segments":
                segments = paging["segments"]
                if element.get_attribute("data-segment-start") != str(
                    segments[0]["index"]
                ) or element.get_attribute("data-segment-limit") != str(len(segments)):
                    raise CaptureError("displayed segments differ from response")
            if (
                pane["artifact"]["id"] != query[side + "Artifact"][0]
                or pane["artifact"]["version"] != query[side + "Version"][0]
                or pane["location"]["value"] != query[side + "Location"][0]
            ):
                raise CaptureError("observed response does not bind the displayed pair")
        if targets is not None:
            target_evidence, png = capture_target_frame(page, targets)
        else:
            png = page.screenshot(full_page=False)
        after = {
            "url": page.url,
            "route": main.get_attribute("data-review-route"),
            "generation": main.get_attribute("data-review-generation"),
            "route_digest": main.get_attribute("data-compare-route-digest"),
        }
        if state != after:
            raise CaptureError("review navigated during capture")
        warnings = page.locator(
            '.notice, .drift-notice, [role="alert"]'
        ).all_text_contents()
        browser.close()
    verify_session(expected["origin"], expected)
    with Image.open(io.BytesIO(png)) as image:
        image.load()
        dimensions = list(image.size)
        if image.format != "PNG" or dimensions != [width, height]:
            raise CaptureError("captured image dimensions differ")
    payloads = {
        "frame.png": png,
        "compare.json": response_bytes,
        "session.json": canonical(before_session),
    }
    for name, payload in payloads.items():
        (target / name).write_bytes(payload)
    record = {
        "contract": "ocd-cvw-capture-bundle-v1",
        "protected_roots": protected,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "session": expected,
        "browser_state": state,
        "response_url": response_url,
        "request_id": request_id,
        "viewport": {"width": width, "height": height, "device_scale_factor": 1},
        "image_dimensions": dimensions,
        "warnings": warnings,
        "page_errors": errors,
        "files": {name: digest(payload) for name, payload in payloads.items()},
        "visual_inspection": "unknown",
        "inspected_loci": [],
        "acceptance": "not-established",
        "method": "playwright-labeled-frame",
        "targets": target_evidence,
    }
    (target / "capture.json").write_bytes(canonical(record))
    verify_bundle(target)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture_parser = commands.add_parser("capture")
    capture_parser.add_argument("--receipt", type=Path, required=True)
    capture_parser.add_argument("--url", required=True)
    capture_parser.add_argument("--output", type=Path, required=True)
    capture_parser.add_argument("--width", type=int, default=1440)
    capture_parser.add_argument("--height", type=int, default=1000)
    capture_parser.add_argument("--left-target", help="JSON object: scope_selector, scope_prefix, literal, occurrence")
    capture_parser.add_argument("--right-target", help="JSON object: scope_selector, scope_prefix, literal, occurrence")
    export_parser = commands.add_parser("export")
    export_parser.add_argument("--source", type=Path, required=True)
    export_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "capture":
        if bool(args.left_target) != bool(args.right_target):
            raise CaptureError("--left-target and --right-target must be supplied together")
        targets = None
        if args.left_target:
            try:
                targets = {"left": json.loads(args.left_target), "right": json.loads(args.right_target)}
            except json.JSONDecodeError as error:
                raise CaptureError("target arguments must be valid JSON") from error
        result = capture(
            receipt=args.receipt,
            route=args.url,
            destination=args.output,
            width=args.width,
            height=args.height,
            targets=targets,
        )
    else:
        result = {"exported_to": str(export_bundle(args.source, args.output))}
    # JSON escapes preserve Unicode values on legacy Windows stdout encodings.
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
