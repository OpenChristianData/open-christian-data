"""PDF presentations must stay bound to exact article, caption and source bytes."""
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from cvw_app.review_contract import ReviewContractError, _ajops_media


@pytest.fixture
def media(tmp_path):
    authorities = []
    def bind(name, role, payload):
        path = tmp_path / name
        path.write_bytes(payload)
        record = dict(name=name, role=role, path=name, bytes=len(payload), sha256=sha256(payload).hexdigest())
        authorities.append(record)
        return record
    image = bind("figure.png", "review-image", b"exact retained image")
    pdf = bind("source.pdf", "comparison-witness", b"exact retained PDF")
    handoff = dict(figures=[dict(article="a11", original_jats_graphic="original.tif", caption="The diagram.", figure_number=1,
        display_asset=dict(image, source_pdf=pdf), qualification="Retained PDF page; original TIF identity is unresolved.")])
    bind("handoff.json", "tei-media-handoff", json.dumps(handoff).encode())
    source = SimpleNamespace(record=dict(authorities=authorities, converter=dict(id="ocd-ajops-jats-article-to-tei")),
        repository_root=tmp_path, sha256="a"*64, authority_path=lambda name: tmp_path / name)
    tei = b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div type="jats:fig"><head>Figure 1</head><p>The diagram.</p><figure><graphic url="original.tif"/></figure></div></body></text></TEI>'
    return source, tei, handoff


def test_binds_separate_image_identity_without_rewriting_tei(media):
    source, tei, _ = media
    roots, approved = {}, []
    artifacts, presentations = _ajops_media(source, tei, "ajops-v1-2024-a11", roots, approved, "source")
    assert len(artifacts) == len(presentations) == len(roots) == len(approved) == 1
    assert artifacts[0]["sha256"] == presentations[0]["sha256"]
    assert artifacts[0]["presentation_kind"] == "image-facsimile"
    assert presentations[0]["artifact_id"] == artifacts[0]["id"]
    assert b'url="original.tif"' in tei


@pytest.mark.parametrize("mutation", ["work", "caption", "graphic", "pdf", "image", "coverage", "handoff"])
def test_rejects_unbound_or_drifted_media(media, mutation):
    source, tei, handoff = media
    work = "ajops-v1-2024-a11"
    if mutation == "work":
        work = "ajops-v1-2024-a22"
    elif mutation == "caption":
        tei = tei.replace(b"The diagram.", b"Another diagram.")
    elif mutation == "graphic":
        tei = tei.replace(b"original.tif", b"other.tif")
    elif mutation == "pdf":
        next(a for a in source.record["authorities"] if a["role"] == "comparison-witness")["sha256"] = "b"*64
    elif mutation == "image":
        (source.repository_root / "figure.png").write_bytes(b"changed image")
    elif mutation == "coverage":
        tei = tei.replace(b"</body>", b'<div type="jats:fig"><figure><graphic url="missing.tif"/></figure></div></body>')
    else:
        (source.repository_root / "handoff.json").write_bytes(b"{}")
    with pytest.raises(ReviewContractError):
        _ajops_media(source, tei, work, {}, [], "source")
