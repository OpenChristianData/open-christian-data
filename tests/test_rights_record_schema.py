"""Scoped labels must not silently broaden public-domain or license claims."""

import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/v2/rights-record.schema.json").read_text(encoding="utf-8"))
EXAMPLE = json.loads((ROOT / "docs/examples/rights-record.json").read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker())


def test_public_domain_example_and_unassessed_record():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    VALIDATOR.validate(EXAMPLE)
    record = deepcopy(EXAMPLE)
    record.update(rights_status="not-assessed", jurisdictions=[], evidence=[], basis='not-assessed')
    del record["assessed_by"], record["assessed_on"]
    VALIDATOR.validate(record)


@pytest.mark.parametrize("license_id", ["CC0-1.0", "CC-BY-4.0", "LicenseRef-specific-permission"])
def test_license_or_dedication_is_distinct_from_expired_copyright(license_id):
    record = deepcopy(EXAMPLE)
    record.update(rights_status="licensed", jurisdictions=["worldwide"], license_ids=[license_id], basis='license')
    VALIDATOR.validate(record)


@pytest.mark.parametrize("status", ["mixed", "restricted", "undetermined"])
def test_other_assessed_outcomes_keep_evidence_and_identity(status):
    VALIDATOR.validate(dict(EXAMPLE, rights_status=status))


@pytest.mark.parametrize("change", [
    {"rights_status": "probably-public-domain"},
    {"jurisdictions": []},
    {"jurisdictions": ["United States"]},
    {"license_ids": ["CC0-1.0"]},
    {"rights_status": "licensed", "license_ids": []},
    {"rights_status": "restricted", "jurisdictions": []},
    {"rights_status": "not-assessed"},
    {"evidence": []},
    {"assessed_on": "2026-10-14T09:00:00+11:00"},
    {"assessed_on": "2026-13-40"},
    {"public_upload_approved": False},
])
def test_rejects_ambiguous_labels_and_broadened_claims(change):
    record = deepcopy(EXAMPLE)
    record.update(change)
    with pytest.raises(jsonschema.ValidationError):
        VALIDATOR.validate(record)


def test_exact_query_distinguishes_scope_territory_and_license():
    original = dict(EXAMPLE, scope="original-text")
    australian = dict(EXAMPLE, jurisdictions=["AU"])
    licensed = dict(EXAMPLE, rights_status="licensed", license_ids=["CC-BY-4.0"], basis='license')
    worldwide = dict(EXAMPLE, edition_id="worldwide-example", jurisdictions=["worldwide"])
    records = [EXAMPLE, original, australian, licensed, worldwide]
    for record in records:
        VALIDATOR.validate(record)
    selected = [record["edition_id"] for record in records
                if record["scope"] == "selected-text"
                and record["rights_status"] == "public-domain"
                and {"US", "worldwide"}.intersection(record["jurisdictions"])]
    assert selected == [EXAMPLE["edition_id"], "worldwide-example"]
