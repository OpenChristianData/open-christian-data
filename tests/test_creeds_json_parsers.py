from build.parsers import creeds_json_catechism, creeds_json_confession


def test_catechism_meta_maps_original_language_to_code():
    meta = creeds_json_catechism.build_meta(
        source_hash="0" * 64,
        doc_cfg=creeds_json_catechism.DOCUMENT_CONFIGS["heidelberg_catechism"],
        metadata={
            "Title": "Heidelberg Catechism",
            "Authors": ["Zacharias Ursinus"],
            "Year": "1563",
            "OriginalLanguage": "German",
        },
        process_date="2026-07-03",
    )

    assert meta["original_language"] == "de"


def test_catechism_meta_names_unmapped_creeds_fields_in_provenance_notes():
    meta = creeds_json_catechism.build_meta(
        source_hash="0" * 64,
        doc_cfg=creeds_json_catechism.DOCUMENT_CONFIGS["heidelberg_catechism"],
        metadata={
            "Title": "Heidelberg Catechism",
            "Authors": ["Zacharias Ursinus"],
            "Year": "1563",
            "OriginalLanguage": "German",
            "OriginStory": "Source origin.",
            "AlternativeTitles": ["Alternate title"],
            "Location": "Heidelberg, Germany",
            "SourceAttribution": "Public Domain",
            "CreedFormat": "Catechism",
        },
        process_date="2026-07-03",
    )

    notes = meta["provenance"]["notes"]
    assert "OriginalLanguage mapped to meta.original_language" in notes
    for field in (
        "OriginStory",
        "AlternativeTitles",
        "Location",
        "SourceAttribution",
        "CreedFormat",
    ):
        assert field in notes


def test_confession_meta_records_original_language_without_schema_field():
    meta = creeds_json_confession.build_meta(
        source_hash="0" * 64,
        doc_cfg=creeds_json_confession.DOCUMENT_CONFIGS["apostles_creed"],
        metadata={
            "Title": "Apostles' Creed",
            "Authors": [],
            "Year": "700",
            "OriginalLanguage": "Latin",
        },
        process_date="2026-07-03",
    )

    assert "original_language" not in meta
    assert "OriginalLanguage=la" in meta["provenance"]["notes"]


def test_confession_meta_names_unmapped_creeds_fields_in_provenance_notes():
    meta = creeds_json_confession.build_meta(
        source_hash="0" * 64,
        doc_cfg=creeds_json_confession.DOCUMENT_CONFIGS["belgic_confession_of_faith"],
        metadata={
            "Title": "Belgic Confession",
            "Authors": ["Guido de Bres"],
            "Year": "1561",
            "OriginalLanguage": "French",
            "OriginStory": "First printed in Rouen.",
            "AlternativeTitles": ["Belgic Confession of Faith"],
            "Location": "Low Countries",
            "SourceAttribution": "Public Domain",
            "CreedFormat": "Canon",
        },
        process_date="2026-07-03",
    )

    notes = meta["provenance"]["notes"]
    assert "OriginalLanguage=fr" in notes
    for field in (
        "OriginStory",
        "AlternativeTitles",
        "Location",
        "SourceAttribution",
        "CreedFormat",
    ):
        assert field in notes
