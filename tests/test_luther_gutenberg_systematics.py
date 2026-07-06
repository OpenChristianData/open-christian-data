"""Focused tests for Luther works parsed by gutenberg_systematics.py."""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.schema_enums import get_enum  # noqa: E402
from build.parsers import gutenberg_systematics as parser  # noqa: E402


OUTPUTS = {
    "luther-bondage-of-the-will": {
        "path": REPO_ROOT / "data" / "structured-text" / "luther-bondage-of-the-will.json",
        "section_count": 13,
        "source_type": "web_transcription",
        "translator": "Henry Cole",
    },
    "luther-commentary-on-galatians": {
        "path": REPO_ROOT / "data" / "structured-text" / "luther-commentary-on-galatians.json",
        "section_count": 8,
        "source_type": "project_gutenberg",
        "translator": "Theodore Graebner",
    },
}


def _load_output(slug: str) -> dict:
    return json.loads(OUTPUTS[slug]["path"].read_text(encoding="utf-8"))


def _iter_sections(sections: list[dict]):
    for section in sections:
        yield section
        yield from _iter_sections(section.get("children", []))


def test_luther_section_counts_match_census_prediction():
    for slug, expected in OUTPUTS.items():
        data = _load_output(slug)
        sections = list(_iter_sections(data["data"]["sections"]))
        assert len(sections) == expected["section_count"]


def test_luther_text_fields_strip_source_boilerplate():
    forbidden = ("Project Gutenberg", "archive.org")
    for slug in OUTPUTS:
        data = _load_output(slug)
        for section in _iter_sections(data["data"]["sections"]):
            for block in section.get("content_blocks", []):
                assert all(term not in block for term in forbidden)


def test_luther_provenance_fields_present():
    for slug, expected in OUTPUTS.items():
        provenance = _load_output(slug)["meta"]["provenance"]
        for field in ("source_url", "source_type", "source_file", "source_hash", "translator"):
            assert provenance.get(field)
        assert provenance["source_type"] == expected["source_type"]
        assert provenance["translator"] == expected["translator"]
        assert provenance["source_hash"].startswith("sha256:")


def test_luther_config_enum_guards_pass():
    parser._validate_configs()
    traditions = get_enum("structured_text", "meta", "tradition")
    work_kinds = get_enum("structured_text", "data", "work_kind")
    for cfg in parser.WORK_CONFIG:
        if not cfg["slug"].startswith("luther-"):
            continue
        assert cfg["work_kind"] in work_kinds
        assert all(value in traditions for value in cfg["tradition"])


@pytest.mark.skipif(
    not all(
        parser.raw_paths(cfg)[0].exists()
        for cfg in parser.WORK_CONFIG
        if cfg["slug"].startswith("luther-")
    ),
    reason="raw Luther source files not downloaded",
)
def test_luther_raw_sources_contain_required_edition_evidence():
    for cfg in parser.WORK_CONFIG:
        if not cfg["slug"].startswith("luther-"):
            continue
        text = "\n\n".join(path.read_text(encoding="utf-8", errors="replace") for path in parser.raw_paths(cfg))
        parser.assert_source_evidence(cfg, text)
