"""The replacement index explicitly limits its coverage to declared identities."""
import json
from build.tools import build_book_index
from tests.test_library_views import _fixture_root


def test_index_ignores_legacy_data_and_catalog(tmp_path):
    root = _fixture_root(tmp_path)
    before = build_book_index.collect_entries(root)
    for name in ('data/structured-text/old.json', 'reports/publish/work_catalog.json', 'library/corpus-manifest.json'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('invalid legacy data', encoding='utf-8')
    assert build_book_index.collect_entries(root) == before


def test_index_refreshes_identity_and_escapes_markdown(tmp_path):
    root = _fixture_root(tmp_path)
    work = next((root / 'library/works').glob('*/work.json'))
    value = json.loads(work.read_text())
    value['title'] = 'Fresh | title'
    work.write_text(json.dumps(value), encoding='utf-8')
    destination = tmp_path / 'index.md'
    # This view fixture deliberately includes unresolved authority errors.
    assert build_book_index.main(['--root', str(root), '--output', str(destination)]) == 1
    result = destination.read_text()
    assert r'Fresh \| title' in result
    assert 'undeclared' in result
    assert 'Forms | Editions' in result


def test_index_keeps_authority_errors_visible(tmp_path):
    root = _fixture_root(tmp_path)
    work = next((root / 'library/works').glob('*/work.json'))
    work.write_text('invalid', encoding='utf-8')
    destination = tmp_path / 'index.md'
    assert build_book_index.main(['--root', str(root), '--output', str(destination)]) == 1
    assert 'invalid' in destination.read_text().lower()
