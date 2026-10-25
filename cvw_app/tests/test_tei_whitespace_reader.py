"""Whitespace-only TEI paragraphs must not disable the reader (37c-275)."""

import hashlib
from pathlib import Path

from cvw_app.review_contract import ReviewApplication
from cvw_app.review_renderers import DEFAULT_RENDERER_REGISTRY


def test_reader_preserves_nbsp_paragraph_without_blank_navigation(tmp_path: Path):
    path = tmp_path / "content.tei.xml"
    path.write_text(
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
        '<p xml:id="before">Before</p>'
        '<p xml:id="i.iv.ii-p856">\u00a0\u00a0</p>'
        '<p xml:id="after">After</p></body></text></TEI>',
        encoding="utf-8",
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    application = ReviewApplication(
        {"works": [{
            "slug": "whitespace", "title": "Whitespace", "creator": "Fixture",
            "scope": "work", "correspondence_sources": [],
            "stages": {
                "source": {"artifacts": []},
                "tei": {"selected_artifact_id": "tei-fixture", "artifacts": [{
                    "id": "tei-fixture", "version": digest, "root": "candidate",
                    "path": path.name, "sha256": digest,
                    "media_type": "application/tei+xml",
                    "presentation_kind": "tei-reader", "location_kind": "tei-anchor",
                }]},
                "json": {"artifacts": []},
            },
        }]},
        {"candidate": tmp_path},
        DEFAULT_RENDERER_REGISTRY,
    )

    view = application.stage_view("whitespace", "tei")

    assert view["availability"] == "available"
    document = view["presentation"]["document"]
    assert [node["text"] for node in document["nodes"]] == [
        "Before", "\u00a0\u00a0", "After",
    ]
    assert [item["location"] for item in view["outline"]] == ["before", "after"]
