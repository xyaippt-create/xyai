from __future__ import annotations

import math
from typing import Any, Mapping


SCHEMA_VERSION = "1.0"
DECISION_VERSION = "image_processing_routing_v1"


def _half_up(value: float) -> int:
    return max(1, int(math.floor(value + 0.5)))


def _estimated(width: int | None = None, height: int | None = None, max_bytes: int | None = None) -> dict[str, int | None]:
    return {
        "width": width,
        "height": height,
        "short_side": min(width, height) if width is not None and height is not None else None,
        "long_side": max(width, height) if width is not None and height is not None else None,
        "max_bytes": max_bytes,
    }


def _result(
    profile: Mapping[str, Any],
    purpose: str,
    *,
    status: str,
    action: str,
    executable: bool,
    reasons: list[str] | None = None,
    blocking: list[str] | None = None,
    warnings: list[str] | None = None,
    parameters: dict[str, Any] | None = None,
    estimated_output: dict[str, Any] | None = None,
    alternatives: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "decision_version": DECISION_VERSION,
        "profile": dict(profile),
        "purpose": purpose,
        "preflight_status": status,
        "recommended_action": action,
        "executable": executable,
        "reason_codes": list(dict.fromkeys(reasons or [])),
        "blocking_reasons": list(dict.fromkeys(blocking or [])),
        "warnings": list(dict.fromkeys(warnings or [])),
        "recommended_parameters": parameters or {},
        "estimated_output": estimated_output or _estimated(),
        "alternatives": alternatives or [],
    }


def _profile_fact_warnings(profile: Mapping[str, Any], *, include_long: bool = True) -> list[str]:
    allowed = {"ALPHA_CHANNEL_PRESENT", "ULTRA_WIDE_IMAGE_DETECTED"}
    if include_long:
        allowed.add("LONG_IMAGE_DETECTED")
    return [code for code in profile.get("warnings", []) if code in allowed]


def _unsupported(profile: Mapping[str, Any], purpose: str) -> dict[str, Any]:
    reasons = [
        code
        for code in profile.get("warnings", [])
        if code in {"ANIMATED_IMAGE_NOT_SUPPORTED", "MULTI_FRAME_IMAGE_NOT_SUPPORTED", "FORMAT_NOT_SUPPORTED"}
    ]
    warnings = [code for code in profile.get("warnings", []) if code not in reasons]
    return _result(
        profile,
        purpose,
        status="UNSUPPORTED_MODE",
        action="UNSUPPORTED",
        executable=False,
        reasons=reasons,
        blocking=reasons,
        warnings=warnings,
    )


def _resize_dimensions(profile: Mapping[str, Any], targets: Mapping[str, Any]) -> tuple[int, int]:
    width, height = int(profile["width"]), int(profile["height"])
    strategy = targets["resize_strategy"]
    if strategy == "FIXED_SHORT_SIDE":
        scale = int(targets["target_short_side"]) / min(width, height)
        return _half_up(width * scale), _half_up(height * scale)
    if strategy == "FIXED_WIDTH":
        target_width = int(targets["target_width"])
        return target_width, _half_up(height * target_width / width)
    if strategy == "FIXED_HEIGHT":
        target_height = int(targets["target_height"])
        return _half_up(width * target_height / height), target_height
    scale = float(targets["scale_ratio"])
    return _half_up(width * scale), _half_up(height * scale)


def _resize_limit(profile: Mapping[str, Any], targets: Mapping[str, Any]) -> tuple[int, int, str, int | float]:
    strategy = targets["resize_strategy"]
    field = {
        "FIXED_SHORT_SIDE": "target_short_side",
        "FIXED_WIDTH": "target_width",
        "FIXED_HEIGHT": "target_height",
        "SCALE_RATIO": "scale_ratio",
    }[strategy]
    source_value: int | float = {
        "FIXED_SHORT_SIDE": int(profile["short_side"]),
        "FIXED_WIDTH": int(profile["width"]),
        "FIXED_HEIGHT": int(profile["height"]),
        "SCALE_RATIO": 1.0,
    }[strategy]
    return int(profile["width"]), int(profile["height"]), field, source_value


def _resize_route(profile: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    purpose = str(request["purpose"])
    targets = request["targets"]
    _, _, field, source_value = _resize_limit(profile, targets)
    requested_value = targets[field]
    manual = request.get("requested_action") == "RESIZE_REDUCTION"
    if requested_value > source_value:
        reasons = ["TARGET_EXCEEDS_SOURCE", "NO_UPSCALE"]
        blocking = list(reasons)
        if manual:
            reasons.append("MANUAL_ACTION_BLOCKED_BY_SAFETY_GATE")
            blocking.append("MANUAL_ACTION_BLOCKED_BY_SAFETY_GATE")
        return _result(
            profile,
            purpose,
            status="BLOCKED_UNSAFE",
            action="UNSUPPORTED",
            executable=False,
            reasons=reasons,
            blocking=blocking,
            alternatives=[{"action": "RESIZE_REDUCTION", "targets": {"resize_strategy": targets["resize_strategy"], field: source_value}}],
        )

    width, height = _resize_dimensions(profile, targets)
    if width == profile["width"] and height == profile["height"]:
        return _result(
            profile,
            purpose,
            status="NO_PROCESSING_NEEDED",
            action="NO_PROCESSING",
            executable=False,
            reasons=["TARGET_EQUALS_SOURCE", "NO_PROCESSING_REQUIRED"],
            estimated_output=_estimated(width, height),
        )

    reasons = ["TARGET_SMALLER_THAN_SOURCE"]
    warnings: list[str] = []
    blocking: list[str] = []
    parameters = {"resize_strategy": targets["resize_strategy"], field: targets[field]}
    alternatives: list[dict[str, Any]] = []
    status, action, executable = "READY", "RESIZE_REDUCTION", True
    estimate = _estimated(width, height)

    if profile.get("is_long_image"):
        reasons.append("LONG_IMAGE_DETECTED")
        if estimate["short_side"] < 600:
            reasons.append("ESTIMATED_SHORT_SIDE_LT_600")
            blocking.append("ESTIMATED_SHORT_SIDE_LT_600")
            parameters = {"min_safe_short_side": 600, "preferred_short_side": 750}
            alternatives = [{"action": "RESIZE_REDUCTION", "targets": {"resize_strategy": "FIXED_SHORT_SIDE", "target_short_side": 750}}]
            status, action, executable = "BLOCKED_UNSAFE", "UNSUPPORTED", False
        elif estimate["short_side"] < 750:
            reasons.append("ESTIMATED_SHORT_SIDE_600_749")
            warnings.append("ESTIMATED_SHORT_SIDE_600_749")
            parameters["requires_risk_confirmation"] = True
            alternatives = [{"action": "RESIZE_REDUCTION", "targets": {"resize_strategy": "FIXED_SHORT_SIDE", "target_short_side": 750}}]
            status = "READY_WITH_WARNING"
        else:
            reasons.append("ESTIMATED_SHORT_SIDE_GE_750")

    if profile.get("is_ultra_wide"):
        reasons.append("ULTRA_WIDE_IMAGE_DETECTED")
        warnings.append("ULTRA_WIDE_IMAGE_DETECTED")
        if status == "READY":
            status = "READY_WITH_WARNING"
    for code in _profile_fact_warnings(profile, include_long=False):
        if code not in warnings and code != "ULTRA_WIDE_IMAGE_DETECTED":
            warnings.append(code)
            if status == "READY":
                status = "READY_WITH_WARNING"

    if manual and purpose != "REDUCE_DIMENSIONS" and executable:
        reasons.append("MANUAL_ACTION_CONFLICTS_WITH_PURPOSE")
        warnings.append("MANUAL_ACTION_CONFLICTS_WITH_PURPOSE")
        status = "READY_WITH_WARNING"
        upload_targets = {key: targets[key] for key in ("max_width", "max_height", "max_bytes") if key in targets}
        alternatives = [{"action": "UPLOAD_ADAPTATION", "targets": upload_targets}]

    return _result(
        profile,
        purpose,
        status=status,
        action=action,
        executable=executable,
        reasons=reasons,
        blocking=blocking,
        warnings=warnings,
        parameters=parameters,
        estimated_output=estimate,
        alternatives=alternatives,
    )


def _upload_dimensions(profile: Mapping[str, Any], targets: Mapping[str, Any]) -> tuple[int, int]:
    width, height = int(profile["width"]), int(profile["height"])
    ratios = [1.0]
    if "max_width" in targets:
        ratios.append(int(targets["max_width"]) / width)
    if "max_height" in targets:
        ratios.append(int(targets["max_height"]) / height)
    scale = min(ratios)
    return _half_up(width * scale), _half_up(height * scale)


def _upload_route(profile: Mapping[str, Any], request: Mapping[str, Any], *, file_size_purpose: bool = False) -> dict[str, Any]:
    purpose = str(request["purpose"])
    targets = request["targets"]
    max_bytes = targets.get("max_bytes")
    all_met = (
        ("max_width" not in targets or profile["width"] <= targets["max_width"])
        and ("max_height" not in targets or profile["height"] <= targets["max_height"])
        and (max_bytes is None or profile["size_bytes"] <= max_bytes)
    )
    if all_met:
        reasons = ["NO_PROCESSING_REQUIRED"] if file_size_purpose else ["UPLOAD_LIMITS_ALREADY_MET", "NO_PROCESSING_REQUIRED"]
        return _result(
            profile,
            purpose,
            status="NO_PROCESSING_NEEDED",
            action="NO_PROCESSING",
            executable=False,
            reasons=reasons,
            estimated_output=_estimated(int(profile["width"]), int(profile["height"]), max_bytes),
        )

    width, height = _upload_dimensions(profile, targets)
    estimate = _estimated(width, height, max_bytes)
    reasons = ["UPLOAD_LIMITS_REQUIRE_ADAPTATION"]
    warnings = _profile_fact_warnings(profile)
    parameters = {key: targets[key] for key in ("max_width", "max_height", "max_bytes") if key in targets}
    alternatives: list[dict[str, Any]] = []
    status, action, executable = "READY", "UPLOAD_ADAPTATION", True
    blocking: list[str] = []

    if profile.get("is_long_image") and estimate["short_side"] < 600:
        reasons.extend(["UPLOAD_LIMITS_UNSAFE_TO_MEET", "ESTIMATED_SHORT_SIDE_LT_600"])
        blocking.extend(["UPLOAD_LIMITS_UNSAFE_TO_MEET", "ESTIMATED_SHORT_SIDE_LT_600"])
        parameters = {"min_safe_short_side": 600, "preferred_short_side": 750}
        alternatives = [
            {"action": "UPLOAD_ADAPTATION", "targets": {"max_width": 750}},
            {"action": "RESIZE_REDUCTION", "targets": {"resize_strategy": "FIXED_SHORT_SIDE", "target_short_side": 750}},
        ]
        status, action, executable = "BLOCKED_UNSAFE", "UNSUPPORTED", False
    elif profile.get("is_long_image") and estimate["short_side"] < 750:
        reasons.append("ESTIMATED_SHORT_SIDE_600_749")
        warnings.append("ESTIMATED_SHORT_SIDE_600_749")
        parameters["requires_risk_confirmation"] = True
        status = "READY_WITH_WARNING"
    elif warnings:
        status = "READY_WITH_WARNING"

    if file_size_purpose and not alternatives:
        alternatives = [{"action": "RESIZE_REDUCTION", "required_targets": ["resize_strategy"]}]
    return _result(
        profile,
        purpose,
        status=status,
        action=action,
        executable=executable,
        reasons=reasons,
        blocking=blocking,
        warnings=warnings,
        parameters=parameters,
        estimated_output=estimate,
        alternatives=alternatives,
    )


def route_preflight(profile: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    """Return the deterministic Stage 5 preflight decision for normalized input."""

    purpose = str(request["purpose"])
    requested_action = request.get("requested_action")
    if profile.get("processing_eligibility") == "UNSUPPORTED":
        return _unsupported(profile, purpose)
    if purpose == "IMPROVE_LOW_QUALITY":
        return _result(
            profile,
            purpose,
            status="ROUTE_TO_ENHANCEMENT",
            action="FUTURE_ENHANCEMENT",
            executable=False,
            reasons=["IMPROVE_LOW_QUALITY_REQUIRES_ENHANCEMENT"],
        )
    if requested_action == "RESIZE_REDUCTION":
        return _resize_route(profile, request)
    if requested_action == "UPLOAD_ADAPTATION":
        return _upload_route(profile, request)
    if requested_action == "LOSSLESS_COMPRESSION" and profile.get("format") == "JPEG":
        reasons = ["JPEG_STRICT_LOSSLESS_NOT_SUPPORTED", "FILE_SIZE_TARGET_REQUIRED", "MANUAL_ACTION_BLOCKED_BY_SAFETY_GATE"]
        return _result(
            profile,
            purpose,
            status="READY_WITH_WARNING",
            action="UNSUPPORTED",
            executable=False,
            reasons=reasons,
            blocking=reasons,
            alternatives=[{"action": "UPLOAD_ADAPTATION", "required_targets": ["max_bytes"]}],
        )
    if purpose == "REDUCE_DIMENSIONS":
        return _resize_route(profile, request)
    if purpose == "MEET_UPLOAD_LIMITS":
        return _upload_route(profile, request)
    if profile.get("format") == "PNG":
        profile_warnings = _profile_fact_warnings(profile)
        return _result(
            profile,
            purpose,
            status="READY_WITH_WARNING" if profile_warnings else "READY",
            action="LOSSLESS_COMPRESSION",
            executable=True,
            reasons=["PNG_STRICT_LOSSLESS_SUPPORTED"],
            warnings=["PNG_STRICT_LOSSLESS_MAY_HAVE_NO_GAIN", *profile_warnings],
            parameters={"preserve_format": "PNG", "preserve_dimensions": True, "preserve_alpha": True},
            estimated_output=_estimated(int(profile["width"]), int(profile["height"])),
        )
    if "max_bytes" not in request["targets"]:
        reasons = ["JPEG_STRICT_LOSSLESS_NOT_SUPPORTED", "FILE_SIZE_TARGET_REQUIRED"]
        return _result(
            profile,
            purpose,
            status="READY_WITH_WARNING",
            action="UNSUPPORTED",
            executable=False,
            reasons=reasons,
            blocking=reasons,
            alternatives=[
                {"action": "UPLOAD_ADAPTATION", "required_targets": ["max_bytes"]},
                {"action": "RESIZE_REDUCTION", "required_targets": ["resize_strategy"]},
            ],
        )
    return _upload_route(profile, request, file_size_purpose=True)
