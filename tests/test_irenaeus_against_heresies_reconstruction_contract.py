from __future__ import annotations

from collections import Counter
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Mapping

from lxml import etree
import pytest

from ocd_kernel.reconstruction import SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
PINNED_SOURCE = Path(
    "D:/Library/Open Christian Data/raw/ccel/anf/anf01.xml"
)
SOURCE_PATH = Path("raw/ccel/anf/anf01.xml")
SOURCE_BYTES = 4_511_814
SOURCE_SHA256 = "8012ea0e35b497d2fbd783f9d4fd7b3a27d98c6dc66fd427b50d7312e6dd45af"
SELECTED_BOOKS = ("ix.ii", "ix.iii", "ix.iv", "ix.vi", "ix.vii")
ALL_IRENAEUS_DIV2 = (
    "ix.i",
    "ix.ii",
    "ix.iii",
    "ix.iv",
    "ix.v",
    "ix.vi",
    "ix.vii",
    "ix.viii",
)
EXPECTED_COUNTS = {
    "br": 9,
    "div2": 5,
    "div3": 173,
    "h2": 5,
    "h3": 173,
    "hr": 6,
    "i": 845,
    "index": 627,
    "l": 21,
    "note": 2_138,
    "p": 2_890,
    "pb": 252,
    "q": 1,
    "scripRef": 1_564,
    "span": 444,
    "verse": 6,
}
SOURCE_MANIFEST_PATH = Path('tests/fixtures/reconstruction-runtime/puritan-irenaeus-against-heresies.source-manifest.json')
MIRROR_FILES = (
    SOURCE_MANIFEST_PATH.as_posix(),
    'tests/fixtures/reconstruction-runtime/authorities/puritan-irenaeus-against-heresies.README.source.md',
    "build/__init__.py",
    "build/tei/__init__.py",
    "build/tei/irenaeus_against_heresies_reconstruction.py",
    "build/tei/irenaeus_against_heresies_oracle.py",
    "ocd_kernel/__init__.py",
    "ocd_kernel/lib/__init__.py",
    "ocd_kernel/lib/path_io.py",
    "ocd_kernel/lib/storage_topology.py",
    "ocd_kernel/reconstruction/__init__.py",
    "ocd_kernel/reconstruction/contract.py",
    "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
    "ocd_kernel/tei/__init__.py",
    "ocd_kernel/tei/normalization.py",
    "ocd_kernel/tei/projection_profile.py",
    "ocd_kernel/tei/validate.py",
    "ocd_kernel/tei/vendor/xsd/tei_all.xsd",
    "sources/structured-text/irenaeus-against-heresies/config.json",
    "sources/structured-text/irenaeus-against-heresies/README.source.md",
    "sources/structured-text/irenaeus-against-heresies/irenaeus-against-heresies.reconstruction-profile.json",
    "sources/structured-text/irenaeus-against-heresies/irenaeus-against-heresies.source-accountability.schema.json",
    "sources/structured-text/irenaeus-against-heresies/irenaeus-against-heresies.source-manifest.json",
    "sources/structured-text/irenaeus-against-heresies/irenaeus-against-heresies.validation-policy.json",
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _parse(path: Path) -> etree._ElementTree:
    return etree.parse(
        str(path),
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            huge_tree=True,
        ),
    )


def _disposable_source_mirror(tmp_path: Path) -> tuple[Path, Path]:
    mirror = tmp_path / "ocd-lib026-mirror"
    source = mirror / SOURCE_PATH
    source.parent.mkdir(parents=True)
    shutil.copyfile(PINNED_SOURCE, source)
    return mirror, source


def _complete_disposable_mirror(tmp_path: Path) -> Path:
    mirror, _ = _disposable_source_mirror(tmp_path)
    for logical in MIRROR_FILES:
        source = ROOT / logical
        destination = mirror / logical
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return mirror


def _load_callable(path: Path, module_name: str, callable_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, callable_name)


def test_pinned_anf1_identity_scope_and_selected_census_are_exact(
    tmp_path: Path,
) -> None:
    mirror, source = _disposable_source_mirror(tmp_path)
    content = source.read_bytes()
    tree = _parse(source)
    body = tree.getroot().find("ThML.body")
    assert body is not None
    divisions = [
        child
        for child in body
        if isinstance(child.tag, str) and child.tag == "div1"
    ]
    irenaeus = [division for division in divisions if division.get("id") == "ix"]
    assert len(irenaeus) == 1
    div2 = [
        child
        for child in irenaeus[0]
        if isinstance(child.tag, str) and child.tag == "div2"
    ]
    selected = [child for child in div2 if child.get("id") in SELECTED_BOOKS]
    features = [node for book in selected for node in book.iter()]

    assert mirror != ROOT
    assert len(content) == SOURCE_BYTES
    assert _sha(content) == SOURCE_SHA256
    assert [division.get("id") for division in divisions] == [
        "i",
        "ii",
        "iii",
        "iv",
        "v",
        "vi",
        "vii",
        "viii",
        "ix",
    ]
    assert tuple(child.get("id") for child in div2) == ALL_IRENAEUS_DIV2
    assert tuple(child.get("id") for child in selected) == SELECTED_BOOKS
    assert [
        child.get("id") for child in div2 if child.get("id") not in SELECTED_BOOKS
    ] == ["ix.i", "ix.v", "ix.viii"]
    assert len(features) == 9_159
    assert sum(len(node.attrib) for node in features) == 28_874
    assert Counter(str(node.tag) for node in features) == EXPECTED_COUNTS
    assert not any(
        isinstance(node, (etree._Comment, etree._ProcessingInstruction))
        for node in features
    )


def test_producer_seam_is_bound_to_the_authoritative_five_book_scope() -> None:
    from build.tei.irenaeus_against_heresies_reconstruction import (
        CONVERTER_ID,
        CONVERTER_VERSION,
        SELECTED_BOOK_IDS,
        SOURCE_SHA256 as IMPLEMENTATION_SOURCE_SHA256,
        _convert,
    )

    assert CONVERTER_ID == "ocd-anf01-irenaeus-against-heresies-to-tei"
    assert CONVERTER_VERSION == "1"
    assert SELECTED_BOOK_IDS == SELECTED_BOOKS
    assert IMPLEMENTATION_SOURCE_SHA256 == SOURCE_SHA256
    assert _convert.converter_id == CONVERTER_ID
    assert _convert.converter_version == CONVERTER_VERSION


class _DirectSource:
    def __init__(self, source: Path) -> None:
        self._source = source
        self.record = {"source_id": "ccel-anf01-irenaeus-against-heresies"}
        self.sha256 = "1" * 64

    def verify(self) -> None:
        assert self._source.is_file()

    def authority_path(self, name: str) -> Path:
        paths = {
            "retained-thml": self._source,
            "reconstruction-profile": ROOT / "sources/structured-text/irenaeus-against-heresies/irenaeus-against-heresies.reconstruction-profile.json",
            "validation-policy": ROOT / "sources/structured-text/irenaeus-against-heresies/irenaeus-against-heresies.validation-policy.json",
            "source-accountability-schema": ROOT / "sources/structured-text/irenaeus-against-heresies/irenaeus-against-heresies.source-accountability.schema.json",
            "tei-p5-xsd": ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd",
            "candidate-package-schema": ROOT / "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
            "existing-source-config": ROOT / "sources/structured-text/irenaeus-against-heresies/config.json",
            "source-local-readme": ROOT / "sources/structured-text/irenaeus-against-heresies/README.source.md",
        }
        return paths[name]


class _DirectCandidate:
    def __init__(self, members: Mapping[str, bytes]) -> None:
        self._members = dict(members)
        self.member_names = (
            "README.source.md",
            "content.tei.xml",
            "manifest.json",
            "provenance.json",
            "source-accountability.json",
            "unresolved.jsonl",
        )
        self.manifest = {
            "contract": "ocd-candidate-package-v1",
            "status": "nonaccepted",
            "source_id": "ccel-anf01-irenaeus-against-heresies",
        }
        inventory = b"".join(
            name.encode("utf-8") + content
            for name, content in sorted(self._members.items())
        )
        self.sha256 = _sha(inventory)

    def member_bytes(self, name: str) -> bytes:
        return self._members[name]


def test_producer_emits_a_complete_five_member_faithful_candidate(
    tmp_path: Path,
) -> None:
    from build.tei.irenaeus_against_heresies_reconstruction import _convert

    _, source = _disposable_source_mirror(tmp_path)
    produced = _convert(_DirectSource(source))

    assert set(produced) == {
        "content.tei.xml",
        "source-accountability.json",
        "provenance.json",
        "unresolved.jsonl",
        "README.source.md",
    }
    accountability = json.loads(produced["source-accountability.json"])
    provenance = json.loads(produced["provenance.json"])
    tei = etree.fromstring(produced["content.tei.xml"])
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}

    assert accountability["selected_book_ids"] == list(SELECTED_BOOKS)
    assert accountability["feature_count"] == 9_159
    assert accountability["attribute_count"] == 28_874
    assert accountability["selected_direct_text_bytes"] == 370_356
    assert accountability["selected_tail_text_bytes"] == 1_018_033
    assert len(accountability["crosswalk"]) == 9_159
    assert accountability["omitted_feature_count"] == 0
    assert accountability["duplicate_feature_count"] == 0
    assert accountability["unresolved_feature_count"] == 0
    assert [item["div2_id"] for item in accountability["division_accounting"]] == list(
        ALL_IRENAEUS_DIV2
    )
    assert [
        item["div2_id"]
        for item in accountability["division_accounting"]
        if item["disposition"] == "outside-against-heresies-book-scope"
    ] == ["ix.i", "ix.v", "ix.viii"]
    assert provenance["work_id"] == "irenaeus-against-heresies"
    assert provenance["accepted_ir"] == "not_accepted"
    assert provenance["human_review"] == "required"
    assert provenance["publication"] == "not_ready"
    assert [
        node.get("{http://www.w3.org/XML/1998/namespace}id")
        for node in tei.xpath("/tei:TEI/tei:text/tei:body/*", namespaces=ns)
    ] == ["anf01-" + item.replace(".", "-") for item in SELECTED_BOOKS]


def test_oracle_seam_is_independent_of_the_producer() -> None:
    from build.tei.irenaeus_against_heresies_oracle import (
        ORACLE_ID,
        ORACLE_VERSION,
        _oracle,
    )

    oracle_path = ROOT / "build/tei/irenaeus_against_heresies_oracle.py"
    source = oracle_path.read_text(encoding="utf-8")
    assert ORACLE_ID == "ocd-anf01-irenaeus-source-to-tei-oracle"
    assert ORACLE_VERSION == "1"
    assert _oracle.oracle_id == ORACLE_ID
    assert _oracle.oracle_version == ORACLE_VERSION
    assert "irenaeus_against_heresies_reconstruction" not in source


def test_oracle_accepts_exact_candidate_and_rejects_text_and_crosswalk_drift(
    tmp_path: Path,
) -> None:
    from build.tei.irenaeus_against_heresies_oracle import _oracle
    from build.tei.irenaeus_against_heresies_reconstruction import _convert

    _, source_path = _disposable_source_mirror(tmp_path)
    source = _DirectSource(source_path)
    produced = dict(_convert(source))
    attestation = _oracle(source, _DirectCandidate(produced))
    assert attestation["status"] == "pass"
    assert attestation["findings"] == []

    text_drift = dict(produced)
    text_drift["content.tei.xml"] = text_drift["content.tei.xml"].replace(
        b"Against Heresies: Book I", b"Against Heresies: Book X", 1
    )
    with pytest.raises(ValueError):
        _oracle(source, _DirectCandidate(text_drift))

    crosswalk_drift = dict(produced)
    accountability = json.loads(crosswalk_drift["source-accountability.json"])
    accountability["crosswalk"][10], accountability["crosswalk"][11] = (
        accountability["crosswalk"][11],
        accountability["crosswalk"][10],
    )
    crosswalk_drift["source-accountability.json"] = (
        json.dumps(
            accountability,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    with pytest.raises(ValueError):
        _oracle(source, _DirectCandidate(crosswalk_drift))


def test_real_framework_reconstructs_and_validates_from_disposable_mirror(
    tmp_path: Path,
) -> None:
    mirror = _complete_disposable_mirror(tmp_path)
    source = SourceManifest.load(
        mirror / SOURCE_MANIFEST_PATH,
        repository_root=mirror,
    )
    convert = _load_callable(
        mirror / "build/tei/irenaeus_against_heresies_reconstruction.py",
        "lib026_mirror_producer",
        "_convert",
    )
    oracle = _load_callable(
        mirror / "build/tei/irenaeus_against_heresies_oracle.py",
        "lib026_mirror_oracle",
        "_oracle",
    )
    candidate = reconstruct(source, tmp_path / "candidate", convert)
    report = validate(source, candidate, oracle)

    assert report.status == "pass"
    assert report.findings == ()
    assert report.attestation["source_sha256"] == SOURCE_SHA256
    assert set(candidate.member_names) == {
        "manifest.json",
        "content.tei.xml",
        "source-accountability.json",
        "provenance.json",
        "unresolved.jsonl",
        "README.source.md",
    }


def _serialize_tei(root: etree._Element) -> bytes:
    return etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "tei-omission",
        "tei-duplication",
        "tei-reorder",
        "tei-invention",
        "tei-text",
        "crosswalk-omission",
        "crosswalk-duplication",
        "crosswalk-reorder",
        "crosswalk-invention",
        "metadata",
        "provenance-boundary",
        "candidate-boundary",
        "unresolved-evidence",
        "readme-evidence",
    ],
)
def test_oracle_rejects_every_required_drift_class(
    tmp_path: Path,
    mutation: str,
) -> None:
    from build.tei.irenaeus_against_heresies_oracle import _oracle
    from build.tei.irenaeus_against_heresies_reconstruction import _convert

    _, source_path = _disposable_source_mirror(tmp_path)
    source = _DirectSource(source_path)
    produced = dict(_convert(source))
    candidate = _DirectCandidate(produced)

    if mutation.startswith("tei-"):
        root = etree.fromstring(produced["content.tei.xml"])
        ns = {"tei": "http://www.tei-c.org/ns/1.0"}
        book = root.xpath("/tei:TEI/tei:text/tei:body/tei:div[1]", namespaces=ns)[0]
        children = [child for child in book if isinstance(child.tag, str)]
        if mutation == "tei-omission":
            book.remove(children[-1])
        elif mutation == "tei-duplication":
            book.append(copy.deepcopy(children[-1]))
        elif mutation == "tei-reorder":
            book.remove(children[1])
            book.insert(3, children[1])
        elif mutation == "tei-invention":
            book.append(etree.Element("{http://www.tei-c.org/ns/1.0}seg"))
        else:
            target = next(node for node in book.iter() if node.text)
            target.text = target.text + " invented"
        produced["content.tei.xml"] = _serialize_tei(root)
        candidate = _DirectCandidate(produced)
    elif mutation.startswith("crosswalk-"):
        accountability = json.loads(produced["source-accountability.json"])
        rows = accountability["crosswalk"]
        if mutation == "crosswalk-omission":
            rows.pop()
        elif mutation == "crosswalk-duplication":
            rows[20] = copy.deepcopy(rows[19])
        elif mutation == "crosswalk-reorder":
            rows[20], rows[21] = rows[21], rows[20]
        else:
            rows.append(copy.deepcopy(rows[-1]))
        produced["source-accountability.json"] = (
            json.dumps(
                accountability,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        candidate = _DirectCandidate(produced)
    elif mutation in {"metadata", "provenance-boundary"}:
        provenance = json.loads(produced["provenance.json"])
        if mutation == "metadata":
            provenance["author"] = "Invented Author"
        else:
            provenance["accepted_ir"] = "accepted"
        produced["provenance.json"] = (
            json.dumps(
                provenance,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        candidate = _DirectCandidate(produced)
    elif mutation == "candidate-boundary":
        candidate.manifest["source_id"] = "invented-source"
    elif mutation == "unresolved-evidence":
        lines = produced["unresolved.jsonl"].splitlines(keepends=True)
        produced["unresolved.jsonl"] = b"".join(reversed(lines))
        candidate = _DirectCandidate(produced)
    else:
        produced["README.source.md"] = produced["README.source.md"].replace(
            b"nonaccepted", b"accepted", 1
        )
        candidate = _DirectCandidate(produced)

    with pytest.raises(ValueError):
        _oracle(source, candidate)


def test_candidate_is_byte_identical_across_fresh_processes_and_cwds(
    tmp_path: Path,
) -> None:
    mirror = _complete_disposable_mirror(tmp_path)
    cwd_a = tmp_path / "cwd-a"
    cwd_b = tmp_path / "cwd-b"
    cwd_a.mkdir()
    cwd_b.mkdir()
    script = """
import hashlib
import importlib.util
from pathlib import Path
import sys
from ocd_kernel.reconstruction import SourceManifest, reconstruct
mirror = Path(sys.argv[1])
destination = Path(sys.argv[2])
spec = importlib.util.spec_from_file_location('lib026_fresh_producer', mirror / 'build/tei/irenaeus_against_heresies_reconstruction.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
source = SourceManifest.load(mirror / 'tests/fixtures/reconstruction-runtime/puritan-irenaeus-against-heresies.source-manifest.json', repository_root=mirror)
candidate = reconstruct(source, destination, module._convert)
print(candidate.sha256 + ' ' + hashlib.sha256(candidate.member_bytes('content.tei.xml')).hexdigest())
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    outputs = []
    for ordinal, cwd in enumerate((cwd_a, cwd_b), start=1):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                str(mirror),
                str(tmp_path / f"fresh-candidate-{ordinal}"),
            ],
            cwd=cwd,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        outputs.append(result.stdout.strip())
    assert outputs[0] == outputs[1]
