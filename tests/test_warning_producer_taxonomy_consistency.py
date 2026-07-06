from __future__ import annotations

from build.lib.warning_producers.taxonomy_consistency import run


def _record(**meta_overrides):
    meta = {"schema_type": "commentary", "id": "sample"}
    meta.update(meta_overrides)
    return {"meta": meta, "data": []}


def test_absent_resource_type_resolves_silently() -> None:
    assert run(_record(), {"resource_type": "commentary"}, {})["warnings"] == []


def test_matching_resource_type_emits_no_warning() -> None:
    assert run(_record(resource_type="commentary"), {"resource_type": "commentary"}, {})["warnings"] == []


def test_overriding_resource_type_emits_warning() -> None:
    warnings = run(_record(resource_type="encyclopedia"), {"resource_type": "encyclopedia"}, {})["warnings"]

    assert len(warnings) == 1
    assert warnings[0]["code"] == "resource_type_overrides_default"
    assert warnings[0]["evidence"] == {"declared": "encyclopedia", "schema_default": "commentary"}
