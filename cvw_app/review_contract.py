"""Manifest, root-binding, and verified-artifact contract for the viewer."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from collections import OrderedDict
from dataclasses import dataclass
import gc
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
import threading
import zlib
from types import MappingProxyType
from typing import Any, Iterable
from urllib.parse import urlencode, quote, urlsplit, parse_qsl

from cvw_app.native_images import (
    MEDIA_FORMATS, MAX_INPUT_BYTES, NativeImageError, check_input_size,
    image_work, inspect_image, preview_image, parse_region, region_image, region_plan,
)

from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    ReviewView,
    SourceManifest,
    ValidationReport,
    _contained,
)
from ocd_kernel.library._common import io_path
from ocd_kernel.library.views import library_search_matches
from ocd_kernel.reconstruction.text_quality import verify_text_quality

from cvw_app.review_renderers import (
    BINARY_PRESENTATION_KINDS,
    CONTEXT_PRESENTATION_KINDS,
    DEFAULT_RENDERER_REGISTRY,
    MAX_PAGE_SCALARS,
    MAX_STRUCTURE_LOCATION_SCALARS,
    RendererError,
    RendererRegistry,
    bounded_visible_text,
    is_route_valid_scalar_text,
    verify_binary_content_signature,
)
from cvw_app.renderer_nodes import _node_text, _nodes_text


MANIFEST_CONTRACT = "ocd-corpus-review-manifest-v1"
CATALOG_CONTRACT = "ocd-corpus-review-catalog-v1"
STAGE_VIEW_CONTRACT = "ocd-corpus-review-stage-view-v1"
LOCATIONS_CONTRACT = "ocd-corpus-review-locations-v1"
COMPARE_VIEW_CONTRACT = "ocd-corpus-review-compare-view-v1"
EVIDENCE_BRIEF_CONTRACT = "ocd-corpus-review-evidence-brief-v1"
CORRESPONDENCE_CONTRACT = "ocd-corpus-review-correspondence-v1"
STAGE_ORDER = ("source", "tei")
STAGE_LABELS = {"source": "Retained source", "tei": "Faithful TEI candidate"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
UNICODE_SURROGATE = re.compile(r"[\ud800-\udfff]")
MAX_WORK_SLUG_SCALARS = 256
MAX_WORK_TITLE_SCALARS = 512
MAX_WORK_CREATOR_SCALARS = 512
MAX_MEDIA_TYPE_SCALARS = 256
MAX_LOCATION_KIND_SCALARS = 128
# Ticket 06a governed budgets (plan v4.18).
MAX_OUTLINE_PAYLOAD_BYTES = 80_000
MAX_RESPONSE_SERIALIZED_BYTES = 512_000
MAX_CATALOG_PAGE_SIZE = 50
MAX_ARTIFACT_PAGE_SIZE = 50
# Location discovery is a bounded index lookup, not a second unbounded outline
# response.  Keep these limits independent of the existing document/response
# budgets so the latter remain stable for all callers.
MAX_LOCATION_PAGE_SIZE = 32
MAX_LOCATION_SEARCH_SCALARS = 256
# A rendered segment is independently bounded, but several nearly-full segments
# can exceed the serialized response envelope once node metadata is included.
# Publish one segment per request so the advertised maximum is always the same
# unit that the response-size probe and navigation contract verify.
PAGING_MAX_SEGMENTS_PER_REQUEST = 1
MAX_CACHE_RETAINED_BYTES = 256 * 1024 * 1024
CACHE_MAX_ENTRIES = 8


class ReviewContractError(ValueError):
    """Raised when viewer input violates the public trust contract."""


class RangeInvalidError(ReviewContractError):
    """A requested segment range violates the canonical decimal range grammar or bounds."""


class RouteStaleError(ReviewContractError):
    """An echoed route_digest does not match the freshly computed manifest state."""


class ResponseTooLargeError(ReviewContractError):
    """A composed presentation response exceeds the governed serialized budget."""


class CatalogTooLargeError(ReviewContractError):
    """The catalog response exceeds the governed serialized budget; operator action required."""


class FormatNotAllowListedError(ReviewContractError):
    """A bytes request named a media type that is not on the safe native-format allow list."""


@dataclass(frozen=True)
class RecordedContext:
    artifact_id: str
    version: str
    location: str


@dataclass(frozen=True)
class CandidateSessionBinding:
    """The already-verified identity needed for one launcher handoff."""

    path: Path
    work_ids: tuple[str, ...]
    source_id: str
    source_manifest_path: str
    source_manifest_sha256: str
    candidate_sha256: str
    validation_report_sha256: str
    validation_status: str


def recorded_stage_context_is_current(view: dict[str, Any]) -> bool:
    """A selected identity is reconcilable when its bytes are readable, even if its requested location is missing."""
    return view["recorded_context"]["state"] in {"exact", "location-missing"}


@dataclass
class StageResolution:
    availability: str
    message: str
    artifact: dict[str, Any] | None = None
    exact: str | None = None
    presentation: dict[str, Any] | None = None
    rendered: dict[str, Any] | None = None
    cache_resident: bool = False
    readable: bool = False
    path: Path | None = None
    verified_image_payload: bytes | None = None


def canonical_route_digest(payload: object) -> str:
    """Compute the governed v1 canonical route digest over a route-affecting payload."""
    canon = json.dumps(
        {"v": 1, "payload": payload},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canon).hexdigest()


from cvw_app.ingest_cache import VerifiedIngestCache, estimate_retained_bytes, compact_projection, PackedOutline

def ingest_cache_key(root_id: str, relpath: str, sha256: str, declared_kind: str, media_type: str) -> tuple[str, ...]:
    """Verified-ingest identity: same bytes under two declared kinds never share an entry."""
    return (str(root_id), Path(relpath).as_posix(), str(sha256), str(declared_kind), str(media_type))


def source_content_digest(source: dict[str, Any]) -> str:
    """Governed content digest over ALL route-affecting fields of one source, including message."""
    return canonical_route_digest(dict(source))


def serialized_payload_size(value: object) -> int:
    """Measured UTF-8 JSON serialization size used by every governed body bound."""
    if isinstance(value, PackedOutline):
        return value.serialized_bytes
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def _original_image_dimensions(media_type: str, payload: bytes) -> dict[str, Any] | None:
    """Read a PNG's encoded dimensions from verified bytes, without decoding pixels.

    Other formats remain unknown until their metadata is supported. A valid
    IHDR does not establish successful browser decoding or painting.
    """
    if (
        media_type == "image/png" and len(payload) >= 33
        and payload[:16] == b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        and zlib.crc32(payload[12:29]) == int.from_bytes(payload[29:33], "big")
    ):
        width = int.from_bytes(payload[16:20], "big")
        height = int.from_bytes(payload[20:24], "big")
        if 0 < width < 2**31 and 0 < height < 2**31:
            return {"width": width, "height": height, "basis": "encoded-png-ihdr"}
    return None


def _plain_node_text(node: dict[str, Any], cache: dict[int, str] | None = None) -> str:
    """Readable text of one rendered node subtree (mirrors renderer aggregation)."""
    if cache is None:
        cache = {}
    if id(node) in cache:
        return cache[id(node)]
    children = node.get("children", []) or []
    own = node.get("text", "") or ""
    text = own if node.get("type") == "preformatted" and not children else " ".join(
        part for part in [own, *(_plain_node_text(child, cache) for child in children)] if part
    ).strip(" ")
    cache[id(node)] = text
    return text


def require_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReviewContractError(f"{label} must be an object")
    # CandidatePackage manifests are intentionally exposed as immutable
    # MappingProxyType values by the minimal reconstruction contract.  Keep
    # the viewer's parsed-JSON mutation boundary detached from that read-only
    # object while accepting any mapping-shaped JSON object.
    return dict(value)


def strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build a JSON object while rejecting ambiguous duplicate fields."""
    value: dict[str, object] = {}
    for name, item in pairs:
        reject_unicode_surrogates(name, "JSON field name")
        if name in value:
            raise ValueError(f"JSON field is duplicated: {name}")
        value[name] = item
    return value


def reject_unicode_surrogates(value: str, label: str) -> None:
    """Reject scalar-invalid UTF-16 surrogate code points in governed text."""
    if UNICODE_SURROGATE.search(value):
        raise ReviewContractError(f"{label} must not contain Unicode surrogate code points")


def governed_identity_text(value: object, label: str) -> str:
    """Validate identity text with the same nonempty predicate as ECMAScript trim()."""
    if isinstance(value, str):
        reject_unicode_surrogates(value, label)
    if not is_route_valid_scalar_text(value):
        raise ReviewContractError(f"{label} must be nonempty text")
    assert isinstance(value, str)
    if len(value) > 256:
        raise ReviewContractError(f"{label} must be at most 256 Unicode scalar values")
    return value


def governed_location_text(value: object, label: str) -> str:
    """Validate one route location with the shared browser-compatible scalar contract."""
    if isinstance(value, str):
        reject_unicode_surrogates(value, label)
    if not is_route_valid_scalar_text(value, MAX_STRUCTURE_LOCATION_SCALARS):
        raise ReviewContractError(
            f"{label} must be nonempty and bounded to at most {MAX_STRUCTURE_LOCATION_SCALARS} Unicode scalar values"
        )
    assert isinstance(value, str)
    return value


def _governed_bounded_text(value: object, label: str, maximum: int) -> str:
    if isinstance(value, str):
        reject_unicode_surrogates(value, label)
    if not is_route_valid_scalar_text(value):
        raise ReviewContractError(f"{label} must be nonempty text")
    assert isinstance(value, str)
    if len(value) > maximum:
        raise ReviewContractError(f"{label} must be at most {maximum} Unicode scalar values")
    return value


def governed_enum_text(value: object, allowed: Collection[str], label: str, requirement: str) -> str:
    """Validate a governed discriminator before any hash-based lookup or indexing."""
    if not isinstance(value, str) or value not in allowed:
        raise ReviewContractError(f"{label} {requirement}")
    return value


def _text(value: object, label: str) -> str:
    if not is_route_valid_scalar_text(value):
        raise ReviewContractError(f"{label} must be nonempty text")
    assert isinstance(value, str)
    return value


def _identity_text(value: object, label: str) -> str:
    return governed_identity_text(value, label)


def _catalog_route_path(value: object, label: str) -> str:
    text = _text(value, label)
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        raise ReviewContractError(f"{label} must be repository-relative")
    return path.as_posix()


def _source_presentation(path: Path) -> tuple[str, str, str]:
    name = path.name.lower()
    if name.endswith((".html", ".htm")):
        return "text/html", "sanitized-html", "source-anchor"
    if name.endswith(".xhtml"):
        return "application/xhtml+xml", "sanitized-html", "source-anchor"
    if name.endswith(".json"):
        return "application/json", "json-tree", "json-pointer"
    text_formats = {".jsonl": "application/x-ndjson", ".toml": "application/toml",
                    ".csv": "text/csv", ".tsv": "text/tab-separated-values",
                    ".usfm": "text/x-usfm", ".sfm": "text/x-usfm"}
    if path.suffix.lower() in text_formats:
        return text_formats[path.suffix.lower()], "exact-text", "source-location"
    if name.endswith(".pdf"):
        return "application/pdf", "pdf-native", "page"
    if name.endswith(".png"):
        return "image/png", "image-facsimile", "image"
    if name.endswith((".jpg", ".jpeg")):
        return "image/jpeg", "image-facsimile", "image"
    if name.endswith(".webp"):
        return "image/webp", "image-facsimile", "image"
    if name.endswith((".tif", ".tiff")):
        return "image/tiff", "image-facsimile", "image"
    if name.endswith(".epub"):
        return "application/epub+zip", "epub-reader", "spine-location"
    if name.startswith("._"):
        return "application/octet-stream", "unsupported-binary", "source-location"
    if name.endswith(".idx"):
        # CrossWire SWORD rawLD indexes are binary order authorities, not UTF-8
        # text. Keep them as an explicit exact-byte handoff in the read-only
        # viewer instead of attempting a lossy decode.
        return "application/octet-stream", "unsupported-binary", "source-location"
    if name.endswith(".zip"):
        return "application/zip", "unsupported-binary", "source-location"
    if name.endswith(".gz"):
        return "application/gzip", "unsupported-binary", "source-location"
    if name.endswith(".tar"):
        return "application/octet-stream", "unsupported-binary", "source-location"
    if name.endswith((".zdt", ".zdx", ".czs", ".czv", ".czz")):
        return "application/octet-stream", "unsupported-binary", "source-location"
    if name.endswith(".tei"):
        return "application/xml", "xml-reader", "source-location"
    if name.endswith(".xml"):
        return "application/xml", "xml-reader", "source-location"
    return "text/plain", "exact-text", "source-location"


def _naves_zld_presentation_context(
    work_id: str,
    source_manifest: SourceManifest,
    source_artifacts: list[dict[str, Any]],
    roots: dict[str, Path],
    approved_roots: list[dict[str, str]],
    source_root_id: str,
) -> dict[str, Any] | None:
    """Bind the Nave review projection to its exact multi-member source packet."""

    record = source_manifest.record
    if work_id != "naves-topical-bible" or record.get("source_id") != "crosswire-nave-sword-v3":
        return None
    source_set = record.get("transformation_source_set")
    if not isinstance(source_set, Mapping):
        raise ReviewContractError("Nave transformation source set is missing")
    members = source_set.get("members")
    source_set_sha256 = source_set.get("sha256")
    if (
        source_set.get("contract") != "ocd-source-member-set-v1"
        or not isinstance(members, (list, tuple))
        or not isinstance(source_set_sha256, str)
        or not SHA256.fullmatch(source_set_sha256)
    ):
        raise ReviewContractError("Nave transformation source set is malformed")
    member_records = [dict(value) for value in members if isinstance(value, Mapping)]
    if len(member_records) != len(members):
        raise ReviewContractError("Nave transformation source members are malformed")
    canonical_source_set = {
        "contract": "ocd-source-member-set-v1",
        "members": sorted(
            member_records,
            key=lambda value: (str(value.get("path")), str(value.get("name"))),
        ),
    }
    if hashlib.sha256(_canonical_json_bytes(canonical_source_set)).hexdigest() != source_set_sha256:
        raise ReviewContractError("Nave transformation source-set digest drifted")
    expected_primary = sorted(
        (
            {
                "name": artifact["name"],
                "path": artifact["authority_path"],
                "bytes": artifact["bytes"],
                "sha256": artifact["sha256"],
            }
            for artifact in source_artifacts
        ),
        key=lambda value: (str(value["path"]), str(value["name"])),
    )
    if canonical_source_set["members"] != expected_primary or {
        value["name"] for value in expected_primary
    } != {"dict-zdt", "dict-zdx", "dict-dat", "dict-idx"}:
        raise ReviewContractError(
            "Nave primary authorities do not match the transformation source set"
        )

    presentation_members = [
        {
            "name": artifact["name"],
            "root": artifact["root"],
            "path": artifact["path"],
            "bytes": artifact["bytes"],
            "sha256": artifact["sha256"],
        }
        for artifact in source_artifacts
    ]
    authorities = record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ReviewContractError("Nave source authorities are malformed")
    by_name = {
        value.get("name"): value
        for value in authorities
        if isinstance(value, Mapping) and isinstance(value.get("name"), str)
    }
    for support_name, expected_role in (
        ("nave-conf", "source-support-metadata-rights"),
        ("nave-archive", "acquisition-container"),
    ):
        authority = by_name.get(support_name)
        if not isinstance(authority, Mapping) or authority.get("role") != expected_role:
            raise ReviewContractError(f"Nave {support_name} support authority is missing")
        support_path = source_manifest.authority_path(support_name)
        support_bytes = support_path.read_bytes()
        declared_bytes = authority.get("bytes")
        declared_sha256 = authority.get("sha256")
        if (
            declared_bytes != len(support_bytes)
            or declared_sha256 != hashlib.sha256(support_bytes).hexdigest()
        ):
            raise ReviewContractError(f"Nave {support_name} support authority drifted")
        root_id = f"{source_root_id}-presentation-{support_name}"
        roots[root_id] = support_path.parent.resolve(strict=True)
        approved_roots.append(
            {
                "id": root_id,
                "access": "read-only",
                "purpose": f"Nave zLD review support authority: {support_name}",
            }
        )
        presentation_members.append(
            {
                "name": support_name,
                "root": root_id,
                "path": support_path.name,
                "bytes": declared_bytes,
                "sha256": declared_sha256,
            }
        )
    context_record = {
        "source_set_sha256": source_set_sha256,
        "members": sorted(presentation_members, key=lambda value: value["name"]),
    }
    return {
        **context_record,
        "sha256": hashlib.sha256(_canonical_json_bytes(context_record)).hexdigest(),
    }


def _ajops_media(source_manifest, tei_bytes, work_id, roots, approved_roots, source_root_id):
    """Bind the reviewed PDF presentations without replacing original JATS graphics."""
    from lxml import etree

    authorities = source_manifest.record["authorities"]
    handoffs = [a for a in authorities if a.get("role") == "tei-media-handoff"]
    if not handoffs:
        return [], []
    if len(handoffs) != 1 or source_manifest.record["converter"]["id"] != "ocd-ajops-jats-article-to-tei":
        raise ReviewContractError("Unsupported TEI media handoff")
    handoff = handoffs[0]
    payload = io_path(source_manifest.authority_path(handoff["name"])).read_bytes()
    if len(payload) != handoff["bytes"] or hashlib.sha256(payload).hexdigest() != handoff["sha256"]:
        raise ReviewContractError("TEI media handoff drifted")
    try:
        record = json.loads(payload, object_pairs_hook=strict_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReviewContractError("Invalid AJOPS media handoff") from error
    figures = record.get("figures") if isinstance(record, dict) else None
    if not isinstance(figures, list) or not figures:
        raise ReviewContractError("AJOPS media figures are missing")
    tei = etree.fromstring(tei_bytes, etree.XMLParser(resolve_entities=False, no_network=True))
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    artifacts, presentations, seen = [], [], set()
    for figure in figures:
        if not isinstance(figure, dict):
            raise ReviewContractError("Invalid AJOPS media figure")
        article = _identity_text(figure.get("article"), "media article")
        graphic = _identity_text(figure.get("original_jats_graphic"), "JATS graphic")
        caption = _text(figure.get("caption"), "figure caption")
        matches = tei.xpath("//t:graphic[@url=$url]/ancestor::t:div[@type='jats:fig']", namespaces=ns, url=graphic)
        if work_id != f"ajops-v1-2024-{article}" or len(matches) != 1 or graphic in seen:
            raise ReviewContractError("AJOPS media work or graphic association mismatch")
        if " ".join(caption.split()) not in " ".join("".join(matches[0].itertext()).split()):
            raise ReviewContractError("AJOPS media caption mismatch")
        seen.add(graphic)
        asset = figure.get("display_asset")
        pdf = asset.get("source_pdf") if isinstance(asset, dict) else None
        if not isinstance(asset, dict) or not isinstance(pdf, dict):
            raise ReviewContractError("AJOPS media asset or PDF is missing")
        for record, role in ((asset, "review-image"), (pdf, "comparison-witness")):
            bound = [a for a in authorities if a.get("role") == role and all(a.get(k) == record.get(k) for k in ("path", "bytes", "sha256"))]
            if len(bound) != 1:
                raise ReviewContractError("AJOPS media asset or PDF authority mismatch")
        path = _contained(source_manifest.repository_root, asset["path"], graphic)
        image = io_path(path).read_bytes()
        if len(image) != asset["bytes"] or hashlib.sha256(image).hexdigest() != asset["sha256"]:
            raise ReviewContractError("AJOPS media image drifted")
        media_type, kind, location = _source_presentation(path)
        if kind != "image-facsimile":
            raise ReviewContractError("AJOPS media is not a supported image")
        root_id = f"{source_root_id}-figure-{len(artifacts) + 1}"
        roots[root_id] = path.parent.resolve(strict=True)
        approved_roots.append({"id": root_id, "access": "read-only", "purpose": "reviewed retained-PDF figure presentation"})
        artifact_id = f"figure-{source_manifest.sha256}-{len(artifacts) + 1}"
        artifacts.append(dict(id=artifact_id, version=asset["sha256"], sha256=asset["sha256"],
            name=f"Figure {figure['figure_number']} (retained PDF)", authority_path=asset["path"],
            bytes=asset["bytes"], root=root_id, path=path.name, media_type=media_type,
            presentation_kind=kind, location_kind=location, supplemental_figure=True))
        presentations.append(dict(artifact_id=artifact_id, artifact_version=asset["sha256"], sha256=asset["sha256"],
            caption=f"Figure {figure['figure_number']}. {caption}", qualification=_text(figure.get("qualification"), "media qualification")))
    graphics = tei.xpath("//t:div[@type='jats:fig']//t:graphic/@url", namespaces=ns)
    if sorted(graphics) != sorted(seen):
        raise ReviewContractError("AJOPS media handoff does not cover the article figures exactly")
    return artifacts, presentations


def _barnes_zcom_presentation_context(
    work_id: str,
    source_manifest: SourceManifest,
    source_artifacts: list[dict[str, Any]],
    roots: dict[str, Path],
    approved_roots: list[dict[str, str]],
    source_root_id: str,
) -> dict[str, Any] | None:
    """Bind the one retained Barnes zCom archive and its exact source members."""
    record = source_manifest.record
    if work_id != "barnes-nt-notes" or record.get("source_id") != "barnes-crosswire-sword-v1.1":
        return None
    if record.get("ticket_id") != "37c-066":
        raise ReviewContractError("Barnes zCom presentation ticket binding is invalid")
    if len(source_artifacts) != 1:
        raise ReviewContractError("Barnes zCom presentation requires its one retained archive")
    archive_artifact = source_artifacts[0]
    if (
        archive_artifact.get("name") != "retained-archive"
        or archive_artifact.get("authority_path") != "raw/sword_modules/Barnes.zip"
        or archive_artifact.get("sha256") != "9e8edc0333875c214124371b3862df118ad3a76ade7753cb2faeed3484615baf"
    ):
        raise ReviewContractError("Barnes zCom retained archive identity drifted")
    authorities = record.get("authorities")
    if not isinstance(authorities, (list, tuple)):
        raise ReviewContractError("Barnes zCom source authorities are malformed")
    by_name = {value.get("name"): value for value in authorities if isinstance(value, Mapping)}
    expected = {
        "retained-verse-index": ("retained-source-member", "raw/sword_modules/Barnes/modules/comments/zcom/barnes/nt.czv"),
        "retained-compressed-data": ("retained-source-member", "raw/sword_modules/Barnes/modules/comments/zcom/barnes/nt.czz"),
        "retained-block-index": ("retained-source-member", "raw/sword_modules/Barnes/modules/comments/zcom/barnes/nt.czs"),
        "retained-module-config": ("source-description", "raw/sword_modules/Barnes/mods.d/barnes.conf"),
    }
    archive_member = {
        "name": archive_artifact["name"],
        "root": archive_artifact["root"],
        "path": archive_artifact["path"],
        "bytes": archive_artifact["bytes"],
        "sha256": archive_artifact["sha256"],
    }
    presentation_members = [archive_member]
    for name, (role, expected_path) in expected.items():
        authority = by_name.get(name)
        if not isinstance(authority, Mapping) or authority.get("role") != role or authority.get("path") != expected_path:
            raise ReviewContractError(f"Barnes zCom declared source member is missing or misrouted: {name}")
        path = source_manifest.authority_path(name)
        payload = path.read_bytes()
        byte_count = authority.get("bytes")
        digest = authority.get("sha256")
        if not isinstance(byte_count, int) or byte_count != len(payload) or digest != hashlib.sha256(payload).hexdigest():
            raise ReviewContractError(f"Barnes zCom declared source member drifted: {name}")
        root_id = f"{source_root_id}-presentation-{name}"
        roots[root_id] = path.parent.resolve(strict=True)
        approved_roots.append({"id": root_id, "access": "read-only", "purpose": f"Barnes zCom review support authority: {name}"})
        context_name = {
            "retained-verse-index": "nt.czv",
            "retained-compressed-data": "nt.czz",
            "retained-block-index": "nt.czs",
            "retained-module-config": "barnes-conf",
        }[name]
        presentation_members.append({"name": context_name, "root": root_id, "path": path.name, "bytes": byte_count, "sha256": digest})
    context_record = {"source_set_sha256": source_manifest.sha256, "members": sorted(presentation_members, key=lambda value: value["name"])}
    return {**context_record, "sha256": hashlib.sha256(_canonical_json_bytes(context_record)).hexdigest()}


def _verified_context_payload(
    artifact: dict[str, Any], roots: Mapping[str, Path]
) -> tuple[dict[str, bytes], str]:
    context = artifact.get("presentation_context")
    if not isinstance(context, dict) or set(context) != {
        "source_set_sha256",
        "members",
        "sha256",
    }:
        raise ReviewContractError("context presentation binding is malformed")
    source_set_sha256 = context.get("source_set_sha256")
    context_sha256 = context.get("sha256")
    members = context.get("members")
    if (
        not isinstance(source_set_sha256, str)
        or not SHA256.fullmatch(source_set_sha256)
        or not isinstance(context_sha256, str)
        or not SHA256.fullmatch(context_sha256)
        or not isinstance(members, list)
        or any(not isinstance(value, dict) for value in members)
    ):
        raise ReviewContractError("context presentation identity is malformed")
    context_record = {
        "source_set_sha256": source_set_sha256,
        "members": members,
    }
    if hashlib.sha256(_canonical_json_bytes(context_record)).hexdigest() != context_sha256:
        raise ReviewContractError("context presentation identity drifted")

    payload: dict[str, bytes] = {}
    for member in members:
        if set(member) != {"name", "root", "path", "bytes", "sha256"}:
            raise ReviewContractError("context presentation member binding is malformed")
        name = _identity_text(member.get("name"), "context presentation member name")
        if name in payload:
            raise ReviewContractError("context presentation member name is duplicated")
        root_id = _text(member.get("root"), "context presentation member root")
        relative = Path(_text(member.get("path"), "context presentation member path"))
        byte_count = member.get("bytes")
        expected = _text(member.get("sha256"), "context presentation member sha256")
        if (
            not isinstance(byte_count, int)
            or isinstance(byte_count, bool)
            or byte_count < 0
            or not SHA256.fullmatch(expected)
        ):
            raise ReviewContractError("context presentation member identity is invalid")
        root = roots.get(root_id)
        if root is None:
            raise ReviewContractError("context presentation member uses an unapproved root")
        if relative.is_absolute() or ".." in relative.parts:
            raise ReviewContractError("context presentation member path escapes its root")
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ReviewContractError("context presentation member is missing or escapes its root")
        member_bytes = path.read_bytes()
        if len(member_bytes) != byte_count or hashlib.sha256(member_bytes).hexdigest() != expected:
            raise ReviewContractError(f"context presentation member bytes drifted: {name}")
        payload[name] = member_bytes
    selected_name = _identity_text(artifact.get("name"), "selected context artifact name")
    selected_sha256 = _text(artifact.get("sha256"), "selected context artifact sha256")
    if selected_name not in payload or hashlib.sha256(payload[selected_name]).hexdigest() != selected_sha256:
        raise ReviewContractError("selected artifact is not the bound context member")
    payload["__selected_name__"] = selected_name.encode("ascii")
    payload["__source_set_sha256__"] = source_set_sha256.encode("ascii")
    return payload, context_sha256


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _validation_authority_bindings(
    source_manifest: SourceManifest,
) -> dict[str, str]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, (list, tuple)):
        raise ReviewContractError("source manifest authorities are invalid")
    by_role: dict[str, list[Mapping[str, object]]] = {}
    for value in authorities:
        if not isinstance(value, Mapping) or not isinstance(value.get("role"), str):
            raise ReviewContractError("source manifest authority role is invalid")
        by_role.setdefault(str(value["role"]), []).append(value)

    sources = by_role.get("primary-source", [])
    if not sources:
        raise ReviewContractError("source manifest has no primary-source authority")
    source_records = sorted(
        (
            {
                "name": value.get("name"),
                "path": value.get("path"),
                "bytes": value.get("bytes"),
                "sha256": value.get("sha256"),
            }
            for value in sources
        ),
        key=lambda value: (str(value["path"]), str(value["name"])),
    )
    if len({value["path"] for value in source_records}) != len(source_records):
        raise ReviewContractError("primary-source authority paths are duplicated")
    if len(source_records) == 1:
        source_sha256 = source_records[0]["sha256"]
        if not isinstance(source_sha256, str) or not SHA256.fullmatch(source_sha256):
            raise ReviewContractError("primary-source authority digest is invalid")
    else:
        source_sha256 = hashlib.sha256(
            _canonical_json_bytes(
                {"contract": "ocd-source-member-set-v1", "members": source_records}
            )
        ).hexdigest()

    singleton_roles = {
        "profile_sha256": "complete-source-feature-profile",
        "package_schema_sha256": "candidate-package-schema",
        "xsd_sha256": "tei-validation-schema",
        "policy_sha256": "independent-validation-policy",
    }
    result = {"source_sha256": str(source_sha256)}
    for field, role in singleton_roles.items():
        matches = by_role.get(role, [])
        digest = matches[0].get("sha256") if len(matches) == 1 else None
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ReviewContractError(
                f"source manifest requires exactly one {role} authority"
            )
        result[field] = digest

    package_schema = source_manifest.record.get("package_schema")
    package_authority = by_role["candidate-package-schema"][0]
    expected_package_schema = {
        "path": package_authority.get("path"),
        "sha256": package_authority.get("sha256"),
    }
    if (
        not isinstance(package_schema, Mapping)
        or dict(package_schema) != expected_package_schema
    ):
        raise ReviewContractError(
            "candidate-package-schema authority binding mismatch"
        )
    return result


def _verify_candidate_authority_bindings(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
) -> None:
    """Independently bind producer claims in the candidate to source authority."""

    for field in ("converter", "package_schema"):
        source_value = source_manifest.record.get(field)
        candidate_value = candidate.manifest.get(field)
        if (
            not isinstance(source_value, Mapping)
            or not isinstance(candidate_value, Mapping)
            or dict(candidate_value) != dict(source_value)
        ):
            label = field.replace("_", "-")
            raise ReviewContractError(
                f"candidate manifest {label} authority binding mismatch"
            )


def _is_reparse_point(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(reparse_flag and attributes & reparse_flag)


def _validate_candidate_input_layout(candidate_dir: Path) -> tuple[Path, Path]:
    """Reject candidate indirection before any package member is read."""

    candidate_dir = Path(candidate_dir).resolve(strict=True)
    package_dir = candidate_dir / "package"
    sidecar = candidate_dir / "validation.json"
    try:
        observed = {path.name for path in candidate_dir.iterdir()}
        if observed not in ({"package", "validation.json"}, {"package", "validation.json", "text-quality.json"}):
            raise ReviewContractError(
                "candidate directory must contain only package/ and validation.json, with optional text-quality.json"
            )
        children = [
            (package_dir, "candidate package", True),
            (sidecar, "candidate validation report", False),
        ]
        if "text-quality.json" in observed:
            children.append((candidate_dir / "text-quality.json", "candidate text-quality report", False))
        for path, label, directory in children:
            if _is_reparse_point(path):
                raise ReviewContractError(f"{label} must not be a reparse point")
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(candidate_dir):
                raise ReviewContractError(f"{label} escapes the candidate directory")
            if directory and not resolved.is_dir():
                raise ReviewContractError(f"{label} is not a directory")
            if not directory and not resolved.is_file():
                raise ReviewContractError(f"{label} is not a file")
        resolved_package = package_dir.resolve(strict=True)
        for member in resolved_package.iterdir():
            if _is_reparse_point(member):
                raise ReviewContractError(
                    f"candidate package member must not be a reparse point: {member.name}"
                )
            resolved_member = member.resolve(strict=True)
            if not resolved_member.is_relative_to(resolved_package):
                raise ReviewContractError(
                    f"candidate package member escapes package/: {member.name}"
                )
    except ReviewContractError:
        raise
    except OSError as error:
        raise ReviewContractError(f"candidate directory is unreadable: {error}") from error
    return resolved_package, sidecar.resolve(strict=True)


def _load_validation_report(
    candidate_dir: Path,
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    *,
    verify_inputs: bool = True,
) -> ValidationReport:
    package_dir, sidecar = _validate_candidate_input_layout(candidate_dir)
    if not candidate.path.samefile(package_dir):
        raise ReviewContractError(
            "candidate directory must contain only package/ and validation.json"
        )
    try:
        content = sidecar.read_bytes()
        record = json.loads(content, object_pairs_hook=strict_json_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ReviewContractError(f"validation.json is unreadable: {error}") from error
    record = require_object(record, "validation report")
    required_report = {
        "contract",
        "status",
        "candidate_sha256",
        "source_manifest_sha256",
        "attestation",
        "findings",
        "report_sha256",
    }
    if set(record) not in (required_report, required_report | {"text_quality_sha256"}):
        raise ReviewContractError("validation report shape mismatch")
    if content != _canonical_json_bytes(record):
        raise ReviewContractError("validation.json is not canonical JSON")
    text_quality_sha256 = record.pop("text_quality_sha256", None)
    try:
        verify_text_quality(sidecar.with_name("text-quality.json"), text_quality_sha256, source_manifest, candidate)
    except (OSError, ValueError) as error:
        raise ReviewContractError(f"text-quality.json is invalid: {error}") from error
    report_sha256 = record.pop("report_sha256")
    if (
        not isinstance(report_sha256, str)
        or not SHA256.fullmatch(report_sha256)
        or hashlib.sha256(_canonical_json_bytes(record)).hexdigest() != report_sha256
    ):
        raise ReviewContractError("validation report digest mismatch")
    if record.get("contract") != "ocd-validation-report-v1":
        raise ReviewContractError("validation report contract mismatch")
    if record.get("status") != "pass":
        raise ReviewContractError("validation report status must be pass")
    candidate_sha256 = record.get("candidate_sha256")
    source_manifest_sha256 = record.get("source_manifest_sha256")
    if candidate_sha256 != candidate.sha256:
        raise ReviewContractError("validation report candidate binding mismatch")
    if source_manifest_sha256 != source_manifest.sha256:
        raise ReviewContractError("validation report source binding mismatch")

    attestation = require_object(record.get("attestation"), "oracle attestation")
    required_attestation = {
        "status",
        "oracle_id",
        "oracle_version",
        "implementation_sha256",
        "import_closure_sha256",
        "runtime",
        "source_manifest_sha256",
        "candidate_sha256",
        "profile_sha256",
        "package_schema_sha256",
        "source_sha256",
        "xsd_sha256",
        "policy_sha256",
        "result_sha256",
        "findings",
    }
    if set(attestation) != required_attestation:
        raise ReviewContractError("oracle attestation shape mismatch")
    if attestation.get("status") != "pass":
        raise ReviewContractError("oracle attestation status must be pass")
    if attestation.get("candidate_sha256") != candidate_sha256:
        raise ReviewContractError("oracle candidate binding mismatch")
    if attestation.get("source_manifest_sha256") != source_manifest_sha256:
        raise ReviewContractError("oracle source-manifest binding mismatch")

    validator = source_manifest.record.get("validator")
    if not isinstance(validator, Mapping):
        raise ReviewContractError("source manifest validator binding is invalid")
    if (
        attestation.get("oracle_id") != validator.get("id")
        or attestation.get("oracle_version") != validator.get("version")
    ):
        raise ReviewContractError("validator identity binding mismatch")
    if attestation.get("implementation_sha256") != validator.get(
        "implementation_sha256"
    ):
        raise ReviewContractError("validator implementation authority binding mismatch")
    if attestation.get("import_closure_sha256") != validator.get(
        "import_closure_sha256"
    ):
        raise ReviewContractError("validator import-closure authority binding mismatch")

    # ``from_work_catalog`` has already loaded and verified both immutable
    # handles before reading this sidecar.  It skips this second full pass so
    # one launch does not hash the same package and source authorities again;
    # direct callers retain the defensive default.
    if verify_inputs:
        candidate.verify_integrity()
        source_manifest.verify()
    _verify_candidate_authority_bindings(source_manifest, candidate)
    for field, expected in _validation_authority_bindings(source_manifest).items():
        if attestation.get(field) != expected:
            raise ReviewContractError(f"oracle {field} authority binding mismatch")
    findings = record.get("findings")
    if (
        not isinstance(findings, list)
        or any(not isinstance(value, str) for value in findings)
        or attestation.get("findings") != findings
    ):
        raise ReviewContractError("validation report findings binding mismatch")
    runtime = attestation.get("runtime")
    if not isinstance(runtime, str) or not runtime.strip():
        raise ReviewContractError("oracle runtime binding is invalid")
    for field in (
        "implementation_sha256",
        "import_closure_sha256",
        "profile_sha256",
        "package_schema_sha256",
        "source_sha256",
        "xsd_sha256",
        "policy_sha256",
        "result_sha256",
    ):
        digest = attestation.get(field)
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ReviewContractError(f"oracle {field} is invalid")
    result_record = {
        key: value for key, value in attestation.items() if key != "result_sha256"
    }
    if hashlib.sha256(_canonical_json_bytes(result_record)).hexdigest() != attestation.get(
        "result_sha256"
    ):
        raise ReviewContractError("oracle result binding mismatch")

    frozen_attestation = MappingProxyType(
        {**attestation, "findings": tuple(findings)}
    )
    return ValidationReport(
        "pass",
        str(candidate_sha256),
        str(source_manifest_sha256),
        frozen_attestation,
        tuple(findings),
        report_sha256,
    )



def _scoped_primary_authorities(
    work_id: str,
    authorities: list[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    """Select source-declared work scopes; candidate output cannot hide sources."""
    result: list[Mapping[str, object]] = []
    names: set[str] = set()
    for authority in authorities:
        name = _identity_text(authority.get("name"), "primary-source authority name")
        if name in names:
            raise ReviewContractError(f"duplicate primary-source authority name: {name}")
        names.add(name)
        if "work_ids" not in authority:
            result.append(authority)
            continue
        values = authority["work_ids"]
        if not isinstance(values, (tuple, list)) or not values:
            raise ReviewContractError("source authority work_ids must be a nonempty array")
        declared = [_identity_text(value, "source authority work_id") for value in values]
        if len(set(declared)) != len(declared):
            raise ReviewContractError("source authority work_ids are duplicated")
        if work_id in declared:
            result.append(authority)
    return result


def _materialize_candidate_binding(
    work_id: str,
    binding: Mapping[str, Any],
    roots: dict[str, Path],
    approved_roots: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], str]:
    """Materialize one already-validated candidate member for a work cohort."""

    review = binding["review"]
    candidate = binding["candidate"]
    validation = binding["validation"]
    route = binding["route"]
    source_root_id = f"source-{candidate.sha256}"
    candidate_root_id = f"candidate-{candidate.sha256}"
    roots[candidate_root_id] = candidate.path
    approved_roots.append(
        {
            "id": candidate_root_id,
            "access": "read-only",
            "purpose": "caller-selected validated TEI candidate",
        }
    )
    authorities = review.source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ReviewContractError("source manifest authorities are invalid")
    primary = [
        item
        for item in authorities
        if isinstance(item, Mapping) and item.get("role") == "primary-source"
    ]
    if not primary:
        raise ReviewContractError("source manifest has no primary-source authority")
    primary_count = len(primary)
    source_indexes = {
        _identity_text(authority.get("name"), "primary-source authority name"): index
        for index, authority in enumerate(primary, start=1)
    }
    primary = _scoped_primary_authorities(work_id, primary)
    if not primary:
        raise ReviewContractError(
            f"candidate has no primary-source authority scoped to WorkCatalog work {work_id}"
        )
    seen_primary_names: set[str] = set()
    source_artifacts: list[dict[str, Any]] = []
    for authority in primary:
        name = _identity_text(authority.get("name"), "primary-source authority name")
        source_index = source_indexes[name]
        if name in seen_primary_names:
            raise ReviewContractError(
                f"duplicate primary-source authority name: {name}"
            )
        seen_primary_names.add(name)
        authority_path = _catalog_route_path(
            authority.get("path"), "primary-source authority path"
        )
        # SourceManifest.verify() has already checked this authority record's
        # name, path containment, byte count, and digest.  Resolve the already
        # verified record path directly with the same owning containment helper
        # instead of rescanning the complete authority tuple by name.
        source_path = _contained(
            review.source_manifest.repository_root,
            authority.get("path"),
            name,
        )
        source_bytes = io_path(source_path).read_bytes()
        artifact_root_id = f"{source_root_id}-{source_index}"
        roots[artifact_root_id] = source_path.parent.resolve(strict=True)
        approved_roots.append(
            {
                "id": artifact_root_id,
                "access": "read-only",
                "purpose": f"current retained source authority: {name}",
            }
        )
        declared_bytes = authority.get("bytes")
        declared_sha256 = authority.get("sha256")
        if declared_bytes != len(source_bytes) or declared_sha256 != hashlib.sha256(source_bytes).hexdigest():
            raise ReviewContractError(f"primary-source authority bytes drifted: {name}")
        source_media, source_kind, source_location = _source_presentation(source_path)
        source_artifacts.append(
            {
                "id": (
                    f"source-{review.source_manifest.sha256}"
                    if primary_count == 1
                    else f"source-{review.source_manifest.sha256}-{source_index}"
                ),
                "version": (
                    review.source_manifest.sha256
                    if primary_count == 1
                    else declared_sha256
                ),
                "name": name,
                "authority_path": authority_path,
                "bytes": declared_bytes,
                "sha256": declared_sha256,
                "root": artifact_root_id,
                "path": source_path.name,
                "media_type": source_media,
                "presentation_kind": source_kind,
                "location_kind": source_location,
            }
        )
    selected_acquisitions = [
        authority
        for authority in review.source_manifest.record['authorities']
        if authority.get('role') == 'acquisition-selection-authority'
    ]
    selection = None
    selected_primary_members = None
    selected_member_set_binding = None
    if selected_acquisitions:
        if len(selected_acquisitions) != 1:
            raise ReviewContractError('selected review requires one acquisition authority')
        from ocd_kernel.library.acquisitions import validate_acquisition
        selected_acquisition = validate_acquisition(
            review.source_manifest.authority_path(selected_acquisitions[0]['name']),
            root=review.source_manifest.repository_root)
        selection = selected_acquisition.get('source_selection')
        source_path = selected_acquisition.get('source_path')
        if selected_acquisition.get('source_kind') == 'retained-member-set':
            selected_member_set_binding = (
                source_path,
                selected_acquisition.get('source_bytes'),
                selected_acquisition.get('source_sha256'),
            )
        if selection is None:
            # Historical WorkCatalog routes may omit sidecar paths. For a
            # source acquisition, source_path alone is not enough to prove
            # that this is the work's selected acquisition: another valid
            # acquisition may point at the same retained bytes.
            retained_files = selected_acquisition.get('retained_files')
            if not isinstance(retained_files, (tuple, list)) or not retained_files:
                raise ReviewContractError(
                    'selected acquisition retained_files must be a nonempty list'
                )
            retained_members = [
                (member.get('path'), member.get('bytes'), member.get('sha256'))
                for member in retained_files
                if isinstance(member, Mapping)
            ]
            if len(retained_members) != len(retained_files):
                raise ReviewContractError(
                    'selected acquisition retained member identity is invalid'
                )
            if (
                selected_acquisition.get('source_kind') == 'retained-member-set'
                or not isinstance(source_path, str)
            ):
                selected_primary_members = retained_members
            else:
                member_path = source_path.partition('#')[0]
                selected = [
                    member for member in retained_files
                    if member.get('path') == member_path
                ]
                if len(selected) > 1:
                    raise ReviewContractError(
                        'selected acquisition source member is duplicated'
                    )
                if selected:
                    member = selected[0]
                    if (
                        selected_acquisition.get('source_bytes') != member.get('bytes')
                        or selected_acquisition.get('source_sha256') != member.get('sha256')
                    ):
                        raise ReviewContractError(
                            'selected acquisition source identity differs from retained member'
                        )
                    selected_primary_members = [
                        (member.get('path'), member.get('bytes'), member.get('sha256'))
                    ]
                else:
                    selected_primary_members = retained_members
            if isinstance(source_path, str):
                manifest_record = review.source_manifest.record
                manifest_work_id = manifest_record.get('work_id')
                manifest_work_ids = manifest_record.get('work_ids')
                if (manifest_work_id is None) == (manifest_work_ids is None):
                    raise ReviewContractError(
                        'source manifest must declare exactly one work_id or work_ids'
                    )
                if manifest_work_id is not None:
                    declared_work_id = _identity_text(
                        manifest_work_id, 'source manifest work_id'
                    )
                    if declared_work_id != work_id:
                        raise ReviewContractError(
                            'selected source manifest work_id differs from route work'
                        )
                else:
                    if (not isinstance(manifest_work_ids, (tuple, list))
                            or not manifest_work_ids
                            or any(not isinstance(value, str) for value in manifest_work_ids)
                            or len(set(manifest_work_ids)) != len(manifest_work_ids)):
                        raise ReviewContractError(
                            'source manifest work_ids must be a nonempty unique list'
                        )
                    if work_id not in manifest_work_ids:
                        raise ReviewContractError(
                            'selected source manifest work_ids omit route work'
                        )
                for route_field in (
                    'work_identity_authority',
                    'acquisition_selection_authority',
                ):
                    if route.get(route_field) is None:
                        raise ReviewContractError(
                                'selected source route requires '
                            f'{route_field} binding'
                        )

    def verify_route_authority(role: str, route_field: str) -> None:
        expected_relative = route.get(route_field)
        if expected_relative is None:
            return
        expected_relative = _catalog_route_path(
            expected_relative, f"work route {route_field}"
        )
        matching = []
        for authority in review.source_manifest.record['authorities']:
            if not isinstance(authority, Mapping) or authority.get('role') != role:
                continue
            scoped = authority.get('work_ids')
            if scoped is not None:
                if (not isinstance(scoped, (tuple, list)) or not scoped
                        or any(not isinstance(value, str) for value in scoped)
                        or len(set(scoped)) != len(scoped)):
                    raise ReviewContractError(f"{role} work_ids are invalid")
                if work_id not in scoped:
                    continue
            matching.append(authority)
        if len(matching) != 1:
            raise ReviewContractError(
                f"selected review must bind exactly one {role} for {work_id}"
            )
        authority = matching[0]
        declared_relative = _catalog_route_path(
            authority.get('path'), f"{role} authority path"
        )
        if declared_relative != expected_relative:
            raise ReviewContractError(
                f"selected review {role} differs from the declared route"
            )
        authority_name = _identity_text(authority.get('name'), f"{role} authority name")
        # Resolve through the manifest's contained long-path-safe resolver.
        # Compare repository-relative identities so Windows extended-length
        # prefixes do not change the route's meaning.
        authority_path = review.source_manifest.authority_path(authority_name)
        if role == 'work-identity-config':
            canonical_work_path = f'library/works/{work_id}/work.json'
            if declared_relative != canonical_work_path:
                raise ReviewContractError(
                    'selected review work-identity authority is not the route work sidecar'
                )
            from ocd_kernel.library.identities import load_work
            selected_work = load_work(authority_path)
            if selected_work['work_id'] != work_id:
                raise ReviewContractError(
                    'selected review work-identity sidecar differs from route work'
                )
        elif role == 'acquisition-selection-authority':
            work_acquisition_prefix = f'library/works/{work_id}/forms/'
            if not declared_relative.startswith(work_acquisition_prefix):
                raise ReviewContractError(
                    'selected review acquisition authority belongs to a different route work'
                )

    if selected_member_set_binding is not None:
        member_set_path, member_set_bytes, member_set_sha256 = selected_member_set_binding
        member_set_authorities = [
            authority
            for authority in review.source_manifest.record['authorities']
            if isinstance(authority, Mapping)
            and authority.get('role') == 'retained-member-set'
        ]
        if len(member_set_authorities) != 1:
            raise ReviewContractError(
                'retained-member-set acquisition requires exactly one member-set authority'
            )
        member_set_authority = member_set_authorities[0]
        declared_member_set_path = _catalog_route_path(
            member_set_authority.get('path'), 'retained-member-set authority path'
        )
        if (
            declared_member_set_path != member_set_path
            or member_set_authority.get('bytes') != member_set_bytes
            or member_set_authority.get('sha256') != member_set_sha256
        ):
            raise ReviewContractError(
                'retained-member-set authority differs from selected acquisition'
            )

    verify_route_authority('work-identity-config', 'work_identity_authority')
    verify_route_authority(
        'acquisition-selection-authority', 'acquisition_selection_authority'
    )
    if selection is not None:
        if selection['work_id'] != work_id:
            raise ReviewContractError('selected review identity differs from acquisition')
        for artifact in source_artifacts:
            if artifact['authority_path'] != selection['member_path']:
                raise ReviewContractError('selected review source differs from acquisition')
            artifact['source_selection'] = selection
    elif selected_primary_members is not None:
        actual_primary_members = [
            (artifact['authority_path'], artifact['bytes'], artifact['sha256'])
            for artifact in source_artifacts
        ]
        if actual_primary_members != selected_primary_members:
            raise ReviewContractError(
                'selected review primary sources differ from acquisition'
            )

    from cvw_app.sword_members import declared_module_context
    module_context = declared_module_context(work_id, review.source_manifest, source_artifacts)
    if module_context is not None:
        for artifact in source_artifacts:
            artifact.update(media_type="application/octet-stream", presentation_kind="sword-members-reader",
                            location_kind="source-location", presentation_context=module_context)

    naves_context = _naves_zld_presentation_context(
        work_id,
        review.source_manifest,
        source_artifacts,
        roots,
        approved_roots,
        source_root_id,
    )
    if naves_context is not None:
        for artifact in source_artifacts:
            artifact.update(
                {
                    "media_type": "application/vnd.crosswire.sword-zld",
                    "presentation_kind": "sword-zld-reader",
                    "location_kind": "source-location",
                    "presentation_context": naves_context,
                }
            )
    barnes_context = _barnes_zcom_presentation_context(
        work_id,
        review.source_manifest,
        source_artifacts,
        roots,
        approved_roots,
        source_root_id,
    )
    if barnes_context is not None:
        for artifact in source_artifacts:
            artifact.update(
                {
                    "media_type": "application/vnd.crosswire.sword-zcom",
                    "presentation_kind": "barnes-zcom-reader",
                    "location_kind": "source-slot",
                    "presentation_context": barnes_context,
                }
            )
    tei_bytes = candidate.member_bytes("content.tei.xml")
    media_artifacts, media_presentations = _ajops_media(
        review.source_manifest, tei_bytes, work_id, roots, approved_roots, source_root_id)
    source_artifacts.extend(media_artifacts)
    tei_artifact = {
        "id": f"tei-{candidate.sha256}",
        "version": candidate.sha256,
        "sha256": hashlib.sha256(tei_bytes).hexdigest(),
        "name": "content.tei.xml",
        "authority_path": "package/content.tei.xml",
        "bytes": len(tei_bytes),
        "root": candidate_root_id,
        "path": "content.tei.xml",
        "media_type": "application/tei+xml",
        "presentation_kind": "tei-reader",
        "location_kind": "tei-anchor",
        "media_presentations": media_presentations,
    }
    validation_summary = {
        "status": "pass",
        "report_sha256": validation.sha256,
        "candidate_sha256": candidate.sha256,
        "source_manifest_sha256": review.source_manifest.sha256,
    }
    return (
        source_artifacts,
        tei_artifact,
        validation_summary,
        _text(route.get("scope"), "WorkCatalog route scope"),
    )


class ReviewApplication:
    def __init__(
        self,
        manifest: dict[str, Any],
        roots: dict[str, Path],
        registry: RendererRegistry,
        candidate_session_bindings: tuple[CandidateSessionBinding, ...] = (),
    ) -> None:
        self.manifest = manifest
        self.roots = roots
        self.registry = registry
        self._candidate_session_bindings = candidate_session_bindings
        self._cache = VerifiedIngestCache(max_entries=64)
        self._ingest_locks = [threading.Lock() for _ in range(64)]
        self._render_slots = threading.BoundedSemaphore(2)
        # The process-local manifest is the catalog authority for every
        # discovery page.  Bind all pages to one canonical digest so a late
        # page cannot silently come from a different manifest.
        self._catalog_version = hashlib.sha256(
            _canonical_json_bytes(manifest)
        ).hexdigest()

    def candidate_session_bindings(self) -> tuple[CandidateSessionBinding, ...]:
        """Return immutable per-candidate identity for the launcher handoff."""

        return self._candidate_session_bindings

    @classmethod
    def from_work_catalog(
        cls,
        catalog_path: Path,
        candidate_dirs: Iterable[Path],
        *,
        repository_root: Path | None = None,
        registry: RendererRegistry = DEFAULT_RENDERER_REGISTRY,
    ) -> "ReviewApplication":
        """Bind ordinary library records to caller-selected validated candidates.

        The generated manifest is process-local compatibility data for the current
        renderer surface.  It is never persisted and therefore does not become a
        second catalog or candidate store.
        """

        try:
            catalog = json.loads(
                Path(catalog_path).read_text(encoding="utf-8"),
                object_pairs_hook=strict_json_object,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise ReviewContractError(f"work catalog is unreadable: {error}") from error
        catalog = require_object(catalog, "work catalog")
        catalog_works = catalog.get("works")
        if not isinstance(catalog_works, list):
            raise ReviewContractError("work catalog works must be an array")

        return cls._from_library_records(catalog_works, candidate_dirs,
                                         repository_root=repository_root, registry=registry)

    @classmethod
    def from_declared_library(cls, repository_root: Path, candidate_dirs: Iterable[Path], *,
                              registry: RendererRegistry = DEFAULT_RENDERER_REGISTRY):
        """Associate explicit candidates with validated work/acquisition sidecars."""
        from cvw_app.library_admission import declared_candidate_records
        from ocd_kernel.library._common import PipelineError
        candidates = tuple(candidate_dirs)
        try:
            records = declared_candidate_records(repository_root, candidates)
        except (PipelineError, OSError, ValueError) as error:
            raise ReviewContractError(f"declared library admission failed: {error}") from error
        return cls._from_library_records(records, candidates,
                                         repository_root=repository_root, registry=registry)

    @classmethod
    def _from_library_records(cls, catalog_works, candidate_dirs, *, repository_root=None,
                               registry=DEFAULT_RENDERER_REGISTRY):
        """Common renderer binding; inputs are transient, never lifecycle authority."""

        repo = (
            Path(repository_root).resolve(strict=True)
            if repository_root is not None
            else Path(__file__).resolve().parent.parent
        )
        works_by_id: dict[str, dict[str, Any]] = {}
        routes: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = {}
        for index, value in enumerate(catalog_works):
            record = require_object(value, f"work catalog works[{index}]")
            work_id = _governed_bounded_text(
                record.get("work_id"), "work catalog work_id", MAX_WORK_SLUG_SCALARS
            )
            if work_id in works_by_id:
                raise ReviewContractError(f"work catalog work_id is duplicated: {work_id}")
            works_by_id[work_id] = record
            state = require_object(
                record.get("reconstruction_state"),
                f"work catalog {work_id} reconstruction_state",
            )
            route_values = state.get("routes", [])
            if not isinstance(route_values, list):
                raise ReviewContractError(
                    f"work catalog {work_id} reconstruction routes must be an array"
                )
            for route_index, route_value in enumerate(route_values):
                route = require_object(
                    route_value,
                    f"work catalog {work_id} route[{route_index}]",
                )
                source_id = _identity_text(
                    route.get("source_id"),
                    f"work catalog {work_id} route source_id",
                )
                manifest_path = _catalog_route_path(
                    route.get("manifest"),
                    f"work catalog {work_id} route manifest",
                )
                routes.setdefault((source_id, manifest_path), []).append((work_id, route))

        candidate_paths: list[Path] = []
        seen_paths: set[Path] = set()
        for index, value in enumerate(candidate_dirs):
            try:
                path = Path(value).resolve(strict=True)
            except OSError as error:
                raise ReviewContractError(
                    f"candidate directory {index + 1} is unavailable: {error}"
                ) from error
            if not path.is_dir():
                raise ReviewContractError(f"candidate directory {index + 1} is not a directory")
            if path in seen_paths:
                raise ReviewContractError("candidate directory is duplicated")
            seen_paths.add(path)
            candidate_paths.append(path)
        if not candidate_paths:
            raise ReviewContractError("at least one candidate directory is required")

        candidate_bindings: dict[str, list[dict[str, Any]]] = {}
        candidate_session_bindings: list[CandidateSessionBinding] = []
        seen_candidate_digests: set[str] = set()
        seen_candidate_routes: set[tuple[str, str]] = set()
        for index, candidate_path in enumerate(candidate_paths, start=1):
            try:
                _validate_candidate_input_layout(candidate_path)
                candidate = CandidatePackage.load(candidate_path / "package")
                if candidate.sha256 in seen_candidate_digests:
                    raise ReviewContractError("candidate manifest digest is duplicated")
                seen_candidate_digests.add(candidate.sha256)
                source_id = _identity_text(
                    candidate.manifest.get("source_id"),
                    f"candidate {index} source_id",
                )
                source_binding = require_object(
                    candidate.manifest.get("source_manifest"),
                    f"candidate {index} source_manifest",
                )
                if set(source_binding) != {"path", "sha256"}:
                    raise ReviewContractError(
                        f"candidate {index} source_manifest binding must contain path and sha256"
                    )
                source_relative = _catalog_route_path(
                    source_binding.get("path"),
                    f"candidate {index} source_manifest path",
                )
                source_path = (repo / source_relative).resolve(strict=True)
                try:
                    source_path.relative_to(repo)
                except ValueError as error:
                    raise ReviewContractError(
                        f"candidate {index} source manifest escapes the repository"
                    ) from error
                source_manifest = SourceManifest.load(source_path, repository_root=repo)
                if source_manifest.sha256 != source_binding.get("sha256"):
                    raise ReviewContractError(
                        f"candidate {index} source-manifest digest does not match current bytes"
                    )
                if source_manifest.record.get("source_id") != source_id:
                    raise ReviewContractError(
                        f"candidate {index} source_id does not match its source manifest"
                    )
                route_matches = routes.get((source_id, source_relative), [])
                if not route_matches:
                    raise ReviewContractError(
                        f"candidate {index} does not resolve to a WorkCatalog route"
                    )
                matched_work_ids: set[str] = set()
                duplicate_work_id: str | None = None
                for work_id, _ in route_matches:
                    if work_id in matched_work_ids:
                        duplicate_work_id = work_id
                        break
                    matched_work_ids.add(work_id)
                if duplicate_work_id is not None:
                    raise ReviewContractError(
                        "candidate route cohort contains duplicate routes for "
                        f"WorkCatalog work {duplicate_work_id}"
                    )
                duplicate_route: tuple[str, str] | None = None
                for work_id, _ in route_matches:
                    route_key = (work_id, source_relative)
                    if route_key in seen_candidate_routes:
                        duplicate_route = route_key
                        break
                if duplicate_route is not None:
                    raise ReviewContractError(
                        "multiple candidate directories resolve to the same "
                        "WorkCatalog route "
                        f"{duplicate_route[0]} ({duplicate_route[1]})"
                    )
                validation = _load_validation_report(
                    candidate_path,
                    source_manifest,
                    candidate,
                    verify_inputs=False,
                )
                review = ReviewView(
                    source_manifest,
                    candidate,
                    validation,
                    candidate.sha256,
                    candidate.member_names,
                )
            except (ReviewContractError, OSError, UnicodeDecodeError, ValueError) as error:
                raise ReviewContractError(
                    f"candidate directory {index} ({candidate_path}) is invalid: {error}"
                ) from error
            candidate_session_bindings.append(
                CandidateSessionBinding(
                    path=candidate_path,
                    work_ids=tuple(work_id for work_id, _ in route_matches),
                    source_id=source_id,
                    source_manifest_path=source_relative,
                    source_manifest_sha256=source_manifest.sha256,
                    candidate_sha256=candidate.sha256,
                    validation_report_sha256=validation.sha256,
                    validation_status=validation.status,
                )
            )
            for work_id, route in route_matches:
                seen_candidate_routes.add((work_id, source_relative))
                candidate_bindings.setdefault(work_id, []).append(
                    {
                        "candidate": candidate,
                        "route": route,
                        "review": review,
                        "validation": validation,
                    }
                )

        roots: dict[str, Path] = {}
        approved_roots: list[dict[str, str]] = []
        works: list[dict[str, Any]] = []
        for work_id, record in works_by_id.items():
            require_object(
                record.get("reconstruction_state"),
                f"work catalog {work_id} reconstruction_state",
            )
            title = _governed_bounded_text(
                record.get("title"), "work catalog title", MAX_WORK_TITLE_SCALARS
            )
            author = record.get("author")
            creator = (
                "Creator not recorded"
                if author is None
                else _governed_bounded_text(
                    author, "work catalog author", MAX_WORK_CREATOR_SCALARS
                )
            )
            category = record.get("category_label") or record.get("category")
            scope = _text(category, "work catalog category")
            stages: dict[str, dict[str, Any]] = {
                stage_id: {"artifacts": []} for stage_id in STAGE_ORDER
            }
            bindings = candidate_bindings.get(work_id, [])
            validation_summary = None
            candidate_validations: list[dict[str, Any]] = []
            if bindings:
                source_artifacts: list[dict[str, Any]] = []
                tei_artifacts: list[dict[str, Any]] = []
                route_scopes: list[str] = []
                for binding in bindings:
                    member_sources, member_tei, member_validation, member_scope = (
                        _materialize_candidate_binding(
                            work_id, binding, roots, approved_roots
                        )
                    )
                    for member_source in member_sources:
                        member_source["candidate_validation_tei_artifact_id"] = (
                            member_tei["id"]
                        )
                    source_artifacts.extend(member_sources)
                    tei_artifacts.append(member_tei)
                    route_scopes.append(member_scope)
                    candidate_validations.append(
                        {
                            **member_validation,
                            "source_id": binding["review"].source_manifest.record.get(
                                "source_id"
                            ),
                            "source_artifact_ids": [
                                artifact["id"] for artifact in member_sources
                            ],
                            "tei_artifact_id": member_tei["id"],
                        }
                    )
                primary_artifacts = [artifact for artifact in source_artifacts if not artifact.get("supplemental_figure")]
                stages["source"] = {
                    "selected_artifact_id": (
                        primary_artifacts[0]["id"] if len(primary_artifacts) == 1 else None
                    ),
                    "artifacts": source_artifacts,
                }
                stages["tei"] = {
                    # A multi-member cohort gets a deterministic first member
                    # while the frontend exposes every explicit identity.
                    "selected_artifact_id": tei_artifacts[0]["id"],
                    "artifacts": tei_artifacts,
                }
                scope = (
                    "partial"
                    if "partial" in route_scopes
                    else route_scopes[0]
                )
                if len(candidate_validations) == 1:
                    validation_summary = {
                        key: candidate_validations[0][key]
                        for key in (
                            "status",
                            "report_sha256",
                            "candidate_sha256",
                            "source_manifest_sha256",
                        )
                    }
            work_manifest = {
                "slug": work_id,
                "title": title,
                "creator": creator,
                "scope": scope,
                "candidate_validation": validation_summary,
                "default_compare": {
                    "left_stage": "source",
                    "right_stage": "tei",
                    "linked": False,
                    "correspondence": "absent",
                },
                "correspondence_sources": [],
                "stages": stages,
            }
            if candidate_validations:
                work_manifest["candidate_validations"] = candidate_validations
            works.append(work_manifest)
        manifest = {
            "contract": MANIFEST_CONTRACT,
            "approved_roots": approved_roots,
            "works": works,
            "input_contract": "work-catalog-plus-candidate-directories-v1",
        }
        return cls(manifest, roots, registry, tuple(candidate_session_bindings))

    def _work(self, slug: str) -> dict[str, Any]:
        works = self.manifest.get("works")
        if not isinstance(works, list):
            raise ReviewContractError("works must be an array")
        matches = [item for item in works if isinstance(item, dict) and item.get("slug") == slug]
        if len(matches) != 1:
            raise ReviewContractError(f"unknown work: {slug}")
        return matches[0]

    def work_summary(self, slug: str) -> dict[str, str]:
        """Return the validated public identity of one governed work."""
        work = self._work(slug)
        return {
            "slug": _governed_bounded_text(work.get("slug"), "work.slug", MAX_WORK_SLUG_SCALARS),
            "title": _governed_bounded_text(work.get("title"), "work.title", MAX_WORK_TITLE_SCALARS),
            "creator": _governed_bounded_text(work.get("creator"), "work.creator", MAX_WORK_CREATOR_SCALARS),
        }

    @property
    def catalog_version(self) -> str:
        return self._catalog_version

    def _validate_catalog_version(self, catalog_version: str | None) -> None:
        if hashlib.sha256(_canonical_json_bytes(self.manifest)).hexdigest() != self._catalog_version:
            raise RouteStaleError("The catalog manifest changed after admission; relaunch is required")
        if catalog_version is None:
            return
        if not SHA256.fullmatch(catalog_version):
            raise RouteStaleError(
                "catalog_version must be a lowercase SHA-256 digest"
            )
        if catalog_version != self._catalog_version:
            raise RouteStaleError(
                "catalog_version does not match the current manifest"
            )

    @staticmethod
    def _page_bounds(offset: int, limit: int, label: str) -> tuple[int, int]:
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or offset < 0
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < 1
            or limit > MAX_CATALOG_PAGE_SIZE
        ):
            raise RangeInvalidError(
                f"{label} offset must be nonnegative and limit must be between 1 and {MAX_CATALOG_PAGE_SIZE}"
            )
        return offset, limit

    def _correspondence_sources(
        self,
        work: dict[str, Any],
        *,
        include_mappings: bool = True,
    ) -> list[dict[str, Any]]:
        values = work.get("correspondence_sources", [])
        if not isinstance(values, list):
            raise ReviewContractError("work.correspondence_sources must be an array")
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        expected = {"contract", "id", "state", "left_stage", "left_artifact_id", "left_artifact_version", "right_stage", "right_artifact_id", "right_artifact_version", "mappings", "message"}
        for index, value in enumerate(values):
            source = require_object(value, f"work.correspondence_sources[{index}]")
            if set(source) != expected:
                raise ReviewContractError("correspondence source fields must match the v1 contract exactly")
            if source["contract"] != CORRESPONDENCE_CONTRACT:
                raise ReviewContractError(f"correspondence source contract must be {CORRESPONDENCE_CONTRACT}")
            source_id = _identity_text(source["id"], "correspondence source id")
            if source_id == "absent":
                raise ReviewContractError("correspondence source id 'absent' is reserved for the route sentinel")
            if source_id in seen:
                raise ReviewContractError(f"correspondence source id is duplicated: {source_id}")
            seen.add(source_id)
            source_state = governed_enum_text(
                source["state"], {"known", "uncertain"},
                "named correspondence source state", "must be known or uncertain",
            )
            left_stage = governed_enum_text(
                source["left_stage"], STAGE_ORDER, "correspondence source left_stage", "must be a known stage"
            )
            right_stage = governed_enum_text(
                source["right_stage"], STAGE_ORDER, "correspondence source right_stage", "must be a known stage"
            )
            for field in ("left_artifact_id", "left_artifact_version", "right_artifact_id", "right_artifact_version"):
                _identity_text(source[field], f"correspondence source {field}")
            _text(source["message"], "correspondence source message")
            mappings = source["mappings"]
            if not isinstance(mappings, list):
                raise ReviewContractError("correspondence source mappings must be an array")
            normalized: list[dict[str, str]] = []
            left_locations: set[str] = set()
            right_locations: set[str] = set()
            for mapping_index, mapping_value in enumerate(mappings):
                mapping = require_object(mapping_value, f"correspondence source mappings[{mapping_index}]")
                if set(mapping) != {"left_location", "right_location"}:
                    raise ReviewContractError("correspondence mapping fields must match the v1 contract exactly")
                left_location = _text(mapping["left_location"], "correspondence mapping left_location")
                right_location = _text(mapping["right_location"], "correspondence mapping right_location")
                if len(left_location) > 512 or len(right_location) > 512:
                    raise ReviewContractError("correspondence mapping locations must be bounded")
                if left_location in left_locations or right_location in right_locations:
                    raise ReviewContractError("known correspondence mappings must be one-to-one")
                left_locations.add(left_location)
                right_locations.add(right_location)
                if include_mappings:
                    normalized.append({"left_location": left_location, "right_location": right_location})
            if source_state == "known" and not mappings:
                raise ReviewContractError("known correspondence source must contain mappings")
            if source_state == "uncertain" and mappings:
                raise ReviewContractError("uncertain correspondence source must not contain target mappings")
            source_payload = {
                **source, "state": source_state, "left_stage": left_stage, "right_stage": right_stage,
                "mappings": normalized if include_mappings else [],
            }
            if not include_mappings:
                source_payload["mapping_count"] = len(mappings)
                source_payload["mapping_discovery"] = {
                    "total": len(mappings),
                    "route": "/api/review/v1/works/{slug}/correspondence",
                    "correspondence_source": source_id,
                    "complete": False,
                }
            sources.append(source_payload)
        return sources

    def _resolve(self, work, stage_id, requested_identity=None, *, image_sha256=None):
        key = (work.get("slug"), stage_id, requested_identity, image_sha256)
        with self._ingest_locks[hash(key) % len(self._ingest_locks)]:
            return self._resolve_selected(work, stage_id, requested_identity, image_sha256=image_sha256)

    def _resolve_selected(
        self,
        work: dict[str, Any],
        stage_id: str,
        requested_identity: tuple[str, str] | None = None,
        *,
        image_sha256: str | None = None,
    ) -> StageResolution:
        stages = require_object(work.get("stages"), "work.stages")
        stage = require_object(stages.get(stage_id, {}), f"stage {stage_id}")
        values = stage.get("artifacts", [])
        if not isinstance(values, list):
            return StageResolution("unsupported", "Artifact declarations are malformed.")
        if any(not isinstance(item, dict) for item in values):
            return StageResolution(
                "unsupported",
                "Artifact declarations are malformed; every artifact must be an object.",
            )
        artifacts = values
        if not artifacts:
            return StageResolution("unavailable", "No artifact is declared for this stage.")
        if requested_identity is None:
            selected_id = stage.get("selected_artifact_id")
            selected = [item for item in artifacts if item.get("id") == selected_id]
        else:
            selected = [
                item
                for item in artifacts
                if (item.get("id"), item.get("version")) == requested_identity
            ]
        if len(selected) != 1:
            if requested_identity is not None:
                return StageResolution(
                    "unsupported",
                    "The requested artifact identity is not a current declared authority member.",
                )
            message = "Choose a retained source. Multiple manifest-bound authorities are available; the viewer will not guess."
            return StageResolution("selection-required", message)
        artifact = selected[0]
        try:
            artifact_id = _identity_text(artifact.get("id"), "artifact.id")
            version = _identity_text(artifact.get("version"), "artifact.version")
            root_id = _text(artifact.get("root"), "artifact.root")
            relative = Path(_text(artifact.get("path"), "artifact.path"))
            expected = _text(artifact.get("sha256"), "artifact.sha256")
            media_type = _governed_bounded_text(artifact.get("media_type"), "artifact.media_type", MAX_MEDIA_TYPE_SCALARS)
            declared_kind = _text(artifact.get("presentation_kind"), "artifact.presentation_kind")
            location_kind = _governed_bounded_text(artifact.get("location_kind"), "artifact.location_kind", MAX_LOCATION_KIND_SCALARS)
            if not SHA256.fullmatch(expected):
                raise ReviewContractError("artifact.sha256 must be lowercase SHA-256")
            root = self.roots.get(root_id)
            if root is None:
                raise ReviewContractError("artifact uses an unapproved root")
            if relative.is_absolute() or ".." in relative.parts:
                raise ReviewContractError("artifact path escapes its approved root")
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ReviewContractError("artifact path escapes its approved root")
            if not path.is_file():
                raise ReviewContractError("artifact is missing")
            verified_image_payload = None
            request_image_info = None
            if image_sha256 is not None:
                if expected != image_sha256:
                    raise ReviewContractError("expected image sha256 does not match the admitted artifact")
                if declared_kind != "image-facsimile" or media_type not in MEDIA_FORMATS:
                    raise NativeImageError("image-unsupported", "Previews support only admitted PNG, JPEG, and WebP images.")
                # A cache hit never validates mutable current bytes. Read once
                # within the compressed budget, hash, then reuse this exact buffer.
                with path.open("rb") as stream:
                    verified_image_payload = stream.read(MAX_INPUT_BYTES + 1)
                check_input_size(len(verified_image_payload))
                if hashlib.sha256(verified_image_payload).hexdigest() != expected:
                    raise ReviewContractError("artifact bytes no longer match the declared sha256")
                request_image_info = inspect_image(verified_image_payload, media_type)
            cache_key = ingest_cache_key(root_id, relative, expected, declared_kind, media_type)
            context_payload = None
            if declared_kind in CONTEXT_PRESENTATION_KINDS:
                context_payload, context_sha256 = _verified_context_payload(
                    artifact, self.roots
                )
                cache_key = (*cache_key, context_sha256)
            selection = artifact.get('source_selection')
            if selection is not None:
                cache_key = (*cache_key, hashlib.sha256(json.dumps(selection, sort_keys=True).encode('utf-8')).hexdigest())
            cached = self._cache.get(cache_key)
            if cached is not None:
                rendered, supported, exact_text_available = cached
                # The exact route always re-reads and re-verifies the bound
                # artifact bytes.  Keep only its availability in the ingest
                # cache rather than retaining a second full text copy beside
                # the rendered node graph.
                exact = "" if exact_text_available else None
                cache_resident = True
            else:
                with self._render_slots:
                    cacheable = True
                    payload = verified_image_payload if verified_image_payload is not None else path.read_bytes()
                    if hashlib.sha256(payload).hexdigest() != expected:
                        raise ReviewContractError("artifact bytes do not match declared sha256")
                    if declared_kind in CONTEXT_PRESENTATION_KINDS:
                        if context_payload is None:
                            raise ReviewContractError(
                                "context presentation payload was not verified"
                            )
                        exact = None
                        rendered, supported = self.registry.render(
                            declared_kind, media_type, context_payload
                        )
                    elif declared_kind in BINARY_PRESENTATION_KINDS:
                        # Binary families keep raw verified bytes (C6/r2 signature check included);
                        # there is no exact text representation to decode.
                        verify_binary_content_signature(media_type, payload)
                        exact = None
                        rendered, supported = self.registry.render(declared_kind, media_type, payload)
                        rendered["_original_dimensions"] = _original_image_dimensions(media_type, payload)
                        if declared_kind == "image-facsimile":
                            try:
                                if request_image_info is not None:
                                    rendered["_native_image"] = request_image_info
                                else:
                                    with image_work():
                                        rendered["_native_image"] = inspect_image(payload, media_type)
                            except NativeImageError as error:
                                rendered["_native_image"] = {"error": {"code": error.code, "message": str(error)}}
                                # Capacity is request-local, not a property of these bytes.
                                # A retry must inspect again once a work slot is available.
                                cacheable = error.code != "image-busy"
                    else:
                        from cvw_app.text_decoding import decode_text
                        exact, text_encoding = decode_text(payload, media_type)
                        from cvw_app.selected_reading import selected_reader_input
                        reader_input = selected_reader_input(exact, declared_kind, selection)
                        rendered, supported = self.registry.render(declared_kind, media_type, reader_input)
                        rendered["_text_encoding"] = text_encoding
                    exact_text_available = exact is not None
                    if cacheable:
                        rendered = compact_projection(rendered)
                        self._cache.admit(
                            cache_key,
                            (rendered, supported, exact_text_available),
                        )
                    # No response embeds the exact text.  The boolean is enough to
                    # publish the identity-bound /exact fallback; that endpoint
                    # deliberately reads and verifies the file again.
                    exact = "" if exact_text_available else None
                    cache_resident = False
        except (OSError, UnicodeDecodeError, ReviewContractError, RendererError) as error:
            return StageResolution("unsupported", f"Selected artifact cannot be opened: {error}")
        public_artifact = {"id": artifact_id, "version": version, "sha256": expected, "media_type": media_type}
        presentation = {
            "declared_kind": declared_kind,
            "kind": rendered["kind"],
            "render_target": "in-browser",
            "text_encoding": rendered.get("_text_encoding"),
            "freshness": "admitted-snapshot" if cache_resident else "verified-this-request",
            "limitations": rendered.get("limitations", []),
            "document": {"nodes": rendered["nodes"]},
        }
        if artifact.get("media_presentations"):
            presentation["media_presentations"] = artifact["media_presentations"]
        if declared_kind == "image-facsimile":
            presentation["original_dimensions"] = rendered.get("_original_dimensions")
            presentation["native_image"] = rendered.get("_native_image")
            image_info = presentation["native_image"] or {}
            if presentation["original_dimensions"] is None:
                presentation["original_dimensions"] = image_info.get("original_dimensions")
        return StageResolution(
            "available" if supported else "unsupported",
            "Selected and byte-verified from an operator-approved read-only root."
            if supported
            else (
                "The selected format has no in-browser presentation; exact byte access remains available."
                if declared_kind in BINARY_PRESENTATION_KINDS
                else "The selected format has no rich presentation; exact inert text is shown."
            ),
            public_artifact,
            exact,
            {**presentation, "outline": rendered["outline"], "contexts": rendered["contexts"], "location_kind": location_kind},
            rendered=rendered,
            cache_resident=cache_resident,
            readable=True,
            path=path,
            verified_image_payload=verified_image_payload,
        )

    def _selected_manifest_identity(self, work: dict[str, Any], stage_id: str) -> tuple[str, str] | None:
        """Return the selected declaration identity without depending on readable artifact bytes."""
        stages = require_object(work.get("stages"), "work.stages")
        stage = require_object(stages.get(stage_id, {}), f"stage {stage_id}")
        values = stage.get("artifacts", [])
        if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
            raise ReviewContractError(f"stage {stage_id} artifact declarations cannot establish one selected identity")
        if not values:
            return None
        selected_id = stage.get("selected_artifact_id")
        selected = [item for item in values if item.get("id") == selected_id]
        if len(selected) != 1:
            raise ReviewContractError(f"stage {stage_id} artifact declarations cannot establish one selected identity")
        return (
            _identity_text(selected[0].get("id"), f"stage {stage_id} selected artifact id"),
            _identity_text(selected[0].get("version"), f"stage {stage_id} selected artifact version"),
        )

    def recorded_identity_is_current(self, slug: str, stage_id: str, recorded: RecordedContext) -> bool:
        """Establish current identity from any declared authority member, not readable bytes or location state."""
        return self._manifest_identity_is_current(
            self._work(slug), stage_id, (recorded.artifact_id, recorded.version)
        )

    def _manifest_identity_is_current(
        self,
        work: dict[str, Any],
        stage_id: str,
        identity: tuple[str, str],
    ) -> bool:
        stages = require_object(work.get("stages"), "work.stages")
        stage = require_object(stages.get(stage_id, {}), f"stage {stage_id}")
        values = stage.get("artifacts", [])
        if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
            raise ReviewContractError(
                f"stage {stage_id} artifact declarations cannot establish current identities"
            )
        return sum(
            (item.get("id"), item.get("version")) == identity for item in values
        ) == 1

    @staticmethod
    def _artifact_summary(artifact: dict[str, Any]) -> dict[str, Any]:
        byte_count = artifact.get("bytes")
        if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
            raise ReviewContractError("artifact.bytes must be a nonnegative integer")
        digest = _text(artifact.get("sha256"), "artifact.sha256")
        if not SHA256.fullmatch(digest):
            raise ReviewContractError("artifact.sha256 must be lowercase SHA-256")
        return {
            "id": _identity_text(artifact.get("id"), "artifact.id"),
            "version": _identity_text(artifact.get("version"), "artifact.version"),
            "name": _identity_text(artifact.get("name"), "artifact.name"),
            "path": _catalog_route_path(artifact.get("authority_path"), "artifact authority path"),
            "bytes": byte_count,
            "sha256": digest,
            "media_type": _governed_bounded_text(
                artifact.get("media_type"), "artifact.media_type", MAX_MEDIA_TYPE_SCALARS
            ),
        }

    def _validate_selected_manifest_persisted_bounds(self, work: dict[str, Any], stage_id: str) -> None:
        stages = work.get("stages")
        if not isinstance(stages, dict):
            return
        stage = stages.get(stage_id, {})
        if not isinstance(stage, dict):
            return
        values = stage.get("artifacts", [])
        if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
            return
        selected = [item for item in values if item.get("id") == stage.get("selected_artifact_id")]
        if len(selected) == 1:
            _identity_text(selected[0].get("id"), f"stage {stage_id} selected artifact id")
            _identity_text(selected[0].get("version"), f"stage {stage_id} selected artifact version")
            _governed_bounded_text(selected[0].get("media_type"), "artifact.media_type", MAX_MEDIA_TYPE_SCALARS)
            _governed_bounded_text(selected[0].get("location_kind"), "artifact.location_kind", MAX_LOCATION_KIND_SCALARS)

    def catalog(self) -> dict[str, Any]:
        self._validate_catalog_version(None)
        works_value = self.manifest.get("works")
        if not isinstance(works_value, list):
            raise ReviewContractError("works must be an array")
        compact_work_catalog = (
            self.manifest.get("input_contract")
            == "work-catalog-plus-candidate-directories-v1"
        )
        works = []
        for index, value in enumerate(works_value):
            work = require_object(value, f"works[{index}]")
            summary = {
                "slug": _governed_bounded_text(work.get("slug"), "work.slug", MAX_WORK_SLUG_SCALARS),
                "title": _governed_bounded_text(work.get("title"), "work.title", MAX_WORK_TITLE_SCALARS),
                "creator": _governed_bounded_text(work.get("creator"), "work.creator", MAX_WORK_CREATOR_SCALARS),
            }
            stages = []
            for stage_id in STAGE_ORDER:
                self._validate_selected_manifest_persisted_bounds(work, stage_id)
                stage_record = require_object(
                    require_object(work.get("stages"), "work.stages").get(stage_id),
                    f"stage {stage_id}",
                )
                artifact_values = stage_record.get("artifacts", [])
                if not isinstance(artifact_values, list) or any(
                    not isinstance(item, dict) for item in artifact_values
                ):
                    raise ReviewContractError(
                        f"stage {stage_id} artifact declarations are malformed"
                    )
                if compact_work_catalog:
                    selected_values = [
                        item
                        for item in artifact_values
                        if item.get("id") == stage_record.get("selected_artifact_id")
                    ]
                    if not artifact_values:
                        availability = "unavailable"
                        message = "No artifact is declared for this stage."
                        selected = None
                    elif len(selected_values) == 1:
                        selected = {
                            "id": _identity_text(
                                selected_values[0].get("id"), "artifact.id"
                            ),
                            "version": _identity_text(
                                selected_values[0].get("version"), "artifact.version"
                            ),
                        }
                        presentation_kind = _identity_text(
                            selected_values[0].get("presentation_kind"),
                            "artifact.presentation_kind",
                        )
                        media_type = _governed_bounded_text(
                            selected_values[0].get("media_type"),
                            "artifact.media_type",
                            MAX_MEDIA_TYPE_SCALARS,
                        )
                        unsupported = presentation_kind not in self.registry.kinds or (
                            presentation_kind == "image-facsimile"
                            and media_type == "image/tiff"
                        ) or presentation_kind == "unsupported-binary"
                        if unsupported:
                            availability = "unsupported"
                            message = (
                                "Exact bytes are declared, but this presentation is not "
                                "supported in the browser."
                            )
                        else:
                            availability = "available"
                            message = "Available from a validated read-only input."
                    else:
                        availability = "selection-required"
                        message = (
                            "Choose a retained source. Multiple manifest-bound authorities "
                            "are available; the viewer will not guess."
                        )
                        selected = None
                    outline = []
                else:
                    resolution = self._resolve(work, stage_id)
                    availability = resolution.availability
                    message = resolution.message
                    selected = None if resolution.artifact is None else {
                        "id": resolution.artifact["id"],
                        "version": resolution.artifact["version"],
                    }
                    outline_full = (
                        [] if resolution.presentation is None else resolution.presentation["outline"]
                    )
                    outline_over_bound = (
                        serialized_payload_size(outline_full) > MAX_OUTLINE_PAYLOAD_BYTES
                    )
                    outline = [] if outline_over_bound else outline_full
                available = availability == "available"
                capabilities = {
                    "read": {
                        "available": available,
                        "reason": "Read presents the byte-verified artifact in browser-native typed nodes."
                        if available else message,
                    },
                    "compare": {
                        "available": available,
                        "reason": "Compare is available when this artifact reopens exactly under its recorded identity and version.",
                    },
                }
                stage_summary = {
                    "id": stage_id,
                    "label": STAGE_LABELS[stage_id],
                    "availability": availability,
                    "selected_artifact": selected,
                    "artifacts": [
                        self._artifact_summary(item)
                        for item in artifact_values
                    ],
                    "outline": outline,
                    "message": message,
                }
                # Capability reasons are not part of the frontend StageSummary.
                # Repeating them for every stage pushes the ordinary 402-work
                # library past the governed catalog response bound.
                if not compact_work_catalog:
                    stage_summary["capabilities"] = capabilities
                stages.append(stage_summary)
            correspondence_sources = [
                {"id": source["id"], "state": source["state"], "left_stage": source["left_stage"], "left_artifact_id": source["left_artifact_id"], "left_artifact_version": source["left_artifact_version"], "right_stage": source["right_stage"], "right_artifact_id": source["right_artifact_id"], "right_artifact_version": source["right_artifact_version"], "mappings": source["mappings"]}
                for source in self._correspondence_sources(work)
            ]
            catalog_work = {
                **summary,
                "scope": _text(work.get("scope"), "work.scope"),
                "candidate_validation": work.get("candidate_validation"),
                "default_compare": work.get("default_compare"),
                "stages": stages,
                "correspondence_sources": correspondence_sources,
            }
            candidate_validations = work.get("candidate_validations")
            if candidate_validations is not None:
                if not isinstance(candidate_validations, list) or any(
                    not isinstance(item, dict) for item in candidate_validations
                ):
                    raise ReviewContractError(
                        "work candidate_validations must be an array of objects"
                    )
                catalog_work["candidate_validations"] = candidate_validations
            works.append(catalog_work)
        return {
            "contract": CATALOG_CONTRACT,
            "manifest_contract": MANIFEST_CONTRACT,
            "approved_roots": [{"id": item["id"], "access": "read-only", "purpose": item["purpose"]} for item in self.manifest["approved_roots"]],
            "works": works,
        }

    def _stage_records(
        self, work: dict[str, Any], stage_id: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if stage_id not in STAGE_ORDER:
            raise ReviewContractError(f"unknown stage: {stage_id}")
        stages = require_object(work.get("stages"), "work.stages")
        stage = require_object(stages.get(stage_id), f"stage {stage_id}")
        values = stage.get("artifacts", [])
        if not isinstance(values, list) or any(
            not isinstance(item, dict) for item in values
        ):
            raise ReviewContractError(
                f"stage {stage_id} artifact declarations are malformed"
            )
        return stage, values

    def _artifact_discovery_summary(
        self, work: dict[str, Any], artifact: dict[str, Any]
    ) -> dict[str, Any]:
        summary = self._artifact_summary(artifact)
        root = artifact.get("root")
        if root is not None:
            summary["approved_root_id"] = _identity_text(root, "artifact root")
        member = artifact.get("candidate_validation_tei_artifact_id")
        if member is not None:
            summary["candidate_validation_tei_artifact_id"] = _identity_text(
                member, "candidate validation TEI artifact id"
            )
        return summary

    def _stage_bounded_summary(
        self,
        work: dict[str, Any],
        stage_id: str,
        artifacts: list[dict[str, Any]],
        requested_identity: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        stage, values = self._stage_records(work, stage_id)
        self._validate_selected_manifest_persisted_bounds(work, stage_id)
        selected_values = [
            item for item in values
            if ((item.get("id"), item.get("version")) == requested_identity
                if requested_identity is not None else item.get("id") == stage.get("selected_artifact_id"))
        ]
        selected: dict[str, str] | None = None
        if not values:
            availability = "unavailable"
            message = "No artifact is declared for this stage."
        elif len(selected_values) != 1:
            availability = "selection-required"
            message = (
                "Choose a retained source. Multiple manifest-bound authorities "
                "are available; the viewer will not guess."
            )
        else:
            selected_value = selected_values[0]
            selected = {
                "id": _identity_text(selected_value.get("id"), "artifact.id"),
                "version": _identity_text(
                    selected_value.get("version"), "artifact.version"
                ),
            }
            presentation_kind = _identity_text(
                selected_value.get("presentation_kind"),
                "artifact.presentation_kind",
            )
            media_type = _governed_bounded_text(
                selected_value.get("media_type"),
                "artifact.media_type",
                MAX_MEDIA_TYPE_SCALARS,
            )
            unsupported = presentation_kind not in self.registry.kinds or (
                presentation_kind == "image-facsimile" and media_type == "image/tiff"
            ) or presentation_kind == "unsupported-binary"
            if unsupported:
                availability = "unsupported"
                message = (
                    "Exact bytes are declared, but this presentation is not "
                    "supported in the browser."
                )
            else:
                availability = "available"
                message = "Available from a validated read-only input."
        return {
            "id": stage_id,
            "label": STAGE_LABELS[stage_id],
            "availability": availability,
            "selected_artifact": selected,
            "artifacts": [
                self._artifact_discovery_summary(work, item) for item in artifacts
            ],
            "artifact_discovery": {
                "total": len(values),
                "returned": len(artifacts),
                "complete": len(artifacts) == len(values),
            },
            "outline": [],
            "message": message,
        }

    def _candidate_validation_payload(
        self, work: dict[str, Any], *, include_source_ids: bool
    ) -> list[dict[str, Any]]:
        values = work.get("candidate_validations")
        if values is None:
            return []
        if not isinstance(values, list) or any(
            not isinstance(item, dict) for item in values
        ):
            raise ReviewContractError(
                "work candidate_validations must be an array of objects"
            )
        payload: list[dict[str, Any]] = []
        for index, value in enumerate(values):
            source_ids = value.get("source_artifact_ids", [])
            if not isinstance(source_ids, list):
                raise ReviewContractError(
                    f"candidate validation {index} source_artifact_ids must be an array"
                )
            if include_source_ids:
                normalized_ids = [
                    _identity_text(item, "candidate validation source artifact id")
                    for item in source_ids
                ]
            else:
                # Validate every retained identity without constructing a
                # second 58k-member list for a bounded work detail response.
                for item in source_ids:
                    _identity_text(item, "candidate validation source artifact id")
                normalized_ids = []
            member = dict(value)
            member["source_artifact_ids"] = (
                normalized_ids if include_source_ids else []
            )
            member["source_artifact_count"] = len(source_ids)
            if not include_source_ids:
                member["source_artifact_discovery"] = {
                    "total": len(source_ids),
                    "route": "/api/review/v1/works/{slug}/stages/source/artifacts",
                    "complete": False,
                }
            payload.append(member)
        return payload

    @staticmethod
    def _associations_need_bounded_detail(work: dict[str, Any]) -> bool:
        candidate_values = work.get("candidate_validations", [])
        if isinstance(candidate_values, list):
            for value in candidate_values:
                if not isinstance(value, dict):
                    continue
                source_ids = value.get("source_artifact_ids", [])
                if isinstance(source_ids, list) and sum(
                    len(item) + 4 for item in source_ids if isinstance(item, str)
                ) > MAX_RESPONSE_SERIALIZED_BYTES // 3:
                    return True
        correspondence_values = work.get("correspondence_sources", [])
        if isinstance(correspondence_values, list):
            for value in correspondence_values:
                if not isinstance(value, dict):
                    continue
                mappings = value.get("mappings", [])
                if isinstance(mappings, list) and sum(
                    len(item.get("left_location", ""))
                    + len(item.get("right_location", ""))
                    + 40
                    for item in mappings
                    if isinstance(item, dict)
                ) > MAX_RESPONSE_SERIALIZED_BYTES // 3:
                    return True
        return False

    def _summary_work(self, work: dict[str, Any]) -> dict[str, Any]:
        summary = self.work_summary(str(work.get("slug")))
        stages = []
        for stage_id in STAGE_ORDER:
            stages.append(self._stage_bounded_summary(work, stage_id, []))
        correspondence_sources = [
            {
                "id": source["id"],
                "state": source["state"],
                "left_stage": source["left_stage"],
                "left_artifact_id": source["left_artifact_id"],
                "left_artifact_version": source["left_artifact_version"],
                "right_stage": source["right_stage"],
                "right_artifact_id": source["right_artifact_id"],
                "right_artifact_version": source["right_artifact_version"],
                "mappings": [],
                "mapping_count": source["mapping_count"],
                "mapping_discovery": source["mapping_discovery"],
            }
            for source in self._correspondence_sources(
                work, include_mappings=False
            )
        ]
        candidate_validations = self._candidate_validation_payload(
            work, include_source_ids=False
        )
        catalog_work = {
            **summary,
            "scope": _text(work.get("scope"), "work.scope"),
            "candidate_validation": work.get("candidate_validation"),
            "default_compare": work.get("default_compare"),
            "stages": stages,
            "correspondence_sources": correspondence_sources,
            "agent_links": self._agent_links(str(work["slug"]), stages),
        }
        if candidate_validations:
            catalog_work["candidate_validations"] = candidate_validations
        return catalog_work

    def _agent_links(self, slug: str, stages: list[dict[str, Any]]) -> dict[str, str]:
        """Discover exact selections without parsing content or guessing associations."""
        base = f"/api/review/v1/works/{quote(slug, safe='')}"
        links = {"work": base + "?" + urlencode({"catalog_version": self._catalog_version})}
        query = {"linked": "false", "correspondence": "absent", "auto_page": "true"}
        for role, stage_id in (("left", "source"), ("right", "tei")):
            stage = next(item for item in stages if item["id"] == stage_id)
            artifact = stage["selected_artifact"]
            if artifact is None:
                return links
            query.update({f"{role}_stage": stage_id, f"{role}_artifact": artifact["id"],
                          f"{role}_version": artifact["version"], f"{role}_location": "start"})
            links[f"{stage_id}_locations"] = base + f"/stages/{stage_id}/locations?" + urlencode({
                "expected_artifact": artifact["id"], "expected_version": artifact["version"], "limit": 20,
            })
        links["compare_text"] = base + "/compare?" + urlencode({**query, "representation": "text"})
        links["compare_brief"] = base + "/compare?" + urlencode({**query, "representation": "brief"})
        return links

    def catalog_summary_page(
        self,
        offset: int = 0,
        limit: int = MAX_CATALOG_PAGE_SIZE,
        catalog_version: str | None = None,
        search: str | None = None,
        state: str | None = None,
    ) -> dict[str, Any]:
        self._validate_catalog_version(catalog_version)
        offset, limit = self._page_bounds(offset, limit, "catalog")
        works_value = self.manifest.get("works")
        if not isinstance(works_value, list):
            raise ReviewContractError("works must be an array")
        roots_value = self.manifest.get("approved_roots", [])
        if not isinstance(roots_value, list):
            raise ReviewContractError("approved_roots must be an array")
        if search is not None and (not isinstance(search, str) or len(search) > 256):
            raise ReviewContractError("catalog search must be at most 256 characters")
        if state not in {None, "all", "no-candidate", "choose-source", "available", "unsupported", "invalid"}:
            raise ReviewContractError("unknown catalog state filter")
        def matches(value):
            if not library_search_matches(search, [str(value.get(key, "")) for key in ("slug", "title", "creator")]): return False
            if state in {None, "all"}: return True
            summary = self._summary_work(value)
            stages = {stage["id"]:stage for stage in summary["stages"]}
            tei = stages.get("tei", {}); source = stages.get("source", {})
            if not summary.get("candidate_validation") and not summary.get("candidate_validations"): actual = "no-candidate"
            elif "unsupported" in {source.get("availability"), tei.get("availability")}: actual = "unsupported"
            elif source.get("availability") == "selection-required": actual = "choose-source"
            elif source.get("availability") == tei.get("availability") == "available": actual = "available"
            else: actual = "invalid"
            return state == actual
        works_value = [value for value in works_value if matches(value)] if search or state not in {None, "all"} else works_value
        total = len(works_value)
        selected = works_value[offset:offset + limit]
        works: list[dict[str, Any]] = []
        for index, value in enumerate(selected, start=offset):
            work = require_object(value, f"works[{index}]")
            works.append(self._summary_work(work))
        page = {
            "offset": offset,
            "returned": len(works),
            "total": total,
            "next_offset": offset + len(works) if offset + len(works) < total else None,
            "catalog_version": self._catalog_version,
        }
        payload = {
            "contract": CATALOG_CONTRACT,
            "manifest_contract": MANIFEST_CONTRACT,
            "catalog_version": self._catalog_version,
            "approved_roots": [],
            "approved_roots_count": len(roots_value),
            "approved_roots_discovery": {
                "route": "/api/review/v1/roots",
                "total": len(roots_value),
                "page_size": MAX_CATALOG_PAGE_SIZE,
                "catalog_version": self._catalog_version,
            },
            "works": works,
            "page": page,
        }
        while serialized_payload_size(payload) > MAX_RESPONSE_SERIALIZED_BYTES:
            if not works or len(works) == 1:
                raise ResponseTooLargeError(
                    "A single catalog work summary exceeds the governed response bound"
                )
            works.pop()
            page["returned"] = len(works)
            page["next_offset"] = (
                offset + len(works) if offset + len(works) < total else None
            )
        return payload

    def _detail_artifacts(
        self,
        stage: dict[str, Any],
        values: list[dict[str, Any]],
        requested_identity: tuple[str, str] | None,
    ) -> list[dict[str, Any]]:
        if requested_identity is not None:
            matches = [
                item for item in values
                if (item.get("id"), item.get("version")) == requested_identity
            ]
            if len(matches) != 1:
                raise ReviewContractError(
                    "requested artifact identity is not a current declared artifact"
                )
        selected = [
            item for item in values
            if item.get("id") == stage.get("selected_artifact_id")
        ]
        result = list(values[:MAX_CATALOG_PAGE_SIZE])
        returned_identities = {
            (item.get("id"), item.get("version")) for item in result
        }
        for item in [*selected, *( [] if requested_identity is None else matches )]:
            identity = (item.get("id"), item.get("version"))
            if identity not in returned_identities:
                result.append(item)
                returned_identities.add(identity)
        return result

    def _work_detail_payload(
        self,
        work: dict[str, Any],
        source_identity: tuple[str, str] | None,
        tei_identity: tuple[str, str] | None,
        *,
        include_full_associations: bool,
    ) -> dict[str, Any]:
        stages = []
        for stage_id, requested_identity in (
            ("source", source_identity), ("tei", tei_identity)
        ):
            stage, values = self._stage_records(work, stage_id)
            artifacts = self._detail_artifacts(stage, values, requested_identity)
            stages.append(self._stage_bounded_summary(work, stage_id, artifacts, requested_identity))
        correspondence_sources = self._correspondence_sources(
            work, include_mappings=include_full_associations
        )
        correspondence = [
            {
                "id": source["id"],
                "state": source["state"],
                "left_stage": source["left_stage"],
                "left_artifact_id": source["left_artifact_id"],
                "left_artifact_version": source["left_artifact_version"],
                "right_stage": source["right_stage"],
                "right_artifact_id": source["right_artifact_id"],
                "right_artifact_version": source["right_artifact_version"],
                "mappings": source["mappings"],
            }
            for source in correspondence_sources
        ]
        if not include_full_associations:
            for item, source in zip(correspondence, correspondence_sources):
                item["mapping_count"] = source["mapping_count"]
                item["mapping_discovery"] = source["mapping_discovery"]
        return {
            **self.work_summary(str(work.get("slug"))),
            "scope": _text(work.get("scope"), "work.scope"),
            "candidate_validation": work.get("candidate_validation"),
            "default_compare": work.get("default_compare"),
            "stages": stages,
            "correspondence_sources": correspondence,
            "candidate_validations": self._candidate_validation_payload(
                work, include_source_ids=include_full_associations
            ),
            "agent_links": self._agent_links(str(work["slug"]), stages),
            "approved_roots_count": len(self.manifest.get("approved_roots", [])),
            "approved_roots_discovery": {
                "route": "/api/review/v1/roots",
                "total": len(self.manifest.get("approved_roots", [])),
                "page_size": MAX_CATALOG_PAGE_SIZE,
                "catalog_version": self._catalog_version,
            },
        }

    def work_detail(
        self,
        slug: str,
        *,
        source_artifact: str | None = None,
        source_version: str | None = None,
        tei_artifact: str | None = None,
        tei_version: str | None = None,
        catalog_version: str | None = None,
    ) -> dict[str, Any]:
        self._validate_catalog_version(catalog_version)
        if (source_artifact is None) != (source_version is None):
            raise ReviewContractError(
                "source_artifact and source_version must appear together"
            )
        if (tei_artifact is None) != (tei_version is None):
            raise ReviewContractError(
                "tei_artifact and tei_version must appear together"
            )
        work = self._work(slug)
        source_identity = (
            None
            if source_artifact is None
            else (
                _identity_text(source_artifact, "source artifact"),
                _identity_text(source_version, "source version"),
            )
        )
        tei_identity = (
            None
            if tei_artifact is None
            else (
                _identity_text(tei_artifact, "TEI artifact"),
                _identity_text(tei_version, "TEI version"),
            )
        )
        include_full = not self._associations_need_bounded_detail(work)
        payload = self._work_detail_payload(
            work, source_identity, tei_identity,
            include_full_associations=include_full,
        )
        if include_full and serialized_payload_size(payload) > MAX_RESPONSE_SERIALIZED_BYTES:
            payload = self._work_detail_payload(
                work, source_identity, tei_identity,
                include_full_associations=False,
            )
        if serialized_payload_size(payload) > MAX_RESPONSE_SERIALIZED_BYTES:
            raise ResponseTooLargeError(
                "The requested work detail exceeds the governed response bound"
            )
        return {
            "contract": "ocd-corpus-review-work-v1",
            "catalog_version": self._catalog_version,
            "work": payload,
        }

    def artifact_page(
        self,
        slug: str,
        stage_id: str,
        *,
        offset: int = 0,
        limit: int = MAX_ARTIFACT_PAGE_SIZE,
        search: str | None = None,
        catalog_version: str | None = None,
        artifact_id: str | None = None,
        artifact_version: str | None = None,
    ) -> dict[str, Any]:
        self._validate_catalog_version(catalog_version)
        offset, limit = self._page_bounds(offset, limit, "artifact discovery")
        if (artifact_id is None) != (artifact_version is None):
            raise ReviewContractError(
                "artifact_id and artifact_version must appear together"
            )
        work = self._work(slug)
        stage, values = self._stage_records(work, stage_id)
        requested = None
        if artifact_id is not None:
            requested = (
                _identity_text(artifact_id, "artifact id"),
                _identity_text(artifact_version, "artifact version"),
            )
            if sum(
                (item.get("id"), item.get("version")) == requested
                for item in values
            ) != 1:
                raise ReviewContractError(
                    "requested artifact identity is not a current declared artifact"
                )
        needle = None if search is None else _governed_bounded_text(
            search, "artifact search", MAX_LOCATION_SEARCH_SCALARS
        ).casefold()
        matched_values = []
        for item in values:
            if needle is not None:
                searchable = " ".join(
                    str(item.get(field, ""))
                    for field in ("name", "authority_path", "path")
                ).casefold()
                if needle not in searchable:
                    continue
            matched_values.append(item)
        matched = len(matched_values)
        page_values = matched_values[offset:offset + limit]

        def make_payload(items: list[dict[str, Any]]) -> dict[str, Any]:
            returned = len(items)
            return {
                "contract": "ocd-corpus-review-artifacts-v1",
                "catalog_version": self._catalog_version,
                "artifacts": [
                    self._artifact_discovery_summary(work, item) for item in items
                ],
                "page": {
                    "offset": offset,
                    "returned": returned,
                    "total": matched,
                    "next_offset": (
                        offset + returned if offset + returned < matched else None
                    ),
                },
                "matched": matched,
                "total": len(values),
            }

        payload = make_payload(page_values)
        while serialized_payload_size(payload) > MAX_RESPONSE_SERIALIZED_BYTES:
            if not page_values or len(page_values) == 1:
                raise ResponseTooLargeError(
                    "A single artifact discovery item exceeds the governed response bound"
                )
            page_values.pop()
            payload = make_payload(page_values)
        return payload

    def correspondence_page(
        self, slug: str, correspondence_source: str, *,
        offset: int = 0, limit: int = MAX_CATALOG_PAGE_SIZE,
        catalog_version: str | None = None,
    ) -> dict[str, Any]:
        self._validate_catalog_version(catalog_version)
        offset, limit = self._page_bounds(offset, limit, "correspondence discovery")
        source_id = _identity_text(correspondence_source, "correspondence source")
        work = self._work(slug)
        # Validate retained mappings without allocating every normalized mapping.
        summaries = self._correspondence_sources(work, include_mappings=False)
        if not any(source["id"] == source_id for source in summaries):
            raise ReviewContractError("correspondence source is not declared for this work")
        source = next(item for item in work["correspondence_sources"] if item["id"] == source_id)
        mappings = source["mappings"]
        selected = [dict(item) for item in mappings[offset:offset + limit]]
        payload = {
            "contract": "ocd-corpus-review-correspondence-page-v1",
            "catalog_version": self._catalog_version,
            "correspondence_source": source_id,
            "mappings": selected,
            "page": {
                "offset": offset, "returned": len(selected), "total": len(mappings),
                "next_offset": offset + len(selected) if offset + len(selected) < len(mappings) else None,
            },
        }
        while serialized_payload_size(payload) > MAX_RESPONSE_SERIALIZED_BYTES:
            if len(selected) <= 1:
                raise ResponseTooLargeError("A correspondence mapping exceeds the governed response bound")
            selected.pop()
            payload["page"]["returned"] = len(selected)
            payload["page"]["next_offset"] = offset + len(selected)
        return payload

    def approved_roots_page(
        self,
        *,
        offset: int = 0,
        limit: int = MAX_CATALOG_PAGE_SIZE,
        work_slug: str | None = None,
        catalog_version: str | None = None,
    ) -> dict[str, Any]:
        self._validate_catalog_version(catalog_version)
        offset, limit = self._page_bounds(offset, limit, "approved root discovery")
        values = self.manifest.get("approved_roots")
        if not isinstance(values, list):
            raise ReviewContractError("approved_roots must be an array")
        root_ids: set[str] | None = None
        if work_slug is not None:
            work = self._work(work_slug)
            root_ids = set()
            stages = require_object(work.get("stages"), "work.stages")
            for stage_id in STAGE_ORDER:
                stage = require_object(stages.get(stage_id), f"stage {stage_id}")
                artifacts = stage.get("artifacts", [])
                if not isinstance(artifacts, list):
                    raise ReviewContractError(
                        f"stage {stage_id} artifact declarations are malformed"
                    )
                for artifact in artifacts:
                    if isinstance(artifact, dict) and isinstance(
                        artifact.get("root"), str
                    ):
                        root_ids.add(artifact["root"])
        total = 0
        roots: list[dict[str, str]] = []
        for index, value in enumerate(values):
            root = require_object(value, f"approved_roots[{index}]")
            root_id = _identity_text(root.get("id"), "approved root id")
            if root_ids is not None and root_id not in root_ids:
                continue
            if total >= offset and len(roots) < limit:
                roots.append(
                    {
                        "id": root_id,
                        "access": "read-only",
                        "purpose": _text(root.get("purpose"), "approved root purpose"),
                    }
                )
            total += 1
        returned = len(roots)
        return {
            "contract": "ocd-corpus-review-roots-v1",
            "catalog_version": self._catalog_version,
            "approved_roots": roots,
            "page": {
                "offset": offset,
                "returned": returned,
                "total": total,
                "next_offset": offset + returned if offset + returned < total else None,
                "catalog_version": self._catalog_version,
            },
            "total": total,
        }

    def _work_scope(self, slug: str) -> dict[str, str]:
        work = self._work(slug)
        summary = self.work_summary(slug)
        return {**summary, "scope": _text(work.get("scope"), "work.scope")}

    def _declaration(self, resolution: StageResolution, location_kind_fallback: str | None = None) -> dict[str, str] | None:
        if resolution.presentation is None or resolution.artifact is None:
            return None
        location_kind = resolution.presentation.get("location_kind") or location_kind_fallback
        if location_kind is None:
            return None
        return {
            "declared_kind": resolution.presentation["declared_kind"],
            "media_type": resolution.artifact["media_type"],
            "location_kind": location_kind,
        }

    def _pane_envelope_member(self, slug: str, stage_id: str, location_value: str | None, declaration: dict[str, str] | None, artifact: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "stage": stage_id,
            "declaration": declaration,
            "artifact": artifact,
            "location": location_value,
        }

    def _served_page_nodes(self, rendered: dict[str, Any], start: int, limit: int,
                           *, _on_served_node=None) -> list[dict[str, Any]]:
        """Serve-time visible projection of the requested segment range.

        Over-cap atomic segments are SHA-mark truncated exactly as contexts are;
        every served body stays bounded without exception.
        """
        segments = rendered["segments"]
        pages = rendered["_pages"]
        served: list[dict[str, Any]] = []
        text_cache: dict[int, str] = {}
        for index in range(start, start + limit):
            page_nodes = pages[index]
            if segments[index].get("truncated"):
                parts = [_plain_node_text(node, text_cache) for node in page_nodes]
                full_text = " ".join(part for part in parts if part).strip(" ")
                replacement = {"type": "preformatted", "text": bounded_visible_text(full_text, MAX_PAGE_SCALARS, "Segment")}
                if _on_served_node is not None:
                    _on_served_node(replacement, tuple(page_nodes), replacement=True)
                served.append(replacement)
            else:
                if _on_served_node is not None:
                    for node in page_nodes:
                        _on_served_node(node, (node,), replacement=False)
                served.extend(page_nodes)
        return served

    def stage_view(
        self,
        slug: str,
        stage_id: str,
        *,
        recorded: RecordedContext | tuple[str, str, str] | None = None,
        from_stage: str | None = None,
        from_location: str | None = None,
        segment_start: int | None = None,
        segment_limit: int | None = None,
        auto_page: bool = False,
        echoed_route_digest: str | None = None,
        _probe: bool = False,
        _resolution: StageResolution | None = None,
    ) -> dict[str, Any]:
        if isinstance(recorded, tuple):
            recorded = RecordedContext(*recorded)
        if stage_id not in STAGE_ORDER:
            raise ReviewContractError(f"unknown stage: {stage_id}")
        if from_stage is not None and from_stage not in STAGE_ORDER:
            raise ReviewContractError(f"unknown correspondence source stage: {from_stage}")
        if (from_stage is None) != (from_location is None):
            raise ReviewContractError("correspondence source stage and location must be supplied together")
        if from_location is not None:
            from_location = governed_location_text(from_location, "correspondence source location")
        work = self._work(slug)
        work_summary = self.work_summary(slug)
        self._validate_selected_manifest_persisted_bounds(work, stage_id)
        resolution = _resolution or self._resolve(
            work,
            stage_id,
            None if recorded is None else (recorded.artifact_id, recorded.version),
        )
        presentation = ({**resolution.presentation, "document":dict(resolution.presentation["document"])} if resolution.presentation else None)
        location = None
        outline: list[dict[str, Any]] = []
        selected_context = None
        paging: dict[str, Any] | None = None
        location_state = "in-range"
        location_message = ""
        identity_current = (
            recorded is not None and resolution.artifact is not None
            and (recorded.artifact_id, recorded.version) == (resolution.artifact["id"], resolution.artifact["version"])
        )
        outline_full: list[dict[str, Any]] = []
        outline_over_bound = False
        context_state = "unavailable"
        actual_value = "start"
        location_kind_value: str | None = None
        if presentation:
            assert resolution.rendered is not None
            rendered = resolution.rendered
            outline_full = rendered["outline"]
            contexts = rendered["contexts"]
            location_kind = presentation.pop("location_kind")
            # The full contexts dict is internal; only selected_context is public.
            presentation.pop("contexts", None)
            presentation.pop("outline", None)
            location_kind_value = location_kind
            start_label = {"source": "Start of retained source", "tei": "Start of faithful TEI candidate", "json": "Start of final JSON"}[stage_id]
            if recorded is None and resolution.artifact is not None:
                recorded = RecordedContext(resolution.artifact["id"], resolution.artifact["version"], "start")
            stable = {"start": start_label, **{item["location"]: item["label"] for item in outline_full}}
            if recorded is None or resolution.artifact is None:
                context_state = "unavailable"
                context_message = "The recorded artifact is no longer selected or available."
            elif (recorded.artifact_id, recorded.version) != (resolution.artifact["id"], resolution.artifact["version"]):
                context_state = "drift"
                context_message = "The recorded artifact or version differs from the current manifest selection."
            elif recorded.location not in stable:
                context_state = "location-missing"
                context_message = "The recorded location does not exist in the selected artifact; no replacement location was inferred."
            else:
                context_state = "exact"
                context_message = "The recorded artifact version and stable location were reopened exactly."
            actual_value = recorded.location if context_state == "exact" else "start"
            location = {"kind": location_kind, "value": actual_value, "label": stable.get(actual_value, start_label)}
            context = contexts.get(actual_value)
            if context is None:
                context = contexts["start"]
            selected_context = {"location": actual_value, "label": location["label"], "text": context["text"], "document": {"nodes": context["nodes"]}}

            outline_over_bound = serialized_payload_size(outline_full) > MAX_OUTLINE_PAYLOAD_BYTES
            outline = [] if outline_over_bound else [dict(item) for item in outline_full]

            segments = rendered["segments"]
            count = len(segments)
            location_segment = 0 if actual_value == "start" else next(
                (index for index, segment in enumerate(segments) if actual_value in segment["locations"]),
                None,
            )
            if auto_page and count > 1 and segment_start is None and segment_limit is None:
                segment_start = location_segment if location_segment is not None else 0
                segment_limit = 1
            # Per-segment locations are internal. Publish only the requested
            # descriptor window: sending metadata for every segment can consume
            # the response budget before any visible content is included.
            descriptor_start = 0 if segment_start is None else segment_start
            descriptor_limit = (
                min(PAGING_MAX_SEGMENTS_PER_REQUEST, count)
                if segment_limit is None
                else segment_limit
            )
            public_segments = [
                {key: value for key, value in segment.items() if key != "locations"}
                for segment in segments[
                    descriptor_start : descriptor_start + descriptor_limit
                ]
            ]
            paging = {
                "mode": "segments",
                "max_segments_per_request": PAGING_MAX_SEGMENTS_PER_REQUEST,
                "segment_count": count,
                "segments": public_segments,
                "location_segment": location_segment,
                "bound": {
                    "artifact_id": resolution.artifact["id"],
                    "version": resolution.artifact["version"],
                    "sha256": resolution.artifact["sha256"],
                },
                "cache_resident": resolution.cache_resident,
            }
            if segment_start is None and segment_limit is None:
                if count > 1:
                    location_state = "page-required"
                    location_message = (
                        f"This artifact is paged into {count} bounded segments; request a segment range "
                        f"of at most {PAGING_MAX_SEGMENTS_PER_REQUEST} segments to load content."
                    )
                    presentation["document"]["nodes"] = []
                else:
                    presentation["document"]["nodes"] = self._served_page_nodes(rendered, 0, 1)
                    location_state = "in-range"
                    location_message = "The whole artifact fits within one bounded segment."
            else:
                if segment_start is None or segment_limit is None:
                    raise RangeInvalidError("segment_start and segment_limit must be supplied together")
                if segment_limit < 1 or segment_limit > PAGING_MAX_SEGMENTS_PER_REQUEST:
                    raise RangeInvalidError(f"segment_limit must be between 1 and {PAGING_MAX_SEGMENTS_PER_REQUEST}")
                if segment_start < 0 or segment_start >= count or segment_start + segment_limit > count:
                    raise RangeInvalidError("the requested segment range escapes the published segments")
                presentation["document"]["nodes"] = self._served_page_nodes(rendered, segment_start, segment_limit)
                containing = set() if location_segment is None else {location_segment}
                requested_window = set(range(segment_start, segment_start + segment_limit))
                if containing & requested_window:
                    location_state = "in-range"
                    location_message = "The recorded location is inside the requested segment range."
                else:
                    location_state = "location-outside-range"
                    location_message = (
                        "The recorded location lies outside the requested segment range; neighboring content "
                        "was not substituted and no replacement was inferred."
                    )
        else:
            context_state = "unavailable"
            context_message = "The recorded artifact is no longer selected or available."

        minimal_size = MAX_RESPONSE_SERIALIZED_BYTES
        if not _probe and resolution.presentation is not None:
            probe = self.stage_view(
                slug, stage_id,
                recorded=recorded, from_stage=from_stage, from_location=from_location,
                segment_start=0, segment_limit=1, _probe=True, _resolution=resolution,
            )
            minimal_size = serialized_payload_size(probe)
        capabilities = self._stage_capabilities(
            resolution, context_state, identity_current, minimal_size,
        )
        envelope_payload: dict[str, Any] = {
            "mode": "stage",
            "stage": stage_id,
            "declaration": self._declaration(resolution, location_kind_value),
            "artifact": None if resolution.artifact is None else {
                "id": resolution.artifact["id"], "version": resolution.artifact["version"], "sha256": resolution.artifact["sha256"],
            },
            "location": None if location is None else location["value"],
            "work": self._work_scope(slug),
        }
        if from_stage is not None:
            envelope_payload["from_stage"] = from_stage
            envelope_payload["from_location"] = from_location
        route_digest = canonical_route_digest(envelope_payload)
        if echoed_route_digest is not None and echoed_route_digest != route_digest:
            raise RouteStaleError(
                "The echoed route digest does not match the current manifest state; "
                "refetch without a route digest to recover fresh state."
            )
        exact_fallback = None
        if resolution.readable and resolution.artifact is not None and context_state in {"exact", "location-missing"}:
            query = urlencode({"expected_artifact": resolution.artifact["id"], "expected_version": resolution.artifact["version"]})
            if resolution.exact is None:
                # Binary families have no text representation: the honest fallback is the governed bytes route (C2).
                if resolution.artifact["media_type"] in SAFE_NATIVE_MEDIA_TYPES:
                    exact_fallback = {
                        "kind": "exact-bytes",
                        "target": f"/api/review/v1/works/{quote(slug, safe="")}/stages/{stage_id}/bytes?{query}",
                        "label": "Download a copy for a native program",
                    }
            else:
                exact_fallback = {"kind": "exact-text", "target": f"/api/review/v1/works/{quote(slug, safe="")}/stages/{stage_id}/exact?{query}", "label": "View exact artifact text"}
        return {
            "contract": STAGE_VIEW_CONTRACT,
            "work": work_summary,
            "stage": {"id": stage_id, "label": STAGE_LABELS[stage_id]},
            "availability": resolution.availability,
            "message": resolution.message,
            "artifact": resolution.artifact,
            "presentation": presentation,
            "exact_fallback": exact_fallback,
            "native_open": native_open_policy(
                None if resolution.artifact is None else resolution.artifact["media_type"],
                slug,
                stage_id,
                None if resolution.artifact is None else resolution.artifact["id"],
                None if resolution.artifact is None else resolution.artifact["version"],
            ),
            "outline": outline,
            "outline_metadata": {
                "available": presentation is not None,
                "total": len(outline_full),
                "returned": len(outline),
                "truncated": outline_over_bound,
                "complete": not outline_over_bound,
            },
            "selected_context": selected_context,
            "location": location,
            "paging": paging,
            "capabilities": capabilities,
            "location_state": location_state,
            "location_message": location_message,
            "route_digest": route_digest,
            "recorded_context": {
                "state": context_state,
                "requested": None if recorded is None else {"artifact_id": recorded.artifact_id, "version": recorded.version, "location": recorded.location},
                "message": context_message,
            },
            "correspondence": {
                "state": "absent",
                "authority": None,
                "requested_from": None if from_stage is None else {"stage": from_stage, "location": from_location},
                "target_location": None,
                "message": "No governed upstream correspondence artifact is available; no location was inferred.",
            },
        }

    def locations(
        self,
        slug: str,
        stage_id: str,
        *,
        expected_artifact: str,
        expected_version: str,
        offset: int = 0,
        limit: int = MAX_LOCATION_PAGE_SIZE,
        search: str | None = None,
    ) -> dict[str, Any]:
        """Return a bounded identity-bound slice of the rendered outline.

        This endpoint deliberately reuses the normal resolver and renderer.  It
        only pages already-rendered source structure; it does not infer work
        boundaries, reread a different artifact, or loosen the document
        response bound.
        """
        if stage_id not in STAGE_ORDER:
            raise ReviewContractError(f"unknown stage: {stage_id}")
        expected_artifact = governed_identity_text(expected_artifact, "expected_artifact")
        expected_version = governed_identity_text(expected_version, "expected_version")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise RangeInvalidError("offset must be a nonnegative integer")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
            or limit > MAX_LOCATION_PAGE_SIZE
        ):
            raise RangeInvalidError(
                f"limit must be between 1 and {MAX_LOCATION_PAGE_SIZE}"
            )
        if search is not None:
            search = _governed_bounded_text(
                search, "location search", MAX_LOCATION_SEARCH_SCALARS
            )

        work = self._work(slug)
        resolution = self._resolve(work, stage_id, (expected_artifact, expected_version))
        outline_full: list[dict[str, Any]] = []
        if resolution.rendered is not None and resolution.presentation is not None:
            outline_full = [dict(item) for item in resolution.rendered["outline"]]
        needle = None if search is None else search.casefold()
        text_matches = set()
        if needle and resolution.rendered is not None and resolution.rendered["kind"] in {"exact-text", "epub-reader"}:
            locations = {item["location"] for item in outline_full}
            current = None
            for node in resolution.rendered["nodes"]:
                if node.get("location") in locations:
                    current = node["location"]
                if current is not None and needle in _node_text(node).casefold():
                    text_matches.add(current)
        matched = [
            item
            for item in outline_full
            if needle is None
            or needle in str(item["location"]).casefold()
            or needle in str(item["label"]).casefold()
            or item["location"] in text_matches
        ]
        if offset > len(matched):
            raise RangeInvalidError("offset exceeds the matched location count")
        items = matched[offset : offset + limit]
        next_offset = offset + len(items) if offset + len(items) < len(matched) else None
        artifact = None if resolution.artifact is None else {
            "id": resolution.artifact["id"],
            "version": resolution.artifact["version"],
            "sha256": resolution.artifact["sha256"],
        }
        return {
            "contract": LOCATIONS_CONTRACT,
            "work": self.work_summary(slug),
            "stage": {"id": stage_id, "label": STAGE_LABELS[stage_id]},
            "availability": resolution.availability,
            "message": resolution.message,
            "artifact": artifact,
            "search": search,
            "offset": offset,
            "limit": limit,
            "total": len(outline_full),
            "matched": len(matched),
            "returned": len(items),
            "next_offset": next_offset,
            "complete": next_offset is None,
            "locations": items,
        }

    def _stage_capabilities(
        self,
        resolution: StageResolution,
        context_state: str,
        identity_current: bool,
        minimal_size: int,
    ) -> dict[str, dict[str, Any]]:
        read_available = resolution.availability == "available" and minimal_size <= MAX_RESPONSE_SERIALIZED_BYTES
        if resolution.availability != "available":
            compare = {"available": False, "reason": "Compare requires an available supported presentation for this stage."}
        elif context_state == "exact" and identity_current:
            compare = {"available": True, "reason": "The recorded artifact version and stable location were reopened exactly."}
        else:
            compare = {
                "available": False,
                "reason": "Compare is unavailable because the recorded artifact or version differs from the current manifest selection; reopen it exactly first.",
            }
        return {
            "read": {
                "available": read_available,
                "reason": (
                    "Read presents the byte-verified artifact in browser-native typed nodes."
                    if read_available
                    else "Exact byte access remains available."
                    if resolution.readable
                    else "Even the smallest legal read request exceeds the governed response budget."
                ),
            },
            "compare": compare,
        }

    def _pair_route_digest(
        self,
        slug: str,
        left_stage: str,
        left_member: dict[str, Any],
        right_stage: str,
        right_member: dict[str, Any],
        *,
        linked: bool | None = None,
        correspondence_source: str | None = None,
        left_range: list[int] | None = None,
        right_range: list[int] | None = None,
        left_image: dict[str, Any] | None = None,
        right_image: dict[str, Any] | None = None,
    ) -> str:
        work = self._work(slug)
        correspondence_digest = None
        if correspondence_source is not None:
            matches = [item for item in self._correspondence_sources(work) if item["id"] == correspondence_source]
            if len(matches) == 1:
                correspondence_digest = source_content_digest(matches[0])
        payload: dict[str, Any] = {
            "mode": "compare",
            "left_stage": left_stage,
            "right_stage": right_stage,
            "left": left_member,
            "right": right_member,
            "work": self._work_scope(slug),
            "linked": linked,
            "correspondence_source": correspondence_source,
            "left_range": left_range,
            "right_range": right_range,
            "correspondence_digest": correspondence_digest,
        }
        if left_image is not None or right_image is not None:
            payload.update(left_image=left_image, right_image=right_image)
        return canonical_route_digest(payload)

    def exact(self, slug: str, stage_id: str, expected_artifact: str, expected_version: str) -> str:
        resolution = self._resolve(
            self._work(slug), stage_id, (expected_artifact, expected_version)
        )
        if not resolution.readable or resolution.artifact is None or resolution.path is None:
            raise ReviewContractError(resolution.message)
        if (expected_artifact, expected_version) != (resolution.artifact["id"], resolution.artifact["version"]):
            raise ReviewContractError("expected artifact identity does not match the current selected artifact")
        # The exact route deliberately serves whole bytes and re-verifies the bound
        # SHA-256 on every access; it is never paged and never cached.
        payload = resolution.path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != resolution.artifact["sha256"]:
            raise ReviewContractError("artifact bytes no longer match the declared sha256")
        try:
            from cvw_app.text_decoding import decode_text
            return decode_text(payload, resolution.artifact["media_type"])[0]
        except RendererError as error:
            raise ReviewContractError(str(error)) from error

    def stage_image(self, slug: str, stage_id: str, expected_artifact: str, expected_version: str,
                    expected_sha256: str, *, variant: str = "preview", region: str | None = None) -> tuple[bytes, dict[str, Any]]:
        """One bounded derivative from the existing exact admission path."""
        if variant not in {"preview", "region"} or (variant == "region") != (region is not None):
            raise ReviewContractError("image variant must be preview, or region with exactly one region tuple")
        box = parse_region(region) if region is not None else None
        if not SHA256.fullmatch(expected_sha256):
            raise ReviewContractError("expected_sha256 must be lowercase SHA-256")
        with image_work():
            resolution = self._resolve(self._work(slug), stage_id, (expected_artifact, expected_version),
                                       image_sha256=expected_sha256)
            if not resolution.readable or resolution.artifact is None or resolution.verified_image_payload is None:
                raise ReviewContractError(resolution.message)
            if box is None:
                result, metadata = preview_image(resolution.verified_image_payload, resolution.artifact["media_type"])
            else:
                result, metadata = region_image(resolution.verified_image_payload, resolution.artifact["media_type"], box)
            declaration = next(item for item in self._work(slug)["stages"][stage_id]["artifacts"]
                               if (item["id"], item["version"]) == (expected_artifact, expected_version))
            metadata["source"] = {**resolution.artifact, "work": slug, "stage": stage_id,
                                  "member": {"root": declaration["root"], "path": declaration["path"]},
                                  "bytes": len(resolution.verified_image_payload), "frame": 0,
                                  "page": None, "page_state": "not-applicable"}
            return result, metadata

    def stage_pdf_page(self, slug: str, stage_id: str, expected_artifact: str, expected_version: str,
                       expected_sha256: str, page: int) -> bytes:
        from cvw_app.pdf_pages import pdf_preview

        if not SHA256.fullmatch(expected_sha256) or not 1 <= page <= 5000:
            raise ReviewContractError("PDF page identity or page number is invalid")
        with image_work():
            payload, media_type = self.stage_bytes(slug, stage_id, expected_artifact, expected_version, expected_sha256)
            if media_type != "application/pdf":
                raise ReviewContractError("Selected file is not a PDF")
            try:
                return pdf_preview(payload, page)
            except RendererError as error:
                raise ReviewContractError(str(error)) from error

    def stage_bytes(self, slug: str, stage_id: str, expected_artifact: str, expected_version: str,
                    expected_sha256: str | None = None) -> tuple[bytes, str]:
        """Serve the byte-verified payload for allow-listed native formats (plan D2).

        Mirrors the /exact identity binding; bytes are re-read and re-verified
        against the declared SHA-256 on every request.
        """
        resolution = self._resolve(
            self._work(slug), stage_id, (expected_artifact, expected_version)
        )
        if not resolution.readable or resolution.artifact is None or resolution.path is None:
            raise ReviewContractError(resolution.message)
        if (expected_artifact, expected_version) != (resolution.artifact["id"], resolution.artifact["version"]):
            raise ReviewContractError("expected artifact identity does not match the current selected artifact")
        media_type = resolution.artifact["media_type"]
        if expected_sha256 is not None and expected_sha256 != resolution.artifact["sha256"]:
            raise ReviewContractError("expected sha256 does not match the admitted artifact")
        if media_type not in SAFE_NATIVE_MEDIA_TYPES:
            raise FormatNotAllowListedError(
                f"Format {media_type} is not on the safe native-format allow list; exact bytes were not served."
            )
        payload = resolution.path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != resolution.artifact["sha256"]:
            raise ReviewContractError("artifact bytes no longer match the declared sha256")
        return payload, media_type

    def compare_view(
        self,
        slug: str,
        *,
        left_stage: str,
        left_recorded: RecordedContext | tuple[str, str, str],
        right_stage: str,
        right_recorded: RecordedContext | tuple[str, str, str],
        linked: bool,
        correspondence_source: str | None,
        left_segment_start: int | None = None,
        left_segment_limit: int | None = None,
        right_segment_start: int | None = None,
        right_segment_limit: int | None = None,
        auto_page: bool = False,
        echoed_route_digest: str | None = None,
        evidence_brief: bool = False,
        text_only: bool = False,
        left_image: dict[str, Any] | None = None,
        right_image: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return two independent stage views plus only governed correspondence evidence."""
        if isinstance(left_recorded, tuple):
            left_recorded = RecordedContext(*left_recorded)
        if isinstance(right_recorded, tuple):
            right_recorded = RecordedContext(*right_recorded)
        if left_stage not in STAGE_ORDER or right_stage not in STAGE_ORDER:
            raise ReviewContractError("compare stages must be known stages")
        if not isinstance(linked, bool):
            raise ReviewContractError("linked navigation must be boolean")
        work = self._work(slug)
        left = self.stage_view(
            slug, left_stage, recorded=left_recorded,
            segment_start=left_segment_start, segment_limit=left_segment_limit,
            auto_page=auto_page,
        )
        right = self.stage_view(
            slug, right_stage, recorded=right_recorded,
            segment_start=right_segment_start, segment_limit=right_segment_limit,
            auto_page=auto_page,
        )
        for pane, selection in ((left, left_image), (right, right_image)):
            if selection is None:
                continue
            variant = selection.get("variant")
            if variant not in {"preview", "original", "region"}:
                raise ReviewContractError("unknown Compare image variant")
            if set(selection) != ({"variant", "region", "source_sha256"} if variant == "region" else {"variant"}):
                raise ReviewContractError("invalid Compare image selection fields")
            if not pane["presentation"] or pane["presentation"]["kind"] != "image-facsimile":
                raise ReviewContractError("Compare image selection requires a native image pane")
            pane["image_selection"] = selection
            if variant == "region":
                if pane["recorded_context"]["state"] != "exact" or selection["source_sha256"] != pane["artifact"]["sha256"]:
                    raise ReviewContractError("region source sha256 does not match the exact admitted pane")
                box = parse_region(selection["region"])
                plan = region_plan(pane["presentation"].get("native_image") or {}, box)
                pane["image_request"] = {**plan, "state": "requested-not-generated", "source_sha256": selection["source_sha256"],
                    "target": f"/api/review/v1/works/{quote(slug, safe="")}/stages/{pane['stage']['id']}/image?" + urlencode({"expected_artifact": pane["artifact"]["id"], "expected_version": pane["artifact"]["version"], "expected_sha256": selection["source_sha256"], "variant": "region", "region": selection["region"]}),
                    "meaning": "Planned region from admitted header metadata; current bytes, pixel mode, color support and decode are checked when requested. No derivative has been generated."}
        contexts_exact = left["recorded_context"]["state"] == "exact" and right["recorded_context"]["state"] == "exact"
        active_link_eligible = contexts_exact and left["availability"] == "available" and right["availability"] == "available"
        identity_matches = tuple(
            self._manifest_identity_is_current(
                work, stage, (recorded.artifact_id, recorded.version)
            )
            for stage, recorded in (
                (left_stage, left_recorded),
                (right_stage, right_recorded),
            )
        )
        historical_identity_drift = not any(identity_matches)
        source = None
        source_error: ReviewContractError | None = None
        if correspondence_source is not None:
            matches = [item for item in self._correspondence_sources(work) if item["id"] == correspondence_source]
            if len(matches) != 1:
                source_error = ReviewContractError("named correspondence source is not governed for this work")
            else:
                source = matches[0]
                if (source["left_stage"], source["right_stage"]) != (left_stage, right_stage):
                    source_error = ReviewContractError("named correspondence source does not govern these pane stages")
                source_identity = (source["left_artifact_id"], source["left_artifact_version"], source["right_artifact_id"], source["right_artifact_version"])
                recorded_identity = (left_recorded.artifact_id, left_recorded.version, right_recorded.artifact_id, right_recorded.version)
                if source_error is None and source_identity != recorded_identity:
                    source_error = ReviewContractError("named correspondence source does not bind these recorded pane artifacts and versions")
            if source_error is not None:
                if not historical_identity_drift:
                    raise source_error
                source = None
        if linked and active_link_eligible and (source is None or source["state"] != "known"):
            raise ReviewContractError("linked navigation requires one exact named known correspondence mapping")
        if source is None:
            correspondence = {
                "state": "absent", "source": None, "left_stage": left_stage, "right_stage": right_stage,
                "left_location": left_recorded.location, "right_location": None,
                "message": "No governed upstream correspondence output is available; no location was inferred.",
            }
        elif source["state"] == "uncertain":
            correspondence = {
                "state": "uncertain", "source": source["id"], "left_stage": left_stage, "right_stage": right_stage,
                "left_location": left_recorded.location, "right_location": None, "message": source["message"],
            }
        else:
            matches = [item for item in source["mappings"] if item["left_location"] == left_recorded.location]
            if len(matches) != 1:
                if not historical_identity_drift:
                    raise ReviewContractError("named correspondence source does not map the recorded left pane location")
                source = None
            else:
                target = matches[0]["right_location"]
                if linked and right_recorded.location != target:
                    if not historical_identity_drift:
                        raise ReviewContractError("the right pane location does not match the named correspondence")
                    source = None
            if source is None:
                correspondence = {
                    "state": "absent", "source": None, "left_stage": left_stage, "right_stage": right_stage,
                    "left_location": left_recorded.location, "right_location": None,
                    "message": "No governed upstream correspondence output is available; no location was inferred.",
                }
            else:
                correspondence = {
                    "state": "known", "source": source["id"], "left_stage": left_stage, "right_stage": right_stage,
                    "left_location": left_recorded.location, "right_location": target, "message": source["message"],
                }
        if linked and not active_link_eligible and not historical_identity_drift:
            if left["availability"] != "available" or right["availability"] != "available":
                raise ReviewContractError(
                    "active linked navigation requires both pane contexts to be exact and both presentations to be available"
                )
            raise ReviewContractError(
                "refusing active linked navigation requires both recorded pane artifact identities and versions to be noncurrent"
            )
        active_linked = linked and active_link_eligible
        link_refusal = None if not linked or active_linked else (
            "Linked navigation was requested for the recorded context, but the recorded pane context is no longer exact; "
            "navigation remains off and no match was inferred over current bytes."
        )
        left_declaration = {
            "declared_kind": left["presentation"]["declared_kind"] if left["presentation"] else None,
            "media_type": left["artifact"]["media_type"] if left["artifact"] else None,
            "location_kind": left["location"]["kind"] if left["location"] else None,
        }
        right_declaration = {
            "declared_kind": right["presentation"]["declared_kind"] if right["presentation"] else None,
            "media_type": right["artifact"]["media_type"] if right["artifact"] else None,
            "location_kind": right["location"]["kind"] if right["location"] else None,
        }
        route_digest = self._pair_route_digest(
            slug, left_stage,
            self._pane_envelope_member(slug, left_stage, None if left["location"] is None else left["location"]["value"], left_declaration, left["artifact"]),
            right_stage,
            self._pane_envelope_member(slug, right_stage, None if right["location"] is None else right["location"]["value"], right_declaration, right["artifact"]),
            linked=linked,
            correspondence_source=correspondence_source,
            left_range=None if left_segment_start is None else [left_segment_start, left_segment_limit],
            right_range=None if right_segment_start is None else [right_segment_start, right_segment_limit],
            left_image=left_image, right_image=right_image,
        )
        if echoed_route_digest is not None and echoed_route_digest != route_digest:
            raise RouteStaleError(
                "The echoed route digest does not match the current manifest state; "
                "refetch without a route digest to recover fresh state."
            )
        view = {
            "contract": COMPARE_VIEW_CONTRACT,
            "work": self.work_summary(slug),
            "left": left,
            "right": right,
            "requested_linked_navigation": linked,
            "linked_navigation": active_linked,
            "link_refusal": link_refusal,
            "correspondence": correspondence,
            "route_digest": route_digest,
        }
        if not evidence_brief and not text_only:
            return view
        brief = self._evidence_brief(
            view, work,
            left_range=None if left_segment_start is None else [left_segment_start, left_segment_limit],
            right_range=None if right_segment_start is None else [right_segment_start, right_segment_limit],
            correspondence_source=correspondence_source,
            auto_page=auto_page,
        )
        if text_only:
            brief["contract"] = "ocd-corpus-review-text-compare-v1"
            for role in ("left", "right"):
                pane = view[role]
                presentation = pane["presentation"]
                brief[role]["text"] = (
                    _nodes_text(presentation["document"]["nodes"])
                    if presentation and pane["availability"] == "available"
                    and pane["recorded_context"]["state"] == "exact"
                    and pane["location_state"] in {"in-range", "location-outside-range"} else None
                )
                paging = pane["paging"]
                brief[role]["next"] = None
                if paging and paging["segments"] and pane["recorded_context"]["state"] == "exact":
                    next_index = paging["segments"][-1]["index"] + 1
                    if next_index < paging["segment_count"]:
                        target = urlsplit(brief["detail"]["target"])
                        query = dict(parse_qsl(target.query))
                        query.pop("route_digest", None)
                        query.update({"representation": "text", f"{role}_segment_start": next_index,
                                      f"{role}_segment_limit": 1})
                        brief[role]["next"] = target.path + "?" + urlencode(query)
            brief["meaning"] += " Text is the readable projection of the requested segments, not exact source bytes; formatting and visual inspection require the detail view."
        return brief

    def _evidence_brief(
        self, view: dict[str, Any], work: dict[str, Any], *,
        left_range: list[int] | None, right_range: list[int] | None,
        correspondence_source: str | None, auto_page: bool = False,
    ) -> dict[str, Any]:
        """Project the admitted pair; no reads, inferred matches, or review verdicts.

        Artifact identity is introduced once and referenced by pane/paging. URLs
        retain the existing exact-identity parameters for direct continuation.
        Exceptions are never size-trimmed: the service's response bound refuses
        an oversized brief just as it refuses an oversized Compare response.
        """
        artifacts: dict[str, Any] = {}
        panes: dict[str, Any] = {}
        query: dict[str, Any] = {
            "linked": str(view["requested_linked_navigation"]).lower(),
            "correspondence": correspondence_source or "absent",
            "route_digest": view["route_digest"],
        }
        if auto_page:
            query["auto_page"] = "true"
        for role, requested_range in (("left", left_range), ("right", right_range)):
            pane = view[role]
            stage = pane["stage"]["id"]
            requested = pane["recorded_context"]["requested"]
            artifact = pane["artifact"]
            artifact_ref = None
            if artifact is not None:
                artifact_ref = role
                declaration = next(
                    item for item in work["stages"][stage]["artifacts"]
                    if (item["id"], item["version"]) == (artifact["id"], artifact["version"])
                )
                artifacts[role] = {**artifact, "member": {
                    "name": declaration.get("name"),
                    "path": declaration.get("authority_path"),
                    "bytes": declaration.get("bytes"),
                }}
            requested_ref = artifact_ref
            if requested is not None and (
                artifact is None or (requested["artifact_id"], requested["version"])
                != (artifact["id"], artifact["version"])
            ):
                requested_ref = f"{role}-requested"
                artifacts[requested_ref] = {
                    "id": requested["artifact_id"], "version": requested["version"], "sha256": None,
                }
            presentation = pane["presentation"]
            paging = pane["paging"]
            warnings: list[dict[str, Any]] = []
            for code, state, healthy, message in (
                ("availability", pane["availability"], "available", pane["message"]),
                ("recorded-context", pane["recorded_context"]["state"], "exact", pane["recorded_context"]["message"]),
                ("location", pane["location_state"], "in-range", pane["location_message"]),
            ):
                if state != healthy:
                    warnings.append({"code": code, "state": state, "message": message})
            if paging is not None:
                for segment in paging["segments"]:
                    for flag in ("oversize", "truncated"):
                        if segment.get(flag):
                            warnings.append({"code": f"segment-{flag}", "segment": segment["index"],
                                             "message": f"Segment {segment['index']} is {flag}; consult exact artifact detail."})
            # EPUB's existing renderer expresses omitted spine entries as named
            # headings. Keep those exceptions even though bodies are omitted.
            if presentation and presentation["kind"] == "epub-reader":
                for node in presentation["document"]["nodes"]:
                    if node.get("type") == "heading" and re.fullmatch(
                        r"Spine document [0-9]+ is named but not rendered", node.get("text", "")
                    ):
                        warnings.append({"code": "epub-spine-unrendered", "message": node["text"]})
            is_image = artifact is not None and artifact["media_type"].startswith("image/")
            dimensions = None if presentation is None else presentation.get("original_dimensions")
            image_info = None if presentation is None else presentation.get("native_image")
            if image_info and image_info.get("error"):
                warnings.append(image_info["error"])
            if is_image and dimensions is None:
                warnings.append({"code": "image-dimensions-unknown",
                                 "message": "Original image dimensions are not available from supported metadata; no size was inferred."})
            native = pane["native_open"]
            panes[role] = {
                "stage": pane["stage"], "artifact_ref": artifact_ref,
                "availability": pane["availability"], "warnings": warnings,
                "recorded_context": {"state": pane["recorded_context"]["state"],
                                     "artifact_ref": requested_ref,
                                     "location": None if requested is None else requested["location"]},
                "location": pane["location"], "location_state": pane["location_state"],
                "requested_range": requested_range,
                "paging": None if paging is None else {
                    key: value for key, value in paging.items() if key not in {"bound", "cache_resident"}
                },
                "presentation": None if presentation is None else {
                    key: presentation[key] for key in ("declared_kind", "kind", "render_target", "freshness", "text_encoding", "limitations") if key in presentation
                },
                "image": {
                    "selection": pane.get("image_selection"),
                    "request": pane.get("image_request"),
                    "original_dimensions": dimensions,
                    "native_image": image_info,
                    "preview_request": None if not image_info or image_info.get("error") else {
                        "variant": "preview", "expected_sha256": artifact["sha256"],
                        "address_basis": "same-origin stage image route from this pane's work/stage/artifact/version",
                    },
                    "dimensions_state": "known" if dimensions else "unknown" if is_image or artifact is None else "not-applicable",
                    "original_ref": "exact_detail" if is_image and pane["exact_fallback"] else None,
                    "presentation_available": is_image and pane["availability"] == "available",
                },
                "exact_detail": pane["exact_fallback"],
                "native_open": native,
            }
            if paging is not None:
                panes[role]["paging"]["artifact_ref"] = artifact_ref
            if requested is not None:
                query.update({f"{role}_stage": stage, f"{role}_artifact": requested["artifact_id"],
                              f"{role}_version": requested["version"], f"{role}_location": requested["location"]})
            if requested_range is not None:
                query.update({f"{role}_segment_start": requested_range[0], f"{role}_segment_limit": requested_range[1]})
            selection = pane.get("image_selection")
            if selection is not None:
                if selection["variant"] == "region":
                    query.update({f"{role}_region": selection["region"], f"{role}_image_sha256": selection["source_sha256"]})
                else:
                    query[f"{role}_image"] = selection["variant"]
        return {
            "contract": EVIDENCE_BRIEF_CONTRACT, "work": view["work"],
            "scope": work.get("scope"), "candidate_validation": work.get("candidate_validation"),
            "artifacts": artifacts, **panes,
            "requested_linked_navigation": view["requested_linked_navigation"],
            "linked_navigation": view["linked_navigation"], "link_refusal": view["link_refusal"],
            "correspondence": view["correspondence"], "route_digest": view["route_digest"],
            "detail": {"target": f"/api/review/v1/works/{quote(view["work"]["slug"], safe="")}/compare?{urlencode(query)}"},
            "bounds": {"max_response_bytes": MAX_RESPONSE_SERIALIZED_BYTES,
                       "max_segments_per_pane": PAGING_MAX_SEGMENTS_PER_REQUEST,
                       "warning_scope": "selected pane locations and requested segment windows"},
            "meaning": "Existing Compare admission/cache availability and validation bindings only; browser decode, paint, visual fidelity, and acceptance are not assessed.",
        }

SAFE_NATIVE_MEDIA_TYPES = frozenset({"application/zip", "application/gzip", "application/octet-stream", "application/pdf", "application/epub+zip", "image/jpeg", "image/png", "image/tiff", "image/webp"})


def native_open_policy(
    media_type: str | None,
    slug: str | None = None,
    stage_id: str | None = None,
    artifact_id: str | None = None,
    artifact_version: str | None = None,
) -> dict[str, Any]:
    """Classify native open; the target is the governed bytes route for allow-listed types (D3)."""
    if media_type in {"text/html", "application/xhtml+xml"}:
        return {"allowed": False, "target": None, "reason": "HTML and XHTML always remain inert inside the viewer."}
    if media_type in SAFE_NATIVE_MEDIA_TYPES:
        target = None
        if None not in (slug, stage_id, artifact_id, artifact_version):
            query = urlencode({"expected_artifact": artifact_id, "expected_version": artifact_version})
            target = f"/api/review/v1/works/{quote(slug, safe="")}/stages/{stage_id}/bytes?{query}"
        return {"allowed": True, "target": target, "reason": "This safe non-code format is eligible for an explicit local handoff."}
    return {"allowed": False, "target": None, "reason": "Native open is not allow-listed for this format." if media_type else "No selected artifact."}
