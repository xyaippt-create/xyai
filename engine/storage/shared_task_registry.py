"""Persistent implementation of HDDE's existing shared task registry boundary."""

from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Iterator, Mapping, MutableMapping
from pathlib import Path
from typing import Any, Callable

from engine.storage.batch_results import batch_reference
from engine.storage.result_reuse import result_lineage_fields


REGISTRY_SCHEMA = "HDDE_SHARED_TASK_REGISTRY_V1"
REGISTRY_RELATIVE_PATH = Path("诊断") / "任务记录" / "共享任务事实.json"


class SharedTaskRegistryError(RuntimeError):
    """The shared registry could not be safely loaded or committed."""


def _json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "to_dict"):
        return _json_ready(value.to_dict())
    raise TypeError(f"UNSUPPORTED_SHARED_TASK_FACT_VALUE:{type(value).__name__}")


class SharedTaskRegistry(MutableMapping[str, dict[str, Any]]):
    """One mapping authority shared by existing Task, Result and Delivery code."""

    def __init__(self, formal_root: Path):
        self._root = Path(formal_root).resolve()
        self._path = (self._root / REGISTRY_RELATIVE_PATH).resolve()
        if self._root not in self._path.parents:
            raise SharedTaskRegistryError("SHARED_TASK_REGISTRY_PATH_INVALID")
        self._lock = threading.RLock()
        self._records = self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.is_file():
            return {}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SharedTaskRegistryError("SHARED_TASK_REGISTRY_INVALID") from exc
        if not isinstance(payload, Mapping) or payload.get("schema") != REGISTRY_SCHEMA:
            raise SharedTaskRegistryError("SHARED_TASK_REGISTRY_INVALID")
        records = payload.get("records")
        if not isinstance(records, Mapping):
            raise SharedTaskRegistryError("SHARED_TASK_REGISTRY_INVALID")
        return {
            str(record_id): dict(record)
            for record_id, record in records.items()
            if str(record_id).strip() and isinstance(record, Mapping)
        }

    def _commit(self, records: Mapping[str, Mapping[str, Any]]) -> None:
        try:
            payload = {"schema": REGISTRY_SCHEMA, "records": _json_ready(records)}
            encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise SharedTaskRegistryError("SHARED_TASK_REGISTRY_RECORD_INVALID") from exc
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        except Exception as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise SharedTaskRegistryError("SHARED_TASK_REGISTRY_WRITE_FAILED") from exc

    def __getitem__(self, key: str) -> dict[str, Any]:
        return self._records[str(key)]

    def __setitem__(self, key: str, value: dict[str, Any]) -> None:
        normalized_key = str(key or "").strip()
        if not normalized_key or not isinstance(value, Mapping):
            raise SharedTaskRegistryError("SHARED_TASK_REGISTRY_RECORD_INVALID")
        with self._lock:
            updated = dict(self._records)
            updated[normalized_key] = dict(value)
            self._commit(updated)
            self._records[normalized_key] = value

    def persist_facts(
        self,
        records: Mapping[str, Mapping[str, Any]],
        *,
        require_identical_existing: bool = False,
    ) -> dict[str, list[str]]:
        """Atomically persist related formal facts, with optional idempotency guard."""

        normalized: dict[str, dict[str, Any]] = {}
        for key, value in records.items():
            normalized_key = str(key or "").strip()
            if not normalized_key or not isinstance(value, Mapping):
                raise SharedTaskRegistryError("SHARED_TASK_REGISTRY_RECORD_INVALID")
            normalized[normalized_key] = dict(_json_ready(value))
        if not normalized:
            return {"created": [], "unchanged": [], "updated": []}

        with self._lock:
            created: list[str] = []
            unchanged: list[str] = []
            updated_keys: list[str] = []
            next_records = dict(self._records)
            for key, value in normalized.items():
                existing = next_records.get(key)
                if isinstance(existing, Mapping) and _json_ready(existing) == value:
                    unchanged.append(key)
                    continue
                if existing is not None and require_identical_existing:
                    raise SharedTaskRegistryError("SHARED_TASK_REGISTRY_FACT_CONFLICT")
                if existing is None:
                    created.append(key)
                else:
                    updated_keys.append(key)
                next_records[key] = value
            if created or updated_keys:
                self._commit(next_records)
                self._records = next_records
            return {"created": created, "unchanged": unchanged, "updated": updated_keys}

    def __delitem__(self, key: str) -> None:
        normalized_key = str(key)
        with self._lock:
            updated = dict(self._records)
            del updated[normalized_key]
            self._commit(updated)
            del self._records[normalized_key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._records)

    def __len__(self) -> int:
        return len(self._records)

    @staticmethod
    def _task_status(record: Mapping[str, Any]) -> str:
        return str(record.get("task_status") or record.get("status") or "").strip().lower()

    @staticmethod
    def _is_task_fact(record: Mapping[str, Any]) -> bool:
        return str(record.get("record_kind") or "task").strip().lower() == "task"

    @staticmethod
    def _result_reference(record: Mapping[str, Any]) -> dict[str, Any] | None:
        task_result = record.get("task_result")
        if not isinstance(task_result, Mapping):
            task_result = {}
        result = record.get("result")
        if hasattr(result, "to_dict"):
            result = result.to_dict()
        if not isinstance(result, Mapping):
            result = {}
        result_id = str(record.get("result_id") or task_result.get("result_id") or result.get("result_id") or "").strip()
        result_file = str(
            record.get("result_file")
            or record.get("output_path")
            or task_result.get("result_file")
            or task_result.get("output_path")
            or result.get("result_file")
            or result.get("output_path")
            or result.get("final_output_path")
            or ""
        ).strip()
        if not result_id:
            return None
        task_id = str(record.get("task_id") or task_result.get("task_id") or result.get("task_id") or "").strip()
        feature_key = str(record.get("feature_key") or task_result.get("feature_key") or result.get("feature_key") or "").strip()
        source_path = str(
            record.get("source_path")
            or record.get("source")
            or record.get("input_path")
            or task_result.get("source_path")
            or task_result.get("source")
            or result.get("source_path")
            or result.get("source")
            or ""
        ).strip()
        reference = {
            "record_kind": "result",
            "result_id": result_id,
            "task_id": task_id,
            "source_task_id": task_id,
            "feature_key": feature_key,
            "module_id": str(record.get("module_id") or task_result.get("module_id") or result.get("module_id") or ""),
            "operation_id": str(record.get("operation_id") or task_result.get("operation_id") or result.get("operation_id") or ""),
            "trace_id": str(record.get("trace_id") or task_result.get("trace_id") or result.get("trace_id") or ""),
            "task_family": str(record.get("task_family") or ""),
            "status": str(record.get("status") or result.get("status") or "completed"),
            "source": source_path,
            "source_path": source_path,
            "result_file": result_file,
            "output_path": result_file,
            "delivery_id": str(record.get("delivery_id") or task_result.get("delivery_id") or ""),
            "deliveries": _json_ready(record.get("deliveries") or []),
            "task_result": _json_ready(dict(task_result)) if task_result else {},
            "result": _json_ready(dict(result)) if result else {},
            "created_at": str(record.get("created_at") or ""),
            "completed_at": str(record.get("completed_at") or ""),
            "task_context": _json_ready(record.get("task_context") or {}),
        }
        for field in ("batch_id", "batch_item_id", "feature_type", "source_id", "output_sha256", "review_status", "result_review_status"):
            if record.get(field) not in (None, ""):
                reference[field] = _json_ready(record[field])
        reference.update(result_lineage_fields(record) or result_lineage_fields(task_result) or result_lineage_fields(result))
        return reference

    def claim_task_execution(self, task_id: str) -> bool:
        """Atomically mark a queued task as started before any worker can execute it."""

        normalized_id = str(task_id or "").strip()
        if not normalized_id:
            return False
        with self._lock:
            record = self._records.get(normalized_id)
            if not isinstance(record, Mapping) or not self._is_task_fact(record):
                return False
            status = self._task_status(record)
            if status not in {"pending", "queued"} or bool(record.get("execution_started")):
                return False
            task_identifier = str(record.get("task_id") or normalized_id)
            updated = dict(self._records)
            matched_keys: list[str] = []
            for key, candidate in self._records.items():
                if not isinstance(candidate, Mapping) or not self._is_task_fact(candidate):
                    continue
                if str(candidate.get("task_id") or key) != task_identifier:
                    continue
                next_record = dict(candidate)
                next_record["execution_started"] = True
                next_record["execution_state"] = "scheduled"
                updated[key] = next_record
                matched_keys.append(key)
            self._commit(updated)
            for key in matched_keys:
                live_record = self._records.get(key)
                if isinstance(live_record, dict):
                    live_record["execution_started"] = True
                    live_record["execution_state"] = "scheduled"
            return True

    def delete_task_fact(self, task_id: str) -> dict[str, Any]:
        """Delete one safe Task fact while retaining any formal Result fact."""

        normalized_id = str(task_id or "").strip()
        if not normalized_id:
            return {"task_id": "", "deleted": False, "reason": "task_id_invalid", "status": ""}
        with self._lock:
            record = self._records.get(normalized_id)
            if not isinstance(record, Mapping) or not self._is_task_fact(record):
                return {"task_id": normalized_id, "deleted": False, "reason": "task_not_found", "status": ""}
            task_identifier = str(record.get("task_id") or normalized_id).strip()
            status = self._task_status(record)
            if status in {"processing", "running"}:
                return {"task_id": task_identifier, "deleted": False, "reason": "task_running", "status": status}
            if status in {"pending", "queued"} and bool(record.get("execution_started")):
                return {"task_id": task_identifier, "deleted": False, "reason": "task_already_started", "status": status}
            if status not in {"pending", "queued", "completed", "failed", "cancelled"}:
                return {"task_id": task_identifier, "deleted": False, "reason": "task_status_protected", "status": status}

            updated = dict(self._records)
            removed_keys = [
                key
                for key, candidate in self._records.items()
                if isinstance(candidate, Mapping)
                and self._is_task_fact(candidate)
                and str(candidate.get("task_id") or key).strip() == task_identifier
            ]
            for key in removed_keys:
                updated.pop(key, None)
            result_reference = self._result_reference(record)
            if result_reference is not None:
                result_id = str(result_reference["result_id"])
                existing = updated.get(result_id)
                if isinstance(existing, Mapping) and str(existing.get("result_id") or "") != result_id:
                    raise SharedTaskRegistryError("SHARED_TASK_RESULT_REFERENCE_CONFLICT")
                updated[result_id] = result_reference
            # Legacy watermark Results lived only inside the parent Task. Retain
            # their explicit membership and individual Result facts atomically.
            batch = batch_reference(record)
            retained = {}
            if batch is not None:
                retained[f"output_batch:{batch['batch_id']}"] = _json_ready(batch)
                for item in batch["items"]:
                    if item.get("status") != "completed" or not item.get("result_id"):
                        continue
                    child = {**record, **item, "task_result": item, "result": item}
                    reference = self._result_reference(child)
                    if reference is not None:
                        retained[str(reference["result_id"])] = reference
                updated.update(retained)
            self._commit(updated)
            for key in removed_keys:
                self._records.pop(key, None)
            if result_reference is not None:
                self._records[str(result_reference["result_id"])] = result_reference
            self._records.update(retained)
            return {
                "task_id": task_identifier,
                "deleted": True,
                "reason": "deleted",
                "status": status,
                "result_id": str((result_reference or {}).get("result_id") or ""),
                "delivery_id": str((result_reference or {}).get("delivery_id") or ""),
                "result_preserved": result_reference is not None or bool(retained),
            }

    def result_reference_for_task(self, task_id: str) -> dict[str, Any] | None:
        normalized_id = str(task_id or "").strip()
        with self._lock:
            for record in self._records.values():
                if not isinstance(record, Mapping) or str(record.get("record_kind") or "") != "result":
                    continue
                if str(record.get("source_task_id") or record.get("task_id") or "") == normalized_id:
                    return dict(record)
        return None

    def reconcile_file_availability(self, path_resolver: Callable[[str], Path]) -> dict[str, list[str]]:
        """Persist live file truth for retained Result and Delivery facts."""

        updated_records: dict[str, dict[str, Any]] = {}
        unavailable_result_ids: list[str] = []
        unavailable_delivery_ids: list[str] = []

        def file_available(raw_path: Any) -> bool:
            value = str(raw_path or "").strip()
            if not value:
                return False
            try:
                return Path(path_resolver(value)).is_file()
            except (OSError, RuntimeError, ValueError):
                return False

        with self._lock:
            for record_id, record in self._records.items():
                if not isinstance(record, Mapping) or str(record.get("record_kind") or "") != "result":
                    continue
                result_file = str(record.get("result_file") or record.get("output_path") or "").strip()
                if not result_file:
                    continue

                next_record = dict(record)
                result_available = file_available(result_file)
                result_file_status = "AVAILABLE" if result_available else "FILE_UNAVAILABLE"
                next_record.update(
                    {
                        "result_available": result_available,
                        "result_file_status": result_file_status,
                        "availability_reason": "" if result_available else "FILE_UNAVAILABLE",
                        "final_output_exists": result_available,
                    }
                )

                for nested_key in ("task_result", "result"):
                    nested = next_record.get(nested_key)
                    if not isinstance(nested, Mapping) or not nested:
                        continue
                    next_nested = dict(nested)
                    next_nested.update(
                        {
                            "result_available": result_available,
                            "result_file_status": result_file_status,
                            "final_output_exists": result_available,
                        }
                    )
                    if "output_path_exists" in next_nested:
                        next_nested["output_path_exists"] = result_available
                    next_record[nested_key] = next_nested

                deliveries = next_record.get("deliveries")
                next_deliveries: list[Any] = []
                delivery_availability: list[bool] = []
                if isinstance(deliveries, list):
                    for delivery in deliveries:
                        if not isinstance(delivery, Mapping):
                            next_deliveries.append(delivery)
                            continue
                        next_delivery = dict(delivery)
                        delivery_path = str(delivery.get("delivery_file") or delivery.get("delivery_path") or "").strip()
                        if delivery_path:
                            available = file_available(delivery_path)
                            delivery_availability.append(available)
                            next_delivery.update(
                                {
                                    "file_available": available,
                                    "file_status": "AVAILABLE" if available else "FILE_UNAVAILABLE",
                                    "availability_reason": "" if available else "FILE_UNAVAILABLE",
                                }
                            )
                            if not available:
                                delivery_id = str(delivery.get("delivery_id") or "").strip()
                                if delivery_id:
                                    unavailable_delivery_ids.append(delivery_id)
                        next_deliveries.append(next_delivery)
                    next_record["deliveries"] = next_deliveries

                if delivery_availability:
                    delivery_available = any(delivery_availability)
                    next_record["delivery_available"] = delivery_available
                    next_record["delivery_file_status"] = "AVAILABLE" if delivery_available else "FILE_UNAVAILABLE"
                if not result_available:
                    unavailable_result_ids.append(str(record.get("result_id") or record_id))
                if _json_ready(next_record) != _json_ready(record):
                    updated_records[record_id] = next_record

            outcome = self.persist_facts(updated_records) if updated_records else {"created": [], "unchanged": [], "updated": []}
        return {
            "updated": list(outcome.get("updated") or []),
            "unavailable_result_ids": sorted(set(unavailable_result_ids)),
            "unavailable_delivery_ids": sorted(set(unavailable_delivery_ids)),
        }
