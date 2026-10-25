"""Runtime identity for unit tests replaying frozen Python 3.14.7 transactions.

Only the version label is supplied by the fixture. Source oracles and installer
checks still run; this does not produce current-runtime acceptance evidence.
"""
import platform

import pytest


@pytest.fixture
def frozen_python_report_runtime(monkeypatch):
    monkeypatch.setattr(platform, "python_version", lambda: "3.14.7")
