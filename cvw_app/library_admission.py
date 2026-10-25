"""Read-only candidate association from declared work and acquisition evidence."""
from collections.abc import Mapping
from pathlib import Path

from ocd_kernel.lib.path_io import resolve_path
from ocd_kernel.library._common import PipelineError, safe_identifier
from ocd_kernel.library.identities import load_work, load_editions
from ocd_kernel.library.acquisitions import acquisition_for_edition
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


def _work_ids(record):
    """Require one explicit identity declaration; never infer a cohort."""
    if 'work_id' in record and 'work_ids' in record:
        raise PipelineError('source manifest has competing work identity declarations')
    values = record.get('work_ids')
    if values is None:
        values = [record.get('work_id')]
    if not isinstance(values, (list, tuple)) or not values:
        raise PipelineError('source manifest must explicitly name work_id or nonempty work_ids')
    if any(not isinstance(value, str) for value in values):
        raise PipelineError('source manifest work identities must be strings')
    checked = [safe_identifier(value, field='source manifest work identity') for value in values]
    if len(set(checked)) != len(checked):
        raise PipelineError('source manifest work identities are duplicated')
    return checked


def _primary_members(record, work_ids):
    by_work = {work_id: set() for work_id in work_ids}
    for authority in record['authorities']:
        if authority['role'] != 'primary-source':
            continue
        scoped = authority.get('work_ids', work_ids)
        if (not isinstance(scoped, (list, tuple)) or not scoped
                or any(not isinstance(value, str) for value in scoped)
                or len(set(scoped)) != len(scoped) or set(scoped) - set(work_ids)):
            raise PipelineError('primary authority work_ids must be a nonempty unique subset of the declared cohort')
        member = (authority['path'], authority['bytes'], authority['sha256'])
        for work_id in scoped:
            if member in by_work[work_id]:
                raise PipelineError('primary source member is duplicated')
            by_work[work_id].add(member)
    if any(not members for members in by_work.values()):
        raise PipelineError('every declared work requires primary source members')
    return by_work


def _acquisition_primary_members(acquired):
    """Return the acquired text sources, excluding packaging and support files.

    A normal ``source_path`` is the acquisition's selected retained source.
    Acquisitions whose source is an ordered member-set manifest, or whose
    source path is not itself a retained member, continue to bind the complete
    retained member set.
    """
    retained = {
        (member['path'], member['bytes'], member['sha256'])
        for member in acquired['retained_files']
    }
    source_path = acquired.get('source_path')
    if acquired.get('source_kind') == 'retained-member-set' or not isinstance(source_path, str):
        return retained

    member_path = source_path.partition('#')[0]
    selected = [member for member in acquired['retained_files'] if member['path'] == member_path]
    if not selected:
        return retained
    if len(selected) != 1:
        raise PipelineError('acquisition selected source member is duplicated')
    member = selected[0]
    if (
        acquired.get('source_bytes') != member['bytes']
        or acquired.get('source_sha256') != member['sha256']
    ):
        raise PipelineError('acquisition selected source identity differs from retained member')
    return {(member['path'], member['bytes'], member['sha256'])}


def _authority_path_for_work(manifest, role, work_id):
    """Resolve the unique manifest authority for one selected work and role."""
    authorities = manifest.record.get('authorities')
    if not isinstance(authorities, (list, tuple)):
        raise PipelineError('source manifest authorities are invalid')
    matching = []
    for authority in authorities:
        if not isinstance(authority, Mapping) or authority.get('role') != role:
            continue
        scoped = authority.get('work_ids')
        if scoped is not None:
            if (not isinstance(scoped, (list, tuple)) or not scoped
                    or any(not isinstance(value, str) for value in scoped)
                    or len(set(scoped)) != len(scoped)):
                raise PipelineError(f'{role} work_ids are invalid')
            if work_id not in scoped:
                continue
        matching.append(authority)
    if len(matching) != 1:
        raise PipelineError(f'source manifest must bind exactly one {role} for {work_id}')
    name = matching[0].get('name')
    if not isinstance(name, str) or not name:
        raise PipelineError(f'source manifest {role} name is invalid')
    # Resolve through SourceManifest to enforce its lexical containment and
    # storage rules, but compare repository-relative authority identities below.
    manifest.authority_path(name)
    path = matching[0].get('path')
    if not isinstance(path, str):
        raise PipelineError(f'source manifest {role} path is invalid')
    return path


def declared_candidate_records(root: Path, candidate_dirs):
    """Build transient renderer inputs; never persist routes or infer identities.

    A source manifest names one work or an explicit ordered work cohort. Its
    primary member set must match the acquisition's selected retained source,
    or the complete retained set when the acquisition uses a member-set
    manifest or has no retained ``source_path``. Packaging and support files
    remain bound by the manifest and acquisition without being treated as
    textual sources. Authority-level work_ids restrict assets to named works.
    """
    root = resolve_path(Path(root), strict=True)
    records = {}
    for directory in candidate_dirs:
        candidate = CandidatePackage.load(Path(directory) / 'package')
        binding = candidate.manifest['source_manifest']
        relative = binding['path']
        manifest_path = resolve_path(root / relative, strict=True)
        if not manifest_path.is_relative_to(root):
            raise PipelineError('source manifest escapes repository')
        manifest = SourceManifest.load(manifest_path, repository_root=root)
        if manifest.sha256 != binding['sha256'] or manifest.record['source_id'] != candidate.manifest['source_id']:
            raise PipelineError('candidate source binding differs from current manifest')
        work_ids = _work_ids(manifest.record)
        members = _primary_members(manifest.record, work_ids)
        for work_id in work_ids:
            _add_record(root, records, manifest, relative, work_id, members[work_id])
    return list(records.values())


def _add_record(root, records, manifest, relative, work_id, primary):
    work_path = root / 'library/works' / work_id / 'work.json'
    if resolve_path(work_path) != work_path:
        raise PipelineError('declared work path is linked')
    work = load_work(work_path)
    if work['work_id'] != work_id:
        raise PipelineError('source manifest and work identity differ')
    matches = []
    for edition in load_editions(work_path):
        acquisition_ids = edition.record.get('acquisition_ids')
        if not acquisition_ids:
            continue
        for acquisition_id in acquisition_ids:
            acquisition_path, acquired = acquisition_for_edition(root, work_id, edition.edition_id, acquisition_id)
            expected_primary = _acquisition_primary_members(acquired)
            if primary == expected_primary:
                matches.append((edition, acquired, acquisition_path))
    if len(matches) != 1:
        raise PipelineError('candidate primary members must match exactly one declared acquisition')
    edition, acquired, acquisition_path = matches[0]
    authority_bindings = None
    if acquired.get('source_selection') is not None or isinstance(acquired.get('source_path'), str):
        selected_work_path = _authority_path_for_work(
            manifest, 'work-identity-config', work_id
        )
        selected_acquisition_path = _authority_path_for_work(
            manifest, 'acquisition-selection-authority', work_id
        )
        expected_acquisition_path = acquisition_path.relative_to(root).as_posix()
        expected_work_path = work_path.relative_to(root).as_posix()
        if selected_acquisition_path != expected_acquisition_path or selected_work_path != expected_work_path:
            raise PipelineError('selected candidate does not bind declared acquisition and work authorities')
        authority_bindings = {
            'work_identity_authority': selected_work_path,
            'acquisition_selection_authority': selected_acquisition_path,
        }
    # The schema makes category optional; this fallback is only a transient CVW label.
    category = edition.record.get('category') or 'uncategorized'
    from cvw_app.review_contract import MAX_WORK_CREATOR_SCALARS
    authors = [c['name'] for c in work.get('creators', []) if c.get('role') == 'author']
    author = '; '.join(authors) or None
    if author is not None and len(author) > MAX_WORK_CREATOR_SCALARS:
        suffix = f' and {len(authors) - 1} others' if len(authors) > 1 else ''
        first = authors[0]
        if len(first) + len(suffix) > MAX_WORK_CREATOR_SCALARS:
            first = first[:MAX_WORK_CREATOR_SCALARS - len(suffix) - 1] + '…'
        author = first + suffix
    record = records.setdefault(work_id, dict(work_id=work_id, title=work['title'],
        author=author,
        category=category, reconstruction_state=dict(routes=[])))
    if record['category'] != category:
        raise PipelineError('selected editions have different categories; select an explicit review scope')
    route = dict(
        source_id=manifest.record['source_id'], manifest=relative,
        scope=acquired.get('source_scope', 'complete declared primary source members; candidate review, not acceptance'))
    if authority_bindings is not None:
        route.update(authority_bindings)
    record['reconstruction_state']['routes'].append(route)
