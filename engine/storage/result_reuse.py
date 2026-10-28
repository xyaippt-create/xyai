"""Resolve one registered formal Result as a safe reusable image Source."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from engine.storage.app_data_migration import resolve_migrated_formal_output_path

SOURCE_ORIGIN_EXISTING_RESULT = "EXISTING_RESULT"


class ResultReuseError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _mapping(value: Any) -> Mapping[str, Any]:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return value if isinstance(value, Mapping) else {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def result_reuse_denial(record: Mapping[str, Any]) -> str:
    action = str(record.get("result_action") or record.get("d3_final_action") or "").upper()
    review = str(record.get("result_review_status") or "").lower()
    if action in {"ACCEPT_ORIGINAL", "KEEP_ORIGINAL", "PROTECTION_BLOCKED"}:
        return "该决定没有可继续编辑的成功 Result。"
    if action == "REVIEW_REQUIRED" and review != "confirmed":
        return "该结果尚待确认，不能作为成功 Result 继续编辑。"
    if review == "rejected":
        return "该结果已被拒绝，不能继续编辑。"
    return ""


def registered_result_fact(registry: Mapping[str, Any] | None, result_id: str) -> dict[str, Any]:
    normalized_result_id = str(result_id or "").strip()
    if not normalized_result_id:
        raise ResultReuseError("RESULT_REUSE_ID_REQUIRED", "缺少要继续处理的结果编号。", status_code=400)
    if registry is None:
        raise ResultReuseError("RESULT_REUSE_REGISTRY_UNAVAILABLE", "统一结果记录当前不可用。", status_code=503)
    matches: list[dict[str, Any]] = []
    for record in registry.values():
        if not isinstance(record, Mapping):
            continue
        if record.get("record_kind") == "compression_batch":
            continue  # Membership references cannot override authoritative Result facts.
        task_result = _mapping(record.get("task_result"))
        result = _mapping(record.get("result"))
        nested_items = result.get("items") if isinstance(result.get("items"), list) else record.get("items")
        candidates = [record]
        if isinstance(nested_items, list):
            candidates.extend(item for item in nested_items if isinstance(item, Mapping))
        for candidate in candidates:
            registered_result_id = str(
                candidate.get("result_id")
                or (task_result.get("result_id") if candidate is record else "")
                or (result.get("result_id") if candidate is record else "")
                or ""
            ).strip()
            if registered_result_id != normalized_result_id:
                continue
            matches.append({
                "fact": {**result, **task_result, **record, **candidate},
                "source_result_id": normalized_result_id,
                "source_task_id": str(candidate.get("task_id") or record.get("task_id") or "").strip(),
                "source_feature_key": str(record.get("feature_key") or candidate.get("feature_key") or "").strip(),
                "raw_path": str(candidate.get("result_file") or candidate.get("output_path") or (task_result.get("result_file") if candidate is record else "") or (result.get("result_file") if candidate is record else "") or (result.get("output_path") if candidate is record else "") or (result.get("final_output_path") if candidate is record else "") or "").strip(),
                "status": str(candidate.get("task_status") or candidate.get("status") or record.get("task_status") or record.get("status") or "").strip().lower(),
                "registered_output_sha256": str(candidate.get("output_sha256") or (task_result.get("output_sha256") if candidate is record else "") or (result.get("output_sha256") if candidate is record else "") or "").strip().lower(),
            })

    if not matches:
        raise ResultReuseError("RESULT_REUSE_NOT_FOUND", "原结果记录不存在或历史记录不完整。", status_code=404)
    task_ids = {item["source_task_id"] for item in matches if item["source_task_id"]}
    result_paths = {item["raw_path"] for item in matches if item["raw_path"]}
    registered_hashes = {
        item["registered_output_sha256"]
        for item in matches
        if item["registered_output_sha256"]
    }
    if len(task_ids) > 1 or len(result_paths) > 1 or len(registered_hashes) > 1:
        raise ResultReuseError("RESULT_REUSE_CONFLICT", "原结果记录存在冲突，无法确定唯一成品。")
    complete_matches = [
        item
        for item in matches
        if item["source_task_id"] and item["raw_path"] and item["registered_output_sha256"]
    ]
    source = next(
        (item for item in complete_matches if item["status"] == "completed"),
        complete_matches[0] if complete_matches else matches[0],
    )
    if not source["source_task_id"] or not source["raw_path"]:
        raise ResultReuseError("RESULT_REUSE_INCOMPLETE", "原结果缺少 Task 或成品文件记录，无法继续处理。")
    if not source["registered_output_sha256"]:
        raise ResultReuseError("RESULT_REUSE_INCOMPLETE", "原结果缺少完整性校验记录，无法安全继续处理。")
    if source["status"] != "completed":
        raise ResultReuseError("RESULT_REUSE_NOT_COMPLETED", "只有已完成的正式结果可以继续处理。")
    return source


def resolve_reusable_result_source(
    registry: Mapping[str, Any] | None,
    result_id: str,
    formal_root: Path,
    *,
    max_bytes: int,
    allowed_suffixes: set[str] | frozenset[str],
) -> dict[str, Any]:
    source = registered_result_fact(registry, result_id)
    reason = result_reuse_denial(source["fact"])
    if reason:
        raise ResultReuseError("RESULT_REUSE_NOT_ACCEPTED", reason)
    root = Path(formal_root).resolve()
    try:
        path = resolve_migrated_formal_output_path(source["raw_path"], root).resolve()
        path.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ResultReuseError("RESULT_REUSE_PATH_UNSAFE", "原结果文件不在当前正式目录中，无法继续处理。") from exc
    if path.suffix.lower() not in allowed_suffixes:
        raise ResultReuseError("RESULT_REUSE_FORMAT_UNSUPPORTED", "原结果格式与目标处理器不兼容。", status_code=415)
    if not path.is_file():
        raise ResultReuseError("RESULT_REUSE_FILE_MISSING", "原结果文件已不存在，未创建新的处理结果。", status_code=404)
    try:
        size_bytes = path.stat().st_size
        actual_sha256 = _sha256(path)
    except OSError as exc:
        raise ResultReuseError("RESULT_REUSE_FILE_UNREADABLE", "原结果文件当前无法读取。") from exc
    if size_bytes <= 0:
        raise ResultReuseError("RESULT_REUSE_FILE_EMPTY", "原结果文件为空，无法继续处理。")
    if size_bytes > int(max_bytes):
        raise ResultReuseError("RESULT_REUSE_FILE_TOO_LARGE", "原结果超过目标处理器的 50MB 输入限制。", status_code=413)
    if source["registered_output_sha256"] != actual_sha256:
        raise ResultReuseError("RESULT_REUSE_INTEGRITY_MISMATCH", "原结果文件与登记记录不一致，已阻止继续处理。")
    return {
        "source_origin": SOURCE_ORIGIN_EXISTING_RESULT,
        "source_result_id": source["source_result_id"],
        "source_task_id": source["source_task_id"],
        "source_feature_key": source["source_feature_key"],
        "source_result_sha256": actual_sha256,
        "source_result_file_name": path.name,
        "source_result_path": path,
        "source_result_size_bytes": size_bytes,
    }


def result_lineage_fields(source: Mapping[str, Any] | None) -> dict[str, str]:
    if not source or source.get("source_origin") != SOURCE_ORIGIN_EXISTING_RESULT:
        return {}
    return {
        "source_origin": SOURCE_ORIGIN_EXISTING_RESULT,
        "source_result_id": str(source.get("source_result_id") or ""),
        "source_task_id": str(source.get("source_task_id") or ""),
        "source_feature_key": str(source.get("source_feature_key") or ""),
        "source_result_sha256": str(source.get("source_result_sha256") or ""),
    }


def result_lineage(registry: Mapping[str, Any], result_id: str) -> dict[str, Any]:
    """Project the persisted parent edges; do not create IDs, counters or file guesses."""
    rows, seen = [], set()
    current_id = result_id
    while current_id:
        if current_id in seen or len(seen) >= 64:
            raise ResultReuseError("RESULT_LINEAGE_CYCLE", "结果来源关系存在循环或超过安全追踪范围。")
        seen.add(current_id)
        resolved = registered_result_fact(registry, current_id)
        fact = resolved["fact"]
        if not rows and result_reuse_denial(fact):
            raise ResultReuseError("RESULT_REUSE_NOT_ACCEPTED", result_reuse_denial(fact))
        parent = result_lineage_fields(fact)
        source_meta = _mapping(fact.get("source_metadata"))
        source_sha = str(fact.get("source_sha256") or source_meta.get("sha256") or fact.get("source_sha_before") or "")
        source_path = str(fact.get("source_path") or fact.get("source") or source_meta.get("path") or "")
        rows.append({"task_id": resolved["source_task_id"], "result_id": current_id,
                     "feature_key": resolved["source_feature_key"],
                     "source_id": str(fact.get("source_id") or ""),
                     "source_sha256": source_sha, "output_sha256": resolved["registered_output_sha256"],
                     "file_name": Path(resolved["raw_path"]).name,
                     "source_file_name": Path(source_path).name,
                     **parent})
        current_id = parent.get("source_result_id", "")
    rows.reverse()
    for index, row in enumerate(rows):
        row["round"] = index + 1
        if index:
            prior = rows[index-1]
            if (row.get("source_task_id") != prior["task_id"]
                    or row.get("source_result_sha256") != prior["output_sha256"]
                    or row["source_sha256"] != prior["output_sha256"]):
                raise ResultReuseError("RESULT_LINEAGE_IDENTITY_MISMATCH", "相邻轮次的 Task、输入或输出摘要不一致。")
    first = rows[0]
    return {"result_id": result_id, "round_count": len(rows), "items": rows,
            "initial_source": {"task_id": first["task_id"], "source_id": first["source_id"],
                               "file_name": first["source_file_name"], "sha256": first["source_sha256"]}}
