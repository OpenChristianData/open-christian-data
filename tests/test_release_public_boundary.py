from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from ocd_kernel.library._common import canonical_bytes
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.public_allowlist import (
    check_public_boundary,
    preview_release,
    render_dataset_card,
)
from ocd_kernel.release.verify import verify_release_v2

from tests.test_release_assembly_v2 import (
    _build_single,
    _files,
    _failed_release,
    _item,
    _multi_configuration_root,
    _promoted_category,
    _read_json,
    _selection,
    _write_json,
)


@pytest.fixture
def tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Keep promoted fixture paths short on Windows."""

    return tmp_path_factory.mktemp("r")


def _manifest(release: Path) -> list[dict[str, Any]]:
    public = release / "public"
    return [
        {
            "path": path,
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for path, content in sorted(_files(public).items())
    ]


def _report(release: Path) -> dict[str, Any]:
    return _read_json(release / "internal" / "release-report.json")


def _rewrite_configuration(
    release: Path, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Rewrite one public config and rebind its private report/card metadata."""

    report = _report(release)
    config = report["configurations"][0]
    content = b"".join(canonical_bytes(row) for row in rows)
    (release / config["path"]).write_bytes(content)
    config["row_count"] = len(rows)
    config["sha256"] = hashlib.sha256(content).hexdigest()
    from ocd_kernel.release.features import configuration_features
    from ocd_kernel.release.typed_rows import encode_rows
    config["features"] = configuration_features(rows)
    typed_content = encode_rows(rows, config["features"])
    (release / config["typed_companion"]["path"]).write_bytes(typed_content)
    config["typed_companion"]["sha256"] = hashlib.sha256(typed_content).hexdigest()
    _write_json(release / "internal" / "release-report.json", report)
    (release / "public" / "README.md").write_text(
        render_dataset_card(report["configurations"]),
        encoding="utf-8",
        newline="\n",
    )
    return report


def test_promoted_release_has_derived_card_clean_boundary_and_manifest(
    tmp_path: Path,
) -> None:
    root, release, selection, _acceptance = _build_single(tmp_path)
    report = _report(release)
    card_path = release / "public" / "README.md"

    assert report["status"] == "pass"
    assert card_path.read_text(encoding="utf-8") == render_dataset_card(
        report["configurations"]
    )
    assert check_public_boundary(release, report) == []
    assert verify_release_v2(root, release, selection=selection) == {
        "status": "pass",
        "errors": [],
    }

    preview = preview_release(root, release, selection=selection)
    assert preview["status"] == "pass"
    assert preview["errors"] == []
    assert preview["files"] == _manifest(release)
    assert preview["files"] == [
        {
            "path": "README.md",
            "size_bytes": card_path.stat().st_size,
            "sha256": hashlib.sha256(card_path.read_bytes()).hexdigest(),
        },
        {
            "path": "data/quotations/train.arrow",
            "size_bytes": (release / "public/data/quotations/train.arrow").stat().st_size,
            "sha256": hashlib.sha256(
                (release / "public/data/quotations/train.arrow").read_bytes()
            ).hexdigest(),
        },
        {
            "path": "data/quotations/train.jsonl",
            "size_bytes": (release / "public/data/quotations/train.jsonl").stat().st_size,
            "sha256": hashlib.sha256(
                (release / "public/data/quotations/train.jsonl").read_bytes()
            ).hexdigest(),
        },
    ]
    assert preview["upload_performed"] is False


def test_card_and_upload_manifest_are_deterministic_for_multiple_configurations(
    tmp_path: Path,
) -> None:
    root, accepted = _multi_configuration_root(tmp_path)
    selection = _selection(
        _item(root, "quote", "quotations", accepted["quotations"]),
        _item(root, "devotional", "devotionals", accepted["devotionals"]),
    )
    first = tmp_path / "release-one"
    second = tmp_path / "release-two"
    first_report = assemble_release_v2(root, first, selection=selection)
    second_report = assemble_release_v2(root, second, selection=selection)

    first_card = (first / "public" / "README.md").read_text(encoding="utf-8")
    second_card = (second / "public" / "README.md").read_text(encoding="utf-8")
    assert first_report["configurations"] == second_report["configurations"]
    assert first_card == second_card
    assert first_card == render_dataset_card(
        list(reversed(first_report["configurations"]))
    )
    for config in first_report["configurations"]:
        assert config["path"].removeprefix("public/") in first_card
        assert str(config["row_count"]) in first_card
        assert config["sha256"] not in first_card

    first_preview = preview_release(root, first, selection=selection)
    second_preview = preview_release(root, second, selection=selection)
    assert first_preview["status"] == second_preview["status"] == "pass"
    assert first_preview["files"] == second_preview["files"]
    assert first_preview["files"] == _manifest(first)
    assert _files(first / "public") == _files(second / "public")


@pytest.mark.parametrize("mutation", ["tampered", "missing"])
def test_tampered_or_missing_card_fails_verification_and_preview(
    tmp_path: Path, mutation: str
) -> None:
    root, release, selection, _acceptance = _build_single(tmp_path)
    card_path = release / "public" / "README.md"
    if mutation == "tampered":
        card_path.write_text(
            card_path.read_text(encoding="utf-8") + "\nforged card\n",
            encoding="utf-8",
            newline="\n",
        )
    else:
        card_path.unlink()

    checked = verify_release_v2(root, release, selection=selection)
    assert checked["status"] == "fail"
    assert checked["errors"]
    diagnostics = " ".join(checked["errors"]).lower()
    assert any(term in diagnostics for term in ("readme", "card", "file set"))

    preview = preview_release(root, release, selection=selection)
    assert preview["status"] == "fail"
    assert preview["errors"]
    assert preview["upload_performed"] is False


def test_public_boundary_rejects_extra_tei_and_private_files(
    tmp_path: Path,
) -> None:
    root, release, selection, _acceptance = _build_single(tmp_path)
    report = _report(release)
    for relative, content in (
        ("accidental/master.tei.xml", "<TEI/>"),
        ("internal/release-report.json", "{}\n"),
    ):
        extra = release / "public" / relative
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text(content, encoding="utf-8")
        errors = check_public_boundary(release, report)
        assert errors
        assert "public file" in " ".join(errors).lower() or "allowlist" in " ".join(errors).lower()

        preview = preview_release(root, release, selection=selection)
        assert preview["status"] == "fail"
        assert preview["errors"]
        assert preview["upload_performed"] is False
        extra.unlink()


def test_public_boundary_scans_nested_private_payloads_and_allows_https_urls(
    tmp_path: Path,
) -> None:
    _root, release, _selection, _acceptance = _build_single(tmp_path)
    config = _report(release)["configurations"][0]
    base_rows = [
        json.loads(line)
        for line in (release / config["path"]).read_text(encoding="utf-8").splitlines()
        if line
    ]
    probes = (
        {"path": "raw\\private.xml"},
        {"path": "internal\\receipt.json"},
        {"path": "reports/private.json"},
        {"path": "exports/private.json"},
        {"markup": "<TEI/>"},
        {"header": "<teiHeader/>"},
        {"source_annotations": "urn:ocd:source-marker:%7B%22rend%22%3A%22comment-digest%3A"
         + "a" * 64 + "%22%7D"},
        {"source_annotations": "urn:ocd:source-marker:%7B%22marker%22%3A%22raw%2Fprivate.xml%22%7D"},
        {"source_annotations": "urn:ocd:source-marker:%3CTEI%2F%3E"},
        {"source_hash": "abcdef123456"},
        {"source_sha256": "0123456789abcdef"},
    )
    for probe in probes:
        rows = copy.deepcopy(base_rows)
        rows[0]["nested_probe"] = {"nested": probe}
        report = _rewrite_configuration(release, rows)
        errors = check_public_boundary(release, report)
        assert errors, probe

    rows = copy.deepcopy(base_rows)
    rows[0]["text"] += " See https://example.org/library/book"
    report = _rewrite_configuration(release, rows)
    assert check_public_boundary(release, report) == []

    rows = copy.deepcopy(base_rows)
    rows[0]["nested_probe"] = {"source_annotations":
        "urn:ocd:source-marker:%7B%22rend%22%3A%22source-comment-retained-privately%22%7D"}
    report = _rewrite_configuration(release, rows)
    assert any("private source annotation" in error for error in check_public_boundary(release, report))

    rows = copy.deepcopy(base_rows)
    rows[0]["nested_probe"] = {"source_annotations": "source-annotation:00001"}
    report = _rewrite_configuration(release, rows)
    assert check_public_boundary(release, report) == []


def test_preview_revalidates_release_before_boundary_and_does_not_write(
    tmp_path: Path,
) -> None:
    root, release, selection, _acceptance = _build_single(tmp_path)
    report = _report(release)
    receipt_path = release / report["items"][0]["receipt_path"]
    receipt = _read_json(receipt_path)
    receipt["row_count"] = 0
    _write_json(receipt_path, receipt)
    before_release = _files(release)
    before_root = _files(root)

    # The public tree itself remains boundary-clean; the private receipt is
    # deliberately invalid so only the release verifier can reject this.
    assert check_public_boundary(release, report) == []
    preview = preview_release(root, release, selection=selection)
    assert preview["status"] == "fail"
    assert preview["errors"]
    assert preview["upload_performed"] is False
    assert _files(release) == before_release
    assert _files(root) == before_root


def test_preview_rejects_failed_release_before_upload_boundary(
    tmp_path: Path,
) -> None:
    root, acceptance = _promoted_category(tmp_path, "quotations", "preview-failed")
    selection = _selection(
        _item(root, "quote", "quotations", acceptance),
        _item(root, "future", "future_category", acceptance),
    )
    release = tmp_path / "failed-release"
    report, retained_stage = _failed_release(root, release, selection=selection)
    assert report["status"] == "fail"
    assert not release.exists()

    preview = preview_release(root, retained_stage, selection=selection)
    assert preview["status"] == "fail"
    assert any("failed" in error.lower() for error in preview["errors"])
    assert preview["upload_performed"] is False


def test_preview_rejects_excluded_only_empty_release(
    tmp_path: Path,
) -> None:
    root, acceptance = _promoted_category(tmp_path, "quotations", "preview-empty")
    selection = _selection(
        _item(
            root,
            "quote",
            "quotations",
            acceptance,
            exclude_reason="held for later review",
        )
    )
    release = tmp_path / "empty-release"
    report = assemble_release_v2(root, release, selection=selection)
    assert report["status"] == "pass"
    assert report["configurations"] == []
    assert _files(release / "public") == {}

    preview = preview_release(root, release, selection=selection)
    assert preview["status"] == "fail"
    assert preview["files"] == []
    assert any(
        term in " ".join(preview["errors"]).lower()
        for term in ("empty", "no public", "configuration")
    )
    assert preview["upload_performed"] is False


def test_preview_rejects_public_reparse_entry(tmp_path: Path) -> None:
    root, release, selection, _acceptance = _build_single(tmp_path)
    target = tmp_path / "outside-public.txt"
    target.write_text("outside", encoding="utf-8")
    link = release / "public" / "linked.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    preview = preview_release(root, release, selection=selection)
    assert preview["status"] == "fail"
    diagnostics = " ".join(preview["errors"]).lower()
    assert "reparse" in diagnostics or "symlink" in diagnostics
    assert preview["upload_performed"] is False


def test_public_boundary_rejects_detected_reparse_without_link_privileges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ocd_kernel.release.public_allowlist as boundary

    _root, release, _selection, _acceptance = _build_single(tmp_path)
    original = boundary._is_link
    monkeypatch.setattr(boundary, "_is_link", lambda path: path.name == "data" or original(path))
    errors = check_public_boundary(release, _report(release))
    assert any("reparse" in error for error in errors)


def test_preview_rejects_late_public_mutation_after_boundary_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ocd_kernel.release.public_allowlist as public_allowlist

    root, release, selection, _acceptance = _build_single(tmp_path)

    def mutate_then_pass(*args: Any, **kwargs: Any) -> list[str]:
        report = args[1]
        config = report["configurations"][0]
        path = Path(release) / config["path"]
        path.write_bytes(path.read_bytes() + b"{}\n")
        return []

    monkeypatch.setattr(public_allowlist, "check_public_boundary", mutate_then_pass)
    preview = public_allowlist.preview_release(root, release, selection=selection)
    assert preview["status"] == "fail"
    assert preview["errors"]
    assert preview["upload_performed"] is False


def test_publish_hf_release_dry_run_prints_manifest_and_never_writes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from build.tools.publish_hf_release import main

    root, release, selection, _acceptance = _build_single(tmp_path)
    selection_path = tmp_path / "selection.json"
    _write_json(selection_path, selection)
    before_release = _files(release)
    before_root = _files(root)

    exit_code = main(
        [
            "--root",
            str(root),
            "--release",
            str(release),
            "--selection",
            str(selection_path),
            "--dry-run",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "pass"
    assert payload["files"] == _manifest(release)
    assert payload["upload_performed"] is False
    assert _files(release) == before_release
    assert _files(root) == before_root


def test_publish_hf_release_returns_one_for_failed_preview(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from build.tools.publish_hf_release import main

    root, acceptance = _promoted_category(tmp_path, "quotations", "cli-failed")
    selection = _selection(
        _item(root, "quote", "quotations", acceptance),
        _item(root, "future", "future_category", acceptance),
    )
    release = tmp_path / "failed-release"
    _report, retained_stage = _failed_release(root, release, selection=selection)
    assert not release.exists()
    selection_path = tmp_path / "selection.json"
    _write_json(selection_path, selection)

    exit_code = main(
        [
            "--root",
            str(root),
            "--release",
            str(retained_stage),
            "--selection",
            str(selection_path),
            "--dry-run",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "fail"
    assert payload["errors"]
    assert payload["upload_performed"] is False


def test_publish_hf_release_requires_dry_run_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from build.tools.publish_hf_release import main

    root, release, selection, _acceptance = _build_single(tmp_path)
    selection_path = tmp_path / "selection.json"
    _write_json(selection_path, selection)

    with pytest.raises(SystemExit) as caught:
        main(
            [
                "--root",
                str(root),
                "--release",
                str(release),
                "--selection",
                str(selection_path),
            ]
        )
    assert caught.value.code == 2
    assert "dry-run" in capsys.readouterr().err.lower()
def test_privacy_scan_avoids_regex_without_required_characters(monkeypatch):
    from ocd_kernel.release import public_allowlist as boundary
    calls = []
    original = boundary._LOCAL_PATH

    class ObservedPattern:
        def search(self, text):
            calls.append(text)
            return original.search(text)

    monkeypatch.setattr(boundary, '_LOCAL_PATH', ObservedPattern())
    assert boundary._scan([{'text': 'Amen'} for _ in range(1000)], 'rows') == []
    assert not calls


def test_privacy_scan_normalizes_repeated_short_field_names_once(monkeypatch):
    from ocd_kernel.release import public_allowlist as boundary
    original = boundary.re.sub
    calls = []
    key = 'speed_probe_repeated_field'

    def observed(pattern, replacement, value, *args, **kwargs):
        if value == key:
            calls.append(value)
        return original(pattern, replacement, value, *args, **kwargs)

    monkeypatch.setattr(boundary.re, 'sub', observed)
    assert boundary._scan([{key: 'Amen'} for _ in range(1000)], 'rows') == []
    assert len(calls) <= 1


@pytest.mark.parametrize('value', [
    'C:\\Users\\Reader', 'file://local', '/tmp/file', 'raw/file', '\\\\server\\share',
    '%2Fhome%2Fprivate', '%3CTEI%3E', '<x:teiHeader/>', 'a'*64,
    'urn:ocd:private', 'urn%3Aocd%3Aprivate', 'quoted /users/private/file',
    'Amen', 'https://example.org/text', 'a'*63, '<paragraph>',
])
def test_privacy_scan_retains_string_detection(value):
    from urllib.parse import unquote
    from ocd_kernel.release import public_allowlist as boundary
    candidates = (value, unquote(value)) if '%' in value else (value,)
    if any('urn:ocd:' in text.lower() for text in candidates):
        expected = ['private source annotation in public content: rows']
    elif any(boundary._LOCAL_PATH.search(text) or boundary._TEI.search(text)
             or boundary.re.search(r'(?i)\b[0-9a-f]{64}\b', text) for text in candidates):
        expected = ['private path, TEI, or digest in public content: rows']
    else:
        expected = []
    assert boundary._scan(value, 'rows') == expected
