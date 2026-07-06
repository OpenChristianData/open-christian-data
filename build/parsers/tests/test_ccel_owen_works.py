"""test_ccel_owen_works.py
Tests for ccel_owen_works.py -- Phase 2 TDD (written before the parser).

Five test groups:
  1. preprocess_thml(raw_bytes) -> str
  2. get_all_text(elem) -> str
  3. is_editorial_div(div_elem, is_top_level: bool) -> bool
  4. extract_heading(div_elem) -> tuple[str, str]  (label, title)
  5. build_output_id(slug) -> str  +  WORK_CONFIG coverage

All div/XML fixtures use real structures from the 5 downloaded Owen XML files
(raw/ccel/owen/*.xml).  Entity-replacement fixtures use minimal synthetic bytes
because the 5 downloaded files encode Unicode directly (no HTML entities).

Run with:  py -3 -m pytest build/parsers/tests/test_ccel_owen_works.py -v
"""

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.parsers.ccel_owen_works import (  # noqa: E402
    preprocess_thml,
    get_all_text,
    is_editorial_div,
    extract_heading,
    build_output_id,
    WORK_CONFIG,
)


# ===========================================================================
# Group 1: preprocess_thml(raw_bytes) -> str
# ===========================================================================
# DOCTYPE fixture anchored to real mort.xml multi-line DOCTYPE structure.
# The 5 downloaded Owen files encode Unicode directly (no HTML entities), so
# entity-replacement tests use minimal synthetic byte strings.

_MORT_DOCTYPE_BYTES = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<!DOCTYPE ThML PUBLIC \n'
    b'    "-//CCEL/DTD Theological Markup Language//EN"\n'
    b'    "http://www.ccel.org/dtd/ThML10.dtd">\n'
    b'<ThML><ThML.body><p>hello</p></ThML.body></ThML>'
)

_DOCTYPE_WITH_SUBSET_BYTES = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<!DOCTYPE ThML PUBLIC "-//CCEL//DTD//EN" "url.dtd" [\n'
    b'  <!ENTITY mdash "&#x2014;">\n'
    b']>\n'
    b'<ThML><ThML.body><p>hello</p></ThML.body></ThML>'
)


def _entity_bytes(entity: bytes) -> bytes:
    return b'<ThML><ThML.body><p>' + entity + b'</p></ThML.body></ThML>'


def test_preprocess_mdash_replaced():
    result = preprocess_thml(_entity_bytes(b'&mdash;'))
    assert '\u2014' in result
    assert '&mdash;' not in result


def test_preprocess_rsquo_replaced():
    result = preprocess_thml(_entity_bytes(b'&rsquo;'))
    assert '\u2019' in result
    assert '&rsquo;' not in result


def test_preprocess_nbsp_replaced():
    result = preprocess_thml(_entity_bytes(b'&nbsp;'))
    assert '\u00a0' in result
    assert '&nbsp;' not in result


def test_preprocess_doctype_multiline_stripped():
    """Real mort.xml multi-line DOCTYPE is stripped; surrounding XML is preserved."""
    result = preprocess_thml(_MORT_DOCTYPE_BYTES)
    assert '<!DOCTYPE' not in result
    assert '<ThML>' in result
    assert '<p>hello</p>' in result


def test_preprocess_doctype_with_internal_subset_stripped():
    """DOCTYPE with [...] internal subset is stripped (exercises re.DOTALL path)."""
    result = preprocess_thml(_DOCTYPE_WITH_SUBSET_BYTES)
    assert '<!DOCTYPE' not in result
    assert '<ThML>' in result


def test_preprocess_xml_entities_not_double_processed():
    """&amp; &lt; &gt; are XML built-ins -- ET resolves them as & < > correctly."""
    xml = b'<ThML><ThML.body><p>&amp; &lt; &gt;</p></ThML.body></ThML>'
    result = preprocess_thml(xml)
    root = ET.fromstring(result)
    text = root.findtext('./ThML.body/p')
    assert text == '& < >'


def test_preprocess_unknown_entity_silently_dropped():
    """Unknown entity &xyzzy; silently dropped -- no crash, surrounding text preserved."""
    xml = b'<ThML><ThML.body><p>before&xyzzy;after</p></ThML.body></ThML>'
    result = preprocess_thml(xml)
    assert 'before' in result
    assert 'after' in result
    assert '&xyzzy;' not in result


def test_preprocess_no_entities_parses_cleanly():
    """Input with no entities parses cleanly -- minimal real div structure from mort.xml."""
    xml = (
        b'<ThML><ThML.body>'
        b'<div1 type="Work" id="i">'
        b'<div2 n="I" type="Chapter" title="Chapter I." id="i.iv">'
        b'<h1>Chapter I.</h1>'
        b'<p>Some content.</p>'
        b'</div2>'
        b'</div1>'
        b'</ThML.body></ThML>'
    )
    result = preprocess_thml(xml)
    root = ET.fromstring(result)
    assert root is not None


# ===========================================================================
# Group 2: get_all_text(elem) -> str
# ===========================================================================
# ET element trees built from real Owen XML tag patterns.

def test_get_all_text_note_excluded_tail_included():
    """<note> text excluded; tail text after </note> IS included."""
    elem = ET.fromstring('<p>before<note>footnote</note>after</p>')
    assert get_all_text(elem) == 'beforeafter'


def test_get_all_text_pb_excluded_tail_included():
    """<pb> text excluded; tail included -- page break pattern from mort.xml."""
    elem = ET.fromstring('<p>before<pb n="5" id="i.iv-Page_5" />after</p>')
    assert get_all_text(elem) == 'beforeafter'


def test_get_all_text_scripcontext_excluded():
    """<scripContext> text excluded (new Owen _SKIP_TAGS entry -- from sermons.xml)."""
    elem = ET.fromstring(
        '<div1><scripContext version="KJV" id="i-p0.1" /><p>content</p></div1>'
    )
    result = get_all_text(elem)
    assert 'content' in result
    assert 'KJV' not in result


def test_get_all_text_scripref_included():
    """<scripRef> inline text IS included -- from mort.xml Chapter I argument element."""
    elem = ET.fromstring(
        '<argument>laid in '
        '<scripRef osisRef="Bible:Rom.8.13">Rom. viii. 13</scripRef>'
        ' the words</argument>'
    )
    result = get_all_text(elem)
    assert 'Rom. viii. 13' in result
    assert 'laid in' in result


def test_get_all_text_name_included():
    """<name> inline text IS included -- Owen XML uses many name tags."""
    elem = ET.fromstring(
        '<p>the character of <name title="Owen, John">Owen</name>, if</p>'
    )
    result = get_all_text(elem)
    assert 'Owen' in result
    assert 'the character of' in result


def test_get_all_text_inline_formatting_included():
    """<em> <i> <span> inline formatting text IS included -- from mort.xml paragraph."""
    elem = ET.fromstring(
        '<p><span style="font-variant:small-caps">That</span> is <i>important</i>.</p>'
    )
    result = get_all_text(elem)
    assert 'That' in result
    assert 'important' in result


def test_get_all_text_nested_collapse():
    """Nested elements collapse correctly to a single concatenated string."""
    elem = ET.fromstring('<p>a<span>b<em>c</em>d</span>e</p>')
    assert get_all_text(elem) == 'abcde'


# ===========================================================================
# Group 3: is_editorial_div(div_elem, is_top_level: bool) -> bool
# ===========================================================================
# Div fixtures use real attribute values from the 5 downloaded Owen XML files.

# --- Should return True (editorial / exclude) ---

def test_editorial_div2_prefatory_note_mort():
    """div2 type='Preface' with 'Prefatory note.' heading is editorial (mort.xml)."""
    div = ET.fromstring(
        '<div2 type="Preface" title="Prefatory note." id="i.ii">'
        '<h1>Prefatory note.</h1>'
        '<p>Content.</p>'
        '</div2>'
    )
    assert is_editorial_div(div, is_top_level=False) is True


def test_editorial_div1_top_level_preface_sermons():
    """Top-level div1 type='Preface' is always editorial -- Goold collection preface (sermons.xml)."""
    div = ET.fromstring(
        '<div1 type="Preface" title="Preface" id="i">'
        '<scripContext version="KJV" id="i-p0.1" />'
        '<h2>Preface.</h2>'
        '<p>The two following volumes contain...</p>'
        '</div1>'
    )
    assert is_editorial_div(div, is_top_level=True) is True


def test_editorial_titlepage():
    """div2 type='Titlepage' is always editorial (mort.xml Titlepage)."""
    div = ET.fromstring(
        '<div2 type="Titlepage" title="Title page." id="i.i">'
        '<p>Title content</p>'
        '</div2>'
    )
    assert is_editorial_div(div, is_top_level=False) is True


def test_editorial_back():
    """div1 type='Back' is editorial (deathofdeath.xml Back div1)."""
    div = ET.fromstring(
        '<div1 type="Back" title="Indexes." id="ii">'
        '<h1>Indexes</h1>'
        '</div1>'
    )
    assert is_editorial_div(div, is_top_level=True) is True


def test_editorial_index():
    """div2 type='Index' is editorial (deathofdeath.xml Index of Scripture References)."""
    div = ET.fromstring(
        '<div2 type="Index" title="Index of Scripture References." id="ii.i">'
        '<h2>Index of Scripture References</h2>'
        '</div2>'
    )
    assert is_editorial_div(div, is_top_level=False) is True


def test_editorial_heading_matches_indexes():
    """div with first heading matching /^indexes?$/i is editorial."""
    div = ET.fromstring(
        '<div1 type="Back" title="Indexes" id="ii">'
        '<h1>Indexes</h1>'
        '</div1>'
    )
    assert is_editorial_div(div, is_top_level=True) is True


# --- Should return False (Owen's own / include) ---

def test_not_editorial_preface_own():
    """div2 type='Preface' with plain 'Preface.' heading is Owen's own (not editorial)."""
    div = ET.fromstring(
        '<div2 type="Preface" title="Preface." id="ii.i">'
        '<h2>Preface.</h2>'
        "<p>Owen's own preface.</p>"
        '</div2>'
    )
    assert is_editorial_div(div, is_top_level=False) is False


def test_not_editorial_to_the_reader():
    """div2 type='Preface' with 'To the reader.' heading is Owen's own (deathofdeath.xml)."""
    div = ET.fromstring(
        '<div2 type="Preface" title="To the reader." id="i.v">'
        '<h2>To the reader.</h2>'
        '<p>Reader,</p>'
        '</div2>'
    )
    assert is_editorial_div(div, is_top_level=False) is False


def test_not_editorial_to_the_right_honourable():
    """div2 type='Preface' with 'To the Right Honourable...' is Owen's own (deathofdeath.xml)."""
    div = ET.fromstring(
        '<div2 type="Preface"'
        ' title="To the Right Honourable Robert, Earl of Warwick."'
        ' id="i.iii">'
        '<h2>To the Right Honourable Robert, Earl of Warwick,</h2>'
        '<p>Content.</p>'
        '</div2>'
    )
    assert is_editorial_div(div, is_top_level=False) is False


def test_not_editorial_chapter():
    """div2 type='Chapter' is not editorial (mort.xml Chapter I div2)."""
    div = ET.fromstring(
        '<div2 n="I" type="Chapter" title="Chapter I." id="i.iv">'
        '<h1>Chapter I.</h1>'
        '<p>Content.</p>'
        '</div2>'
    )
    assert is_editorial_div(div, is_top_level=False) is False


def test_not_editorial_part():
    """div2 type='Part' is not editorial (deathofdeath.xml Book I div2)."""
    div = ET.fromstring(
        '<div2 n="I" type="Part" title="Book I." id="i.vii">'
        '<h1>Book I.</h1>'
        '</div2>'
    )
    assert is_editorial_div(div, is_top_level=False) is False


def test_not_editorial_sermon():
    """div3 type='Sermon' is not editorial (sermons.xml Sermon I div3)."""
    div = ET.fromstring(
        '<div3 n="I" type="Sermon" title="Sermon I. Acts xvi. 9." id="ii.i.v">'
        '<h2>Sermon I.  A vision of unchangeable, free mercy, in sending the means'
        ' of grace to undeserving sinners.</h2>'
        '</div3>'
    )
    assert is_editorial_div(div, is_top_level=False) is False


# ===========================================================================
# Group 4: extract_heading(div_elem) -> tuple[str, str]  (label, title)
# ===========================================================================
# Real div structures from the 5 downloaded Owen XML files.

def test_extract_heading_chapter_h2_with_title_attr():
    """div3 Chapter with <h2>Chapter I.</h2> + title attr (deathofdeath.xml)."""
    div = ET.fromstring(
        '<div3 n="I" type="Chapter"'
        ' title="Chapter I. In general of the end of the death of Christ'
        ' as it is in the Scripture proposed."'
        ' id="i.vii.i">'
        '<h2>Chapter I.</h2>'
        '<argument>In general...</argument>'
        '</div3>'
    )
    label, title = extract_heading(div)
    assert label == 'Chapter I'
    # h2 "Chapter I." matches HEADING_RE; group 2 is empty. title= attr consulted for subtitle.
    assert title == 'In general of the end of the death of Christ as it is in the Scripture proposed'


def test_extract_heading_chapter_h1_mort_style():
    """div2 Chapter with <h1> heading (mort.xml -- chapters at div2 level use h1)."""
    div = ET.fromstring(
        '<div2 n="I" type="Chapter" title="Chapter I." id="i.iv">'
        '<h1>Chapter I.</h1>'
        '<argument>The foundation of the whole ensuing discourse.</argument>'
        '</div2>'
    )
    label, title = extract_heading(div)
    assert label == 'Chapter I'


def test_extract_heading_part_book_i():
    """div2 Part with h1 'Book I.' -> label='Book I', title='' (deathofdeath.xml)."""
    div = ET.fromstring(
        '<div2 n="I" type="Part" title="Book I." id="i.vii">'
        '<h1>Book I.</h1>'
        '<div3 n="I" type="Chapter" id="i.vii.i"><h2>Chapter I.</h2></div3>'
        '</div2>'
    )
    label, title = extract_heading(div)
    assert label == 'Book I'
    assert title == ''


def test_extract_heading_part_i_of_communion():
    """div2 Part with h1 'Part I. Of Communion...' -> label + title split (communion.xml)."""
    div = ET.fromstring(
        '<div2 n="I" type="Part" title="Part I. Of Communion with God the Father." id="i.vi">'
        '<h1>Part I. Of Communion with each Person distinctly \u2014'
        ' Of Communion with the Father</h1>'
        '</div2>'
    )
    label, title = extract_heading(div)
    assert label == 'Part I'
    assert 'Communion' in title


def test_extract_heading_sermon_i():
    """div3 Sermon with h2 'Sermon I. A vision...' -> label + title split (sermons.xml)."""
    div = ET.fromstring(
        '<div3 n="I" type="Sermon" title="Sermon I. Acts xvi. 9." id="ii.i.v">'
        '<h2>Sermon I.  A vision of unchangeable, free mercy, in sending the means'
        ' of grace to undeserving sinners.</h2>'
        '</div3>'
    )
    label, title = extract_heading(div)
    assert label == 'Sermon I'
    assert 'vision' in title


def test_extract_heading_no_heading_elements():
    """div with no heading elements returns ('', '')."""
    div = ET.fromstring(
        '<div2 type="Chapter" title="" id="x">'
        '<p>Content only, no heading element present.</p>'
        '</div2>'
    )
    label, title = extract_heading(div)
    assert label == ''
    assert title == ''


def test_extract_heading_fallback_title_attr():
    """div with title= attr but no heading element uses title attr (algorithm step 4)."""
    div = ET.fromstring(
        '<div3 n="I" type="Chapter" title="Chapter I. Of the foundation." id="x">'
        '<p>Content only.</p>'
        '</div3>'
    )
    label, title = extract_heading(div)
    # No h1/h2 present -> step 4: HEADING_RE on title attr value
    # "Chapter I. Of the foundation." -> label='Chapter I', title='Of the foundation'
    assert label == 'Chapter I'
    assert 'foundation' in title


# ===========================================================================
# Group 5: build_output_id(slug) -> str  +  WORK_CONFIG coverage
# ===========================================================================

_NAMED_MAPPINGS = [
    ('mort',              'john-owen-mortification'),
    ('deathofdeath',      'john-owen-death-of-death'),
    ('communion',         'john-owen-communion'),
    ('pneum',             'john-owen-pneumatologia'),
    ('just',              'john-owen-justification'),
    ('indwellingsin',     'john-owen-indwelling-sin'),
    ('glory',             'john-owen-glory'),
    ('spirituallyminded', 'john-owen-spiritually-minded'),
    ('temptation',        'john-owen-temptation'),
    ('sin_grace',         'john-owen-sin-grace'),
    ('catechisms',        'john-owen-two-catechisms'),
]


@pytest.mark.parametrize("ccel_id,expected_id", _NAMED_MAPPINGS)
def test_work_config_named_ccel_id_to_output_id(ccel_id, expected_id):
    """WORK_CONFIG slug for ccel_id produces the expected output ID."""
    entry = next((w for w in WORK_CONFIG if w['ccel_id'] == ccel_id), None)
    assert entry is not None, f"ccel_id '{ccel_id}' not found in WORK_CONFIG"
    assert build_output_id(entry['slug']) == expected_id


@pytest.mark.parametrize("entry", WORK_CONFIG, ids=[w['ccel_id'] for w in WORK_CONFIG])
def test_work_config_all_produce_valid_id(entry):
    """All 32 WORK_CONFIG entries produce a 'john-owen-{slug}' output ID."""
    output_id = build_output_id(entry['slug'])
    assert output_id == f"john-owen-{entry['slug']}"
    assert output_id.startswith('john-owen-')


def test_work_config_has_32_entries():
    """WORK_CONFIG contains exactly 32 works."""
    assert len(WORK_CONFIG) == 32


def test_work_config_all_have_required_keys():
    """All 32 WORK_CONFIG entries have required keys: slug, ccel_id, title, work_kind."""
    required = {'slug', 'ccel_id', 'title', 'work_kind'}
    for entry in WORK_CONFIG:
        missing = required - set(entry.keys())
        assert not missing, f"Entry {entry.get('ccel_id')} missing keys: {missing}"
