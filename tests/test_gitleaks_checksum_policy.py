"""Checksum exceptions retain detection of credentials in the same records."""

from hashlib import sha256
import ast
import json
from pathlib import Path
import shutil
import subprocess
import tomllib

import pytest

from build.tools.pre_commit_pytest import _pytest_environment


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".gitleaks.toml"
RECORD = "library/works/calvins-institutes/publication/completion.json"
SOURCE_RECORD = "plans/2026-10-02-v1-public-information-drafts/artifacts/library-completion-reconciliation-20261023/ccel-four/ccel_native_emitter.py"


def test_checksum_policy_preserves_all_default_rules_and_requires_path_and_match():
    config = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    assert config["extend"] == {"useDefault": True}
    assert len(config["rules"]) == 1
    rule = config["rules"][0]
    assert set(rule) == {"id", "allowlists"}
    assert rule["id"] == "generic-api-key"
    assert rule["allowlists"][0]["condition"] == "AND"
    assert rule["allowlists"][0]["regexTarget"] == "match"


@pytest.mark.parametrize("case", ["checksum", "credential", "provider-token", "other-path",
    *[pytest.param(case, marks=pytest.mark.requires_local_artifacts) for case in
      ("source-checksum", "source-credential", "source-provider-token", "source-other-path")]])
def test_real_scanner_allows_only_record_checksums(tmp_path, case):
    scanner = shutil.which("gitleaks") or shutil.which("gitleaks.exe")
    if scanner is None:
        pytest.skip("Gitleaks executable is required for scanner integration")
    repo = tmp_path / "repo"
    repo.mkdir()
    digest = sha256(b"synthetic scanner regression fixture").hexdigest()
    content = {"oracle-api-repair-binding.json": digest}
    if case == "credential":
        content["api_key"] = digest
    elif case == "provider-token":
        content["api_key"] = "gh" + "p_" + digest[:36]
    if case.startswith("source-"):
        tree = ast.parse((ROOT / SOURCE_RECORD).read_bytes())
        values = next(ast.literal_eval(node.value) for node in tree.body
                      if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                      and node.targets[0].id == "KNOWN_SOURCES")
        content = {"smith-christians-secret-happy-life": values["smith-christians-secret-happy-life"]}
        if case == "source-credential":
            content["api_key"] = digest
        elif case == "source-provider-token":
            content["api_key"] = "gh" + "p_" + digest[:36]
    target = repo / ("other.json" if case in {"other-path", "source-other-path"}
                     else SOURCE_RECORD if case.startswith("source-") else RECORD)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(content), encoding="utf-8")
    environment = _pytest_environment()
    for command in (["git", "init", "-q"], ["git", "add", "."]):
        subprocess.run(command, cwd=repo, env=environment, check=True, capture_output=True)
    report = tmp_path / "findings.json"
    result = subprocess.run(
        [scanner, "protect", "--staged", "--config", str(CONFIG), "--redact",
         "--no-banner", "--report-format", "json", "--report-path", str(report)],
        cwd=repo, env=environment, check=False, capture_output=True, text=True,
    )
    allowed = case in {"checksum", "source-checksum"}
    assert result.returncode == (0 if allowed else 1), result.stderr
    findings = json.loads(report.read_text(encoding="utf-8"))
    if allowed:
        assert findings == []
    elif case in {"provider-token", "source-provider-token"}:
        assert any(item["RuleID"] == "github-pat" for item in findings)
    else:
        assert any(item["RuleID"] == "generic-api-key" for item in findings)
