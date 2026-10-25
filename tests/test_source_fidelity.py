"""Public-seam tests: conserved words alone do not prove faithful relationships."""
from __future__ import annotations

import json
from copy import deepcopy
from lxml import etree
import pytest

from build.lib.source_fidelity import compare, digest
from build.lib.source_fidelity_adapters import prepare
from build.lib.source_fidelity_mutations import qualify
from build.lib.source_parser_corroboration import corroborate
from build.tools.check_source_fidelity import verify, main

XML_SOURCE = b'<doc><div id="work"><p id="p1">before<i>emphasis</i>after<note>note</note>end</p><p id="p2">second</p></div></doc>'
XML_PROFILE = dict(adapter="xml-map", source_root_id="work", candidate_root_id="src-1", id_prefix="src-",
    tags={"div":"div", "p":"p", "i":"hi", "note":"note"}, attributes={},
    excluded_attributes={"id":"source selection/navigation identity replaced by occurrence correspondence"},
    fixed_attributes={"i":{"rend":"italic"}})
XML_TEI = b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader/><text><body><div xml:id="src-1"><p xml:id="src-2">before<hi xml:id="src-3" rend="italic">emphasis</hi>after<note xml:id="src-4">note</note>end</p><p xml:id="src-5">second</p></div></body></text></TEI>'
JSON_SOURCE = b'{"Metadata":{"Title":"Fixture"},"Data":[{"Number":1,"Question":"Same?","Answer":"Yes","Proofs":[]},{"Number":2,"Question":"Same?","Answer":"Yes","Proofs":[]}]}'
JSON_PROFILE = dict(adapter="catechism-json", work_id="fixture")
JSON_TEI = b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader/><text><body><div xml:id="lib062-fixture-body" type="catechism"><div xml:id="lib062-fixture-row-0001" type="question-unit" n="1"><label xml:id="lib062-fixture-row-0001-number" type="source-number">1</label><p xml:id="lib062-fixture-row-0001-question" ana="#question">Same?</p><p xml:id="lib062-fixture-row-0001-answer" ana="#answer">Yes</p><note xml:id="lib062-fixture-row-0001-proofs-empty" type="source-empty-array" n="Proofs"/></div><div xml:id="lib062-fixture-row-0002" type="question-unit" n="2"><label xml:id="lib062-fixture-row-0002-number" type="source-number">2</label><p xml:id="lib062-fixture-row-0002-question" ana="#question">Same?</p><p xml:id="lib062-fixture-row-0002-answer" ana="#answer">Yes</p><note xml:id="lib062-fixture-row-0002-proofs-empty" type="source-empty-array" n="Proofs"/></div></div></body></text></TEI>'


@pytest.mark.parametrize("source,candidate,profile", [(XML_SOURCE,XML_TEI,XML_PROFILE),(JSON_SOURCE,JSON_TEI,JSON_PROFILE)])
def test_baselines_and_claim_specific_mutations(source,candidate,profile):
    report = verify(source,candidate,profile,mutations=True)
    assert report["status"] == "pass", report
    qualification = report["mutation_qualification"]
    assert qualification["status"] == "pass", qualification
    assert qualification["rejected"] >= 7
    assert all(all(c["invariants"].values()) for c in qualification["cases"] if c["status"]=="rejected")
    assert report["coverage"]["counts"]["passed"] > 0
    assert report["coverage"]["counts"]["excluded"] > 0


def test_equal_text_different_owners_fails_attachment():
    tree = etree.fromstring(JSON_TEI)
    answers = tree.xpath('//*[@ana="#answer"]')
    left,right=answers
    first,second=left.getparent(),right.getparent()
    i,j=first.index(left),second.index(right)
    first.remove(left)
    second.remove(right)
    first.insert(i,right)
    second.insert(j,left)
    assert ''.join(tree.itertext()) == ''.join(etree.fromstring(JSON_TEI).itertext())
    report=verify(JSON_SOURCE,etree.tostring(tree),JSON_PROFILE)
    assert report["status"]=="fail"
    assert "attachment" in {f["rule"] for f in report["findings"]}
    assert "text" not in {f["rule"] for f in report["findings"]}


def test_inline_move_preserves_flat_text_but_fails():
    tree=etree.fromstring(XML_TEI)
    hi=tree.xpath('//*[@xml:id="src-3"]')[0]
    hi.text+=hi.tail
    hi.tail=''
    assert ''.join(tree.itertext())==''.join(etree.fromstring(XML_TEI).itertext())
    report=verify(XML_SOURCE,etree.tostring(tree),XML_PROFILE)
    assert {"text","inline-tail"} <= {f["rule"] for f in report["findings"]}


@pytest.mark.parametrize("source,profile,candidate", [
    (XML_SOURCE.replace(b'<p id="p1"',b'<p unknown="x" id="p1"'),XML_PROFILE,XML_TEI),
    (JSON_SOURCE.replace(b'"Answer":"Yes"',b'"Answer":"Yes","Unknown":null',1),JSON_PROFILE,JSON_TEI),
])
def test_unknown_source_features_prevent_complete_pass(source,profile,candidate):
    report=verify(source,candidate,profile)
    assert report["status"]=="incomplete"
    assert report["coverage"]["counts"]["unsupported"]==1


def test_false_or_stale_parser_evidence_cannot_certify():
    plan=prepare(XML_SOURCE,XML_PROFILE)
    evidence=corroborate(XML_SOURCE,"xml")
    evidence["source_sha256"]="0"*64
    assert compare(plan,XML_TEI,evidence)["status"]=="fail"
    evidence=corroborate(XML_SOURCE,"xml")
    evidence["status"]="fail"
    assert compare(plan,XML_TEI,evidence)["status"]=="fail"
    evidence["status"]="unsupported"
    assert compare(plan,XML_TEI,evidence)["status"]=="incomplete"


def test_mutations_not_credited_for_failing_baseline():
    plan=prepare(XML_SOURCE,XML_PROFILE)
    result=qualify(plan,XML_TEI.replace(b'emphasis',b'changed'),corroborate(XML_SOURCE,"xml"))
    assert result["status"]=="not-run" and result["cases"]==[]


def test_no_mapped_attribute_can_be_overwritten():
    profile=deepcopy(XML_PROFILE)
    profile["attributes"]={"a":"rend","b":"rend"}
    with pytest.raises(ValueError,match="conflicting source mappings"):
        prepare(XML_SOURCE.replace(b'<p id="p1"',b'<p a="x" b="y" id="p1"'),profile)
    profile["attributes"]={"a":"rend"}
    with pytest.raises(ValueError,match="fixed/source attribute collision"):
        prepare(XML_SOURCE.replace(b'<i>',b'<i a="other">'),profile)


def test_source_links_are_remapped_by_native_identity_and_unknown_targets_uncovered():
    source=b'<d><p id="root"><a href="#second">link</a><p id="second">target</p></p></d>'
    profile=dict(adapter="xml-map",source_root_id="root",candidate_root_id="src-1",id_prefix="src-",
        tags={"p":"p","a":"ref"},attributes={"href":"target"},excluded_attributes={"id":"ordinal correspondence"})
    plan=prepare(source,profile)
    assert plan.carriers[1].attributes["target"]=="#src-3"
    broken=prepare(source.replace(b'#second',b'#missing'),profile)
    assert any(c["disposition"]=="unsupported" for c in broken.coverage.values())


@pytest.mark.parametrize("source_tokens,candidate_tokens", [
    (b'https://example.test #inside', b'https://example.test #src-3'),
    (b'#inside https://example.test', b'#src-3 https://example.test'),
])
def test_mixed_external_and_local_link_tokens_use_source_target_identity(source_tokens, candidate_tokens):
    source = (b'<d><p id="work"><a href="' + source_tokens +
              b'">link</a><p id="inside">target</p></p></d>')
    profile = dict(adapter="xml-map", source_root_id="work", candidate_root_id="src-1",
                   id_prefix="src-", tags={"p": "p", "a": "ref"},
                   attributes={"href": "target"}, excluded_attributes={"id": "ordinal"})
    candidate = (b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader>'
                 b'<p xml:id="inside">wrong target</p></teiHeader><text><body>'
                 b'<p xml:id="src-1"><ref xml:id="src-2" target="' + source_tokens +
                 b'">link</ref><p xml:id="src-3">target</p></p></body></text></TEI>')
    assert verify(source, candidate, profile)["status"] == "fail"
    corrected = candidate.replace(source_tokens, candidate_tokens)
    assert verify(source, corrected, profile)["status"] == "pass"


def test_duplicate_native_source_link_identity_blocks_mapping():
    source = b'<d><p id="inside">outside</p><p id="work"><a href="#inside">link</a><p id="inside">target</p></p></d>'
    profile = dict(adapter="xml-map", source_root_id="work", candidate_root_id="src-1",
                   id_prefix="src-", tags={"p": "p", "a": "ref"},
                   attributes={"href": "target"}, excluded_attributes={"id": "ordinal"})
    with pytest.raises(ValueError, match="ambiguous native source link target: inside"):
        prepare(source, profile)


def test_duplicate_native_source_navigation_identity_blocks_mapping():
    source = b'<d><p id="inside">outside</p><p id="work" prev="inside"><i id="inside">target</i></p></d>'
    profile = deepcopy(XML_PROFILE)
    profile.update(attributes={"prev": "prev"}, native_link_attributes=["prev"])
    with pytest.raises(ValueError, match="ambiguous native source link target: inside"):
        prepare(source, profile)


def test_candidate_in_header_cannot_satisfy_readable_body_claims():
    candidate=XML_TEI.replace(b'<teiHeader/>',b'').replace(b'<body>',b'<teiHeader>').replace(b'</body>',b'</teiHeader>')
    report=verify(XML_SOURCE,candidate,XML_PROFILE)
    assert report["status"]=="fail"
    assert any(f["rule"]=="candidate-parse-or-scope" for f in report["findings"])


def test_plain_source_errors_fail_closed():
    with pytest.raises(ValueError,match="duplicate JSON key"):
        prepare(b'{"Data":[],"Data":[]}',JSON_PROFILE)
    with pytest.raises(ValueError,match="invalid catechism row"):
        prepare(b'{"Data":[{"Number":1}]}',JSON_PROFILE)


def test_cli_returns_machine_readable_evidence_and_never_mutates_inputs(tmp_path,capsys):
    source=tmp_path/'source.xml'
    candidate=tmp_path/'candidate.xml'
    profile=tmp_path/'profile.json'
    source.write_bytes(XML_SOURCE)
    candidate.write_bytes(XML_TEI)
    profile.write_text(json.dumps(XML_PROFILE),encoding='utf-8')
    assert main(['--source',str(source),'--source-sha256',digest(XML_SOURCE),
                 '--candidate',str(candidate),'--candidate-sha256',digest(XML_TEI),
                 '--profile',str(profile),'--mutations'])==0
    report=json.loads(capsys.readouterr().out)
    assert report['source_sha256']==digest(XML_SOURCE)
    assert report['input_binding']=={'source':'matched','candidate':'matched'}
    assert source.read_bytes()==XML_SOURCE and candidate.read_bytes()==XML_TEI


def test_cli_rejects_stale_source_or_candidate_binding(tmp_path,capsys):
    source=tmp_path/'source.xml'
    candidate=tmp_path/'candidate.xml'
    profile=tmp_path/'profile.json'
    source.write_bytes(XML_SOURCE)
    candidate.write_bytes(XML_TEI)
    profile.write_text(json.dumps(XML_PROFILE),encoding='utf-8')
    args=['--source',str(source),'--candidate',str(candidate),'--profile',str(profile)]
    assert main(args+['--source-sha256','0'*64])==2
    assert 'source SHA-256 mismatch' in capsys.readouterr().err
    assert main(args+['--source-sha256',digest(XML_SOURCE),
                      '--candidate-sha256','0'*64])==2
    assert 'candidate SHA-256 mismatch' in capsys.readouterr().err


def test_cli_rejects_input_changed_during_verification(tmp_path, capsys, monkeypatch):
    import build.tools.check_source_fidelity as checker

    source = tmp_path / 'source.xml'
    candidate = tmp_path / 'candidate.xml'
    profile = tmp_path / 'profile.json'
    source.write_bytes(XML_SOURCE)
    candidate.write_bytes(XML_TEI)
    profile.write_text(json.dumps(XML_PROFILE), encoding='utf-8')
    original_verify = checker.verify

    def change_candidate_after_snapshot(*args, **kwargs):
        report = original_verify(*args, **kwargs)
        candidate.write_bytes(XML_TEI + b' ')
        return report

    monkeypatch.setattr(checker, 'verify', change_candidate_after_snapshot)
    assert main(['--source', str(source), '--source-sha256', digest(XML_SOURCE),
                 '--candidate', str(candidate), '--profile', str(profile)]) == 2
    assert 'input changed during checking' in capsys.readouterr().err


def test_candidate_exclusions_are_explicit_and_cannot_mask_source_claims():
    profile=deepcopy(XML_PROFILE)
    profile["candidate_attribute_exclusions"]={"rendition":"header CSS scope excluded"}
    candidate=XML_TEI.replace(b'rend="italic"',b'rend="italic" rendition="#style"')
    report=verify(XML_SOURCE,candidate,profile)
    assert report["status"]=="pass"
    assert len(report["candidate_attribute_exclusions"])==1
    profile["candidate_attribute_exclusions"]={"rend":"cannot hide source claim"}
    with pytest.raises(ValueError,match="conflicts with source claim"):
        verify(XML_SOURCE,XML_TEI,profile)


def test_native_navigation_links_check_selected_and_external_source_targets():
    source=b'<d><p id="outside"/><p id="work" prev="outside" next="inside"><i id="inside">x</i></p></d>'
    profile=deepcopy(XML_PROFILE)
    profile.update(tags={"p":"p","i":"hi"},attributes={"prev":"prev","next":"next"},
                   native_link_attributes=["prev","next"],external_base="https://example.test/source")
    plan=prepare(source,profile)
    assert plan.carriers[0].attributes['prev']=='https://example.test/source#outside'
    assert plan.carriers[0].attributes['next']=='#src-2'


TEI_BODY_SOURCE = b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><titleStmt><title>Source</title></titleStmt></fileDesc></teiHeader><text><body><div><p>before<hi rend="italic">emphasis</hi>after</p><p>second</p></div></body></text></TEI>'
TEI_BODY_CANDIDATE = b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><titleStmt><title>Generated</title></titleStmt></fileDesc></teiHeader><text><body><div><p>before<hi rend="italic">emphasis</hi>after</p><p>second</p></div></body></text></TEI>'
TEI_BODY_PROFILE = {"adapter": "tei-body-identity", "identity_mode": "structural-position"}


def test_tei_body_identity_checks_every_body_carrier_and_excludes_header():
    report = verify(TEI_BODY_SOURCE, TEI_BODY_CANDIDATE, TEI_BODY_PROFILE)
    assert report["status"] == "pass", report
    assert report["coverage"]["counts"]["excluded"] == 1
    assert report["claims"]["inline-tail"]["status"] == "passed"
    mutated = TEI_BODY_CANDIDATE.replace(b"<hi ", b"<seg ").replace(b"</hi>", b"</seg>")
    changed = verify(TEI_BODY_SOURCE, mutated, TEI_BODY_PROFILE)
    assert changed["status"] == "fail"
    assert "role" in {finding["rule"] for finding in changed["findings"]}


PLAIN_LINES_PROFILE = {
    "adapter": "plain-text-lines",
    "encoding": "utf-8",
    "line_endings": ["CRLF"],
    "line_terminator_policy": "trim-one-final-empty-segment",
    "candidate_carrier": "tei:ab",
    "candidate_attribute_exclusions": {
        "xml:id": "Generated carrier identity is not present in plain-text input; order supplies the correspondence.",
        "n": "Candidate-generated ordinal line number is represented by line order, not source text.",
        "type": "Candidate TEI line-carrier role is not encoded by this plain-text source.",
    },
}
PLAIN_LINES_CANDIDATE = (
    b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader/><text><body><div>'
    b'<ab xml:id="line-1" n="1" type="source-line">First</ab>\n'
    b'<ab xml:id="line-2" n="2" type="source-line">second</ab>\n'
    b'<ab xml:id="line-3" n="3" type="source-line"/>\n</div></body></text></TEI>'
)


def test_plain_text_line_profile_checks_exact_order_and_marks_unmapped_structure():
    source = b"First\r\nsecond\r\n\r\n"
    report = verify(source, PLAIN_LINES_CANDIDATE, PLAIN_LINES_PROFILE)
    assert report["status"] == "incomplete", report
    assert report["coverage"]["counts"]["passed"] >= 4
    assert report["coverage"]["counts"]["excluded"] >= 4
    assert report["coverage"]["counts"]["unsupported"] == 1
    assert report["claims"]["attachment"]["status"] == "unsupported"
    assert report["claims"]["inline-tail"]["status"] == "unsupported"
    assert len(report["candidate_attribute_exclusions"]) == 9
    changed = verify(source, PLAIN_LINES_CANDIDATE.replace(b"second", b"Second"), PLAIN_LINES_PROFILE)
    assert changed["status"] == "fail"
    assert "text" in {finding["rule"] for finding in changed["findings"]}


def test_plain_text_line_profile_does_not_strip_a_candidate_byte_order_mark():
    source = b"first\r\n"
    candidate = PLAIN_LINES_CANDIDATE.replace(b"First", b"\xef\xbb\xbffirst").replace(
        b'<ab xml:id="line-2" n="2" type="source-line">second</ab>\n', b"")
    candidate = candidate.replace(
        b'<ab xml:id="line-3" n="3" type="source-line"/>\n', b"")
    report = verify(source, candidate, PLAIN_LINES_PROFILE)
    assert report["status"] == "fail"
    assert "text" in {finding["rule"] for finding in report["findings"]}


def test_plain_text_projection_rejects_readable_text_outside_line_carriers():
    source = b"alpha\r\nbeta\r\n"
    candidate = (
        b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div>'
        b'<ab>alpha</ab><p>invented readable prose</p><ab>beta</ab>'
        b'</div></body></text></TEI>'
    )
    report = verify(source, candidate, PLAIN_LINES_PROFILE)
    assert report["status"] == "fail"
    assert any("outside tei:ab" in finding.get("message", "") for finding in report["findings"])
    assert report["claims"]["invention"]["status"] != "passed"


def test_plain_text_line_endings_are_not_credited_as_candidate_fidelity():
    candidate = (
        b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><ab>alpha</ab>'
        b'</body></text></TEI>'
    )
    for source in (b"alpha", b"alpha\r\n"):
        report = verify(source, candidate, PLAIN_LINES_PROFILE)
        assert report["status"] == "incomplete"
        assert report["claims"]["text"]["status"] == "passed"
        terminal = next(item for item in report["coverage"]["occurrences"]
                        if item["location"] == "@terminal-newline")
        assert terminal["result"] == "excluded"
        assert terminal["present"] is source.endswith(b"\r\n")
        assert not any(item["feature"] == "plain-text-line-boundary" and item["result"] == "passed"
                       for item in report["coverage"]["occurrences"])


def test_invalid_candidate_never_reports_unchecked_claims_as_passed():
    report = verify(TEI_BODY_SOURCE, b"<TEI", TEI_BODY_PROFILE)
    assert report["status"] == "fail"
    assert {claim["status"] for claim in report["claims"].values()} == {"unassessed"}
    assert report["coverage"]["counts"].get("passed", 0) == 0


def test_mutations_qualify_tei_body_without_xml_ids():
    report = verify(TEI_BODY_SOURCE, TEI_BODY_CANDIDATE, TEI_BODY_PROFILE, mutations=True)
    assert report["status"] == "pass"
    qualification = report["mutation_qualification"]
    assert qualification["status"] == "pass", qualification
    assert qualification["applicable"] >= 7
    assert all(case["status"] == "rejected" for case in qualification["cases"]
               if case["status"] != "not-applicable")


def test_mutations_challenge_empty_source_carriers():
    source = (b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
              b'<p n="one"/><p n="two"/></body></text></TEI>')
    qualification = verify(source, source, TEI_BODY_PROFILE, mutations=True)["mutation_qualification"]
    cases = {case["mutation"]: case["status"] for case in qualification["cases"]}
    assert qualification["status"] == "pass"
    assert all(cases[name] == "rejected" for name in ("omit", "duplicate", "invent"))
    assert cases["change-text"] == "not-applicable"


@pytest.mark.parametrize("old,new,rule", [
    (b'<note xml:id="src-4">', b'<p xml:id="src-4">', "role"),
    (b'rend="italic"', b'rend="plain"', "attributes"),
])
def test_equal_words_cannot_hide_semantic_loss(old, new, rule):
    changed = XML_TEI.replace(old, new)
    if b'<p xml:id="src-4">' in changed:
        changed = changed.replace(b'</note>', b'</p>')
    assert ''.join(etree.fromstring(changed).itertext()) == ''.join(etree.fromstring(XML_TEI).itertext())
    report = verify(XML_SOURCE, changed, XML_PROFILE)
    assert report["status"] == "fail"
    assert rule in {f["rule"] for f in report["findings"]}


def test_work_moved_to_front_cannot_pass_body_check():
    changed = XML_TEI.replace(b'<body>', b'<front>').replace(b'</body>', b'</front><body><div/></body>')
    assert ''.join(etree.fromstring(changed).itertext()) == ''.join(etree.fromstring(XML_TEI).itertext())
    assert verify(XML_SOURCE, changed, XML_PROFILE)["status"] == "fail"


def test_omitted_empty_source_carrier_fails():
    source = XML_SOURCE.replace(b'<note>note</note>', b'<note/>')
    candidate = XML_TEI.replace(b'<note xml:id="src-4">note</note>', b'<note xml:id="src-4"/>')
    assert verify(source, candidate, XML_PROFILE)["status"] == "pass"
    report = verify(source, candidate.replace(b'<note xml:id="src-4"/>', b''), XML_PROFILE)
    assert report["status"] == "fail"
    assert "omission" in {f["rule"] for f in report["findings"]}


def test_broken_local_link_prevents_mutation_qualification():
    candidate = TEI_BODY_CANDIDATE.replace(b'<p>second</p>', b'<p next="#missing">second</p>')
    report = verify(TEI_BODY_SOURCE, candidate, TEI_BODY_PROFILE, mutations=True)
    assert report["status"] == "fail"
    assert report["local_links"]["status"] == "fail"
    assert report["mutation_qualification"]["status"] == "not-run"
