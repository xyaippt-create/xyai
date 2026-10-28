"""Run the 15-image D-01 perception/decision matrix outside formal output paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageDraw, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.color_correction.core import process_single_image


SAMPLE_LABELS = {
    "01": "A2 正常商务人物",
    "02": "B0 受控错误偏黄",
    "03": "B1 受控错误偏蓝",
    "04": "B2 受控整体欠曝",
    "05": "C1 人物局部欠曝/逆光",
    "06": "C2 灰闷低对比",
    "07": "C3 冷暖混合光",
    "08": "C4 LED 蓝光污染人物",
    "09": "C5 高饱和红色包装",
    "10": "C6 高饱和蓝色包装",
    "11": "C7 黑色包装",
    "12": "C8 正常商务空间",
    "13": "C9 合理暖光",
    "14": "C10 高光临界",
    "15": "C11 正常暗调",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pixel_changed(source: Path, output: Path) -> bool:
    with Image.open(source) as source_image, Image.open(output) as output_image:
        source_rgb = np.asarray(ImageOps.exif_transpose(source_image).convert("RGB"))
        output_rgb = np.asarray(output_image.convert("RGB"))
    return not np.array_equal(source_rgb, output_rgb)


def _checks() -> dict[str, list[tuple[str, Callable[[dict[str, Any]], bool]]]]:
    return {
        "01": [
            ("allows ORIGINAL", lambda a: a["processing_decision"] == "ORIGINAL"),
            ("no global cast", lambda a: a["global_cast_direction"] == "none"),
            ("person protected", lambda a: a["person"]["present"]),
        ],
        "02": [
            ("global warm cast", lambda a: a["global_cast_direction"] == "warm"),
            ("high cast confidence", lambda a: a["global_cast_confidence"] >= 0.62),
            ("global correction allowed", lambda a: a["processing_decision"] == "NORMAL"),
        ],
        "03": [
            ("global cool cast", lambda a: a["global_cast_direction"] == "cool"),
            ("high cast confidence", lambda a: a["global_cast_confidence"] >= 0.62),
            ("global correction allowed", lambda a: a["processing_decision"] == "NORMAL"),
        ],
        "04": [
            ("global underexposure", lambda a: a["exposure"] == "global_under"),
            ("global treatment", lambda a: a["processing_decision"] == "NORMAL"),
        ],
        "05": [
            ("local subject underexposure", lambda a: a["exposure"] == "local_subject_under"),
            ("local treatment required", lambda a: a["processing_decision"] == "LOCAL_REQUIRED"),
            ("no global cast", lambda a: a["global_cast_direction"] == "none"),
        ],
        "06": [
            ("low contrast", lambda a: a["low_contrast"]),
            ("floating black", lambda a: a["floating_black"]),
            ("not global underexposure", lambda a: a["exposure"] == "normal"),
        ],
        "07": [
            ("mixed light", lambda a: a["mixed_light"] and a["lighting"] == "mixed"),
            ("no global cast", lambda a: a["global_cast_direction"] == "none"),
            ("low or original", lambda a: a["processing_decision"] in {"LOW", "ORIGINAL"}),
        ],
        "08": [
            ("screen color protected", lambda a: a["key_color"]["probable_product_or_screen_color"] == "screen"),
            ("local person contamination", lambda a: a["person"]["local_light_contamination"]),
            ("local treatment required", lambda a: a["processing_decision"] == "LOCAL_REQUIRED"),
            ("no global cast", lambda a: a["global_cast_direction"] == "none"),
        ],
        "09": [
            ("product color protected", lambda a: a["key_color"]["probable_product_or_screen_color"] == "product"),
            ("no global cast", lambda a: a["global_cast_direction"] == "none"),
            ("original", lambda a: a["processing_decision"] == "ORIGINAL"),
        ],
        "10": [
            ("product color protected", lambda a: a["key_color"]["probable_product_or_screen_color"] == "product"),
            ("no global cast", lambda a: a["global_cast_direction"] == "none"),
            ("original", lambda a: a["processing_decision"] == "ORIGINAL"),
        ],
        "11": [
            ("dark material protected", lambda a: a["dark_material_protection"]),
            ("not underexposure", lambda a: a["exposure"] == "normal"),
            ("original", lambda a: a["processing_decision"] == "ORIGINAL"),
        ],
        "12": [
            ("original", lambda a: a["processing_decision"] == "ORIGINAL"),
            ("no global cast", lambda a: a["global_cast_direction"] == "none"),
        ],
        "13": [
            ("legitimate warm", lambda a: a["scene_intent"] == "legitimate_warm"),
            ("no global cast", lambda a: a["global_cast_direction"] == "none"),
            ("original", lambda a: a["processing_decision"] == "ORIGINAL"),
        ],
        "14": [
            ("high highlight risk", lambda a: a["highlight_risk"] == "high"),
            ("not underexposure", lambda a: a["exposure"] == "normal"),
            ("limited treatment", lambda a: a["processing_decision"] == "LOW"),
        ],
        "15": [
            ("legitimate dark", lambda a: a["scene_intent"] == "legitimate_dark"),
            ("not underexposure", lambda a: a["exposure"] == "normal"),
            ("original", lambda a: a["processing_decision"] == "ORIGINAL"),
        ],
    }


def _contact_sheet(records: list[dict[str, Any]], path: Path) -> None:
    tile_width, tile_height = 560, 310
    sheet = Image.new("RGB", (tile_width * 3, tile_height * 5), "#d8d8d8")
    for index, record in enumerate(records):
        source_path = Path(record["source_path"])
        output_path = Path(record["output_path"])
        tile = Image.new("RGB", (tile_width, tile_height), "white")
        with Image.open(source_path) as image:
            before = ImageOps.contain(ImageOps.exif_transpose(image).convert("RGB"), (260, 245))
        with Image.open(output_path) as image:
            after = ImageOps.contain(image.convert("RGB"), (260, 245))
        tile.paste(before, ((270 - before.width) // 2, 44 + (245 - before.height) // 2))
        tile.paste(after, (280 + (270 - after.width) // 2, 44 + (245 - after.height) // 2))
        draw = ImageDraw.Draw(tile)
        draw.text((10, 8), f"{record['sample_id']} {record['label']}", fill="black")
        draw.text((10, 25), f"BEFORE | {record['decision']} | {record['cast']} | {record['exposure']} | AFTER", fill="#333333")
        draw.text((10, 292), f"matrix={record['matrix_status']} pixel_changed={record['pixel_changed']}", fill="#333333")
        sheet.paste(tile, ((index % 3) * tile_width, (index // 3) * tile_height))
    sheet.save(path, quality=92)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    input_root = args.inputs.resolve()
    output_root = args.output.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    result_root = output_root / "results"
    result_root.mkdir(exist_ok=True)

    discovered: dict[str, Path] = {}
    for path in input_root.glob("D01_*.*"):
        sample_id = path.stem.split("_")[1] if len(path.stem.split("_")) >= 2 else ""
        if sample_id in SAMPLE_LABELS:
            if sample_id in discovered:
                raise RuntimeError(f"duplicate sample: {sample_id}")
            discovered[sample_id] = path
    if set(discovered) != set(SAMPLE_LABELS):
        missing = sorted(set(SAMPLE_LABELS) - set(discovered))
        extra = sorted(set(discovered) - set(SAMPLE_LABELS))
        raise RuntimeError(f"D-01 samples must be exactly 15; missing={missing}, extra={extra}")

    source_before = {
        sample_id: {
            "sha256": _sha256(path),
            "size": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns,
        }
        for sample_id, path in discovered.items()
    }
    checks = _checks()
    records: list[dict[str, Any]] = []
    for sample_id in sorted(discovered):
        source = discovered[sample_id]
        target = result_root / source.name
        result = process_single_image(source, target).to_dict()
        analysis = result["analysis"]
        check_results = [
            {"name": name, "pass": bool(predicate(analysis))}
            for name, predicate in checks[sample_id]
        ]
        records.append(
            {
                "sample_id": sample_id,
                "label": SAMPLE_LABELS[sample_id],
                "source_path": str(source),
                "output_path": str(target),
                "source_sha256": source_before[sample_id]["sha256"],
                "output_sha256": result["output_sha256"],
                "pixel_changed": _pixel_changed(source, target),
                "decision": analysis["processing_decision"],
                "scope": analysis["processing_scope"],
                "output_policy": analysis["output_policy"],
                "cast": analysis["global_cast_direction"],
                "cast_confidence": analysis["global_cast_confidence"],
                "lighting": analysis["lighting"],
                "exposure": analysis["exposure"],
                "scene_intent": analysis["scene_intent"],
                "highlight_risk": analysis["highlight_risk"],
                "person": analysis["person"],
                "key_color": analysis["key_color"],
                "protection_needs": analysis["protection_needs"],
                "strategy": analysis["strategy_id"],
                "matrix_checks": check_results,
                "matrix_status": "PASS" if all(item["pass"] for item in check_results) else "FAIL",
                "result": result,
            }
        )

    source_after = {
        sample_id: {
            "sha256": _sha256(path),
            "size": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns,
        }
        for sample_id, path in discovered.items()
    }
    sources_unchanged = source_before == source_after
    matrix_pass = all(record["matrix_status"] == "PASS" for record in records)
    outputs_valid = all(Path(record["output_path"]).is_file() and Path(record["output_path"]).stat().st_size > 0 for record in records)
    summary = {
        "evaluation": "HDDE D-01 color perception and decision",
        "sample_run": f"{len(records)}/15",
        "matrix_status": "PASS" if matrix_pass else "FAIL",
        "outputs_valid": outputs_valid,
        "sources_unchanged": sources_unchanged,
        "input_root": str(input_root),
        "output_root": str(output_root),
        "formal_output_used": False,
        "records": records,
    }
    (output_root / "decision_records.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _contact_sheet(records, output_root / "before_after_contact_sheet.jpg")
    print(json.dumps({key: value for key, value in summary.items() if key != "records"}, ensure_ascii=False, indent=2))
    for record in records:
        print(
            f"{record['sample_id']} {record['matrix_status']} "
            f"decision={record['decision']} cast={record['cast']} "
            f"lighting={record['lighting']} exposure={record['exposure']}"
        )
    return 0 if matrix_pass and outputs_valid and sources_unchanged and len(records) == 15 else 1


if __name__ == "__main__":
    raise SystemExit(main())
