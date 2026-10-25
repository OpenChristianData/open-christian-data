import pytest

from build.tools.census_newadvent_identities import inventory
from tests.test_census_newadvent_sources import BASE, cohort


def test_literal_fields_keep_duplicates_and_do_not_infer_volume(tmp_path):
    source = cohort(tmp_path, '<h1>Article</h1><span id="mlawork">The Catholic Encyclopedia.</span><span id="mlavolume">Vol. 3.</span><span id="mlavolume">Other source statement</span>', BASE + "01001a.htm")
    result = inventory([source])
    page = result["source_pages"][0]
    assert page["source_shape"] == "article-shaped-page-with-citation"
    assert page["duplicate_field_ids"] == ["mlavolume"]
    assert result["literal_volume_statement_counts"] == {"Other source statement": 1, "Vol. 3.": 1}
    assert result["metadata_adopted"] is False
    with pytest.raises(ValueError, match="Duplicate retained"):
        inventory([source, source])


def test_uncited_history_shape_is_not_fabricated_as_an_article_volume(tmp_path):
    source = cohort(tmp_path, '<h1>History</h1><p>Source account</p>', BASE + "00001a.htm")
    result = inventory([source])
    assert result["uncited_article_shaped_urls"] == [BASE + "00001a.htm"]
    assert result["literal_volume_statement_counts"] == {}


def test_readable_features_are_censused_even_when_images_are_unretained(tmp_path):
    source = cohort(tmp_path, '<div id="springfield2"><img src="missing.png"><greek>word</greek><font color="#cc3333">Head</font></div><div id="ogdenville">Footer</div><font color="blue">Navigation</font>', BASE + "01001a.htm")
    result = inventory([source])
    assert result["readable_element_counts"]["greek"] == 1
    assert result["readable_presentation_attribute_values"]["font@color"] == {"#cc3333": 1}
    assert result["source_pages"][0]["readable_region_count"] == 2
