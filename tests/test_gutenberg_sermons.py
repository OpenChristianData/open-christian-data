"""Tests for build/parsers/gutenberg_sermons.py

Covers all key parsing functions for both Luther Lenker and Newman PPS series.
Each test verifies one specific behaviour with a true-positive and/or true-negative case.
"""

import sys
from pathlib import Path

# Ensure repo root is on sys.path for imports
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "build" / "parsers"))

import gutenberg_sermons as gs  # noqa: E402
from build.lib.text_utils import smart_title  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


def _log() -> list:
    return []


# ---------------------------------------------------------------------------
# blocks_from_text
# ---------------------------------------------------------------------------


def test_blocks_from_text_splits_on_blank_lines():
    text = "Line one.\nLine two.\n\nLine three.\n"
    blocks = gs.blocks_from_text(text)
    assert len(blocks) == 2
    assert blocks[0] == "Line one. Line two."
    assert blocks[1] == "Line three."


def test_blocks_from_text_normalises_whitespace():
    text = "  word   spaced   \n\n  next  block  \n"
    blocks = gs.blocks_from_text(text)
    assert blocks[0] == "word   spaced"
    assert blocks[1] == "next  block"


def test_blocks_from_text_empty_string():
    assert gs.blocks_from_text("") == []


# ---------------------------------------------------------------------------
# _is_luther_title_block
# ---------------------------------------------------------------------------


def test_is_luther_title_block_valid_caps():
    assert gs._is_luther_title_block("AN EXHORTATION TO GOOD WORKS") is True


def test_is_luther_title_block_valid_single_title():
    assert gs._is_luther_title_block("THE DAY OF GRACE") is True


def test_is_luther_title_block_rejects_lowercase():
    assert gs._is_luther_title_block("This is a normal sentence.") is False


def test_is_luther_title_block_rejects_short():
    # Less than 5 chars
    assert gs._is_luther_title_block("ABC") is False


def test_is_luther_title_block_rejects_no_long_word():
    # All single characters -- no 3+ letter word
    assert gs._is_luther_title_block("A B C D E F G") is False


def test_is_luther_title_block_rejects_long_paragraph():
    # Very long text should not be treated as a title
    long = "WORD " * 50
    assert gs._is_luther_title_block(long) is False


# ---------------------------------------------------------------------------
# _extract_luther_scripture_ref
# ---------------------------------------------------------------------------


def test_extract_luther_scripture_ref_standard():
    ref = gs._extract_luther_scripture_ref("Romans 13, 11-14")
    assert ref == "Romans 13, 11-14"


def test_extract_luther_scripture_ref_strips_trailing_period():
    ref = gs._extract_luther_scripture_ref("Matthew 21, 1-9.")
    assert ref == "Matthew 21, 1-9"


def test_extract_luther_scripture_ref_empty():
    assert gs._extract_luther_scripture_ref("") is None


def test_extract_luther_scripture_ref_no_digit():
    # Must have both alpha and digit
    assert gs._extract_luther_scripture_ref("Random text here") is None


def test_extract_luther_scripture_ref_no_alpha():
    assert gs._extract_luther_scripture_ref("123, 456") is None


def test_extract_luther_scripture_ref_strips_embedded_quotation():
    # DjVu vols run scripture ref and quotation on same line
    tail = "Math.  21,  1-9.  And  when  they  drew  nigh  unto  Jerusalem."
    ref = gs._extract_luther_scripture_ref(tail)
    assert ref is not None
    assert "Math" in ref
    assert "And  when" not in ref


# ---------------------------------------------------------------------------
# _extract_newman_title
# ---------------------------------------------------------------------------


def test_extract_newman_title_inline():
    block = "SERMON I. THE LAPSE OF TIME."
    title = gs._extract_newman_title(block)
    assert "Lapse Of Time" in title or "lapse of time" in title.lower()


def test_extract_newman_title_no_match_returns_fallback():
    block = "Not a sermon header at all."
    title = gs._extract_newman_title(block)
    assert title == "Untitled Sermon"


def test_extract_newman_title_bare_numeral():
    block = "SERMON IV."
    title = gs._extract_newman_title(block)
    # Should fall back to "Sermon IV"
    assert "IV" in title or "iv" in title.lower()


def test_extract_newman_title_multiline():
    block = "SERMON II.\nHOLINESS NECESSARY FOR FUTURE BLESSEDNESS."
    title = gs._extract_newman_title(block)
    assert "Holiness" in title or "holiness" in title.lower()


# ---------------------------------------------------------------------------
# _extract_newman_scripture_ref
# ---------------------------------------------------------------------------


def test_extract_newman_scripture_ref_valid():
    blocks = ["Hebrews xii. 14.", "'Holiness, without which no man shall see the Lord.'"]
    ref = gs._extract_newman_scripture_ref(blocks)
    assert ref is not None
    assert "Hebrews" in ref
    assert "14" in ref


def test_extract_newman_scripture_ref_no_match():
    blocks = ["This is just a paragraph of content.", "More content here."]
    ref = gs._extract_newman_scripture_ref(blocks)
    assert ref is None


def test_extract_newman_scripture_ref_requires_digit():
    # A line that looks like a book name but has no chapter/verse
    blocks = ["Matthew.", "Some content."]
    ref = gs._extract_newman_scripture_ref(blocks)
    assert ref is None


def test_extract_newman_scripture_ref_empty_list():
    assert gs._extract_newman_scripture_ref([]) is None


# ---------------------------------------------------------------------------
# _NEWMAN_SERMON_RE pattern
# ---------------------------------------------------------------------------


def test_newman_sermon_re_matches_standard():
    assert gs._NEWMAN_SERMON_RE.match("SERMON I. The Lapse of Time.") is not None


def test_newman_sermon_re_matches_roman_numerals():
    assert gs._NEWMAN_SERMON_RE.match("SERMON XIV. Some Title.") is not None


def test_newman_sermon_re_no_match_lowercase():
    # Pattern is case-insensitive, but "sermon" without "SERMON" should still match
    assert gs._NEWMAN_SERMON_RE.match("sermon i. title") is not None


def test_newman_sermon_re_no_match_non_sermon():
    assert gs._NEWMAN_SERMON_RE.match("This is not a sermon header.") is None


# ---------------------------------------------------------------------------
# _LUTHER_TEXT_LINE_RE pattern
# ---------------------------------------------------------------------------


def test_luther_text_re_matches_epistle():
    m = gs._LUTHER_TEXT_LINE_RE.match("Epistle Text: Romans 13, 11-14")
    assert m is not None
    assert "Romans" in m.group(1)


def test_luther_text_re_matches_gospel():
    m = gs._LUTHER_TEXT_LINE_RE.match("Gospel Text: Matthew 21, 1-9.")
    assert m is not None
    assert "Matthew" in m.group(1)


def test_luther_text_re_case_insensitive():
    m = gs._LUTHER_TEXT_LINE_RE.match("epistle text: John 3, 16")
    assert m is not None


def test_luther_text_re_matches_bare_text():
    # Vols 2-8 use bare "Text:" without the Epistle/Gospel prefix
    m = gs._LUTHER_TEXT_LINE_RE.match("Text:    Romans  12,  1-6. ")
    assert m is not None
    assert "Romans" in m.group(1)


def test_luther_text_re_matches_bare_text_spaced_colon():
    m = gs._LUTHER_TEXT_LINE_RE.match("Text :  Math.  21,  1-9.")
    assert m is not None
    assert "Math" in m.group(1)


def test_luther_text_re_matches_period_separator():
    # Vol 7 uses period as separator: "Text. Luke 16:19-31"
    m = gs._LUTHER_TEXT_LINE_RE.match("Text.  Luke  16:19-31.  And  there  was  a  rich  man.")
    assert m is not None
    assert "Luke" in m.group(1)


def test_luther_text_re_matches_comma_separator():
    # Vol 7 also uses comma: "Text, Luke 15:1-10"
    m = gs._LUTHER_TEXT_LINE_RE.match("Text,  Luke  15:1-10.")
    assert m is not None
    assert "Luke" in m.group(1)


def test_luther_text_re_no_match_toc_entry():
    # TOC entries don't start with "Epistle Text:" -- they have the liturgical day first
    line = "First Sunday in Advent. -- An Exhortation. Romans 13, 11-14 9"
    assert gs._LUTHER_TEXT_LINE_RE.match(line) is None


def test_luther_text_re_body_sentence_has_no_digit_in_tail():
    # "text." with prose but no digit in tail: regex may match (period is valid separator),
    # but parse_luther_volume's digit guard rejects it as a boundary marker.
    m = gs._LUTHER_TEXT_LINE_RE.match("text.  I have rendered it correctly.")
    if m:
        assert not any(c.isdigit() for c in m.group(1))


# ---------------------------------------------------------------------------
# parse_luther_volume integration
# ---------------------------------------------------------------------------


_LUTHER_SAMPLE = """\
Table of Contents

First Sunday in Advent. -- An Exhortation to Good Works. Romans 13, 11-14 9

Epistle Text: Romans 13, 11-14
Now it is high time to awake out of sleep: for now is our salvation nearer
than when we believed.

AN EXHORTATION TO GOOD WORKS

1. First, let us consider what it means to cast off the works of darkness.
We must lay aside every sin that might ensnare us in the darkness of unbelief.
The gospel demands that we present ourselves as living sacrifices.
Our conduct must reflect the lordship of Christ in all things.

2. Second, the apostle calls us to put on the armor of light.
This means we must be armed with righteousness, faith, and love.
The darkness cannot overcome the light that Christ has given to us.
We walk in the day, not in the night, for we belong to Christ.

Epistle Text: Galatians 4, 4-7
But when the fullness of the time was come, God sent forth his Son.

BORN OF A WOMAN

1. Here we consider the mystery of the incarnation and its meaning.
The Son of God took on human flesh that we might be adopted as children.
This is the great exchange: He took our poverty and gave us His riches.
Our salvation rests entirely on the grace of God in Christ Jesus.

2. The apostle tells us we are no longer servants but sons of God.
Through faith we receive the spirit of adoption whereby we cry Abba, Father.
This is the glorious liberty of the children of God revealed in Scripture.
"""


def test_parse_luther_volume_extracts_sermons():
    vol_cfg = {"vol": 1, "series_label": "epistle-sermons", "title": "Epistle Sermons, Part 1"}
    entries = gs.parse_luther_volume(vol_cfg, _LUTHER_SAMPLE, 1, _log())
    assert len(entries) >= 1


def test_parse_luther_volume_has_required_fields():
    vol_cfg = {"vol": 1, "series_label": "epistle-sermons", "title": "Epistle Sermons, Part 1"}
    entries = gs.parse_luther_volume(vol_cfg, _LUTHER_SAMPLE, 1, _log())
    for e in entries:
        assert "collection_id" in e
        assert "sermon_id" in e
        assert "title" in e
        assert "content_blocks" in e
        assert e["word_count"] > 0
        assert e["collection_id"] == "luther-lenker-sermons"


def test_parse_luther_volume_extracts_scripture_ref():
    vol_cfg = {"vol": 1, "series_label": "epistle-sermons", "title": "Epistle Sermons, Part 1"}
    entries = gs.parse_luther_volume(vol_cfg, _LUTHER_SAMPLE, 1, _log())
    refs = [e.get("primary_reference") for e in entries if e.get("primary_reference")]
    assert len(refs) >= 1
    assert "Romans" in refs[0]["raw"] or "Galatians" in refs[0]["raw"]


def test_parse_luther_volume_sermon_id_format():
    vol_cfg = {"vol": 3, "series_label": "epistle-sermons", "title": "Epistle Sermons, Part 3"}
    entries = gs.parse_luther_volume(vol_cfg, _LUTHER_SAMPLE, 1, _log())
    for e in entries:
        assert e["sermon_id"].startswith("luther-lenker-v03-")


def test_parse_luther_volume_empty_text():
    vol_cfg = {"vol": 1, "series_label": "epistle-sermons", "title": "Epistle Sermons, Part 1"}
    entries = gs.parse_luther_volume(vol_cfg, "", 1, _log())
    assert entries == []


# ---------------------------------------------------------------------------
# parse_newman_volume integration
# ---------------------------------------------------------------------------


_NEWMAN_SAMPLE_IA = """\
PAROCHIAL AND PLAIN SERMONS

VOLUME I

SERMON I. HOLINESS NECESSARY FOR FUTURE BLESSEDNESS.

Hebrews xii. 14.

'Holiness, without which no man shall see the Lord.'

Holiness is the great topic of the New Testament. The apostle here declares
that without it no man shall see the Lord. This is a doctrine which the Church
has always taught, though the world has often tried to evade it. We must be holy
in this life if we would be admitted into the presence of God in the next.

Consider first what holiness means. It is not mere outward conformity to rules.
It is an inward transformation of the heart by the Spirit of God. It involves
the crucifixion of our natural desires and the cultivation of love, humility,
and obedience. The Christian must strive after perfection, knowing that God
requires a clean heart and a right spirit.

SERMON II. THE IMMORTALITY OF THE SOUL.

Matthew xvi. 26.

'What shall a man give in exchange for his soul?'

The immortality of the soul is a truth of great importance to all men. Our Lord
here assumes it as a foundation for his teaching about the value of the soul.
If the soul did not live after death, then this world would be all in all.
But since it does, we must reckon with eternity in every decision we make.

Consider the contrast between the soul and the body. The body is mortal and
subject to decay. The soul is immortal and will face judgment. Our Lord warns
us not to gain the whole world at the cost of our souls. This is the great
peril of materialism and worldliness.
"""


_NEWMAN_SAMPLE_PG = """\
The Project Gutenberg EBook of Parochial and Plain Sermons, Vol. VII, by Newman

*** START OF THE PROJECT GUTENBERG EBOOK PAROCHIAL AND PLAIN SERMONS ***

PAROCHIAL AND PLAIN SERMONS.

SERMON I.

The Lapse of Time.

'_Whatsoever thy hand findeth to do, do it with thy might; for there is no work,
nor device, nor knowledge, nor wisdom, in the grave, whither thou goest._'--Eccles. ix. 10.

Time is short and our opportunities are few. Solomon urges us to use our hands
with diligence, because death is certain and eternity follows close upon this
life. We must not delay what duty calls us to do today, for tomorrow may not
come. The wise man knows that he must use his present moments well.

Let us then ask ourselves how we are spending our time. Are we using it for
the glory of God? Are we making progress in virtue and holiness? The Christian
is not his own but is bought with a price, and must glorify God in every moment.

SERMON II.

Religion a Weariness to the Natural Man.

'_Thou hast not called upon me, O Jacob; but thou hast been weary of me, O Israel._'--Isai. xliii. 22.

The natural man finds religion wearisome. He does not delight in prayer, in
scripture, or in the service of God. This is not because religion is truly
burdensome, but because his heart is set on other things. He prefers the pleasures
of the world to the company of God.

*** END OF THE PROJECT GUTENBERG EBOOK PAROCHIAL AND PLAIN SERMONS ***
"""


def test_parse_newman_volume_ia_extracts_sermons():
    vol_cfg = {"vol": 1, "ia_id": "parochialplainse01newmuoft", "source": "ia", "year": 1868}
    entries = gs.parse_newman_volume(vol_cfg, _NEWMAN_SAMPLE_IA, is_pg=False, sermon_num_start=1, log_lines=_log())
    assert len(entries) >= 1


def test_parse_newman_volume_pg_extracts_sermons():
    vol_cfg = {"vol": 7, "pg_id": "24256", "source": "pg", "year": 1868}
    entries = gs.parse_newman_volume(vol_cfg, _NEWMAN_SAMPLE_PG, is_pg=True, sermon_num_start=1, log_lines=_log())
    assert len(entries) >= 1


def test_parse_newman_volume_has_required_fields():
    vol_cfg = {"vol": 1, "ia_id": "parochialplainse01newmuoft", "source": "ia", "year": 1868}
    entries = gs.parse_newman_volume(vol_cfg, _NEWMAN_SAMPLE_IA, is_pg=False, sermon_num_start=1, log_lines=_log())
    for e in entries:
        assert "collection_id" in e
        assert "sermon_id" in e
        assert "title" in e
        assert "content_blocks" in e
        assert e["word_count"] > 0
        assert e["collection_id"] == "newman-parochial-sermons"


def test_parse_newman_volume_sermon_id_format():
    vol_cfg = {"vol": 5, "ia_id": "parochialplainse05newmuoft", "source": "ia", "year": 1868}
    entries = gs.parse_newman_volume(vol_cfg, _NEWMAN_SAMPLE_IA, is_pg=False, sermon_num_start=1, log_lines=_log())
    for e in entries:
        assert e["sermon_id"].startswith("newman-pps-v05-")


def test_parse_newman_volume_extracts_scripture_ref():
    vol_cfg = {"vol": 1, "ia_id": "parochialplainse01newmuoft", "source": "ia", "year": 1868}
    entries = gs.parse_newman_volume(vol_cfg, _NEWMAN_SAMPLE_IA, is_pg=False, sermon_num_start=1, log_lines=_log())
    refs = [e.get("primary_reference") for e in entries if e.get("primary_reference")]
    assert len(refs) >= 1
    # Should extract "Hebrews xii. 14" or similar
    assert any("Hebrews" in r["raw"] or "Matthew" in r["raw"] for r in refs)


def test_parse_newman_volume_empty_text():
    vol_cfg = {"vol": 1, "ia_id": "parochialplainse01newmuoft", "source": "ia", "year": 1868}
    entries = gs.parse_newman_volume(vol_cfg, "", is_pg=False, sermon_num_start=1, log_lines=_log())
    assert entries == []


def test_parse_newman_volume_pg_strips_wrapper():
    vol_cfg = {"vol": 7, "pg_id": "24256", "source": "pg", "year": 1868}
    # PG sample has header/footer markers -- these should be stripped
    entries = gs.parse_newman_volume(vol_cfg, _NEWMAN_SAMPLE_PG, is_pg=True, sermon_num_start=1, log_lines=_log())
    # Content blocks should not contain "Project Gutenberg" boilerplate
    all_content = " ".join(b for e in entries for b in e["content_blocks"])
    assert "Project Gutenberg" not in all_content


def test_parse_newman_volume_pg_title_not_fallback():
    vol_cfg = {"vol": 7, "pg_id": "24256", "source": "pg", "year": 1868}
    entries = gs.parse_newman_volume(vol_cfg, _NEWMAN_SAMPLE_PG, is_pg=True, sermon_num_start=1, log_lines=_log())
    assert len(entries) >= 1
    # Titles should be real names, not "Sermon I" fallback
    titles = [e["title"] for e in entries]
    assert any("Lapse" in t for t in titles)
    assert not any(t.startswith("Sermon ") and t.split()[-1].isupper() for t in titles)


def test_parse_newman_volume_pg_extracts_embedded_ref():
    vol_cfg = {"vol": 7, "pg_id": "24256", "source": "pg", "year": 1868}
    entries = gs.parse_newman_volume(vol_cfg, _NEWMAN_SAMPLE_PG, is_pg=True, sermon_num_start=1, log_lines=_log())
    refs = [e.get("primary_reference") for e in entries if e.get("primary_reference")]
    assert len(refs) >= 1
    assert any("Eccles" in r["raw"] or "Isai" in r["raw"] for r in refs)


# ---------------------------------------------------------------------------
# _extract_newman_pg_ref
# ---------------------------------------------------------------------------


def test_extract_newman_pg_ref_standard():
    block = "'_Whatsoever thy hand findeth to do._'--Eccles. ix. 10."
    ref = gs._extract_newman_pg_ref(block)
    assert ref is not None
    assert "Eccles" in ref
    assert "10" in ref


def test_extract_newman_pg_ref_numbered_book():
    block = "'_For the love of Christ constraineth us._'--2 Cor. v. 14."
    ref = gs._extract_newman_pg_ref(block)
    assert ref is not None
    assert "Cor" in ref


def test_extract_newman_pg_ref_no_dash_returns_none():
    block = "'Holiness, without which no man shall see the Lord.'"
    assert gs._extract_newman_pg_ref(block) is None


def test_extract_newman_pg_ref_no_digit_returns_none():
    block = "Some text ending with --Matthew."
    assert gs._extract_newman_pg_ref(block) is None


# ---------------------------------------------------------------------------
# strip_pg_wrapper
# ---------------------------------------------------------------------------


def test_strip_pg_wrapper_strips_header_and_footer():
    text = (
        "Preamble junk\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK FOO ***\n"
        "Real content line 1\n"
        "Real content line 2\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK FOO ***\n"
        "Trailing junk\n"
    )
    lines = gs.strip_pg_wrapper(text)
    assert "Real content line 1" in lines
    assert "Preamble junk" not in lines
    assert "Trailing junk" not in lines


def test_strip_pg_wrapper_raises_on_missing_markers():
    import pytest
    with pytest.raises(ValueError, match="markers not found"):
        gs.strip_pg_wrapper("No markers here at all.")


# ---------------------------------------------------------------------------
# Volume config completeness
# ---------------------------------------------------------------------------


def test_luther_volumes_count():
    assert len(gs.LUTHER_VOLUMES) == 8


def test_newman_volumes_count():
    assert len(gs.NEWMAN_VOLUMES) == 8


def test_luther_volumes_have_required_keys():
    for v in gs.LUTHER_VOLUMES:
        assert "vol" in v
        assert "ia_id" in v
        assert "series_label" in v


def test_newman_volumes_have_required_keys():
    for v in gs.NEWMAN_VOLUMES:
        assert "vol" in v
        assert "source" in v
        if v["source"] == "ia":
            assert "ia_id" in v
        else:
            assert "pg_id" in v


def test_luther_series_labels_valid():
    valid = {"epistle-sermons", "gospel-sermons"}
    for v in gs.LUTHER_VOLUMES:
        assert v["series_label"] in valid


# ---------------------------------------------------------------------------
# strip_ia_footer
# ---------------------------------------------------------------------------


def test_strip_ia_footer_truncates_at_date_sentinel():
    text = "Real sermon content here.\n\nMore content.\n\nDate\n\nDue\n\nAPR 27 '55\n"
    result = gs.strip_ia_footer(text)
    assert "Real sermon content" in result
    assert "Date" not in result


def test_strip_ia_footer_truncates_at_ecumenical_statistics():
    text = "Good sermon text.\n\nECUMENICAL PROTESTANT STATISTICS, 1905\n\nGermany 37,000,000\n"
    result = gs.strip_ia_footer(text)
    assert "Good sermon text" in result
    assert "ECUMENICAL" not in result


def test_strip_ia_footer_truncates_at_read_luther_sentinel():
    text = "Last sermon paragraph.\n\n|KE,AD  LUTHER! I\n\nPublisher content.\n"
    result = gs.strip_ia_footer(text)
    assert "Last sermon paragraph" in result
    assert "|KE,AD" not in result


def test_strip_ia_footer_no_sentinel_returns_original():
    text = "Clean text with no footer sentinels.\n\nMore clean text.\n"
    result = gs.strip_ia_footer(text)
    assert result == text


# ---------------------------------------------------------------------------
# _CONTENTS_PREFIX_RE and Gospel Sermon title extraction
# ---------------------------------------------------------------------------


def test_contents_prefix_re_matches_simple():
    m = gs._CONTENTS_PREFIX_RE.match("CONTENTS:  THE WITNESS AND CONFESSION")
    assert m is not None


def test_contents_prefix_re_strips_prefix():
    raw = "CONTENTS:  THE WITNESS AND CONFESSION OF JOHN THE BAPTIST"
    stripped = gs._CONTENTS_PREFIX_RE.sub("", raw).strip()
    assert stripped == "THE WITNESS AND CONFESSION OF JOHN THE BAPTIST"


def test_contents_prefix_re_case_insensitive():
    assert gs._CONTENTS_PREFIX_RE.match("contents: SOME TITLE") is not None


def test_parse_luther_volume_gospel_contents_title():
    """Gospel Sermon volumes: CONTENTS: prefix stripped to give real title."""
    sample = """\
FOURTH SUNDAY IN ADVENT.

Text:  John  1,  19-28.  And  this  is  the  witness  of  John.

CONTENTS:  THE WITNESS AND CONFESSION OF JOHN THE BAPTIST

I.  THE WITNESS. 1.

1. The first thing is that John confessed clearly. He was not the Christ.
John spoke plainly and did not evade the question of the Jews who came
to interrogate him. He confessed and denied not that he was not the Christ.
This is a model of clear evangelical confession for all ministers of the Word.

2. He also denied being Elijah or the prophet. He kept to his calling.
The question of identity is important for any servant of the Word to settle
before God and man, not claiming what does not belong to him.
"""
    vol_cfg = {"vol": 4, "series_label": "gospel-sermons", "title": "Gospel Sermons, Part 1"}
    entries = gs.parse_luther_volume(vol_cfg, sample, 1, _log())
    assert len(entries) >= 1
    title = entries[0]["title"]
    # Should NOT start with "Contents"
    assert not title.lower().startswith("contents")
    # Should contain meaningful words from the heading
    assert "Witness" in title or "Confession" in title or "John" in title


# ---------------------------------------------------------------------------
# _extract_luther_scripture_ref — hyphen-terminated verse range
# ---------------------------------------------------------------------------


def test_extract_luther_scripture_ref_hyphen_terminated():
    # DjVu OCR: verse range dash at end before prose: "Math.  ^3,34-39-  Therefore"
    tail = "Math.  ^3,34-39-  Therefore,  behold,  I  send  unto  you"
    ref = gs._extract_luther_scripture_ref(tail)
    assert ref is not None
    # Prose text should be stripped
    assert "Therefore" not in ref
    # Trailing hyphen should be stripped
    assert not ref.endswith("-")


def test_extract_luther_scripture_ref_hyphen_strip_only_trailing():
    # Normal verse range (hyphen in middle) should not be affected
    ref = gs._extract_luther_scripture_ref("Romans 12, 1-6")
    assert ref == "Romans 12, 1-6"


def test_extract_luther_scripture_ref_comma_separator():
    # DjVu vol 4 Gospel Sermons: "Math,  2, 1-12,  Nozv zvhen Jesus was born..."
    # comma + 2 spaces + uppercase = sentence break; ref is "Math,  2, 1-12"
    tail = "Math,  2, 1-12,  Nozv  zvhcn  Jesus  zvas  horn  in  Bethle-"
    ref = gs._extract_luther_scripture_ref(tail)
    assert ref is not None
    assert "Nozv" not in ref
    assert "Bethle" not in ref
    # Should contain the book and chapter/verse
    assert "Math" in ref
    assert "1-12" in ref or "2" in ref


def test_extract_luther_scripture_ref_comma_digit_continuation():
    # DjVu vol 8 regression: "John  Jf,  Jf6-5Ii,  Be came therefore..."
    # "Jf" = OCR "4", "Jf6" = OCR "46" — comma-break where next word has a digit
    # must NOT be treated as prose break; ref should contain "Jf6" (verse number)
    tail = "John  Jf,  Jf6-5Ii,  Be  came  therefore  again  unto  Cana"
    ref = gs._extract_luther_scripture_ref(tail)
    # The ref must not be cut at the first comma ("John  Jf" has no digits → None)
    # Instead it should extend to the comma before prose ("Be  came  therefore")
    assert ref is not None
    assert "Jf6" in ref or "Jf" in ref  # must include the OCR'd digit continuation
    assert "Be" not in ref or "therefore" not in ref  # prose must be stripped


# ---------------------------------------------------------------------------
# _smart_title
# ---------------------------------------------------------------------------


def test_smart_title_collapses_double_spaces():
    # DjVu OCR double-spacing must be normalised to single spaces
    assert smart_title("THE   NOBLEMAN'S   SON") == "The Nobleman's Son"


def test_smart_title_no_apostrophe_capital():
    # Python str.title() capitalises after apostrophes ("Nobleman'S"); _smart_title must not
    assert smart_title("GOD'S GRACE") == "God's Grace"
    assert smart_title("CHRIST'S ANSWER") == "Christ's Answer"
    assert smart_title("LUTHER'S SERMONS") == "Luther's Sermons"


def test_smart_title_preserves_leading_number():
    # Page-header fallback titles include a leading page number
    assert smart_title("94  LUTHER'S  EPISTLE  SERMONS") == "94 Luther's Epistle Sermons"


def test_smart_title_plain_text_apostrophe():
    # Newman PG plain-text titles may have mixed-case apostrophe words
    assert smart_title("the lord's prayer") == "The Lord's Prayer"
