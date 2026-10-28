"""Output Center's batch view, joined only through persisted item identities.

Legacy membership is read from explicit batch.items records. Files, names and
timestamps never establish membership; unbound historical files stay singletons.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone


BATCH_SCHEMA = "HDDE_BATCH_RESULTS_V1"
TERMINAL = frozenset({"COMPLETED", "KEEP_ORIGINAL", "FAILED", "CANCELED"})


def mapping(value):
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return value if isinstance(value, Mapping) else {}


def value(record, key):
    for source in (record, mapping(record.get("task_result")), mapping(record.get("result"))):
        if source.get(key) not in (None, ""):
            return source[key]
    return ""


def batch_reference(record):
    """Retain a watermark batch independently of its clearable Task records."""
    batch_id = str(record.get("batch_id") or record.get("task_id") or "")
    items = record.get("items") or mapping(record.get("result")).get("items")
    if (record.get("feature_key") != "batch_watermark"
            or not batch_id.startswith("watermark_batch_") or not isinstance(items, list)):
        return None
    return {**record, "record_kind": "watermark_batch", "batch_id": batch_id,
            "batch_schema": BATCH_SCHEMA, "items": items}


def item_identity(batch_id, item_id, feature_type, source_id=""):
    return {"batch_id": batch_id, "batch_item_id": item_id,
            "feature_type": feature_type, "source_id": source_id or f"source_{item_id}"}


def batch_views(registry):
    """Return metadata only. The selected page validates actual output files."""
    batches = {}
    for record in list((registry or {}).values()):
        if not isinstance(record, Mapping):
            continue
        kind = record.get("record_kind")
        if kind == "compression_batch":
            batch_id = str(record.get("batch_id") or "")
            feature = "image_compression"
        else:
            reference = batch_reference(record)
            if reference is None:
                continue
            batch_id = reference["batch_id"]
            feature = "batch_watermark"
        raw_items = record.get("items") or mapping(record.get("result")).get("items")
        if not batch_id or not isinstance(raw_items, list) or not raw_items:
            continue
        # A retained batch is authoritative after its parent Task is cleared.
        if batch_id in batches and kind != "watermark_batch":
            continue
        item_ids = [str(i.get("batch_item_id") or i.get("id") or i.get("item_id") or "")
                    for i in raw_items if isinstance(i, Mapping)]
        if len(item_ids) != len(raw_items) or not all(item_ids) or len(set(item_ids)) != len(item_ids):
            continue
        items = []
        for raw, item_id in zip(raw_items, item_ids):
            source = mapping(raw.get("source"))
            task_id = str(raw.get("task_id") or (record.get("task_id") if feature == "batch_watermark" else "") or "")
            task = mapping((registry or {}).get(task_id))
            result_id = str(raw.get("result_id") or "")
            result = mapping((registry or {}).get(result_id)) or task
            status = str(raw.get("status") or "pending").upper().replace("CANCELLED", "CANCELED")
            status = "QUEUED" if status == "PENDING" else status
            # Publication and the batch snapshot are separate durable facts.
            # An exact completed Task / retained Result outranks a stale row.
            if feature == "image_compression":
                reserved_id = str(raw.get("reserved_result_id") or result_id)
                authoritative = mapping((registry or {}).get(reserved_id)) or task
                source_matches = bool(source.get("sha256")) and str(value(authoritative, "source_sha256")) == source["sha256"]
                task_matches = str(value(authoritative, "task_id")) == task_id
                if source_matches and task_matches and str(value(authoritative, "status")).lower() == "completed":
                    if str(value(authoritative, "result_id")) == reserved_id and reserved_id:
                        result, result_id, status = authoritative, reserved_id, "COMPLETED"
                    elif authoritative.get("winner_scheme_id") == "keep_original" and not value(authoritative, "result_id"):
                        result, result_id, status = authoritative, "", "KEEP_ORIGINAL"
            path = str(raw.get("output_path") or "")
            sha = str(raw.get("output_sha256") or "")
            if result_id and str(value(result, "result_id")) == result_id and str(value(result, "task_id")) == task_id:
                path = path or str(value(result, "output_path") or value(result, "result_file"))
                sha = sha or str(value(result, "output_sha256"))
            if status != "COMPLETED":
                result_id, path, sha = "", "", ""
            original = int(raw.get("original_bytes") or raw.get("source_size_bytes") or source.get("size_bytes") or 0)
            final = raw.get("final_bytes", raw.get("output_size_bytes"))
            if final is None and status == "COMPLETED":
                final = value(result, "output_size_bytes") or None
            items.append({
                **item_identity(batch_id, item_id, feature, str(raw.get("source_id") or source.get("source_id") or "")),
                "task_id": task_id, "result_id": result_id, "status": status,
                "output_path": path, "output_sha256": sha.lower(),
                "file_name": str(raw.get("name") or raw.get("file_name") or ""),
                "source_path": str(raw.get("source_path") or source.get("path") or ""),
                "source_sha256": str(raw.get("source_sha256") or raw.get("source_sha_before") or source.get("sha256") or ""),
                "original_bytes": original,
                "final_bytes": original if status == "KEEP_ORIGINAL" else int(final) if final is not None else None,
                "error": str(raw.get("error") or raw.get("failure_reason") or ""),
                "available": False,
            })
        counts = Counter(i["status"] for i in items)
        original = sum(i["original_bytes"] for i in items)
        final = sum(i["final_bytes"] if i["status"] in {"COMPLETED", "KEEP_ORIGINAL"}
                    and i["final_bytes"] is not None else i["original_bytes"] for i in items)
        created = record.get("created_at") or ""
        if isinstance(created, (int, float)):
            created = datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
        category = "compression" if feature == "image_compression" else feature
        label = "批量压缩" if feature == "image_compression" else "批量水印"
        batches[batch_id] = {
            "id": batch_id, "card_type": "batch", "batch_schema": BATCH_SCHEMA,
            "batch_id": batch_id, "feature_type": feature, "processing_type": category,
            "processing_label": label, "file_name": f"{label} · {len(items)} 张",
            "created_at": str(created), "items": items,
            "running": any(i["status"] not in TERMINAL for i in items),
            "summary": {"total": len(items), "completed": counts["COMPLETED"],
                        "keep_original": counts["KEEP_ORIGINAL"], "failed": counts["FAILED"],
                        "canceled": counts["CANCELED"], "pending": counts["QUEUED"],
                        "processing": counts["PROCESSING"], "original_bytes": original,
                        "final_bytes": final, "saved_bytes": original - final,
                        "saved_percent": (original - final) * 100 / original if original else None},
        }
    return list(batches.values())
