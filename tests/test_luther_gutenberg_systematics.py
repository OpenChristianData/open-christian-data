"""Focused tests for Luther works parsed by gutenberg_systematics.py."""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ocd_kernel.lib.schema_enums import get_enum  # noqa: E402
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


def test_galatians_publication_year_correction_is_metadata_only(tmp_path, monkeypatch):
    """Both producer outputs clear the unsupported date without changing other fields."""
    monkeypatch.setattr(parser, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(parser, "RAW_DIR", tmp_path / "raw" / "gutenberg")
    monkeypatch.setattr(parser, "local_now", lambda: datetime(2026, 7, 5, tzinfo=timezone.utc))
    cfg = next(item for item in parser.WORK_CONFIG if item["slug"] == "luther-commentary-on-galatians")
    source_hash = "sha256:" + "a" * 64
    previous = dict(cfg, pub_year=1937)
    expected_meta = parser.build_structured_text_meta(previous, source_hash)
    expected_meta["original_publication_year"] = None
    parser.write_source_config(previous, source_hash)
    config_path = tmp_path / "sources" / "structured-text" / cfg["slug"] / "config.json"
    expected_config = json.loads(config_path.read_text(encoding="utf-8"))
    expected_config["original_publication_year"] = None

    assert cfg["pub_year"] is None
    assert parser.build_structured_text_meta(cfg, source_hash) == expected_meta
    parser.write_source_config(cfg, source_hash)
    assert json.loads(config_path.read_text(encoding="utf-8")) == expected_config


def test_other_systematics_publication_years_are_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(parser, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(parser, "RAW_DIR", tmp_path / "raw" / "gutenberg")
    monkeypatch.setattr(parser, "local_now", lambda: datetime(2026, 7, 5, tzinfo=timezone.utc))
    expected = {
        "strong-systematic-theology-vol-1": 1907,
        "strong-systematic-theology-vol-2": 1907,
        "strong-systematic-theology-vol-3": 1907,
        "dabney-systematic-theology": 1871,
        "shedd-dogmatic-theology-vol-1": 1888,
        "shedd-dogmatic-theology-vol-2": 1889,
        "shedd-dogmatic-theology-vol-3": 1894,
        "miley-systematic-theology-vol-1": 1892,
        "miley-systematic-theology-vol-2": 1894,
        "aa-hodge-outlines": 1879,
        "hooker-ecclesiastical-polity": 1597,
        "luther-bondage-of-the-will": 1823,
    }
    others = [cfg for cfg in parser.WORK_CONFIG if cfg["slug"] != "luther-commentary-on-galatians"]
    assert {cfg["slug"] for cfg in others} == set(expected)
    all_metadata = {}
    for cfg in others:
        source_hash = "sha256:" + "a" * 64
        meta = parser.build_structured_text_meta(cfg, source_hash)
        all_metadata[cfg["slug"]] = meta
        assert meta["original_publication_year"] == expected[cfg["slug"]]
        parser.write_source_config(cfg, source_hash)
        kind = "catechisms" if cfg["work_kind"] == "catechism_qa" else "structured-text"
        path = tmp_path / "sources" / kind / cfg["slug"] / "config.json"
        assert json.loads(path.read_text(encoding="utf-8"))["original_publication_year"] == expected[cfg["slug"]]
    # Complete metadata baseline from the pre-correction producer, with a fixed clock/hash.
    payload = json.dumps(all_metadata, sort_keys=True, ensure_ascii=False).encode("utf-8")
    assert hashlib.sha256(payload).hexdigest() == "80b4c276f28fef64493de32e5afb909618bac37722c544e79ea6a54f1cf87d46"


@pytest.fixture
def galatians_binding_fixture(tmp_path, monkeypatch):
    slug = "luther-commentary-on-galatians"
    relative = Path("sources/structured-text") / slug
    directory = tmp_path / relative
    directory.mkdir(parents=True)
    config = json.loads((REPO_ROOT / relative / "config.json").read_bytes())
    config["original_publication_year"] = 1937
    config["download_date"] = "2001-02-03"
    config["owner_extension"] = {"preserve": [1, "unchanged"]}
    config_path = directory / "config.json"
    config_path.write_bytes(json.dumps(config, indent=2).replace("\n", "\r\n").encode())
    implementation = tmp_path / "fixture.py"
    implementation.write_bytes(b"# fixture only\n")
    digest = hashlib.sha256(implementation.read_bytes()).hexdigest()
    manifest = {
        "contract": "ocd-source-manifest-v1", "work_id": slug,
        "authorities": [{"name": "source-config", "path": (relative / "config.json").as_posix(),
                         "bytes": config_path.stat().st_size,
                         "sha256": hashlib.sha256(config_path.read_bytes()).hexdigest()}],
        "converter": {"callable": "convert", "implementation_path": "fixture.py", "implementation_sha256": digest},
        "validator": {"callable": "verify", "implementation_path": "fixture.py", "implementation_sha256": digest,
                      "import_closure_sha256": digest},
        "package_schema": {"path": "fixture.py", "sha256": digest},
    }
    manifest_path = directory / f"{slug}.source-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    for relative_path in ("sources/structured-text/other/config.json", "data/other.json", "raw/source.txt"):
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"must remain untouched")
    monkeypatch.setattr(parser, "REPO_ROOT", tmp_path)
    return tmp_path, config_path, manifest_path


def _binding_snapshot(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_galatians_config_only_refresh_preserves_all_other_bytes(galatians_binding_fixture):
    root, config, manifest = galatians_binding_fixture
    before = _binding_snapshot(root)
    result = parser.refresh_galatians_config_binding()
    after = _binding_snapshot(root)
    assert before.keys() == after.keys()
    assert {path for path in before if before[path] != after[path]} == {
        config.relative_to(root), manifest.relative_to(root)}
    assert config.read_bytes() == before[config.relative_to(root)].replace(
        b'"original_publication_year": 1937', b'"original_publication_year": null')
    old_digest = hashlib.sha256(before[config.relative_to(root)]).hexdigest()
    assert manifest.read_bytes() == before[manifest.relative_to(root)].replace(
        old_digest.encode(), result["config_sha256"].encode())
    assert parser.refresh_galatians_config_binding() == result
    assert _binding_snapshot(root) == after


def test_galatians_config_refresh_rejects_drift_without_writes(galatians_binding_fixture):
    root, config, _ = galatians_binding_fixture
    config.write_bytes(config.read_bytes() + b" ")
    before = _binding_snapshot(root)
    with pytest.raises(ValueError, match="authority bytes drifted"):
        parser.refresh_galatians_config_binding()
    assert _binding_snapshot(root) == before


def test_galatians_config_refresh_rolls_back_failed_manifest_write(galatians_binding_fixture, monkeypatch):
    root, _, manifest = galatians_binding_fixture
    before = _binding_snapshot(root)
    original_replace = Path.replace

    def fail_manifest(path, target):
        if target == manifest:
            raise OSError("simulated manifest failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_manifest)
    with pytest.raises(OSError, match="simulated manifest failure"):
        parser.refresh_galatians_config_binding()
    assert _binding_snapshot(root) == before


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
