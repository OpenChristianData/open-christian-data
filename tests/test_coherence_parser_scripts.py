"""Bounded contracts for the maintained script paths in Sub #202."""

from __future__ import annotations

import hashlib
import json
import urllib.error
from pathlib import Path

import pytest

from build.scripts import add_token_counts
from build.scripts import build_apocrypha_verse_index as apocrypha_index
from build.scripts import build_kjv_verse_index as kjv_index
from build.scripts import build_verse_index as bsb_index
from build.scripts import download_gutenberg, download_sword_modules
from build.scripts import generate_disputed_verses, short_entries_report
from build.scripts import upload_huggingface


def test_add_token_counts_handles_add_mismatch_skip_and_recursive_units() -> None:
    records = [
        {"commentary_text": "A bounded commentary sentence."},
        {"commentary_text": ""},
        {"commentary_text": "Existing count is intentionally wrong.", "token_count": 0},
    ]

    added, mismatches, skipped, computed = add_token_counts.process_records_list(
        records, add_token_counts.extract_text_commentary, dry_run=False
    )

    assert (added, mismatches, skipped) == (1, 1, 1)
    assert records[0]["token_count"] == add_token_counts.count_tokens(
        "A bounded commentary sentence."
    )
    assert computed == [
        records[0]["token_count"],
        add_token_counts.count_tokens("Existing count is intentionally wrong."),
    ]

    units = [
        {
            "content": "Root unit content.",
            "children": [{"content": "Nested unit content."}],
        }
    ]
    unit_added, unit_mismatches, unit_counts = add_token_counts.process_doctrinal_units(
        units, dry_run=False
    )
    assert (unit_added, unit_mismatches) == (2, 0)
    assert units[0]["token_count"] == add_token_counts.count_tokens("Root unit content.")
    assert units[0]["children"][0]["token_count"] == add_token_counts.count_tokens(
        "Nested unit content."
    )
    assert unit_counts == [
        add_token_counts.count_tokens("Root unit content."),
        add_token_counts.count_tokens("Nested unit content."),
    ]

class _BytesResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return self.payload


def test_apocrypha_index_uses_deuterocanonical_books_and_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "apocrypha.json"
    monkeypatch.setattr(apocrypha_index, "setup_logging", lambda: None)
    monkeypatch.setattr(apocrypha_index, "OUTPUT_FILE", output)
    monkeypatch.setattr(
        apocrypha_index,
        "load_pysword_kjva",
        lambda: [
            ("Genesis", "Gen", [1]),
            ("Prayer of Manasseh", "PrMan", [1]),
        ],
    )

    apocrypha_index.main()

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["book_count"] == 1
    assert result["books"]["PrMan"]["chapter_count"] == 1
    assert result["books"]["PrMan"]["verses"]["1"] == list(range(1, 16))
    assert "Gen" not in result["books"]

    monkeypatch.setattr(apocrypha_index, "load_pysword_kjva", lambda: [("Genesis", "Gen", [5])])
    with pytest.raises(SystemExit):
        apocrypha_index.main()


def test_kjv_index_builds_from_canon_table_and_rejects_bad_conf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path
    kjv_dir = root / "KJV"
    module_data = kjv_dir / "modules" / "texts" / "ztext" / "kjv"
    module_data.mkdir(parents=True)
    (kjv_dir / "mods.d").mkdir()
    conf = kjv_dir / "mods.d" / "kjv.conf"
    conf.write_text("[KJV]\nModDrv=zText\n", encoding="utf-8")
    output = root / "kjv-index.json"

    monkeypatch.setattr(kjv_index, "_setup_logging", lambda: None)
    monkeypatch.setattr(kjv_index, "REPO_ROOT", root)
    monkeypatch.setattr(kjv_index, "KJV_DIR", kjv_dir)
    monkeypatch.setattr(kjv_index, "MODULE_DATA_DIR", module_data)
    monkeypatch.setattr(kjv_index, "KJV_ZIP", root / "missing.zip")
    monkeypatch.setattr(kjv_index, "OUTPUT_FILE", output)

    kjv_index.main()

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["book_count"] == 66
    assert result["books"]["Matt"]["verses"]["17"][-1] == 27
    assert result["books"]["Rev"]["chapter_count"] == 22
    assert result["books"]["Rev"]["verses"]["22"][-1] == 21

    conf.write_text("[KJV]\nModDrv=wrong\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        kjv_index.main()


_CANONICAL_OSIS = (
    "Gen Exod Lev Num Deut Josh Judg Ruth 1Sam 2Sam 1Kgs 2Kgs 1Chr 2Chr Ezra "
    "Neh Esth Job Ps Prov Eccl Song Isa Jer Lam Ezek Dan Hos Joel Amos Obad Jonah "
    "Mic Nah Hab Zeph Hag Zech Mal Matt Mark Luke John Acts Rom 1Cor 2Cor Gal Eph "
    "Phil Col 1Thess 2Thess 1Tim 2Tim Titus Phlm Heb Jas 1Pet 2Pet 1John 2John "
    "3John Jude Rev"
).split()


def _write_bsb_fixture(directory: Path, *, malformed: bool = False) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for number, osis in enumerate(_CANONICAL_OSIS, start=1):
        chapter = 0 if malformed and osis == "Gen" else 1
        payload = {
            "meta": {
                "scope": {
                    "book": osis,
                    "book_osis": osis,
                    "book_number": number,
                }
            },
            "data": [{"chapter": chapter, "verse": 1, "text": "bounded"}],
        }
        (directory / f"{number:02d}-{osis}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )


def test_bsb_verse_index_requires_all_books_and_positive_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bsb_dir = tmp_path / "bsb"
    output = tmp_path / "verse-index.json"
    _write_bsb_fixture(bsb_dir)
    monkeypatch.setattr(bsb_index, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(bsb_index, "BSB_DIR", bsb_dir)
    monkeypatch.setattr(bsb_index, "OUTPUT_FILE", output)

    bsb_index.main()

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["book_count"] == 66
    assert result["books"]["Gen"]["verses"] == {"1": [1]}
    assert "_source_file" not in result["books"]["Gen"]

    _write_bsb_fixture(bsb_dir, malformed=True)
    with pytest.raises(SystemExit):
        bsb_index.main()


def test_gutenberg_downloader_hashes_success_and_retries_transient_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    def successful_urlopen(request, timeout=60):
        attempts.append(request.full_url)
        return _BytesResponse(b"bounded Gutenberg text")

    monkeypatch.setattr(download_gutenberg.urllib.request, "urlopen", successful_urlopen)
    assert (
        download_gutenberg.download_text("https://example.test/text")
        == b"bounded Gutenberg text"
    )
    assert attempts == ["https://example.test/text"]
    assert download_gutenberg.sha256_bytes(b"bounded Gutenberg text") == (
        "sha256:" + hashlib.sha256(b"bounded Gutenberg text").hexdigest()
    )

    attempts.clear()

    def transient_urlopen(request, timeout=60):
        attempts.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 503, "busy", {}, None)

    monkeypatch.setattr(download_gutenberg.urllib.request, "urlopen", transient_urlopen)
    monkeypatch.setattr(download_gutenberg.time, "sleep", lambda _delay: None)
    with pytest.raises(urllib.error.HTTPError):
        download_gutenberg.download_text("https://example.test/transient")
    assert len(attempts) == 4


def test_sword_downloader_distinguishes_dry_run_cached_and_invalid_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cached = tmp_path / "cached.zip"
    cached.write_bytes(b"PK\x03\x04fixture")
    assert download_sword_modules.is_valid_zip(cached)
    assert download_sword_modules.sha256_file(cached) == hashlib.sha256(
        b"PK\x03\x04fixture"
    ).hexdigest()
    cached_result = download_sword_modules.download_module("Barnes", cached, dry_run=True)
    assert cached_result["status"] == "cached"

    dry_run_dest = tmp_path / "dry-run.zip"
    monkeypatch.setattr(download_sword_modules, "RAW_DIR", tmp_path)
    dry_result = download_sword_modules.download_module("Wesley", dry_run_dest, dry_run=True)
    assert dry_result["status"] == "dry-run"
    assert not dry_run_dest.exists()

    def html_urlopen(request, timeout=120):
        return _BytesResponse(b"<html>not a zip</html>")

    monkeypatch.setattr(download_sword_modules.urllib.request, "urlopen", html_urlopen)
    monkeypatch.setattr(download_sword_modules.time, "sleep", lambda _delay: None)
    invalid_result = download_sword_modules.download_module(
        "Barnes", tmp_path / "downloaded.zip", dry_run=False
    )
    assert invalid_result["status"] == "error: not a valid ZIP after download"
    assert (tmp_path / "downloaded.zip").read_bytes().startswith(b"<html>")


def test_disputed_verse_computation_labels_offsets_and_missing_indexes() -> None:
    bsb = {"books": {"Gen": {"verses": {"1": [1]}}}}
    kjv = {"books": {"Gen": {"verses": {"1": [1, 2, 3]}}}}
    result = generate_disputed_verses.compute_disputed(
        bsb, kjv, {("Gen", "1", 2)}
    )
    assert result == {
        "Gen": {
            "1": [
                {"verse": 2, "type": "versification_offset"},
                {"verse": 3, "type": "manuscript_omission"},
            ]
        }
    }

    with pytest.raises(SystemExit):
        generate_disputed_verses.load_index(Path("Z:/missing-index.json"), "BSB")


def test_short_entries_report_returns_ascii_previews_for_short_records(tmp_path: Path) -> None:
    commentary_dir = tmp_path / "commentary"
    commentary_dir.mkdir()
    (commentary_dir / "chapter.json").write_text(
        json.dumps(
            {
                "data": [
                    {"entry_id": "short", "word_count": 2, "commentary_text": "café\nshort"},
                    {"entry_id": "long", "word_count": 10, "commentary_text": "long"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (commentary_dir / "_manifest.json").write_text("{}", encoding="utf-8")

    result = short_entries_report.scan_commentary(commentary_dir, threshold=5)

    assert result == [("short", 2, "caf? short")]
    assert short_entries_report.ascii_safe("one two three", max_len=7) == "one two..."


def test_huggingface_upload_plan_and_retry_are_network_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    (export_dir / "README.md").write_text("dataset card", encoding="utf-8")
    (export_dir / "b.jsonl").write_text("{}\n", encoding="utf-8")
    (export_dir / "a.jsonl").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(upload_huggingface, "EXPORT_DIR", export_dir)

    all_files = upload_huggingface.collect_upload_files()
    assert [(local.name, remote) for local, remote in all_files] == [
        ("README.md", "README.md"),
        ("a.jsonl", "data/a.jsonl"),
        ("b.jsonl", "data/b.jsonl"),
    ]
    assert upload_huggingface.collect_upload_files(readme_only=True) == [
        (export_dir / "README.md", "README.md")
    ]

    class Api:
        def __init__(self):
            self.calls = []

        def upload_file(self, **kwargs):
            self.calls.append(kwargs)

    api = Api()
    assert upload_huggingface.upload_with_retry(api, export_dir / "a.jsonl", "data/a.jsonl")
    assert len(api.calls) == 1
    assert api.calls[0]["repo_id"] == upload_huggingface.HF_REPO_ID

    class FailingApi:
        def __init__(self):
            self.calls = 0

        def upload_file(self, **kwargs):
            self.calls += 1
            raise RuntimeError("bounded upload failure")

    monkeypatch.setattr(upload_huggingface, "RETRY_DELAYS", [0, 0, 0])
    failing = FailingApi()
    assert not upload_huggingface.upload_with_retry(
        failing, export_dir / "a.jsonl", "data/a.jsonl"
    )
    assert failing.calls == upload_huggingface.MAX_RETRIES
