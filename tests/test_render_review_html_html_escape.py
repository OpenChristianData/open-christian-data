from __future__ import annotations

from pathlib import Path

import build.tools.render_review_html as render_review_html
from build.tools.render_review_html import render_resource_html


def test_definition_block_script_renders_as_escaped_text() -> None:
    record = {
        "meta": {
            "id": "escape-test",
            "title": "Escape Test",
            "schema_type": "reference_entry",
            "schema_version": "2.1.0",
        },
        "data": [
            {
                "entry_id": "escape-test.script",
                "term": "Script",
                "alt_terms": [],
                "definition_blocks": ["<script>alert('xss')</script>"],
            }
        ],
    }

    html = render_resource_html(record, source_path=Path("data/reference/escape-test.json"))

    assert "<script>alert('xss')</script>" not in html
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in html


def test_ocr_evidence_surface_renders_as_escaped_text(monkeypatch) -> None:
    record = {
        "meta": {
            "id": "escape-test",
            "title": "Escape Test",
            "schema_type": "reference_entry",
            "schema_version": "2.1.0",
        },
        "data": [
            {
                "entry_id": "escape-test.script",
                "term": "Script",
                "alt_terms": [],
                "definition_blocks": ["Safe source text."],
            }
        ],
    }
    surface = "<script>alert('xss')</script>"

    def fake_warnings(payload, source_path, resource_type):
        return {
            "ocr_scanner": [
                {
                    "code": "digit_in_letter",
                    "severity": "warning",
                    "entry_id": "escape-test.script",
                    "field_path": "definition_blocks.0",
                    "message": "Escaped OCR surface.",
                    "evidence": {"surface": surface, "snippet": f"before {surface} after"},
                    "signature": "sig",
                    "ephemeral": False,
                }
            ]
        }

    monkeypatch.setattr(render_review_html, "_producer_warnings", fake_warnings)

    html = render_resource_html(record, source_path=Path("data/reference/escape-test.json"))

    assert surface not in html
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in html
