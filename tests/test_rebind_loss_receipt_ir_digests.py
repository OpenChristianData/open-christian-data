from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from build.tei.rebind_loss_receipt_ir_digests import (
    ReceiptRebindError,
    plan_receipt_rebinds,
    write_receipt_rebinds,
)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, bytes]:
    tei_path = tmp_path / "ir" / "demo.tei.xml"
    output_path = tmp_path / "ir" / "hf" / "demo.jsonl"
    receipt_path = output_path.with_suffix(".jsonl.loss.json")
    tei_path.parent.mkdir()
    output_path.parent.mkdir()
    canonical_tei = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<TEI xmlns="http://www.tei-c.org/ns/1.0">\n'
        b"  <text><body><p>Alpha beta.</p></body></text>\n"
        b"</TEI>\n"
    )
    output_bytes = b'{"id":"demo","text":"Alpha beta."}\n'
    tei_path.write_bytes(canonical_tei)
    output_path.write_bytes(output_bytes)
    receipt = {
        "receipt_schema": "loss-receipt-v2",
        "ir": {"path": "ir/demo.tei.xml", "sha256": "placeholder"},
        "output": {"path": "ir/hf/demo.jsonl", "sha256": _sha256(output_bytes)},
        "unchanged": {"nested": [1, 2, 3]},
    }
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (tmp_path / ".gitattributes").write_text(
        "ir/demo.tei.xml text eol=lf\n",
        encoding="utf-8",
        newline="\n",
    )
    for arguments in (
        ("init",),
        ("config", "user.email", "ticket01@example.invalid"),
        ("config", "user.name", "Ticket 01 Test"),
        ("add", "."),
        ("commit", "-m", "fixture"),
    ):
        subprocess.run(
            ["git", *arguments],
            check=True,
            cwd=tmp_path,
            capture_output=True,
        )
    checkout_tei = canonical_tei.replace(b"\n", b"\r\n")
    tei_path.write_bytes(checkout_tei)
    receipt["ir"]["sha256"] = _sha256(checkout_tei)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    subprocess.run(
        ["git", "add", receipt_path.relative_to(tmp_path).as_posix()],
        check=True,
        cwd=tmp_path,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "bind checkout bytes"],
        check=True,
        cwd=tmp_path,
        capture_output=True,
    )
    return receipt_path, tei_path, output_path, canonical_tei


def test_governed_rebind_changes_only_ir_sha_after_semantics_proof(
    tmp_path: Path,
) -> None:
    receipt_path, tei_path, output_path, canonical_tei = _fixture(tmp_path)
    before = json.loads(receipt_path.read_text(encoding="utf-8"))

    plans = plan_receipt_rebinds(
        tmp_path,
        receipt_paths=(receipt_path,),
        expected_count=1,
    )

    assert len(plans) == 1
    assert plans[0].pure_eol_normalization is True
    assert plans[0].xml_c14n_equal is True
    assert plans[0].output_json_semantics_equal is True
    assert plans[0].canonical_ir_sha256 == _sha256(canonical_tei)
    assert plans[0].checkout_ir_sha256 == before["ir"]["sha256"]
    tei_before = tei_path.read_bytes()
    output_before = output_path.read_bytes()

    write_receipt_rebinds(plans)

    after = json.loads(receipt_path.read_text(encoding="utf-8"))
    expected = json.loads(json.dumps(before))
    expected["ir"]["sha256"] = _sha256(canonical_tei)
    assert after == expected
    assert tei_path.read_bytes() == tei_before
    assert output_path.read_bytes() == output_before

    repeated_plans = plan_receipt_rebinds(
        tmp_path,
        receipt_paths=(receipt_path,),
        expected_count=1,
    )
    rebound_bytes = receipt_path.read_bytes()
    write_receipt_rebinds(repeated_plans)
    assert receipt_path.read_bytes() == rebound_bytes


def test_governed_rebind_rejects_real_ir_mutation(tmp_path: Path) -> None:
    receipt_path, tei_path, _, _ = _fixture(tmp_path)
    tei_path.write_bytes(tei_path.read_bytes().replace(b"beta", b"gamma"))

    with pytest.raises(ReceiptRebindError, match="canonical Git identity mismatch"):
        plan_receipt_rebinds(
            tmp_path,
            receipt_paths=(receipt_path,),
            expected_count=1,
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_governed_rebind_rejects_resolved_junction_alias(tmp_path: Path) -> None:
    receipt_path, tei_path, output_path, canonical_tei = _fixture(tmp_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["ir"]["sha256"] = _sha256(canonical_tei)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    alias = tmp_path / "alias-ir"
    (alias / "hf").mkdir(parents=True)
    (alias / tei_path.name).write_bytes(canonical_tei)
    (alias / "hf" / output_path.name).write_bytes(output_path.read_bytes())
    alias_receipt = alias / "hf" / receipt_path.name
    alias_receipt.write_bytes(receipt_path.read_bytes())
    subprocess.run(
        ["git", "add", "."],
        check=True,
        cwd=tmp_path,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add tracked alias"],
        check=True,
        cwd=tmp_path,
        capture_output=True,
    )
    shutil.rmtree(tmp_path / "ir")
    linked = tmp_path / "ir"
    try:
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(linked), str(alias)],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as error:
        pytest.skip(f"junction creation unavailable: {error}")
    try:
        with pytest.raises(ReceiptRebindError, match="reparse|symlink"):
            plan_receipt_rebinds(
                tmp_path,
                receipt_paths=(linked / "hf" / receipt_path.name,),
                expected_count=1,
            )
    finally:
        os.rmdir(linked)
