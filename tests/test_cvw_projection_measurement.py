"""Truthful fixture metrics and fail-closed projection measurement."""
import hashlib

import pytest

from cvw_app import projection_measurement as meter
from cvw_app.bounded_tei_projection import build_projection, renderer_version
from cvw_app.bounded_xml_index import build_index
from cvw_app.renderer_nodes import RendererError


@pytest.fixture
def fixture_master(tmp_path):
    payload = ('<TEI><text><body><div xml:id="same"><head>One</head>'
               '<p>Café α</p></div><div xml:id="same"><head>Two</head>'
               '<p>Other text</p></div></body></text></TEI>').encode('utf-8')
    master = tmp_path / 'master.xml'
    master.write_bytes(payload)
    return master, payload, hashlib.sha256(payload).hexdigest()


def test_observer_reports_actual_utf8_renderer_input_without_output_change(fixture_master):
    master, payload, digest = fixture_master
    index = build_index(master, expected_sha256=digest, renderer_version=renderer_version())
    observed = []
    normal = build_projection(master, index, expected_sha256=digest)
    measured = build_projection(master, index, expected_sha256=digest,
                                observe_render_input=observed.append)
    assert measured == normal
    assert observed == [len(payload)]
    assert len(payload) > len(payload.decode('utf-8'))


def test_fixture_measurement_counts_and_boundaries(fixture_master, monkeypatch):
    master, payload, digest = fixture_master
    ticks = iter([0., 2., 2., 7.] + [float(n) for i in range(10) for n in (7+i, 8+i)])
    monkeypatch.setattr(meter, 'perf_counter', lambda: next(ticks))
    result = meter.measure_fixture_projection(master, expected_sha256=digest,
                                              location='start', segment=0)
    assert result['index_parser_input_bytes'] == len(payload)
    assert result['full_renderer_input_bytes'] == len(payload)
    assert result['index_admission_seconds'] == 2
    assert result['first_view_after_index_admission_seconds'] == 5
    assert result['navigation_seconds'] == [1.] * 10
    assert result['navigation_serialized_response_bytes'] == [result['first_view_serialized_response_bytes']] * 10
    assert result['retained_index_and_projection_bytes'] > result['retained_after_index_admission_bytes'] > 0
    assert result['master_sha256'] == digest
    assert len(result['projection_integrity_sha256']) == len(result['selected_response_sha256']) == 64
    assert result['budgets'] == {'first_view_pass': True, 'warm_navigation_pass': True,
                                 'warm_trials_within_budget': 10}
    assert result['route_activated'] is False
    assert result['fresh_process_repeats'] == 0
    assert master.read_bytes() == payload


def test_budget_failures_and_nine_of_ten_rule():
    result = meter.evaluate_budgets(5.001, (1.,) * 9 + (1.001,))
    assert not result.first_view_pass
    assert result.warm_navigation_pass
    assert result.warm_trials_within_budget == 9
    assert not meter.evaluate_budgets(0., (1.,) * 8 + (1.001,) * 2).warm_navigation_pass


@pytest.mark.parametrize('duration', [float('nan'), float('inf'), -1., True])
def test_invalid_durations_cannot_pass(duration):
    with pytest.raises(ValueError, match='finite nonnegative'):
        meter.evaluate_budgets(duration, (0.,) * 10)


def test_incomplete_navigation_matrix_cannot_pass():
    with pytest.raises(ValueError, match='exactly ten'):
        meter.evaluate_budgets(0., (0.,) * 9)


def test_stale_fixture_cannot_emit_receipt(fixture_master):
    master, _, digest = fixture_master
    master.write_bytes(b'<TEI/>')
    with pytest.raises(RendererError, match='sha256'):
        meter.measure_fixture_projection(master, expected_sha256=digest,
                                          location='start', segment=0)


@pytest.mark.parametrize('location,segment', [('missing', 0), ('start', 10000)])
def test_unknown_selection_cannot_emit_receipt(fixture_master, location, segment):
    master, _, digest = fixture_master
    with pytest.raises(RendererError, match='unknown global'):
        meter.measure_fixture_projection(master, expected_sha256=digest,
                                          location=location, segment=segment)
