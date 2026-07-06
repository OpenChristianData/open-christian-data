from __future__ import annotations

import copy
import inspect
import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
ZERO_SHA = "sha256:" + ("0" * 64)
ONE_SHA = "sha256:" + ("1" * 64)


def _schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def _ot(label: str) -> str:
    return "ot-sha256:" + sha256(label.encode("utf-8")).hexdigest()


def _walk_words(rendering: dict[str, Any]) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for page in rendering["pages"]:
        for block in page["blocks"]:
            for line in block["lines"]:
                words.extend(line["words"])
    return words


def _walk_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(value)
        for child in value.values():
            keys.update(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_walk_keys(child))
    return keys


def _line(
    *,
    label: str,
    text: str,
    y: int,
    words: list[str] | None = None,
) -> dict[str, Any]:
    tokens = words or text.split()
    observed_words = [
        {
            "observation_token_id": _ot(f"{label}-w-{index}-{token}"),
            "word_native_id": f"{label}-w-{index}",
            "source_raw": token,
            "confidence": 91.0,
            "bbox_native": {"x": 60 + (index * 52), "y": y, "w": 48, "h": 18},
        }
        for index, token in enumerate(tokens, start=1)
    ]
    return {
        "observation_token_id": _ot(f"{label}-line"),
        "line_native_id": f"{label}-line",
        "source_raw": text,
        "confidence": 90.0,
        "bbox_native": {"x": 60, "y": y, "w": 520, "h": 22},
        "words": observed_words,
    }


def _page(
    *,
    manifest_id: str,
    rendering_id: str,
    page_sequence: int,
    protected_text: str | None = None,
    conflict: bool = False,
) -> dict[str, Any]:
    first_line = _line(
        label=f"p{page_sequence}-b1-l1",
        text=protected_text or "Church history begins",
        y=120,
        words=[protected_text] if protected_text is not None else None,
    )
    hyphen_left = _line(
        label=f"p{page_sequence}-b1-l2",
        text="con-",
        y=150,
        words=["con-"],
    )
    hyphen_right = _line(
        label=f"p{page_sequence}-b1-l3",
        text="tinuation",
        y=178,
        words=["tinuation"],
    )
    conflict_block = {
        "block_id": f"p{page_sequence}-b2-conflict",
        "block_type": "text",
        "bbox_native": {"x": 60, "y": 880 if conflict else 260, "w": 520, "h": 80},
        "lines": [
            _line(
                label=f"p{page_sequence}-b2-l1",
                text=(
                    "This body prose line carries paragraph typography evidence"
                    if conflict
                    else "See AUGUSTINE"
                ),
                y=900 if conflict else 280,
            )
        ],
    }
    return {
        "schema_version": "sidecar-page-v1",
        "manifest_id": manifest_id,
        "rendering_id": rendering_id,
        "page_native_id": f"page_{page_sequence:04d}",
        "page_sequence": page_sequence,
        "page_dimensions_native": {"width": 1000, "height": 1000, "unit": "pixel"},
        "blocks": [
            {
                "block_id": f"p{page_sequence}-b1",
                "block_type": "text",
                "bbox_native": {"x": 50, "y": 100, "w": 560, "h": 120},
                "lines": [first_line, hyphen_left, hyphen_right],
            },
            conflict_block,
        ],
        "parsed_keys_index": [
            {
                "key": "fixture_key",
                "handling": "extras_carried",
                "source_path": "fixture.source",
                "note": "TEST-13: re-validate against real vol_01 sidecars once B4 generates them.",
            }
        ],
        "page_extras_carried": {},
        "page_extras_carried_keys": [],
        "page_extras_jcs_sha256": ZERO_SHA,
        "source_payload_sha256": ONE_SHA,
    }


def _write_bundle(
    root: Path,
    *,
    engine_family: str = "tesseract",
    rendering_id: str = "tesseract-render",
    protected_text: str | None = None,
    conflict: bool = False,
) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    manifest_id = f"{engine_family}-manifest"
    page = _page(
        manifest_id=manifest_id,
        rendering_id=rendering_id,
        page_sequence=1,
        protected_text=protected_text,
        conflict=conflict,
    )
    page_path = root / "s1" / engine_family / "pages" / "page_0001.json"
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(json.dumps(page, indent=2, ensure_ascii=False), encoding="utf-8")
    rel_page = page_path.relative_to(root).as_posix()
    manifest = {
        "schema_version": "sidecar-manifest-v1",
        "manifest_id": manifest_id,
        "work_id": "schaff-herzog",
        "edition_id": "nsh-1908-1914",
        "volume": 1,
        "rendering_id": rendering_id,
        "engine_family": engine_family,
        "engine_version": "fixture-1.0",
        "source_lineage_id": f"{engine_family}-lineage",
        "source_files": [{"path": "raw/source-fixture.json", "sha256": ONE_SHA}],
        "pages": [
            {
                "page_native_id": page["page_native_id"],
                "page_sequence": page["page_sequence"],
                "status": "eligible",
                "sidecar_page_path": rel_page,
                "source_payload_sha256": page["source_payload_sha256"],
                "edition_page_key": {
                    "section": "body",
                    "anchor": page["page_sequence"],
                    "ordinal": 0,
                },
            }
        ],
        "manifest_cross_check": {
            "samples_checked": 1,
            "samples_matched": 1,
            "samples_inconclusive": 0,
            "failed_samples": [],
        },
        "bundle_extras_carried": {},
        "bundle_extras_carried_keys": [],
        "bundle_extras_jcs_sha256": ZERO_SHA,
        "created_at": "2026-05-29T00:00:00Z",
    }
    manifest_path = root / "s1" / engine_family / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest_path, manifest, [page]


def _render(manifest_path: Path, repo_root: Path) -> dict[str, Any]:
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    render_manifest(manifest_path, repo_root=repo_root)
    pages_dir = manifest_path.parent / "pages"
    page_files = sorted(pages_dir.glob("*.rendering-v1.json"))
    if not page_files:
        raise AssertionError(f"No per-page files found in {pages_dir}")
    return json.loads(page_files[0].read_text(encoding="utf-8"))


def test_rendering_conformance_preserves_observation_token_identity(tmp_path: Path) -> None:
    """TEST-13: re-validate against real vol_01 sidecars once B4 generates them."""
    from build.lib.rendering_semantic_validator import validate_rendering

    manifest_path, _manifest, pages = _write_bundle(tmp_path)
    rendering = _render(manifest_path, tmp_path)

    jsonschema.Draft202012Validator.check_schema(_schema("rendering-v1"))
    jsonschema.validate(instance=rendering, schema=_schema("rendering-v1"))
    assert validate_rendering(rendering) == []

    input_ids = [
        word["observation_token_id"]
        for page in pages
        for block in page["blocks"]
        for line in block["lines"]
        for word in line["words"]
    ]
    output_ids = [word["observation_token_id"] for word in _walk_words(rendering)]
    assert sorted(output_ids) == sorted(input_ids)
    assert len(output_ids) == len(set(output_ids))

    required_envelope = set(_schema("rendering-v1")["required"])
    assert required_envelope.issubset(rendering)


def test_protected_char_preservation_and_safe_deletions(tmp_path: Path) -> None:
    """TEST-13: re-validate against real vol_01 sidecars once B4 generates them.

    Full arch2 section 3.3 protected set: long-s, ae/oe ligatures, accented
    Latin, en/em dashes, curly quotes, Greek and Hebrew script, dagger, section
    sign -- every one must survive verbatim into normalised. BOM + ZWSP are the
    only folds (safe deletions). Escapes used per PY-08 (Write tool corrupts
    non-ASCII literals).
    """
    # Named codepoints: long-s, ae, oe, e-acute, u-umlaut, en-dash, em-dash,
    # curly double-open/close, curly single-open/close, Greek alpha, Hebrew
    # alef, dagger, section sign.
    protected_chars = (
        "ſ", "æ", "œ", "é", "ü",
        "–", "—", "“", "”", "‘",
        "’", "α", "א", "†", "§",
    )
    bom = "﻿"
    zwsp = "​"
    body = (
        "ſæœé ü–—“Quote”"
        "‘ok’ α א †§"
    )
    protected = bom + body + zwsp
    manifest_path, _manifest, _pages = _write_bundle(tmp_path, protected_text=protected)

    rendering = _render(manifest_path, tmp_path)
    protected_word = _walk_words(rendering)[0]

    # source_raw is byte-identical to the sidecar input (no mutation at all).
    assert protected_word["layers"]["source_raw"] == protected
    # normalised drops only the two safe-delete codepoints; every protected
    # character survives. No T3 substitution, no NFKC fold, no hyphen->en-dash.
    expected_normalised = protected.replace(bom, "").replace(zwsp, "")
    assert protected_word["layers"]["normalised"] == expected_normalised
    assert protected_word["layers"]["structured"] == expected_normalised
    assert protected_word["layers"]["display"] == expected_normalised
    for char in protected_chars:
        assert char in protected_word["layers"]["normalised"]
    assert bom not in protected_word["layers"]["normalised"]
    assert zwsp not in protected_word["layers"]["normalised"]


def test_renderer_is_isolated_per_engine(tmp_path: Path) -> None:
    """TEST-13: re-validate against real vol_01 sidecars once B4 generates them."""
    from build.tools.ocr_pipeline import render_s2

    tesseract_manifest, _tess_meta, _tess_pages = _write_bundle(
        tmp_path / "tesseract-run",
        engine_family="tesseract",
        rendering_id="tesseract-render",
    )
    abbyy_manifest, _abbyy_meta, _abbyy_pages = _write_bundle(
        tmp_path / "abbyy-run",
        engine_family="abbyy",
        rendering_id="abbyy-render",
    )

    signature = inspect.signature(render_s2.render_manifest)
    assert "manifest_path" in signature.parameters
    assert all("manifests" not in name and "other" not in name for name in signature.parameters)

    tesseract_rendering = _render(tesseract_manifest, tesseract_manifest.parents[2])
    abbyy_rendering = _render(abbyy_manifest, abbyy_manifest.parents[2])

    assert tesseract_rendering["engine_family"] == "tesseract"
    assert tesseract_rendering["rendering_id"] == "tesseract-render"
    assert abbyy_rendering["engine_family"] == "abbyy"
    assert abbyy_rendering["rendering_id"] == "abbyy-render"

    tesseract_json = json.dumps(tesseract_rendering, sort_keys=True)
    assert "abbyy-render" not in tesseract_json
    assert "abbyy" not in tesseract_json
    forbidden_keys = {
        "winner",
        "winning_engine",
        "compared_engines",
        "engine_comparison",
        "cross_engine_comparison",
    }
    assert forbidden_keys.isdisjoint(_walk_keys(tesseract_rendering))


def test_isolation_reads_no_other_engine_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bind isolation at the read boundary, not just by output strings.

    Instrument the renderer's JSON reads while rendering the tesseract bundle and
    assert no file under the sibling abbyy bundle is ever read (lock line 50:
    S2 is isolated per engine).
    """
    from build.tools.ocr_pipeline import render_s2

    tesseract_manifest, _meta, _pages = _write_bundle(
        tmp_path / "tesseract-run",
        engine_family="tesseract",
        rendering_id="tesseract-render",
    )
    _write_bundle(
        tmp_path / "abbyy-run",
        engine_family="abbyy",
        rendering_id="abbyy-render",
    )

    read_paths: list[Path] = []
    original_read_json = render_s2._read_json

    def _tracking_read(path: Any) -> dict[str, Any]:
        read_paths.append(Path(path).resolve())
        return original_read_json(path)

    monkeypatch.setattr(render_s2, "_read_json", _tracking_read)
    render_s2.render_manifest(tesseract_manifest, repo_root=tesseract_manifest.parents[2])

    abbyy_dir = (tmp_path / "abbyy-run").resolve()
    assert read_paths, "renderer read nothing -- instrumentation missed the read path"
    for path in read_paths:
        assert abbyy_dir != path and abbyy_dir not in path.parents, (
            f"renderer read a sibling-engine file during isolated render: {path}"
        )


def test_structural_disagreement_is_observed_not_resolved(tmp_path: Path) -> None:
    """TEST-13: re-validate against real vol_01 sidecars once B4 generates them."""
    manifest_path, _manifest, _pages = _write_bundle(tmp_path, conflict=True)

    rendering = _render(manifest_path, tmp_path)
    conflicted = rendering["pages"][0]["blocks"][1]

    assert conflicted["block_type"] == "unknown"
    assert conflicted["block_type_confidence"] == "low"
    assert conflicted["block_type_conflicts"]
    assert {item["evidence_type"] for item in conflicted["block_type_conflicts"]} == {
        "geometry",
        "text",
    }
    matching_uncertainties = [
        item
        for item in rendering["structural_uncertainty_queue"]
        if item["rendering_block_id"] == conflicted["rendering_block_id"]
        and item["reason"] == "structural_disagreement"
    ]
    assert matching_uncertainties
    assert "winner" not in _walk_keys(conflicted)
    assert "resolved_block_type" not in _walk_keys(conflicted)


def test_semantic_validator_rejects_broken_derived_spans(tmp_path: Path) -> None:
    """The semantic validator binds the once-only + referential-integrity rules."""
    from build.lib.rendering_semantic_validator import validate_rendering

    manifest_path, _manifest, _pages = _write_bundle(tmp_path)
    rendering = _render(manifest_path, tmp_path)
    assert validate_rendering(rendering) == []

    # Duplicate an observation_token_id -> once-only invariant violated.
    dup = copy.deepcopy(rendering)
    words = dup["pages"][0]["blocks"][0]["lines"][0]["words"]
    words.append(copy.deepcopy(words[0]))
    dup_errors = validate_rendering(dup)
    assert any("appears 2 times" in error for error in dup_errors)

    # A derived span citing a contributor that is not in words[] -> referential
    # mismatch.
    dangling = copy.deepcopy(rendering)
    block_id = dangling["pages"][0]["blocks"][0]["rendering_block_id"]
    dangling["derived_spans_by_block"][block_id] = [
        {
            "derived_span_id": "ds-sha256:" + ("0" * 64),
            "operation": "joined_continuation",
            "contributor_observation_token_ids": [
                "ot-sha256:" + ("f" * 64),
                "ot-sha256:" + ("e" * 64),
            ],
            "boundary_type": "line_break",
            "structured_text": "continuation",
            "language_lane": "en",
            "dictionary_match": {"matched": False, "resource_id": "none", "matched_form": None},
            "candidate_window": "w1",
            "confidence_floor": None,
        }
    ]
    dangling_errors = validate_rendering(dangling)
    assert any("references missing word" in error for error in dangling_errors)


def test_render_manifest_enforces_semantic_validation_at_write_boundary(tmp_path: Path) -> None:
    """The production render path runs the semantic validator before writing.

    Arch3 section 2.6 makes the derived-span / once-only checks semantic-validator
    obligations; JSON Schema cannot express them. A sidecar whose two words share
    an observation_token_id must be rejected by render_manifest, not silently
    written.
    """
    manifest_path, _manifest, _pages = _write_bundle(tmp_path)
    page_path = tmp_path / "s1" / "tesseract" / "pages" / "page_0001.json"
    page = json.loads(page_path.read_text(encoding="utf-8"))
    first_line_words = page["blocks"][0]["lines"][0]["words"]
    assert len(first_line_words) >= 2
    first_line_words[1]["observation_token_id"] = first_line_words[0]["observation_token_id"]
    page_path.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="semantic validation"):
        _render(manifest_path, tmp_path)


def test_render_manifest_rerenders_when_manifest_hash_changes(tmp_path: Path) -> None:
    """Existing S2 output is reused only when its source manifest hash still matches."""
    from build.tools.ocr_pipeline import render_s2

    manifest_path, _manifest, _pages = _write_bundle(tmp_path)
    first = _render(manifest_path, tmp_path)
    assert first["engine_version"] == "fixture-1.0"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["engine_version"] = "fixture-2.0"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    _render(manifest_path, tmp_path)
    page_file = manifest_path.parent / "pages" / "page_0001.rendering-v1.json"
    second = json.loads(page_file.read_text(encoding="utf-8"))

    assert second["engine_version"] == "fixture-2.0"
    assert second["source_sidecar_refs"][0]["path"] == manifest_path.relative_to(tmp_path).as_posix()
    assert second["source_sidecar_refs"][0]["sha256"] == render_s2._file_sha256(manifest_path)


def test_render_s2_cli_threads_force_to_render_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The direct render_s2 CLI exposes --force and passes it through."""
    from build.tools.ocr_pipeline import render_s2

    calls: list[dict[str, Any]] = []

    def _fake_render_manifest(
        manifest_path: Path,
        *,
        repo_root: Path,
        output_dir: Path,
        force: bool,
        allow_stale_manifest: bool,
    ) -> dict[str, Any]:
        calls.append(
            {
                "manifest_path": manifest_path,
                "repo_root": repo_root,
                "output_dir": output_dir,
                "force": force,
                "allow_stale_manifest": allow_stale_manifest,
            }
        )
        return {}

    monkeypatch.setattr(render_s2, "render_manifest", _fake_render_manifest)
    manifest_path = tmp_path / "manifest.json"
    output_dir = tmp_path / "rendering"

    assert render_s2.main(
        [
            str(manifest_path),
            "--repo-root",
            str(tmp_path),
            "--output-dir",
            str(output_dir),
            "--force",
        ]
    ) == 0

    assert calls == [
        {
            "manifest_path": manifest_path,
            "repo_root": tmp_path,
            "output_dir": output_dir,
            "force": True,
            "allow_stale_manifest": False,
        }
    ]


# ---------------------------------------------------------------------------
# Helpers for tesseract_line_attrs tests
# ---------------------------------------------------------------------------


def _write_tla_bundle(
    root: Path,
    *,
    line_text: str,
    tla_entry: dict[str, Any] | None,
    engine_family: str = "tesseract",
    rendering_id: str = "tesseract-render",
) -> tuple[Path, str]:
    """Write a minimal one-block/one-line sidecar bundle.

    Returns (manifest_path, line_native_id).  tla_entry=None means no
    tesseract_line_attrs key in page_extras_carried at all.
    """
    manifest_id = f"{engine_family}-tla-manifest"
    line_label = "p1-b1-l1"
    line_obj = _line(label=line_label, text=line_text, y=120)
    line_native_id: str = line_obj["line_native_id"]

    page_extras: dict[str, Any] = {}
    if tla_entry is not None:
        page_extras["tesseract_line_attrs"] = {line_native_id: tla_entry}

    page: dict[str, Any] = {
        "schema_version": "sidecar-page-v1",
        "manifest_id": manifest_id,
        "rendering_id": rendering_id,
        "page_native_id": "page_0001",
        "page_sequence": 1,
        "page_dimensions_native": {"width": 1000, "height": 1000, "unit": "pixel"},
        "blocks": [
            {
                "block_id": "p1-b1",
                "block_type": "text",
                "bbox_native": {"x": 50, "y": 100, "w": 560, "h": 40},
                "lines": [line_obj],
            }
        ],
        "parsed_keys_index": [],
        "page_extras_carried": page_extras,
        "page_extras_carried_keys": sorted(page_extras.keys()),
        "page_extras_jcs_sha256": ZERO_SHA,
        "source_payload_sha256": ONE_SHA,
    }

    page_path = root / "s1" / engine_family / "pages" / "page_0001.json"
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(json.dumps(page, indent=2, ensure_ascii=False), encoding="utf-8")
    rel_page = page_path.relative_to(root).as_posix()

    manifest: dict[str, Any] = {
        "schema_version": "sidecar-manifest-v1",
        "manifest_id": manifest_id,
        "work_id": "schaff-herzog",
        "edition_id": "nsh-1908-1914",
        "volume": 1,
        "rendering_id": rendering_id,
        "engine_family": engine_family,
        "engine_version": "fixture-1.0",
        "source_lineage_id": f"{engine_family}-lineage",
        "source_files": [{"path": "raw/source-fixture.json", "sha256": ONE_SHA}],
        "pages": [
            {
                "page_native_id": page["page_native_id"],
                "page_sequence": page["page_sequence"],
                "status": "eligible",
                "sidecar_page_path": rel_page,
                "source_payload_sha256": page["source_payload_sha256"],
                "edition_page_key": {
                    "section": "body",
                    "anchor": page["page_sequence"],
                    "ordinal": 0,
                },
            }
        ],
        "manifest_cross_check": {
            "samples_checked": 1,
            "samples_matched": 1,
            "samples_inconclusive": 0,
            "failed_samples": [],
        },
        "bundle_extras_carried": {},
        "bundle_extras_carried_keys": [],
        "bundle_extras_jcs_sha256": ZERO_SHA,
        "created_at": "2026-05-29T00:00:00Z",
    }
    manifest_path = root / "s1" / engine_family / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest_path, line_native_id


# ---------------------------------------------------------------------------
# tesseract_line_attrs -> line_geometry population tests
# ---------------------------------------------------------------------------


def test_tesseract_x_size_populates_line_geometry(tmp_path: Path) -> None:
    """x_size from tesseract_line_attrs flows into line_geometry.x_size."""
    manifest_path, _ = _write_tla_bundle(
        tmp_path,
        line_text="ABELARD",
        tla_entry={"x_size": 57.5, "x_descenders": 7.5, "x_ascenders": 13.5},
    )
    rendering = _render(manifest_path, tmp_path)
    line = rendering["pages"][0]["blocks"][0]["lines"][0]
    assert line["line_geometry"]["x_size"] == 57.5
    assert line["line_geometry"]["x_descenders"] == 7.5
    assert line["line_geometry"]["x_ascenders"] == 13.5
    assert line["line_geometry"]["baseline"] is None


def test_tesseract_baseline_routed_to_line_extras_not_line_geometry(tmp_path: Path) -> None:
    """baseline [slope, intercept] goes to line_extras_carried, never line_geometry.baseline."""
    manifest_path, _ = _write_tla_bundle(
        tmp_path,
        line_text="ABELARD",
        tla_entry={"x_size": 57.5, "baseline": [0.001, -4.0]},
    )
    rendering = _render(manifest_path, tmp_path)
    line = rendering["pages"][0]["blocks"][0]["lines"][0]
    assert line["line_geometry"]["baseline"] is None
    assert line["line_extras_carried"].get("baseline") == [0.001, -4.0]
    assert "baseline" in line["line_extras_carried_keys"]


def test_no_tesseract_line_attrs_leaves_line_geometry_null(tmp_path: Path) -> None:
    """Tesseract rendering with no tesseract_line_attrs: line_geometry stays all None."""
    manifest_path, _ = _write_tla_bundle(
        tmp_path,
        line_text="ABELARD",
        tla_entry=None,
    )
    rendering = _render(manifest_path, tmp_path)
    line = rendering["pages"][0]["blocks"][0]["lines"][0]
    assert line["line_geometry"] == {
        "x_size": None,
        "baseline": None,
        "x_descenders": None,
        "x_ascenders": None,
    }


def test_non_tesseract_rendering_line_geometry_stays_null(tmp_path: Path) -> None:
    """Non-Tesseract engine (surya) with no tesseract_line_attrs: line_geometry all None."""
    manifest_path, _ = _write_tla_bundle(
        tmp_path,
        line_text="Body prose line without geometry data.",
        tla_entry=None,
        engine_family="surya",
        rendering_id="surya-render",
    )
    rendering = _render(manifest_path, tmp_path)
    line = rendering["pages"][0]["blocks"][0]["lines"][0]
    assert line["line_geometry"] == {
        "x_size": None,
        "baseline": None,
        "x_descenders": None,
        "x_ascenders": None,
    }


# ---------------------------------------------------------------------------
# x_size geometric signal in _classify_block tests
# ---------------------------------------------------------------------------


def test_x_size_below_threshold_adds_geometry_headword_signal(tmp_path: Path) -> None:
    """x_size < 62px adds a geometry signal suggesting headword to block_type_evidence."""
    manifest_path, _ = _write_tla_bundle(
        tmp_path,
        line_text="ABELARD",
        tla_entry={"x_size": 57.5},
    )
    rendering = _render(manifest_path, tmp_path)
    block = rendering["pages"][0]["blocks"][0]
    signals = block["block_type_evidence"]["signals"]
    geometry_headword = [
        s for s in signals
        if s["evidence_type"] == "geometry" and s["suggested_block_type"] == "headword"
    ]
    assert geometry_headword, f"Expected geometry/headword signal; got: {signals}"


def test_x_size_above_threshold_no_geometry_headword_signal(tmp_path: Path) -> None:
    """x_size >= 62px does not add a geometry headword signal."""
    manifest_path, _ = _write_tla_bundle(
        tmp_path,
        line_text="ABELARD",
        tla_entry={"x_size": 70.0},
    )
    rendering = _render(manifest_path, tmp_path)
    block = rendering["pages"][0]["blocks"][0]
    signals = block["block_type_evidence"]["signals"]
    geometry_headword = [
        s for s in signals
        if s["evidence_type"] == "geometry" and s["suggested_block_type"] == "headword"
    ]
    assert not geometry_headword, f"Unexpected geometry/headword signal at x_size=70.0: {signals}"


def test_x_size_geometry_signal_conflicts_with_prose_text(tmp_path: Path) -> None:
    """x_size < 62px on body prose (>= 6 words): geometry says headword, text says paragraph.

    Conflict must produce block_type=unknown with both geometry and text in conflicts.
    """
    manifest_path, _ = _write_tla_bundle(
        tmp_path,
        line_text="This long body prose line has more than six words signalling paragraph.",
        tla_entry={"x_size": 57.5},
    )
    rendering = _render(manifest_path, tmp_path)
    block = rendering["pages"][0]["blocks"][0]
    assert block["block_type"] == "unknown"
    assert block["block_type_confidence"] == "low"
    conflict_types = {c["evidence_type"] for c in block["block_type_conflicts"]}
    assert "geometry" in conflict_types
    assert "text" in conflict_types


# ---------------------------------------------------------------------------
# Codex review fixes (Q1 minimum, Q3 cross-ref, Q7 empty-text,
#                     additional non-Tesseract scope + Q5/Q6 coverage)
# ---------------------------------------------------------------------------


def _write_multiline_tla_bundle(
    root: Path,
    *,
    lines: list[tuple[str, dict[str, Any] | None]],
    engine_family: str = "tesseract",
    rendering_id: str = "tesseract-render",
) -> Path:
    """Write a one-block, multi-line sidecar bundle for x_size minimum tests.

    ``lines`` is a list of (line_text, tla_entry_or_None) pairs.
    """
    manifest_id = f"{engine_family}-multi-manifest"
    line_objs = [_line(label=f"p1-b1-l{i}", text=txt, y=120 + i * 25) for i, (txt, _) in enumerate(lines, 1)]
    tla: dict[str, Any] = {}
    for line_obj, (_, attrs) in zip(line_objs, lines):
        if attrs is not None:
            tla[line_obj["line_native_id"]] = attrs
    page_extras: dict[str, Any] = {"tesseract_line_attrs": tla} if tla else {}
    page: dict[str, Any] = {
        "schema_version": "sidecar-page-v1",
        "manifest_id": manifest_id,
        "rendering_id": rendering_id,
        "page_native_id": "page_0001",
        "page_sequence": 1,
        "page_dimensions_native": {"width": 1000, "height": 1000, "unit": "pixel"},
        "blocks": [{
            "block_id": "p1-b1",
            "block_type": "text",
            "bbox_native": {"x": 50, "y": 100, "w": 560, "h": 80},
            "lines": line_objs,
        }],
        "parsed_keys_index": [],
        "page_extras_carried": page_extras,
        "page_extras_carried_keys": sorted(page_extras.keys()),
        "page_extras_jcs_sha256": ZERO_SHA,
        "source_payload_sha256": ONE_SHA,
    }
    page_path = root / "s1" / engine_family / "pages" / "page_0001.json"
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(json.dumps(page, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest: dict[str, Any] = {
        "schema_version": "sidecar-manifest-v1",
        "manifest_id": manifest_id,
        "work_id": "schaff-herzog",
        "edition_id": "nsh-1908-1914",
        "volume": 1,
        "rendering_id": rendering_id,
        "engine_family": engine_family,
        "engine_version": "fixture-1.0",
        "source_lineage_id": f"{engine_family}-lineage",
        "source_files": [{"path": "raw/source-fixture.json", "sha256": ONE_SHA}],
        "pages": [{
            "page_native_id": page["page_native_id"],
            "page_sequence": page["page_sequence"],
            "status": "eligible",
            "sidecar_page_path": page_path.relative_to(root).as_posix(),
            "source_payload_sha256": page["source_payload_sha256"],
            "edition_page_key": {
                "section": "body",
                "anchor": page["page_sequence"],
                "ordinal": 0,
            },
        }],
        "manifest_cross_check": {"samples_checked": 1, "samples_matched": 1, "samples_inconclusive": 0, "failed_samples": []},
        "bundle_extras_carried": {},
        "bundle_extras_carried_keys": [],
        "bundle_extras_jcs_sha256": ZERO_SHA,
        "created_at": "2026-05-29T00:00:00Z",
    }
    manifest_path = root / "s1" / engine_family / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def test_empty_text_block_with_x_size_below_threshold_not_headword(tmp_path: Path) -> None:
    """Empty-text block with x_size < 62px must not classify as headword (Q7)."""
    manifest_path, _ = _write_tla_bundle(
        tmp_path,
        line_text="",
        tla_entry={"x_size": 57.5},
    )
    rendering = _render(manifest_path, tmp_path)
    block = rendering["pages"][0]["blocks"][0]
    assert block["block_type"] != "headword", (
        f"Empty-text block classified as {block['block_type']!r}; x_size must not fire on empty text"
    )


def test_minimum_x_size_triggers_geometry_signal_for_multiline_headword_block(tmp_path: Path) -> None:
    """A two-line block with x_sizes [57.5, 70.0] fires geometry signal via minimum (Q1).

    Median would pick 70.0 and miss the heading-sized first line.
    """
    manifest_path = _write_multiline_tla_bundle(
        tmp_path,
        lines=[
            ("ABELARD", {"x_size": 57.5}),
            ("continued body runover at body size here", {"x_size": 70.0}),
        ],
    )
    rendering = _render(manifest_path, tmp_path)
    block = rendering["pages"][0]["blocks"][0]
    signals = block["block_type_evidence"]["signals"]
    geometry_headword = [
        s for s in signals
        if s["evidence_type"] == "geometry" and s["suggested_block_type"] == "headword"
    ]
    assert geometry_headword, f"Expected geometry/headword signal from minimum x_size; got: {signals}"


def test_cross_reference_not_conflicted_by_x_size_signal(tmp_path: Path) -> None:
    """'See AUGUSTINE' with x_size < 62px stays cross_reference, not unknown (Q3).

    The geometry headword signal must not fire when text already signals cross_reference.
    """
    manifest_path, _ = _write_tla_bundle(
        tmp_path,
        line_text="See AUGUSTINE",
        tla_entry={"x_size": 57.5},
    )
    rendering = _render(manifest_path, tmp_path)
    block = rendering["pages"][0]["blocks"][0]
    assert block["block_type"] == "cross_reference", (
        f"Expected cross_reference, got {block['block_type']!r}"
    )
    assert "cross_reference_target" in block


def test_non_tesseract_engine_ignores_tesseract_line_attrs_key(tmp_path: Path) -> None:
    """Surya sidecar carrying tesseract_line_attrs key still gets null line_geometry (additional finding).

    The engine_family guard in _render_page must strip the attrs for non-Tesseract engines.
    """
    manifest_path, _ = _write_tla_bundle(
        tmp_path,
        line_text="Body prose line.",
        tla_entry={"x_size": 57.5},
        engine_family="surya",
        rendering_id="surya-render",
    )
    rendering = _render(manifest_path, tmp_path)
    line = rendering["pages"][0]["blocks"][0]["lines"][0]
    assert line["line_geometry"] == {
        "x_size": None,
        "baseline": None,
        "x_descenders": None,
        "x_ascenders": None,
    }


def test_x_size_at_exact_threshold_no_geometry_headword_signal(tmp_path: Path) -> None:
    """x_size == 62.0 (exactly at threshold) does NOT add a geometry headword signal (Q6 boundary)."""
    manifest_path, _ = _write_tla_bundle(
        tmp_path,
        line_text="ABELARD",
        tla_entry={"x_size": 62.0},
    )
    rendering = _render(manifest_path, tmp_path)
    block = rendering["pages"][0]["blocks"][0]
    signals = block["block_type_evidence"]["signals"]
    geometry_headword = [
        s for s in signals
        if s["evidence_type"] == "geometry" and s["suggested_block_type"] == "headword"
    ]
    assert not geometry_headword, f"Unexpected geometry/headword at x_size=62.0: {signals}"


def test_tesseract_attrs_rendering_passes_schema_and_semantic_validation(tmp_path: Path) -> None:
    """Tesseract rendering with populated line_geometry and baseline in extras is schema-valid (Q5)."""
    from build.lib.rendering_semantic_validator import validate_rendering

    manifest_path, _ = _write_tla_bundle(
        tmp_path,
        line_text="ABELARD",
        tla_entry={"x_size": 57.5, "x_descenders": 7.5, "x_ascenders": 13.5, "baseline": [0.001, -4.0]},
    )
    rendering = _render(manifest_path, tmp_path)
    jsonschema.validate(instance=rendering, schema=_schema("rendering-v1"))
    assert validate_rendering(rendering) == []
