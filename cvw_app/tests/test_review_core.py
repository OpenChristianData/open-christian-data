from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import struct
import zipfile
import zlib

import pytest

from cvw_app import review_renderers

from cvw_app.review_contract import (
    MAX_RESPONSE_SERIALIZED_BYTES,
    RangeInvalidError,
    ReviewApplication,
    VerifiedIngestCache,
    _source_presentation,
    serialized_payload_size,
)
from cvw_app.review_renderers import (
    BINARY_PRESENTATION_KINDS,
    DEFAULT_RENDERER_REGISTRY,
    MAX_PAGE_SCALARS,
    MAX_PAGE_SERIALIZED_BYTES,
    RendererError,
    verify_binary_content_signature,
)


FIXTURES = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "review-v1"
    / "artifacts"
    / "binary-contract"
)


@pytest.mark.parametrize(
    ("value", "is_scalar"),
    [
        ("ordinary text", True),
        ("\uD7FF", True),
        ("\uE000", True),
        ("\U0010FFFF", True),
        ("𝔘", True),
        ("\ud800", False),
        ("\udfff", False),
        ("\ud800\udfff", False),
        ("before\ud800after", False),
        ("𝔘\udfff", False),
    ],
)
def test_unicode_scalar_guards_cover_astral_and_surrogate_boundaries(
    value: str, is_scalar: bool
) -> None:
    assert review_renderers._is_unicode_scalar_text(value) is is_scalar
    assert review_renderers.is_route_valid_scalar_text(value) is is_scalar
    if is_scalar:
        assert review_renderers.bounded_visible_text(value, 100, "Value") == value
    else:
        with pytest.raises(RendererError, match="Unicode scalar"):
            review_renderers.bounded_visible_text(value, 100, "Value")


@pytest.mark.parametrize(
    "node",
    [
        {"type": "paragraph", "text": "\ud800"},
        {"type": "heading", "text": "Heading", "level": 1, "location": "\ud800"},
    ],
)
def test_document_nodes_reject_surrogate_text_key_and_location(
    node: dict[str, object],
) -> None:
    with pytest.raises(RendererError, match="invalid document node"):
        review_renderers._validate_document_nodes([node], "document")


def test_document_nodes_reject_surrogate_key_in_valid_json_structure() -> None:
    nodes = [{
        "type": "json-object", "text": "", "children": [{
            "type": "json-property", "text": "key", "key": "key",
            "location": "property", "children": [{
                "type": "json-value", "text": "value", "value_kind": "string",
            }],
        }],
    }]
    review_renderers._validate_document_nodes(nodes, "document")
    nodes[0]["children"][0]["key"] = "\ud800"
    with pytest.raises(RendererError, match="node key"):
        review_renderers._validate_document_nodes(nodes, "document")


def test_heading_contexts_use_first_top_level_duplicate_and_preserve_boundaries() -> None:
    nodes = [
        {"type": "heading", "text": "First", "level": 1, "location": "same"},
        {"type": "paragraph", "text": "First body"},
        {"type": "heading", "text": "Second", "level": 1, "location": "same"},
    ]
    contexts = review_renderers._heading_contexts(
        nodes, [{"location": "same", "label": "Same", "level": 1}]
    )
    assert [node["text"] for node in contexts["same"]["nodes"]] == [
        "First",
        "First body",
    ]

    structural_nodes = [
        {"type": "heading", "text": "", "level": 1, "location": "outer"},
        {"type": "paragraph", "text": "Outer body"},
        {"type": "heading", "text": "Inner", "level": 2, "location": "inner"},
        {"type": "paragraph", "text": "Inner body"},
        {"type": "heading", "text": "", "level": 1, "location": "next"},
        {"type": "paragraph", "text": "Next body"},
    ]
    bounded = review_renderers._heading_contexts(
        structural_nodes,
        [
            {"location": "outer", "label": "Outer", "level": 1},
            {"location": "inner", "label": "Inner", "level": 2},
            {"location": "next", "label": "Next", "level": 1},
        ],
    )
    assert [node["text"] for node in bounded["outer"]["nodes"]] == [
        "",
        "Outer body",
        "Inner",
        "Inner body",
    ]
    assert [node["text"] for node in bounded["inner"]["nodes"]] == [
        "Inner",
        "Inner body",
    ]


def test_heading_contexts_ignores_nested_locations_and_preserves_missing_stopiteration() -> None:
    nodes = [
        {
            "type": "paragraph",
            "text": "Outer text",
            "children": [
                {"type": "heading", "text": "Nested", "level": 1, "location": "nested"}
            ],
        }
    ]
    with pytest.raises(StopIteration):
        review_renderers._heading_contexts(
            nodes, [{"location": "nested", "label": "Nested", "level": 1}]
        )
    with pytest.raises(StopIteration):
        review_renderers._heading_contexts(
            nodes, [{"location": "missing", "label": "Missing", "level": 1}]
        )


def test_retained_binary_fixtures_keep_exact_identity_and_safe_presentations() -> None:
    digests = json.loads(
        (Path(__file__).parent / "fixtures" / "binary_contract_digests.json").read_text(
            encoding="utf-8"
        )
    )
    cases = {
        "facsimile.jpg": ("image-facsimile", "image/jpeg", True, "image"),
        "facsimile.png": ("image-facsimile", "image/png", True, "image"),
        "facsimile.tiff": ("image-facsimile", "image/tiff", False, "paragraph"),
        "monograph.pdf": ("pdf-native", "application/pdf", True, "paragraph"),
        "monograph.epub": ("epub-reader", "application/epub+zip", True, "heading"),
    }

    for name, (kind, media_type, supported, first_node) in cases.items():
        payload = (FIXTURES / name).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == digests[name]
        rendered, observed_supported = DEFAULT_RENDERER_REGISTRY.render(
            kind, media_type, payload
        )
        assert observed_supported is supported
        assert rendered["nodes"][0]["type"] == first_node
        assert all(
            node["type"] not in {"script", "iframe", "object"}
            for node in rendered["nodes"]
        )


def test_non_epub_archives_are_honestly_unsupported_binary_authorities() -> None:
    cases = {
        "authority.zip": ("application/zip", b"PK\x03\x04payload"),
        "authority.jsonl.gz": ("application/gzip", b"\x1f\x8bpayload"),
    }

    assert "unsupported-binary" in BINARY_PRESENTATION_KINDS
    for name, (media_type, payload) in cases.items():
        assert _source_presentation(Path(name)) == (
            media_type,
            "unsupported-binary",
            "source-location",
        )
        verify_binary_content_signature(media_type, payload)
        rendered, supported = DEFAULT_RENDERER_REGISTRY.render(
            "unsupported-binary", media_type, payload
        )
        assert supported is False
        assert rendered["nodes"] == [
            {
                "type": "paragraph",
                "text": "Download this file to open it in another application.",
            }
        ]


def _nave_zld_context(
    entries: tuple[tuple[str, bytes], ...], selected_name: str = "dict-zdt"
) -> dict[str, bytes]:
    payloads = tuple(
        b'<entryFree n="'
        + key.encode("utf-8")
        + b'"><def>'
        + definition
        + b"</def></entryFree>\x00"
        for key, definition in entries
    )
    data_start = 4 + 8 * len(payloads)
    payload_cursor = data_start
    table = []
    for payload in payloads:
        table.append(struct.pack("<II", payload_cursor, len(payload)))
        payload_cursor += len(payload)
    plain = struct.pack("<I", len(payloads)) + b"".join(table) + b"".join(payloads)
    compressed = zlib.compress(plain) + (b"\x00" * 1_024)
    dat_records = []
    idx_records = []
    dat_cursor = 0
    for entry_number, (key, _) in enumerate(entries):
        record = key.encode("utf-8") + b"\r\n" + struct.pack("<II", 0, entry_number)
        idx_records.append(struct.pack("<II", dat_cursor, len(record)))
        dat_records.append(record + b"\r\n")
        dat_cursor += len(record) + 2
    members = {
        "dict-zdt": compressed + b"\r\n",
        "dict-zdx": struct.pack("<II", 0, len(compressed)),
        "dict-dat": b"".join(dat_records),
        "dict-idx": b"".join(idx_records),
        "nave-conf": b"[Nave]\r\nModDrv=zLD\r\n",
    }
    archive_buffer = io.BytesIO()
    archive_names = (
        ("dict-zdx", "modules/lexdict/zld/nave/dict.zdx"),
        ("dict-zdt", "modules/lexdict/zld/nave/dict.zdt"),
        ("dict-dat", "modules/lexdict/zld/nave/dict.dat"),
        ("dict-idx", "modules/lexdict/zld/nave/dict.idx"),
        ("nave-conf", "mods.d/nave.conf"),
    )
    with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for member_name, archive_name in archive_names:
            archive.writestr(archive_name, members[member_name])
    return {
        **members,
        "nave-archive": archive_buffer.getvalue(),
        "__selected_name__": selected_name.encode("ascii"),
        "__source_set_sha256__": b"8" * 64,
    }


def _small_nave_zld_context(selected_name: str = "dict-zdt") -> dict[str, bytes]:
    return _nave_zld_context(
        (
            (
                "AARON",
                b'First <ref osisRef="Gen.1.1">Genesis 1:1</ref>'
                b"<lb/><list><item>Priest</item></list>",
            ),
        ),
        selected_name,
    )


def test_sword_zld_renderer_exposes_each_exact_carrier_through_one_bound_projection() -> None:
    for selected_name in ("dict-zdt", "dict-zdx", "dict-dat", "dict-idx"):
        rendered, supported = DEFAULT_RENDERER_REGISTRY.render(
            "sword-zld-reader",
            "application/vnd.crosswire.sword-zld",
            _small_nave_zld_context(selected_name),
        )
        visible = " ".join(node["text"] for node in rendered["nodes"])
        assert supported is True
        assert rendered["kind"] == "sword-zld-reader"
        assert f"Selected exact carrier: {selected_name}" in visible
        assert "1. AARON ⟦entryFree/@n:AARON⟧" in visible
        assert "⟦osisRef:Gen.1.1⟧" in visible
        assert "• Priest" in visible

    drifted = _small_nave_zld_context()
    drifted["dict-idx"] = struct.pack("<II", 1, 15)
    with pytest.raises(RendererError, match="retained Nave ZIP differs from extracted dict-idx"):
        DEFAULT_RENDERER_REGISTRY.render(
            "sword-zld-reader",
            "application/vnd.crosswire.sword-zld",
            drifted,
        )


def test_sword_zld_oversize_rows_page_without_losing_any_arrow_marker() -> None:
    repeated_markers = ("→ marker " * 7_202).strip().encode("utf-8")
    context = _nave_zld_context(
        (
            ("AARON", b"First dictionary record."),
            ("GOD", repeated_markers),
            ("JAPHLET", b"Middle dictionary record."),
            ("JESUS", repeated_markers),
            ("ZUZIMS", b"Terminal dictionary record."),
        )
    )

    rendered, supported = DEFAULT_RENDERER_REGISTRY.render(
        "sword-zld-reader",
        "application/vnd.crosswire.sword-zld",
        context,
    )

    logical_text = " ".join(node["text"] for node in rendered["nodes"])
    served_nodes = [node for page in rendered["_pages"] for node in page]
    served_text = " ".join(node["text"] for node in served_nodes)
    assert supported is True
    assert logical_text.count("→") == 14_404
    assert served_text.count("→") == 14_404
    assert served_text == logical_text
    assert all(segment["scalar_count"] <= MAX_PAGE_SCALARS for segment in rendered["segments"])
    assert all("oversize" not in segment for segment in rendered["segments"])
    assert all("truncated" not in segment for segment in rendered["segments"])
    assert sum(node["text"].startswith("2. GOD ") for node in served_nodes) == 1
    assert sum(node["text"].startswith("4. JESUS ") for node in served_nodes) == 1


def test_html_and_tei_are_rendered_as_inert_typed_content() -> None:
    html, supported = DEFAULT_RENDERER_REGISTRY.render(
        "sanitized-html",
        "text/html",
        '<h1>Retained title</h1><script>alert(1)</script><p onclick="bad()">Text</p>',
    )
    assert supported is True
    assert "alert(1)" not in json.dumps(html)
    assert "onclick" not in json.dumps(html)

    tei, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader",
        "application/tei+xml",
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><p>Faithful text.</p></body></text></TEI>',
    )
    assert supported is True
    assert "Faithful text." in json.dumps(tei)


def test_tei_corpus_renders_each_child_work_as_inert_typed_content() -> None:
    tei, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader",
        "application/tei+xml",
        (
            '<teiCorpus xmlns="http://www.tei-c.org/ns/1.0">'
            "<teiHeader><fileDesc><titleStmt><title>Corpus metadata</title></titleStmt>"
            "<publicationStmt><p>Unpublished.</p></publicationStmt>"
            "<sourceDesc><p>Retained sources.</p></sourceDesc></fileDesc></teiHeader>"
            '<TEI xml:id="first"><text><body><div xml:id="first-work">'
            "<head>First Work</head><p>First faithful body.</p>"
            "</div></body></text></TEI>"
            '<TEI xml:id="second"><text><body><div xml:id="second-work">'
            "<head>Second Work</head><p>Second faithful body.</p>"
            "</div></body></text></TEI>"
            "</teiCorpus>"
        ),
    )

    assert supported is True
    assert [item["label"] for item in tei["outline"]] == [
        "First Work",
        "Second Work",
    ]
    visible = json.dumps(tei)
    assert "First faithful body." in visible
    assert "Second faithful body." in visible
    assert "Corpus metadata" not in visible
    assert len(tei["segments"]) == 2
    assert tei["segments"][0]["locations"] == ["first-work"]
    assert tei["segments"][1]["locations"] == ["second-work"]
    assert tei["_pages"][0][0]["text"] == "First Work"
    assert tei["_pages"][1][0]["text"] == "Second Work"


def test_tei_corpus_boundaries_survive_detached_internal_pages() -> None:
    exact = (
        '<teiCorpus xmlns="http://www.tei-c.org/ns/1.0">'
        "<TEI><text><body><p>First work.</p></body></text></TEI>"
        "<TEI><text><body><p>Second work.</p></body></text></TEI>"
        "</teiCorpus>"
    )
    rendered = review_renderers.render_tei("application/tei+xml", exact)
    rendered["_pages"] = deepcopy(rendered["_pages"])

    validated = review_renderers._validate_renderer_output(rendered)

    assert len(validated["segments"]) == 2
    assert validated["_pages"][0][0]["text"] == "First work."
    assert validated["_pages"][1][0]["text"] == "Second work."


def test_non_corpus_renderer_cannot_invent_internal_page_boundaries() -> None:
    rendered = review_renderers.render_sanitized_html(
        "text/html", "<p>First block.</p><p>Second block.</p>"
    )
    assert len(rendered["segments"]) == 1
    rendered["_pages"] = [[rendered["nodes"][0]], [rendered["nodes"][1]]]

    with pytest.raises(
        RendererError, match="internal pages do not match canonical segmentation"
    ):
        review_renderers._validate_renderer_output(rendered)


def test_tei_corpus_empty_child_fails_honestly() -> None:
    exact = (
        '<teiCorpus xmlns="http://www.tei-c.org/ns/1.0">'
        "<TEI><text><body><p>First work.</p></body></text></TEI>"
        "<TEI><text><body/></text></TEI>"
        "</teiCorpus>"
    )

    with pytest.raises(RendererError, match="child has no readable content"):
        DEFAULT_RENDERER_REGISTRY.render("tei-reader", "application/tei+xml", exact)


def test_large_tei_dictionary_is_losslessly_pageable_by_entry(
    tmp_path: Path,
) -> None:
    entries = "".join(
        (
            f'<entry xml:id="entry-{ordinal:04d}" n="{ordinal}">'
            f"<form><orth>Term {ordinal:04d}</orth></form>"
            f"<sense><def>Definition {ordinal:04d} {'x' * 48}</def></sense>"
            "</entry>"
        )
        for ordinal in range(1, 3_964)
    )
    exact = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
        f"{entries}</body></text></TEI>"
    )

    artifact_path = tmp_path / "dictionary.tei.xml"
    artifact_path.write_text(exact, encoding="utf-8")
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    artifact_id = f"tei-{digest}"
    application = ReviewApplication(
        {
            "works": [
                {
                    "slug": "dictionary",
                    "title": "Dictionary",
                    "creator": "Retained source",
                    "scope": "work",
                    "correspondence_sources": [],
                    "stages": {
                        "source": {"artifacts": []},
                        "tei": {
                            "selected_artifact_id": artifact_id,
                            "artifacts": [
                                {
                                    "id": artifact_id,
                                    "version": digest,
                                    "root": "candidate",
                                    "path": artifact_path.name,
                                    "sha256": digest,
                                    "media_type": "application/tei+xml",
                                    "presentation_kind": "tei-reader",
                                    "location_kind": "tei-anchor",
                                }
                            ],
                        },
                        "json": {"artifacts": []},
                    },
                }
            ]
        },
        {"candidate": tmp_path},
        DEFAULT_RENDERER_REGISTRY,
    )

    first = application.stage_view(
        "dictionary", "tei", segment_start=0, segment_limit=1
    )
    segment_count = first["paging"]["segment_count"]
    views = [
        application.stage_view(
            "dictionary", "tei", segment_start=index, segment_limit=1
        )
        for index in range(segment_count)
    ]
    segments = [view["paging"]["segments"][0] for view in views]
    nodes = [
        node for view in views for node in view["presentation"]["document"]["nodes"]
    ]

    def has_private_metadata(value: object) -> bool:
        if isinstance(value, dict):
            return any(
                key.startswith("_") or has_private_metadata(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(has_private_metadata(item) for item in value)
        return False

    assert segment_count > 1
    assert first["paging"]["max_segments_per_request"] == 1
    assert [segment["index"] for segment in segments] == list(range(segment_count))
    assert len(nodes) == 3_963
    assert nodes[0]["text"].startswith("Term 0001 Definition 0001")
    assert nodes[-1]["text"].startswith("Term 3963 Definition 3963")
    assert all(segment["scalar_count"] <= MAX_PAGE_SCALARS for segment in segments)
    assert all("oversize" not in segment for segment in segments)
    assert all("truncated" not in segment for segment in segments)
    assert all(
        serialized_payload_size(view) <= MAX_RESPONSE_SERIALIZED_BYTES for view in views
    )
    assert all(not has_private_metadata(view) for view in views)


def test_oversized_outline_is_discoverable_in_bounded_identity_bound_pages(
    tmp_path: Path,
) -> None:
    exact = "".join(
        f'<h2 id="location-{index:04d}">Location {index:04d} {"x" * 180}</h2>'
        f"<p>Body {index:04d}.</p>"
        for index in range(1, 501)
    )
    artifact_path = tmp_path / "oversized.html"
    artifact_path.write_text(exact, encoding="utf-8")
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    artifact_id = f"source-{digest}"
    application = ReviewApplication(
        {
            "works": [
                {
                    "slug": "oversized",
                    "title": "Oversized outline",
                    "creator": "Retained source",
                    "scope": "work",
                    "correspondence_sources": [],
                    "stages": {
                        "source": {
                            "selected_artifact_id": artifact_id,
                            "artifacts": [
                                {
                                    "id": artifact_id,
                                    "version": digest,
                                    "root": "source",
                                    "path": artifact_path.name,
                                    "sha256": digest,
                                    "media_type": "text/html",
                                    "presentation_kind": "sanitized-html",
                                    "location_kind": "html-anchor",
                                }
                            ],
                        },
                        "tei": {"artifacts": []},
                    },
                }
            ]
        },
        {"source": tmp_path},
        DEFAULT_RENDERER_REGISTRY,
    )

    view = application.stage_view("oversized", "source")
    assert view["outline_metadata"]["truncated"] is True
    assert view["outline_metadata"]["total"] == 500
    assert view["outline_metadata"]["returned"] == 0
    locations = application.locations(
        "oversized",
        "source",
        expected_artifact=artifact_id,
        expected_version=digest,
        offset=1,
        limit=2,
    )
    assert locations["artifact"] == {"id": artifact_id, "version": digest, "sha256": digest}
    assert locations["total"] == locations["matched"] == 500
    assert locations["returned"] == 2
    assert locations["next_offset"] == 3
    assert [item["label"] for item in locations["locations"]] == [
        "Location 0002 " + "x" * 180,
        "Location 0003 " + "x" * 180,
    ]
    drifted = application.locations(
        "oversized",
        "source",
        expected_artifact="stale-artifact",
        expected_version="stale-version",
        limit=2,
    )
    assert drifted["availability"] == "unsupported"
    assert drifted["artifact"] is None
    assert drifted["total"] == drifted["matched"] == drifted["returned"] == 0
    assert drifted["locations"] == []
    assert "current declared authority" in drifted["message"]
    searched = application.locations(
        "oversized",
        "source",
        expected_artifact=artifact_id,
        expected_version=digest,
        limit=10,
        search="Location 0499",
    )
    assert searched["matched"] == searched["returned"] == 1
    assert searched["locations"][0]["location"] == "location-0499"
    with pytest.raises(RangeInvalidError, match="offset exceeds"):
        application.locations(
            "oversized",
            "source",
            expected_artifact=artifact_id,
            expected_version=digest,
            offset=501,
        )


def test_location_page_bound_keeps_maximal_unicode_labels_within_response_budget(
    tmp_path: Path,
) -> None:
    label = "𝔘" * 512
    exact = "".join(
        f'<h2 id="unicode-{index:02d}">{label}</h2><p>Body {index:02d}.</p>'
        for index in range(40)
    )
    artifact_path = tmp_path / "unicode.html"
    artifact_path.write_text(exact, encoding="utf-8")
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    artifact_id = f"source-{digest}"
    application = ReviewApplication(
        {
            "works": [{
                "slug": "unicode",
                "title": "Unicode outline",
                "creator": "Retained source",
                "scope": "work",
                "correspondence_sources": [],
                "stages": {
                    "source": {
                        "selected_artifact_id": artifact_id,
                        "artifacts": [{
                            "id": artifact_id,
                            "version": digest,
                            "root": "source",
                            "path": artifact_path.name,
                            "sha256": digest,
                            "media_type": "text/html",
                            "presentation_kind": "sanitized-html",
                            "location_kind": "html-anchor",
                        }],
                    },
                    "tei": {"artifacts": []},
                },
            }],
        },
        {"source": tmp_path},
        DEFAULT_RENDERER_REGISTRY,
    )

    locations = application.locations(
        "unicode",
        "source",
        expected_artifact=artifact_id,
        expected_version=digest,
    )
    assert locations["returned"] == 32
    assert locations["next_offset"] == 32
    assert serialized_payload_size(locations) <= MAX_RESPONSE_SERIALIZED_BYTES


def test_tei_exact_retained_source_byte_carrier_is_verified_and_disclosed() -> None:
    retained = b"<ThML><ThML.body><p>Retained words.</p></ThML.body></ThML>"
    encoded = base64.b64encode(retained).decode("ascii")
    digest = hashlib.sha256(retained).hexdigest()
    exact = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div>'
        "<head>Readable work</head>"
        f'<ab type="exact-retained-source-bytes" subtype="base64" n="{digest}">{encoded}</ab>'
        "<p>Faithfully reconstructed words.</p>"
        "</div></body></text></TEI>"
    )

    rendered, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader", "application/tei+xml", exact
    )

    assert supported is True
    serialized = json.dumps(rendered)
    assert encoded not in serialized
    assert f"{len(retained)} decoded bytes" in serialized
    assert f"SHA-256 {digest}" in serialized
    assert "Faithfully reconstructed words." in serialized
    assert all(not segment.get("truncated") for segment in rendered["segments"])

    drifted = exact.replace(digest, "0" * 64)
    with pytest.raises(
        RendererError,
        match="does not match its declared SHA-256",
    ):
        DEFAULT_RENDERER_REGISTRY.render("tei-reader", "application/tei+xml", drifted)


def _tei_with_base64_application_json(retained: bytes, digest: str) -> str:
    encoded = base64.b64encode(retained).decode("ascii")
    return (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        '<teiHeader><fileDesc><sourceDesc><bibl>'
        f'<idno type="sha256">{digest}</idno>'
        '</bibl></sourceDesc></fileDesc></teiHeader>'
        '<text><body><div type="retained-json-document">'
        '<head>Readable JSON work</head>'
        '<div type="retained-byte-stream">'
        f'<ab type="base64-application-json">{encoded}</ab>'
        '</div><div type="json-semantic-tree"><p>Readable semantic tree.</p></div>'
        '</div></body></text></TEI>'
    )


def test_tei_base64_application_json_carrier_is_verified_and_disclosed() -> None:
    retained = b'{\r\n  "Metadata": {"Title": "Retained work"},\r\n  "Data": []\r\n}'
    digest = hashlib.sha256(retained).hexdigest()
    encoded = base64.b64encode(retained).decode("ascii")
    exact = _tei_with_base64_application_json(retained, digest)

    rendered, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader", "application/tei+xml", exact
    )

    serialized = json.dumps(rendered)
    assert supported is True
    assert encoded not in serialized
    assert f"{len(retained)} decoded bytes" in serialized
    assert f"SHA-256 {digest}" in serialized
    assert f"{len(encoded)} encoded scalars" in serialized
    assert "valid UTF-8 JSON" in serialized
    assert "Readable semantic tree." in serialized
    assert not any("canonical base64 carrier" in node.get("text", "") for node in rendered["nodes"])
    assert any("canonical base64 carrier" in detail for detail in rendered["limitations"])
    assert all(not segment.get("oversize") for segment in rendered["segments"])
    assert all(not segment.get("truncated") for segment in rendered["segments"])


def test_accepted_json_carrier_allows_repeated_identical_source_digest_only() -> None:
    retained = b'{"Data":[]}'
    digest = hashlib.sha256(retained).hexdigest()
    exact = _tei_with_base64_application_json(retained, digest)
    extra = f'<bibl type="ocd-acceptance-binding"><idno type="sha256">{digest}</idno></bibl>'
    accepted = exact.replace('</sourceDesc>', extra + '</sourceDesc>')
    assert accepted != exact
    rendered, supported = DEFAULT_RENDERER_REGISTRY.render("tei-reader", "application/tei+xml", accepted)
    assert supported and digest in json.dumps(rendered)
    with pytest.raises(RendererError, match="requires one lowercase source SHA-256"):
        DEFAULT_RENDERER_REGISTRY.render("tei-reader", "application/tei+xml", exact.replace('</sourceDesc>', extra.replace(digest, 'f' * 64) + '</sourceDesc>'))


def test_epub_renders_a_whole_115_document_book_inside_the_archive_budget(tmp_path: Path) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('mimetype', 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        archive.writestr('META-INF/container.xml', '<container><rootfiles><rootfile full-path="content.opf"/></rootfiles></container>')
        items = ''.join(f'<item id="p{i}" href="p{i}.html" media-type="application/xhtml+xml"/>' for i in range(115))
        spine = ''.join(f'<itemref idref="p{i}"/>' for i in range(115))
        archive.writestr('content.opf', f'<package><manifest>{items}</manifest><spine>{spine}</spine></package>')
        for index in range(115):
            heading = f'<h1>Chapter {index + 1}</h1>' if index < 114 else ''
            archive.writestr(f'p{index}.html', f'<html><body>{heading}<p>Retained text {index + 1}.</p></body></html>')
    rendered, supported = DEFAULT_RENDERER_REGISTRY.render("epub-reader", "application/epub+zip", output.getvalue())
    assert supported and len(rendered['outline']) == 115
    assert rendered['outline'][-1]['label'] == 'Part 115: p114.html'
    assert 'Retained text 115.' in json.dumps(rendered['nodes'])
    assert not any('unrendered' in item['location'] for item in rendered['outline'])
    path = tmp_path / 'book.epub'
    path.write_bytes(output.getvalue())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    application = ReviewApplication({'works': [{
        'slug': 'epub', 'title': 'Whole EPUB', 'creator': 'Retained source', 'scope': 'work', 'correspondence_sources': [],
        'stages': {'source': {'selected_artifact_id': 'source', 'artifacts': [dict(id='source', version=digest,
            root='source', path=path.name, sha256=digest, media_type='application/epub+zip', presentation_kind='epub-reader', location_kind='spine-location')]}, 'tei': {'artifacts': []}},
    }]}, {'source': tmp_path}, DEFAULT_RENDERER_REGISTRY)
    matches = application.locations('epub', 'source', expected_artifact='source', expected_version=digest, search='Retained text 115')
    assert [item['location'] for item in matches['locations']] == [rendered['outline'][-1]['location']]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("invalid-base64", "not valid base64"),
        ("noncanonical-base64", "not canonical base64"),
        ("invalid-utf8", "not UTF-8"),
        ("invalid-json", "does not decode to valid JSON"),
        ("wrong-source", "does not match the enclosing source SHA-256"),
        ("topology", "topology drifted"),
    ],
)
def test_tei_base64_application_json_carrier_fails_closed(
    mutation: str, message: str
) -> None:
    retained = b'{"Data":[]}'
    digest = hashlib.sha256(retained).hexdigest()
    exact = _tei_with_base64_application_json(retained, digest)
    if mutation == "invalid-base64":
        exact = exact.replace(base64.b64encode(retained).decode("ascii"), "!invalid!")
    elif mutation == "noncanonical-base64":
        encoded = base64.b64encode(retained).decode("ascii")
        assert encoded.endswith("0=")
        exact = exact.replace(encoded, encoded[:-2] + "1=")
    elif mutation == "invalid-utf8":
        invalid = b"\xff"
        exact = _tei_with_base64_application_json(
            invalid, hashlib.sha256(invalid).hexdigest()
        )
    elif mutation == "invalid-json":
        invalid = b'{"Data":NaN}'
        exact = _tei_with_base64_application_json(
            invalid, hashlib.sha256(invalid).hexdigest()
        )
    elif mutation == "wrong-source":
        exact = _tei_with_base64_application_json(b'{"Data":[1]}', digest)
    else:
        exact = exact.replace(
            '<ab type="base64-application-json">',
            '<ab type="base64-application-json" n="invented">',
        )

    with pytest.raises(RendererError, match=message):
        DEFAULT_RENDERER_REGISTRY.render(
            "tei-reader", "application/tei+xml", exact
        )


def test_tei_readable_source_heading_and_xml_node_ledger_are_bounded() -> None:
    record = {
        "attributes": [],
        "feature_id": "source-node-000001",
        "kind": "element",
        "namespace_declarations": [],
        "ordinal": 1,
        "parent_ordinal": None,
        "pi_target": None,
        "qname": "ThML",
        "scope": "tree",
        "sibling_ordinal": 1,
        "tail": "",
        "text": "",
    }
    record["payload_sha256"] = hashlib.sha256(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
    exact = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div>'
        '<div type="readable-transcription"><ab type="source-heading" subtype="h2" '
        'corresp="#source-node-000002">Readable source heading</ab>'
        '<p corresp="#source-node-000003">Faithful body.</p></div>'
        '<div type="complete-xml-node-transcription">'
        f'<ab xml:id="source-node-000001" type="source-xml-node" subtype="element" n="1">{payload}</ab>'
        "</div></div></body></text></TEI>"
    )

    rendered, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader", "application/tei+xml", exact
    )

    assert supported is True
    assert [item["label"] for item in rendered["outline"]] == [
        "Readable source heading"
    ]
    visible = json.dumps(rendered)
    assert "Faithful body." in visible
    assert "Complete XML node ledger: 1 identity-bound records verified." in visible
    assert payload not in visible

    drifted_record = {**record, "text": "invented"}
    drifted_payload = json.dumps(drifted_record, sort_keys=True, separators=(",", ":"))
    with pytest.raises(RendererError, match="payload digest drifted"):
        DEFAULT_RENDERER_REGISTRY.render(
            "tei-reader",
            "application/tei+xml",
            exact.replace(payload, drifted_payload),
        )


def test_tei_source_preservation_blocks_remain_readable() -> None:
    tei, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader",
        "application/tei+xml",
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>
        <div xml:id="easter"><head>Easter-Day.</head><div type="collect">
        <head xml:id="collect">The Collect.</head><ab type="source-block">
        <seg type="drop-cap">A</seg><seg type="source-text">LMIGHTY God, who through thine only-begotten Son</seg>
        <lb/><seg type="source-text">hast overcome death.</seg></ab></div></div>
        </body></text></TEI>""",
    )

    assert supported is True
    visible = json.dumps(tei)
    assert (
        "ALMIGHTY God, who through thine only-begotten Son hast overcome death."
        in visible
    )
    assert [node["text"] for node in tei["nodes"]].count(
        "ALMIGHTY God, who through thine only-begotten Son hast overcome death."
    ) == 1


def test_tei_epigraph_and_closer_follow_handled_nodes_in_document_order() -> None:
    tei, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader",
        "application/tei+xml",
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>
        <div xml:id="sermon">
          <head>The sacred words chosen for this occasion.</head>
          <epigraph>
            <bibl>Romans VI. 23.</bibl>
            <q>For the wages of sin is death, but the gift of God is eternal life.</q>
          </epigraph>
          <p>Prose follows the scripture quotation.</p>
          <closer>AMEN.</closer>
        </div>
        </body></text></TEI>""",
    )

    assert supported is True
    assert [(node["type"], node["text"]) for node in tei["nodes"]] == [
        ("heading", "The sacred words chosen for this occasion."),
        (
            "paragraph",
            "Romans VI. 23. For the wages of sin is death, but the gift of God is eternal life.",
        ),
        ("paragraph", "Prose follows the scripture quotation."),
        ("paragraph", "AMEN."),
    ]


def test_tei_mixed_unhandled_wrapper_text_and_tails_keep_document_order() -> None:
    tei, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader",
        "application/tei+xml",
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div>
        Prefix text.
        <wrapper>Before the nested marker.
          <span>middle unhandled text.</span>
          <head>Nested heading.</head>
          After the nested heading.
        </wrapper>
        Outer tail text.
        <p>Prose text.</p>
        Ending tail text.
        </div></body></text></TEI>""",
    )

    assert supported is True
    assert [(node["type"], node["text"]) for node in tei["nodes"]] == [
        ("paragraph", "Prefix text."),
        ("paragraph", "Before the nested marker. middle unhandled text."),
        ("heading", "Nested heading."),
        ("paragraph", "After the nested heading."),
        ("paragraph", "Outer tail text."),
        ("paragraph", "Prose text."),
        ("paragraph", "Ending tail text."),
    ]


def test_tei_empty_gap_rend_markers_stay_in_heading_and_prose_order() -> None:
    tei, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader",
        "application/tei+xml",
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div>
        <head>Oluadah Equiano or GUSTAVUS VASSA, <gap reason="illegible"
        extent="1 span" rend="〈…〉"/></head>
        <p>Published <gap reason="illegible" extent="1 span" rend="〈…〉"/></p>
        <p>The retained prose follows.</p>
        </div></body></text></TEI>""",
    )

    assert supported is True
    assert [(node["type"], node["text"]) for node in tei["nodes"]] == [
        ("heading", "Oluadah Equiano or GUSTAVUS VASSA, 〈…〉"),
        ("paragraph", "Published 〈…〉"),
        ("paragraph", "The retained prose follows."),
    ]
    assert json.dumps(tei["nodes"], ensure_ascii=False).count("〈…〉") == 2


def test_tei_empty_gap_without_display_is_honest_and_nonempty_gap_is_not_duplicated() -> None:
    tei, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader",
        "application/tei+xml",
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><p>
        Before <gap reason="illegible" extent="1 word"/> after
        <gap desc="editorial note" rend="〈…〉">retained text</gap>.
        </p></body></text></TEI>""",
    )

    assert supported is True
    assert [node["text"] for node in tei["nodes"]] == [
        "Before [illegible gap; extent 1 word] after retained text."
    ]
    visible = json.dumps(tei, ensure_ascii=False)
    assert "〈…〉" not in visible
    assert "editorial note" not in visible
    assert "missing" not in visible


def test_tei_index_table_keeps_blank_cells_in_source_column_positions() -> None:
    tei, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader",
        "application/tei+xml",
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>
        <table>
          <row><cell role="label">Chapter</cell><cell role="label">Verse</cell>
            <cell role="label">Vol.</cell><cell role="label">Page</cell></row>
          <row><cell>i</cell><cell>5</cell><cell></cell><cell>472</cell></row>
          <row><cell></cell><cell>6</cell><cell>1</cell><cell>453</cell></row>
        </table>
        </body></text></TEI>""",
    )

    assert supported is True
    table = tei["nodes"][0]
    assert table["type"] == "table"
    assert [
        [cell["text"] for cell in row["children"]]
        for row in table["children"]
    ] == [
        ["Chapter", "Verse", "Vol.", "Page"],
        ["i", "5", "", "472"],
        ["", "6", "1", "453"],
    ]


def test_html_table_preserves_explicit_rows_blank_cells_and_spans() -> None:
    html, supported = DEFAULT_RENDERER_REGISTRY.render(
        "sanitized-html",
        "text/html",
        """<table>
          <tr><td rowspan="2">A</td><td>B</td></tr>
          <tr></tr>
          <tr><td colspan="2" rowspan="1">INTRODUCTION.</td></tr>
          <tr><th>&nbsp;</th><th>PAGE</th></tr>
        </table>""",
    )

    assert supported is True
    table = html["nodes"][0]
    assert len(table["children"]) == 4
    assert table["children"][0]["children"][0] == {
        "type": "table-cell",
        "text": "A",
        "rowspan": 2,
    }
    assert table["children"][1]["children"] == []
    assert table["children"][2]["children"][0] == {
        "type": "table-cell",
        "text": "INTRODUCTION.",
        "colspan": 2,
    }
    assert [cell["text"] for cell in table["children"][3]["children"]] == [
        "\u00a0",
        "PAGE",
    ]


def test_html_table_spans_allow_long_leading_zeros_and_exact_bounds() -> None:
    colspan = "0" * 5_000 + "1000"
    rowspan = "0" * 5_000 + "65534"
    html, supported = DEFAULT_RENDERER_REGISTRY.render(
        "sanitized-html",
        "text/html",
        f'<table><tr><td colspan="{colspan}" rowspan="{rowspan}">x</td></tr></table>',
    )

    assert supported is True
    cell = html["nodes"][0]["children"][0]["children"][0]
    assert cell["colspan"] == 1000
    assert cell["rowspan"] == 65534


def test_tei_table_preserves_explicit_rows_and_maps_bounded_spans() -> None:
    tei, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader",
        "application/tei+xml",
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>
        <table>
          <row><cell cols="0002" rows="1">INTRODUCTION.</cell><cell>body</cell></row>
          <row></row>
          <row><cell>&#160;</cell><cell role="label" ana="#source-tag">PAGE</cell></row>
        </table>
        </body></text></TEI>""",
    )

    assert supported is True
    table = tei["nodes"][0]
    assert len(table["children"]) == 3
    assert table["children"][0]["children"][0] == {
        "type": "table-cell",
        "text": "INTRODUCTION.",
        "colspan": 2,
    }
    assert table["children"][1]["children"] == []
    assert [cell["text"] for cell in table["children"][2]["children"]] == [
        "\u00a0",
        "PAGE",
    ]
    assert table["children"][2]["children"][1]["scope"] == "row"


def test_tei_table_accepts_rows_greater_than_one() -> None:
    tei, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader",
        "application/tei+xml",
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>
        <table><row><cell cols="0002" rows="0002">x</cell></row></table>
        </body></text></TEI>""",
    )

    assert supported is True
    assert tei["nodes"][0]["children"][0]["children"][0] == {
        "type": "table-cell",
        "text": "x",
        "colspan": 2,
        "rowspan": 2,
    }


@pytest.mark.parametrize("attribute", ["colspan", "rowspan"])
def test_table_spans_reject_huge_significant_digits(attribute: str) -> None:
    value = "1" * 5_000
    exact = f'<table><tr><td {attribute}="{value}">x</td></tr></table>'

    with pytest.raises(RendererError, match="table .*span"):
        DEFAULT_RENDERER_REGISTRY.render("sanitized-html", "text/html", exact)


@pytest.mark.parametrize(
    ("kind", "media_type", "exact"),
    [
        ("sanitized-html", "text/html", '<table><tr><td colspan="0">x</td></tr></table>'),
        ("sanitized-html", "text/html", '<table><tr><td colspan="1001">x</td></tr></table>'),
        ("sanitized-html", "text/html", '<table><tr><td rowspan="65535">x</td></tr></table>'),
        ("sanitized-html", "text/html", '<table><tr><td colspan>x</td></tr></table>'),
        ("sanitized-html", "text/html", '<table><tr><td rowspan>x</td></tr></table>'),
        ("sanitized-html", "text/html", '<table><tr><td colspan="2" colspan="3">x</td></tr></table>'),
        ("sanitized-html", "text/html", '<table><tr><td colspan="２">x</td></tr></table>'),
        ("sanitized-html", "text/html", '<table><tr><td colspan="\v2">x</td></tr></table>'),
        ("tei-reader", "application/tei+xml", '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><table><row><cell cols="-1">x</cell></row></table></body></text></TEI>'),
        ("tei-reader", "application/tei+xml", '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><table><row><cell rows="65535">x</cell></row></table></body></text></TEI>'),
        ("tei-reader", "application/tei+xml", '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><table><row><cell cols="1.5">x</cell></row></table></body></text></TEI>'),
        ("tei-reader", "application/tei+xml", '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><table><row><cell rows="２">x</cell></row></table></body></text></TEI>'),
    ],
)
def test_table_spans_fail_closed_at_the_artifact_boundary(
    kind: str,
    media_type: str,
    exact: str,
) -> None:
    with pytest.raises(RendererError, match="table .*span"):
        DEFAULT_RENDERER_REGISTRY.render(kind, media_type, exact)


@pytest.mark.parametrize(
    "nodes",
    [
        [{"type": "paragraph", "text": "bad", "colspan": 2}],
        [{
            "type": "table",
            "text": "",
            "children": [{
                "type": "table-row",
                "text": "",
                "children": [{"type": "table-cell", "text": "bad", "rowspan": True}],
            }],
        }],
        [{
            "type": "table",
            "text": "",
            "children": [{
                "type": "table-row",
                "text": "",
                "children": [{"type": "table-cell", "text": "bad", "rowspan": 65535}],
            }],
        }],
    ],
)
def test_document_nodes_reject_ungoverned_or_invalid_table_spans(
    nodes: list[dict[str, object]],
) -> None:
    with pytest.raises(RendererError, match="table .*span"):
        review_renderers._validate_document_nodes(nodes, "document")


def test_tei_table_pages_bound_serialized_compare_without_splitting_rows(
    tmp_path: Path,
) -> None:
    table_count = 1_200
    exact = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
        '<div xml:id="table-index"><head>Calvin index</head>'
        + "".join(
            f"<table><row><cell>Chapter {ordinal // 10}</cell>"
            f"<cell>Verse {ordinal}</cell><cell></cell>"
            f"<cell>Page {ordinal}</cell></row></table>"
            for ordinal in range(1, table_count + 1)
        )
        + "</div></body></text></TEI>"
    )
    artifact_path = tmp_path / "table-heavy.tei.xml"
    artifact_path.write_text(exact, encoding="utf-8")
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()

    def artifact(artifact_id: str) -> dict[str, str]:
        return {
            "id": artifact_id,
            "version": digest,
            "root": "candidate",
            "path": artifact_path.name,
            "sha256": digest,
            "media_type": "application/tei+xml",
            "presentation_kind": "tei-reader",
            "location_kind": "tei-anchor",
        }

    source_id = f"source-{digest}"
    tei_id = f"tei-{digest}"
    manifest = {
        "works": [
            {
                "slug": "table-heavy",
                "title": "Table-heavy work",
                "creator": "Retained source",
                "scope": "work",
                "correspondence_sources": [],
                "stages": {
                    "source": {
                        "selected_artifact_id": source_id,
                        "artifacts": [artifact(source_id)],
                    },
                    "tei": {
                        "selected_artifact_id": tei_id,
                        "artifacts": [artifact(tei_id)],
                    },
                    "json": {"artifacts": []},
                },
            }
        ]
    }
    application = ReviewApplication(
        manifest,
        {"candidate": tmp_path},
        DEFAULT_RENDERER_REGISTRY,
    )

    rendered, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader", "application/tei+xml", exact
    )
    assert supported is True
    assert len(rendered["_pages"]) > 1
    assert all(
        serialized_payload_size(page) <= MAX_PAGE_SERIALIZED_BYTES
        for page in rendered["_pages"]
    )

    tables = [
        node
        for page in rendered["_pages"]
        for node in page
        if node["type"] == "table"
    ]
    assert len(tables) == table_count
    assert all(len(table["children"]) == 1 for table in tables)
    assert [
        [cell["text"] for cell in table["children"][0]["children"]]
        for table in tables
    ] == [
        [
            f"Chapter {ordinal // 10}",
            f"Verse {ordinal}",
            "",
            f"Page {ordinal}",
        ]
        for ordinal in range(1, table_count + 1)
    ]

    compare = application.compare_view(
        "table-heavy",
        left_stage="source",
        left_recorded=(source_id, digest, "table-index"),
        right_stage="tei",
        right_recorded=(tei_id, digest, "table-index"),
        linked=False,
        correspondence_source=None,
        left_segment_start=0,
        left_segment_limit=1,
        right_segment_start=0,
        right_segment_limit=1,
    )
    assert serialized_payload_size(compare) <= MAX_RESPONSE_SERIALIZED_BYTES


def test_tei_line_break_preserves_word_boundary_without_serialization_whitespace() -> (
    None
):
    tei, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader",
        "application/tei+xml",
        (
            '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
            "<ab>United States and<lb/>most other parts</ab>"
            "</body></text></TEI>"
        ),
    )

    assert supported is True
    assert [node["text"] for node in tei["nodes"]] == [
        "United States and most other parts"
    ]


def test_tei_nonbreaking_line_break_preserves_joined_word() -> None:
    tei, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader",
        "application/tei+xml",
        (
            '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
            '<ab>word<lb break="no"/>wrap</ab>'
            "</body></text></TEI>"
        ),
    )

    assert supported is True
    assert [node["text"] for node in tei["nodes"]] == ["wordwrap"]


def test_tei_inline_note_stays_visibly_separate_at_its_source_position() -> None:
    tei, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader",
        "application/tei+xml",
        (
            '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
            "<p>A. An act of the"
            "<note><p>The resurrection of Christ.</p></note>"
            " mighty power of God.</p>"
            "</body></text></TEI>"
        ),
    )

    assert supported is True
    assert [(node["type"], node["text"]) for node in tei["nodes"]] == [
        ("paragraph", "A. An act of the"),
        ("blockquote", "The resurrection of Christ."),
        ("paragraph", "mighty power of God."),
    ]
    assert "theThe resurrection" not in json.dumps(tei)


def test_tei_entry_free_rows_are_keyed_lossless_and_bounded() -> None:
    repeated_markers = ("→ marker " * 7_202).strip()
    entries = (
        ("AARON", "First dictionary record."),
        ("GOD", repeated_markers),
        ("JAPHLET", "Middle dictionary record."),
        ("JESUS", repeated_markers),
        ("ZUZIMS", "Terminal dictionary record."),
    )
    exact = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
        + "".join(
            f'<entryFree n="{key}"><form><orth>{key}</orth></form>'
            f"<def>{definition}</def></entryFree>"
            for key, definition in entries
        )
        + "</body></text></TEI>"
    )

    rendered, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader", "application/tei+xml", exact
    )

    logical_text = " ".join(node["text"] for node in rendered["nodes"])
    served_nodes = [node for page in rendered["_pages"] for node in page]
    served_text = " ".join(node["text"] for node in served_nodes)
    assert supported is True
    assert len(rendered["nodes"]) == len(entries)
    assert served_text == logical_text
    assert served_text.count("→") == 14_404
    assert all(segment["scalar_count"] <= MAX_PAGE_SCALARS for segment in rendered["segments"])
    assert all("oversize" not in segment for segment in rendered["segments"])
    assert all("truncated" not in segment for segment in rendered["segments"])
    for key, _ in entries:
        assert sum(node["text"].startswith(f"{key} ") for node in served_nodes) == 1


def test_tei_long_heading_keeps_a_canonical_bounded_outline_label() -> None:
    heading = "A" * 513
    tei, supported = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader",
        "application/tei+xml",
        (
            '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
            f'<div xml:id="long-heading"><head>{heading}</head><p>Body.</p></div>'
            "</body></text></TEI>"
        ),
    )

    assert supported is True
    label = tei["outline"][0]["label"]
    assert label == " ".join(label.split())
    assert len(label) <= 512
    assert "shortened to 512 Unicode scalars" in label


def test_segment_partition_counts_spaces_between_ordinary_blocks() -> None:
    html = "".join(f"<p>{'A' * 500}</p>" for _ in range(100))
    rendered, supported = DEFAULT_RENDERER_REGISTRY.render(
        "sanitized-html", "text/html", html
    )

    assert supported is True
    assert len(rendered["segments"]) == 2
    assert sum(item["scalar_count"] for item in rendered["segments"]) == 50_098
    assert all(
        item["scalar_count"] <= MAX_PAGE_SCALARS for item in rendered["segments"]
    )
    assert all("oversize" not in item for item in rendered["segments"])
    assert all("truncated" not in item for item in rendered["segments"])


def test_segment_scalar_count_excludes_unserved_cross_segment_separator() -> None:
    html = f"<p>X</p><p>{'Y' * MAX_PAGE_SCALARS}</p>"
    rendered, supported = DEFAULT_RENDERER_REGISTRY.render(
        "sanitized-html", "text/html", html
    )

    assert supported is True
    assert [item["scalar_count"] for item in rendered["segments"]] == [
        1,
        MAX_PAGE_SCALARS,
    ]
    assert all(
        item["scalar_count"] <= MAX_PAGE_SCALARS for item in rendered["segments"]
    )
    assert all("oversize" not in item for item in rendered["segments"])
    assert all("truncated" not in item for item in rendered["segments"])


def test_thml_xml_reader_shows_only_the_readable_body_as_inert_structure() -> None:
    assert _source_presentation(Path("retained.xml")) == (
        "application/xml",
        "xml-reader",
        "source-location",
    )
    rendered, supported = DEFAULT_RENDERER_REGISTRY.render(
        "xml-reader",
        "application/xml",
        """<?xml version="1.0"?>
        <!DOCTYPE ThML PUBLIC "-//CCEL/DTD ThML//EN" "https://example.invalid/thml.dtd">
        <ThML><ThML.head><DC.Title>Hidden metadata</DC.Title></ThML.head>
        <ThML.body><h1 id="chapter-one">Chapter One</h1><p>Readable text.</p>
        <scripCom><p>Readable commentary.</p></scripCom></ThML.body></ThML>""",
    )

    assert supported is True
    assert rendered["kind"] == "xml-reader"
    assert rendered["outline"][0]["label"] == "Chapter One"
    visible = json.dumps(rendered)
    assert "Readable text." in visible
    assert "Readable commentary." in visible
    assert "Hidden metadata" not in visible


def test_thml_xml_reader_preserves_native_table_geometry_through_html_projection() -> None:
    rendered, supported = DEFAULT_RENDERER_REGISTRY.render(
        "xml-reader",
        "application/xml",
        """<ThML><ThML.body>
        <table>
          <tr><td rowspan="2">A</td><td>B</td></tr>
          <tr></tr>
          <tr><td colspan="2">INTRODUCTION.</td></tr>
          <tr><th>&#160;</th><th>PAGE</th></tr>
        </table>
        </ThML.body></ThML>""",
    )

    assert supported is True
    assert rendered["kind"] == "xml-reader"
    table = rendered["nodes"][0]
    assert len(table["children"]) == 4
    assert table["children"][0]["children"][0]["rowspan"] == 2
    assert table["children"][1]["children"] == []
    assert table["children"][2]["children"][0]["colspan"] == 2
    assert [cell["text"] for cell in table["children"][3]["children"]] == [
        "\u00a0",
        "PAGE",
    ]


def test_thml_native_divisions_become_metadata_only_navigation_anchors() -> None:
    exact = """<ThML><ThML.body>
    <div1 id="work-one" title="Native Work One"><p>Body title.</p>
      <div2 id="part-one" title="Native Part One"><p>Inner prose.</p></div2>
      <p>Trailing prose.</p>
    </div1>
    </ThML.body></ThML>"""

    rendered, supported = DEFAULT_RENDERER_REGISTRY.render(
        "xml-reader", "application/xml", exact
    )

    assert supported is True
    assert rendered["outline"][:2] == [
        {"location": "work-one", "label": "Native Work One", "level": 1},
        {"location": "part-one", "label": "Native Part One", "level": 2},
    ]
    assert rendered["nodes"][:3] == [
        {"type": "heading", "text": "", "level": 1, "location": "work-one"},
        {"type": "paragraph", "text": "Body title."},
        {"type": "heading", "text": "", "level": 2, "location": "part-one"},
    ]
    assert [node["text"] for node in rendered["nodes"] if node["type"] == "paragraph"] == [
        "Body title.",
        "Inner prose.",
        "Trailing prose.",
    ]
    visible_body = " ".join(node["text"] for node in rendered["nodes"])
    assert "Native Work One" not in visible_body
    assert "Native Part One" not in visible_body


def test_thml_native_division_duplicate_and_missing_ids_are_deterministic() -> None:
    exact = """<ThML><ThML.body>
    <div1 id="same" title="First"><p>First prose.</p></div1>
    <div1 id="same" title="Second"><p>Second prose.</p></div1>
    <div1 title="Third"><p>Third prose.</p></div1>
    </ThML.body></ThML>"""

    first, first_supported = DEFAULT_RENDERER_REGISTRY.render(
        "xml-reader", "application/xml", exact
    )
    second, second_supported = DEFAULT_RENDERER_REGISTRY.render(
        "xml-reader", "application/xml", exact
    )

    assert first_supported is True and second_supported is True
    assert first["outline"] == second["outline"]
    locations = [item["location"] for item in first["outline"]]
    assert locations[0] == "same"
    assert len(locations) == len(set(locations)) == 3
    assert all(location != "start" for location in locations)
    assert [node["text"] for node in first["nodes"] if node["type"] == "paragraph"] == [
        "First prose.",
        "Second prose.",
        "Third prose.",
    ]


def test_thml_untitled_divisions_and_reserved_marker_attributes_keep_readable_text() -> None:
    exact = """<ThML><ThML.body>
    <div1 id="untitled"><p>Untitled prose.</p></div1>
    <div1 id="empty" title="Empty title"></div1>
    <div1 id="hidden" title="Hidden title"><script>not readable</script></div1>
    <p data-cvw-native-label="Impersonated label" data-cvw-native-location="fake">Plain prose.</p>
    </ThML.body></ThML>"""

    rendered, supported = DEFAULT_RENDERER_REGISTRY.render(
        "xml-reader", "application/xml", exact
    )

    assert supported is True
    assert rendered["outline"] == []
    assert [node["text"] for node in rendered["nodes"]] == [
        "Untitled prose.",
        "Plain prose.",
    ]


def test_unknown_or_entity_bearing_xml_falls_back_to_bounded_exact_text() -> None:
    for exact in (
        "<ocr><line>Uninterpreted OCR.</line></ocr>",
        "<!DOCTYPE doc [<!ENTITY probe 'value'>]><doc>&probe;</doc>",
    ):
        rendered, supported = DEFAULT_RENDERER_REGISTRY.render(
            "xml-reader", "application/xml", exact
        )
        assert supported is True
        assert rendered["kind"] == "exact-text"
        assert rendered["nodes"][0]["text"] == exact


def test_plain_text_passages_preserve_every_character_and_search_beyond_labels(tmp_path: Path) -> None:
    exact = "Opening\r\n\r\n" + "A long paragraph " + "x" * 300 + " needle in the middle.\r\n\r\nLast line."
    path = tmp_path / "book.txt"
    path.write_bytes(exact.encode())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    rendered, supported = DEFAULT_RENDERER_REGISTRY.render("exact-text", "text/plain", exact)
    assert supported
    assert "".join(node["text"] for node in rendered["nodes"]) == exact
    positions = [f"text-{exact.index(text)}" for text in ("Opening", "A long paragraph", "Last line")]
    assert [item["location"] for item in rendered["outline"]] == positions
    assert "needle" not in rendered["outline"][1]["label"]
    application = ReviewApplication({"works": [{
        "slug": "plain", "title": "Plain text", "creator": "Retained source", "scope": "work",
        "correspondence_sources": [], "stages": {
            "source": {"selected_artifact_id": "source", "artifacts": [{
                "id": "source", "version": digest, "root": "source", "path": path.name,
                "sha256": digest, "media_type": "text/plain", "presentation_kind": "exact-text",
                "location_kind": "source-line",
            }]}, "tei": {"artifacts": []},
        },
    }]}, {"source": tmp_path}, DEFAULT_RENDERER_REGISTRY)
    result = application.locations("plain", "source", expected_artifact="source", expected_version=digest, search="NEEDLE IN THE MIDDLE")
    assert [item["location"] for item in result["locations"]] == [positions[1]]
    view = application.stage_view("plain", "source", recorded=("source", digest, positions[1]))
    assert "needle in the middle" in view["selected_context"]["text"]
    long_line = "x" * 45_000 + "needle at the end"
    long_rendered, _ = DEFAULT_RENDERER_REGISTRY.render("exact-text", "text/plain", long_line)
    assert "".join(node["text"] for node in long_rendered["nodes"]) == long_line
    assert "needle at the end" in long_rendered["contexts"][long_rendered["outline"][-1]["location"]]["text"]


def test_explicit_work_detail_selection_is_available_without_changing_library_default(tmp_path: Path) -> None:
    artifacts = [dict(id=name, version='v1', name=name, bytes=0, root='source', path=name+'.txt', authority_path=name+'.txt', sha256='a'*64,
        media_type='text/plain', presentation_kind='exact-text', location_kind='source-location') for name in ('first','last')]
    application = ReviewApplication({'works': [dict(slug='book', title='A real reading choice', creator='Author', scope='work',
        correspondence_sources=[], stages=dict(source=dict(artifacts=artifacts), tei=dict(artifacts=[])))]}, {'source':tmp_path}, DEFAULT_RENDERER_REGISTRY)
    before=application.work_detail('book')['work']['stages'][0]
    assert before['availability']=='selection-required' and before['selected_artifact'] is None
    selected=application.work_detail('book',source_artifact='last',source_version='v1')['work']['stages'][0]
    assert selected['availability']=='available'
    assert selected['selected_artifact']==dict(id='last',version='v1')
    assert application.work_detail('book')['work']['stages'][0]['selected_artifact'] is None
    with pytest.raises(ValueError,match='current declared artifact'):
        application.work_detail('book',source_artifact='last',source_version='changed')


def test_legacy_html_implicit_paragraphs_and_inert_image_alternatives_are_readable() -> (
    None
):
    html, supported = DEFAULT_RENDERER_REGISTRY.render(
        "sanitized-html",
        "text/html",
        """<html><body>
        <center><h2>The Order for Morning Prayer,</h2></center>
        <font color="Red"><em>Opening rubric.</em></font><P>
        <strong><img src="https://outside.invalid/w.gif" alt="W">HEN</strong>
        the wicked man turneth away.<BR>Second visible line.<P>
        The next prayer has no explicit closing paragraph.
        <script>exfiltrate()</script>
        </body></html>""",
    )

    assert supported is True
    assert html["nodes"] == [
        {
            "type": "heading",
            "text": "The Order for Morning Prayer,",
            "level": 2,
            "location": html["nodes"][0]["location"],
        },
        {"type": "paragraph", "text": "Opening rubric.", "inline": [{"text":"Opening rubric.", "marks":["italic"]}]},
        {
            "type": "paragraph",
            "text": "WHEN the wicked man turneth away. Second visible line.",
            "inline": [{"text":"WHEN","marks":["bold"]},{"text":" the wicked man turneth away. Second visible line.","marks":[]}],
        },
        {
            "type": "paragraph",
            "text": "The next prayer has no explicit closing paragraph.",
        },
    ]
    serialized = json.dumps(html)
    assert "outside.invalid" not in serialized
    assert "exfiltrate" not in serialized


def test_large_single_line_json_is_losslessly_pageable_without_truncation() -> None:
    exact = json.dumps(
        {"payload": "x" * (MAX_PAGE_SCALARS * 2 + 17)}, separators=(",", ":")
    )

    rendered, supported = DEFAULT_RENDERER_REGISTRY.render(
        "json-tree", "application/json", exact
    )

    assert supported is True
    assert rendered["kind"] == "exact-text"
    assert all(node["type"] == "preformatted" for node in rendered["nodes"])
    assert all(len(node["text"]) <= MAX_PAGE_SCALARS for node in rendered["nodes"])
    assert "".join(node["text"] for node in rendered["nodes"]) == exact
    assert len(rendered["segments"]) >= 3
    assert len(rendered["outline"]) == len(rendered["nodes"])
    assert all(item["location"] in rendered["contexts"] for item in rendered["outline"])
    assert all("oversize" not in segment for segment in rendered["segments"])
    assert all("truncated" not in segment for segment in rendered["segments"])


def test_verified_ingest_cache_is_bounded_and_evicts_oldest_entry() -> None:
    cache = VerifiedIngestCache(max_entries=2, max_retained_bytes=1_000_000)
    cache.admit(("one",), {"text": "one"})
    cache.admit(("two",), {"text": "two"})
    assert cache.get(("one",)) == {"text": "one"}
    cache.admit(("three",), {"text": "three"})

    assert cache.get(("two",)) is None
    assert set(cache.snapshot()) == {("one",), ("three",)}


def test_rendered_cache_budget_counts_payload_not_shared_class_state() -> None:
    class MappingWithSharedState(dict):
        shared_runtime = b"x" * 200_000

    cache = VerifiedIngestCache(max_retained_bytes=100_000)
    small = MappingWithSharedState({"nodes": [{"text": "small"}]})
    cache.admit(("small",), small)
    assert cache.get(("small",)) is small

    large = MappingWithSharedState({"nodes": [{"text": "x" * 200_000}]})
    cache.admit(("large",), large)
    assert cache.get(("large",)) is None
    assert cache.get(("small",)) is small


def test_text_ingest_cache_retains_exact_availability_not_duplicate_text(
    tmp_path: Path,
) -> None:
    exact = "x" * 1_000_000
    artifact_path = tmp_path / "large.tei.xml"
    artifact_path.write_text(exact, encoding="utf-8")
    rendered = {
        "kind": "tei-document",
        "nodes": [{"type": "paragraph", "text": "bounded rendering"}],
        "outline": [],
        "contexts": [],
        "segments": [],
    }

    class FixedRegistry:
        def render(
            self,
            declared_kind: str,
            media_type: str,
            value: str,
        ) -> tuple[dict[str, object], bool]:
            assert declared_kind == "tei-xml"
            assert media_type == "application/tei+xml"
            assert value == exact
            return rendered, True

    application = ReviewApplication({}, {"candidate": tmp_path}, FixedRegistry())
    application._cache = VerifiedIngestCache(
        max_entries=1,
        max_retained_bytes=100_000,
    )
    artifact_id = "tei-" + "a" * 64
    version = "b" * 64
    work = {
        "stages": {
            "tei": {
                "selected_artifact_id": artifact_id,
                "artifacts": [
                    {
                        "id": artifact_id,
                        "version": version,
                        "root": "candidate",
                        "path": artifact_path.name,
                        "sha256": hashlib.sha256(
                            artifact_path.read_bytes()
                        ).hexdigest(),
                        "media_type": "application/tei+xml",
                        "presentation_kind": "tei-xml",
                        "location_kind": "tei-xml-id",
                    }
                ],
            }
        }
    }

    first = application._resolve(work, "tei")
    second = application._resolve(work, "tei")

    assert first.cache_resident is False
    assert first.exact == ""
    assert second.cache_resident is True
    assert second.exact == ""
    assert next(iter(application._cache.snapshot().values()))[2] is True


def test_thml_releases_xml_tree_before_context_and_page_allocation(monkeypatch):
    import weakref
    from cvw_app import review_renderers
    original_parse = review_renderers.ElementTree.fromstring
    original_finalize = review_renderers._finalize_structure
    original_feed = review_renderers._SafeHtmlNodes.feed
    roots = []
    def parse(*args, **kwargs):
        root = original_parse(*args, **kwargs)
        roots.append(weakref.ref(root))
        return root
    def finalize(*args, **kwargs):
        assert roots and roots[-1]() is None
        return original_finalize(*args, **kwargs)
    def feed(*args, **kwargs):
        assert roots and roots[-1]() is None
        return original_feed(*args, **kwargs)
    monkeypatch.setattr(review_renderers.ElementTree, "fromstring", parse)
    monkeypatch.setattr(review_renderers, "_finalize_structure", finalize)
    monkeypatch.setattr(review_renderers._SafeHtmlNodes, "feed", feed)
    output = review_renderers.render_xml_reader("application/xml", "<ThML><ThML.body><h1>Opening</h1><p>Readable text.</p></ThML.body></ThML>")
    assert output["contexts"]["start"]["text"] == "Opening Readable text."
