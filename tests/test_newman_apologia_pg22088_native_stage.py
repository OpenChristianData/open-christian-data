"""Focused reversible-carrier guards for Newman Apologia PG22088."""

from collections import Counter
from hashlib import sha256
from pathlib import Path

from lxml import etree
import pytest

from build.tei import newman_apologia_pg22088_native as native
from build.tei import newman_apologia_pg22088_native_oracle as oracle
from ocd_kernel.projection.categories.native_documents import project_document
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


@pytest.fixture(scope="module", autouse=True)
def current_source_oracle(tmp_path_factory):
    from tests.runtime_candidate_baselines import current_runtime_baseline

    root = Path(__file__).resolve().parents[1]
    manifest, candidate = current_runtime_baseline(
        root=root,
        original_manifest="sources/structured-text/newman-apologia-pro-vita-sua/LIB-068.source-manifest.json",
        runtime_manifest="tests/fixtures/reconstruction-runtime/newman-lib068.source-manifest.json",
        retained_package=oracle.PACKAGE,
        retained_sha256="16b3ab4991f1f9f0ad5f03f010623073253172df630c5118929542240987ad18",
        destination=tmp_path_factory.mktemp("newman-current-oracle") / "handoff",
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(oracle, "MANIFEST", manifest.path)
        patch.setattr(oracle, "PACKAGE", candidate.path)
        yield


def _roots() -> tuple[etree._Element, etree._Element, bytes]:
    raw = native.direct_candidate()
    adapted, counts = native.adapt(raw)
    assert counts == native.EXPECTED
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    return etree.fromstring(raw, parser), etree.fromstring(adapted, parser), adapted


def test_source_oracle_reverse_structure_p5_and_native_prose(tmp_path: Path) -> None:
    _, _, adapted = _roots()
    report = oracle.check(adapted)
    assert report["source_oracle_status"] == "pass"
    assert report["carrier_counts"] == native.EXPECTED
    identity = {
        "work_id": "newman-apologia-pro-vita-sua",
        "textual_form_id": "newman-apologia-pro-vita-sua-retained-electronic",
        "edition_id": "newman-apologia-pro-vita-sua-retained-electronic-witness",
        "acquisition_id": "newman-apologia-pro-vita-sua-retained-source",
    }
    source = {"source_path": "raw/gutenberg/pg22088.txt", "source_sha256": native.SOURCE_SHA256,
              "source_bytes": 818680}
    revision = {"id": "newman-apologia-pg22088-current-v1", "date": "2026-09-28",
                "note": "Complete retained electronic witness."}
    bound = bind_reviewed_header(adapted, expected_sha256=sha256(adapted).hexdigest(),
                                 identity=identity, source=source,
                                 source_url="https://www.gutenberg.org/ebooks/22088",
                                 declared_scope="Complete retained PG22088 electronic member",
                                 revision=revision)
    path = tmp_path / "bound.tei.xml"
    path.write_bytes(bound)
    assert validate_file(path) == []
    projected = project_document(path, identity={key: identity[key] for key in
                                                  ("work_id", "textual_form_id", "edition_id")},
                                 language="en", representation_revision=revision["id"],
                                 edition_title="Project Gutenberg retained electronic witness",
                                 _allow_acceptance_metadata=True, category="prose")
    assert len(projected["rows"]) == 1
    assert projected["receipt"]["unsupported"] == []


def test_provider_partition_preserves_all_lines_outside_work_text(tmp_path: Path) -> None:
    _, _, adapted = _roots()
    work, header, license = native.partition(adapted)
    report = oracle.check_partition(adapted, work, header, license)
    assert report["represented_work_lines"] == 13790
    assert report["evidence_only_provider_lines"] == 384
    assert report["work_line_range"] == [33, 13822]
    root = etree.fromstring(work)
    divisions = root.findall(native.TEI + "text/" + native.TEI + "body/" + native.TEI + "div/" + native.TEI + "div")
    assert len(divisions) == 7
    assert divisions[0].get("type") == "title-page"
    assert divisions[-1].get("type") == "additional-notes"
    path = tmp_path / "work-only.tei.xml"
    path.write_bytes(work)
    assert validate_file(path) == []


def test_partition_oracle_rejects_changed_provider_evidence() -> None:
    _, _, adapted = _roots()
    work, header, license = native.partition(adapted)
    changed = etree.fromstring(license)
    segment = next(node for node in changed.iter(native.TEI + "seg") if node.get("n") == "13823")
    segment.text = "changed provider delimiter"
    with pytest.raises(ValueError, match="difference"):
        oracle.check_partition(adapted, work, header,
                               etree.tostring(changed, encoding="UTF-8", xml_declaration=True))


@pytest.mark.parametrize(
    ("tag", "attribute", "original", "changed"),
    [
        ("ab", "subtype", "source-whitespace", "wrong-whitespace"),
        ("seg", "subtype", "source-part-I__source-column-day-0-2", "source-part-F__source-column-day-0-2"),
        ("list", "type", "chronology-entries__source_n_11157", "chronology-entries__source_n_11158"),
        ("lg", "type", "stanza__source_n_43", "stanza__source_n_44"),
        ("floatingText", "type", "source-letter__source_n_12579", "source-letter__source_n_12580"),
        ("seg", "type", "source-recipient-address", "wrong-address"),
        ("seg", "type", "source-recipient-address-line", "wrong-address-line"),
        ("cell", "role", "day__source_n_1", "day__source_n_2"),
    ],
)
def test_reverse_oracle_rejects_carrier_mutations(
    tag: str, attribute: str, original: str, changed: str
) -> None:
    before, after, _ = _roots()
    matches = [node for node in after.iter(native.TEI + tag) if node.get(attribute) == original]
    assert matches
    matches[0].set(attribute, changed)
    with pytest.raises(ValueError, match="difference|cannot be reversed|census"):
        counts: Counter[str] = Counter()
        oracle._restore(after, counts)
        if dict(counts) != oracle.EXPECTED:
            raise ValueError("PG22088 reverse carrier census differs")
        oracle._compare(before, after)


def test_reverse_oracle_rejects_text_mutation() -> None:
    before, after, _ = _roots()
    line = next(node for node in after.iter(native.TEI + "seg") if node.get("n") == "1")
    line.text = (line.text or "") + " changed"
    counts: Counter[str] = Counter()
    oracle._restore(after, counts)
    with pytest.raises(ValueError, match="text difference"):
        oracle._compare(before, after)


def test_direct_source_digest_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(native, "DIRECT_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="source-bound TEI differs"):
        native.direct_candidate()
