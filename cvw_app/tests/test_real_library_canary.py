"""Opt-in canary for the current manifest-bound library routes.

The canary deliberately takes its WorkCatalog and candidate directories from the
operator. It never discovers, copies, generates, or persists candidate data.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from threading import Thread
import time
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

from cvw_app.launch_windows import preflight_candidate_session, resolve_launch_paths
from cvw_app.review_contract import (
    MAX_RESPONSE_SERIALIZED_BYTES,
    SAFE_NATIVE_MEDIA_TYPES,
    RecordedContext,
    ReviewApplication,
    _source_presentation,
)
from cvw_app.review_service import make_server


_NOT_APPLICABLE_UNLESS_PRESENT = {"TIFF", "packaged EPUB"}
_MANDATORY_FORMAT_CLASSES = {
    "HTML",
    "XHTML",
    "plain-text",
    "JSON",
    "TEI",
    "PDF",
    "image",
}
_FORMAT_CLASSES = tuple(
    sorted(_MANDATORY_FORMAT_CLASSES | _NOT_APPLICABLE_UNLESS_PRESENT)
)
_HTTP_CANARY_TIMEOUT_SECONDS = 120
_PREFERRED_LONG_WORK_SLUG = "fisher-marrow-of-modern-divinity"


def _format_class(media_type: str) -> str | None:
    if media_type in SAFE_NATIVE_MEDIA_TYPES:
        if media_type == "application/pdf":
            return "PDF"
        if media_type == "application/epub+zip":
            return "packaged EPUB"
        if media_type == "image/tiff":
            return "TIFF"
        return "image"
    if media_type == "text/html":
        return "HTML"
    if media_type == "application/xhtml+xml":
        return "XHTML"
    if media_type == "application/json":
        return "JSON"
    if media_type == "application/tei+xml":
        return "TEI"
    if media_type.startswith("image/"):
        return "image"
    if media_type in {"application/zip", "application/gzip"}:
        return None
    return "plain-text"


def _required_format_classes(
    catalog_path: Path,
    repository_root: Path,
) -> dict[str, list[str]]:
    """Derive live classes from route manifests, not ReviewApplication output."""

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    route_manifests: dict[tuple[str, str], None] = {}
    for work in catalog["works"]:
        for route in work["reconstruction_state"]["routes"]:
            route_manifests[(route["source_id"], route["manifest"])] = None

    required: dict[str, list[str]] = {}
    for source_id, relative_manifest in sorted(route_manifests):
        relative = Path(relative_manifest)
        if relative.is_absolute() or ".." in relative.parts:
            raise AssertionError(f"route manifest escapes the repository: {relative_manifest}")
        manifest_path = (repository_root / relative).resolve(strict=True)
        if not manifest_path.is_relative_to(repository_root):
            raise AssertionError(f"route manifest escapes the repository: {relative_manifest}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for authority in manifest["authorities"]:
            if authority.get("role") != "primary-source":
                continue
            authority_path = Path(authority["path"])
            media_type, _, _ = _source_presentation(authority_path)
            format_name = _format_class(media_type)
            if format_name is None:
                continue
            required.setdefault(format_name, []).append(
                f"{source_id}:{authority_path.as_posix()}"
            )

    # Every manifest-bound candidate exposes the faithful TEI stage. This is
    # the only expected class not represented by retained source authorities.
    if route_manifests:
        required.setdefault("TEI", []).append("candidate:package/content.tei.xml")
    return required


def _missing_required_format_classes(
    required: dict[str, list[str]],
    observed: dict[str, list[dict[str, object]]],
) -> list[str]:
    return sorted(name for name in required if not observed.get(name))


def test_required_format_derivation_reads_current_route_manifests_independently(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    manifest_path = repo / "sources" / "example.source-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "authorities": [
                    {"path": "raw/example/page.html", "role": "primary-source"},
                    {"path": "raw/example/page.xhtml", "role": "primary-source"},
                    {"path": "raw/example/records.json", "role": "primary-source"},
                    {"path": "raw/example/scan.pdf", "role": "primary-source"},
                    {"path": "raw/example/cover.jpg", "role": "primary-source"},
                    {"path": "raw/example/ocr.txt", "role": "primary-source"},
                    {"path": "raw/example/scan.tiff", "role": "primary-source"},
                    {"path": "raw/example/book.epub", "role": "primary-source"},
                ]
            }
        ),
        encoding="utf-8",
    )
    catalog_path = repo / "reports" / "publish" / "work_catalog.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(
        json.dumps(
            {
                "works": [
                    {
                        "reconstruction_state": {
                            "routes": [
                                {
                                    "source_id": "example",
                                    "manifest": "sources/example.source-manifest.json",
                                }
                            ]
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    required = _required_format_classes(catalog_path, repo.resolve())

    assert set(required) == _MANDATORY_FORMAT_CLASSES | _NOT_APPLICABLE_UNLESS_PRESENT
    assert required["HTML"] == ["example:raw/example/page.html"]
    assert required["XHTML"] == ["example:raw/example/page.xhtml"]
    assert required["TEI"] == ["candidate:package/content.tei.xml"]


def test_canary_reports_missing_candidate_format_coverage() -> None:
    required = {"HTML": ["route:page.html"], "PDF": ["route:scan.pdf"]}
    observed = {"HTML": [{"slug": "example"}]}

    assert _missing_required_format_classes(required, observed) == ["PDF"]


def test_canary_accepts_an_explicit_repository_root_for_isolated_worktrees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCD_CVW_CANARY_CATALOG", "catalog.json")
    monkeypatch.setenv(
        "OCD_CVW_CANARY_CANDIDATES",
        os.pathsep.join(("candidate-one", "candidate-two")),
    )
    monkeypatch.setenv("OCD_CVW_CANARY_REPOSITORY_ROOT", "canonical-root")

    catalog, candidates, repository_root = _canary_paths()

    assert catalog == Path("catalog.json")
    assert candidates == [Path("candidate-one"), Path("candidate-two")]
    assert repository_root == Path("canonical-root")


def test_required_canary_mode_fails_instead_of_skipping_without_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OCD_CVW_CANARY_CATALOG", raising=False)
    monkeypatch.delenv("OCD_CVW_CANARY_CANDIDATES", raising=False)
    monkeypatch.setenv("OCD_CVW_REQUIRE_REAL_CANARY", "1")

    with pytest.raises(pytest.fail.Exception, match="required real-library canary"):
        _canary_paths()


def test_required_canary_mode_fails_for_separator_only_candidate_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCD_CVW_CANARY_CATALOG", "catalog.json")
    monkeypatch.setenv("OCD_CVW_CANARY_CANDIDATES", os.pathsep)
    monkeypatch.setenv("OCD_CVW_REQUIRE_REAL_CANARY", "1")

    with pytest.raises(pytest.fail.Exception, match="did not contain a path"):
        _canary_paths()


def _canary_paths() -> tuple[Path, list[Path], Path | None]:
    catalog_text = os.environ.get("OCD_CVW_CANARY_CATALOG")
    candidate_text = os.environ.get("OCD_CVW_CANARY_CANDIDATES")
    repository_root_text = os.environ.get("OCD_CVW_CANARY_REPOSITORY_ROOT")
    if not catalog_text or not candidate_text:
        if os.environ.get("OCD_CVW_REQUIRE_REAL_CANARY") == "1":
            pytest.fail(
                "required real-library canary inputs are unavailable: set "
                "OCD_CVW_CANARY_CATALOG and OCD_CVW_CANARY_CANDIDATES"
            )
        pytest.skip(
            "set OCD_CVW_CANARY_CATALOG and OCD_CVW_CANARY_CANDIDATES "
            "(os.pathsep-separated) for the real-library canary"
        )
    candidates = [Path(value) for value in candidate_text.split(os.pathsep) if value]
    if not candidates:
        if os.environ.get("OCD_CVW_REQUIRE_REAL_CANARY") == "1":
            pytest.fail("required OCD_CVW_CANARY_CANDIDATES did not contain a path")
        pytest.skip("OCD_CVW_CANARY_CANDIDATES did not contain a path")
    repository_root = Path(repository_root_text) if repository_root_text else None
    return Path(catalog_text), candidates, repository_root


def _real_long_work(
    application: ReviewApplication,
    catalog: dict[str, object],
) -> tuple[dict[str, object], dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    works = catalog["works"]
    assert isinstance(works, list)
    preferred = os.environ.get("OCD_CVW_LONG_WORK_SLUG", _PREFERRED_LONG_WORK_SLUG)
    ordered = sorted(works, key=lambda work: work["slug"] != preferred)
    for work in ordered:
        stages = {stage["id"]: stage for stage in work["stages"]}
        if not all(stages.get(stage_id, {}).get("selected_artifact") for stage_id in ("source", "tei")):
            continue
        views: dict[str, dict[str, object]] = {}
        for stage_id in ("source", "tei"):
            selected_identity = stages[stage_id]["selected_artifact"]
            selected = next(
                artifact
                for artifact in stages[stage_id]["artifacts"]
                if artifact["id"] == selected_identity["id"]
                and artifact["version"] == selected_identity["version"]
            )
            views[stage_id] = application.stage_view(
                work["slug"],
                stage_id,
                recorded=RecordedContext(selected["id"], selected["version"], "start"),
            )
        if all(view.get("paging", {}).get("segment_count", 0) > 1 for view in views.values()):
            return work, stages, views
    pytest.fail("no supplied current candidate has both a multi-segment source and TEI stage")


def test_current_long_work_serves_every_bounded_source_and_tei_segment() -> None:
    catalog_path, candidate_dirs, repository_root = _canary_paths()
    paths = resolve_launch_paths(catalog_path, candidate_dirs, repository_root=repository_root)
    application = ReviewApplication.from_work_catalog(
        paths.catalog_path,
        paths.candidate_dirs,
        repository_root=paths.repository_root,
    )
    catalog = application.catalog()
    work, stages, initial_views = _real_long_work(application, catalog)
    server = make_server(
        paths.catalog_path,
        list(paths.candidate_dirs),
        static_root=paths.static_root,
        host="127.0.0.1",
        port=0,
        repository_root=paths.repository_root,
        application=application,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    timings: dict[str, float] = {}
    try:
        for stage_id in ("source", "tei"):
            selected_identity = stages[stage_id]["selected_artifact"]
            selected = next(
                artifact
                for artifact in stages[stage_id]["artifacts"]
                if artifact["id"] == selected_identity["id"]
                and artifact["version"] == selected_identity["version"]
            )
            paging = initial_views[stage_id]["paging"]
            count = paging["segment_count"]
            maximum = paging["max_segments_per_request"]
            started = time.monotonic()
            starts = list(range(0, count, maximum))
            for start in starts:
                limit = min(maximum, count - start)
                query = urlencode(
                    {
                        "expected_artifact": selected["id"],
                        "expected_version": selected["version"],
                        "location": "start",
                        "segment_start": start,
                        "segment_limit": limit,
                    }
                )
                url = f"{origin}/api/review/v1/works/{work['slug']}/stages/{stage_id}?{query}"
                with urlopen(url, timeout=_HTTP_CANARY_TIMEOUT_SECONDS) as response:
                    body = response.read()
                    assert response.status == 200
                assert len(body) <= MAX_RESPONSE_SERIALIZED_BYTES
                view = json.loads(body)
                assert view["artifact"]["id"] == selected["id"]
                assert view["artifact"]["version"] == selected["version"]
                assert view["artifact"]["sha256"] == selected["sha256"]
                assert view["paging"]["segment_count"] == count
                assert view["paging"]["bound"]["sha256"] == selected["sha256"]
                assert view["presentation"]["document"]["nodes"]
                expected_state = "in-range" if start == 0 else "location-outside-range"
                assert view["location_state"] == expected_state
            timings[stage_id] = round(time.monotonic() - started, 3)

        def compare_body(left_start: int, left_limit: int, right_start: int, right_limit: int) -> dict[str, object]:
            source_identity = stages["source"]["selected_artifact"]
            tei_identity = stages["tei"]["selected_artifact"]
            source = next(artifact for artifact in stages["source"]["artifacts"] if artifact["id"] == source_identity["id"] and artifact["version"] == source_identity["version"])
            tei = next(artifact for artifact in stages["tei"]["artifacts"] if artifact["id"] == tei_identity["id"] and artifact["version"] == tei_identity["version"])
            query = urlencode(
                {
                    "left_stage": "source",
                    "left_artifact": source["id"],
                    "left_version": source["version"],
                    "left_location": "start",
                    "right_stage": "tei",
                    "right_artifact": tei["id"],
                    "right_version": tei["version"],
                    "right_location": "start",
                    "linked": "false",
                    "correspondence": "absent",
                    "left_segment_start": left_start,
                    "left_segment_limit": left_limit,
                    "right_segment_start": right_start,
                    "right_segment_limit": right_limit,
                }
            )
            with urlopen(
                f"{origin}/api/review/v1/works/{work['slug']}/compare?{query}",
                timeout=_HTTP_CANARY_TIMEOUT_SECONDS,
            ) as response:
                body = response.read()
                assert response.status == 200
            assert len(body) <= MAX_RESPONSE_SERIALIZED_BYTES
            return json.loads(body)

        source_paging = initial_views["source"]["paging"]
        tei_paging = initial_views["tei"]["paging"]
        source_last = source_paging["segment_count"] - 1
        tei_last = tei_paging["segment_count"] - 1
        first_left_last_right = compare_body(0, 1, tei_last, 1)
        last_left_first_right = compare_body(source_last, 1, 0, 1)
        assert first_left_last_right["left"]["location_state"] == "in-range"
        assert first_left_last_right["right"]["location_state"] == "location-outside-range"
        assert last_left_first_right["left"]["location_state"] == "location-outside-range"
        assert last_left_first_right["right"]["location_state"] == "in-range"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    print(
        "CVW_REAL_LONG_WORK_CANARY="
        + json.dumps(
            {
                "slug": work["slug"],
                "source_segments": initial_views["source"]["paging"]["segment_count"],
                "tei_segments": initial_views["tei"]["paging"]["segment_count"],
                "render_navigation_seconds": timings,
            },
            sort_keys=True,
        )
    )


def test_current_manifest_bound_formats_are_reachable_and_digest_bound() -> None:
    catalog_path, candidate_dirs, repository_root = _canary_paths()
    paths = resolve_launch_paths(
        catalog_path,
        candidate_dirs,
        repository_root=repository_root,
    )
    required = _required_format_classes(paths.catalog_path, paths.repository_root)
    missing_from_routes = sorted(_MANDATORY_FORMAT_CLASSES - set(required))
    if missing_from_routes:
        pytest.fail(
            "only TIFF and packaged EPUB may be absent from current route manifests; "
            f"missing mandatory classes: {missing_from_routes}"
        )
    print(
        "CVW_REAL_LIBRARY_REQUIRED_CLASSES="
        + json.dumps({name: len(witnesses) for name, witnesses in sorted(required.items())})
    )
    application = ReviewApplication.from_work_catalog(
        paths.catalog_path,
        paths.candidate_dirs,
        repository_root=paths.repository_root,
    )

    observed: dict[str, list[dict[str, object]]] = {}
    catalog = application.catalog()
    catalog_bytes = len(json.dumps(catalog, ensure_ascii=False).encode("utf-8"))
    assert len(catalog["works"]) == 402
    assert catalog_bytes <= MAX_RESPONSE_SERIALIZED_BYTES
    print(
        "CVW_REAL_LIBRARY_CATALOG="
        + json.dumps(
            {
                "works": len(catalog["works"]),
                "serialized_bytes": catalog_bytes,
                "maximum_bytes": MAX_RESPONSE_SERIALIZED_BYTES,
            },
            sort_keys=True,
        )
    )
    for work in catalog["works"]:
        for stage in work["stages"]:
            for artifact in stage["artifacts"]:
                format_name = _format_class(artifact["media_type"])
                if format_name is None:
                    continue
                observed.setdefault(format_name, []).append(
                    {
                        "slug": work["slug"],
                        "stage": stage["id"],
                        "artifact": artifact,
                    }
                )

    covered: dict[str, list[str]] = {}
    server = make_server(
        paths.catalog_path,
        list(paths.candidate_dirs),
        static_root=paths.static_root,
        host="127.0.0.1",
        port=0,
        repository_root=paths.repository_root,
        application=application,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(origin + "/api/review/v1/works", timeout=10) as response:
            served_catalog_body = response.read()
            assert response.status == 200
            assert len(served_catalog_body) <= MAX_RESPONSE_SERIALIZED_BYTES
        assert json.loads(served_catalog_body) == catalog

        for format_name in sorted(required):
            errors: list[str] = []
            for item in observed.get(format_name, []):
                artifact = item["artifact"]
                assert isinstance(artifact, dict)
                recorded = RecordedContext(artifact["id"], artifact["version"], "start")
                view = application.stage_view(
                    item["slug"], item["stage"], recorded=recorded
                )
                if view["recorded_context"]["state"] != "exact":
                    errors.append(f"{item['slug']} recorded context is not exact")
                    continue
                if view["artifact"]["sha256"] != artifact["sha256"]:
                    errors.append(f"{item['slug']} digest changed during Read")
                    continue
                if view["availability"] != "available":
                    errors.append(f"{item['slug']} is {view['availability']}: {view['message']}")
                    continue
                identity_query = urlencode(
                    {
                        "expected_artifact": artifact["id"],
                        "expected_version": artifact["version"],
                    }
                )
                stage_query = identity_query + "&" + urlencode({"location": "start"})
                stage_url = (
                    f"{origin}/api/review/v1/works/{item['slug']}/stages/"
                    f"{item['stage']}?{stage_query}"
                )
                print(
                    "CVW_REAL_LIBRARY_HTTP_WITNESS_START="
                    + json.dumps(
                        {
                            "format": format_name,
                            "slug": item["slug"],
                            "stage": item["stage"],
                        },
                        sort_keys=True,
                    )
                )
                started = time.monotonic()
                with urlopen(
                    stage_url, timeout=_HTTP_CANARY_TIMEOUT_SECONDS
                ) as response:
                    served_payload = response.read()
                    assert response.status == 200
                assert len(served_payload) <= 512_000
                served_view = json.loads(served_payload)
                elapsed = time.monotonic() - started
                print(
                    "CVW_REAL_LIBRARY_HTTP_WITNESS="
                    + json.dumps(
                        {
                            "elapsed_seconds": round(elapsed, 3),
                            "format": format_name,
                            "slug": item["slug"],
                            "stage": item["stage"],
                        },
                        sort_keys=True,
                    )
                )
                assert served_view["artifact"]["sha256"] == artifact["sha256"]
                assert served_view["recorded_context"]["state"] == "exact"
                nodes = served_view["presentation"]["document"]["nodes"]
                paging = served_view.get("paging") or {}
                if not nodes and paging.get("segment_count", 0) > 1:
                    page_query = stage_query + "&" + urlencode(
                        {
                            "segment_start": 0,
                            "segment_limit": min(
                                paging["max_segments_per_request"],
                                paging["segment_count"],
                            ),
                        }
                    )
                    with urlopen(
                        stage_url.partition("?")[0] + "?" + page_query,
                        timeout=_HTTP_CANARY_TIMEOUT_SECONDS,
                    ) as response:
                        page_payload = response.read()
                        assert response.status == 200
                    assert len(page_payload) <= 512_000
                    served_view = json.loads(page_payload)
                    assert served_view["artifact"]["sha256"] == artifact["sha256"]
                    assert served_view["recorded_context"]["state"] == "exact"
                    nodes = served_view["presentation"]["document"]["nodes"]
                assert nodes, f"{format_name} witness has no rendered document nodes"
                assert all(
                    not segment.get("truncated")
                    for segment in served_view.get("paging", {}).get("segments", [])
                ), f"{format_name} witness contains a truncated, unreviewable segment"
                if format_name in {"HTML", "XHTML"}:
                    assert any(
                        node["type"]
                        in {"paragraph", "list-item", "blockquote", "preformatted", "table"}
                        for node in nodes
                    ), f"{format_name} witness rendered structure headings but no readable body"
                if artifact["media_type"] in SAFE_NATIVE_MEDIA_TYPES:
                    payload, media_type = application.stage_bytes(
                        item["slug"], item["stage"], artifact["id"], artifact["version"]
                    )
                    with urlopen(
                        stage_url.partition("?")[0] + "/bytes?" + identity_query,
                        timeout=_HTTP_CANARY_TIMEOUT_SECONDS,
                    ) as response:
                        served_payload = response.read()
                        assert response.status == 200
                        assert response.headers.get_content_type() == media_type
                    assert served_payload == payload
                    assert hashlib.sha256(payload).hexdigest() == artifact["sha256"]
                else:
                    exact = application.exact(
                        item["slug"], item["stage"], artifact["id"], artifact["version"]
                    )
                    with urlopen(
                        stage_url.partition("?")[0] + "/exact?" + identity_query,
                        timeout=_HTTP_CANARY_TIMEOUT_SECONDS,
                    ) as response:
                        assert response.status == 200
                        assert response.read() == exact.encode("utf-8")
                covered.setdefault(format_name, []).append(
                    f"{item['slug']}:{item['stage']}:{artifact['path']}"
                )
                break
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    missing = _missing_required_format_classes(required, observed)
    if missing:
        pytest.fail(
            "supplied current candidates do not cover required format classes: "
            f"{missing}; required={sorted(required)} observed={sorted(observed)}"
        )
    for format_name in sorted(required):
        if format_name not in covered:
            pytest.fail(f"required format class {format_name} has no readable HTTP witness")

    for work in catalog["works"]:
        stages = {stage["id"]: stage for stage in work["stages"]}
        source, tei = stages["source"], stages["tei"]
        if source["selected_artifact"] and tei["selected_artifact"]:
            compare = application.compare_view(
                work["slug"],
                left_stage="source",
                left_recorded=RecordedContext(
                    source["selected_artifact"]["id"],
                    source["selected_artifact"]["version"],
                    "start",
                ),
                right_stage="tei",
                right_recorded=RecordedContext(
                    tei["selected_artifact"]["id"],
                    tei["selected_artifact"]["version"],
                    "start",
                ),
                linked=False,
                correspondence_source=None,
            )
            assert compare["linked_navigation"] is False
            assert compare["correspondence"]["state"] == "absent"

    matrix = {}
    for name in _FORMAT_CLASSES:
        if name in covered:
            matrix[name] = {"status": "covered", "routes": covered[name]}
        else:
            status = "not applicable: no current manifest-bound route"
            if name in _NOT_APPLICABLE_UNLESS_PRESENT:
                status = "not applicable: TIFF/packaged EPUB not present in current routes"
            matrix[name] = {"status": status, "routes": []}
    print("CVW_REAL_LIBRARY_CANARY_MATRIX=" + json.dumps(matrix, sort_keys=True))


def test_current_manifest_bound_browser_workflow_is_reachable() -> None:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import expect, sync_playwright
    except ImportError as error:
        if os.environ.get("OCD_CVW_REQUIRE_REAL_CANARY") == "1":
            pytest.fail(f"required Python Playwright is unavailable: {error}")
        pytest.skip(f"Python Playwright is unavailable: {error}")

    catalog_path, candidate_dirs, repository_root = _canary_paths()
    paths = resolve_launch_paths(
        catalog_path,
        candidate_dirs,
        repository_root=repository_root,
    )
    preflight_started = time.monotonic()
    application, preflight = preflight_candidate_session(paths)
    preflight_seconds = time.monotonic() - preflight_started
    assert len(preflight) == len(paths.candidate_dirs)
    assert all(item.validation_status == "pass" and item.work_ids for item in preflight)
    server = make_server(
        paths.catalog_path,
        list(paths.candidate_dirs),
        static_root=paths.static_root,
        host="127.0.0.1",
        port=0,
        repository_root=paths.repository_root,
        application=application,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except PlaywrightError as error:
                if os.environ.get("OCD_CVW_REQUIRE_REAL_CANARY") == "1":
                    pytest.fail(f"required Chromium browser is unavailable: {error}")
                pytest.skip(f"Chromium is unavailable for the browser canary: {error}")
            context = None
            try:
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1000},
                    permissions=["clipboard-read", "clipboard-write"],
                )
                page = context.new_page()
                browser_errors: list[str] = []
                page.on("pageerror", lambda error: browser_errors.append(str(error)))
                page.on(
                    "request",
                    lambda request: browser_errors.append(
                        f"unexpected browser write request: {request.method} {request.url}"
                    )
                    if request.method != "GET"
                    else None,
                )
                page.on(
                    "console",
                    lambda message: browser_errors.append(message.text)
                    if message.type == "error"
                    else None,
                )
                library_started = time.monotonic()
                page.goto(origin + "/review", wait_until="networkidle")
                library_seconds = time.monotonic() - library_started
                expect(page).to_have_title("Corpus Review Viewer")
                expect(page.get_by_role("heading", name="Choose a text")).to_be_visible()
                expect(page.get_by_text("Showing 402 of 402 texts")).to_be_visible()
                state_filter = page.get_by_label("Candidate session state")
                expect(state_filter.locator("option")).to_have_count(6)
                search = page.get_by_label("Search texts")
                search.focus()
                page.keyboard.type("John Milton Paradise")
                expect(page.get_by_text("Showing 1 of 402 texts")).to_be_visible()
                expect(page.get_by_text("Paradise Lost", exact=True)).to_be_visible()
                page.get_by_label("Search texts").fill("")
                state_filter.select_option("no-candidate")
                expect(page.locator("section.work-panel")).to_contain_text("No candidate supplied")
                filtered_count = page.locator("section.work-panel .panel-tools p").inner_text()
                assert filtered_count.startswith("Showing ") and filtered_count.endswith(" of 402 texts")
                assert filtered_count != "Showing 0 of 402 texts"
                state_filter.select_option("all")
                expect(page.get_by_text("Showing 402 of 402 texts")).to_be_visible()

                open_paradise = page.get_by_role(
                    "button", name="Open Paradise Lost", exact=True
                )
                expect(open_paradise).to_be_enabled()
                open_paradise.focus()
                page.keyboard.press("Enter")
                expect(
                    page.locator("section.reader-title").get_by_role(
                        "heading", name="Paradise Lost"
                    )
                ).to_be_visible()

                source_select = page.get_by_label("Retained source authority")
                expect(source_select).to_have_value("")
                expect(page.get_by_text("No retained source has been selected.")).to_be_visible()
                options = source_select.locator("option")
                assert options.count() >= 2
                selected_id = options.nth(1).get_attribute("value")
                assert selected_id
                source_select.focus()
                page.keyboard.press("ArrowDown")
                page.keyboard.press("Enter")
                expect(source_select).to_have_value(selected_id)
                expect(page.locator("article.artifact-panel")).to_be_visible()
                expect(
                    page.get_by_role(
                        "status", name="Candidate validation identity"
                    )
                ).to_contain_text("Validation passed")
                expect(
                    page.get_by_role(
                        "status", name="Candidate validation identity"
                    ).locator("code")
                ).to_have_count(3)

                compare_button = page.get_by_role(
                    "button", name="Compare source and TEI", exact=True
                )
                expect(compare_button).to_be_enabled()
                compare_button.focus()
                page.keyboard.press("Enter")
                expect(
                    page.get_by_role("heading", name="Compare source and TEI")
                ).to_be_visible()
                expect(page.get_by_label("Left retained source", exact=True)).to_have_value(selected_id)
                correspondence = page.get_by_role(
                    "status", name="Correspondence status"
                )
                expect(correspondence).to_contain_text("Correspondence: absent")
                expect(correspondence).to_contain_text("unlinked")

                page.set_viewport_size({"width": 900, "height": 800})
                left_pane = page.get_by_role("region", name="Left pane: Retained source")
                right_pane = page.get_by_role(
                    "region", name="Right pane: Faithful TEI candidate"
                )
                expect(left_pane).to_be_visible()
                expect(right_pane).to_be_visible()
                left_box = left_pane.bounding_box()
                right_box = right_pane.bounding_box()
                assert left_box is not None and right_box is not None
                assert right_box["y"] > left_box["y"]
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                )
                expect(
                    page.get_by_role("button", name="Copy exact reviewed identity")
                ).to_be_visible()
                page.set_viewport_size({"width": 1440, "height": 1000})

                page.goto(origin + "/review", wait_until="networkidle")
                long_search = page.get_by_label("Search texts")
                long_search.focus()
                page.keyboard.type("The Marrow of Modern Divinity")
                long_row = page.locator("tbody tr").filter(has_text="The Marrow of Modern Divinity")
                expect(long_row).to_have_count(1)
                long_open = long_row.get_by_role("button", name="Open The Marrow of Modern Divinity")
                long_open.focus()
                page.keyboard.press("Enter")
                expect(
                    page.locator("section.reader-title").get_by_role(
                        "heading", name="The Marrow of Modern Divinity"
                    )
                ).to_be_visible()

                def page_to_last(label: str) -> tuple[str, float]:
                    navigation = page.get_by_role("navigation", name=label)
                    expect(navigation).to_be_visible()
                    status = navigation.locator("span[aria-live='polite']")
                    next_button = navigation.get_by_role("button", name="Next segments")
                    started = time.monotonic()
                    steps = 0
                    while not next_button.is_disabled():
                        previous = status.inner_text()
                        next_button.focus()
                        page.keyboard.press("Enter")
                        expect(status).not_to_have_text(previous)
                        steps += 1
                        if steps == 1:
                            warning_name = label.replace(
                                " segment navigation", " recorded location warning"
                            )
                            expect(
                                page.get_by_role("status", name=warning_name)
                            ).to_contain_text("no replacement was inferred")
                        assert steps < 100
                    return status.inner_text(), time.monotonic() - started

                read_last, read_seconds = page_to_last("Read segment navigation")
                assert read_last == "Segments 22–22 of 22"
                long_compare = page.get_by_role("button", name="Compare source and TEI", exact=True)
                long_compare.focus()
                page.keyboard.press("Enter")
                expect(page.get_by_role("heading", name="Compare source and TEI")).to_be_visible()
                left_last, left_seconds = page_to_last("Left pane segment navigation")
                assert left_last == "Segments 22–22 of 22"
                right_first = page.get_by_role("navigation", name="Right pane segment navigation").locator("span[aria-live='polite']")
                expect(right_first).to_have_text("Segments 1–1 of 22")
                right_last, right_seconds = page_to_last("Right pane segment navigation")
                assert right_last == "Segments 22–22 of 22"
                expect(
                    page.get_by_role("navigation", name="Left pane segment navigation").locator("span[aria-live='polite']")
                ).to_have_text("Segments 22–22 of 22")
                copy_identity = page.get_by_role("button", name="Copy exact reviewed identity")
                expect(copy_identity).to_be_enabled()
                copy_identity.focus()
                page.keyboard.press("Enter")
                expect(page.get_by_text("Exact reviewed identity copied. No acceptance decision was created or stored.")).to_be_visible()
                copied = json.loads(page.evaluate("navigator.clipboard.readText()"))
                assert copied["contract"] == "ocd-cvw-reviewed-identity-v1"
                assert copied["work_id"] == _PREFERRED_LONG_WORK_SLUG
                assert len(copied["source"]["sha256"]) == 64
                assert len(copied["candidate"]["artifact_sha256"]) == 64
                assert len(copied["candidate"]["package_sha256"]) == 64
                assert len(copied["validation"]["report_sha256"]) == 64
                assert len(copied["validation"]["source_manifest_sha256"]) == 64
                assert not browser_errors, browser_errors
                print("CVW_REAL_LIBRARY_BROWSER_CANARY=passed")
                print(
                    "CVW_REAL_FULL_CATALOG_CANARY="
                    + json.dumps(
                        {
                            "candidate_directories": len(preflight),
                            "catalog_works": 402,
                            "library_load_seconds": round(library_seconds, 3),
                            "preflight_seconds": round(preflight_seconds, 3),
                            "resolved_work_bindings": sum(len(item.work_ids) for item in preflight),
                        },
                        sort_keys=True,
                    )
                )
                print(
                    "CVW_REAL_LONG_WORK_BROWSER_CANARY="
                    + json.dumps(
                        {
                            "slug": _PREFERRED_LONG_WORK_SLUG,
                            "read_first_to_last_seconds": round(read_seconds, 3),
                            "compare_left_first_to_last_seconds": round(left_seconds, 3),
                            "compare_right_first_to_last_seconds": round(right_seconds, 3),
                        },
                        sort_keys=True,
                    )
                )
            finally:
                if context is not None:
                    context.close()
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
