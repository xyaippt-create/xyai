"""Stage 5 deterministic image-processing preflight."""

from .contracts import PreflightContractError, validate_preflight_request
from .four_k_v1 import (
    FOUR_K_V1_MODE,
    FOUR_K_V1_OUTPUT_PROFILE,
    FOUR_K_V1_QUALITY_CAPABILITY_BOUNDARY,
    FOUR_K_V1_ROUTE,
    FOUR_K_V1_TARGET_LONG_EDGE,
    FourKV1ProcessingError,
    build_4k_v1_output_path,
    get_4k_v1_contract,
    inspect_4k_v1_source,
    plan_4k_v1_dimensions,
    process_4k_v1_image,
)
from .profile import build_image_profile
from .routing import route_preflight

__all__ = [
    "FOUR_K_V1_MODE",
    "FOUR_K_V1_OUTPUT_PROFILE",
    "FOUR_K_V1_QUALITY_CAPABILITY_BOUNDARY",
    "FOUR_K_V1_ROUTE",
    "FOUR_K_V1_TARGET_LONG_EDGE",
    "FourKV1ProcessingError",
    "PreflightContractError",
    "build_4k_v1_output_path",
    "build_image_profile",
    "get_4k_v1_contract",
    "inspect_4k_v1_source",
    "plan_4k_v1_dimensions",
    "process_4k_v1_image",
    "route_preflight",
    "validate_preflight_request",
]
