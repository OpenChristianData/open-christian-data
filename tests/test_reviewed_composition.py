import hashlib

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.reviewed_composition import compose_reviewed_documents, verify_reviewed_composition

HEADER = b'<teiHeader xmlns="http://www.tei-c.org/ns/1.0"><fileDesc><sourceDesc><p>Ordered volumes</p></sourceDesc></fileDesc></teiHeader>'


def member(identifier):
    raw = b'<?xml version="1.0"?>\n<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:id="' + identifier + b'"><teiHeader><fileDesc><titleStmt><title>' + identifier + b'</title></titleStmt></fileDesc></teiHeader><text><body><p>Original  text</p></body></text></TEI>'
    return raw, hashlib.sha256(raw).hexdigest()


def test_complete_headers_and_text_remain_ordered_without_rewriting():
    members = [member(b'volume1'), member(b'volume2')]
    result = compose_reviewed_documents(HEADER, members)
    assert all(raw.split(b'?>', 1)[1] in result for raw, _ in members)
    assert verify_reviewed_composition(result, HEADER, members) == []
    assert verify_reviewed_composition(compose_reviewed_documents(HEADER, members[::-1]), HEADER, members)
    assert verify_reviewed_composition(result.replace(b'Original  text', b'Changed text', 1), HEADER, members)
    assert verify_reviewed_composition(result.replace(b'<title>volume1</title>', b'<title>Other</title>'), HEADER, members)
    assert verify_reviewed_composition(result.replace(members[1][0].split(b'?>', 1)[1], b''), HEADER, members)
    assert verify_reviewed_composition(result.replace(b'</teiCorpus>', b'Invented</teiCorpus>'), HEADER, members)


def test_conflicting_ids_and_stale_member_hash_fail_closed():
    with pytest.raises(PipelineError, match='duplicate'):
        compose_reviewed_documents(HEADER, [member(b'same'), member(b'same')])
    with pytest.raises(PipelineError, match='hash mismatch'):
        compose_reviewed_documents(HEADER, [member(b'one'), (member(b'two')[0], '0' * 64)])


def test_concatenated_member_is_rejected_as_one_source_document():
    first, _ = member(b'one')
    second, _ = member(b'two')
    concatenated = first + second
    with pytest.raises(PipelineError, match='one XML document'):
        compose_reviewed_documents(
            HEADER,
            [(concatenated, hashlib.sha256(concatenated).hexdigest()), member(b'three')],
        )
