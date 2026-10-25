"""Challenge the exact A47235 candidate against source-owned features."""

from pathlib import Path

import pytest

from build.tei.prayers_baths_for_cure_reconstruction import _convert
from build.tei.prayers_baths_for_cure_oracle import _oracle
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/prayers-baths-for-cure.source-manifest.json'

@pytest.fixture(scope="module")
def bound_pair(tmp_path_factory: pytest.TempPathFactory) -> tuple[SourceManifest, CandidatePackage]:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    package = reconstruct(source, tmp_path_factory.mktemp("a47235") / "package", _convert)
    return source, package


class ChangedContent:
    """Supply altered TEI to the independent checker without rebuilding a package."""

    def __init__(self, original: CandidatePackage, changed: bytes):
        self.sha256 = original.sha256
        self.manifest = original.manifest
        self.original = original
        self.changed = changed

    def member_bytes(self, name: str) -> bytes:
        return self.changed if name == "content.tei.xml" else self.original.member_bytes(name)


def test_current_candidate_is_source_bound_and_valid(bound_pair: tuple[SourceManifest, CandidatePackage]) -> None:
    source, candidate = bound_pair
    report = validate(source, candidate, _oracle)
    assert report.status == "pass" and not report.findings
    assert candidate.member_bytes("content.tei.xml") == (
        ROOT / "raw/tcp/high-range/A47235/A47235.xml"
    ).read_bytes()


def test_checker_rejects_loss_of_map_prayer_division_and_uncertain_text(
    bound_pair: tuple[SourceManifest, CandidatePackage],
) -> None:
    source, candidate = bound_pair
    original = candidate.member_bytes("content.tei.xml")
    for old, new in (
        (b'type="map"', b'type="lost-map"'),
        (b'type="prayers"', b'type="prose"'),
        (b'char:EOLunhyphen', b'char:EOLhyphen'),
        (b'<unclear>bear</unclear>', b'bare'),
    ):
        assert original.count(old) == 1
        changed = original.replace(old, new, 1)
        result = _oracle(source, ChangedContent(candidate, changed))
        assert result["status"] == "fail"
        assert "candidate TEI is not byte-identical to retained A47235 XML" in result["findings"]
