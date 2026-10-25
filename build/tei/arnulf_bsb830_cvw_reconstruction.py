"""Package Arnulf's retained openMGH division for read-only CVW comparison.

The accepted master is a byte pin, never an input to the producer. The source
division and header are reconstructed by the maintained exact-division route.
"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Mapping

from build.tei.openmgh_exclusive_reconstruction import _convert as _base_convert
from build.tei.openmgh_exact_work_div import parse_tei
from build.tools.prepare_openmgh_exact_work_div_batch import _candidate
from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header


CONVERTER_ID = "ocd-arnulf-bsb830-exact-div-cvw"
CONVERTER_VERSION = "1"


def _record(manifest: SourceManifest, name: str) -> dict:
    value = json.loads(manifest.authority_path(name).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = _record(source_manifest, "reconstruction-profile")
    exact = _record(source_manifest, "exact-work-div-manifest")
    work = _record(source_manifest, "work-sidecar")
    if (
        profile.get("contract") != "ocd-openmgh-exclusive-profile-v1"
        or exact.get("contract") != "ocd-openmgh-exact-work-div-batch-v1"
        or len(exact.get("works", [])) != 1
        or exact["works"][0].get("work_id") != profile.get("work_id")
        or work.get("work_id") != profile.get("work_id")
    ):
        raise ValueError("Arnulf exact-division profile identity drifted")
    source_bytes = source_manifest.authority_path("extracted-xml").read_bytes()
    entry = exact["works"][0]
    original = _candidate(parse_tei(source_bytes), exact, entry, work)
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    scope = (
        f"The complete top-level source work div {entry['source_work_div_index']} "
        f"named {entry['source_work_div_n']} in extracted {profile['source_path']}. "
        "Every internal node and marker belongs to this div. Other top-level work "
        "divs remain outside this work selection; no shared top-level marker exists."
    )
    candidate = bind_reviewed_header(
        original,
        expected_sha256=sha256(original).hexdigest(),
        identity={
            "work_id": profile["work_id"],
            "textual_form_id": form["textual_form_id"],
            "edition_id": edition["edition_id"],
            "acquisition_id": edition["acquisition_ids"][0],
        },
        source={
            "source_path": profile["source_path"],
            "source_sha256": profile["source_sha256"],
            "source_bytes": len(source_bytes),
        },
        source_url=profile["source_url"],
        declared_scope=scope,
        revision={
            "id": f"{profile['work_id']}-openmgh-exact-work-div-v1",
            "date": profile["revision_date"],
            "note": "Accept the complete source work div in the extracted openMGH electronic witness.",
        },
    )
    if sha256(candidate).hexdigest() != profile.get("accepted_master_sha256"):
        raise ValueError("source-derived candidate differs from pinned accepted master")
    produced = dict(_base_convert(source_manifest))
    produced["content.tei.xml"] = candidate
    return produced


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION


__all__ = ("_convert",)
