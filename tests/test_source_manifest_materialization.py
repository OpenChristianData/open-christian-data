from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from build.tools.check_source_manifest_materialization import (
    CANONICAL_LF_MODE,
    MANAGED_BLOCK_END,
    MANAGED_BLOCK_START,
    audit_source_manifests,
    main,
    render_gitattributes,
)


def _identity(content: bytes) -> dict[str, object]:
    return {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _manifest(
    root: Path,
    name: str,
    authorities: list[dict[str, object]],
    *,
    implementation_suffix: str = "",
) -> Path:
    converter_path = f"build/tei/converter{implementation_suffix}.py"
    validator_path = f"build/tei/validator{implementation_suffix}.py"
    schema_path = f"schemas/package{implementation_suffix}.json"
    converter = b"def _convert():\n    return None\n"
    validator = b"def _oracle():\n    return None\n"
    schema = b"{}\n"
    for relative, content in (
        (converter_path, converter),
        (validator_path, validator),
        (schema_path, schema),
    ):
        _write(root / relative, content)
    payload = {
        "contract": "ocd-source-manifest-v1",
        "source_id": name,
        "work_id": name,
        "authorities": authorities,
        "converter": {
            "id": f"converter-{name}",
            "version": "1",
            "callable": "_convert",
            "implementation_path": converter_path,
            "implementation_sha256": hashlib.sha256(converter).hexdigest(),
        },
        "validator": {
            "id": f"validator-{name}",
            "version": "1",
            "callable": "_oracle",
            "implementation_path": validator_path,
            "implementation_sha256": hashlib.sha256(validator).hexdigest(),
            "import_closure_sha256": "0" * 64,
        },
        "package_schema": {
            "path": schema_path,
            "sha256": hashlib.sha256(schema).hexdigest(),
        },
    }
    path = root / "sources" / name / f"{name}.source-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
    return path


def _authority(path: str, declared: bytes, **extra: object) -> dict[str, object]:
    return {
        "name": path.replace("/", "-"),
        "path": path,
        "role": "fixture",
        **_identity(declared),
        **extra,
    }


def _entry(report: dict[str, object], path: str) -> dict[str, object]:
    entries = report["entries"]
    assert isinstance(entries, list)
    return next(entry for entry in entries if entry["path"] == path)


def test_legacy_lf_and_crlf_equivalence_are_explicitly_transitional(tmp_path: Path) -> None:
    lf = b"alpha\nbeta\n"
    crlf = b"alpha\r\nbeta\r\n"
    _write(tmp_path / "evidence/current-crlf.txt", crlf)
    _write(tmp_path / "evidence/current-lf.txt", lf)
    _write(tmp_path / "evidence/exact-lf.txt", lf)
    _manifest(
        tmp_path,
        "line-endings",
        [
            _authority("evidence/current-crlf.txt", lf),
            _authority("evidence/current-lf.txt", crlf),
            _authority("evidence/exact-lf.txt", lf),
        ],
    )

    report = audit_source_manifests(tmp_path)

    assert report["ok"] is True
    assert (
        _entry(report, "evidence/current-crlf.txt")["classification"]
        == "canonical LF-equivalent"
    )
    assert _entry(report, "evidence/current-lf.txt")["classification"] == "CRLF-equivalent"
    assert _entry(report, "evidence/exact-lf.txt")["classification"] == "exact"
    assert report["transitional_legacy_inference"]["active"] is True
    assert "reporting only" in report["transitional_legacy_inference"]["note"]


@pytest.mark.parametrize(
    "content",
    [b"alpha\r\nbeta\n", b"alpha\rbeta\r"],
    ids=["mixed-eol", "lone-cr"],
)
def test_legacy_exact_mixed_eol_bytes_use_verbatim_attributes(
    tmp_path: Path,
    content: bytes,
) -> None:
    path = "evidence/exact-mixed-eol.txt"
    _write(tmp_path / path, content)
    _manifest(tmp_path, "exact-mixed-eol", [_authority(path, content)])

    report = audit_source_manifests(tmp_path)

    entry = _entry(report, path)
    assert report["ok"] is True
    assert entry["classification"] == "exact"
    assert entry["attribute"] == "-text"
    attributes = render_gitattributes(report)
    assert f"{path} -text !eol" in attributes
    assert "eol=mixed" not in attributes
    assert "eol=lone-cr" not in attributes


@pytest.mark.parametrize(
    "actual",
    [
        b"\xef\xbb\xbfalpha\nbeta\n",
        b"alpha\r\nbeta\n",
        b"alpha\rbeta\r",
        b"alpha\nbeta",
    ],
    ids=["bom", "mixed", "lone-cr", "final-newline"],
)
def test_unsafe_text_variants_are_stale_not_equivalent(tmp_path: Path, actual: bytes) -> None:
    declared = b"alpha\nbeta\n"
    _write(tmp_path / "evidence/unsafe.txt", actual)
    _manifest(tmp_path, "unsafe", [_authority("evidence/unsafe.txt", declared)])

    report = audit_source_manifests(tmp_path)

    assert report["ok"] is False
    assert _entry(report, "evidence/unsafe.txt")["classification"] == "stale"
    assert any(error["code"] == "stale" for error in report["errors"])


def test_conflicting_identities_for_one_path_fail_closed(tmp_path: Path) -> None:
    _write(tmp_path / "evidence/shared.txt", b"one\n")
    _manifest(
        tmp_path,
        "first",
        [_authority("evidence/shared.txt", b"one\n")],
        implementation_suffix="-first",
    )
    _manifest(
        tmp_path,
        "second",
        [_authority("evidence/shared.txt", b"two\n")],
        implementation_suffix="-second",
    )

    report = audit_source_manifests(tmp_path)

    assert report["ok"] is False
    assert _entry(report, "evidence/shared.txt")["classification"] == "conflict"
    assert any(error["code"] == "conflict" for error in report["errors"])


def test_missing_and_containment_fail_closed(tmp_path: Path) -> None:
    _manifest(
        tmp_path,
        "broken-paths",
        [
            _authority("evidence/missing.txt", b"missing\n"),
            _authority("../escape.txt", b"escape\n"),
        ],
    )

    report = audit_source_manifests(tmp_path)

    assert report["ok"] is False
    assert _entry(report, "evidence/missing.txt")["classification"] == "missing"
    assert {error["code"] for error in report["errors"]} >= {"containment", "missing"}


def test_raw_binding_is_exact_hash_audited_but_not_projected(tmp_path: Path) -> None:
    retained = b"retained\r\nsource\r\n"
    _write(tmp_path / "raw/source.txt", retained)
    _manifest(tmp_path, "raw-source", [_authority("raw/source.txt", retained)])

    report = audit_source_manifests(tmp_path)
    raw_entry = _entry(report, "raw/source.txt")

    assert report["ok"] is True
    assert raw_entry["classification"] == "exact"
    assert raw_entry["exact_match"] is True
    assert raw_entry["actual"] == _identity(retained)
    assert raw_entry["attribute_projected"] is False
    assert "raw/source.txt" not in render_gitattributes(report)


def test_attribute_projection_is_managed_sorted_and_read_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lf = b"lf\n"
    crlf = b"crlf\r\n"
    binary = b"\x00\x01\x02"
    for relative, content in (
        ("z/lf.txt", lf),
        ("a/crlf.txt", crlf),
        ("m/binary.bin", binary),
        ("raw/retained.bin", binary),
    ):
        _write(tmp_path / relative, content)
    _manifest(
        tmp_path,
        "attributes",
        [
            _authority("z/lf.txt", lf),
            _authority("a/crlf.txt", crlf),
            _authority("m/binary.bin", binary),
            _authority("raw/retained.bin", binary),
        ],
    )
    attributes_path = tmp_path / ".gitattributes"
    attributes_path.write_text("existing text eol=lf\n", encoding="utf-8", newline="\n")

    result = main(["--repository-root", str(tmp_path), "--print-gitattributes"])
    output = capsys.readouterr().out

    assert result == 0
    assert attributes_path.read_text(encoding="utf-8") == "existing text eol=lf\n"
    assert output.startswith(MANAGED_BLOCK_START)
    assert output.endswith(MANAGED_BLOCK_END + "\n")
    rows = [line for line in output.splitlines() if line and not line.startswith("#")]
    assert rows == sorted(rows, key=str.casefold)
    assert "a/crlf.txt text eol=crlf" in rows
    assert "m/binary.bin -text !eol" in rows
    assert "z/lf.txt text eol=lf" in rows
    assert all(not row.startswith("raw/") for row in rows)


def test_explicit_exact_bytes_mode_disables_line_ending_equivalence(tmp_path: Path) -> None:
    declared = b"alpha\nbeta\n"
    _write(tmp_path / "evidence/exact.txt", b"alpha\r\nbeta\r\n")
    _manifest(
        tmp_path,
        "explicit",
        [_authority("evidence/exact.txt", declared, byte_mode="exact-bytes-v1")],
    )

    report = audit_source_manifests(tmp_path)

    assert report["ok"] is False
    assert _entry(report, "evidence/exact.txt")["classification"] == "stale"


def test_v2_manifest_is_rejected_until_v2_contract_is_supported(tmp_path: Path) -> None:
    _write(tmp_path / "evidence/source.txt", b"source\n")
    manifest = _manifest(
        tmp_path,
        "v2",
        [_authority("evidence/source.txt", b"source\n")],
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["contract"] = "ocd-source-manifest-v2"
    manifest.write_text(json.dumps(payload), encoding="utf-8", newline="\n")

    report = audit_source_manifests(tmp_path)

    assert report["ok"] is False
    assert any(
        error["code"] == "invalid-manifest"
        and "only ocd-source-manifest-v1 is supported" in error["message"]
        for error in report["errors"]
    )


@pytest.mark.parametrize(
    "actual",
    [b"\x00\x01", b"\xffalpha"],
    ids=["binary", "invalid-utf8"],
)
def test_canonical_text_mode_rejects_binary_and_invalid_utf8(
    tmp_path: Path, actual: bytes
) -> None:
    _write(tmp_path / "evidence/unsafe.bin", actual)
    _manifest(
        tmp_path,
        "canonical-text",
        [
            _authority(
                "evidence/unsafe.bin",
                actual,
                byte_mode=CANONICAL_LF_MODE,
            )
        ],
    )

    report = audit_source_manifests(tmp_path)

    assert report["ok"] is False
    assert _entry(report, "evidence/unsafe.bin")["classification"] == "stale"
    assert any(
        error["code"] == "stale" and error["path"] == "evidence/unsafe.bin"
        for error in report["errors"]
    )


def test_non_scalar_byte_mode_is_a_structured_invalid_binding(tmp_path: Path) -> None:
    actual = b"source\n"
    _write(tmp_path / "evidence/malformed.txt", actual)
    _manifest(
        tmp_path,
        "malformed-mode",
        [_authority("evidence/malformed.txt", actual, byte_mode=[])],
    )

    report = audit_source_manifests(tmp_path)

    assert report["ok"] is False
    assert any(
        error["code"] == "invalid-binding"
        and error["binding"] == "authority:evidence-malformed.txt"
        for error in report["errors"]
    )


@pytest.mark.parametrize("filename", ["source-manifest.json", "named.source-manifest.json"])
def test_discovers_both_manifest_filename_conventions(tmp_path: Path, filename: str) -> None:
    content = b"source witness\n"
    _write(tmp_path / "evidence/witness.txt", content)
    manifest = _manifest(tmp_path, "discovery", [_authority("evidence/witness.txt", content)])
    manifest.rename(manifest.with_name(filename))

    report = audit_source_manifests(tmp_path)

    assert report["ok"] is True
    assert _entry(report, "evidence/witness.txt")["classification"] == "exact"
