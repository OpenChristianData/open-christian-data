"""Exact prior source notes for frozen historical notice-index test fixtures."""

from hashlib import sha256


CURRENT_TARGET_APPENDIX = "\n## Current accepted-target notice binding \u2014 2026-10-09\n".encode("utf-8")


def frozen_source_note(raw: bytes, expected_sha256: str) -> bytes:
    if sha256(raw).hexdigest() == expected_sha256:
        return raw
    if raw.count(CURRENT_TARGET_APPENDIX) == 1:
        original, _appendix = raw.split(CURRENT_TARGET_APPENDIX, 1)
        if sha256(original).hexdigest() == expected_sha256:
            return original
    raise ValueError("Source note does not preserve the frozen notice-index preimage")
