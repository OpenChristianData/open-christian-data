"""Shared operations for existing review commands."""

from __future__ import annotations

from ocd_kernel.library._common import PipelineError
from ocd_kernel.reconstruction import SourceManifest, reconstruct, validate
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable
import argparse
import json
from pathlib import Path


def preflight(*, root_override: Path | None=None, CONTRACT, FIXTURE_MARKER, RECEIPT, RECEIPT_SHA, ROOT, STAGE, _dependencies, _json, _scope, _sha) -> tuple[dict, Path, Path, bool]:
    if not _io_path(RECEIPT).is_file() or _sha(RECEIPT) != RECEIPT_SHA:
        raise PipelineError('Expositors frozen stage receipt differs')
    record = _json(RECEIPT)
    if (record.get('contract') != CONTRACT or record.get('status') != 'staged-only'
            or record.get('installation') != 'not-performed' or record.get('rights') != 'not-assessed'
            or Path(record.get('stage_root', '')).resolve(strict=True) != STAGE.resolve(strict=True)
            or Path(record.get('canonical_root', '')).resolve(strict=True) != ROOT.resolve(strict=True)):
        raise PipelineError('Expositors stage contract or roots differ')
    stage = STAGE.resolve(strict=True)
    fixture = root_override is not None
    root = root_override.resolve(strict=True) if fixture else ROOT.resolve(strict=True)
    if fixture:
        scratch = Path('D:/Library/Open Christian Data/candidate-reviews').resolve(strict=True)
        if scratch not in root.parents or not _io_path(root / FIXTURE_MARKER).is_file():
            raise PipelineError('Expositors override requires a marked review-area fixture')
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError('Expositors install roots overlap')
    _dependencies(stage)
    _scope(root, stage, record['work'])
    return record, root, stage, fixture


def build_candidates(*, AUTHORITY, MEMBERS, ROOT, _convert, _oracle, __doc__) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    destination = args.destination.absolute()
    if destination.exists() or ROOT.resolve() in destination.resolve().parents:
        raise ValueError('candidate root must be fresh and external')
    destination.mkdir(parents=True)
    results = []
    for member in MEMBERS:
        manifest = SourceManifest.load(AUTHORITY / member / 'source-manifest.json', repository_root=ROOT)
        candidate = reconstruct(manifest, destination / member, _convert)
        report = validate(manifest, candidate, _oracle)
        record = dict(contract='ocd-validation-report-v1', status=report.status,
                      candidate_sha256=report.candidate_sha256,
                      source_manifest_sha256=report.source_manifest_sha256,
                      attestation=dict(report.attestation), findings=list(report.findings),
                      report_sha256=report.sha256)
        (destination / (member + '.validation.json')).write_bytes(
            (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8'))
        results.append(dict(member=member, source_manifest_sha256=manifest.sha256,
                            candidate_sha256=candidate.sha256, report_sha256=report.sha256))
    print(json.dumps(results, sort_keys=True))
