"""Focused coverage of the conservative lead-repair CLI boundary."""

import json
from pathlib import Path

import pytest

from build.tools import repair_manifest_leads as cli
from ocd_kernel.library._common import PipelineError

ROOT = Path("selected-root")


@pytest.mark.parametrize("apply", [False, True])
def test_preview_and_apply_use_the_selected_root(monkeypatch, capsys, apply):
    plan = {"conservation": {"status": "preview"}}
    calls = []
    monkeypatch.setattr(cli, "plan_lead_repair", lambda root: calls.append(("plan", root)) or plan)
    monkeypatch.setattr(cli, "apply_lead_repair", lambda root, value: calls.append(("apply", root, value)) or {"status": "applied"})
    args = ["--root", str(ROOT)] + (["--apply"] if apply else [])
    assert cli.main(args) == 0
    assert calls == [("plan", ROOT)] + ([("apply", ROOT, plan)] if apply else [])
    assert json.loads(capsys.readouterr().out) == {"applied": apply, "status": "applied" if apply else "preview"}


@pytest.mark.parametrize("error", [PipelineError("invalid witness"), OSError("unreadable witness"), UnicodeError("invalid text")])
def test_expected_failure_returns_a_blocked_result(monkeypatch, capsys, error):
    def fail(root):
        raise error
    monkeypatch.setattr(cli, "plan_lead_repair", fail)
    assert cli.main(["--root", str(ROOT)]) == 1
    assert json.loads(capsys.readouterr().out) == {"status": "blocked", "reason": str(error)}


def test_unexpected_failure_is_not_hidden(monkeypatch):
    def fail(root):
        raise RuntimeError("unexpected failure")
    monkeypatch.setattr(cli, "plan_lead_repair", fail)
    with pytest.raises(RuntimeError, match="unexpected failure"):
        cli.main(["--root", str(ROOT)])
