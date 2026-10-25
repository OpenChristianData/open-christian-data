"""Prepare only Stokes's two existing acquired electronic volume candidates."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from lxml import etree

from build.tei.stokes_retained_scope import ROOT, LOG, OLD_PACKAGE, WORK_ID, MEMBERS, retained, parse, sha
from build.tei.stokes_retained_completion import SOURCE_DIR, canonical, _convert
from build.tei.stokes_retained_completion_oracle import _closure, _fresh_import_paths, _IMPORT_PATHS, check, oracle
from ocd_kernel.reconstruction import SourceManifest, CandidatePackage, reconstruct, validate

LIBRARY = Path("D:/Library/Open Christian Data")
CANDIDATES = LIBRARY / "candidate-reviews/stokes-existing-readable-20261003-v4"


def authority(name, path, role):
    data = (ROOT / path).read_bytes()
    return dict(name=name, path=Path(path).as_posix(), role=role, bytes=len(data), sha256=sha(data))


def manifests():
    directory = ROOT / SOURCE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for member_id, spec in MEMBERS.items():
        source = parse(retained(member_id)); body = source.find("ThML.body")
        nodes = list(body.iter())
        profile_path = SOURCE_DIR / (member_id + ".profile.json")
        profile = dict(contract="ocd-stokes-complete-retained-volume-profile-v1", work_id=WORK_ID, member_id=member_id,
            source=spec, source_body_c14n_sha256=sha(etree.tostring(body, method="c14n", with_comments=True)),
            body_tags=dict(Counter(x.tag for x in nodes if isinstance(x.tag, str))),
            body_comments=sum(x.tag is etree.Comment for x in nodes), front=spec["front"], back=spec["back"],
            genre="commentary; source scripCom type Commentary", scope="complete retained electronic volume; two volumes included in whole acquired work",
            mapping="numbered source hierarchy; actual readable native paragraphs/notes/indices/table/ref/poetry; source hN paragraphs retain original level and order; comments exact",
            administration="Complete original header fields and CSS accounted separately, no inferred editorial metadata")
        (ROOT / profile_path).write_bytes(canonical(profile))
        policy_path = SOURCE_DIR / (member_id + ".policy.json")
        (ROOT / policy_path).write_bytes(canonical(dict(contract="ocd-stokes-independent-readable-policy-v1", member_id=member_id,
            independent="Direct raw XML reader; never imports native emitter or trusts its private ledger for readable body proof",
            required=["complete source and actual DOM preorder", "actual direct and tail payloads", "actual source IDs/semantic attributes", "actual parent and sibling positions", "inverse full readable body C14N", "all comments and source administrative fields", "P5", "fresh existing-work replay", "representative negative challenges"],
            body="No omission/reordering/invented targets; complete printed and generated indices and note attachments", rights="CCEL visible credit required; release separate")))
        authorities = [authority("retained-thml", spec["path"], "primary-source"),
            authority("volume-profile", profile_path, "complete-source-feature-profile"),
            authority("volume-policy", policy_path, "independent-validation-policy"),
            authority("tei-p5-xsd", "ocd_kernel/tei/vendor/xsd/tei_all.xsd", "tei-validation-schema"),
            authority("candidate-package-schema", "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json", "candidate-package-schema"),
            authority("source-local-attribution-readme", "data/commentaries/expositors-bible/README.md", "source-rights-attribution"),
            authority("ccel-permission", "sources/commentaries/expositors-bible/ccel-permission.md", "source-rights-evidence"),
            authority("common-native-emitter", "build/tei/ccel_retained_native_emitter.py", "frozen-native-repair-dependency"),
            authority("stokes-authority-recovery", "build/tei/stokes_retained_scope.py", "existing-candidate-recovery-code"),
            authority("two-volume-scope", LOG / "retained-scope-reconciliation.json", "complete-acquired-work-scope")]
        if spec["volume"] == 2:
            authorities += [authority("original-tei", OLD_PACKAGE / "content.tei.xml", "preexisting-reconstruction-input"), authority("original-account", OLD_PACKAGE / "source-accountability.json", "historical-source-feature-proof")]
        converter = dict(id=_convert.converter_id, version=_convert.converter_version, callable="_convert", implementation_path="build/tei/stokes_retained_completion.py", implementation_sha256=sha((ROOT / "build/tei/stokes_retained_completion.py").read_bytes()))
        validator = dict(id=oracle.oracle_id, version=oracle.oracle_version, callable="oracle", implementation_path="build/tei/stokes_retained_completion_oracle.py", implementation_sha256=sha((ROOT / "build/tei/stokes_retained_completion_oracle.py").read_bytes()), import_closure_sha256=_closure())
        record = dict(contract="ocd-source-manifest-v1", source_id=member_id + "-existing-retained-completion-v1", work_id=WORK_ID, ticket_id="37c-152-existing-acquired-two-volume-completion", authorities=authorities, converter=converter, validator=validator,
            package_schema=dict(path="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json", sha256=next(x["sha256"] for x in authorities if x["role"] == "candidate-package-schema")),
            scope=dict(kind="complete-existing-retained-volume", member_id=member_id, volume=spec["volume"], acquired_work_member_count=2, no_acquisition_or_download=True), source_order=dict(order="complete original source DOM, including comment/tail attachment"))
        path = SOURCE_DIR / (member_id + ".source-manifest.json")
        (ROOT / path).write_bytes(canonical(record)); SourceManifest.load(ROOT / path, repository_root=ROOT)
        paths[member_id] = path
    return paths


def challenges(member_id, package):
    raw = package.member_bytes("content.tei.xml"); account = package.member_bytes("source-accountability.json")
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    cases = []
    schema = etree.XMLSchema(etree.parse(str(ROOT / 'ocd_kernel/tei/vendor/xsd/tei_all.xsd')))
    selectors = [
        ("readable-paragraph-text", ".//t:p", "text"),
        ("source-tail-text", ".//t:ref", "tail"),
        ("source-heading-role", ".//t:p[contains(@rend,'source-h')]", "rend"),
        ("table-cell-span", ".//t:cell[@cols]", "cols"),
        ("scripture-reference-literal", ".//t:ref[@target][not(starts-with(@target,'#'))]", "target"),
        ("generated-index-directive", ".//t:milestone[@unit='insertIndex']", "n"),
        ("note-label", ".//t:note[@n]", "n"),
    ]
    for label, selector, field in selectors:
        tree = etree.fromstring(raw)
        matches = tree.xpath('./t:text' + selector[1:], namespaces=ns)
        if not matches: raise ValueError("Missing required challenge source feature: " + label)
        node = next((x for x in matches if getattr(x, field, None)), matches[0]) if field in {"text", "tail"} else matches[0]
        if field == "text": node.text = (node.text or "") + "CHALLENGE"
        elif field == "tail": node.tail = (node.tail or "") + "CHALLENGE"
        elif field == 'cols': node.set(field, str(int(node.get(field)) + 1))
        else: node.set(field, (node.get(field) or "") + "CHALLENGE")
        schema.assertValid(tree)
        changed = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
        try: check(member_id, changed, account)
        except ValueError as error: cases.append(dict(challenge=label, rejected=True, p5_valid=True, reason=str(error)[:300], candidate_sha256=sha(changed)))
        else: raise ValueError("Independent Stokes oracle admitted mutation: " + label)
    tree = etree.fromstring(raw); notes = tree.xpath("./t:text//t:note", namespaces=ns); note = notes[0]
    target = next(x for x in tree.xpath("./t:text//t:p", namespaces=ns) if x is not note.getparent() and note not in x.iterancestors())
    note.getparent().remove(note); target.append(note)
    schema.assertValid(tree)
    changed = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
    try: check(member_id, changed, account)
    except ValueError as error: cases.append(dict(challenge="complete-note-attachment", rejected=True, p5_valid=True, reason=str(error)[:300], candidate_sha256=sha(changed)))
    else: raise ValueError("Independent Stokes oracle admitted wrong note attachment")
    changed_account = json.loads(account)
    comment = next(x for x in changed_account['features'] if x['source_tag'] == '#comment')
    comment['source_text'] += 'CHALLENGE'
    altered = canonical(changed_account)
    try: check(member_id, raw, altered)
    except (ValueError, etree.DocumentInvalid) as error: cases.append(dict(challenge='administrative-comment-source-fields', rejected=True, reason=str(error)[:300], accounting_sha256=sha(altered)))
    else: raise ValueError('Independent Stokes oracle admitted altered source comment accounting')
    return cases


def import_challenge():
    """Observe actual imports, then challenge a new first-party import in isolation."""
    directory = ROOT / '.tmp_audit/stokes-existing-import-20261003-v2'
    if directory.exists(): raise ValueError('Fresh Stokes import challenge directory required')
    oracle_path = Path('build/tei/stokes_retained_completion_oracle.py')
    for relative in (*_IMPORT_PATHS, oracle_path.as_posix()):
        path = directory / relative; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / relative).read_bytes())
    baseline = _closure(directory)
    if baseline != _closure(ROOT): raise ValueError('Isolated Stokes import baseline differs')
    extra = directory / 'ocd_kernel/stokes_import_challenge.py'
    extra.write_text('CHALLENGE = True\n', encoding='utf-8')
    original = (directory / oracle_path).read_bytes()
    (directory / oracle_path).write_bytes(original + b'\nimport ocd_kernel.stokes_import_challenge\n')
    observed = _fresh_import_paths(directory)
    try: _closure(directory)
    except ValueError as error:
        if observed != tuple(sorted((*_IMPORT_PATHS, 'ocd_kernel/stokes_import_challenge.py'))):
            raise ValueError('Stokes unexpected-import challenge changed other imports')
        return dict(status='pass', fresh_isolated_process=True, observed_paths=list(_IMPORT_PATHS), closure_sha256=baseline,
            implementation_sha256=sha((ROOT / oracle_path).read_bytes()), unexpected_import='ocd_kernel/stokes_import_challenge.py', rejected=True, reason=str(error), observed_mutant_paths=list(observed))
    raise ValueError('Stokes oracle accepted unexpected first-party import')


def prepare():
    closure_proof = import_challenge()
    paths = manifests(); results = []
    for member_id, relative in paths.items():
        manifest = SourceManifest.load(ROOT / relative, repository_root=ROOT)
        directory = CANDIDATES / member_id / "package"
        directory.parent.mkdir(parents=True, exist_ok=True)
        candidate = CandidatePackage.load(directory) if directory.exists() else reconstruct(manifest, directory, _convert)
        report = validate(manifest, candidate, oracle)
        if report.status != "pass": raise ValueError("Stokes current source gate failed")
        direct = check(member_id, candidate.member_bytes("content.tei.xml"), candidate.member_bytes("source-accountability.json"))
        direct["mutations"] = challenges(member_id, candidate)
        replay_records = []
        for index in [1, 2]:
            replay_dir = CANDIDATES / member_id / ('fresh-process-replay-' + str(index))
            if replay_dir.exists(): raise ValueError('Fresh Stokes replay destination required')
            subprocess.run([sys.executable, "-m", "build.tei.stokes_retained_completion", str(replay_dir), "--source-manifest", str(ROOT / relative)], cwd=ROOT, check=True, capture_output=True)
            replay = CandidatePackage.load(replay_dir)
            same = candidate.sha256 == replay.sha256 and all(candidate.member_bytes(name) == replay.member_bytes(name) for name in candidate.member_names)
            if not same: raise ValueError("Stokes clean existing-work replay differs")
            replay_records.append(dict(path=replay_dir.as_posix(), package_sha256=replay.sha256, exact_all_member_bytes_equal=True))
        result = dict(member_id=member_id, package_path=directory.as_posix(), package_sha256=candidate.sha256, source_manifest_path=relative.as_posix(), source_manifest_sha256=manifest.sha256, oracle_report=json.loads(json.dumps(dict(report.attestation), default=dict)), oracle_report_sha256=report.sha256, direct_source_review=direct,
            import_closure_proof=closure_proof,
            reproducibility=dict(status="pass", fresh_python_process=True, exact_six_member_bytes_equal=True, replays=replay_records, historical_LIB034_receipts="unchanged and dated; this is current existing-work repair/completion replay"))
        (ROOT / LOG / (member_id + "-current-review.json")).write_bytes(canonical(result)); results.append(result)
    (ROOT / LOG / "candidate-completion-receipt.json").write_bytes(canonical(dict(status="pass", work_id=WORK_ID, included_volumes=2, acquired_volumes=2, members=results)))
    return [dict(member_id=x["member_id"], package_sha256=x["package_sha256"], status="pass") for x in results]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.parse_args()
    print(json.dumps(prepare(), sort_keys=True))
