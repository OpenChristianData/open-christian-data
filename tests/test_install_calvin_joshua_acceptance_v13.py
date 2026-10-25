"""The retained installer must expose its guarded CLI without applying changes."""

import subprocess
import sys


def test_help_exposes_reviewed_preflight_requirements():
    result = subprocess.run(
        [sys.executable, "-m", "build.tools.install_calvin_joshua_acceptance_v13", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    for option in ("--library-root", "--stage-root", "--apply", "--preflight-receipt", "--preflight-sha256"):
        assert option in result.stdout
