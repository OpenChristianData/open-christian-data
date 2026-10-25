from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path

from lxml import etree

from build.tei import calvin_commentaries_oracle as oracle
from build.tei import calvin_commentaries_reconstruction as producer
from ocd_kernel.reconstruction import SourceManifest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (
    ROOT / 'tests/fixtures/reconstruction-runtime/calvin-commentaries.source-manifest.json'
)


def test_calvin_selected_members_preserve_source_features_and_text() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    source.verify()

    for member in ("calcom01.xml", "calcom45.xml"):
        source_bytes = source.authority_path(member).read_bytes()
        source_root = producer._parse(source_bytes)
        oracle_root = oracle._parse(source_bytes)
        sink = producer._FeatureSink()
        output = BytesIO()
        with etree.xmlfile(output, encoding="UTF-8") as writer:
            writer.write_declaration()
            with writer.element(
                f"{{{producer.TEI_NS}}}TEI",
                nsmap={None: producer.TEI_NS, "xml": producer.XML_NS},
            ):
                producer._write_source_member(writer, member, source_root, sink)

        candidate_root = etree.fromstring(output.getvalue())
        projected_member = candidate_root[0]
        expected_features = oracle._expected_features(member, oracle_root, 1)
        observed_features = json.loads(b"[" + sink.buffer.getvalue() + b"]")

        assert observed_features == expected_features
        assert sink.member_stats[member]["element_count"] == len(expected_features)
        assert (
            sink.member_stats[member]["represented_element_count"]
            + sink.member_stats[member]["formatting_only_excluded_element_count"]
            == len(expected_features)
        )
        assert oracle._source_stream(oracle_root) == oracle._candidate_stream(
            projected_member
        )