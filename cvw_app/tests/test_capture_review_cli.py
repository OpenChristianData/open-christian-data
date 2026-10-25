import io
import json
import sys
from pathlib import Path

import pytest

from cvw_app import capture_review


@pytest.mark.parametrize("command", ["capture", "export"])
def test_main_emits_lossless_json_on_windows_legacy_stdout(monkeypatch, command):
    unicode_value = "Greek λόγος, accented café, and non-BMP 𝔓"
    if command == "capture":
        expected = {"targets": {"left": {"literal": unicode_value}}}
        monkeypatch.setattr(capture_review, "capture", lambda **kwargs: expected)
        arguments = [
            "capture", "--receipt", "receipt.json", "--url", "http://localhost/review",
            "--output", "capture-output",
        ]
    else:
        destination = Path(unicode_value)
        expected = {"exported_to": str(destination)}
        monkeypatch.setattr(capture_review, "export_bundle", lambda *args: destination)
        arguments = ["export", "--source", "bundle", "--output", str(destination)]

    monkeypatch.setattr(sys, "argv", ["capture_review", *arguments])
    buffer = io.BytesIO()
    with io.TextIOWrapper(buffer, encoding="cp1252", errors="strict") as stdout:
        monkeypatch.setattr(sys, "stdout", stdout)
        capture_review.main()
        stdout.flush()
        output = buffer.getvalue()

    assert json.loads(output.decode("cp1252")) == expected
    assert output.endswith(b"\n")
