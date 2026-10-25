"""Exact six-child LIB-040 stage, release gate, and rollback fixtures."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from build.tools import install_lib040_augustine_child as installer
from build.tools.install_lib040_augustine_child import (
    FIXTURE_MARKER, RECEIPT_SHA256, ROOT, _receipt, install, preflight,
)
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.tei.install_accepted import _files


# These are current implementation bytes; original stage receipts and all source,
# accepted-generation, row, and projection receipt pins remain unchanged.
CURRENT_CODE_SHA256 = {'build/tools/stage_lib040_augustine_division.py': '55eb4091788cfcaedf09a3aaf7e5abed41a01e26d6e40e1d702fd6be418c0195', 'ocd_kernel/projection/categories/commentary.py': 'f6dedc1ba7cb7a2c6c1c6572fd029a64e19e759cda0b349b60ac0d91c337f25f', 'ocd_kernel/projection/categories/lib040_augustine_divisions.py': '69f18e3b878be004c8b7e0193a17b97b1b008bf8c07ed87375f2eaeeb807bb70', 'ocd_kernel/projection/categories/lib040_augustine_selected.py': '59f9b78450bd691ff32870eca4b2dddbbd2e4bc482b950480732852869c1ff25', 'ocd_kernel/projection/categories/native_documents.py': '229f3f1e9be106c061c8f7a699820f263fc615798c61212ef8756a009261a59a', 'ocd_kernel/projection/categories/prose.py': 'e39117916a64f903bd2b5efc569096308c29c99f429f28386f0ada378aba49aa', 'ocd_kernel/projection/categories/sermons.py': '03a95a8305fa3bc00fa586b80240d8fbb24bbb87beba6f73267f37fe6d938795', 'ocd_kernel/projection/native_content.py': '0cf26976895508516f84bff8c6436acf35b5d0593632971cf5eb5a788165ff77'}
BEFORE_FIXTURES = Path(__file__).resolve().parent / "fixtures/reconstruction-runtime/authorities"

# Independently checked current receipts for the exact retained stage generations.
# Historical receipt bytes and all row/source/master/acceptance claims stay pinned.
CURRENT_PROJECTION_RECEIPT_SHA256 = {'augustine-soliloquies': 'bb90ad32e9bffc66006bc3e66919ccd3c5d7cb818ce6a816482ae461d2308c76', 'augustine-sermon-on-the-mount': '0c76043aceccc5b5d62fbc3b67736b6442108f9d8fe4e32417f5237b900e8734', 'augustine-tractates-on-john': '3ec1b9ee45bad3795fc0c0e34a3629b436a5bb3115b52c6f64c32469af34ca73', 'augustine-letters-part-1': '6a2c8701067941ad85f3e7ade1754284332f0c1b574256f9594501fdb52bcf1d', 'augustine-sermons-selected-lessons': 'dde24d39b95b359772d731620f668b1035bfde58af0de34015ab3f38dfdfb368', 'augustine-homilies-on-first-john': 'b3ff58680cecbe324cdf1da36383fcaf3edc043bf50679700af3e24e27b25e27'}
CURRENT_PROJECTION_AUTHORITY_SHA256 = {'schemas/v2/categories/prose.schema.json': 'df6e471ab4d3dce7db962958fc3981ee2014e0633829800f561060f4ad682ea8', 'schemas/v2/categories/commentary.schema.json': '0fef3ce3ae76e59f80560b50e4b0b6cbd07197845208194d0eb068aaa16b616a', 'schemas/v2/categories/sermons.schema.json': 'bd59b9e1a9cac78ef7128d130952775facb0cba4bef8eeafebc77f7edb0d22f0', 'schemas/v2/public-row.schema.json': '29451b7ba42c1a7e47cc9ea249d7eef9ce802883d52d4ff8c639370e3dcc85dc', 'schemas/v2/native-content.schema.json': 'adee3a40da9f908948e5589b8816a022ee2a96458cb7c9e013bdbf606e0011ab', 'build/bible_data/osis_book_codes.json': 'fc9ae1685535e787ba0d8101629818ce5582e7310b228595190f918611c1f03b'}


@pytest.fixture(autouse=True)
def _current_implementation_receipt_view(monkeypatch, tmp_path):
    # A real private receipt and pin keep the install journal bound to the
    # envelope actually checked, while every original receipt stays untouched.
    original_receipts = {work_id: installer._receipt(work_id) for work_id in RECEIPT_SHA256}
    runtime_root = tmp_path / "current-runtime"
    for relative, expected in CURRENT_CODE_SHA256.items():
        payload = io_path(ROOT / relative).read_bytes()
        assert sha256(payload).hexdigest() == expected, relative
        target = io_path(runtime_root / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    for relative, expected in CURRENT_PROJECTION_AUTHORITY_SHA256.items():
        assert sha256(io_path(ROOT / relative).read_bytes()).hexdigest() == expected, relative
    pins = {}
    for work_id, original in original_receipts.items():
        expected = {
            "build/tools/stage_lib040_augustine_division.py",
            "ocd_kernel/projection/categories/native_documents.py",
            "ocd_kernel/projection/categories/prose.py",
            "ocd_kernel/projection/native_content.py",
        }
        if work_id in installer.SELECTED_WORKS:
            expected.update({"ocd_kernel/projection/categories/lib040_augustine_selected.py",
                             "ocd_kernel/projection/categories/sermons.py"})
        else:
            expected.update({"ocd_kernel/projection/categories/lib040_augustine_divisions.py",
                             "ocd_kernel/projection/categories/commentary.py"})
        assert set(original["code_sha256"]) == expected
        current = deepcopy(original)
        current["code_sha256"] = {relative: CURRENT_CODE_SHA256[relative] for relative in expected}
        current["projection"]["receipt_sha256"] = CURRENT_PROJECTION_RECEIPT_SHA256[work_id]
        restored = deepcopy(current)
        restored["code_sha256"] = original["code_sha256"]
        restored["projection"]["receipt_sha256"] = original["projection"]["receipt_sha256"]
        assert restored == original
        suffix = "selected-acceptance-stage" if work_id in installer.SELECTED_WORKS else "acceptance-stage"
        relative = Path("plans/2026-09-22-source-preflight") / f"lib040-{work_id}-{suffix}-20260926.json"
        original_raw = io_path(ROOT / relative).read_bytes()
        assert sha256(original_raw).hexdigest() == RECEIPT_SHA256[work_id]
        assert json.loads(original_raw) == original
        payload = (json.dumps(current, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        target = io_path(runtime_root / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        pins[work_id] = sha256(payload).hexdigest()
        assert io_path(ROOT / relative).read_bytes() == original_raw
    monkeypatch.setattr(installer, "ROOT", runtime_root)
    for work_id, digest in pins.items():
        monkeypatch.setitem(RECEIPT_SHA256, work_id, digest)
    for work_id, original in original_receipts.items():
        current = installer._receipt(work_id)
        current["code_sha256"] = original["code_sha256"]
        current["projection"]["receipt_sha256"] = original["projection"]["receipt_sha256"]
        assert current == original


def _fixture_root(tmp_path: Path, work_id: str) -> Path:
    root = tmp_path / work_id
    root.mkdir()
    (root / FIXTURE_MARKER).write_text("isolated fixture\n", encoding="utf-8")
    receipt = _receipt(work_id)
    work = Path("library/works") / work_id
    stage = Path(receipt["stage_root"])
    for relative in receipt["external"]:
        target = io_path(root / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(io_path(stage / relative), target)
    for relative in receipt["before"]:
        target = io_path(root / work / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        origin = (BEFORE_FIXTURES / f"lib040-child-install-preimage-{work_id}.{relative}"
                  if relative in {"state.json", "work.json"} else ROOT / work / relative)
        assert sha256(io_path(origin).read_bytes()).hexdigest() == receipt["before"][relative]
        shutil.copy2(io_path(origin), target)
    assert _files(root / work) == receipt["before"]
    return root


@pytest.mark.parametrize("work_id,rows", [
    ("augustine-soliloquies", 4),
    ("augustine-sermon-on-the-mount", 3),
    ("augustine-tractates-on-john", 125),
    ("augustine-letters-part-1", 169),
    ("augustine-sermons-selected-lessons", 97),
    ("augustine-homilies-on-first-john", 10),
])
def test_clean_fixture_install_preserves_handoff_and_checks_rows(tmp_path: Path, work_id: str, rows: int) -> None:
    root = _fixture_root(tmp_path, work_id)
    checked = preflight(work_id, root_override=root)
    assert checked["status"] == "pass-read-only"
    result = install(work_id, root_override=root)
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == rows
    work = Path("library/works") / work_id
    assert _files(root / work) == checked["after"]
    operations = list((root / "library/.sidecar-operations").iterdir())
    assert len(operations) == 1
    operation = operations[0]
    journal = json.loads((operation / "operation.json").read_text(encoding="utf-8"))
    assert journal["phase"] == "complete"
    assert _files(operation / "previous") == checked["before"]
    handoff = Path(checked["preserved_handoff"]).relative_to(work)
    assert io_path(root / work / handoff).read_bytes() == io_path(operation / "previous" / handoff).read_bytes()


@pytest.mark.parametrize("phase", ["after-copy", "after-old-rename", "after-new-rename", "after-postcheck"])
def test_injected_failure_restores_exact_prior_generation(tmp_path: Path, phase: str) -> None:
    work_id = "augustine-soliloquies"
    root = _fixture_root(tmp_path, work_id)
    work = Path("library/works") / work_id
    before = _files(root / work)

    def fail_at(reached: str) -> None:
        if reached == phase:
            raise RuntimeError("injected " + phase)

    with pytest.raises(RuntimeError, match="injected " + phase):
        install(work_id, root_override=root, fail_at=fail_at)
    assert _files(root / work) == before
    operations = list((root / "library/.sidecar-operations").iterdir())
    assert len(operations) == 1
    journal = json.loads((operations[0] / "operation.json").read_text(encoding="utf-8"))
    assert journal["phase"] == ("failed-before-swap" if phase == "after-copy" else "rolled-back")
    assert preflight(work_id, root_override=root)["status"] == "pass-read-only"


def test_selected_receipt_pin_rejects_stale_or_tampered_receipt(monkeypatch) -> None:
    work_id = "augustine-letters-part-1"
    monkeypatch.setitem(RECEIPT_SHA256, work_id, "0" * 64)
    with pytest.raises(PipelineError, match="receipt differs from installer pin"):
        preflight(work_id)


def test_selected_retained_source_tamper_rejected(tmp_path: Path) -> None:
    work_id = "augustine-homilies-on-first-john"
    root = _fixture_root(tmp_path, work_id)
    source = root / "raw/ccel/npnf1/npnf107.xml"
    source.write_bytes(source.read_bytes() + b" ")
    with pytest.raises(PipelineError, match="external source or evidence differs"):
        preflight(work_id, root_override=root)
    assert not (root / "library/.sidecar-operations").exists()


@pytest.mark.parametrize("work_id,phase", [
    ("augustine-homilies-on-first-john", "after-copy"),
    ("augustine-sermons-selected-lessons", "after-old-rename"),
    ("augustine-homilies-on-first-john", "after-new-rename"),
    ("augustine-sermons-selected-lessons", "after-postcheck"),
])
def test_selected_injected_swap_failure_restores_prior_generation(tmp_path: Path, work_id: str, phase: str) -> None:
    root = _fixture_root(tmp_path, work_id)
    work = Path("library/works") / work_id
    before = _files(root / work)

    def fail_at(reached: str) -> None:
        if reached == phase:
            raise RuntimeError("selected injected " + phase)

    with pytest.raises(RuntimeError, match="selected injected " + phase):
        install(work_id, root_override=root, fail_at=fail_at)
    assert _files(root / work) == before
    operations = list((root / "library/.sidecar-operations").iterdir())
    assert len(operations) == 1
    journal = json.loads((operations[0] / "operation.json").read_text(encoding="utf-8"))
    assert journal["phase"] == ("failed-before-swap" if phase == "after-copy" else "rolled-back")
    assert preflight(work_id, root_override=root)["status"] == "pass-read-only"


def test_drifted_handoff_rejected(tmp_path: Path) -> None:
    work_id = "augustine-soliloquies"
    root = _fixture_root(tmp_path, work_id)
    handoff = Path(_receipt(work_id)["work_local_handoff"])
    io_path(root / handoff).write_bytes(b"changed handoff")
    with pytest.raises(PipelineError, match="generation differs"):
        preflight(work_id, root_override=root)


def test_selected_drifted_handoff_rejected(tmp_path: Path) -> None:
    work_id = "augustine-letters-part-1"
    root = _fixture_root(tmp_path, work_id)
    assert preflight(work_id, root_override=root)["status"] == "pass-read-only"
    handoff = Path(_receipt(work_id)["work_local_handoff"])
    io_path(root / handoff).write_bytes(b"changed selected handoff")
    with pytest.raises(PipelineError, match="generation differs"):
        preflight(work_id, root_override=root)


@pytest.mark.parametrize("mutation", ["receipt", "row", "source_division_binding"])
def test_current_projection_envelope_rejects_drift(tmp_path: Path, monkeypatch, mutation: str) -> None:
    work_id = "augustine-soliloquies"
    root = _fixture_root(tmp_path, work_id)
    work = Path("library/works") / work_id
    before = _files(root / work)
    actual_project = installer.project_accepted_prose

    def changed_projection(*args, **kwargs):
        result = actual_project(*args, **kwargs)
        if mutation == "receipt":
            result["receipt"]["unreviewed_runtime_claim"] = True
        elif mutation == "row":
            result["rows"][0]["text"] += " changed"
        else:
            result["receipt"]["source_division_binding"]["source_ids"][0] = "wrong-source-unit"
        return result

    monkeypatch.setattr(installer, "project_accepted_prose", changed_projection)
    with pytest.raises(PipelineError, match="projection (?:receipt )?differs"):
        preflight(work_id, root_override=root)
    assert _files(root / work) == before
    assert not (root / "library/.sidecar-operations").exists()
