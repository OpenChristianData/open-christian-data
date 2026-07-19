from ocd_kernel.lib.block_id import block_id


def test_block_id_is_deterministic():
    assert block_id("same text") == block_id("same text")


def test_block_id_disambiguator_suffix():
    first = block_id("duplicate", 0)
    second = block_id("duplicate", 1)
    assert not first.endswith(".0")
    assert second == f"{first}.1"
