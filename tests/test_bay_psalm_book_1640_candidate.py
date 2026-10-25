"""Focused whole-source proof for the nonaccepted Bay Psalm Book candidate."""

from pathlib import Path

import pytest

from build.tei.bay_psalm_book_1640_oracle import _oracle
from build.tei.bay_psalm_book_1640_reconstruction import _convert
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/bay-psalm-book-1640.source-manifest.json'


@pytest.fixture(scope="module")
def bound_pair(tmp_path_factory: pytest.TempPathFactory) -> tuple[SourceManifest, CandidatePackage]:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    package = reconstruct(source, tmp_path_factory.mktemp("n00001") / "package", _convert)
    return source, package


class ChangedContent:
    """Supply altered TEI to the independent oracle without rebuilding a package."""

    def __init__(self, original: CandidatePackage, changed: bytes):
        self.sha256 = original.sha256
        self.manifest = original.manifest
        self.original = original
        self.changed = changed

    def member_bytes(self, name: str) -> bytes:
        return self.changed if name == "content.tei.xml" else self.original.member_bytes(name)


def test_current_candidate_is_exact_source_and_tei_p5(
    bound_pair: tuple[SourceManifest, CandidatePackage],
) -> None:
    source, candidate = bound_pair
    report = validate(source, candidate, _oracle)
    assert report.status == "pass" and not report.findings
    content = candidate.member_bytes("content.tei.xml")
    assert content == (ROOT / "raw/tcp/high-range/N00001/N00001.xml").read_bytes()


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b'<front>', b'<front type="lost-front">'),
        (b'<body>', b'<body type="lost-body">'),
        (b'<back>', b'<back type="lost-back">'),
        (b'<gap reason="illegible: missing"', b'<gap reason="invented"'),
        (b'<pb facs="unknown:000004_0000_0F9EDB7385F953D0"/>', b'<pb facs="invented"/>'),
    ],
)
def test_oracle_rejects_whole_source_feature_mutations(
    bound_pair: tuple[SourceManifest, CandidatePackage], old: bytes, new: bytes
) -> None:
    source, candidate = bound_pair
    original = candidate.member_bytes("content.tei.xml")
    assert original.count(old) == 1
    changed = original.replace(old, new, 1)
    result = _oracle(source, ChangedContent(candidate, changed))
    assert result["status"] == "fail"
    assert "candidate TEI is not byte-identical to retained N00001 XML" in result["findings"]


def test_oracle_rejects_verse_note_and_final_matter_mutations(
    bound_pair: tuple[SourceManifest, CandidatePackage],
) -> None:
    source, candidate = bound_pair
    original = candidate.member_bytes("content.tei.xml")
    for old, new in (
        (b"<l>", b"<l n=\"invented\">"),
        (b"<note>", b"<note place=\"invented\">"),
        (b'type="errata"', b'type="invented"'),
    ):
        assert old in original
        changed = original.replace(old, new, 1)
        result = _oracle(source, ChangedContent(candidate, changed))
        assert result["status"] == "fail"
        assert "candidate TEI is not byte-identical to retained N00001 XML" in result["findings"]
