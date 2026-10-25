"""Challenge the complete exact-byte TCP A23804 candidate and one-work boundary."""

from pathlib import Path

import pytest

from build.tei.whole_duty_prayer_a23804_oracle import _oracle
from build.tei.whole_duty_prayer_a23804_reconstruction import _convert
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "sources/structured-text/whole-duty-of-prayer/whole-duty-of-prayer.source-manifest.json"
SOURCE = ROOT / "raw/tcp/high-range/A23804/A23804.xml"


@pytest.fixture(scope="module")
def bound_pair(tmp_path_factory: pytest.TempPathFactory) -> tuple[SourceManifest, CandidatePackage]:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    package = reconstruct(source, tmp_path_factory.mktemp("a23804") / "package", _convert)
    return source, package


class ChangedContent:
    """Expose one mutated TEI member to the independent oracle."""

    def __init__(self, original: CandidatePackage, changed: bytes):
        self.sha256 = original.sha256
        self.manifest = original.manifest
        self.original = original
        self.changed = changed

    def member_bytes(self, name: str) -> bytes:
        return self.changed if name == "content.tei.xml" else self.original.member_bytes(name)


def _replace_once(original: bytes, old: bytes, new: bytes) -> bytes:
    assert original.count(old) == 1, old
    return original.replace(old, new, 1)


def test_one_complete_titled_work_produces_one_p5_tei(bound_pair: tuple[SourceManifest, CandidatePackage]) -> None:
    source, candidate = bound_pair
    report = validate(source, candidate, _oracle)
    tei_members = [name for name in candidate.member_names if name.endswith(".tei.xml")]
    candidate_bytes = candidate.member_bytes("content.tei.xml")
    assert report.status == "pass" and not report.findings
    assert tei_members == ["content.tei.xml"]
    assert candidate_bytes == SOURCE.read_bytes()
    assert candidate.manifest["status"] == "nonaccepted"


def test_source_identity_author_qualification_and_internal_devotions_are_bound(
    bound_pair: tuple[SourceManifest, CandidatePackage],
) -> None:
    source, candidate = bound_pair
    result = _oracle(source, candidate)
    assert result["status"] == "pass" and not result["findings"]
    profile = __import__("json").loads(
        source.authority_path("reconstruction-profile").read_text(encoding="utf-8")
    )
    features = profile["source_features"]
    assert features["title_statement_titles"] == [
        "The whole duty of prayer containing devotions for every day in the week, and for several occasions, ordinary and extraordinary / by the author of The whole duty of man ..."
    ]
    assert features["grouped_work_text_count"] == 1
    assert features["body_div_types"] == ["part", "title_page", "part"]
    assert any("preponderance of opinion" in note for note in features["source_notes"])
    assert any("Additional devotions for several occasions" in note for note in features["source_notes"])


def test_independent_oracle_rejects_four_p5_valid_source_mutations(
    bound_pair: tuple[SourceManifest, CandidatePackage], tmp_path: Path
) -> None:
    source, candidate = bound_pair
    original = candidate.member_bytes("content.tei.xml")
    mutations = (
        (
            b'<idno type="DLPS">A23804</idno>',
            b'<idno type="DLPS">A23805</idno>',
        ),
        (
            b"No absolute certainty has yet been reached",
            b"Absolute certainty has been reached",
        ),
        (b"special t.p.", b"separate title page"),
        (
            b'<pb n="1" facs="tcp:64934:4"',
            b'<pb n="1a" facs="tcp:64934:4"',
        ),
    )
    for index, (old, new) in enumerate(mutations):
        changed = _replace_once(original, old, new)
        changed_path = tmp_path / f"mutation-{index}.tei.xml"
        changed_path.write_bytes(changed)
        assert validate_file(changed_path) == []
        result = _oracle(source, ChangedContent(candidate, changed))
        assert result["status"] == "fail"
        assert "candidate TEI is not byte-identical to retained TCP A23804 XML" in result["findings"]
