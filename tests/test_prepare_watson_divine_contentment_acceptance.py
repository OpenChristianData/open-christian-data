"""Focused handoff checks for Watson Contentment's present retained source."""

import hashlib
import json

import pytest

from build.tools import prepare_watson_divine_contentment_acceptance as helper
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import promote_accepted_master, validate_acceptance


def test_historical_preparer_fails_closed_after_code_closure_change(tmp_path_factory):
    original_manifest = (helper.ROOT / helper.MANIFEST).read_bytes()
    stage = tmp_path_factory.mktemp("h") / "s"
    with pytest.raises(PipelineError):
        helper.prepare(helper.ROOT, stage)
    assert (helper.ROOT / helper.MANIFEST).read_bytes() == original_manifest


def test_changed_visual_frame_fails_before_staging(tmp_path, monkeypatch):
    original_read = helper._read

    def changed_frame(path, expected=None):
        if path.name == "frame.png" and path.parent.name == "cvw-capture-opening-v5":
            return original_read(path, "0" * 64)
        return original_read(path, expected)

    monkeypatch.setattr(helper, "_read", changed_frame)
    stage = tmp_path / "contentment-stage"
    with pytest.raises(PipelineError, match="SHA-256 mismatch"):
        helper.prepare(helper.ROOT, stage)
    assert not stage.exists()


def test_changed_source_gap_fails_before_staging(tmp_path, monkeypatch):
    original_json = helper._json

    def changed_gap(content, label):
        value = original_json(content, label)
        if label == "source accountability":
            value["source_completeness_gap"]["absent_native_ids"] = ["ix"]
        return value

    monkeypatch.setattr(helper, "_json", changed_gap)
    stage = tmp_path / "contentment-stage"
    with pytest.raises(PipelineError, match="source gap"):
        helper.prepare(helper.ROOT, stage)
    assert not stage.exists()
