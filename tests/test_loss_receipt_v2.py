from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest
from lxml import etree

from build.tei.check_ledger import check_receipt
from build.tei.project_hf import _record_divs, project_file
from ocd_kernel.lib.git_artifact import CanonicalGitArtifactError
from ocd_kernel.tei.normalization import normalize
from ocd_kernel.tei.projection_profile import (
    TARGET_FIELD_DEFINITIONS,
    classify_base,
    dropped_ancestor,
    rule_for,
)
from ocd_kernel.tei.writer import TEI_NS, derive_address

NS = {"tei": TEI_NS}
REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "ocd_kernel" / "schemas" / "v1" / "loss_receipt_v2.schema.json"
VECTORS_PATH = REPO_ROOT / "ocd_kernel" / "tei" / "normalization_vectors.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _junction(link: Path, target: Path) -> None:
    subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
    )


def _commit_projection_fixture(
    repo_root: Path,
    tei_path: Path,
    *,
    autocrlf: bool = False,
) -> None:
    relative_tei = tei_path.relative_to(repo_root).as_posix()
    (repo_root / ".gitattributes").write_text(
        f"{relative_tei} text eol=lf\n",
        encoding="utf-8",
        newline="\n",
    )
    for arguments in (
        ("init",),
        ("config", "user.email", "ticket01@example.invalid"),
        ("config", "user.name", "Ticket 01 Test"),
        ("config", "core.autocrlf", "true" if autocrlf else "false"),
        ("add", "."),
        ("commit", "-m", "fixture"),
    ):
        subprocess.run(
            ["git", *arguments],
            check=True,
            cwd=repo_root,
            capture_output=True,
        )


def _receipt_fixture(tmp_path: Path, *, unknown: bool = False) -> Path:
    mystery = '<mystery xml:id="m1">text</mystery>' if unknown else '<hi xml:id="h1">beta</hi>'
    paragraph = "Alpha " + mystery + "." if unknown else "Alpha " + mystery + "."
    tei_path = tmp_path / "ir" / "sample.demo.tei.xml"
    output_path = tmp_path / "out.jsonl"
    receipt_path = tmp_path / "receipt.loss.json"
    tei_path.parent.mkdir(parents=True)
    tei_path.write_text(
        f'''<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc><titleStmt><title>Sample Work</title></titleStmt></fileDesc></teiHeader>
  <text><body><div type="chapter" xml:id="chapter">
    <head>Chapter</head>
    <p xml:id="p1">{paragraph}</p>
    <note xml:id="n1">Secret</note>
  </div></body></text>
</TEI>
''',
        encoding="utf-8",
    )
    record_id = "sample/demo/chapter"
    text = "Alpha text." if unknown else "Alpha beta."
    output_path.write_text(
        json.dumps(
            {
                "id": record_id,
                "title_path": ["Sample Work", "Chapter"],
                "argument": None,
                "text": text,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    target_element = "m1" if unknown else "h1"
    target_text = "text" if unknown else "beta"
    child_target = {
        "record_id": record_id,
        "field": "text",
        "char_start": 6,
        "char_end": 10,
    }
    p_target = {
        "record_id": record_id,
        "field": "text",
        "char_start": 0,
        "char_end": len(text),
    }
    nodes = [
        {
            "address": "text[1]",
            "element": "text",
            "disposition": "structural",
            "reason_code": "structural.text",
        },
        {
            "address": "body[1]",
            "element": "body",
            "disposition": "structural",
            "reason_code": "structural.body",
        },
        {
            "address": "chapter",
            "element": "div",
            "disposition": "structural",
            "reason_code": "structural.div",
        },
        {
            "address": "chapter/head[1]",
            "element": "head",
            "disposition": "delivered",
            "canonical_text_sha256": _sha256_text("Chapter"),
            "canonical_text_length": 7,
            "targets": [
                {
                    "record_id": record_id,
                    "field": "title_path",
                    "item_index": 1,
                    "char_start": 0,
                    "char_end": 7,
                }
            ],
        },
        {
            "address": "p1",
            "element": "p",
            "disposition": "delivered",
            "canonical_text_sha256": _sha256_text(text),
            "canonical_text_length": len(text),
            "targets": [p_target],
        },
        {
            "address": target_element,
            "element": "mystery" if unknown else "hi",
            "disposition": "delivered" if unknown else "normalized",
            "canonical_text_sha256": _sha256_text(target_text),
            "canonical_text_length": len(target_text),
            **({} if unknown else {"reason_code": "normalize.inline.markup-removed"}),
            "targets": [child_target],
        },
        {
            "address": "n1",
            "element": "note",
            "disposition": "dropped",
            "canonical_text_sha256": _sha256_text("Secret"),
            "canonical_text_length": 6,
            "reason_code": "drop.element.note",
        },
    ]
    if unknown:
        nodes[-2]["element"] = "mystery"
    counts = {disposition: 0 for disposition in ("delivered", "normalized", "structural", "dropped", "empty")}
    classes: dict[str, dict[str, int]] = {}
    for node in nodes:
        disposition = node["disposition"]
        counts[disposition] += 1
        classes.setdefault(node["element"], {key: 0 for key in counts})[disposition] += 1
    receipt = {
        "receipt_schema": "loss-receipt-v2",
        "projection": {
            "id": "hf-clean-text-v2",
            "generator": "tests/test_loss_receipt_v2.py",
            "generated_at": "2026-07-16T00:00:00Z",
        },
        "ir": {"path": "ir/sample.demo.tei.xml", "sha256": _sha256(tei_path)},
        "output": {"path": "out.jsonl", "sha256": _sha256(output_path)},
        "totals": {"addressable_nodes": len(nodes), **counts},
        "classes": classes,
        "nodes": nodes,
    }
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt_path


def _projected_fixture(
    tmp_path: Path,
    body: str,
    *,
    stem: str,
) -> tuple[dict[str, object], Path, list[dict[str, object]]]:
    tei_path = tmp_path / "ir" / f"{stem}.demo.tei.xml"
    output_path = tmp_path / f"{stem}.jsonl"
    receipt_path = tmp_path / f"{stem}.loss.json"
    tei_path.parent.mkdir(parents=True)
    tei_path.write_text(
        f'''<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc><titleStmt><title>B03c Fixture</title></titleStmt></fileDesc></teiHeader>
  <text><body><div type="chapter" xml:id="chapter">{body}</div></body></text>
</TEI>''',
        encoding="utf-8",
    )
    receipt = project_file(
        tei_path,
        output_path,
        receipt_path=receipt_path,
        repo_root=tmp_path,
    )
    records = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return receipt, receipt_path, records


@pytest.mark.parametrize(
    ("autocrlf", "checkout_newline"),
    ((False, b"\n"), (True, b"\r\n")),
    ids=("lf-host", "crlf-host"),
)
def test_strict_checker_uses_committed_git_bytes_across_host_eol_configurations(
    tmp_path: Path,
    autocrlf: bool,
    checkout_newline: bytes,
) -> None:
    _, receipt_path, _ = _projected_fixture(
        tmp_path,
        '<p xml:id="p1">Alpha beta.</p>',
        stem="canonical-crlf",
    )
    tei_path = tmp_path / "ir" / "canonical-crlf.demo.tei.xml"
    _commit_projection_fixture(tmp_path, tei_path, autocrlf=autocrlf)
    canonical_bytes = subprocess.run(
        ["git", "show", "HEAD:ir/canonical-crlf.demo.tei.xml"],
        check=True,
        cwd=tmp_path,
        capture_output=True,
    ).stdout
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["ir"]["sha256"] = hashlib.sha256(canonical_bytes).hexdigest()
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    tei_path.write_bytes(canonical_bytes.replace(b"\n", checkout_newline))

    assert check_receipt(receipt_path, repo_root=tmp_path) == []


def test_strict_checker_reports_lexical_escape_without_traceback(tmp_path: Path) -> None:
    receipt_path = _receipt_fixture(tmp_path)
    receipt = json.loads(receipt_path.read_bytes())
    receipt["ir"]["path"] = "../escaped.tei.xml"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    errors = check_receipt(receipt_path, repo_root=tmp_path)

    assert len(errors) == 1
    assert "IR path is outside the repository" in errors[0]


def test_strict_checker_rejects_nested_directory_as_repository_root(
    tmp_path: Path,
) -> None:
    _, receipt_path, _ = _projected_fixture(
        tmp_path,
        '<p xml:id="p1">Alpha beta.</p>',
        stem="nested-repository-root",
    )
    tei_path = tmp_path / "ir" / "nested-repository-root.demo.tei.xml"
    _commit_projection_fixture(tmp_path, tei_path)

    errors = check_receipt(receipt_path, repo_root=tmp_path / "ir")

    assert len(errors) == 1
    assert "repository root" in errors[0]
    assert "top-level" in errors[0]


@pytest.mark.parametrize(
    ("autocrlf", "checkout_newline"),
    ((False, b"\n"), (True, b"\r\n")),
    ids=("lf-host", "crlf-host"),
)
def test_projector_binds_committed_git_bytes_across_host_eol_configurations(
    tmp_path: Path,
    autocrlf: bool,
    checkout_newline: bytes,
) -> None:
    _, receipt_path, _ = _projected_fixture(
        tmp_path,
        '<p xml:id="p1">Alpha beta.</p>',
        stem="projector-canonical-crlf",
    )
    tei_path = tmp_path / "ir" / "projector-canonical-crlf.demo.tei.xml"
    output_path = tmp_path / "projector-canonical-crlf.jsonl"
    _commit_projection_fixture(tmp_path, tei_path, autocrlf=autocrlf)
    canonical_bytes = subprocess.run(
        ["git", "show", "HEAD:ir/projector-canonical-crlf.demo.tei.xml"],
        check=True,
        cwd=tmp_path,
        capture_output=True,
    ).stdout
    tei_path.write_bytes(canonical_bytes.replace(b"\n", checkout_newline))

    receipt = project_file(
        tei_path,
        output_path,
        receipt_path=receipt_path,
        repo_root=tmp_path,
    )

    assert receipt["ir"]["sha256"] == hashlib.sha256(canonical_bytes).hexdigest()


def test_strict_checker_rejects_worktree_mutation_against_git(
    tmp_path: Path,
) -> None:
    _, receipt_path, _ = _projected_fixture(
        tmp_path,
        '<p xml:id="p1">Alpha beta.</p>',
        stem="canonical-mutation",
    )
    tei_path = tmp_path / "ir" / "canonical-mutation.demo.tei.xml"
    _commit_projection_fixture(tmp_path, tei_path)
    tei_path.write_bytes(tei_path.read_bytes().replace(b"beta", b"gamma"))

    errors = check_receipt(receipt_path, repo_root=tmp_path)

    assert any("canonical Git identity mismatch" in error for error in errors)


def test_projector_rejects_worktree_mutation_against_git(tmp_path: Path) -> None:
    _, receipt_path, _ = _projected_fixture(
        tmp_path,
        '<p xml:id="p1">Alpha beta.</p>',
        stem="projector-canonical-mutation",
    )
    tei_path = tmp_path / "ir" / "projector-canonical-mutation.demo.tei.xml"
    output_path = tmp_path / "projector-canonical-mutation.jsonl"
    _commit_projection_fixture(tmp_path, tei_path)
    original_output = output_path.read_bytes()
    original_receipt = receipt_path.read_bytes()
    tei_path.write_bytes(tei_path.read_bytes().replace(b"beta", b"gamma"))

    with pytest.raises(
        CanonicalGitArtifactError,
        match="canonical Git identity mismatch",
    ):
        project_file(
            tei_path,
            output_path,
            receipt_path=receipt_path,
            repo_root=tmp_path,
        )

    assert output_path.read_bytes() == original_output
    assert receipt_path.read_bytes() == original_receipt


def test_strict_checker_rejects_unauthorized_committed_receipt_mutation(
    tmp_path: Path,
) -> None:
    _, receipt_path, _ = _projected_fixture(
        tmp_path,
        '<p xml:id="p1">Alpha beta.</p>',
        stem="receipt-mutation",
    )
    tei_path = tmp_path / "ir" / "receipt-mutation.demo.tei.xml"
    _commit_projection_fixture(tmp_path, tei_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["projection"]["generated_at"] = "2099-01-01T00:00:00Z"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    errors = check_receipt(receipt_path, repo_root=tmp_path)

    assert any("unauthorized committed receipt change" in error for error in errors)


def test_strict_checker_rejects_dirty_receipt_formatting_without_rebind(
    tmp_path: Path,
) -> None:
    _, receipt_path, _ = _projected_fixture(
        tmp_path,
        '<p xml:id="p1">Alpha beta.</p>',
        stem="receipt-formatting",
    )
    tei_path = tmp_path / "ir" / "receipt-formatting.demo.tei.xml"
    _commit_projection_fixture(tmp_path, tei_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    canonical_ir = subprocess.run(
        ["git", "show", "HEAD:ir/receipt-formatting.demo.tei.xml"],
        check=True,
        cwd=tmp_path,
        capture_output=True,
    ).stdout
    receipt["ir"]["sha256"] = hashlib.sha256(canonical_ir).hexdigest()
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    subprocess.run(
        ["git", "add", receipt_path.name],
        check=True,
        cwd=tmp_path,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "bind canonical IR"],
        check=True,
        cwd=tmp_path,
        capture_output=True,
    )
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    errors = check_receipt(receipt_path, repo_root=tmp_path)

    assert any("unauthorized committed receipt change" in error for error in errors)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_strict_checker_rejects_resolved_junction_alias(
    tmp_path: Path,
) -> None:
    _, receipt_path, _ = _projected_fixture(
        tmp_path,
        '<p xml:id="p1">Alpha beta.</p>',
        stem="junction-alias",
    )
    tei_path = tmp_path / "ir" / "junction-alias.demo.tei.xml"
    canonical_bytes = tei_path.read_bytes().replace(b"\r\n", b"\n")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["ir"]["sha256"] = hashlib.sha256(canonical_bytes).hexdigest()
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    alias = tmp_path / "alias-ir"
    alias.mkdir()
    (alias / tei_path.name).write_bytes(canonical_bytes)
    _commit_projection_fixture(tmp_path, tei_path)
    tei_path.unlink()
    (tmp_path / "ir").rmdir()
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
        errors = check_receipt(receipt_path, repo_root=tmp_path)
        assert any("reparse" in error or "symlink" in error for error in errors)
    finally:
        os.rmdir(linked)


def test_v2_schema_uses_five_dispositions_and_exact_targets() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["receipt_schema"]["const"] == "loss-receipt-v2"
    assert schema["properties"]["totals"]["required"] == [
        "addressable_nodes",
        "delivered",
        "normalized",
        "structural",
        "dropped",
        "empty",
    ]
    assert schema["$defs"]["target"]["properties"]["field"]["enum"] == [
        "text",
        "argument",
        "title_path",
        "speeches",
    ]
    assert TARGET_FIELD_DEFINITIONS["title_path"].requires_item_index is True
    assert TARGET_FIELD_DEFINITIONS["speeches"].value_kind == "structured-array-item"
    assert TARGET_FIELD_DEFINITIONS["speeches"].requires_item_index is True


def test_every_committed_receipt_ir_is_explicitly_pinned_to_lf() -> None:
    receipt_paths = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"],
        check=True,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.splitlines()
    ir_paths = sorted(
        json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))["ir"]["path"]
        for path in receipt_paths
        if path.endswith(".loss.json")
    )

    actual = {
        path: subprocess.run(
            ["git", "check-attr", "eol", "--", path],
            check=True,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
        for path in ir_paths
    }

    assert len(ir_paths) == 15
    assert actual == {path: f"{path}: eol: lf" for path in ir_paths}


def test_normalization_vectors_are_shared_and_conformant() -> None:
    vectors = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
    assert any("\\u00a0" in json.dumps(vector) for vector in vectors)
    for vector in vectors:
        assert normalize(vector["input"], vector["mode"]) == vector["expected"]


def test_dropped_ancestor_rule_includes_note_pb_and_drop_div() -> None:
    root = etree.fromstring(
        b'''<text xmlns="http://www.tei-c.org/ns/1.0">
          <note><p xml:id="note-p">inside note</p></note>
          <pb><p xml:id="pb-p">inside pb</p></pb>
          <div type="title"><p xml:id="title-p">inside title</p></div>
        </text>'''
    )
    for xml_id in ("note-p", "pb-p", "title-p"):
        node = root.xpath(f".//*[@xml:id='{xml_id}']", namespaces={"xml": "http://www.w3.org/XML/1998/namespace"})[0]
        assert classify_base(node) == "dropped"
        assert dropped_ancestor(node) is not None


def test_strict_checker_accepts_an_independently_constructed_v2_receipt(tmp_path: Path) -> None:
    receipt_path = _receipt_fixture(tmp_path)
    assert check_receipt(receipt_path, repo_root=tmp_path) == []


@pytest.mark.skipif(os.name != "nt", reason="requires a Windows junction")
def test_projector_rejects_untracked_junction_alias_to_committed_ir(
    tmp_path: Path,
) -> None:
    _, _, _ = _projected_fixture(
        tmp_path,
        '<p xml:id="p1">Alpha beta.</p>',
        stem="junction-source",
    )
    tei_path = tmp_path / "ir" / "junction-source.demo.tei.xml"
    _commit_projection_fixture(tmp_path, tei_path)
    alias_root = tmp_path / "alias-ir"
    _junction(alias_root, tmp_path / "ir")
    try:
        alias = alias_root / tei_path.name
        assert alias.absolute() != tei_path.absolute()
        assert alias.resolve(strict=True) == tei_path.resolve(strict=True)

        with pytest.raises(CanonicalGitArtifactError, match="reparse|symlink"):
            project_file(
                alias,
                tmp_path / "junction-output.jsonl",
                receipt_path=tmp_path / "junction-output.loss.json",
                repo_root=tmp_path,
            )
    finally:
        os.rmdir(alias_root)


def test_strict_checker_rejects_missing_span_endpoint(tmp_path: Path) -> None:
    receipt_path = _receipt_fixture(tmp_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    for node in receipt["nodes"]:
        if node["address"] == "p1":
            del node["targets"][0]["char_end"]
            break
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    errors = check_receipt(receipt_path, repo_root=tmp_path)
    assert any("schema:" in error or "target set mismatch" in error for error in errors)


def test_strict_checker_rejects_unknown_text_bearing_element(tmp_path: Path) -> None:
    receipt_path = _receipt_fixture(tmp_path, unknown=True)
    errors = check_receipt(receipt_path, repo_root=tmp_path)
    assert any("unknown TEI element fails closed" in error for error in errors)


@pytest.mark.parametrize(
    ("xpath", "expected"),
    [
        ("/tei:TEI/tei:text", "structural"),
        ("/tei:TEI/tei:text/tei:body", "structural"),
        ("/tei:TEI/tei:text/tei:front", "structural"),
        ("/tei:TEI/tei:text/tei:back", "structural"),
        ("/tei:TEI/tei:text/tei:body/tei:div", "structural"),
    ],
)
def test_structural_registry_is_identity_based(xpath: str, expected: str) -> None:
    root = etree.fromstring(
        b'''<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><front/><body><div/></body><back/></text></TEI>'''
    )
    assert classify_base(root.xpath(xpath, namespaces=NS)[0]) == expected


def test_general_profile_table_covers_stage1_roles() -> None:
    root = etree.fromstring(
        b'''<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div>
          <label>Rubric</label><speaker>Minister.</speaker><p>Paragraph <hi>styled</hi> <ref>link</ref></p>
          <argument><p>Argument</p></argument><head>Title\xc2\xa0Here</head>
          <quote><lg><l>Line one</l><l>Line two</l></lg></quote>
          <trailer><date>June</date></trailer><label xml:id="empty"/>
          <note><emph>Drop me</emph></note><div type="title"><p>Drop me too</p></div>
          <mystery>Unknown text</mystery>
        </div></body></text></TEI>'''
    )
    def first_live(local: str) -> etree._Element:
        return root.xpath(
            f".//tei:{local}[not(ancestor::tei:note) and not(ancestor::tei:div[@type='title'])]",
            namespaces=NS,
        )[0]

    for local in ("label", "speaker", "p", "head", "argument", "quote", "lg", "l", "trailer", "date"):
        assert classify_base(first_live(local)) == "delivered"
    for local in ("ref", "hi"):
        assert classify_base(first_live(local)) == "normalized"
    assert classify_base(root.xpath(".//tei:note", namespaces=NS)[0]) == "dropped"
    assert classify_base(root.xpath(".//tei:mystery", namespaces=NS)[0]) is None
    assert classify_base(root.xpath(".//*[@xml:id='empty']", namespaces={"xml": "http://www.w3.org/XML/1998/namespace"})[0]) == "delivered"


def test_seeded_bcp_label_regression_is_pending_b03b(tmp_path: Path) -> None:
    from build.tei.project_hf import project_file

    tei_path = tmp_path / "ir" / "bcp.demo.tei.xml"
    output_path = tmp_path / "out.jsonl"
    tei_path.parent.mkdir(parents=True)
    tei_path.write_text(
        '''<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div type="service">
          <label xml:id="minister-label">Minister.</label><p>The Lord be with you.</p>
        </div></body></text></TEI>''',
        encoding="utf-8",
    )
    receipt = project_file(tei_path, output_path, repo_root=tmp_path)
    assert receipt["receipt_schema"] == "loss-receipt-v2"
    assert any(node["address"] == "minister-label" and node["disposition"] == "delivered" for node in receipt["nodes"])


def test_mixed_content_parent_div_regression_is_pending_b03b() -> None:
    root = etree.fromstring(
        b'''<text xmlns="http://www.tei-c.org/ns/1.0"><div xml:id="parent"><p>Parent text</p>
          <div xml:id="child"><p>Child text</p></div></div></text>'''
    )
    assert any(derive_address(div) == "parent" for div in _record_divs(root))


@pytest.mark.parametrize(
    "local",
    ["list", "item", "table", "row", "cell", "lb"],
)
def test_b03c_container_and_lb_elements_are_structural(local: str) -> None:
    rule = rule_for(local)
    assert rule is not None, f"<{local}> is used by the projector but not declared in the profile"
    assert rule.role == "structural"
    assert rule.reason_code == f"structural.{local}"

    root = etree.fromstring(
        f'''<text xmlns="http://www.tei-c.org/ns/1.0"><body><div>
          <{local}/>
        </div></body></text>'''.encode("utf-8")
    )
    node = root.xpath(f".//tei:{local}", namespaces=NS)[0]
    assert classify_base(node) == "structural"


@pytest.mark.parametrize("local", ["q", "bibl", "name"])
def test_b03c_inline_text_carriers_stay_normalized(local: str) -> None:
    rule = rule_for(local)
    assert rule is not None, f"<{local}> is used by the projector but not declared in the profile"
    assert rule.role == "normalized"
    assert rule.reason_code == "normalize.inline.markup-removed"

    root = etree.fromstring(
        f'''<text xmlns="http://www.tei-c.org/ns/1.0"><body><div>
          <p>Before <{local}>carried</{local}> after.</p>
        </div></body></text>'''.encode("utf-8")
    )
    node = root.xpath(f".//tei:{local}", namespaces=NS)[0]
    assert classify_base(node) == "normalized"


def test_loss_receipt_v2_schema_admits_b03c_structural_reasons() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    reason_codes = set(schema["$defs"]["node"]["properties"]["reason_code"]["enum"])
    expected = {
        "structural.list",
        "structural.item",
        "structural.table",
        "structural.row",
        "structural.cell",
        "structural.lb",
    }
    assert expected <= reason_codes


def test_b03c_table_cells_are_independent_blocks_and_pass_strict_checker(
    tmp_path: Path,
) -> None:
    receipt, receipt_path, records = _projected_fixture(
        tmp_path,
        """<table xml:id="table-1">
          <row xml:id="row-1"><cell xml:id="cell-1"><p>Alpha cell.</p></cell></row>
          <row xml:id="row-2"><cell xml:id="cell-2"><p>Beta cell.</p></cell></row>
        </table>""",
        stem="b03c-table",
    )

    assert check_receipt(receipt_path, repo_root=tmp_path) == []
    assert len(records) == 1
    assert records[0]["text"] == "Alpha cell.\n\nBeta cell."
    for local, expected_count in {"table": 1, "row": 2, "cell": 2}.items():
        nodes = [node for node in receipt["nodes"] if node["element"] == local]
        assert len(nodes) == expected_count
        assert all(node["disposition"] == "structural" for node in nodes)


def test_b03c_list_items_are_independent_blocks_and_pass_strict_checker(
    tmp_path: Path,
) -> None:
    receipt, receipt_path, records = _projected_fixture(
        tmp_path,
        """<list xml:id="list-1">
          <item xml:id="item-1"><p>First item.</p></item>
          <item xml:id="item-2"><p>Second item.</p></item>
        </list>""",
        stem="b03c-list",
    )

    assert check_receipt(receipt_path, repo_root=tmp_path) == []
    assert len(records) == 1
    assert records[0]["text"] == "First item.\n\nSecond item."
    for local, expected_count in {"list": 1, "item": 2}.items():
        nodes = [node for node in receipt["nodes"] if node["element"] == local]
        assert len(nodes) == expected_count
        assert all(node["disposition"] == "structural" for node in nodes)


def test_b03c_lb_projects_as_newline_and_passes_strict_checker(tmp_path: Path) -> None:
    receipt, receipt_path, records = _projected_fixture(
        tmp_path,
        '<p xml:id="verse">You,<lb xml:id="line-break"/>What</p>',
        stem="b03c-lb",
    )

    assert check_receipt(receipt_path, repo_root=tmp_path) == []
    assert len(records) == 1
    assert records[0]["text"] == "You,\nWhat"
    assert "You,What" not in records[0]["text"]
    lb = next(node for node in receipt["nodes"] if node["element"] == "lb")
    assert lb["disposition"] == "structural"
    assert lb["reason_code"] == "structural.lb"


def test_b03c_structural_cell_direct_text_fails_closed(tmp_path: Path) -> None:
    _, receipt_path, _ = _projected_fixture(
        tmp_path,
        '<table><row><cell xml:id="bare-cell">bare text</cell></row></table>',
        stem="b03c-bare-cell",
    )

    errors = check_receipt(receipt_path, repo_root=tmp_path)
    assert any("structural element has unmapped direct text" in error for error in errors)


def test_b03c_sp_direct_text_fails_closed(tmp_path: Path) -> None:
    _, receipt_path, _ = _projected_fixture(
        tmp_path,
        '<sp xml:id="speech">stray<speaker>A</speaker><p>B</p></sp>',
        stem="b03c-sp-direct-text",
    )

    errors = check_receipt(receipt_path, repo_root=tmp_path)
    assert errors, "strict checker silently accepted direct text on <sp>"


def test_head_only_div_does_not_mint_a_record_when_it_governs_one() -> None:
    """A head rides its descendant record's title_path; it must not add a record.

    Minting a record per head-bearing div would put a contentless row against
    every structural book/part div in the corpus.
    """

    root = etree.fromstring(
        b'''<text xmlns="http://www.tei-c.org/ns/1.0"><div xml:id="book"><head>Book I</head>
          <div xml:id="chapter"><p>Chapter text</p></div></div></text>'''
    )
    addresses = [derive_address(div) for div in _record_divs(root)]
    assert addresses == ["chapter"]


def test_head_only_div_gets_a_record_when_it_governs_none() -> None:
    """A standalone divider's heading has no descendant record to carry it.

    Real case: Standard Ebooks' City of God <div type="part"><head>Part I</head>.
    Without its own record the heading text has no delivery path at all, so it
    would be silently lost -- which is the defect this campaign exists to remove.
    """

    root = etree.fromstring(
        b'''<text xmlns="http://www.tei-c.org/ns/1.0"><div type="part" xml:id="part-1">
          <head>Part I</head></div></text>'''
    )
    assert [derive_address(div) for div in _record_divs(root)] == ["part-1"]


@pytest.mark.slow
@pytest.mark.requires_local_artifacts
def test_every_committed_receipt_is_v2_and_passes_the_strict_checker() -> None:
    """The gate: pin all 15 committed receipts to strict v2.

    Without this, a regressed projector or a hand-edited receipt reverts the
    corpus to an unverified state with nothing to catch it -- the exact way the
    v1 ledger returned PASS for months while text was missing.
    """

    receipts = sorted((REPO_ROOT / "ir").rglob("*.loss.json"))
    assert receipts, "no committed receipts found under ir/"
    failures: dict[str, list[str]] = {}
    for receipt_path in receipts:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        relative = receipt_path.relative_to(REPO_ROOT).as_posix()
        assert receipt["receipt_schema"] == "loss-receipt-v2", f"{relative} is not v2"
        errors = check_receipt(receipt_path, repo_root=REPO_ROOT)
        if errors:
            failures[relative] = errors[:5]
    assert not failures, f"strict v2 rejected committed receipts: {failures}"
