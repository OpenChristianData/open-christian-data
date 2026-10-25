from __future__ import annotations

import http.client
import json
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

from cvw_app.review_service import ReviewHTTPServer


def _start_server(
    tmp_path: Path,
    *,
    application: object | None = None,
) -> tuple[ReviewHTTPServer, Thread, list[tuple[str, dict[str, object]]]]:
    static_root = tmp_path / "dist"
    static_root.mkdir()
    events: list[tuple[str, dict[str, object]]] = []

    def sink(event: str, **fields: object) -> None:
        events.append((event, fields))

    descriptor = {
        "contract": "ocd-corpus-review-session-v1",
        "session": {
            "session_id": "service-session",
            "host": "127.0.0.1",
            "requested_port": 0,
            "port": 43111,
            "origin": "http://127.0.0.1:43111",
            "pid": 123,
            "state": "ready",
            "catalog_sha256": "a" * 64,
            "candidate_sha256": ["b" * 64],
            "implementation_sha256": "c" * 64,
        },
    }
    server = ReviewHTTPServer(
        ("127.0.0.1", 0),
        application or SimpleNamespace(),
        static_root,
        session_descriptor=descriptor,
        event_sink=sink,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, events


def _stop_server(server: ReviewHTTPServer, thread: Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_ephemeral_servers_receive_distinct_loopback_ports(tmp_path: Path) -> None:
    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()
    first, first_thread, _ = _start_server(tmp_path / "first")
    second, second_thread, _ = _start_server(tmp_path / "second")
    try:
        assert first.server_address[1] != second.server_address[1]
    finally:
        _stop_server(second, second_thread)
        _stop_server(first, first_thread)


def test_fixed_port_collision_fails_loudly(tmp_path: Path) -> None:
    first, thread, _ = _start_server(tmp_path)
    try:
        with pytest.raises(OSError):
            ReviewHTTPServer(
                ("127.0.0.1", first.server_address[1]),
                SimpleNamespace(),
                tmp_path / "dist",
            )
    finally:
        _stop_server(first, thread)


def test_session_endpoint_returns_runtime_descriptor_and_request_id(tmp_path: Path) -> None:
    server, thread, events = _start_server(tmp_path)
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", "/api/review/v1/session")
        response = connection.getresponse()
        body = json.loads(response.read())
        request_id = response.getheader("X-CVW-Request-ID")
        connection.close()
    finally:
        _stop_server(server, thread)

    assert response.status == 200
    assert request_id
    assert body["contract"] == "ocd-corpus-review-session-v1"
    assert body["session"]["session_id"] == "service-session"
    request_events = [fields for event, fields in events if event == "request"]
    assert len(request_events) == 1
    assert request_events[0]["request_id"] == request_id
    assert request_events[0]["path"] == "/api/review/v1/session"


def test_error_response_is_structured_and_logged_with_request_id(tmp_path: Path) -> None:
    server, thread, events = _start_server(tmp_path)
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", "/missing")
        response = connection.getresponse()
        body = json.loads(response.read())
        request_id = response.getheader("X-CVW-Request-ID")
        connection.close()
    finally:
        _stop_server(server, thread)

    assert response.status == 404
    assert request_id
    assert body["error"] == {
        "code": "route-not-found",
        "message": "The requested route does not exist.",
        "request_id": request_id,
    }
    request_events = [fields for event, fields in events if event == "request"]
    assert request_events[0]["request_id"] == request_id
    assert request_events[0]["error_code"] == "route-not-found"


def test_locations_endpoint_binds_identity_and_forwards_bounded_query(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def locations(*args: object, **kwargs: object) -> dict[str, object]:
        calls.append({"args": args, **kwargs})
        return {
            "contract": "ocd-corpus-review-locations-v1",
            "work": {"slug": "demo", "title": "Demo", "creator": "Author"},
            "stage": {"id": "tei", "label": "Faithful TEI candidate"},
            "availability": "available",
            "message": "ok",
            "artifact": {"id": "artifact", "version": "version", "sha256": "a" * 64},
            "search": kwargs["search"],
            "offset": kwargs["offset"],
            "limit": kwargs["limit"],
            "total": 3,
            "matched": 1,
            "returned": 1,
            "next_offset": None,
            "complete": True,
            "locations": [{"location": "part-one", "label": "Part One", "level": 1}],
        }

    server, thread, _ = _start_server(tmp_path, application=SimpleNamespace(locations=locations))
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request(
            "GET",
            "/api/review/v1/works/demo/stages/tei/locations"
            "?expected_artifact=artifact&expected_version=version&offset=2&limit=4&search=Part%20One",
        )
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
    finally:
        _stop_server(server, thread)

    assert response.status == 200
    assert body["contract"] == "ocd-corpus-review-locations-v1"
    assert calls == [{
        "args": ("demo", "tei"),
        "expected_artifact": "artifact",
        "expected_version": "version",
        "offset": 2,
        "limit": 4,
        "search": "Part One",
    }]


@pytest.mark.parametrize(
    ("query", "error_code"),
    [
        (
            "expected_artifact=a&expected_artifact=b&expected_version=v",
            "artifact-invalid",
        ),
        ("expected_artifact=a&expected_version=v&unknown=x", "artifact-invalid"),
        ("expected_artifact=a&expected_version=v&limit=0", "range-invalid"),
        ("expected_artifact=a&expected_version=v&limit=33", "range-invalid"),
        ("expected_artifact=a&expected_version=v&offset=-1", "range-invalid"),
    ],
)
def test_locations_endpoint_rejects_ambiguous_or_invalid_queries(
    tmp_path: Path, query: str, error_code: str
) -> None:
    server, thread, _ = _start_server(
        tmp_path,
        application=SimpleNamespace(locations=lambda **_: {}),
    )
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request(
            "GET",
            f"/api/review/v1/works/demo/stages/source/locations?{query}",
        )
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
    finally:
        _stop_server(server, thread)

    assert response.status == 422
    assert body["error"]["code"] == error_code


def test_summary_catalog_view_stays_bounded_for_large_root_and_work_inputs(
    tmp_path: Path,
) -> None:
    roots = [
        {"id": f"source-root-{index}", "access": "read-only", "purpose": "retained source"}
        for index in range(58_675)
    ]
    works = [
        {
            "slug": f"work-{index}",
            "title": f"Work {index}",
            "creator": "Creator",
            "scope": "work",
            "candidate_validation": None,
            "default_compare": None,
            "stages": [],
            "correspondence_sources": [],
        }
        for index in range(402)
    ]
    summary = {
        "contract": "ocd-corpus-review-catalog-v1",
        "manifest_contract": "ocd-corpus-review-manifest-v1",
        "catalog_version": "a" * 64,
        "approved_roots": [],
        "approved_roots_count": len(roots),
        "approved_roots_discovery": {"total": len(roots), "route": "/api/review/v1/roots"},
        "works": works[:50],
        "page": {
            "offset": 0,
            "returned": 50,
            "total": len(works),
            "next_offset": 50,
            "catalog_version": "a" * 64,
        },
    }
    application = SimpleNamespace(
        catalog=lambda: {
            "contract": "ocd-corpus-review-catalog-v1",
            "manifest_contract": "ocd-corpus-review-manifest-v1",
            "approved_roots": roots,
            "works": works,
        },
        catalog_summary_page=lambda offset, limit, catalog_version=None: summary,
    )
    server, thread, _ = _start_server(tmp_path, application=application)
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        connection.request("GET", "/api/review/v1/works?view=summary&offset=0&limit=50")
        response = connection.getresponse()
        payload = response.read()
        body = json.loads(payload)
        connection.close()
    finally:
        _stop_server(server, thread)

    assert response.status == 200
    assert len(payload) <= 512_000
    assert body["approved_roots"] == []
    assert body["approved_roots_count"] == 58_675
    assert body["page"] == {
        "offset": 0,
        "returned": 50,
        "total": 402,
        "next_offset": 50,
        "catalog_version": "a" * 64,
    }


def test_work_detail_and_artifact_discovery_routes_forward_exact_late_selection(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, object]] = []
    detail = {
        "contract": "ocd-corpus-review-work-v1",
        "catalog_version": "b" * 64,
        "work": {"slug": "large-work", "stages": [], "correspondence_sources": []},
    }
    artifacts = {
        "contract": "ocd-corpus-review-artifacts-v1",
        "catalog_version": "b" * 64,
        "artifacts": [{"id": "late-source", "version": "source-version"}],
        "page": {"offset": 0, "returned": 1, "total": 58_675, "next_offset": 1},
        "matched": 1,
        "total": 58_675,
    }

    def work_detail(slug: str, **kwargs: object) -> dict[str, object]:
        calls.append(("detail", (slug, kwargs)))
        return detail

    def artifact_page(slug: str, stage: str, **kwargs: object) -> dict[str, object]:
        calls.append(("artifacts", (slug, stage, kwargs)))
        return artifacts

    server, thread, _ = _start_server(
        tmp_path,
        application=SimpleNamespace(work_detail=work_detail, artifact_page=artifact_page),
    )
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request(
            "GET",
            "/api/review/v1/works/large-work"
            "?source_artifact=late-source&source_version=source-version",
        )
        detail_response = connection.getresponse()
        detail_body = json.loads(detail_response.read())
        connection.request(
            "GET",
            "/api/review/v1/works/large-work/stages/source/artifacts"
            "?offset=0&limit=50&search=late&catalog_version=" + "b" * 64,
        )
        artifacts_response = connection.getresponse()
        artifacts_body = json.loads(artifacts_response.read())
        connection.close()
    finally:
        _stop_server(server, thread)

    assert detail_response.status == 200
    assert detail_body == detail
    assert artifacts_response.status == 200
    assert artifacts_body == artifacts
    assert calls == [
        ("detail", ("large-work", {"source_artifact": "late-source", "source_version": "source-version", "tei_artifact": None, "tei_version": None, "catalog_version": None})),
        ("artifacts", ("large-work", "source", {"offset": 0, "limit": 50, "search": "late", "catalog_version": "b" * 64})),
    ]


def test_correspondence_discovery_route_is_reachable_and_strict(tmp_path: Path) -> None:
    calls = []

    def correspondence_page(slug: str, source: str, **kwargs: object) -> dict[str, object]:
        calls.append((slug, source, kwargs))
        return {"mappings": [{"left_location": "a", "right_location": "b"}]}

    server, thread, _ = _start_server(tmp_path, application=SimpleNamespace(correspondence_page=correspondence_page))
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        path = "/api/review/v1/works/work/correspondence?correspondence_source=map&offset=1&limit=2&catalog_version=" + "a" * 64
        connection.request("GET", path)
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["mappings"] == [{"left_location": "a", "right_location": "b"}]
        connection.request("GET", path + "&unexpected=true")
        rejected = connection.getresponse()
        assert rejected.status == 422
        rejected.read()
        connection.close()
    finally:
        _stop_server(server, thread)
    assert calls == [("work", "map", {"offset": 1, "limit": 2, "catalog_version": "a" * 64})]


def test_catalog_pagination_without_summary_is_rejected_without_full_build(tmp_path: Path) -> None:
    def catalog() -> dict[str, object]:
        pytest.fail("ambiguous query must not build the legacy catalog")
    server, thread, _ = _start_server(tmp_path, application=SimpleNamespace(catalog=catalog))
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        connection.request("GET", "/api/review/v1/works?offset=0&limit=50")
        response = connection.getresponse()
        assert response.status == 422
        assert "view=summary" in json.loads(response.read())["error"]["message"]
        connection.close()
    finally:
        _stop_server(server, thread)


def test_roots_route_pages_complete_root_claims(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def approved_roots_page(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {
            "contract": "ocd-corpus-review-roots-v1",
            "catalog_version": "c" * 64,
            "approved_roots": [{"id": "root-2", "access": "read-only", "purpose": "source"}],
            "page": {"offset": 1, "returned": 1, "total": 58_675, "next_offset": 2},
        }

    server, thread, _ = _start_server(
        tmp_path,
        application=SimpleNamespace(approved_roots_page=approved_roots_page),
    )
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request(
            "GET",
            "/api/review/v1/roots?offset=1&limit=50&catalog_version=" + "c" * 64,
        )
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
    finally:
        _stop_server(server, thread)

    assert response.status == 200
    assert body["page"]["total"] == 58_675
    assert calls == [{"offset": 1, "limit": 50, "work_slug": None, "catalog_version": "c" * 64}]
