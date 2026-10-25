"""The retired OCD entry point must stop without running OCR production."""
from build.tools import probe_nsh_scandata


def test_relocated_diagnostic_stops_with_actionable_destination(capsys):
    assert probe_nsh_scandata.main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "From that repository run:" in captured.err
    assert "EzraOCR" in captured.err
    assert "py -3 ezra/tools/probe_nsh_scandata.py [volumes]" in captured.err
