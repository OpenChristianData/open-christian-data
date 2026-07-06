from build.lib.text_layers import (
    assert_surface_field_invariant,
    build_reference_layers,
    definition_block_ids,
)


def test_reference_layers_key_definition_blocks_by_structured_blocks():
    layers = build_reference_layers(
        term="Term",
        definition_blocks=["A"],
        normalised_blocks=["a"],
    )
    expected_key = definition_block_ids(["A"])[0]

    assert list(layers["definition_blocks"]) == [expected_key]
    assert_surface_field_invariant(
        {
            "entry_id": "test.entry",
            "term": "Term",
            "alt_terms": [],
            "definition_blocks": ["A"],
            "layers": layers,
        },
        text_layer_shape="multi_field",
    )
