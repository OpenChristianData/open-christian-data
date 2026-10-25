"""Portable grammar and authority checks for maintained native projection routes.

These synthetic checks prove bounded route behavior; retained-book fidelity stays
with each route's complete source and independent observer evidence.
"""

from hashlib import sha256
import importlib
import json
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET

from lxml import etree
import pytest

from ocd_kernel.library._common import PipelineError


PREFIX = "ocd_kernel.projection.categories."
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"


def test_calvin_joshua_requires_acceptance_before_reading_master():
    from ocd_kernel.projection.categories import calvin_joshua_source_native as route

    with pytest.raises(PipelineError, match="Joshua acceptance authority is missing"):
        route._require_identity({}, Path("unread-master.xml"))


def test_cassiodorus_literal_tail_carrier_is_checked_by_both_parsers():
    from ocd_kernel.projection.categories import cassiodorus_source_profile as route

    node = ET.Element(NS + "ab", {"type": "source-tail-text", "n": "1.2.tail",
                                  XML + "id": "source-tail-text-1.2", XML + "space": "preserve"})
    node.text = "  retained tail\n"
    route.check_content_node_et(node)
    route.check_content_node_lxml(etree.fromstring(ET.tostring(node)))
    node.attrib.pop(XML + "space")
    with pytest.raises(ValueError, match="source-native block carrier"):
        route.check_content_node_et(node)
    with pytest.raises(ValueError, match="source-native block carrier"):
        route.check_content_node_lxml(etree.fromstring(ET.tostring(node)))


def test_coppens_cover_admission_is_exact_and_identity_cannot_fall_back():
    from ocd_kernel.projection.categories import coppens_pg70790_source_profile as route

    node = ET.Element(NS + "graphic", {"n": "3.2", XML + "id": "img_images_cover.jpg",
                                      "rend": "source-class:ig001 source-alt-empty", "url": "images/cover.jpg"})
    assert route.graphic_allowed(node)
    node.set("url", "https://example.org/cover.jpg")
    assert not route.graphic_allowed(node)
    assert route.select(Path("unread"), {"identity": {"work_id": "unrelated"}}) is None
    with pytest.raises(PipelineError, match="profile identity differs"):
        route.select(Path("unread"), {"identity": {**route.IDENTITY, "edition_id": "changed"}})


def test_creeds_body_boundary_rejects_ambiguous_header():
    from ocd_kernel.projection.categories import creeds_json_lib062_remaining_profile as route

    assert route._body(b"<TEI><teiHeader></teiHeader><text>Words</text></TEI>") == b"<text>Words</text></TEI>"
    for invalid in (b"<TEI><text>Words</text></TEI>", b"</teiHeader></teiHeader><text/>"):
        with pytest.raises(PipelineError, match="TEI header boundary differs"):
            route._body(invalid)


def test_daily_light_readable_lines_preserve_breaks_and_independent_rendering():
    from ocd_kernel.projection.categories import daily_light as route

    raw = b'<p xmlns="http://www.tei-c.org/ns/1.0"><hi>Morning</hi>  Words <lb/> next <ref>John 1:1</ref>.</p>'
    assert route._render_et(ET.fromstring(raw)) == "Morning Words\nnext John 1:1."
    assert route._render_lxml(etree.fromstring(raw)) == "Morning Words\nnext John 1:1."
    for raw in (b'<p xmlns="http://www.tei-c.org/ns/1.0"><note>unmapped</note></p>',
                b'<p xmlns="http://www.tei-c.org/ns/1.0"><lb>hidden words</lb></p>'):
        with pytest.raises(PipelineError, match="Daily Light"):
            route._render_et(ET.fromstring(raw))


@pytest.mark.parametrize("name", ["strong_vol2_source_lines", "strong_complete_group_profile",
                                  "l599_slave_trade_source_profile", "tyerman_whitefield_source_profile"])
def test_exact_source_routes_reject_changed_master_and_leave_unrelated_work_generic(name):
    route = importlib.import_module(PREFIX + name)
    context = dict(language="en", category="prose", collection=False,
                   allow_acceptance_metadata=True, projection_profile=None, source_base=None)
    if name == "strong_complete_group_profile":
        context["acquisition_id"] = route.ACQUISITION
    assert route.route({"work_id": "unrelated"}, b"unreviewed", **context) is False
    with pytest.raises(ValueError, match="exact|reviewed"):
        route.route(route.IDENTITY, b"unreviewed", **context)


def test_fox_known_profile_cannot_attach_to_unrelated_work_or_changed_master():
    from ocd_kernel.projection.categories import fox_pg43031_source_profile as route

    context = dict(language=route.LANGUAGE, category=route.CATEGORY, collection=False,
                   projection_profile=route.PROFILE, allow_acceptance_metadata=True)
    with pytest.raises(ValueError, match="another accepted work"):
        route.route(b"unreviewed", identity={"work_id": "unrelated"}, **context)
    with pytest.raises(ValueError, match="exact accepted master"):
        route.route(b"unreviewed", identity=route.IDENTITY, **context)


@pytest.mark.parametrize("name,label", [("geneva", "Geneva"), ("leeser", "Leeser"), ("tyndale", "Tyndale")])
def test_source_native_bible_producer_and_observer_reject_identity_before_source_access(name, label):
    producer = importlib.import_module(PREFIX + name + "_native_bible")
    observer = importlib.import_module(PREFIX + name + "_native_bible_check")
    context = dict(root=Path("unread-root"), identity={"work_id": "unrelated"},
                   representation_revision="fixture", edition_title="Fixture")
    with pytest.raises(PipelineError, match=label + " exact identity differs"):
        producer.project_document(Path("unread-master.xml"), **context)
    errors = observer.check_document(Path("unread-master.xml"), [], {}, **context)
    assert len(errors) == 1 and label in errors[0] and "identity differs" in errors[0]


def test_guyon_known_work_requires_exact_accepted_identity_before_source_access():
    from ocd_kernel.projection.categories import guyon_source_profile as route

    kwargs = dict(category="prose", collection=False, projection_profile=None)
    assert route.select_accepted({"identity": {"work_id": "unrelated"}}, **kwargs) is None
    context = {"identity": {**route.IDENTITY, "edition_id": "changed"}, "accepted": {}}
    with pytest.raises(ValueError, match="accepted identity or source-member-set authority"):
        route.select_accepted(context, **kwargs)


def test_hymnary_original_csv_line_endings_and_spans_are_not_normalized():
    from ocd_kernel.projection.categories import hymnary_pd_native as route

    raw = b'<seg xmlns="http://www.tei-c.org/ns/1.0" corresp="oldest_pd_instances.csv#bytes-2-8">a<lb n="CRLF"/>b<lb n="CR"/>c<lb n="LF"/>d</seg>'
    assert route._literal_et(ET.fromstring(raw)) == "a\r\nb\rc\nd"
    assert route._literal_lxml(etree.fromstring(raw)) == "a\r\nb\rc\nd"
    assert route._span(ET.fromstring(raw)) == "oldest_pd_instances.csv#bytes-2-8"
    for value in ("oldest_pd_instances.csv#bytes-8-2", "other.csv#bytes-2-8"):
        node = ET.fromstring(raw)
        node.set("corresp", value)
        with pytest.raises(PipelineError, match="original CSV field span"):
            route._span(node)


def test_native_reference_policy_rejects_changed_bytes(tmp_path, monkeypatch):
    from ocd_kernel.projection.categories import lib025_native_reference as route

    path = tmp_path / "policy.json"
    raw = b'{"fixture":true}'
    path.write_bytes(raw)
    monkeypatch.setattr(route, "POLICY_PATH", path)
    monkeypatch.setattr(route, "POLICY_SHA", sha256(raw).hexdigest())
    assert route.policy() == {"fixture": True}
    path.write_bytes(b'{"fixture":false}')
    with pytest.raises(ValueError, match="root-reviewed policy pin"):
        route.policy()


def test_native_reference_accepted_route_requires_actual_promotion(tmp_path, monkeypatch):
    from ocd_kernel.projection.categories import lib025_native_reference_accepted as route
    from ocd_kernel.tei import acceptance

    monkeypatch.setattr(acceptance, "validate_acceptance", lambda *args, **kwargs: {"promotion": {"status": "unpromoted"}})
    with pytest.raises(PipelineError, match="requires actual promoted acceptance"):
        route.metadata(tmp_path, tmp_path / "unpromoted.json")


def test_native_reference_independent_xml_observer_rejects_entity_declarations(tmp_path):
    from ocd_kernel.projection.categories import lib025_native_reference_observer as route

    path = tmp_path / "reference.xml"
    raw = b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text>Words</text></TEI>'
    path.write_bytes(raw)
    seen = []
    assert route.parse(path, lambda tag, attrs: seen.append(tag), lambda tag: None) == sha256(raw).hexdigest()
    assert seen == ["http://www.tei-c.org/ns/1.0}TEI", "http://www.tei-c.org/ns/1.0}text"]
    path.write_bytes(b'<!DOCTYPE TEI [<!ENTITY x "invented">]><TEI>&x;</TEI>')
    with pytest.raises(ValueError, match="rejects DTD/entity declarations"):
        route.parse(path, lambda *args: None, lambda *args: None)


@pytest.mark.parametrize("name", ["lib040_augustine_divisions", "lib040_harmony"])
def test_augustine_bound_evidence_rejects_hash_or_length_drift(tmp_path, name):
    route = importlib.import_module(PREFIX + name)
    path = tmp_path / "evidence.json"
    raw = b'{"fixture":"bound"}'
    path.write_bytes(raw)
    binding = {"path": path.name, "bytes": len(raw), "sha256": sha256(raw).hexdigest()}
    assert route._bound_json(tmp_path, binding) == {"fixture": "bound"}
    for changed in ({**binding, "bytes": len(raw) + 1}, {**binding, "sha256": "0" * 64}):
        with pytest.raises(PipelineError, match="evidence binding differs"):
            route._bound_json(tmp_path, changed)


def test_lib061_recognized_collection_cannot_fall_back_on_changed_identity():
    from ocd_kernel.projection.categories import lib061_toml_native as route

    assert route.route({"acceptance": {"identity": {"work_id": "unrelated"}}}) is None
    metadata = {"acceptance": {"identity": {**route.IDENTITY, "edition_id": "changed"}}}
    with pytest.raises(PipelineError, match="exact retained collection"):
        route.route(metadata)


@pytest.mark.parametrize("name,reason", [("liturgies_chrysostom_check", "exact identity/profile/language"),
                                        ("liturgies_office_check", "exact profile, identity, and language")])
def test_independent_liturgy_profile_rejects_wrong_identity_before_reading_master(name, reason):
    route = importlib.import_module(PREFIX + name)
    errors = route.verify_document(Path("unread.xml"), [], {}, identity={"work_id": "unrelated"},
                                   language="en", representation_revision="fixture", edition_title="Fixture",
                                   projection_profile=route.PROFILE)
    assert len(errors) == 1 and reason in errors[0]


def test_pg20476_producer_and_observer_reject_unbound_source_before_master(tmp_path):
    from ocd_kernel.projection.categories import pg20476_hymns as producer
    from ocd_kernel.projection.categories import pg20476_hymns_check as observer

    retained = tmp_path / "source.html"
    retained.write_bytes(b"unbound source")
    context = dict(retained_path=retained, identity={"work_id": producer.WORK_ID}, language="eng",
                   representation_revision="fixture", edition_title="Fixture")
    with pytest.raises(PipelineError, match="retained source identity differs"):
        producer.project_pg20476_document(Path("unread.xml"), **context)
    assert observer.check_pg20476_document(Path("unread.xml"), [], {}, **context) == ["PG20476 source checker identity differs"]


def test_nave_literal_list_grammar_and_known_identity_are_closed():
    from ocd_kernel.projection.categories import topical_nave as route

    raw = f'<def xmlns="{NS[1:-1]}"> Lead  <lb/>line<list><item>Parent <ref type="osisRef" target="Gen.1.1">1:1</ref><list><item>Child</item></list> tail</item></list> End </def>'
    assert route._render_et(ET.fromstring(raw)) == " Lead  \nline\n  Parent 1:1\n    Child tail End "
    bad = ET.fromstring(f'<def xmlns="{NS[1:-1]}"><ref type="scripture" target="Gen.1.1">1:1</ref></def>')
    with pytest.raises(PipelineError, match="Nave literal reference"):
        route._render_et(bad)
    context = dict(identity={**route.IDENTITY, "edition_id": "changed"}, language="en",
                   representation_revision="fixture", edition_title=route.TITLE)
    with pytest.raises(PipelineError, match="exact native identity/context"):
        route.project_nave_native(Path("unread.xml"), **context)
    assert route.verify_nave_native(Path("unread.xml"), [], {}, **context) == ["unsupported-visible: Nave checker identity/context"]


def test_tyerman_john_both_traversals_require_complete_three_volume_envelope():
    from ocd_kernel.projection.categories import tyerman_john_group_profile as route

    raw = f'<TEI xmlns="{NS[1:-1]}"><teiHeader/><text><group/></text></TEI>'.encode()
    with pytest.raises(PipelineError, match="John source group envelope differs"):
        route.source_census_et(ET.fromstring(raw))
    with pytest.raises(ValueError, match="John source group envelope differs"):
        route.source_census_lxml(etree.fromstring(raw))


def test_whitefield_sermon_identity_is_required_before_master_access():
    from ocd_kernel.projection.categories import whitefield_retained as route

    with pytest.raises(PipelineError, match="Whitefield projection identity differs"):
        route.project(Path("unread.xml"), identity={"work_id": "unrelated", "edition_id": "unrelated"},
                      language="en", representation_revision="fixture", edition_title="Fixture")


def test_public_dispositions_independent_annotation_decode_rejects_changed_marker():
    from ocd_kernel.projection import native_public_dispositions as route

    detail = {"unit": "source-html-comment", "n": "3", "rend": "retained comment"}
    encoded = route.ANNOTATION + quote(json.dumps(detail, ensure_ascii=False, separators=(",", ":")), safe="")
    assert route._annotation(encoded, "3", "retained comment", "source-html-comment") == detail
    assert route._observed_annotation(encoded, "3", "retained comment", "source-html-comment") == detail
    for decoder in (route._annotation, route._observed_annotation):
        with pytest.raises(ValueError, match="annotation"):
            decoder(encoded, "4", "retained comment", "source-html-comment")
