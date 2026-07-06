"""Tests for ccel_npnf2.py Session 2A, 2B, and 2C outputs and parser invariants."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.parsers.ccel_npnf2 import (  # noqa: E402
    BATCH_2A_VOLS,
    BATCH_2B_VOLS,
    BATCH_2C_VOLS,
    VOLUME_CONFIG,
    _EDITORIAL_TITLE_PATTERNS,
    count_nodes,
    is_editorial_div,
    parse_volume_work,
    sum_tree,
)
from build.lib.pytest_skips import skip_if_missing_data  # noqa: E402

EXPECTED_NODE_COUNTS = {'ambrose-of-milan-concerning-repentance': 30,
 'ambrose-of-milan-concerning-virgins': 28,
 'ambrose-of-milan-concerning-widows': 15,
 'ambrose-of-milan-exposition-of-christian-faith': 91,
 'ambrose-of-milan-letters': 15,
 'ambrose-of-milan-on-duties-of-clergy': 105,
 'ambrose-of-milan-on-holy-spirit': 54,
 'ambrose-of-milan-on-mysteries': 9,
 'ambrose-of-milan-on-satyrus': 2,
 'athanasius-against-the-arians': 44,
 'athanasius-against-the-heathen': 51,
 'athanasius-apology-to-the-emperor': 36,
 'athanasius-arian-history': 9,
 'athanasius-circular-to-bishops-of-egypt-and-libya': 3,
 'athanasius-defence-against-the-arians': 9,
 'athanasius-defence-of-dionysius': 1,
 'athanasius-defence-of-his-flight': 28,
 'athanasius-defence-of-the-nicene-definition': 8,
 'athanasius-deposition-of-arius': 1,
 'athanasius-encyclical-letter': 8,
 'athanasius-letters-and-chronicles': 56,
 'athanasius-life-of-antony': 46,
 'athanasius-on-ariminum-and-seleucia': 4,
 'athanasius-on-luke-10-22': 7,
 'athanasius-on-the-incarnation': 58,
 'athanasius-statement-of-faith': 1,
 'athanasius-synodal-letter-to-africa': 1,
 'athanasius-synodal-letter-to-antioch': 1,
 'basil-of-caesarea-hexaemeron': 9,
 'basil-of-caesarea-letters': 356,
 'basil-of-caesarea-on-the-holy-spirit': 30,
 'cyril-of-jerusalem-catechetical-lectures': 24,
 'ecumenical-councils-canons-and-decrees': 182,
 'eusebius-letter-on-nicene-creed': 1,
 'gregory-of-nazianzus-select-letters': 111,
 'gregory-of-nazianzus-select-orations': 24,
 'gregory-of-nyssa-against-eunomius': 124,
 'gregory-of-nyssa-answer-to-eunomius-second-book': 1,
 'gregory-of-nyssa-funeral-oration-on-meletius': 1,
 'gregory-of-nyssa-great-catechism': 42,
 'gregory-of-nyssa-letters': 18,
 'gregory-of-nyssa-not-three-gods': 1,
 'gregory-of-nyssa-on-infants-early-deaths': 1,
 'gregory-of-nyssa-on-pilgrimages': 1,
 'gregory-of-nyssa-on-the-baptism-of-christ': 1,
 'gregory-of-nyssa-on-the-faith': 1,
 'gregory-of-nyssa-on-the-holy-spirit': 1,
 'gregory-of-nyssa-on-the-holy-trinity': 1,
 'gregory-of-nyssa-on-the-making-of-man': 33,
 'gregory-of-nyssa-on-the-soul-and-resurrection': 2,
 'gregory-of-nyssa-on-virginity': 25,
 'gregory-the-great-pastoral-rule-and-epistles': 351,
 'gregory-the-great-selected-epistles': 153,
 'hilary-of-poitiers-select-works': 21,
 'jerome-against-jovinianus': 2,
 'jerome-against-pelagians': 4,
 'jerome-against-vigilantius': 1,
 'jerome-dialogue-against-luciferians': 1,
 'jerome-letters': 150,
 'jerome-life-of-hilarion': 1,
 'jerome-life-of-malchus': 1,
 'jerome-life-of-paulus': 1,
 'jerome-perpetual-virginity-of-mary': 1,
 'jerome-to-pammachius-against-john-of-jerusalem': 1,
 'john-cassian-selected-works': 919,
 'john-of-damascus-orthodox-faith': 106,
 'leo-the-great-letters-and-sermons': 217,
 'sulpitius-severus-selected-works': 237,
 'vincent-of-lerins-commonitory': 33}
EXPECTED_MIN_WORD_COUNTS = {'ambrose-of-milan-concerning-repentance': 25118,
 'ambrose-of-milan-concerning-virgins': 20526,
 'ambrose-of-milan-concerning-widows': 13946,
 'ambrose-of-milan-exposition-of-christian-faith': 88235,
 'ambrose-of-milan-letters': 52209,
 'ambrose-of-milan-on-duties-of-clergy': 74239,
 'ambrose-of-milan-on-holy-spirit': 52090,
 'ambrose-of-milan-on-mysteries': 7073,
 'ambrose-of-milan-on-satyrus': 31652,
 'athanasius-against-the-arians': 111033,
 'athanasius-against-the-heathen': 23994,
 'athanasius-apology-to-the-emperor': 12588,
 'athanasius-arian-history': 25836,
 'athanasius-circular-to-bishops-of-egypt-and-libya': 10899,
 'athanasius-defence-against-the-arians': 37891,
 'athanasius-defence-of-dionysius': 10003,
 'athanasius-defence-of-his-flight': 8523,
 'athanasius-defence-of-the-nicene-definition': 15358,
 'athanasius-deposition-of-arius': 2086,
 'athanasius-encyclical-letter': 3997,
 'athanasius-letters-and-chronicles': 70272,
 'athanasius-life-of-antony': 24195,
 'athanasius-on-ariminum-and-seleucia': 24899,
 'athanasius-on-luke-10-22': 3060,
 'athanasius-on-the-incarnation': 28464,
 'athanasius-statement-of-faith': 1427,
 'athanasius-synodal-letter-to-africa': 4530,
 'athanasius-synodal-letter-to-antioch': 2862,
 'basil-of-caesarea-hexaemeron': 43407,
 'basil-of-caesarea-letters': 170876,
 'basil-of-caesarea-on-the-holy-spirit': 35342,
 'cyril-of-jerusalem-catechetical-lectures': 108027,
 'ecumenical-councils-canons-and-decrees': 144312,
 'eusebius-letter-on-nicene-creed': 1487,
 'gregory-of-nazianzus-select-letters': 36148,
 'gregory-of-nazianzus-select-orations': 193424,
 'gregory-of-nyssa-against-eunomius': 189796,
 'gregory-of-nyssa-answer-to-eunomius-second-book': 59092,
 'gregory-of-nyssa-funeral-oration-on-meletius': 3569,
 'gregory-of-nyssa-great-catechism': 31308,
 'gregory-of-nyssa-letters': 17447,
 'gregory-of-nyssa-not-three-gods': 5521,
 'gregory-of-nyssa-on-infants-early-deaths': 8565,
 'gregory-of-nyssa-on-pilgrimages': 1574,
 'gregory-of-nyssa-on-the-baptism-of-christ': 6088,
 'gregory-of-nyssa-on-the-faith': 1995,
 'gregory-of-nyssa-on-the-holy-spirit': 9381,
 'gregory-of-nyssa-on-the-holy-trinity': 3585,
 'gregory-of-nyssa-on-the-making-of-man': 37278,
 'gregory-of-nyssa-on-the-soul-and-resurrection': 33097,
 'gregory-of-nyssa-on-virginity': 24566,
 'gregory-the-great-pastoral-rule-and-epistles': 200592,
 'gregory-the-great-selected-epistles': 90673,
 'hilary-of-poitiers-select-works': 208889,
 'jerome-against-jovinianus': 61885,
 'jerome-against-pelagians': 31356,
 'jerome-against-vigilantius': 6421,
 'jerome-dialogue-against-luciferians': 13633,
 'jerome-letters': 260304,
 'jerome-life-of-hilarion': 11400,
 'jerome-life-of-malchus': 3404,
 'jerome-life-of-paulus': 3886,
 'jerome-perpetual-virginity-of-mary': 10833,
 'jerome-to-pammachius-against-john-of-jerusalem': 22387,
 'john-cassian-selected-works': 330280,
 'john-of-damascus-orthodox-faith': 80953,
 'leo-the-great-letters-and-sermons': 161936,
 'sulpitius-severus-selected-works': 102403,
 'vincent-of-lerins-commonitory': 19409}


def test_batch_2a_volumes_are_locked():
    assert BATCH_2A_VOLS == ["npnf204", "npnf205"]


def test_batch_2b_volumes_are_locked():
    assert BATCH_2B_VOLS == ["npnf206", "npnf207", "npnf208"]


def test_batch_2c_volumes_are_locked():
    assert BATCH_2C_VOLS == ["npnf209", "npnf210", "npnf211", "npnf212", "npnf213", "npnf214"]


def test_config_covers_session_2a_2b_and_2c_work_count():
    vols = BATCH_2A_VOLS + BATCH_2B_VOLS + BATCH_2C_VOLS
    assert sum(len(VOLUME_CONFIG[vol]["works"]) for vol in vols) == len(EXPECTED_NODE_COUNTS)


@pytest.mark.slow
@pytest.mark.parametrize("slug,expected", sorted(EXPECTED_NODE_COUNTS.items()))
def test_output_section_counts_match_pilot_parse(slug, expected):
    path = REPO_ROOT / "data" / "structured-text" / f"{slug}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert count_nodes(data["data"]["sections"]) == expected


@pytest.mark.slow
@pytest.mark.parametrize("slug,min_words", sorted(EXPECTED_MIN_WORD_COUNTS.items()))
def test_output_word_counts_are_non_empty(slug, min_words):
    path = REPO_ROOT / "data" / "structured-text" / f"{slug}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert sum_tree(data["data"]["sections"], "word_count") >= min_words


@pytest.mark.parametrize("vol", BATCH_2A_VOLS + BATCH_2B_VOLS + BATCH_2C_VOLS)
def test_raw_files_are_cached(vol):
    raw_file = VOLUME_CONFIG[vol]["raw_file"]
    skip_if_missing_data(raw_file)
    assert raw_file.exists()
    assert raw_file.stat().st_size > 0


def test_editorial_introduction_is_skipped():
    elem = ET.fromstring('<div2 title="Introduction." id="vii.i"/>')
    assert is_editorial_div(elem) is True


def test_content_letter_is_not_skipped():
    elem = ET.fromstring('<div2 type="Letter" title="To Eusebius." id="xiii.ii"/>')
    assert is_editorial_div(elem) is False


def test_editorial_pattern_does_not_swallow_on_the_faith():
    assert _EDITORIAL_TITLE_PATTERNS.match("On the Faith.") is None


def test_pilot_treatise_parse_has_expected_shape():
    skip_if_missing_data(VOLUME_CONFIG["npnf204"]["raw_file"])
    cfg = next(w for w in VOLUME_CONFIG["npnf204"]["works"] if w["slug"] == "athanasius-on-the-incarnation")
    result = parse_volume_work("npnf204", cfg, VOLUME_CONFIG["npnf204"]["raw_file"].read_bytes())
    assert count_nodes(result["sections"]) == EXPECTED_NODE_COUNTS["athanasius-on-the-incarnation"]


def test_pilot_narrative_parse_has_expected_shape():
    skip_if_missing_data(VOLUME_CONFIG["npnf204"]["raw_file"])
    cfg = next(w for w in VOLUME_CONFIG["npnf204"]["works"] if w["slug"] == "athanasius-life-of-antony")
    result = parse_volume_work("npnf204", cfg, VOLUME_CONFIG["npnf204"]["raw_file"].read_bytes())
    assert count_nodes(result["sections"]) == EXPECTED_NODE_COUNTS["athanasius-life-of-antony"]


def test_pilot_gregory_parse_has_expected_shape():
    skip_if_missing_data(VOLUME_CONFIG["npnf205"]["raw_file"])
    cfg = next(w for w in VOLUME_CONFIG["npnf205"]["works"] if w["slug"] == "gregory-of-nyssa-great-catechism")
    result = parse_volume_work("npnf205", cfg, VOLUME_CONFIG["npnf205"]["raw_file"].read_bytes())
    assert count_nodes(result["sections"]) == EXPECTED_NODE_COUNTS["gregory-of-nyssa-great-catechism"]


def test_pilot_jerome_letters_parse_has_expected_shape():
    skip_if_missing_data(VOLUME_CONFIG["npnf206"]["raw_file"])
    cfg = next(w for w in VOLUME_CONFIG["npnf206"]["works"] if w["slug"] == "jerome-letters")
    result = parse_volume_work("npnf206", cfg, VOLUME_CONFIG["npnf206"]["raw_file"].read_bytes())
    assert count_nodes(result["sections"]) == EXPECTED_NODE_COUNTS["jerome-letters"]


def test_pilot_multi_author_volume_splits_by_author_and_work_family():
    cyril = next(w for w in VOLUME_CONFIG["npnf207"]["works"] if w["author_id"] == "cyril-of-jerusalem")
    gregory_slugs = [w["slug"] for w in VOLUME_CONFIG["npnf207"]["works"] if w["author_id"] == "gregory-of-nazianzus"]
    assert cyril["slug"] == "cyril-of-jerusalem-catechetical-lectures"
    assert gregory_slugs == ["gregory-of-nazianzus-select-orations", "gregory-of-nazianzus-select-letters"]


def test_pilot_gregory_orations_parse_has_expected_shape():
    skip_if_missing_data(VOLUME_CONFIG["npnf207"]["raw_file"])
    cfg = next(w for w in VOLUME_CONFIG["npnf207"]["works"] if w["slug"] == "gregory-of-nazianzus-select-orations")
    result = parse_volume_work("npnf207", cfg, VOLUME_CONFIG["npnf207"]["raw_file"].read_bytes())
    assert count_nodes(result["sections"]) == EXPECTED_NODE_COUNTS["gregory-of-nazianzus-select-orations"]


def test_pilot_gregory_letters_parse_has_expected_shape():
    skip_if_missing_data(VOLUME_CONFIG["npnf207"]["raw_file"])
    cfg = next(w for w in VOLUME_CONFIG["npnf207"]["works"] if w["slug"] == "gregory-of-nazianzus-select-letters")
    result = parse_volume_work("npnf207", cfg, VOLUME_CONFIG["npnf207"]["raw_file"].read_bytes())
    assert count_nodes(result["sections"]) == EXPECTED_NODE_COUNTS["gregory-of-nazianzus-select-letters"]


def test_pilot_basil_letters_parse_has_expected_shape():
    skip_if_missing_data(VOLUME_CONFIG["npnf208"]["raw_file"])
    cfg = next(w for w in VOLUME_CONFIG["npnf208"]["works"] if w["slug"] == "basil-of-caesarea-letters")
    result = parse_volume_work("npnf208", cfg, VOLUME_CONFIG["npnf208"]["raw_file"].read_bytes())
    assert count_nodes(result["sections"]) == EXPECTED_NODE_COUNTS["basil-of-caesarea-letters"]


def test_pilot_session_2c_multi_author_parse_has_expected_shape():
    skip_if_missing_data(VOLUME_CONFIG["npnf209"]["raw_file"])
    cfg = next(w for w in VOLUME_CONFIG["npnf209"]["works"] if w["slug"] == "john-of-damascus-orthodox-faith")
    result = parse_volume_work("npnf209", cfg, VOLUME_CONFIG["npnf209"]["raw_file"].read_bytes())
    assert count_nodes(result["sections"]) == EXPECTED_NODE_COUNTS["john-of-damascus-orthodox-faith"]


def test_pilot_gregory_the_great_letters_parse_has_expected_shape():
    skip_if_missing_data(VOLUME_CONFIG["npnf213"]["raw_file"])
    cfg = next(w for w in VOLUME_CONFIG["npnf213"]["works"] if w["slug"] == "gregory-the-great-selected-epistles")
    result = parse_volume_work("npnf213", cfg, VOLUME_CONFIG["npnf213"]["raw_file"].read_bytes())
    assert count_nodes(result["sections"]) == EXPECTED_NODE_COUNTS["gregory-the-great-selected-epistles"]


def test_pilot_ecumenical_councils_parse_has_expected_shape():
    skip_if_missing_data(VOLUME_CONFIG["npnf214"]["raw_file"])
    cfg = next(w for w in VOLUME_CONFIG["npnf214"]["works"] if w["slug"] == "ecumenical-councils-canons-and-decrees")
    result = parse_volume_work("npnf214", cfg, VOLUME_CONFIG["npnf214"]["raw_file"].read_bytes())
    assert count_nodes(result["sections"]) == EXPECTED_NODE_COUNTS["ecumenical-councils-canons-and-decrees"]


@pytest.mark.slow
def test_every_output_has_refined_provenance():
    for slug in EXPECTED_NODE_COUNTS:
        path = REPO_ROOT / "data" / "structured-text" / f"{slug}.json"
        provenance = json.loads(path.read_text(encoding="utf-8"))["meta"]["provenance"]
        assert provenance["source_type"] == "ccel_thml"
        assert provenance["source_url"].startswith("https://www.ccel.org/ccel/schaff/npnf2")
        assert provenance["source_file"].startswith("raw/ccel/npnf2/npnf2")
        assert provenance["source_hash"].startswith("sha256:")
        assert provenance["translator"]
