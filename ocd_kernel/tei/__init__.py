"""Shared TEI infrastructure."""

from ocd_kernel.tei.normalization import normalize, normalize_block, normalize_inline
from ocd_kernel.tei.projection_profile import (
    PROFILE_ID,
    PROFILE_VERSION,
    ROLE_REGISTRY,
    TARGET_FIELD_DEFINITIONS,
)

__all__ = [
    "PROFILE_ID",
    "PROFILE_VERSION",
    "ROLE_REGISTRY",
    "TARGET_FIELD_DEFINITIONS",
    "normalize",
    "normalize_block",
    "normalize_inline",
]
