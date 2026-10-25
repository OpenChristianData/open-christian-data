"""Focused source-identity gates for direct TCP sidecar accounting."""
from pathlib import Path

import pytest

from build.tools import prepare_direct_tcp_four_sidecars as tcp
from ocd_kernel.library._common import PipelineError


GOOD_XML = """<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc>
<titleStmt><title>Complete retained title</title><author>Test Author</author></titleStmt>
<publicationStmt><idno type="DLPS">A48888</idno></publicationStmt>
</fileDesc><encodingDesc><editorialDecl><p>We respectfully request that due credit and attribution is given to their original source.</p>
</editorialDecl></encodingDesc></teiHeader><text><body><p>Text.</p></body></text></TEI>"""


def test_tcp_header_binds_complete_title_and_source_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.xml"
    source.write_text(GOOD_XML, encoding="utf-8")
    monkeypatch.setattr(tcp, "resolve_repo_path", lambda _root, _relative: source)
    assert tcp._source_identity(tmp_path, {"path": "source.xml"}, "A48888") == {
        "source_title": "Complete retained title", "source_author": "Test Author", "tcp_id": "A48888"
    }


@pytest.mark.parametrize("mutated", [
    GOOD_XML.replace("A48888", "A48889"),
    GOOD_XML.replace("<author>Test Author</author>", ""),
    GOOD_XML.replace("due credit and attribution", "editorial credit"),
    GOOD_XML.replace("<text>", "<back>").replace("</text>", "</back>"),
])
def test_tcp_header_rejects_identity_scope_or_credit_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutated: str
) -> None:
    source = tmp_path / "source.xml"
    source.write_text(mutated, encoding="utf-8")
    monkeypatch.setattr(tcp, "resolve_repo_path", lambda _root, _relative: source)
    with pytest.raises(PipelineError, match="identity or credit request differs"):
        tcp._source_identity(tmp_path, {"path": "source.xml"}, "A48888")


def _generation(tmp_path: Path):
    from ocd_kernel.library._common import sha256_file

    root = tmp_path / "root"
    stage = tmp_path / "stage"
    target = root / "library" / "works" / "test-work"
    target.mkdir(parents=True)
    (target / "work.json").write_text("before", encoding="utf-8")
    staged_file = stage / "library" / "works" / "test-work" / "work.json"
    staged_file.parent.mkdir(parents=True)
    staged_file.write_text("after", encoding="utf-8")
    item = {"path": "library/works/test-work/work.json",
            "before_sha256": sha256_file(target / "work.json"),
            "proposed_sha256": sha256_file(staged_file)}
    return root, stage, target, item


def test_guarded_install_records_complete_generation(tmp_path: Path) -> None:
    from build.tools.install_direct_tcp_four_sidecars import _install_one, _tree

    root, stage, target, item = _generation(tmp_path)
    result = _install_one(root, stage, "test-work", [item], validate_live=False)
    assert _tree(target)["work.json"] == item["proposed_sha256"]
    assert result["after"]["work.json"] == item["proposed_sha256"]
    assert (Path(result["operation"]) / "operation.json").read_text(encoding="utf-8").find('"complete"') >= 0


def test_guarded_install_rolls_back_failed_swap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from build.tools.install_direct_tcp_four_sidecars import _install_one, _tree

    root, stage, target, item = _generation(tmp_path)
    original_rename = Path.rename

    def fail_incoming(source: Path, destination: Path) -> Path:
        if source.name == "incoming":
            raise OSError("injected second rename failure")
        return original_rename(source, destination)

    monkeypatch.setattr(Path, "rename", fail_incoming)
    with pytest.raises(OSError, match="injected second rename failure"):
        _install_one(root, stage, "test-work", [item], validate_live=False)
    assert _tree(target)["work.json"] == item["before_sha256"]
    journals = list((root / "library" / ".sidecar-operations").glob("*/operation.json"))
    assert len(journals) == 1
    assert '"rolled-back"' in journals[0].read_text(encoding="utf-8")
