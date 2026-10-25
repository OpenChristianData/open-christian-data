"""Work boundaries must survive adversarial changes inside a single source file."""
import copy
import errno
import hashlib
import json
import os
from pathlib import Path

import pytest

from ocd_kernel.lib import path_io
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import validate_record
from ocd_kernel.library.source_selection import (
    derive_source_carrier_inventory,
    verify_complete_source_accounting,
    verify_source_selection,
    verify_selection_union,
)


@pytest.fixture
def selection(tmp_path):
    raw = b'<ThML><ThML.body><div1 id="credits" title="Credits"><p id="credit">Source credit.</p></div1><div1 id="a" title="First Work"><p>Alpha.</p></div1><div1 id="b" title="Second Work"><p>Beta.</p></div1></ThML.body></ThML>'
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'raw/source.xml').write_bytes(raw)
    acquired = dict(schema_version='2.0', acquisition_id='source', edition_id='edition', provider='Fixture', url='https://example.test/source',
        retained_files=[dict(path='raw/source.xml', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), media_type='application/xml')],
        source_selection=dict(selection_id='first-v1', work_id='first', member_path='raw/source.xml',
            units=[dict(native_id='a', title='First Work', role='body')],
            dependencies=[dict(native_id='credit', text_sha256=hashlib.sha256(b'Source credit.').hexdigest(), purpose='source-credit')]))
    work = dict(schema_version='2.0', work_id='first', title='First Work', evidence=['raw/source.xml#a','raw/source.xml#credit'], textual_forms=[])
    validate_record('acquisition', acquired)
    validate_record('work', work)
    return tmp_path, acquired, work


def test_child_valid_while_sibling_is_unselected(selection):
    root, acquisition, work = selection
    result = verify_source_selection(acquisition, work, root=root)
    assert result['selected_native_ids'] == ['a']
    assert result['dependencies'][0]['text'] == 'Source credit.'


def test_ordered_multi_unit_work_selection_is_valid(selection):
    root, acquisition, work = selection
    acquisition = copy.deepcopy(acquisition)
    acquisition['source_selection']['selection_id'] = 'multi-v1'
    acquisition['source_selection']['units'].append(
        dict(native_id='b', title='Second Work', role='body')
    )
    work['evidence'].append('raw/source.xml#b')
    result = verify_source_selection(acquisition, work, root=root)
    assert result['selected_native_ids'] == ['a', 'b']


@pytest.mark.parametrize('change', ['id-only', 'id-and-heading', 'missing-credit', 'wrong-credit-hash', 'duplicate-unit', 'wrong-work'])
def test_selection_corruption_fails(selection, change):
    root, acquired, work = selection
    acquired = copy.deepcopy(acquired)
    value = acquired['source_selection']
    if change in ('id-only', 'id-and-heading'):
        value['units'][0]['native_id'] = 'b'
        if change == 'id-and-heading':
            value['units'][0]['title'] = 'Second Work'
    elif change == 'missing-credit':
        value['dependencies'] = []
    elif change == 'wrong-credit-hash':
        value['dependencies'][0]['text_sha256'] = '0' * 64
    elif change == 'duplicate-unit':
        value['units'].append(dict(value['units'][0]))
    else:
        value['work_id'] = 'second'
    with pytest.raises(PipelineError, match='source selection'):
        verify_source_selection(acquired, work, root=root)


def test_union_positive_and_negative_controls():
    expected = {'a': 'first', 'b': 'second'}
    children = [dict(work_id='first', selected_native_ids=['a']), dict(work_id='second', selected_native_ids=['b'])]
    verify_selection_union(expected, children)
    for broken in (children[:1], children + children[:1], [children[0], dict(work_id='first', selected_native_ids=['b'])]):
        with pytest.raises(PipelineError, match='selection union'):
            verify_selection_union(expected, broken)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "First Work "),
        ("title", "First W0rk"),
        ("native_id", "b"),
    ],
)
def test_selection_rejects_near_distinct_or_sibling_unit(selection, field, value):
    root, acquisition, work = selection
    acquisition = copy.deepcopy(acquisition)
    acquisition["source_selection"]["units"][0][field] = value
    with pytest.raises(PipelineError, match="source selection"):
        verify_source_selection(acquisition, work, root=root)


def test_selection_rejects_missing_source_context(selection):
    root, acquisition, work = selection
    acquisition = copy.deepcopy(acquisition)
    work = copy.deepcopy(work)
    work["textual_forms"] = [
        {
            "textual_form_id": "english",
            "language": "en",
            "editions": [
                {
                    "edition_id": "edition",
                    "title": "First Work",
                    "category": "prose",
                    "language": "en",
                    "acquisition_ids": ["source"],
                    "containing_source": {
                        "title": "Wrong source title",
                        "locator": "raw/source.xml",
                        "evidence": ["raw/source.xml"],
                    },
                }
            ],
        }
    ]
    with pytest.raises(PipelineError, match="source selection"):
        verify_source_selection(acquisition, work, root=root)


def test_complete_accounting_derives_source_order_and_allows_pending_sibling(selection):
    root, acquisition, _ = selection
    assert [row["native_id"] for row in derive_source_carrier_inventory(acquisition, root=root)] == [
        "credits", "a", "b"
    ]
    result = verify_complete_source_accounting(
        acquisition,
        [dict(work_id="first", selected_native_ids=["a"]),
         dict(work_id="second", selected_native_ids=["b"])],
        [dict(native_id="credits", disposition="shared-credit-context"),
         dict(native_id="a", disposition="selected", work_id="first"),
         dict(native_id="b", disposition="selected", work_id="second")],
        root=root,
    )
    assert [row["position"] for row in result] == [0, 1, 2]


@pytest.mark.parametrize(
    "mutation",
    ["omitted", "duplicated", "reordered", "misassigned"],
)
def test_complete_accounting_rejects_envelope_mutations(selection, mutation):
    root, acquisition, _ = selection
    children = [dict(work_id="first", selected_native_ids=["a"]),
                dict(work_id="second", selected_native_ids=["b"])]
    accounting = [dict(native_id="credits", disposition="shared-credit-context"),
                  dict(native_id="a", disposition="selected", work_id="first"),
                  dict(native_id="b", disposition="selected", work_id="second")]
    if mutation == "omitted":
        accounting.pop()
    elif mutation == "duplicated":
        accounting.insert(2, dict(accounting[1]))
    elif mutation == "reordered":
        accounting[1], accounting[2] = accounting[2], accounting[1]
    else:
        accounting[1]["work_id"] = "second"
    with pytest.raises(PipelineError, match="source accounting"):
        verify_complete_source_accounting(acquisition, children, accounting, root=root)


def test_deep_retained_source_reads_use_extended_paths(selection, monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows extended-length filesystem regression")

    root, acquisition, work = selection
    library_root = root / ("library-" * 16) / ("data-" * 16)
    source = library_root / "raw" / "source.xml"
    source_bytes = (root / "raw" / "source.xml").read_bytes()
    path_io.io_path(source).parent.mkdir(parents=True)
    path_io.io_path(source).write_bytes(source_bytes)
    config = root / ".ocd-storage.json"
    path_io.io_path(config).write_text(
        json.dumps({"library_root": str(library_root)}), encoding="utf-8"
    )
    assert len(str(source)) >= 260

    original_open = Path.open

    def reject_unprefixed_deep_paths(path, *args, **kwargs):
        value = os.fsdecode(os.fspath(path))
        if len(value) >= 260 and not value.startswith("\\\\?\\"):
            raise OSError(errno.ENAMETOOLONG, "legacy path rejected", value)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_unprefixed_deep_paths)

    result = verify_source_selection(acquisition, work, root=root)
    assert result["selected_native_ids"] == ["a"]
    inventory = derive_source_carrier_inventory(acquisition, root=root)
    assert [item["native_id"] for item in inventory] == ["credits", "a", "b"]
