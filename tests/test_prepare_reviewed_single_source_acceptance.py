"""Focused guards for reviewed LIB-069 single-source handoffs."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from build.tools import prepare_reviewed_single_source_acceptance as handoff
from ocd_kernel.library._common import PipelineError


def _write(path: Path, content: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def test_jointly_rewritten_visual_image_and_inventories_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(handoff, "MEASUREMENT", Path("evidence"))
    witness = replace(handoff.WITNESSES["baltimore-catechism-no-1"],
                      ticket="fixture", visual_points=("frame",))
    home = tmp_path / "evidence/fixture/visual-final"
    route = (f"https://localhost/review?leftArtifact=source-{witness.manifest_sha}"
             f"&rightArtifact=tei-{witness.package_sha}&linked=false&correspondence=absent")
    image_hash = _write(home / "frame.jpg", b"reviewed pixels")
    identity = dict(work_id=witness.work_id,
                    source=dict(path=witness.source, sha256=witness.source_sha),
                    candidate=dict(package_sha256=witness.package_sha,
                                   artifact_sha256=witness.tei_sha),
                    validation=dict(report_sha256=witness.report_sha))
    def encoded(value):
        return (json.dumps(value, sort_keys=True) + "\n").encode()
    hashes = (
        _write(home.parent / "visual-final-review.md", b"Reviewed historical sample\n"),
        _write(home / "reviewed-identity.json", encoded(identity)),
        _write(home / "image-inventory.json", encoded([dict(file="frame.jpg", sha256=image_hash)])),
        _write(home / "observations.json", encoded([dict(name="frame", sha256=image_hash,
                                                          url=route, after="2026-09-09T03:00:00Z")])),
    )
    pinned = replace(witness, visual_hashes=hashes)
    files, reviewed_at = handoff._visual_evidence(tmp_path, pinned)
    assert files["visual/frame.jpg"] == b"reviewed pixels"
    assert reviewed_at == "2026-09-09T03:00:00Z"

    new_hash = _write(home / "frame.jpg", b"jointly rewritten pixels")
    _write(home / "image-inventory.json", encoded([dict(file="frame.jpg", sha256=new_hash)]))
    _write(home / "observations.json", encoded([dict(name="frame", sha256=new_hash,
                                                      url=route, after="2026-09-09T03:00:00Z")]))
    with pytest.raises(PipelineError, match="SHA-256 mismatch"):
        handoff._visual_evidence(tmp_path, pinned)


def test_header_derivation_preserves_reviewed_body_and_source_rights_statement():
    original = (b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc>'
                b'<titleStmt><title>Test</title></titleStmt><publicationStmt><availability>'
                b'Nonaccepted candidate; publication is not authorized; human identity, edition, rights, textual, and editorial review remain separate.'
                b'</availability></publicationStmt><sourceDesc><bibl><title>Source</title></bibl>'
                b'</sourceDesc></fileDesc><revisionDesc><change status="draft">Original</change>'
                b'</revisionDesc></teiHeader><text><body><p>Exact words</p></body></text></TEI>')
    witness = replace(handoff.WITNESSES["luthers-small-catechism"],
                      tei_sha=hashlib.sha256(original).hexdigest())
    derived = handoff._derive_header(original, witness, handoff._identity(witness),
                                     dict(id="luther-test-revision", date="2026-09-25", note="Test binding"),
                                     43598)
    assert derived.split(b"</teiHeader>", 1)[1] == original.split(b"</teiHeader>", 1)[1]
    assert b"publication is not authorized" in derived
    assert b"ocd-acceptance-binding" in derived
