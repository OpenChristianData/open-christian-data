"""Cached LLM triage warning producer for OCR scanner candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from build.lib.paths import REPO_ROOT
from build.lib.warning_producers import WARNING_OUTPUT_SCHEMA, build_warning


PRODUCER_ID = "llm_triage"
SIGNATURE_VERSION = 1
PROMPT_VERSION = "llm-triage-v1"
EVIDENCE_SCHEMA_VERSION = "ocr-evidence-v1"
MODEL = "nvidia/meta-llama-3.3-70b-instruct"
LLM_TEMPERATURE = 0.0
DEFAULT_CACHE_DIR = REPO_ROOT / "tests" / "fixtures" / "llm_triage"

WARNING_CODES = {
    "error_no_fix": {
        "severity": "warning",
        "description": "LLM triage classified the OCR candidate as a real error without a safe fix.",
        "signature_fields": ["entry_id", "field_path", "code", "candidate_signature"],
    },
    "not_error": {
        "severity": "info",
        "description": "LLM triage classified the OCR candidate as not an error.",
        "signature_fields": ["entry_id", "field_path", "code", "candidate_signature"],
    },
    "uncertain": {
        "severity": "warning",
        "description": "LLM triage could not confidently classify the OCR candidate.",
        "signature_fields": ["entry_id", "field_path", "code", "candidate_signature"],
    },
    "producer_budget_exhausted": {
        "severity": "warning",
        "description": "LLM triage could not classify candidates within the configured live-call budget.",
        "signature_fields": ["entry_id", "field_path", "code", "candidate_signature"],
    },
}
APPLIES_TO_RESOURCE_TYPES = ["encyclopedia", "commentary", "sermon_collection", "anthology"]
REQUIRES_CAPABILITIES = {}
CONSUMES = ["ocr_scanner"]
PRODUCES_SCHEMA = {
    "type": "object",
    "properties": {
        "warnings": WARNING_OUTPUT_SCHEMA["properties"]["warnings"],
        "silenced_by_threshold": {"type": "integer"},
    },
    "required": ["warnings", "silenced_by_threshold"],
    "additionalProperties": False,
}
SCOPE = "record_local"


@dataclass(frozen=True)
class TriageOptions:
    max_llm_calls: int = 0
    max_llm_cost_usd: float = 0.0
    llm_cache_dir: Path = DEFAULT_CACHE_DIR
    enable_llm_triage: bool = False
    model: str = MODEL
    prompt_version: str = PROMPT_VERSION
    evidence_schema_version: str = EVIDENCE_SCHEMA_VERSION
    llm_temperature: float = LLM_TEMPERATURE


def run(record: dict, meta: dict, upstream_outputs: dict) -> dict:
    return run_with_options(record, meta, upstream_outputs, TriageOptions())


def run_with_options(record: dict, meta: dict, upstream_outputs: dict, options: TriageOptions) -> dict:
    ocr_output = upstream_outputs.get("ocr_scanner")
    candidates = ocr_output.get("candidates") if isinstance(ocr_output, dict) else None
    if not isinstance(candidates, list) or not candidates:
        return {"warnings": [], "silenced_by_threshold": 0}

    cache = load_cache(options.llm_cache_dir, options)
    warnings: list[dict[str, Any]] = []
    calls_used = 0
    budget_exhausted = 0

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        key = cache_key(
            model=options.model,
            prompt_version=options.prompt_version,
            candidate_signature=str(candidate.get("signature") or ""),
            evidence_schema_version=options.evidence_schema_version,
            llm_temperature=options.llm_temperature,
        )
        cached = cache.get(key)
        if isinstance(cached, dict):
            warnings.append(_classification_warning(candidate, cached))
            continue
        if not _live_budget_available(options, calls_used):
            warnings.append(_budget_warning(candidate))
            budget_exhausted += 1
            continue
        classification = _classify_with_live_clients(candidate, options)
        calls_used += 1
        warnings.append(_classification_warning(candidate, classification))

    return {"warnings": warnings, "silenced_by_threshold": budget_exhausted}


def cache_key(
    *,
    model: str,
    prompt_version: str,
    candidate_signature: str,
    evidence_schema_version: str,
    llm_temperature: float,
) -> str:
    payload = json.dumps(
        {
            "model": model,
            "prompt_version": prompt_version,
            "candidate_signature": candidate_signature,
            "evidence_schema_version": evidence_schema_version,
            "llm_temperature": llm_temperature,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_cache(cache_dir: Path, options: TriageOptions) -> dict[str, dict[str, Any]]:
    cache_dir = Path(cache_dir)
    responses: dict[str, dict[str, Any]] = {}
    if not cache_dir.exists():
        return responses
    for path in sorted(cache_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("prompt_version") != options.prompt_version:
            continue
        if payload.get("evidence_schema_version") != options.evidence_schema_version:
            continue
        if payload.get("model") != options.model:
            continue
        if float(payload.get("llm_temperature", -1)) != options.llm_temperature:
            continue
        path_responses = payload.get("responses")
        if isinstance(path_responses, dict):
            responses.update({key: value for key, value in path_responses.items() if isinstance(value, dict)})
    return responses


def _classification_warning(candidate: dict[str, Any], classification: dict[str, Any]) -> dict[str, Any]:
    code = str(classification.get("classification") or "uncertain")
    if code not in {"error_no_fix", "not_error", "uncertain"}:
        code = "uncertain"
    confidence = float(classification.get("confidence") or 0)
    evidence = {
        "surface": str(candidate.get("value") or ""),
        "snippet": str(candidate.get("snippet") or "")[:120],
        "candidate_signature": str(candidate.get("signature") or ""),
        "ocr_code": str(candidate.get("reason") or ""),
        "classification": code,
        "confidence": confidence,
        "reasoning": str(classification.get("reasoning") or "cached triage"),
    }
    return build_warning(
        producer=__import__(__name__, fromlist=[""]),
        code=code,
        entry_id=str(candidate.get("entry_id") or "") or None,
        field_path=str(candidate.get("field_path") or "") or None,
        message=f"{candidate.get('entry_id') or 'Entry'}: LLM triage classified OCR candidate as {code}.",
        evidence=evidence,
        signature_values={"candidate_signature": evidence["candidate_signature"]},
    )


def _budget_warning(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence = {
        "surface": str(candidate.get("value") or ""),
        "snippet": str(candidate.get("snippet") or "")[:120],
        "candidate_signature": str(candidate.get("signature") or ""),
        "ocr_code": str(candidate.get("reason") or ""),
        "classification": "producer_budget_exhausted",
        "confidence": 0,
        "reasoning": "No cached triage response and live LLM triage is disabled or out of budget.",
    }
    return build_warning(
        producer=__import__(__name__, fromlist=[""]),
        code="producer_budget_exhausted",
        entry_id=str(candidate.get("entry_id") or "") or None,
        field_path=str(candidate.get("field_path") or "") or None,
        message="LLM triage cache miss; live triage budget exhausted.",
        evidence=evidence,
        signature_values={"candidate_signature": evidence["candidate_signature"]},
    )


def _live_budget_available(options: TriageOptions, calls_used: int) -> bool:
    return options.enable_llm_triage and options.max_llm_calls > calls_used and options.max_llm_cost_usd > 0


def _classify_with_live_clients(candidate: dict[str, Any], options: TriageOptions) -> dict[str, Any]:
    from build.tools.ocr_scanner.llm_triage import gemini_classifier  # noqa: F401
    from build.tools.ocr_scanner.llm_triage import openai_compat_classifier  # noqa: F401

    raise RuntimeError("live_llm_triage_not_implemented_for_producer")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-llm-calls", type=int, default=0)
    parser.add_argument("--max-llm-cost-usd", type=float, default=0.0)
    parser.add_argument("--llm-cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--enable-llm-triage", action="store_true", default=False)
    return parser.parse_args(argv)


def options_from_args(args: argparse.Namespace) -> TriageOptions:
    return TriageOptions(
        max_llm_calls=args.max_llm_calls,
        max_llm_cost_usd=args.max_llm_cost_usd,
        llm_cache_dir=args.llm_cache_dir,
        enable_llm_triage=args.enable_llm_triage,
    )


def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
