"""Focused bsb829 Disputatio source ownership, frozen stage, and fixture rollback checks."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.openmgh_exact_work_div import check_candidate
from build.tools import install_openmgh_bsb829_disputatio_exact as cohort
from build.tools import prepare_openmgh_exact_work_div_batch as batch
from build.tools.install_openmgh_exact_work_div_batch import _frozen
from ocd_kernel.library._common import PipelineError
from tests.openmgh_historical_fixture import historical_exact_work_root
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path


ROOT = batch.ROOT
MANIFEST = ROOT / "plans/2026-09-22-source-preflight/openmgh-exact-batch-bsb829-disputatio-20260927.json"


@pytest.fixture(scope="module")
def historical_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return historical_exact_work_root(
        ROOT, tmp_path_factory.mktemp("mgh-exact-historical"), MANIFEST,
        cohort.FREEZE, cohort.FREEZE_SHA256,
    )


def _case(index: int, historical_root: Path) -> tuple[bytes, bytes, dict, dict, dict, dict]:
    manifest = batch._manifest(MANIFEST, ROOT)
    entry = manifest["works"][index]
    work, acquisition = batch._work(historical_root, entry, manifest)
    retained = (ROOT / manifest["source"]["path"]).read_bytes()
    candidate = batch._candidate(batch.parse_tei(retained), manifest, entry, work)
    return retained, candidate, manifest, entry, work, acquisition


@pytest.mark.parametrize("index", range(1))
def test_catalog_ids_identify_entire_exclusive_source_div(index: int, historical_root: Path) -> None:
    retained, candidate, manifest, entry, work, acquisition = _case(index, historical_root)
    checked = check_candidate(retained, candidate, manifest, entry, work, acquisition)
    assert checked["source_work_div_index"] == entry["source_work_div_index"]
    assert checked["source_node_count"] > 1
    assert checked["source_page_breaks"] >= 1


def test_all_volume_children_are_selected_or_explicitly_held() -> None:
    manifest = batch._manifest(MANIFEST, ROOT)
    selected = set(manifest["selected_work_div_indexes"])
    held = set(manifest["excluded_work_div_indexes"])
    dispositions = manifest["excluded_work_div_dispositions"]
    assert selected == {entry["source_work_div_index"] for entry in manifest["works"]}
    assert selected.isdisjoint(held)
    assert selected | held == set(range(manifest["source"]["volume_child_count"]))
    assert {item["source_work_div_index"] for item in dispositions} == held
    assert all(item["disposition"].startswith("held: ") for item in dispositions)
    assert manifest["marker_ownership"]["top_level_interstitial_nodes"] == []
    assert manifest["marker_ownership"]["shared_heading_nodes"] == []
    assert Path(manifest["source"]["path"]).suffix == ".xml"
    assert Path(manifest["package"]["path"]).suffix == ".zip"


def test_oracle_rejects_lost_internal_page_marker(historical_root: Path) -> None:
    retained, candidate, manifest, entry, work, acquisition = _case(0, historical_root)
    tree = etree.fromstring(candidate)
    marker = tree.xpath("//*[local-name()='body']//*[local-name()='pb']")[0]
    marker.getparent().remove(marker)
    with pytest.raises(ValueError, match="candidate differs"):
        check_candidate(retained, etree.tostring(tree), manifest, entry, work, acquisition)


def test_oracle_rejects_neighbor_catalog_identity(historical_root: Path) -> None:
    retained, candidate, manifest, entry, work, acquisition = _case(0, historical_root)
    changed = deepcopy(work)
    neighbor = "bsb00000829_00676_6"
    changed["textual_forms"][0]["editions"][0]["containing_source"]["locator"] = (
        f"{manifest['source']['path']}#{neighbor}"
    )
    with pytest.raises(ValueError, match="catalog"):
        check_candidate(retained, candidate, manifest, entry, changed, acquisition)


def test_frozen_pin_and_allowlist() -> None:
    manifest = batch._manifest(MANIFEST, ROOT)
    assert sha256(cohort.FREEZE.read_bytes()).hexdigest() == cohort.FREEZE_SHA256
    assert cohort.WORKS == {entry["work_id"] for entry in manifest["works"]}
    with pytest.raises(PipelineError, match="freeze changed"):
        _frozen(cohort.FREEZE, "0" * 64)


def test_stock_transaction_rolls_back_isolated_work(tmp_path: Path, historical_root: Path) -> None:
    work_id = "disputatio-vel-defensio-paschalis-papae"
    record_path = Path(
        "D:/Library/Open Christian Data/candidate-reviews/"
        f"openmgh-exact-bsb829-disputatio-stages-20260927/{work_id}.json"
    )
    record = json.loads(Path(_io_path(record_path)).read_bytes())
    fixture = tmp_path / "r"
    work_rel = Path("library/works") / work_id
    target = fixture / work_rel
    target.parent.mkdir(parents=True)
    shutil.copytree(_io_path(historical_root / work_rel), _io_path(target))
    before = _files(target)
    assert before == record["before"]
    source = Path(record["stage_root"]) / work_rel

    def fail_after_new_live(point: str) -> None:
        if point == "after-new-live":
            raise RuntimeError("injected bsb829 Disputatio rollback")

    with pytest.raises(RuntimeError, match="injected bsb829 Disputatio rollback"):
        _commit_generation(
            fixture, target, source, work_id=work_id,
            before=record["before"], after=record["after"],
            existed=True, replacement=False,
            operation_kind="openmgh-exact-work-div-fixture",
            result_status="installed-and-validated", accepted_editions=1,
            fail_at=fail_after_new_live,
        )
    assert _files(target) == before
    journals = list((fixture / ".tmp_audit").glob("accepted-install-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text(encoding="utf-8"))["phase"] == "rolled-back"


def test_lamentatio_two_letter_carrier_is_held() -> None:
    manifest = batch._manifest(MANIFEST, ROOT)
    held = {item["source_work_div_index"]: item["disposition"]
            for item in manifest["excluded_work_div_dispositions"]}
    assert 18 in held and "Lamentatio and Excusatio" in held[18]
    retained = batch.parse_tei((ROOT / manifest["source"]["path"]).read_bytes())
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    volume = retained.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)[0]
    carrier = list(volume)[18]
    assert [child.get("type") for child in carrier] == ["part", "part"]
    starts = [" ".join(" ".join(child.itertext()).split()) for child in carrier]
    assert starts[0].startswith("[LAMENTATIO PRO CAPTIONE PAPE PASCHALIS.]")
    assert starts[1].startswith("[EXCUSATIO DISPENSATIONIS PAPE PRO CAPTIONE SUA.]")
    assert 18 not in manifest["selected_work_div_indexes"]


def test_shared_carriers_stay_held() -> None:
    manifest = batch._manifest(MANIFEST, ROOT)
    shared = [item["source_work_div_index"]
              for item in manifest["excluded_work_div_dispositions"]
              if "shared source carrier" in item["disposition"]]
    assert shared == [0, 3, 5, 14, 16, 20]


def test_all_prior_installed_divisions_stay_outside_scope() -> None:
    manifest = batch._manifest(MANIFEST, ROOT)
    prior = [item for item in manifest["excluded_work_div_dispositions"]
             if "already installed accepted master" in item["disposition"]]
    assert len(prior) == 13
    assert not {item["source_work_div_index"] for item in prior} & set(
        manifest["selected_work_div_indexes"])


def test_current_metadata_does_not_satisfy_historical_before_pin() -> None:
    manifest = batch._manifest(MANIFEST, ROOT)
    entry = manifest["works"][0]
    assert sha256((ROOT / entry["work_path"]).read_bytes()).hexdigest() != entry["work_sha256"]
    with pytest.raises(ValueError, match="work or acquisition preimage changed"):
        batch._work(ROOT, entry, manifest)


def test_real_installer_rejects_noncanonical_fixture_root(historical_root: Path) -> None:
    from build.tools.install_openmgh_exact_work_div_batch import preflight

    with pytest.raises(PipelineError, match="canonical workspace checkout required"):
        preflight(cohort.FREEZE, expected_freeze_sha256=cohort.FREEZE_SHA256,
                  work_id=next(iter(cohort.WORKS)), root=historical_root)
