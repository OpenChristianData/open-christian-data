from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
import time

import pytest

from cvw_app.review_renderers import (
    DEFAULT_RENDERER_REGISTRY,
    RendererError,
    PRESENTATION_KINDS,
)
from cvw_app.ingest_cache import compact_projection, PackedPages
from cvw_app.text_decoding import decode_text
from cvw_app.capture_review import (
    CaptureError,
    canonical,
    digest,
    export_bundle,
    session_identity,
    validate_route,
)
from cvw_app.tests.test_review_work_catalog import evidence_pair


def tei(body):
    return DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader",
        "application/tei+xml",
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
        + body
        + "</body></text></TEI>",
    )[0]


def test_emphasis_is_visible_in_both_projections_without_inventing_spacing():
    body = '<p>Before <hi rend="italic">emphasized <hi rend="bold">and bold</hi></hi> after.</p>'
    candidate = tei(body)["nodes"][0]
    source = DEFAULT_RENDERER_REGISTRY.render(
        "sanitized-html",
        "text/html",
        "<p>Before <em>emphasized <b>and bold</b></em> after.</p>",
    )[0]["nodes"][0]
    assert candidate == source
    assert candidate["text"] == "Before emphasized and bold after."
    assert any(run["marks"] == ["bold", "italic"] for run in candidate["inline"])


def test_typed_null_and_unknown_rend_are_disclosed():
    result = tei(
        '<ab type="json-null"><seg type="json-scalar"/></ab><p><hi rend="mystery">Text</hi></p>'
    )
    assert result["nodes"][0]["text"] == "null"
    assert "mystery" in result["limitations"][0]


def test_note_related_limitations_preserve_exact_text_and_document_order():
    result = tei(
        '<p><note xml:id="n">Note</note>'
        '<hi xml:id="em1" rend="italic">One</hi>'
        '<hi xml:id="em2" rend="mystery">Two</hi></p>'
    )
    assert result["limitations"] == [
        "n: Note content is displayed separately; original inline paragraph continuity and backlinks require exact-TEI inspection",
        "em1: Inline typography around a note requires exact-TEI inspection",
        "em2: Inline typography around a note requires exact-TEI inspection",
    ]


def test_explicit_block_quote_obeys_document_node_contract():
    result = tei(
        '<quote type="block">Quoted <hi rend="italic">text</hi>.</quote>'
    )
    assert result["nodes"][0] == {
        "type": "blockquote",
        "text": "",
        "children": [{
            "type": "paragraph",
            "text": "Quoted text.",
            "inline": [
                {"text": "Quoted ", "marks": []},
                {"text": "text", "marks": ["italic"]},
                {"text": ".", "marks": []},
            ],
        }],
    }


def test_nested_multi_paragraph_lists_preserve_grouping_and_order():
    result = tei(
        '<list type="ordered"><item><p>A</p><p>B</p><list><item>C</item></list></item><item>D</item></list>'
    )
    group = result["nodes"][0]
    assert group["ordered"] is True
    assert len(group["children"]) == 2
    first = group["children"][0]["children"]
    assert [part["text"] for part in first[:2]] == ["A", "B"]
    assert first[2]["type"] == "list"
    assert first[2]["children"][0]["children"][0]["text"] == "C"


def test_long_list_pages_preserve_every_item_and_continuation_numbers():
    result = tei(
        '<list type="ordered">'
        + "".join(
            "<item>" + str(i) + " " + ("word " * 40) + "</item>" for i in range(600)
        )
        + "</list>"
    )
    assert len(result["segments"]) > 1
    items = []
    for page in result["_pages"]:
        group = page[0]
        assert group["type"] == "list"
        assert group.get("start", 1) == len(items) + 1
        items.extend(group["children"])
    assert len(items) == 600
    assert [item["children"][0]["text"].split()[0] for item in items] == [
        str(i) for i in range(600)
    ]
    assert not any(segment.get("truncated") for segment in result["segments"])


def test_html_ordered_list_start_and_nested_items():
    result = DEFAULT_RENDERER_REGISTRY.render(
        "sanitized-html",
        "text/html",
        '<ol start="4"><li>A<ul><li>B</li></ul></li><li>C</li></ol>',
    )[0]
    group = result["nodes"][0]
    assert group["ordered"] and group["start"] == 4
    assert len(group["children"]) == 2
    assert group["children"][0]["children"][1]["type"] == "list"


@pytest.mark.parametrize(
    "payload,media,expected",
    [
        (b'<meta charset="iso-8859-1"><p>\x93Hello\x94</p>', "text/html", "cp1252"),
        (b"\xef\xbb\xbfHello", "text/plain", "utf-8-sig"),
        (b'<meta charset="windows-1252"><p>caf\xe9</p>', "text/html", "cp1252"),
    ],
)
def test_declared_decoding(payload, media, expected):
    text, encoding = decode_text(payload, media)
    assert encoding == expected
    assert "\ufffd" not in text


@pytest.mark.parametrize(
    "payload",
    [
        b'<meta charset="utf-8"><meta charset="windows-1252">',
        b"<p>\xff</p>",
        b'\xef\xbb\xbf<meta charset="windows-1252">',
        b'<meta charset="utf-7">',
    ],
)
def test_ambiguous_or_invalid_encoding_fails_closed(payload):
    with pytest.raises(RendererError):
        decode_text(payload, "text/html")


def test_legacy_exact_and_read_use_the_same_decoding(evidence_pair):
    app, selection, _ = evidence_pair(
        source_bytes=b'<meta charset="windows-1252"><p>caf\xe9</p>'
    )
    pane = app.compare_view("brief-example", **selection)["left"]
    assert pane["presentation"]["text_encoding"] == "cp1252"
    assert pane["presentation"]["document"]["nodes"][0]["text"] == "caf\xe9"
    artifact = pane["artifact"]
    assert "caf\xe9" in app.exact(
        "brief-example", "source", artifact["id"], artifact["version"]
    )


def test_cold_compare_resolves_once_per_pane_and_warm_reuses_projection(
    evidence_pair, monkeypatch
):
    app, selection, _ = evidence_pair()
    calls = []
    render = app.registry.render

    def counted(*args, **kwargs):
        calls.append(args[0])
        return render(*args, **kwargs)

    monkeypatch.setattr(app.registry, "render", counted)
    app.compare_view("brief-example", **selection)
    assert len(calls) == 2
    app.compare_view("brief-example", **selection, evidence_brief=True)
    assert len(calls) == 2


def test_concurrent_requests_share_one_cold_render(evidence_pair, monkeypatch):
    app, selection, _ = evidence_pair()
    calls = []
    render = app.registry.render

    def counted(*args, **kwargs):
        calls.append(args[0])
        time.sleep(0.025)
        return render(*args, **kwargs)

    monkeypatch.setattr(app.registry, "render", counted)
    barrier = threading.Barrier(4)

    def read(_):
        barrier.wait()
        return app.stage_view(
            "brief-example", "source", recorded=selection["left_recorded"]
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(read, range(4)))
    assert len(calls) == 1
    assert all(result["availability"] == "available" for result in results)


def test_compacted_pages_and_contexts_are_identical():
    original = tei("<p>Alpha</p><p>Beta</p>")
    compact = compact_projection(original, threshold=0)
    assert isinstance(compact["_pages"], PackedPages)
    assert compact["_pages"][0] == original["_pages"][0]
    assert compact["contexts"]["start"] == original["contexts"]["start"]
    assert compact["segments"] == original["segments"]


def test_search_covers_unloaded_work_id_and_state(evidence_pair):
    app, _, _ = evidence_pair()
    manifest = deepcopy(app.manifest)
    first = manifest["works"][0]
    for i in range(65):
        manifest["works"].append(
            {**deepcopy(first), "slug": f"later-{i}", "title": f"Title {i}"}
        )
    app = type(app)(manifest, app.roots, app.registry)
    result = app.catalog_summary_page(search="later-64", state="available")
    assert result["page"]["total"] == 1
    assert result["works"][0]["slug"] == "later-64"


def test_every_registered_success_kind_is_allowed():
    assert (
        set(DEFAULT_RENDERER_REGISTRY.kinds) - {"unsupported-binary"}
        <= PRESENTATION_KINDS
    )


def test_capture_rejects_wrong_origin_and_incomplete_route():
    identity = session_identity(
        {
            "session_id": "s",
            "origin": "http://127.0.0.1:1234",
            "implementation_sha256": "a" * 64,
            "catalog_sha256": "b" * 64,
            "candidate_sha256": ["c" * 64],
        }
    )
    with pytest.raises(CaptureError):
        validate_route("http://127.0.0.1:1235/review/works/a", identity)
    with pytest.raises(CaptureError):
        validate_route(identity["origin"] + "/review/works/a", identity)


def test_capture_accepts_sidecar_session_with_no_catalog_digest():
    receipt = {
        "session": {
            "session_id": "sidecar-session",
            "origin": "http://127.0.0.1:65302",
            "implementation_sha256": "a" * 64,
            "catalog_sha256": None,
            "candidate_sha256": ["c" * 64],
        }
    }

    assert session_identity(receipt) == {
        "session_id": "sidecar-session",
        "origin": "http://127.0.0.1:65302",
        "implementation_sha256": "a" * 64,
        "catalog_sha256": None,
        "candidate_sha256": ["c" * 64],
    }


def test_capture_export_is_fresh_and_digest_verified(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "frame.png").write_bytes(b"example")
    (source / "capture.json").write_bytes(
        canonical({"files": {"frame.png": digest(b"example")}})
    )
    target = export_bundle(source, tmp_path / "export")
    assert (target / "frame.png").read_bytes() == b"example"
    with pytest.raises(CaptureError):
        export_bundle(source, target)
    (source / "frame.png").write_bytes(b"tampered")
    with pytest.raises(CaptureError):
        export_bundle(source, tmp_path / "invalid")


def test_explicit_source_heading_rend_is_discoverable_without_inference():
    result = tei(
        '<p xml:id="greek" rend="source-h2">Index of Greek Words and Phrases</p><p rend="large">Ordinary paragraph</p>'
    )
    assert result["outline"] == [
        {"location": "greek", "label": "Index of Greek Words and Phrases", "level": 2}
    ]
    assert result["nodes"][0]["type"] == "heading"
    assert result["nodes"][1]["type"] == "paragraph"


def test_nested_source_html_heading_types_remain_navigable_in_retained_order():
    result = tei('<ab type="source-div">Before. <seg type="source-div"><seg type="source-h2" rend="source-class:chapter" xml:id="chapter-11">Chapter <hi rend="italic">XI</hi></seg><seg type="source-p">Last chapter text.</seg></seg> After.</ab>')
    assert result['outline'] == [dict(location='chapter-11', label='Chapter XI', level=2)]
    assert [node['type'] for node in result['nodes']] == ['paragraph', 'heading', 'paragraph', 'paragraph']
    assert [node['text'] for node in result['nodes']] == ['Before.', 'Chapter XI', 'Last chapter text.', 'After.']
    assert result['nodes'][1]['inline'][-1]['marks'] == ['italic']


def test_long_list_starts_with_its_recorded_heading():
    result = tei(
        "<head>Index</head><list>"
        + "".join(
            "<item>" + str(i) + " " + ("word " * 100) + "</item>" for i in range(600)
        )
        + "</list>"
    )
    assert result["_pages"][0][0]["type"] == "heading"
    assert result["_pages"][0][1]["type"] == "list"
    assert (
        sum(
            len(node["children"])
            for page in result["_pages"]
            for node in page
            if node["type"] == "list"
        )
        == 600
    )


def test_packed_selected_context_does_not_decode_unused_start(
    evidence_pair, monkeypatch
):
    from cvw_app import review_contract
    from cvw_app.ingest_cache import PackedContexts

    app, selection, _ = evidence_pair(
        source_bytes=b'<h1 id="selected">Selected</h1><p>Body</p>'
    )
    monkeypatch.setattr(
        review_contract,
        "compact_projection",
        lambda value: compact_projection(value, threshold=0),
    )
    calls = []
    original = PackedContexts.__getitem__

    def read(self, key):
        calls.append(key)
        return original(self, key)

    monkeypatch.setattr(PackedContexts, "__getitem__", read)
    record = selection["left_recorded"]
    view = app.stage_view(
        "brief-example",
        "source",
        recorded=review_contract.RecordedContext(
            record.artifact_id, record.version, "selected"
        ),
    )
    assert view["recorded_context"]["state"] == "exact"
    assert calls and set(calls) == {"selected"}


def test_capture_output_protection_is_bound_to_live_snapshot(tmp_path):
    from cvw_app.capture_review import receipt_protected_roots, fresh_directory
    from cvw_app.serving_identity import digest_json

    snapshot = {"protected_input_identities": {"protected_roots": [str(tmp_path)]}}
    identity = digest_json(snapshot)
    receipt = {"startup_snapshot": {**snapshot, "snapshot_sha256": identity}}
    live = {"session": {"startup_snapshot_sha256": identity}}
    assert receipt_protected_roots(receipt, live) == [str(tmp_path)]
    with pytest.raises(CaptureError):
        fresh_directory(tmp_path / "forbidden", [str(tmp_path)])
    receipt["startup_snapshot"]["protected_input_identities"] = {
        "protected_roots": [str(tmp_path / "elsewhere")]
    }
    with pytest.raises(CaptureError):
        receipt_protected_roots(receipt, live)
    assert not (tmp_path / "forbidden").exists()


def test_gloss_labels_remain_with_their_items_in_source_order():
    result = tei(
        '<list type="gloss"><label>Term A</label><item>Definition A</item><label>Term B</label><item>Definition B</item></list>'
    )
    items = result["nodes"][0]["children"]
    assert [[p["text"] for p in item["children"]] for item in items] == [
        ["Term A", "Definition A"],
        ["Term B", "Definition B"],
    ]


def test_nested_list_headings_keep_reachable_contexts():
    result = tei(
        "<list><item><p>Outer</p><list><head>Nested heading</head><item>Inner</item></list></item></list>"
    )
    location = result["outline"][0]["location"]
    assert location in result["contexts"]
    assert location in result["segments"][0]["locations"]
    assert "Inner" in result["contexts"][location]["text"]
