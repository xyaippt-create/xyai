"""A03-RL real-file before/after benchmark. Never writes to a Source directory."""
from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
import pstats
import sys
import time
import types
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inventory(target):
    from PIL import Image, ImageDraw

    source_root = Path("D:/影界文件/输出/4K画质增强")
    paths = sorted(source_root.glob("*.png"))
    rows = []
    sheet = Image.new("RGB", (1200, ((len(paths) + 5) // 6) * 170), "white")
    draw = ImageDraw.Draw(sheet)
    for index, path in enumerate(paths):
        with Image.open(path) as opened:
            size = opened.size
            preview = opened.convert("RGB")
            preview.thumbnail((192, 140))
        x, y = (index % 6) * 200, (index // 6) * 170
        sheet.paste(preview, (x, y))
        draw.text((x, y + 143), f"{index:02d}  {size[0]}x{size[1]}", fill="black")
        rows.append({"id": f"L{index:02d}", "path": str(path), "dimensions": size})
    target.mkdir(parents=True, exist_ok=True)
    sheet.save(target / "inventory.jpg")
    (target / "inventory.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(target / "inventory.jpg"), flush=True)


def run(manifest, target, limit, baseline_from=None):
    from engine.image_compression import delivery_options as engine
    from PIL import Image

    target.mkdir(parents=True, exist_ok=False)
    code_files = [ROOT / "engine/image_compression" / name for name in (
        "delivery_options.py", "jpg_quality_gate.py", "jpg_large_search.py", "jpg_full_resolution.py",
        "lossless_verifier.py", "common.py",
    )]
    hashes = {str(path.relative_to(ROOT)): sha(path) for path in code_files if path.exists()}
    if baseline_from:
        archived = []
        for name in ("jpg_quality_gate", "delivery_options"):
            path = baseline_from / (name + ".py.source.txt")
            module = types.ModuleType("engine.image_compression._baseline_" + name)
            module.__package__ = "engine.image_compression"
            exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
            archived.append(module)
        engine = archived[1]
        engine.evaluate_jpg_quality = archived[0].evaluate_jpg_quality
        hashes = json.loads((baseline_from / "benchmark.json").read_text(encoding="utf-8"))["code_hashes"]
    # Preserve exact executed baseline source, not a git revision in this dirty tree.
    for path in code_files:
        if path.exists() and not baseline_from:
            (target / (path.name + ".source.txt")).write_bytes(path.read_bytes())
    samples = json.loads(Path(manifest).read_text(encoding="utf-8"))
    if limit:
        samples = samples[:limit]
    rows = []
    for sample in samples:
        source = Path(sample["path"]).resolve()
        source_sha = sha(source)
        output = target / sample["id"]
        profiler = cProfile.Profile()
        started = time.perf_counter()
        profiler.enable()
        result = engine.generate_delivery_candidates(
            source, output, source_filename=source.name, moment=datetime(2026, 9, 5, 18, 0),
        )
        profiler.disable()
        elapsed = time.perf_counter() - started
        stats = pstats.Stats(profiler)
        profile = {}
        for (_filename, _line, function), (primitive, calls, self_time, total, _callers) in stats.stats.items():
            if function in {
                "_encode_jpg_candidate", "_evaluate_jpg_trial", "evaluate_jpg_quality",
                "_generate_verified_png_candidate", "_png_variant_payloads", "verify_lossless_png_files",
                "publish_image_bytes_with_metadata", "_publish_winner", "read_bytes", "write_bytes",
                "plan_large_jpg_search", "full_resolution_metrics",
            }:
                item = profile.setdefault(function, {"calls": 0, "self_seconds": 0.0, "cumulative_seconds": 0.0})
                item["calls"] += calls
                item["self_seconds"] += self_time
                item["cumulative_seconds"] += total
        winner = result["winner"]
        png = next(candidate for candidate in result["candidates"] if candidate["scheme_id"] == "png_lossless")
        formal = [path for path in output.iterdir() if path.is_file()]
        if formal:
            with Image.open(formal[0]) as image:
                image.load()
                assert image.size == (winner["width"], winner["height"])
            assert sha(formal[0]) == winner["output_sha256"]
        assert len(formal) == result["public_output_count"] <= 1
        assert sha(source) == source_sha
        assert png["lossless_verified"] and png["pixel_diff_count"] == png["max_channel_diff"] == 0
        assert winner["quality_gate"]["status"] == "PASS"
        row = {
            **sample, "source_sha256": source_sha, "source_bytes": source.stat().st_size,
            "source_pixels": winner["width"] * winner["height"],
            "size_profile": result["size_search_profile"]["profile_id"],
            "lossless_bytes": png["file_size"], "lossless_gain": png["saved_percent"],
            "lossless_verification": png["metadata_details"]["lossless_verification"],
            "winner_scheme_id": result["winner_scheme_id"], "winner_bytes": winner["file_size"],
            "winner_sha256": winner["output_sha256"], "winner_path": winner["output_path"],
            "saved_percent": winner["saved_percent"], "quality_gate": winner["quality_gate"],
            "public_output_count": result["public_output_count"], "elapsed_seconds": elapsed,
            "jpg_search": result["jpg_search"], "profile": profile,
            "jpg_trials": [{key: candidate.get(key) for key in (
                "scheme_id", "file_size", "quality_gate", "search_details", "direct_source_lineage",
            )} for candidate in result["candidates"] if candidate["format"] == "JPG"],
        }
        rows.append(row)
        (target / "benchmark.json").write_text(json.dumps({
            "code_hashes": hashes, "rows": rows, "complete": len(rows) == len(samples),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"id": sample["id"], "bytes": row["winner_bytes"],
                          "saved": row["saved_percent"], "seconds": round(elapsed, 3),
                          "encodes": result["jpg_search"]["encode_count"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--baseline-from", type=Path)
    args = parser.parse_args()
    target = args.target.resolve()
    target.relative_to(ROOT / "output")
    if args.inventory:
        inventory(target)
    else:
        run(args.manifest, target, args.limit, args.baseline_from)
