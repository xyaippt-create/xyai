"""Task-scoped A03-RL-P1 wall-clock accounting of the unmodified production engine.

No mock, replacement encoder, cached gate or altered search is used. Python/C
profile events and a few source-line ranges partition elapsed time exclusively.
ROI probe metrics stay in JPEG_ROI_PROBE; named quality metrics describe full
candidate/final-file gates. IO measures file API wait, not OS physical disk time;
memmap page faults remain charged to the metric operation that triggers them.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import inspect
import io
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageFile
from engine.image_compression import delivery_options as engine
from engine.image_compression import common, lossless_verifier
from engine.image_compression import jpg_full_resolution as full
from engine.image_compression import jpg_large_search as large
from engine.image_compression import jpg_quality_gate as gate
from engine.output import metadata_writer, publish_safety

PHASES = tuple(name + "_MS" for name in (
    "SOURCE_READ_DECODE", "SOURCE_PROFILE", "ALPHA_ANALYSIS", "ROI_EXTRACTION",
    "PNG_CANDIDATE_GENERATION", "PNG_VERIFICATION", "JPEG_ROI_PROBE",
    "JPEG_FULL_ENCODE", "JPEG_FULL_DECODE", "GLOBAL_QUALITY_GATE", "LOCAL_RISK_GATE",
    "EDGE_ANALYSIS", "HIGH_FREQUENCY_ANALYSIS", "GRADIENT_ANALYSIS", "COLOR_ANALYSIS",
    "ICC_METADATA", "SHA256", "TEMP_FILE_IO", "WINNER_SELECTION", "FORMAL_PUBLISH",
))
CODE_FILES = [ROOT / "engine/image_compression" / name for name in (
    "delivery_options.py", "jpg_quality_gate.py", "jpg_large_search.py",
    "jpg_full_resolution.py", "lossless_verifier.py", "common.py",
)] + [ROOT / "engine/output" / name for name in ("metadata_writer.py", "publish_safety.py")]


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def line_phases(function, default, ranges):
    lines, first = inspect.getsourcelines(function)
    result = {first + i: default for i in range(len(lines))}
    for start, stop, phase in ranges:
        begin = next(i for i, line in enumerate(lines) if line.strip().startswith(start))
        end = next((i for i in range(begin + 1, len(lines)) if lines[i].strip().startswith(stop)), len(lines))
        result.update({first + i: phase for i in range(begin, end)})
    return result


class StageProfile:
    def __init__(self, source):
        self.source_sha = sha(source)
        self.phases = Counter()
        self.functions = defaultdict(lambda: {"calls": 0, "inclusive_ms": 0.0, "exclusive_ms": 0.0})
        self.stack = []
        self.frames = {}
        self.image_ids = {}
        self.path_sha = {str(source): self.source_sha}
        self.open_inputs = {}
        self.decodes = defaultdict(lambda: {"count": 0, "milliseconds": 0.0, "callers": Counter()})
        self.payloads = []
        self.overhead = 0.0
        self.last = time.perf_counter()
        watched_names = {
            "generate_delivery_candidates", "_content_risk_profile", "_size_search_profile", "_real_transparency",
            "_png_variant_payloads", "_encode_png_variant", "_generate_verified_png_candidate", "_basic_png_verifier",
            "_encode_jpg_candidate", "_publish_winner", "_adaptive_jpg_candidates", "_large_jpg_candidates",
            "optimise_png_data", "_compress_scanlines", "read_image_info", "verify_lossless_png_files",
            "_protected_exif_facts", "plan_large_jpg_search", "select_native_rois", "native_source_hf_mean",
            "full_resolution_metrics", "evaluate_jpg_quality", "write_hdde_metadata_bytes", "read_hdde_metadata",
            "_decoded_signature", "_read_exif", "_read_effective_dpi", "_source_metadata_facts",
            "_write_png_metadata", "_write_jpeg_metadata", "publish_prepared_bytes_no_overwrite",
        }
        self.watched = {function.__code__ for module in (engine, common, lossless_verifier, full, large, gate, metadata_writer, publish_safety)
                        for name, function in vars(module).items() if name in watched_names and inspect.isfunction(function)}
        self.watched.update((Image.open.__code__, ImageFile.ImageFile.load.__code__))
        self.maps = {
            full.full_resolution_metrics.__code__: line_phases(full.full_resolution_metrics, "GLOBAL_QUALITY_GATE", [
                ("for y in range", "for y in range", "EDGE_ANALYSIS"),
                ("source_luma =", "horizontal =", "EDGE_ANALYSIS"),
                ("source_hf_sum +=", "horizontal =", "HIGH_FREQUENCY_ANALYSIS"),
                ("horizontal =", "source_lab =", "LOCAL_RISK_GATE"),
                ("source_lab =", "finally:", "COLOR_ANALYSIS"),
                ("smooth_hist +=", "source_edge_sum +=", "GRADIENT_ANALYSIS"),
            ]),
            large.plan_large_jpg_search.__code__: line_phases(large.plan_large_jpg_search, "JPEG_ROI_PROBE", [
                ("started =", "trials:", "ROI_EXTRACTION"),
            ]),
            engine.generate_delivery_candidates.__code__: line_phases(engine.generate_delivery_candidates, "WINNER_SELECTION", [
                ("source_file =", "width, height =", "SOURCE_READ_DECODE"),
            ]),
        }

    def account(self, now):
        elapsed = now - self.last
        phase = self.stack[-1]["phase"] if self.stack else "OTHER"
        self.phases[phase + "_MS"] += elapsed * 1000
        if self.stack:
            self.functions[self.stack[-1]["key"]]["exclusive_ms"] += elapsed * 1000

    def finish_hook(self, began):
        end = time.perf_counter()
        self.overhead += end - began
        self.last = end

    def trace(self, frame, event, arg):
        if frame.f_code not in self.maps:
            return None
        began = time.perf_counter()
        self.account(began)
        if event == "line" and id(frame) in self.frames:
            self.frames[id(frame)]["phase"] = self.maps[frame.f_code][frame.f_lineno]
        self.finish_hook(began)
        return self.trace if frame.f_code in self.maps else None

    def phase_for(self, frame, event, arg):
        name = frame.f_code.co_name
        file = Path(frame.f_code.co_filename).name
        current = self.stack[-1]["phase"] if self.stack else "OTHER"
        in_roi = any(node["name"] == "plan_large_jpg_search" for node in self.stack)
        if event == "c_call":
            c_name = getattr(arg, "__name__", "")
            owner = getattr(arg, "__self__", None)
            module = str(getattr(arg, "__module__", ""))
            if "sha256" in c_name or (c_name in {"update", "hexdigest", "digest"} and "HASH" in type(owner).__name__):
                return "SHA256", c_name
            if isinstance(owner, (io.BufferedIOBase, io.FileIO)) and not isinstance(owner, io.BytesIO):
                if c_name in {"read", "readinto", "write", "seek", "flush", "close"}:
                    return ("SOURCE_READ_DECODE" if current == "SOURCE_READ_DECODE" else "TEMP_FILE_IO"), c_name
            if module in {"nt", "posix"} and c_name in {"fsync", "open", "unlink", "rename", "mkdir"}:
                return "TEMP_FILE_IO", c_name
            return None, ""
        if file == "ImageFile.py" and name == "load" and getattr(frame.f_locals.get("self"), "tile", None):
            opened = frame.f_locals["self"]
            if in_roi:
                return None, ""
            identity = self.image_ids.get(id(opened), "UNIDENTIFIED")
            frame_key = "decode:" + identity
            parent = frame.f_back.f_code.co_name
            self.decodes[identity]["count"] += 1
            self.decodes[identity]["callers"][parent] += 1
            if identity == self.source_sha:
                return "SOURCE_READ_DECODE", frame_key
            if opened.format == "JPEG":
                return "JPEG_FULL_DECODE", frame_key
            return current, frame_key
        if file == "delivery_options.py":
            phases = {
                "generate_delivery_candidates": "WINNER_SELECTION", "_content_risk_profile": "SOURCE_PROFILE",
                "_size_search_profile": "SOURCE_PROFILE", "_real_transparency": "ALPHA_ANALYSIS",
                "_png_variant_payloads": "PNG_CANDIDATE_GENERATION", "_encode_png_variant": "PNG_CANDIDATE_GENERATION",
                "_generate_verified_png_candidate": "PNG_VERIFICATION", "_basic_png_verifier": "PNG_VERIFICATION",
                "_encode_jpg_candidate": "JPEG_FULL_ENCODE", "_publish_winner": "FORMAL_PUBLISH",
                "_adaptive_jpg_candidates": "JPEG_ROI_PROBE", "_large_jpg_candidates": "JPEG_ROI_PROBE",
            }
            return phases.get(name), name
        if file == "common.py" and name in {"optimise_png_data", "_compress_scanlines"}:
            return "PNG_CANDIDATE_GENERATION", name
        if file == "common.py" and name == "read_image_info":
            return "ICC_METADATA", name
        if file == "lossless_verifier.py":
            if name == "verify_lossless_png_files":
                return "PNG_VERIFICATION", name
            if name == "_protected_exif_facts":
                return "ICC_METADATA", name
        if file == "jpg_large_search.py":
            return {"plan_large_jpg_search": "JPEG_ROI_PROBE", "select_native_rois": "ROI_EXTRACTION",
                    "native_source_hf_mean": "SOURCE_PROFILE"}.get(name), name
        if file == "jpg_full_resolution.py" and name == "full_resolution_metrics":
            return "GLOBAL_QUALITY_GATE", name
        if file == "jpg_quality_gate.py" and name == "evaluate_jpg_quality":
            return "GLOBAL_QUALITY_GATE", name
        if file == "metadata_writer.py" and name in {
            "write_hdde_metadata_bytes", "read_hdde_metadata", "_decoded_signature", "_read_exif",
            "_read_effective_dpi", "_source_metadata_facts", "_write_png_metadata", "_write_jpeg_metadata",
        }:
            return "ICC_METADATA", name
        if file == "publish_safety.py" and name == "publish_prepared_bytes_no_overwrite":
            return ("FORMAL_PUBLISH" if any(n["name"] == "_publish_winner" for n in self.stack) else "TEMP_FILE_IO"), name
        return None, ""

    def profile(self, frame, event, arg):
        token = (id(frame), "c") if event.startswith("c_") else id(frame)
        # Ignore unrelated calls before any expensive accounting/introspection.
        # Residual dispatch cost remains in wall-clock stages; a plain run is
        # recorded separately so observer effects cannot masquerade as speedup.
        if event == "call" and frame.f_code not in self.watched:
            return
        if event in {"return", "c_return", "c_exception"} and token not in self.frames and token not in self.open_inputs:
            return
        if event == "c_call" and getattr(arg, "__name__", "") not in {
            "openssl_sha256", "sha256", "update", "hexdigest", "digest", "read", "readinto", "write",
            "seek", "flush", "close", "fsync", "open", "unlink", "rename", "mkdir",
        }:
            return
        began = time.perf_counter()
        self.account(began)
        # Count real decoding by content identity; auxiliary fingerprint time is
        # profiler overhead, never reported as production SHA/IO work.
        is_image_open = Path(frame.f_code.co_filename).name == "Image.py" and frame.f_code.co_name == "open"
        in_roi = any(node["name"] == "plan_large_jpg_search" for node in self.stack)
        if is_image_open and not in_roi:
            if event == "call":
                fp = frame.f_locals.get("fp")
                if isinstance(fp, io.BytesIO):
                    self.open_inputs[id(frame)] = hashlib.sha256(fp.getbuffer()).hexdigest()
                elif isinstance(fp, (str, Path)):
                    key = str(fp)
                    if key not in self.path_sha:
                        self.path_sha[key] = sha(fp)
                    self.open_inputs[id(frame)] = self.path_sha[key]
            elif event == "return" and arg is not None:
                self.image_ids[id(arg)] = self.open_inputs.pop(id(frame), "UNIDENTIFIED")
        if event in {"call", "c_call"}:
            phase, key = self.phase_for(frame, event, arg)
            if phase:
                name = frame.f_code.co_name
                if name == "_encode_png_variant":
                    key += ":" + str((frame.f_locals["optimize"], frame.f_locals["compress_level"], frame.f_locals["remove_opaque_alpha"]))
                if name == "_compress_scanlines":
                    key += ":strategy=" + str(frame.f_locals["strategy"])
                node = {"phase": phase, "key": key, "name": name, "start": began, "overhead": self.overhead, "token": token}
                self.stack.append(node)
                self.frames[token] = node
        elif event in {"return", "c_return", "c_exception"} and token in self.frames:
            node = self.frames.pop(token)
            assert self.stack[-1] is node, "profiling stack must be balanced"
            self.stack.pop()
            duration = (began - node["start"] - (self.overhead - node["overhead"])) * 1000
            stats = self.functions[node["key"]]
            stats["calls"] += 1
            stats["inclusive_ms"] += duration
            if node["key"].startswith("decode:"):
                self.decodes[node["key"][7:]]["milliseconds"] += duration
            if event == "return" and isinstance(arg, bytes) and node["name"] in {"_encode_png_variant", "_compress_scanlines"}:
                self.payloads.append({"operation": node["key"], "time_ms": duration, "bytes": len(arg), "sha256": hashlib.sha256(arg).hexdigest()})
        self.finish_hook(began)

    def run(self, source, output):
        started = self.last = time.perf_counter()
        sys.settrace(self.trace)
        sys.setprofile(self.profile)
        try:
            result = engine.generate_delivery_candidates(source, output, source_filename=source.name, moment=datetime(2026, 9, 5, 18, 0))
        finally:
            sys.setprofile(None)
            sys.settrace(None)
        ended = time.perf_counter()
        self.account(ended)
        assert not self.stack
        times = {key: round(self.phases[key], 3) for key in (*PHASES, "OTHER_MS")}
        times["PROFILER_OVERHEAD_MS"] = round(self.overhead * 1000, 3)
        times["TOTAL_MS"] = round((ended - started) * 1000, 3)
        times["ACCOUNTING_ERROR_MS"] = round(times["TOTAL_MS"] - sum(v for k, v in times.items() if k != "TOTAL_MS"), 6)
        return result, times


def run(manifest, target, ids):
    target.resolve().relative_to(ROOT / "output")
    target.mkdir(parents=True, exist_ok=False)
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in CODE_FILES}
    for path in CODE_FILES:
        (target / (path.name + ".source.txt")).write_bytes(path.read_bytes())
    rows = []
    samples = [s for s in json.loads(manifest.read_text(encoding="utf-8")) if not ids or s["id"] in ids]
    if ids:
        assert {s["id"] for s in samples} == set(ids)
    for sample in samples:
        assert hashes == {str(p.relative_to(ROOT)): sha(p) for p in CODE_FILES}, "production code drifted"
        source = Path(sample["path"]).resolve()
        profiler = StageProfile(source)
        print(json.dumps({"started": sample["id"], "source_sha": profiler.source_sha}), flush=True)
        result, times = profiler.run(source, target / sample["id"])
        winner = result["winner"]
        png = next(c for c in result["candidates"] if c["format"] == "PNG")
        assert sha(source) == profiler.source_sha == result["source_identity"]["sha256"]
        assert winner["quality_gate"]["status"] == "PASS"
        outputs = [p for p in (target / sample["id"]).iterdir() if p.is_file()]
        assert len(outputs) == result["public_output_count"] <= 1
        if outputs:
            assert sha(outputs[0]) == winner["output_sha256"]
            with Image.open(outputs[0]) as verified:
                verified.load()
                assert verified.size == (winner["width"], winner["height"])
        assert png["lossless_verified"] and png["pixel_diff_count"] == png["max_channel_diff"] == 0
        assert hashes == {str(p.relative_to(ROOT)): sha(p) for p in CODE_FILES}, "production code drifted"
        row = {**sample, "source_sha256": profiler.source_sha, "source_bytes": source.stat().st_size,
               "stages": times, "functions": dict(profiler.functions), "decode_artifacts": dict(profiler.decodes),
               "png_encoding_operations": profiler.payloads, "png_variants": png["metadata_details"]["lossless_optimization"],
               "lossless_verification": png["metadata_details"]["lossless_verification"],
               "winner_bytes": winner["file_size"], "winner_sha256": winner["output_sha256"],
               "winner_path": winner["output_path"], "winner_scheme_id": result["winner_scheme_id"],
               "saved_percent": winner["saved_percent"], "quality_gate": winner["quality_gate"],
               "public_output_count": len(outputs), "jpg_search": result["jpg_search"]}
        rows.append(row)
        (target / "profile.json").write_text(json.dumps({"code_hashes": hashes, "profiler_sha256": sha(__file__),
            "rows": rows, "complete": len(rows) == len(samples)}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"finished": sample["id"], "stages": times, "bytes": winner["file_size"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--ids", nargs="*")
    args = parser.parse_args()
    run(args.manifest, args.target.resolve(), args.ids)
