from __future__ import annotations

import re
from typing import Any, Mapping


PURPOSES = {
    "REDUCE_FILE_SIZE",
    "REDUCE_DIMENSIONS",
    "MEET_UPLOAD_LIMITS",
    "IMPROVE_LOW_QUALITY",
}
REQUESTED_ACTIONS = {
    None,
    "LOSSLESS_COMPRESSION",
    "RESIZE_REDUCTION",
    "UPLOAD_ADAPTATION",
}
RESIZE_STRATEGIES = {
    "FIXED_SHORT_SIDE": "target_short_side",
    "SCALE_RATIO": "scale_ratio",
    "FIXED_WIDTH": "target_width",
    "FIXED_HEIGHT": "target_height",
}
TOP_LEVEL_FIELDS = {"file_token", "purpose", "targets", "requested_action"}
UPLOAD_FIELDS = {"max_width", "max_height", "max_bytes"}
RESIZE_FIELDS = {"resize_strategy", *RESIZE_STRATEGIES.values()}

ERROR_MESSAGES = {
    "INVALID_REQUEST_BODY": "请求体必须是仅包含固定字段的 JSON 对象。",
    "INVALID_PURPOSE": "purpose 不在阶段5固定枚举中。",
    "INVALID_REQUESTED_ACTION": "requested_action 不在阶段5固定枚举中。",
    "MISSING_RESIZE_TARGET": "尺寸缩小请求缺少唯一目标策略和参数。",
    "CONFLICTING_TARGETS": "目标参数包含多个或相互冲突的尺寸语义。",
    "MISSING_UPLOAD_LIMITS": "上传适配至少需要一个上传限制。",
    "INVALID_TARGET_VALUE": "目标参数类型、范围或字段不合法。",
    "ABSOLUTE_PATH_NOT_ALLOWED": "file_token 只允许安全 token，不允许本地路径。",
    "IMAGE_DECODE_FAILED": "图片无法完成解码。",
}


class PreflightContractError(ValueError):
    def __init__(self, code: str, *, status_code: int = 400, message: str | None = None) -> None:
        super().__init__(message or ERROR_MESSAGES.get(code, code))
        self.code = code
        self.status_code = status_code
        self.message = message or ERROR_MESSAGES.get(code, code)

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _looks_like_absolute_path(value: str) -> bool:
    token = value.strip()
    return bool(
        re.match(r"^[A-Za-z]:[\\/]", token)
        or token.startswith(("/", "\\\\", "file://", "file:\\\\"))
    )


def _validate_resize_targets(targets: Mapping[str, Any]) -> None:
    strategy = targets.get("resize_strategy")
    present = [field for field in RESIZE_STRATEGIES.values() if field in targets]
    if strategy is None and not present:
        raise PreflightContractError("MISSING_RESIZE_TARGET")
    if strategy not in RESIZE_STRATEGIES:
        raise PreflightContractError("INVALID_TARGET_VALUE")
    expected = RESIZE_STRATEGIES[strategy]
    if present != [expected]:
        if not present:
            raise PreflightContractError("MISSING_RESIZE_TARGET")
        raise PreflightContractError("CONFLICTING_TARGETS")
    value = targets[expected]
    if expected == "scale_ratio":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < float(value) < 1:
            raise PreflightContractError("INVALID_TARGET_VALUE")
    elif not _is_positive_int(value):
        raise PreflightContractError("INVALID_TARGET_VALUE")


def _validate_upload_targets(targets: Mapping[str, Any], *, required: bool) -> None:
    present = [field for field in UPLOAD_FIELDS if field in targets]
    if required and not present:
        raise PreflightContractError("MISSING_UPLOAD_LIMITS")
    if any(not _is_positive_int(targets[field]) for field in present):
        raise PreflightContractError("INVALID_TARGET_VALUE")


def validate_preflight_request(payload: Any) -> dict[str, Any]:
    """Validate and normalize the frozen Stage 5 request contract."""

    if not isinstance(payload, Mapping):
        raise PreflightContractError("INVALID_REQUEST_BODY")
    if set(payload) != TOP_LEVEL_FIELDS:
        raise PreflightContractError("INVALID_REQUEST_BODY")

    file_token = payload.get("file_token")
    if not isinstance(file_token, str) or not file_token.strip():
        raise PreflightContractError("INVALID_REQUEST_BODY")
    if _looks_like_absolute_path(file_token):
        raise PreflightContractError("ABSOLUTE_PATH_NOT_ALLOWED")

    purpose = payload.get("purpose")
    if purpose not in PURPOSES:
        raise PreflightContractError("INVALID_PURPOSE")
    requested_action = payload.get("requested_action")
    if requested_action not in REQUESTED_ACTIONS:
        raise PreflightContractError("INVALID_REQUESTED_ACTION")
    targets = payload.get("targets")
    if not isinstance(targets, Mapping):
        raise PreflightContractError("INVALID_REQUEST_BODY")

    resize_required = purpose == "REDUCE_DIMENSIONS" or requested_action == "RESIZE_REDUCTION"
    upload_required = purpose == "MEET_UPLOAD_LIMITS" or requested_action == "UPLOAD_ADAPTATION"
    allowed = set()
    if purpose == "REDUCE_FILE_SIZE":
        allowed.update(UPLOAD_FIELDS)
    if resize_required:
        allowed.update(RESIZE_FIELDS)
    if upload_required:
        allowed.update(UPLOAD_FIELDS)
    if purpose == "IMPROVE_LOW_QUALITY" and targets:
        raise PreflightContractError("INVALID_TARGET_VALUE")
    if any(field not in allowed for field in targets):
        raise PreflightContractError("INVALID_TARGET_VALUE")

    if resize_required:
        _validate_resize_targets(targets)
    if upload_required:
        _validate_upload_targets(targets, required=True)
    elif purpose == "REDUCE_FILE_SIZE":
        _validate_upload_targets(targets, required=False)

    return {
        "file_token": file_token.strip(),
        "purpose": purpose,
        "targets": dict(targets),
        "requested_action": requested_action,
    }
