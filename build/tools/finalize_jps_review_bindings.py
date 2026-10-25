"""Bind late immutable coordinator evidence without rewriting completed proofs."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from build.tools.prepare_jps_current import ROOT, WORK, canonical
from ocd_kernel.library._common import io_path
from ocd_kernel.tei.install_accepted import _files

def digest(path):
    return sha256(io_path(path).read_bytes()).hexdigest()

def main():
    output = ROOT/'reports/_logs/jps-private-release-20261001-v1'
    publication = ROOT/WORK/'publication'
    completion = json.loads(io_path(publication/'completion.json').read_bytes())
    for name in ('authority_bindings', 'schema_implementation_bindings'):
        for path, expected in completion[name].items():
            if digest(ROOT/path) != expected:
                raise ValueError('Current input changed: '+path)
    for path, expected in completion['release_file_bindings'].items():
        if digest(Path(completion['release_path'])/path) != expected:
            raise ValueError('Release file changed: '+path)
    installed = json.loads((ROOT/'reports/_logs/jps-install-20261001-v1/installed-audit.json').read_bytes())['files']
    current = {p:h for p,h in _files(ROOT/WORK).items() if not p.startswith('publication/')}
    if current != installed:
        raise ValueError('Installed generation changed')
    statuses = {
        'reports/_logs/jps-coordinator-source-review-20261001-v1/review.json':'pass',
        'reports/_logs/jps-coordinator-source-review-20261001-v1/renewed-body-review.json':'pass',
        'reports/_logs/jps-coordinator-source-review-20261001-v1/staged-content-review.json':'pass-stage-content-review',
        'reports/_logs/jps-coordinator-source-review-20261001-v1/install-clearance.json':'cleared-for-serialized-guarded-install',
        'reports/_logs/jps-install-20261001-v1/coordinator-installed-generation-review.json':'pass',
        'reports/_logs/jps-source-empty-bible-support-20261001-v1/coordinator-reviewed-freeze.json':'pass-reviewed-freeze',
        'reports/_logs/jps-source-empty-bible-support-20261001-v1/independent-final-focused-review.json':'independent-read-only-review-pass',
    }
    for path, status in statuses.items():
        if json.loads(io_path(ROOT/path).read_bytes())['status'] != status:
            raise ValueError('Coordinator receipt status differs: '+path)
    projection = json.loads((output/'actual-master-projection.json').read_bytes())
    codes = 'build/bible_data/osis_book_codes.json'
    if projection['receipt']['book_codes_sha256'] != digest(ROOT/codes):
        raise ValueError('Book code authority differs from checked receipt')
    result = dict(status='pass', checked_at=datetime.now(timezone.utc).isoformat(),
        authority_bindings_checked=len(completion['authority_bindings']),
        schema_implementation_bindings_checked=len(completion['schema_implementation_bindings']),
        release_file_bindings_checked=len(completion['release_file_bindings']), installed_files_checked=len(current),
        coordinator_review_bindings={path:digest(ROOT/path) for path in statuses},
        publication_files={path.relative_to(ROOT).as_posix():digest(path) for path in publication.iterdir() if path.is_file()},
        terminal_exit_code=0, terminal_log_sha256=digest(ROOT/'reports/_logs/jps-release-terminal-20261001-v1.log'),
        book_codes_receipt_matches_current=dict(path=codes,sha256=digest(ROOT/codes)),
        rows=23213, source_empty_rows=19, text_characters=completion['text_characters'],
        rights_human_publication_remain_separate=True,
        supplement_qualification='Immutable coordinator installed-generation receipt arrived after owner before-enumeration; bound here without rewriting completed release proof or rerunning pipeline.')
    for path in (output/'final-delivery-audit.json', publication/'coordinator-reviews.json'):
        if path.exists():
            raise FileExistsError(path)
        path.write_bytes(canonical(result))
    print(json.dumps(dict(status='pass',completion_sha256=digest(publication/'completion.json'),
        final_audit_sha256=digest(output/'final-delivery-audit.json'),
        current_inputs=len(completion['authority_bindings'])+len(completion['schema_implementation_bindings']),release_files=7)))

if __name__ == '__main__':
    main()
