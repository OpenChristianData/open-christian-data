"""Public ref updates retain every identity check; empty pushes do no work."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.fixture
def run_hook(tmp_path):
    hook = Path(__file__).resolve().parents[1] / ".githooks/pre-push"
    if not hook.is_file():
        pytest.skip("The private repository owns the publication hook")
    git = shutil.which("git")
    bundled = Path(git).resolve().parents[1] / "bin/bash.exe" if git else None
    bash = str(bundled) if bundled and bundled.is_file() else shutil.which("bash")
    assert bash, "Git Bash is required to verify the publication hook"
    log = tmp_path / "calls.txt"
    wrapper = r'''git() {
    printf '%s\n' "$*" >> "$HOOK_CALL_LOG"
    case "$1" in
        rev-list) printf '%s\n' "$HOOK_NEW" ;;
        grep)
            if [[ "$HOOK_CASE" = content && "$*" = *"$HOOK_MARKER"* ]]; then
                printf '%s\n' content.txt
            else return 1; fi ;;
        ls-tree)
            if [[ "$HOOK_CASE" = filename ]]; then printf '%s.txt\n' "$HOOK_MARKER"
            else printf '%s\n' safe.txt; fi ;;
        log)
            if [[ "$HOOK_CASE" = message ]]; then printf '%s\n' "$HOOK_MARKER"
            else printf '%s\n' 'Public update'; fi ;;
        *) return 99 ;;
    esac
}
export -f git
exec bash "$1" "$2" "$3"
'''
    old, new = "a" * 40, "b" * 40

    def invoke(mode="clean", *, protocol=None, remote="public", url="https://github.com/OpenChristianData/open-christian-data.git"):
        environment = {**os.environ, "HOOK_CALL_LOG": log.as_posix(),
                       "HOOK_CASE": mode, "HOOK_MARKER": "Based" + "GPT", "HOOK_NEW": new}
        if protocol is None:
            protocol = f"refs/heads/main {new} refs/heads/main {old}\n"
        result = subprocess.run([bash, "-c", wrapper, "test-pre-push", hook.as_posix(), remote, url],
                                input=protocol.encode(), capture_output=True,
                                env=environment, check=False, timeout=15)
        result.stdout = result.stdout.decode()
        result.stderr = result.stderr.decode()
        calls = log.read_text() if log.exists() else ""
        return result, calls
    return invoke, old, new


def test_up_to_date_public_push_does_not_scan_private_head(run_hook):
    invoke, _, _ = run_hook
    result, calls = invoke(protocol="")
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == ""


def test_public_update_scans_exact_commit_range_content_names_and_messages(run_hook):
    invoke, old, new = run_hook
    result, calls = invoke()
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"rev-list {old}..{new}" in calls
    assert "grep " in calls and "ls-tree " in calls and "log " in calls
    assert "HEAD" not in calls


@pytest.mark.parametrize("mode", ("content", "filename", "message"))
def test_public_update_rejects_each_identity_surface(run_hook, mode):
    invoke, _, _ = run_hook
    result, calls = invoke(mode)
    assert result.returncode == 1
    assert "PRE-PUSH BLOCKED" in result.stdout
    assert "rev-list " in calls


@pytest.mark.parametrize("branch,new", (("refs/tags/v2", "b" * 40), ("refs/heads/main", "0" * 40)))
def test_public_update_rejects_other_refs_and_deletion(run_hook, branch, new):
    invoke, old, _ = run_hook
    result, calls = invoke(protocol=f"refs/heads/main {new} {branch} {old}\n")
    assert result.returncode == 1 and "PRE-PUSH BLOCKED" in result.stdout
    assert calls == ""


def test_public_remote_mismatch_remains_blocked(run_hook):
    invoke, _, _ = run_hook
    result, calls = invoke(url="https://example.invalid/wrong-repository.git")
    assert result.returncode == 1 and "PRE-PUSH BLOCKED" in result.stdout
    assert calls == ""
