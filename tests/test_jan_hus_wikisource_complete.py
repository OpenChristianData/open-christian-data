from __future__ import annotations

from pathlib import Path

from build.tei.jan_hus_wikisource_complete import _convert
from build.tei.jan_hus_wikisource_complete_oracle import findings
from ocd_kernel.reconstruction.contract import SourceManifest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "sources/manifest-acquisitions/wikisource-jan-hus-complete-20261008/source-manifest.json"


def test_complete_wikisource_witness_replays_and_rejects_text_or_page_mutation():
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    members = _convert(manifest)
    raw = members["content.tei.xml"]
    assert findings(manifest, raw) == []

    changed_text = raw.replace(
        b'xml:id="jan-hus-chapter-1"', b'xml:id="jan-hus-chapter-X"', 1
    )
    assert changed_text != raw
    assert findings(manifest, changed_text)

    first_page = b'<pb n="5"'
    assert first_page in raw
    assert findings(manifest, raw.replace(first_page, b'<pb n="6"', 1))
