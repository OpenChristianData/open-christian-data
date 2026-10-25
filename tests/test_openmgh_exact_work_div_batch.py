"""Focused source-ownership and mutation checks for generic openMGH work-div batches."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from lxml import etree
import pytest

from build.tei.openmgh_exact_work_div import check_candidate
from build.tools import prepare_openmgh_exact_work_div_batch as batch
from build.tools import install_openmgh_bsb705_exact as cohort
from build.tools.install_openmgh_exact_work_div_batch import _frozen
from ocd_kernel.library._common import PipelineError
from tests.openmgh_historical_fixture import historical_exact_work_root


MANIFEST = (batch.ROOT / "plans/2026-09-22-source-preflight/"
            "openmgh-exact-batch-bsb705-manifest-20260927.json")


@pytest.fixture(scope="module")
def historical_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return historical_exact_work_root(
        batch.ROOT, tmp_path_factory.mktemp("mgh-exact-historical"), MANIFEST,
        cohort.FREEZE, cohort.FREEZE_SHA256,
    )


def _case(index: int, historical_root: Path) -> tuple[bytes, bytes, dict, dict, dict, dict]:
    manifest = batch._manifest(MANIFEST, batch.ROOT)
    entry = manifest["works"][index]
    work, acquisition = batch._work(historical_root, entry, manifest)
    source_bytes = (batch.ROOT / manifest["source"]["path"]).read_bytes()
    candidate = batch._candidate(batch.parse_tei(source_bytes), manifest, entry, work)
    return source_bytes, candidate, manifest, entry, work, acquisition


@pytest.mark.parametrize("index", range(7))
def test_catalog_ids_independently_identify_complete_disjoint_source_div(index: int, historical_root: Path) -> None:
    retained, candidate, manifest, entry, work, acquisition = _case(index, historical_root)
    checked = check_candidate(retained, candidate, manifest, entry, work, acquisition)
    assert checked["source_work_div_index"] == index
    assert checked["source_node_count"] > 1
    assert checked["source_page_breaks"] >= 1


def test_oracle_rejects_lost_internal_line(historical_root: Path) -> None:
    retained, candidate, manifest, entry, work, acquisition = _case(1, historical_root)
    tree = etree.fromstring(candidate)
    block = tree.xpath("//*[local-name()='body']/*[local-name()='div']/*[local-name()='ab']")[0]
    line = next(node for node in block if node.tag.endswith("}lb"))
    block.remove(line)
    with pytest.raises(ValueError, match="candidate differs"):
        check_candidate(retained, etree.tostring(tree), manifest, entry, work, acquisition)


def test_oracle_rejects_catalog_id_owned_by_a_neighbor(historical_root: Path) -> None:
    retained, candidate, manifest, entry, work, acquisition = _case(1, historical_root)
    neighbor = manifest["works"][2]["catalog_locator_ids"][0]
    changed = deepcopy(work)
    changed["textual_forms"][0]["editions"][0]["containing_source"]["locator"] = (
        f"{manifest['source']['path']}#{neighbor}"
    )
    with pytest.raises(ValueError, match="catalog"):
        check_candidate(retained, candidate, manifest, entry, changed, acquisition)


def test_shared_top_level_marker_must_be_explicitly_handled(historical_root: Path) -> None:
    retained, candidate, manifest, entry, work, acquisition = _case(1, historical_root)
    changed = deepcopy(manifest)
    changed["marker_ownership"]["shared_heading_nodes"] = ["unreviewed heading"]
    with pytest.raises(ValueError, match="shared top-level markers"):
        check_candidate(retained, candidate, changed, entry, work, acquisition)


def test_manifest_source_and_zip_are_distinct_pinned_members() -> None:
    manifest = batch._manifest(MANIFEST, batch.ROOT)
    assert Path(manifest["source"]["path"]).suffix == ".xml"
    assert Path(manifest["package"]["path"]).suffix == ".zip"
    assert manifest["source"]["sha256"] != manifest["package"]["sha256"]


def test_reviewed_cohort_pin_and_allowlist_match_manifest() -> None:
    manifest = batch._manifest(MANIFEST, batch.ROOT)
    assert sha256(cohort.FREEZE.read_bytes()).hexdigest() == cohort.FREEZE_SHA256
    assert cohort.WORKS == {entry["work_id"] for entry in manifest["works"]}
    with pytest.raises(PipelineError, match="freeze changed"):
        _frozen(cohort.FREEZE, "0" * 64)


def test_current_metadata_does_not_satisfy_historical_before_pin() -> None:
    manifest = batch._manifest(MANIFEST, batch.ROOT)
    entry = manifest["works"][0]
    assert sha256((batch.ROOT / entry["work_path"]).read_bytes()).hexdigest() != entry["work_sha256"]
    with pytest.raises(ValueError, match="work or acquisition preimage changed"):
        batch._work(batch.ROOT, entry, manifest)


def test_real_installer_rejects_noncanonical_fixture_root(historical_root: Path) -> None:
    from build.tools.install_openmgh_exact_work_div_batch import preflight

    with pytest.raises(PipelineError, match="canonical workspace checkout required"):
        preflight(cohort.FREEZE, expected_freeze_sha256=cohort.FREEZE_SHA256,
                  work_id=next(iter(cohort.WORKS)), root=historical_root)
