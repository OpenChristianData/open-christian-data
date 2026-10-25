"""Source-bound attribution notices in the offline public card."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.public_allowlist import preview_release, render_dataset_card
from ocd_kernel.release.selection import validate_release_selection
from ocd_kernel.release.verify import verify_release_v2
from tests.test_release_assembly_v2 import _item, _promoted_category, _selection


REPO = Path(__file__).resolve().parents[1]
LAW_SOURCE = "sources/structured-text/law-serious-call/README.source.md"
LAW_NOTICE = "data/structured-text/README.md"
LAW_SOURCE_SHA = "3a728f28c3d26523af6c53074b1c31b01fb3beaf7e91d0c35fc05be65ce9ca4d"
LAW_NOTICE_SHA = "5e5486361f57c60837fa8447751ebd79935c414cb42f32e9605d2830a514be3c"


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("rn")


def _binding(source_path: str, source_sha: str, notice_sha: str = LAW_NOTICE_SHA) -> dict:
    return dict(source_path=source_path, source_sha256=source_sha,
                notice_path=LAW_NOTICE, notice_sha256=notice_sha)


def _fixture(tmp_path):
    root, acceptance = _promoted_category(tmp_path, "quotations", "notices")
    identity = json.loads(acceptance.read_text(encoding="utf-8"))["identity"]
    source_path = f"sources/structured-text/{identity['work_id']}/README.source.md"
    source = (REPO / LAW_SOURCE).read_bytes()
    notice = (REPO / LAW_NOTICE).read_bytes()
    (root / source_path).parent.mkdir(parents=True, exist_ok=True)
    (root / source_path).write_bytes(source)
    (root / LAW_NOTICE).parent.mkdir(parents=True, exist_ok=True)
    (root / LAW_NOTICE).write_bytes(notice)
    selected = _item(root, "quote", "quotations", acceptance,
                     public_notices=[_binding(source_path, hashlib.sha256(source).hexdigest())])
    return root, acceptance, _selection(selected), notice.decode("utf-8")


def test_real_law_notice_is_bound_to_reviewed_source_and_verbatim_public_text():
    acceptance = next((REPO / "library/works/law-serious-call").rglob("acceptance.json"))
    bound = _binding(LAW_SOURCE, LAW_SOURCE_SHA)
    text = notice_texts_for_item(REPO, {"item_id": "law", "public_notices": [bound]}, acceptance)
    assert text == [(REPO / LAW_NOTICE).read_text(encoding="utf-8")]
    assert "sourced via" in text[0] and "Do not sell CCEL files" in text[0]


def test_selected_notice_is_deterministic_public_and_independently_verified(tmp_path):
    root, _acceptance, selection, notice = _fixture(tmp_path)
    release = tmp_path / "release"
    report = assemble_release_v2(root, release, selection=selection)
    card = (release / "public/README.md").read_text(encoding="utf-8")
    assert report["status"] == "pass"
    assert card.count(notice) == 1
    assert card.endswith(notice)
    assert verify_release_v2(root, release, selection=selection) == {"status": "pass", "errors": []}
    assert preview_release(root, release, selection=selection)["status"] == "pass"

    (release / "public/README.md").write_text(card.replace(notice, ""), encoding="utf-8")
    result = verify_release_v2(root, release, selection=selection)
    assert result["status"] == "fail"
    assert any("dataset card" in issue for issue in result["errors"])

    (release / "public/README.md").write_text(card, encoding="utf-8", newline="\n")
    source_path = selection["items"][0]["public_notices"][0]["source_path"]
    (root / source_path).write_text("# Changed source notice\n", encoding="utf-8", newline="\n")
    drift = verify_release_v2(root, release, selection=selection)
    assert drift["status"] == "fail"
    assert any("source notice SHA-256 mismatch" in issue for issue in drift["errors"])


def test_failed_item_cannot_emit_its_notice(tmp_path):
    root, acceptance, selection, notice = _fixture(tmp_path)
    failed = copy.deepcopy(selection["items"][0])
    failed.update(item_id="future", category="future_category")
    failed["public_notices"][0]["notice_path"] = "data/future-only/README.md"
    failed["public_notices"][0]["notice_sha256"] = "0" * 64
    selection["items"].append(failed)
    release = tmp_path / "failed-release"
    from tests.test_release_assembly_v2 import _failed_release
    report, release = _failed_release(root, release, selection=selection)
    assert report["status"] == "fail"
    assert report["accounting"]["failed"] == 1
    card = (release / "public/README.md").read_text(encoding="utf-8")
    assert card.count(notice) == 1
    assert "future_category" not in card
    assert "future-only" not in card
    assert verify_release_v2(root, release, selection=selection)["status"] == "fail"


def test_excluded_binding_and_cross_work_binding_fail_closed(tmp_path):
    root, acceptance, selection, _notice = _fixture(tmp_path)
    excluded = copy.deepcopy(selection)
    excluded["items"][0]["exclude_reason"] = "held"
    with pytest.raises(PipelineError, match="excluded item"):
        validate_release_selection(excluded)

    wrong = copy.deepcopy(selection["items"][0])
    wrong["public_notices"][0]["source_path"] = LAW_SOURCE
    with pytest.raises(PipelineError, match="not source-bound"):
        notice_texts_for_item(root, wrong, acceptance)


def test_bad_hash_utf8_and_private_notice_content_fail_closed(tmp_path):
    root, acceptance, selection, _notice = _fixture(tmp_path)
    selected = selection["items"][0]
    wrong = copy.deepcopy(selected)
    wrong["public_notices"][0]["notice_sha256"] = "0" * 64
    with pytest.raises(PipelineError, match="SHA-256 mismatch"):
        notice_texts_for_item(root, wrong, acceptance)

    notice_path = root / LAW_NOTICE
    notice_path.write_bytes(b"\xff\n")
    invalid = copy.deepcopy(selected)
    invalid["public_notices"][0]["notice_sha256"] = hashlib.sha256(notice_path.read_bytes()).hexdigest()
    with pytest.raises(PipelineError, match="not UTF-8"):
        notice_texts_for_item(root, invalid, acceptance)

    notice_path.write_text("# Notice\n\nSee library/works/private.json.\n", encoding="utf-8", newline="\n")
    private = copy.deepcopy(selected)
    private["public_notices"][0]["notice_sha256"] = hashlib.sha256(notice_path.read_bytes()).hexdigest()
    with pytest.raises(PipelineError, match="private path"):
        notice_texts_for_item(root, private, acceptance)


def test_notice_card_deduplicates_identical_explicit_text():
    config = [{"category": "prose", "path": "public/data/prose/train.jsonl", "row_count": 1}]
    notice = "# Attribution\n\nCredit the retained provider.\n"
    card = render_dataset_card(config, notices=[notice, notice])
    assert card.count(notice) == 1
    assert "Licenses vary by record" in card
    assert "not automatically to unrelated records" in card
