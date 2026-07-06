from build.lib.layer_diff import diff_layers


def _layer(value: str) -> dict[str, str]:
    return {
        "source_raw": value,
        "normalised": value,
        "structured": value,
        "display": value,
        "source_raw_origin": "observed",
    }


def test_diff_layers_single_field_changed_and_equal():
    ops = diff_layers(
        {"commentary_text": _layer("before")},
        {"commentary_text": _layer("after")},
    )
    assert ops == [
        {
            "field_path": "commentary_text",
            "layer_a_value": "before",
            "layer_b_value": "after",
            "op": "changed",
        }
    ]
    assert diff_layers({"commentary_text": _layer("same")}, {"commentary_text": _layer("same")})[0]["op"] == "equal"


def test_diff_layers_multi_field_added_removed_content_hash_paths():
    ops = diff_layers(
        {
            "term": _layer("Aaron"),
            "alt_terms": {"0": _layer("Aharon")},
            "definition_blocks": {"aaaabbbbccccdddd": _layer("first")},
        },
        {
            "term": _layer("Aaron"),
            "definition_blocks": {"eeeeffff00001111": _layer("second")},
        },
    )
    by_path = {op["field_path"]: op for op in ops}
    assert by_path["term"]["op"] == "equal"
    assert by_path["alt_terms.0"]["op"] == "removed"
    assert by_path["definition_blocks.aaaabbbbccccdddd"]["op"] == "removed"
    assert by_path["definition_blocks.eeeeffff00001111"]["op"] == "added"
