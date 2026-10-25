"""Loopback HTTP/static/CLI adapter for the Corpus Review Viewer."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import time
import uuid
from urllib.parse import parse_qs, unquote, urlparse

from cvw_app.review_contract import (
    MAX_ARTIFACT_PAGE_SIZE,
    MAX_CATALOG_PAGE_SIZE,
    MAX_LOCATION_PAGE_SIZE,
    MAX_LOCATION_SEARCH_SCALARS,
    MAX_RESPONSE_SERIALIZED_BYTES,
    FormatNotAllowListedError,
    RangeInvalidError,
    RecordedContext,
    ReviewApplication,
    ReviewContractError,
    ResponseTooLargeError,
    RouteStaleError,
    SHA256,
    governed_identity_text,
    governed_location_text,
    is_route_valid_scalar_text,
    reject_unicode_surrogates,
)
from cvw_app.session_observability import (
    DiagnosticHealth,
    make_session_descriptor,
    new_session_id,
)
from cvw_app.serving_identity import ServingIdentity, ServingIdentityError
from cvw_app.native_images import NativeImageError, parse_region


SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'none'; connect-src 'self'; font-src 'self'; "
        "form-action 'none'; frame-ancestors 'none'; frame-src 'none'; img-src 'self' data: blob:; "
        "media-src 'none'; object-src 'none'; script-src 'self'; style-src 'self'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
_STAGE_ROUTE = re.compile(r"^/api/review/v1/works/([^/]+)/stages/(source|tei|json)(/exact|/bytes|/image|/pdf-page)?$")
_ARTIFACTS_ROUTE = re.compile(r"^/api/review/v1/works/([^/]+)/stages/(source|tei)/artifacts$")
_LOCATIONS_ROUTE = re.compile(r"^/api/review/v1/works/([^/]+)/stages/(source|tei)/locations$")
_COMPARE_ROUTE = re.compile(r"^/api/review/v1/works/([^/]+)/compare$")
_WORK_ROUTE = re.compile(r"^/api/review/v1/works/([^/]+)$")
_CORRESPONDENCE_ROUTE = re.compile(r"^/api/review/v1/works/([^/]+)/correspondence$")
_ROOTS_ROUTE = "/api/review/v1/roots"
_MALFORMED_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_CANONICAL_DECIMAL = re.compile(r"^[0-9]{1,9}$")


def _optional_range_once(query: dict[str, list[str]], name: str) -> int | None:
    values = query.get(name, [])
    if len(values) > 1:
        raise RangeInvalidError(f"{name} may be supplied at most once")
    if not values:
        return None
    if not _CANONICAL_DECIMAL.fullmatch(values[0]):
        raise RangeInvalidError(f"{name} must be a canonical nonnegative decimal integer")
    return int(values[0])


def _optional_route_digest(query: dict[str, list[str]]) -> str | None:
    values = query.get("route_digest", [])
    if len(values) > 1:
        raise RouteStaleError("route_digest may be supplied at most once")
    if not values:
        return None
    if not SHA256.fullmatch(values[0]):
        raise RouteStaleError("route_digest must be a lowercase SHA-256 digest")
    return values[0]


def _required_once(query: dict[str, list[str]], name: str, *, maximum: int = 512) -> str:
    values = query.get(name, [])
    if len(values) != 1:
        raise ReviewContractError(f"{name} is required once")
    value = values[0]
    if not is_route_valid_scalar_text(value, maximum):
        raise ReviewContractError(f"{name} must be nonempty and bounded")
    return value


def _optional_once(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name, [])
    if len(values) > 1:
        raise ReviewContractError(f"{name} may be supplied at most once")
    if not values:
        return None
    reject_unicode_surrogates(values[0], name)
    return values[0]


def _optional_identity_once(query: dict[str, list[str]], name: str) -> str | None:
    value = _optional_once(query, name)
    if value is None:
        return None
    return governed_identity_text(value, name)


def _optional_catalog_version(query: dict[str, list[str]]) -> str | None:
    value = _optional_once(query, "catalog_version")
    if value is None:
        return None
    if not SHA256.fullmatch(value):
        raise RouteStaleError(
            "catalog_version must be a lowercase SHA-256 digest"
        )
    return value


def _image_selection(query: dict[str, list[str]], side: str) -> dict[str, str] | None:
    variant = _optional_once(query, f"{side}_image")
    region = _optional_once(query, f"{side}_region")
    digest = _optional_once(query, f"{side}_image_sha256")
    if region is not None or digest is not None:
        if region is None or digest is None or variant is not None or not SHA256.fullmatch(digest):
            raise ReviewContractError("region and image_sha256 must appear together without an image variant field")
        parse_region(region)
        return {"variant": "region", "region": region, "source_sha256": digest}
    if variant is None:
        return None
    if variant not in {"preview", "original"}:
        raise ReviewContractError("Compare image must be preview or original")
    return {"variant": variant}


def _required_location_once(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name, [])
    if len(values) != 1:
        raise ReviewContractError(f"{name} is required once")
    return governed_location_text(values[0], name)


def _optional_location_once(query: dict[str, list[str]], name: str) -> str | None:
    value = _optional_once(query, name)
    return None if value is None else governed_location_text(value, name)


def _optional_search_once(query: dict[str, list[str]], name: str) -> str | None:
    value = _optional_once(query, name)
    if value is None:
        return None
    if not is_route_valid_scalar_text(value, MAX_LOCATION_SEARCH_SCALARS):
        raise ReviewContractError(
            f"{name} must be nonempty and bounded to at most {MAX_LOCATION_SEARCH_SCALARS} Unicode scalar values"
        )
    return value


def _required_identity_once(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name, [])
    if len(values) != 1:
        raise ReviewContractError(f"{name} is required once")
    try:
        return governed_identity_text(values[0], name)
    except ReviewContractError as error:
        if "nonempty" in str(error) or "at most 256" in str(error):
            raise ReviewContractError(f"{name} must be nonempty and bounded") from error
        raise


def _strict_query(raw_query: str) -> dict[str, list[str]]:
    if _MALFORMED_PERCENT_ESCAPE.search(raw_query):
        raise ReviewContractError("query contains a malformed percent escape")
    try:
        return parse_qs(raw_query, keep_blank_values=True, errors="strict")
    except UnicodeDecodeError as error:
        raise ReviewContractError("query contains malformed percent-encoded UTF-8") from error


class _ReviewHandler(BaseHTTPRequestHandler):
    server_version = "CorpusReviewViewer/1"
    # One request per connection: request_id and refusal state are handler-local.
    # Keep-alive would require resetting that state for every request first.
    protocol_version = "HTTP/1.0"

    def setup(self) -> None:
        super().setup()
        self.request_id = uuid.uuid4().hex
        self.request_started = time.monotonic()

    @property
    def review_server(self) -> "ReviewHTTPServer":
        return self.server  # type: ignore[return-value]

    def _headers(self, status: HTTPStatus, content_type: str, length: int, extra: dict[str, str] | None = None) -> None:
        self.response_started = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("X-CVW-Request-ID", self.request_id)
        self.send_header("Cache-Control", "no-store")
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()

    def _verify_response_identity(self) -> bool:
        if self.review_server.serving_identity is not None and not getattr(self, "identity_refused", False):
            try:
                # Verify once, immediately before headers, including error replies.
                self.review_server.serving_identity.verify()
            except ServingIdentityError as error:
                self.identity_refused = True
                self._error(HTTPStatus.SERVICE_UNAVAILABLE, "implementation-drift", str(error))
                return False
        return True

    def _bytes(self, status: HTTPStatus, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        if not self._verify_response_identity():
            return
        self._headers(status, content_type, len(body), extra)
        self.wfile.write(body)
        self._record_response(status, len(body))

    def _record_response(
        self,
        status: HTTPStatus,
        length: int,
        *,
        error_code: str | None = None,
    ) -> None:
        self.review_server.record_event(
            "request",
            request_id=self.request_id,
            method=self.command,
            path=urlparse(self.path).path,
            status=int(status),
            bytes=length,
            elapsed_ms=round((time.monotonic() - self.request_started) * 1000),
            error_code=error_code or getattr(self, "response_error_code", None),
        )

    def _json(self, status: HTTPStatus, value: object) -> None:
        self._bytes(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _bounded_json(self, value: object, code: str, message: str) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        if len(body) > MAX_RESPONSE_SERIALIZED_BYTES:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, code, message)
            return
        self._bytes(HTTPStatus.OK, body, "application/json; charset=utf-8")

    def _error(self, status: HTTPStatus, code: str, message: str) -> None:
        self.response_error_code = code
        self._json(
            status,
            {
                "contract": "ocd-corpus-review-error-v1",
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": self.request_id,
                },
                "request_id": self.request_id,
            },
        )

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        try:
            if route == "/api/review/v1/session":
                self._json(HTTPStatus.OK, self.review_server.public_session_descriptor())
                return
            if route == "/api/review/v1/works":
                query = _strict_query(parsed.query)
                if "view" in query:
                    expected_query = {"view", "offset", "limit", "catalog_version", "search", "state"}
                    unknown = sorted(set(query) - expected_query)
                    if unknown:
                        raise ReviewContractError(
                            f"unknown catalog query field: {unknown[0]}"
                        )
                    view = _required_once(query, "view", maximum=16)
                    if view != "summary":
                        raise ReviewContractError("view must be summary when supplied")
                    offset = _optional_range_once(query, "offset")
                    limit = _optional_range_once(query, "limit")
                    if limit is not None and (
                        limit < 1 or limit > MAX_CATALOG_PAGE_SIZE
                    ):
                        raise RangeInvalidError(
                            f"limit must be between 1 and {MAX_CATALOG_PAGE_SIZE}"
                        )
                    summary_method = getattr(
                        self.review_server.application, "catalog_summary_page", None
                    )
                    if summary_method is None:
                        raise ReviewContractError(
                            "bounded catalog summary is unavailable"
                        )
                    self._bounded_json(
                        summary_method(
                            offset=0 if offset is None else offset,
                            limit=MAX_CATALOG_PAGE_SIZE if limit is None else limit,
                            catalog_version=_optional_catalog_version(query),
                            **({"search": _optional_search_once(query, "search")} if "search" in query else {}),
                            **({"state": _optional_once(query, "state")} if "state" in query else {}),
                        ),
                        "response-too-large",
                        "Request a smaller catalog page to stay within the governed response bound.",
                    )
                    return
                if query:
                    raise ReviewContractError("Catalog query parameters require view=summary")
                catalog = self.review_server.application.catalog()
                body = json.dumps(catalog, ensure_ascii=False).encode("utf-8")
                if len(body) > MAX_RESPONSE_SERIALIZED_BYTES:
                    self._error(
                        HTTPStatus.UNPROCESSABLE_ENTITY,
                        "catalog-too-large",
                        "The catalog exceeds the governed response bound; the operator must reduce the manifest works or outline bounds.",
                    )
                    return
                self._bytes(HTTPStatus.OK, body, "application/json; charset=utf-8")
                return
            if route == _ROOTS_ROUTE:
                query = _strict_query(parsed.query)
                expected_query = {"offset", "limit", "work", "catalog_version"}
                unknown = sorted(set(query) - expected_query)
                if unknown:
                    raise ReviewContractError(
                        f"unknown root discovery query field: {unknown[0]}"
                    )
                offset = _optional_range_once(query, "offset")
                limit = _optional_range_once(query, "limit")
                if limit is not None and (
                    limit < 1 or limit > MAX_CATALOG_PAGE_SIZE
                ):
                    raise RangeInvalidError(
                        f"limit must be between 1 and {MAX_CATALOG_PAGE_SIZE}"
                    )
                roots_method = getattr(
                    self.review_server.application, "approved_roots_page", None
                )
                if roots_method is None:
                    raise ReviewContractError(
                        "approved root discovery is unavailable"
                    )
                self._bounded_json(
                    roots_method(
                        offset=0 if offset is None else offset,
                        limit=MAX_CATALOG_PAGE_SIZE if limit is None else limit,
                        work_slug=_optional_identity_once(query, "work"),
                        catalog_version=_optional_catalog_version(query),
                    ),
                    "response-too-large",
                    "Request a smaller approved-root page to stay within the governed response bound.",
                )
                return
            artifacts_match = _ARTIFACTS_ROUTE.fullmatch(route)
            if artifacts_match:
                slug, stage_id = artifacts_match.groups()
                query = _strict_query(parsed.query)
                expected_query = {
                    "offset", "limit", "search", "catalog_version",
                    "artifact_id", "artifact_version",
                }
                unknown = sorted(set(query) - expected_query)
                if unknown:
                    raise ReviewContractError(
                        f"unknown artifact discovery query field: {unknown[0]}"
                    )
                offset = _optional_range_once(query, "offset")
                limit = _optional_range_once(query, "limit")
                if limit is not None and (
                    limit < 1 or limit > MAX_ARTIFACT_PAGE_SIZE
                ):
                    raise RangeInvalidError(
                        f"limit must be between 1 and {MAX_ARTIFACT_PAGE_SIZE}"
                    )
                artifact_kwargs = {
                    "offset": 0 if offset is None else offset,
                    "limit": MAX_ARTIFACT_PAGE_SIZE if limit is None else limit,
                    "search": _optional_search_once(query, "search"),
                    "catalog_version": _optional_catalog_version(query),
                }
                artifact_id = _optional_identity_once(query, "artifact_id")
                artifact_version = _optional_identity_once(query, "artifact_version")
                if artifact_id is not None or artifact_version is not None:
                    artifact_kwargs.update(
                        {"artifact_id": artifact_id, "artifact_version": artifact_version}
                    )
                self._bounded_json(
                    self.review_server.application.artifact_page(
                        slug,
                        stage_id,
                        **artifact_kwargs,
                    ),
                    "response-too-large",
                    "Request a smaller artifact page to stay within the governed response bound.",
                )
                return
            correspondence_match = _CORRESPONDENCE_ROUTE.fullmatch(route)
            if correspondence_match:
                query = _strict_query(parsed.query)
                unknown = sorted(set(query) - {"correspondence_source", "offset", "limit", "catalog_version"})
                if unknown:
                    raise ReviewContractError(f"unknown correspondence query field: {unknown[0]}")
                offset = _optional_range_once(query, "offset")
                limit = _optional_range_once(query, "limit")
                self._bounded_json(
                    self.review_server.application.correspondence_page(
                        correspondence_match.group(1),
                        _required_once(query, "correspondence_source"),
                        offset=0 if offset is None else offset,
                        limit=MAX_CATALOG_PAGE_SIZE if limit is None else limit,
                        catalog_version=_optional_catalog_version(query),
                    ),
                    "response-too-large", "Request a smaller correspondence page.",
                )
                return
            work_match = _WORK_ROUTE.fullmatch(route)
            if work_match:
                query = _strict_query(parsed.query)
                expected_query = {
                    "source_artifact", "source_version", "tei_artifact", "tei_version",
                    "catalog_version",
                }
                unknown = sorted(set(query) - expected_query)
                if unknown:
                    raise ReviewContractError(
                        f"unknown work detail query field: {unknown[0]}"
                    )
                self._bounded_json(
                    self.review_server.application.work_detail(
                        work_match.group(1),
                        source_artifact=_optional_identity_once(query, "source_artifact"),
                        source_version=_optional_identity_once(query, "source_version"),
                        tei_artifact=_optional_identity_once(query, "tei_artifact"),
                        tei_version=_optional_identity_once(query, "tei_version"),
                        catalog_version=_optional_catalog_version(query),
                    ),
                    "response-too-large",
                    "Request a bounded work detail response.",
                )
                return
            compare_match = _COMPARE_ROUTE.fullmatch(route)
            if compare_match:
                query = _strict_query(parsed.query)
                expected_query = {"left_stage", "left_artifact", "left_version", "left_location", "right_stage", "right_artifact", "right_version", "right_location", "linked", "correspondence", "left_segment_start", "left_segment_limit", "right_segment_start", "right_segment_limit", "auto_page", "route_digest", "representation", "left_image", "left_region", "left_image_sha256", "right_image", "right_region", "right_image_sha256"}
                unknown = sorted(set(query) - expected_query)
                if unknown:
                    raise ReviewContractError(f"unknown compare query field: {unknown[0]}")
                left_stage = _required_once(query, "left_stage", maximum=16)
                right_stage = _required_once(query, "right_stage", maximum=16)
                linked_value = _required_once(query, "linked", maximum=5)
                if linked_value not in {"true", "false"}:
                    raise ReviewContractError("linked must be true or false")
                correspondence = _required_identity_once(query, "correspondence")
                if correspondence == "absent":
                    correspondence = None
                representation = _optional_once(query, "representation")
                if representation not in {None, "brief", "text"}:
                    raise ReviewContractError("representation must be brief or text when supplied")
                auto_page_value = _optional_once(query, "auto_page")
                if auto_page_value not in {None, "true", "false"}:
                    raise ReviewContractError("auto_page must be true or false")
                self._bounded_json(
                    self.review_server.application.compare_view(
                        compare_match.group(1),
                        left_stage=left_stage,
                        left_recorded=RecordedContext(
                            _required_identity_once(query, "left_artifact"),
                            _required_identity_once(query, "left_version"),
                            _required_once(query, "left_location"),
                        ),
                        right_stage=right_stage,
                        right_recorded=RecordedContext(
                            _required_identity_once(query, "right_artifact"),
                            _required_identity_once(query, "right_version"),
                            _required_once(query, "right_location"),
                        ),
                        linked=linked_value == "true",
                        correspondence_source=correspondence,
                        left_segment_start=_optional_range_once(query, "left_segment_start"),
                        left_segment_limit=_optional_range_once(query, "left_segment_limit"),
                        right_segment_start=_optional_range_once(query, "right_segment_start"),
                        right_segment_limit=_optional_range_once(query, "right_segment_limit"),
                        auto_page=auto_page_value == "true",
                        echoed_route_digest=_optional_route_digest(query),
                        evidence_brief=representation == "brief",
                        **({"text_only": True} if representation == "text" else {}),
                        left_image=_image_selection(query, "left"), right_image=_image_selection(query, "right"),
                    ),
                    "response-too-large",
                    "Request a smaller segment range for each pane to stay within the governed response bound.",
                )
                return
            locations_match = _LOCATIONS_ROUTE.fullmatch(route)
            if locations_match:
                slug, stage_id = locations_match.groups()
                query = _strict_query(parsed.query)
                expected_query = {
                    "expected_artifact", "expected_version", "offset", "limit", "search",
                }
                unknown = sorted(set(query) - expected_query)
                if unknown:
                    raise ReviewContractError(f"unknown locations query field: {unknown[0]}")
                offset = _optional_range_once(query, "offset")
                limit = _optional_range_once(query, "limit")
                if limit is not None and (
                    limit < 1 or limit > MAX_LOCATION_PAGE_SIZE
                ):
                    raise RangeInvalidError(
                        f"limit must be between 1 and {MAX_LOCATION_PAGE_SIZE}"
                    )
                self._bounded_json(
                    self.review_server.application.locations(
                        slug,
                        stage_id,
                        expected_artifact=_required_identity_once(query, "expected_artifact"),
                        expected_version=_required_identity_once(query, "expected_version"),
                        offset=0 if offset is None else offset,
                        limit=MAX_LOCATION_PAGE_SIZE if limit is None else limit,
                        search=_optional_search_once(query, "search"),
                    ),
                    "response-too-large",
                    "Request a smaller location range to stay within the governed response bound.",
                )
                return
            match = _STAGE_ROUTE.fullmatch(route)
            if match:
                slug, stage_id, suffix = match.groups()
                query = _strict_query(parsed.query)
                expected_artifact = _required_identity_once(query, "expected_artifact")
                expected_version = _required_identity_once(query, "expected_version")
                if suffix == "/exact":
                    exact = self.review_server.application.exact(slug, stage_id, expected_artifact, expected_version)
                    self._bytes(HTTPStatus.OK, exact.encode("utf-8"), "text/plain; charset=utf-8")
                elif suffix == "/pdf-page":
                    unknown = sorted(set(query) - {"expected_artifact", "expected_version", "expected_sha256", "page"})
                    if unknown:
                        raise ReviewContractError(f"unknown PDF query field: {unknown[0]}")
                    page = _optional_range_once(query, "page")
                    if page is None:
                        raise ReviewContractError("PDF page is required")
                    payload = self.review_server.application.stage_pdf_page(
                        slug, stage_id, expected_artifact, expected_version,
                        _required_identity_once(query, "expected_sha256"), page,
                    )
                    self._bytes(HTTPStatus.OK, payload, "image/png")
                elif suffix == "/image":
                    expected_query = {"expected_artifact", "expected_version", "expected_sha256", "variant", "region"}
                    unknown = sorted(set(query) - expected_query)
                    if unknown:
                        raise ReviewContractError(f"unknown image query field: {unknown[0]}")
                    variant = _required_once(query, "variant", maximum=16)
                    region = _optional_once(query, "region")
                    expected_sha256 = _required_identity_once(query, "expected_sha256")
                    payload, metadata = self.review_server.application.stage_image(
                        slug, stage_id, expected_artifact, expected_version, expected_sha256, variant=variant, region=region,
                    )
                    self._bytes(HTTPStatus.OK, payload, metadata["output"]["media_type"], {
                        "X-CVW-Image-Metadata": json.dumps(metadata, ensure_ascii=True, separators=(",", ":")),
                        "X-CVW-Source-SHA256": metadata["source"]["sha256"],
                        "X-CVW-Output-SHA256": metadata["output"]["sha256"],
                    })
                elif suffix == "/bytes":
                    expected_query = {"expected_artifact", "expected_version", "expected_sha256", "download"}
                    unknown = sorted(set(query) - expected_query)
                    if unknown:
                        raise ReviewContractError(f"unknown bytes query field: {unknown[0]}")
                    download = _optional_once(query, "download")
                    if download is not None and download != "1":
                        raise ReviewContractError("download must be 1 when supplied")
                    expected_sha256 = _optional_once(query, "expected_sha256")
                    arguments = {} if expected_sha256 is None else {"expected_sha256": expected_sha256}
                    payload, media_type = self.review_server.application.stage_bytes(
                        slug, stage_id, expected_artifact, expected_version, **arguments,
                    )
                    disposition = "attachment" if download == "1" else "inline"
                    # Native bytes get their own sandboxed header set; the JSON
                    # SECURITY_HEADERS (frame-ancestors 'none' et al.) stay off this response.
                    if not self._verify_response_identity():
                        return
                    self.response_started = True
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", media_type)
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("X-CVW-Request-ID", self.request_id)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Security-Policy", "sandbox")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Content-Disposition", disposition)
                    self.end_headers()
                    self.wfile.write(payload)
                    self._record_response(HTTPStatus.OK, len(payload))
                else:
                    expected_query = {
                        "expected_artifact", "expected_version", "location", "from_stage", "from_location",
                        "segment_start", "segment_limit", "auto_page", "route_digest",
                    }
                    unknown = sorted(set(query) - expected_query)
                    if unknown:
                        raise ReviewContractError(f"unknown stage query field: {unknown[0]}")
                    location = _required_location_once(query, "location")
                    from_stage = _optional_once(query, "from_stage")
                    from_location = _optional_location_once(query, "from_location")
                    segment_start = _optional_range_once(query, "segment_start")
                    segment_limit = _optional_range_once(query, "segment_limit")
                    auto_page_value = _optional_once(query, "auto_page")
                    if auto_page_value not in {None, "true", "false"}:
                        raise ReviewContractError("auto_page must be true or false")
                    echoed = _optional_route_digest(query)
                    view = self.review_server.application.stage_view(
                        slug,
                        stage_id,
                        recorded=RecordedContext(expected_artifact, expected_version, location),
                        from_stage=from_stage,
                        from_location=from_location,
                        segment_start=segment_start,
                        segment_limit=segment_limit,
                        auto_page=auto_page_value == "true",
                        echoed_route_digest=echoed,
                    )
                    self._bounded_json(view, "response-too-large", "Request a smaller segment range to stay within the governed response bound.")
                return
            if route == "/review" or route.startswith("/review/"):
                self._static("review.html")
                return
            if route.startswith("/assets/"):
                self._static(route.removeprefix("/"))
                return
            self._error(HTTPStatus.NOT_FOUND, "route-not-found", "The requested route does not exist.")
        except ServingIdentityError as error:
            self.identity_refused = True
            self._error(HTTPStatus.SERVICE_UNAVAILABLE, "implementation-drift", str(error))
        except RangeInvalidError as error:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, "range-invalid", str(error))
        except RouteStaleError as error:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, "route-stale", str(error))
        except ResponseTooLargeError as error:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, "response-too-large", str(error))
        except FormatNotAllowListedError as error:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, "format-not-allow-listed", str(error))
        except NativeImageError as error:
            self._error(HTTPStatus.SERVICE_UNAVAILABLE if error.code == "image-busy" else HTTPStatus.UNPROCESSABLE_ENTITY,
                        error.code, str(error))
        except ReviewContractError as error:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, "artifact-invalid", str(error))
        except OSError as error:
            if getattr(self, "response_started", False):
                raise
            self.review_server.record_event(
                "error",
                request_id=self.request_id,
                method=self.command,
                path=parsed.path,
                error_type=type(error).__name__,
                message=str(error),
            )
            self._error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "artifact-unavailable",
                "The viewer could not read the requested artifact; see the session diagnostics.",
            )
        except Exception as error:
            if getattr(self, "response_started", False):
                raise
            self.review_server.record_event(
                "error",
                request_id=self.request_id,
                method=self.command,
                path=parsed.path,
                error_type=type(error).__name__,
                message=str(error),
            )
            self._error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "internal-error",
                "The viewer could not complete the request; see the session diagnostics.",
            )

    def _reject_write(self) -> None:
        self._error(
            HTTPStatus.NOT_FOUND,
            "route-not-found",
            "The read-only viewer does not expose write routes.",
        )

    def do_POST(self) -> None:  # noqa: N802
        self._reject_write()

    def do_PUT(self) -> None:  # noqa: N802
        self._reject_write()

    def do_PATCH(self) -> None:  # noqa: N802
        self._reject_write()

    def do_DELETE(self) -> None:  # noqa: N802
        self._reject_write()

    def _static(self, relative_text: str) -> None:
        relative = Path(relative_text)
        root = self.review_server.static_root
        target = (root / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or not target.is_relative_to(root):
            self._error(HTTPStatus.NOT_FOUND, "route-not-found", "The requested route does not exist.")
            return
        if not target.is_file():
            self._error(HTTPStatus.NOT_FOUND, "asset-not-found", "The requested viewer asset does not exist.")
            return
        body = target.read_bytes()
        if self.review_server.serving_identity is not None:
            self.review_server.serving_identity.verify_static_bytes(relative.as_posix(), body)
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self._bytes(HTTPStatus.OK, body, content_type)

    def log_message(self, format: str, *args: object) -> None:
        return


class ReviewHTTPServer(ThreadingHTTPServer):
    # Fixed-port collisions must fail loudly; silent SO_REUSEADDR binding can
    # cross-wire two read-only review sessions on Windows.
    allow_reuse_address = False

    def __init__(
        self,
        address: tuple[str, int],
        application: ReviewApplication,
        static_root: Path,
        *,
        session_descriptor: Mapping[str, object] | None = None,
        event_sink: Callable[..., None] | None = None,
        serving_identity: ServingIdentity | None = None,
    ) -> None:
        self.application = application
        self.static_root = static_root.resolve()
        self.event_sink = event_sink
        self.diagnostic_health = DiagnosticHealth()
        self.serving_identity = serving_identity
        super().__init__(address, _ReviewHandler)
        if session_descriptor is None:
            display_host = "127.0.0.1" if address[0] == "localhost" else address[0]
            actual_port = int(self.server_address[1])
            session_descriptor = make_session_descriptor(
                session_id=new_session_id(),
                host=address[0],
                requested_port=address[1],
                port=actual_port,
                origin=f"http://{display_host}:{actual_port}",
                pid=os.getpid(),
                state="ready",
            )
        self.session_descriptor = session_descriptor

    def public_session_descriptor(self) -> dict[str, object]:
        """Keep absolute provenance and detailed exception text in local evidence."""
        session = dict(self.session_descriptor.get("session", {}))
        session.pop("error_message", None)
        if "phases" in session:
            session["phases"] = {
                name: {key: value for key, value in row.items() if key not in {"message", "errors"}}
                for name, row in session["phases"].items()
            }
        return {"contract": self.session_descriptor.get("contract"), "session": session}

    def record_event(self, event: str, **fields: object) -> None:
        if self.event_sink is not None:
            session = self.session_descriptor.get("session", {})
            fields.setdefault("session_id", session.get("session_id"))
            fields.setdefault("origin", session.get("origin"))
            try:
                self.event_sink(event, **fields)
            except OSError as error:
                self.diagnostic_health.report(error, event=event, request_id=fields.get("request_id"), session_id=fields.get("session_id"), operation="event_sink")


def make_server(
    catalog_path: Path,
    candidate_dirs: list[Path],
    *,
    static_root: Path,
    host: str = "127.0.0.1",
    port: int = 0,
    repository_root: Path | None = None,
    application: ReviewApplication | None = None,
    session_descriptor: Mapping[str, object] | None = None,
    event_sink: Callable[..., None] | None = None,
    serving_identity: ServingIdentity | None = None,
) -> ReviewHTTPServer:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("Corpus Review Viewer must bind to loopback only")
    if not static_root.resolve().is_dir():
        raise ValueError("static_root must be an existing directory")
    if application is None:
        raise ValueError(
            "server application must come from the protected candidate-session preflight"
        )
    return ReviewHTTPServer(
        (host, port),
        application,
        static_root,
        session_descriptor=session_descriptor,
        event_sink=event_sink,
        serving_identity=serving_identity,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    from cvw_app.launch_windows import build_argument_parser as build_launcher_parser

    return build_launcher_parser()


def main() -> None:
    from cvw_app.launch_windows import main as launch_windows_main

    launch_windows_main()


if __name__ == "__main__":
    main()
