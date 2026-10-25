"""Exact PG37311 native source routing and independent mutation checks."""

from collections import Counter
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import xml.etree.ElementTree as ET

from lxml import etree
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import woolman_pg37311_source_profile as woolman
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.projection.native_content import project_content, readable_content
from ocd_kernel.projection.native_content_check import observe_content, verify_content
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.public_rows import public_rows_with_omissions
from ocd_kernel.release.work_metadata import compose_work_metadata


ROOT = Path(__file__).resolve().parents[1]
EDITION = ROOT / "library/works/john-woolman-journal-other-writings/forms/english/editions/everyman-402-1910-electronic"
MASTER = EDITION / "master.tei.xml"
ACCEPTANCE = EDITION / "acceptance.json"
ITEM = "john-woolman-journal-other-writings--everyman-402-1910-electronic"
NS = "{http://www.tei-c.org/ns/1.0}"


@pytest.mark.requires_local_artifacts
def test_exact_source_profile_and_census_refuse_mutations() -> None:
    raw = MASTER.read_bytes()
    assert sha256(raw).hexdigest() == woolman.MASTER_SHA256
    assert woolman.route(raw, identity=woolman.IDENTITY, language="en", category="prose",
                         collection=False, projection_profile=woolman.PROFILE,
                         allow_acceptance_metadata=True)
    woolman.check_et(ET.fromstring(raw), raw)
    woolman.check_lxml(etree.fromstring(raw), raw)
    with pytest.raises(ValueError, match="exact accepted master"):
        woolman.route(raw.replace(b"JOHN WOOLMAN", b"JOHN WOOLMAM", 1),
                      identity=woolman.IDENTITY, language="en", category="prose",
                      collection=False, projection_profile=woolman.PROFILE,
                      allow_acceptance_metadata=True)
    with pytest.raises(ValueError, match="cannot apply to another work"):
        woolman.route(raw, identity=woolman.IDENTITY | {"work_id": "another-work"},
                      language="en", category="prose", collection=False,
                      projection_profile=woolman.PROFILE, allow_acceptance_metadata=True)
    mutated = ET.fromstring(raw)
    next(mutated.iter(NS + "graphic")).set("url", "images/wrong.jpg")
    with pytest.raises(ValueError, match="image references"):
        woolman.check_et(mutated, raw)
    observed = etree.fromstring(raw)
    next(observed.iter(NS + "ab")).set("type", "source-invented")
    with pytest.raises(ValueError, match="block census"):
        woolman.check_lxml(observed, raw)


@pytest.mark.requires_local_artifacts
def test_every_source_block_type_roundtrips_independently() -> None:
    root = etree.fromstring(MASTER.read_bytes())
    samples = {}
    counts = Counter()
    for node in root.iter(NS + "ab"):
        counts[node.get("type")] += 1
        samples.setdefault(node.get("type"), node)
    assert counts == Counter(woolman.BLOCK_COUNTS)
    for kind, node in samples.items():
        raw = etree.tostring(node, encoding="utf-8", with_tail=False)
        content = project_content(ET.fromstring(raw), source_profile=woolman.PROFILE)
        text = readable_content(content)
        assert verify_content(raw, content, text, source_profile=woolman.PROFILE) == [], kind
        changed = deepcopy(content)
        changed["attributes"]["type"] = "source-invented"
        assert verify_content(raw, changed, text, source_profile=woolman.PROFILE), kind
    invented = ET.fromstring(f'<ab xmlns="{NS[1:-1]}" type="source-invented">text</ab>')
    with pytest.raises(PipelineError, match="unsupported native source block type"):
        project_content(invented, source_profile=woolman.PROFILE)
    with pytest.raises(ValueError, match="unsupported native source block type"):
        observe_content(ET.tostring(invented, encoding="utf-8"), source_profile=woolman.PROFILE)


@pytest.mark.requires_local_artifacts
def test_real_accepted_projection_and_independent_public_boundary() -> None:
    projection = project_accepted_prose(ROOT, acceptance_path=ACCEPTANCE)
    rows, receipt = projection["rows"], projection["receipt"]
    assert len(rows) == len(woolman.UNIT_IDS) == 12
    assert verify_accepted_prose(ROOT, acceptance_path=ACCEPTANCE, rows=rows, receipt=receipt) == []
    full, _ = compose_work_metadata(ROOT, rows, receipt)
    public, transform = public_rows_with_omissions(full, item_id=ITEM)
    assert transform is None
    assert [row["text"] for row in public] == [row["text"] for row in full]
    assert _scan(public, ITEM) == []
