from build.lib.text_layers import build_reference_layers, definition_block_ids
from build.parsers import ia_schaff_herzog


def test_definition_block_keys_survive_inserted_block():
    original = ["first block", "second block"]
    inserted = ["new block", *original]

    original_keys = definition_block_ids(original)
    inserted_keys = definition_block_ids(inserted)

    assert original_keys[0] in inserted_keys
    assert original_keys[1] in inserted_keys
    assert inserted_keys[1:] == original_keys


def test_schaff_entry_builder_uses_content_hash_layer_keys():
    entry = ia_schaff_herzog.build_entry(
        {
            "term": "TEST ENTRY",
            "definition_blocks": ["Normalised block"],
            "source_raw_definition_blocks": ["Normalised  block"],
            "vol_num": 3,
        },
        set(),
        emit_layers=True,
    )

    block_layers = entry["layers"]["definition_blocks"]
    expected_key = definition_block_ids(["Normalised block"])[0]
    assert list(block_layers) == [expected_key]
    assert block_layers[expected_key]["source_raw_origin"] == "observed"


def test_alt_terms_are_position_keyed():
    layers = build_reference_layers(
        term="Term",
        alt_terms=["dup", "dup"],
        definition_blocks=["body"],
        source_raw_alt_terms=["dup ", " dup"],
    )
    assert sorted(layers["alt_terms"]) == ["0", "1"]
