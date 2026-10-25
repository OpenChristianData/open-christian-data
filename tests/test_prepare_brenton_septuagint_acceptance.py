"""Preparation-only regression for the frozen Brenton acceptance handoff."""

from __future__ import annotations

import hashlib
import json

from build.tools.prepare_brenton_septuagint_acceptance import (
    NEUTRAL_ANA,
    NEUTRAL_PUBLISHER,
    ORIGINAL_SHA,
    PREDECESSOR_ANA,
    PREDECESSOR_PUBLISHER,
    ROOT,
    prepare,
)
from ocd_kernel.tei.acceptance import validate_acceptance


def test_brenton_handoff_is_frozen_pending_and_leaves_canonical_work_unchanged(tmp_path_factory, monkeypatch):
    canonical = ROOT / "library/works/brenton-septuagint"
    before = {
        path.relative_to(canonical).as_posix(): path.read_bytes()
        for path in canonical.rglob("*")
        if path.is_file()
    }
    # Keep complete-work paths short while giving this test its own namespace.
    stage_parent = tmp_path_factory.mktemp("b")
    stage = stage_parent / "b"
    historical = _historical_brenton_root(stage_parent / "br", monkeypatch, stage)
    acceptance = prepare(historical, stage)
    record = validate_acceptance(acceptance, root=stage)
    evidence = stage / "library/works/brenton-septuagint/integration/brenton-electronic-whole-work-v1"
    original = (evidence / "original-package/content.tei.xml").read_bytes()
    derived = (evidence / "candidate.tei.xml").read_bytes()
    predecessor = (evidence / "inputs/held-predecessor-candidate.tei.xml").read_bytes()
    receipt = json.loads((stage / "BRENTON_HANDOFF_RECEIPT.json").read_bytes())
    notice = (stage / "library/works/brenton-septuagint/SOURCE_NOTICE.md").read_text(encoding="utf-8")

    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    assert original.split(b"</teiHeader>", 1)[1] == derived.split(b"</teiHeader>", 1)[1]
    assert predecessor.replace(PREDECESSOR_ANA, NEUTRAL_ANA, 1).replace(
        PREDECESSOR_PUBLISHER, NEUTRAL_PUBLISHER, 1
    ) == derived
    assert PREDECESSOR_ANA not in derived and PREDECESSOR_PUBLISHER not in derived
    assert derived.count(NEUTRAL_ANA) == 1 and derived.count(NEUTRAL_PUBLISHER) == 1
    assert derived.count(b"nonaccepted") == 1  # historical source-generation revision only
    assert record["promotion"]["status"] == "pending"
    assert record["decision"]["agent_assessment"]["status"] == "unassessed"
    assert record["decision"]["human_decision"]["status"] == "not-recorded"
    assert record["review"]["coverage"]["status"] == "partial"
    assert "electronic-witness/visual/current-cvw" in record["review"]["coverage"]["unreviewed"]
    assert not (stage / "library/works/brenton-septuagint/forms/brenton-septuagint-retained-en/editions/brenton-septuagint-electronic/master.tei.xml").exists()
    assert receipt["status"] == "frozen-pending-parent-review"
    assert receipt["promotion_performed"] is False
    assert receipt["installation_performed"] is False
    assert receipt["predecessor"]["status"] == "held-no-accept-promote-install"
    assert "Lancelot Charles Lee Brenton" in notice
    assert "Public Domain" in notice
    assert "applicable law" in notice
    assert all((canonical / name).read_bytes() == content for name, content in before.items())


def _historical_brenton_root(root, monkeypatch, stage):
    """Mirror the exact preacceptance source-rebind generation for this handoff."""
    from pathlib import Path
    import shutil
    from build.tools import prepare_brenton_septuagint_acceptance as owner
    from ocd_kernel.lib.storage_topology import resolve_repo_path

    original_raw = (ROOT / owner.REBIND / "manifest.json").read_bytes()
    assert hashlib.sha256(original_raw).hexdigest() == "db4c6ffd38a69544630b09f58474f00a72b2abd0600111fb85d11feaef67e7bd"
    original = json.loads(original_raw)
    assert len(original["after"]) == 4
    root.mkdir()
    records = {}
    for relative, expected in original["after"].items():
        source = ROOT / owner.REBIND / owner.WORK / relative
        raw = source.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected
        target = root / owner.WORK / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        records[relative] = json.loads(raw)
    assert {p.relative_to(root / owner.WORK).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (root / owner.WORK).rglob("*") if p.is_file()} == original["after"]
    assert records["state.json"]["targets"][-1]["stage"] == "review"
    references = {owner.CONFIG, owner.REBIND / "manifest.json", owner.REBIND / "apply-receipt.json",
                  owner.PREDECESSOR / "BRENTON_HANDOFF_RECEIPT.json",
                  owner.PREDECESSOR / owner.EDITION / "acceptance.json",
                  owner.PREDECESSOR / owner.WORK / "integration/brenton-electronic-whole-work-v1/candidate.tei.xml"}
    for name in ("work.json", "state.json"):
        record = records[name]
        queues = [record.get("evidence", [])]
        queues.extend(target.get("evidence", []) for target in record.get("targets", []))
        for values in queues:
            for reference in values:
                relative = Path(reference.split("#", 1)[0])
                assert not relative.is_absolute() and ".." not in relative.parts
                references.add(relative)
    shutil.copytree(resolve_repo_path(ROOT, owner.RAW.as_posix()), root / owner.RAW)
    for relative in sorted(references):
        raw = resolve_repo_path(ROOT, relative.as_posix()).read_bytes()
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert target.read_bytes() == raw
        else:
            target.write_bytes(raw)
    assert {p.relative_to(root / owner.WORK).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (root / owner.WORK).rglob("*") if p.is_file()} == original["after"]
    # Run the real current producer module from its owning checkout.  Its
    # explicit repository-root argument still points at the historical mirror.
    from types import SimpleNamespace
    import sys
    current_run = owner.subprocess.run
    def current_cli(command, **kwargs):
        assert command[:3] == [sys.executable, "-m", "build.tei.brenton_septuagint"]
        assert command[command.index("--repository-root") + 1] == str(stage)
        assert kwargs["cwd"] == root and kwargs["check"] is True
        return current_run(command, **(kwargs | {"cwd": ROOT}))
    monkeypatch.setattr(owner, "subprocess", SimpleNamespace(run=current_cli))
    return root
