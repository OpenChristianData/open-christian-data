"""Contract tests for the bounded 37c-087 / LIB-024 BSB route."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/bsb.source-manifest.json"
TEI_NS = "http://www.tei-c.org/ns/1.0"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _load_oracle():
    path = ROOT / "build/tei/bsb_oracle.py"
    spec = importlib.util.spec_from_file_location("_bsb_contract_test_oracle", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_candidate(destination: Path) -> dict[str, object]:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "build/tools/reconstruct_candidate.py"),
            "--manifest",
            MANIFEST.relative_to(ROOT).as_posix(),
            "--destination",
            str(destination),
            "--repository-root",
            str(ROOT),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="session")
def candidate_runs(tmp_path_factory: pytest.TempPathFactory):
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    root = tmp_path_factory.mktemp("bsb-candidates")
    first = root / "first"
    second = root / "second"
    first_summary = _run_candidate(first)
    second_summary = _run_candidate(second)
    return manifest, first, second, first_summary, second_summary


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _reseal(candidate: Path) -> None:
    manifest_path = candidate / "manifest.json"
    record = json.loads(manifest_path.read_text(encoding="utf-8"))
    for member in record["members"]:
        content = (candidate / member["name"]).read_bytes()
        member["bytes"] = len(content)
        member["sha256"] = _sha(content)
    manifest_path.write_bytes(
        (
            json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            + "\n"
        ).encode("utf-8")
    )


def _mutate(candidate: Path, kind: str) -> None:
    tei_path = candidate / "content.tei.xml"
    if kind in {"omit-book", "reorder-books", "alter-text"}:
        root = etree.fromstring(tei_path.read_bytes())
        body = root.find(f"{{{TEI_NS}}}text/{{{TEI_NS}}}body")
        assert body is not None
        if kind == "omit-book":
            body.remove(body[-1])
        elif kind == "reorder-books":
            first, second = body[0], body[1]
            body.remove(first)
            body.remove(second)
            body.insert(0, second)
            body.insert(1, first)
        else:
            verse = root.xpath(
                "//*[local-name()='ab' and @type='verse' and string-length(text()) > 0]"
            )[0]
            assert verse.text is not None
            verse.text += " [MUTATION]"
        tei_path.write_bytes(
            etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
        )
    else:
        account_path = candidate / "source-accountability.json"
        account = json.loads(account_path.read_text(encoding="utf-8"))
        account["crosswalk"].pop()
        account_path.write_bytes(
            (
                json.dumps(account, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                + "\n"
            ).encode("utf-8")
        )
    _reseal(candidate)


def test_manifest_binds_current_bsb_source() -> None:
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    source = manifest.authority_path("retained-bsb-json")
    assert source.stat().st_size == 8304051
    assert _sha(source.read_bytes()) == (
        "73ca9ea1e36041bbbbd077738b250e266192669819117326516f871804872dac"
    )
    assert manifest.record["ticket_id"] == "37c-087"
    assert manifest.record["work_id"] == "bsb"
    assert manifest.record["scope"]["assigned_work"] == "bsb"
    assert manifest.record["scope"]["excluded_source_members"] == ()


def test_candidate_is_nonaccepted_accounted_and_schema_validated(candidate_runs) -> None:
    manifest, first, _, first_summary, _ = candidate_runs
    assert first_summary["status"] == "pass"
    assert first_summary["acceptance_status"] == "nonaccepted"
    package = CandidatePackage.load(first / "package")
    assert package.manifest["source_manifest"]["sha256"] == manifest.sha256
    account = json.loads((package.path / "source-accountability.json").read_text(encoding="utf-8"))
    assert account["observation_counts"] == {
        "books": 66,
        "chapters": 1189,
        "duplicate": 0,
        "invented": 0,
        "omitted": 0,
        "represented": 32359,
        "top_level_fields": 2,
        "verses": 31102,
    }
    root = etree.fromstring((package.path / "content.tei.xml").read_bytes())
    assert len(root.xpath("/t:TEI/t:text/t:body/t:div", namespaces={"t": TEI_NS})) == 66
    assert len(root.xpath("//t:div[@type='chapter']", namespaces={"t": TEI_NS})) == 1189
    verses = root.xpath("//t:ab[@type='verse']", namespaces={"t": TEI_NS})
    assert len(verses) == 31102
    assert sum((verse.text or "") == "" for verse in verses) == 16


def test_two_fresh_process_runs_are_byte_identical(candidate_runs) -> None:
    _, first, second, first_summary, second_summary = candidate_runs
    assert first_summary["candidate"]["sha256"] == second_summary["candidate"]["sha256"]
    assert _tree_bytes(first) == _tree_bytes(second)


@pytest.mark.parametrize("kind", ["omit-book", "reorder-books", "alter-text", "alter-accountability"])
def test_independent_oracle_rejects_meaningful_mutations(candidate_runs, tmp_path: Path, kind: str) -> None:
    manifest, first, _, _, _ = candidate_runs
    mutated = tmp_path / kind
    shutil.copytree(first / "package", mutated)
    _mutate(mutated, kind)
    package = CandidatePackage.load(mutated)
    with pytest.raises(ValueError):
        validate(manifest, package, _load_oracle()._oracle)


def test_oracle_does_not_import_bsb_producer() -> None:
    source = (ROOT / "build/tei/bsb_oracle.py").read_text(encoding="utf-8")
    assert "bsb_reconstruction" not in source
    assert "build.parsers.bsb_bible_text" not in source
