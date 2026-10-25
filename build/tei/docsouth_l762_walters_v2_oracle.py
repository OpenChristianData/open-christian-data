"""Independent Walters title-boundary and retained-image candidate oracle."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping
from xml.etree import ElementTree as ET

from build.tei.docsouth_l761_l762_one_root_v2_oracle import (
    _oracle as _oracle_with_assets,
)
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-docsouth-l762-walters-title-and-retained-assets-oracle"
ORACLE_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
T = "{" + TEI + "}"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def _oracle(
    manifest: SourceManifest, candidate: CandidatePackage
) -> Mapping[str, object]:
    """Check generic fidelity, all image members, and the source title boundary."""
    result = dict(_oracle_with_assets(manifest, candidate))
    findings = list(result["findings"])

    if manifest.record.get("source_id") != "docsouth-walters":
        findings.append("source manifest is not the exact Walters route")
    if manifest.record.get("work_id") != "alexander-walters-my-life-and-work":
        findings.append("source manifest work identity differs from L762 Walters")

    profile = json.loads(manifest.authority_path("profile").read_bytes())
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    expected_title_binding = profile.get("top_level_titled_work")
    if account.get("top_level_titled_work") != expected_title_binding:
        findings.append("candidate source accounting does not bind the titled-work identity")

    try:
        source = ET.fromstring(
            manifest.authority_path("official-source-member").read_bytes()
        )
        output = ET.fromstring(candidate.member_bytes("content.tei.xml"))
    except ET.ParseError as exc:
        findings.append(f"title-boundary XML parsing failed: {exc}")
    else:
        source_titles = source.findall("text/front/titlePage/docTitle")
        output_titles = output.findall(T + "text/" + T + "front/" + T + "titlePage/" + T + "docTitle")
        source_title = _text(source_titles[0]) if len(source_titles) == 1 else ""
        output_title = _text(output_titles[0]) if len(output_titles) == 1 else ""
        if len(source_titles) != 1 or len(output_titles) != 1:
            findings.append("source and candidate must each preserve one displayed title page")
        if not source_title or source_title != output_title:
            findings.append("source-attested top-level title differs from candidate title page")
        if (
            not isinstance(expected_title_binding, dict)
            or expected_title_binding.get("title") != source_title
            or expected_title_binding.get("work_id")
            != "alexander-walters-my-life-and-work"
        ):
            findings.append("profile top-level titled-work boundary differs from the source")

    result["status"] = "pass" if not findings else "fail"
    result["oracle_id"] = ORACLE_ID
    result["oracle_version"] = ORACLE_VERSION
    oracle_path = Path(__file__).resolve()
    assets_path = Path(_oracle_with_assets.__code__.co_filename).resolve()
    one_root_path = assets_path.with_name("docsouth_l761_l762_one_root_oracle.py")
    result["implementation_sha256"] = _sha(oracle_path.read_bytes())
    result["import_closure_sha256"] = _sha(
        oracle_path.read_bytes() + assets_path.read_bytes() + one_root_path.read_bytes()
    )
    result["findings"] = findings
    result.pop("result_sha256", None)
    result["result_sha256"] = _sha(_json(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
