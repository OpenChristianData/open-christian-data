"""Prove standard accepted admission of the exact installed Carey generation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.categories import native_documents, prose, sermons


ROOT = Path(__file__).resolve().parents[1]
EDITION = ROOT / "library/works/carey-enquiry/forms/carey-enquiry-retained-text/editions/carey-enquiry-pg11449-electronic-witness"
ACCEPTANCE = EDITION / "acceptance.json"
MASTER_HASH = "74ea4ce79d468922d968de2ee5fe11a541784b7646ad8185b79f3bcc12468c6f"


def nodes(value):
    if isinstance(value, list):
        for child in value:
            yield from nodes(child)
    elif isinstance(value, dict):
        yield value
        yield from nodes(value.get("content", []))


def test_standard_accepted_carey_projection_and_producer_disabled_verifier(monkeypatch):
    before = {name:hashlib.sha256(io_path(EDITION / name).read_bytes()).hexdigest()
              for name in ("master.tei.xml", "acceptance.json")}
    assert before["master.tei.xml"] == MASTER_HASH
    assert before["acceptance.json"] == "82de0f67123ac73aad56adb8b3060a024792a0cb905dab4725044ab4466af133"
    result = prose.project_accepted_prose(ROOT, acceptance_path=ACCEPTANCE)
    assert len(result["rows"]) == 1
    receipt = result["receipt"]
    assert receipt["projection_profile"] == native_documents.CAREY_GROUPED_TABLE_PROFILE
    assert receipt["master_sha256"] == MASTER_HASH
    assert receipt["anchors"][0]["unit_id"].startswith("/TEI/text/group/text/body/")
    tree = list(nodes(result["rows"][0]["structure"]))
    tables = [node for node in tree if node.get("kind") == "table"]
    assert [(node["attributes"]["source_row_count"], node["attributes"]["source_column_count"])
            for node in tables] == [("112", "5"), ("100", "5"), ("42", "5"), ("98", "6")]
    assert sum(node.get("kind") == "table-row" and "source_role" in node.get("attributes", {}) for node in tree) == 352
    assert sum(node.get("kind") == "table-cell" and "number" in node.get("attributes", {}) for node in tree) == 1536
    assert sum(node.get("kind") == "line-break" and node.get("attributes", {}).get("type") == "source-blank-line"
               for node in tree) == 250
    canonical_rows = json.dumps(result["rows"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    assert hashlib.sha256(canonical_rows).hexdigest() == receipt["output_sha256"]

    def forbidden_producer(*args, **kwargs):
        raise AssertionError("Accepted independent verification invoked the producer")

    monkeypatch.setattr(native_documents, "project_document", forbidden_producer)
    assert prose.verify_accepted_prose(ROOT, acceptance_path=ACCEPTANCE, rows=result["rows"], receipt=receipt) == []
    for name, digest in before.items():
        assert hashlib.sha256(io_path(EDITION / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("mutation", [
    "work", "form", "edition", "acquisition", "master", "accounting_path", "accounting_bytes", "accounting_hash", "profile",
])
def test_standard_accepted_route_rejects_mismatched_carey_binding(monkeypatch, mutation):
    accepted = json.loads(io_path(ACCEPTANCE).read_bytes())
    context = {"root":ROOT, "accepted":deepcopy(accepted),
               "identity":{key:accepted["identity"][key] for key in ("work_id", "textual_form_id", "edition_id")},
               "authority":{"master":{"sha256":MASTER_HASH}}}
    if mutation in {"work", "form", "edition"}:
        field = {"work":"work_id", "form":"textual_form_id", "edition":"edition_id"}[mutation]
        context["identity"][field] = "other"
    elif mutation == "acquisition":
        context["accepted"]["identity"]["acquisition_id"] = "other"
    elif mutation == "master":
        context["authority"]["master"]["sha256"] = "0" * 64
    elif mutation.startswith("accounting_"):
        field = {"accounting_path":"path", "accounting_bytes":"bytes", "accounting_hash":"sha256"}[mutation]
        context["accepted"]["source"]["accounting"][field] = 1 if field == "bytes" else "other"
    monkeypatch.setattr(sermons, "_accepted_context", lambda *args, **kwargs:context)
    # Synthetic invalid bindings must reach Carey's guard; the installed test
    # above exercises the real accounting/profile reader and verifier.
    monkeypatch.setattr(prose, "_accepted_projection_profile", lambda *args:None)
    if mutation == "profile":
        monkeypatch.setattr(prose, "_accepted_projection_profile", lambda *args:"other-profile")
    with pytest.raises(PipelineError, match="Carey accepted.*differs"):
        prose.project_accepted_prose(ROOT, acceptance_path=ACCEPTANCE)
    errors = prose.verify_accepted_prose(ROOT, acceptance_path=ACCEPTANCE, rows=[], receipt={})
    assert len(errors) == 1 and "Carey accepted" in errors[0] and "differs" in errors[0]


def test_other_work_context_keeps_existing_profile_route():
    context = {"identity":{"work_id":"other"}, "accepted":{"identity":{"work_id":"other"}}}
    assert prose._carey_accepted_profile(ROOT, context) is None
