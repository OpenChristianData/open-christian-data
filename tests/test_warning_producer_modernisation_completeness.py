from __future__ import annotations

import copy


def _record() -> dict:
    return {
        "meta": {
            "id": "sample/work/edition/modernised/vol-01",
            "schema_type": "modernised_record",
            "language": "en",
            "modernisation_ruleset_version": "en@1.0.0",
            "paired_with": "sample/work/edition/original/vol-01",
        },
        "blocks": [
            {
                "block_id": "b1",
                "language_segments": [],
                "original_text": "He hath authority.",
                "modern_text": "He has authority.",
                "modernisations": [
                    {
                        "rule_id": "en.archaic_verb_eth_to_s_irregular",
                        "rule_version": "en@1.0.0",
                        "span": {"start_token": 1, "end_token": 2},
                        "original": "hath",
                        "modern": "has",
                    }
                ],
            }
        ],
    }


def _codes(output: dict) -> set[str]:
    return {warning["code"] for warning in output["warnings"]}


def test_mod_stale_ruleset() -> None:
    from build.lib.warning_producers import modernisation_completeness

    stale = _record()
    clean = copy.deepcopy(stale)
    clean["meta"]["modernisation_ruleset_version"] = "en@1.1.0"

    stale_output = modernisation_completeness.run(
        stale,
        {"resource_id": "sample", "ruleset_versions": {"en": "en@1.1.0"}},
        {},
    )
    clean_output = modernisation_completeness.run(
        clean,
        {"resource_id": "sample", "ruleset_versions": {"en": "en@1.1.0"}},
        {},
    )

    assert "MOD_STALE_RULESET" in _codes(stale_output)
    assert "MOD_STALE_RULESET" not in _codes(clean_output)


def test_mod_span_inconsistent() -> None:
    from build.lib.warning_producers import modernisation_completeness

    broken = _record()
    broken["blocks"][0]["modernisations"][0]["original"] = "has"
    clean = _record()

    assert "MOD_SPAN_INCONSISTENT" in _codes(modernisation_completeness.run(broken, {"resource_id": "sample"}, {}))
    assert "MOD_SPAN_INCONSISTENT" not in _codes(modernisation_completeness.run(clean, {"resource_id": "sample"}, {}))


def test_mod_translit_inconsistent() -> None:
    from build.lib.warning_producers import modernisation_completeness

    broken = _record()
    broken["blocks"][0]["original_text"] = "The word agape endureth."
    broken["blocks"][0]["modern_text"] = "The word agape endures."
    broken["blocks"][0]["language_segments"] = [
        {
            "span": {"start_token": 2, "end_token": 3},
            "language": "grc",
            "original_script": "αγαπη",
            "transliteration": "agape",
            "transliterated_from": "grc",
        }
    ]
    broken["blocks"][0]["modernisations"] = [
        {
            "rule_id": "en.archaic_verb_eth_to_s_regular",
            "rule_version": "en@1.0.0",
            "span": {"start_token": 2, "end_token": 3},
            "original": "agape",
            "modern": "agape",
        }
    ]
    clean = copy.deepcopy(broken)
    clean["blocks"][0]["modernisations"][0]["span"] = {"start_token": 3, "end_token": 4}
    clean["blocks"][0]["modernisations"][0]["original"] = "endureth"
    clean["blocks"][0]["modernisations"][0]["modern"] = "endures"

    assert "MOD_TRANSLIT_INCONSISTENT" in _codes(
        modernisation_completeness.run(broken, {"resource_id": "sample"}, {})
    )
    assert "MOD_TRANSLIT_INCONSISTENT" not in _codes(
        modernisation_completeness.run(clean, {"resource_id": "sample"}, {})
    )


def test_mod_rule_gone() -> None:
    from build.lib.warning_producers import modernisation_completeness

    broken = _record()
    broken["blocks"][0]["modernisations"][0]["rule_id"] = "en.rule_removed"
    clean = _record()

    assert "MOD_RULE_GONE" in _codes(modernisation_completeness.run(broken, {"resource_id": "sample"}, {}))
    assert "MOD_RULE_GONE" not in _codes(modernisation_completeness.run(clean, {"resource_id": "sample"}, {}))


def test_mod_delta_unreconstructable() -> None:
    from build.lib.warning_producers import modernisation_completeness

    broken = _record()
    broken["blocks"][0]["modern_text"] = "He keeps authority."
    clean = _record()

    assert "MOD_DELTA_UNRECONSTRUCTABLE" in _codes(
        modernisation_completeness.run(broken, {"resource_id": "sample"}, {})
    )
    assert "MOD_DELTA_UNRECONSTRUCTABLE" not in _codes(
        modernisation_completeness.run(clean, {"resource_id": "sample"}, {})
    )
