"""S65-REFCOLOR-POC: reference-driven level pick, isolated from the formal chain.

The reference contributes only its per-lightness neutral cast ("what white should look
like") and, on route R2, its tone percentiles. Reuses the frozen S64 level-pick internals
read-only; writes only under artifacts/s65_refcolor_poc; network blocked in-process.
"""

from __future__ import annotations

import hashlib
import json
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from engine.color_correction.color_management import load_color_managed_source, srgb_profile_bytes  # noqa: E402
from engine.color_correction.formal_runtime import run_formal_color_runtime  # noqa: E402
from engine.color_correction.level_pick import (  # noqa: E402
    HAZE_MIN,
    LEVELS,
    SKIN_KEEP,
    LevelPickAnalysis,
    _adaptation_matrix,
    _gamut_pull,
    _prepare_render,
    _to_linear,
    _to_srgb,
    analyze_level_pick,
    delta_e2000,
    level_safety,
)

TASK_ID = "S65-REFCOLOR-POC"
OUT = REPO_ROOT / "artifacts" / "s65_refcolor_poc"
AI4K = Path(r"D:\HDDE样本\AI4K")
AICOLOR = Path(r"D:\HDDE样本\AIColor")
REAL_PAIRS = Path(r"D:\HDDE样本\RefColor")

CLEAN = {
    "S03_fashion": AI4K / "ChatGPT Image 2026年6月28日 16_05_17.png",
    "S04_ink": AI4K / "ChatGPT Image 2026年6月28日 16_54_53.png",
    "S05_tsingtao": AI4K / "ChatGPT Image 2026年6月30日 12_20_14.png",
    "S07_orange": AI4K / "ChatGPT Image 2026年9月12日 13_08_42.png",
    "S08_sky": AI4K / "ChatGPT Image 2026年9月12日 13_12_46.png",
    "S11_nvidia": AICOLOR / "ChatGPT Image 2026年7月1日 12_19_04 (1).png",
    "S13_huawei": AICOLOR / "ChatGPT Image 2026年7月8日 10_02_36.png",
    "S14_oppo": AICOLOR / "ChatGPT Image 2026年7月8日 10_05_23.png",
}
SERIES = {"S01_flower": AI4K / "2.png", "S09_flower": AI4K / "ChatGPT Image 2026年9月13日 13_59_42.png"}
CASTS = {"yellow": (0.0, 14.0), "blue": (0.0, -12.0), "green": (-10.0, 0.0)}

# Initial gates from the approved card; calibrated by the PoC, never loosened by the executor.
GATE_STRONG_REDUCTION = 0.60
GATE_MEDIUM_REDUCTION = 0.40
GATE_SERIES_MEDIUM_REDUCTION = 0.40
GATE_IDENTITY_MAX_DE = 0.5
GATE_SAME_TONE_MEDIUM_MAX_DE = 1.5
GATE_SECONDS = 5.0


class _OfflineSocket(socket.socket):
    def __init__(self, *a: Any, **k: Any) -> None:
        raise RuntimeError("NETWORK_BLOCKED_BY_S65_POC")


def block_network() -> None:
    socket.socket = _OfflineSocket  # type: ignore[misc]
    socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("NETWORK_BLOCKED_BY_S65_POC"))  # type: ignore[assignment]


def out_path(rel: str) -> Path:
    target = (OUT / rel).resolve()
    if OUT.resolve() not in target.parents:
        raise RuntimeError(f"PATH_ESCAPE: {rel}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_rgb(path: Path) -> np.ndarray:
    return np.ascontiguousarray(load_color_managed_source(path).pixels[..., :3])


def save_png(rgb: np.ndarray, path: Path) -> Path:
    Image.fromarray(rgb).save(path, format="PNG", icc_profile=srgb_profile_bytes(), compress_level=1)
    return path


def add_cast(rgb: np.ndarray, ab: tuple[float, float]) -> np.ndarray:
    lin = _to_linear(rgb.astype(np.float32) / 255.0) @ _adaptation_matrix((0.0, 0.0), ab).T
    return (np.clip(_to_srgb(_gamut_pull(lin)), 0, 1) * 255 + 0.5).astype(np.uint8)


def mean_de(a: np.ndarray, b: np.ndarray) -> float:
    step = max(1, max(a.shape[:2]) // 700)
    return float(delta_e2000(a[::step, ::step], b[::step, ::step]).mean())


# ------------------------------------------------------------- the method ---

def reference_cast_at(curve: list[list[float]], lightness: float) -> tuple[float, float]:
    knots = np.array(curve, dtype=np.float64)
    return float(np.interp(lightness, knots[:, 0], knots[:, 1])), float(np.interp(lightness, knots[:, 0], knots[:, 2]))


def tone_percentiles(rgb: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)
    return np.percentile(lab[..., 0][:: max(1, rgb.shape[0] // 512), :: max(1, rgb.shape[1] // 512)], [1, 5, 25, 50, 75, 95, 99])


def plan(target: np.ndarray, reference: np.ndarray) -> dict[str, Any]:
    t = analyze_level_pick(target)
    r = analyze_level_pick(reference)
    usable = bool(t.neutral["reliable"] and len(t.neutral.get("tone_curve") or []) > 2 and r.neutral["reliable"] and len(r.neutral.get("tone_curve") or []) > 2)
    return {"target": t, "reference": r, "usable": usable, "reason": "OK" if usable else "NO_RELIABLE_NEUTRAL_IN_TARGET_OR_REFERENCE",
            "tone_t": tone_percentiles(target), "tone_r": tone_percentiles(reference)}


def render(target: np.ndarray, p: dict[str, Any], strength: float, *, with_tone: bool) -> np.ndarray:
    analysis: LevelPickAnalysis = p["target"]
    src = target.astype(np.float32) / 255.0
    img = src
    if p["usable"]:
        base = _prepare_render(target, analysis)
        ref_curve = p["reference"].neutral["tone_curve"]
        out = np.zeros((src.shape[0] * src.shape[1], 3), np.float32)
        for (kl, ka, kb), (idx, w, lin) in zip(base.knots, base.knot_pixels):
            ra, rb = reference_cast_at(ref_curve, kl)
            dst = (ka + strength * (ra - ka), kb + strength * (rb - kb))
            out[idx] += w * np.einsum("ij,kj->ik", lin, _adaptation_matrix((ka, kb), dst))
        img = _to_srgb(_gamut_pull(out.reshape(src.shape)))
    if with_tone:
        # Lightness curve through matched percentiles, end points fixed: tone style, never clipping.
        xs = np.concatenate(([0.0], p["tone_t"], [100.0]))
        ys = np.concatenate(([0.0], p["tone_t"] + strength * (p["tone_r"] - p["tone_t"]), [100.0]))
        if np.all(np.diff(xs) > 0) and np.all(np.diff(ys) > 0):
            lab = cv2.cvtColor(img.astype(np.float32), cv2.COLOR_RGB2LAB)
            lab[..., 0] = np.interp(lab[..., 0], xs, ys).astype(np.float32)
            img = _to_srgb(_gamut_pull(_to_linear(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB))))
    if analysis.skin is not None:
        img = img + (SKIN_KEEP * analysis.skin)[..., None] * (src - img)
    return (np.clip(img, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


ROUTES = {"R1_WB": False, "R2_WB_TONE": True}


def high_chroma_de(a: np.ndarray, b: np.ndarray) -> float | None:
    lab = cv2.cvtColor(a.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)
    mask = np.hypot(lab[..., 1], lab[..., 2]) > 45
    if mask.sum() < 500:
        return None
    return round(float(delta_e2000(a[mask][None], b[mask][None]).mean()), 2)


def sheet(title: str, panels: list[tuple[str, np.ndarray]], path: Path) -> None:
    cell = 420
    thumbs = []
    for name, arr in panels:
        im = Image.fromarray(arr)
        im.thumbnail((cell, cell))
        thumbs.append((name, im))
    h = max(t.height for _, t in thumbs)
    canvas = Image.new("RGB", (len(thumbs) * (cell + 8), h + 64), "white")
    try:
        font = ImageFont.truetype("msyh.ttc", 20)
    except OSError:
        font = ImageFont.load_default()
    d = ImageDraw.Draw(canvas)
    d.text((6, 4), title, fill="black", font=font)
    x = 0
    for name, im in thumbs:
        canvas.paste(im, (x, 34))
        d.text((x + 4, 36 + im.height), name, fill="black", font=font)
        x += cell + 8
    canvas.save(path, quality=88)


def run_case(case_id: str, kind: str, target: np.ndarray, reference: np.ndarray, truth: np.ndarray | None,
             target_path: Path, reference_path: Path) -> dict[str, Any]:
    t0 = time.perf_counter()
    p = plan(target, reference)
    levels = {route: {name: render(target, p, s, with_tone=tone) for name, s in LEVELS.items()} for route, tone in ROUTES.items()}
    seconds = (time.perf_counter() - t0) / len(ROUTES)
    row: dict[str, Any] = {"case": case_id, "kind": kind, "usable": p["usable"], "reason": p["reason"], "seconds_per_route": round(seconds, 2)}
    base_t = mean_de(target, truth) if truth is not None else None
    row["dE_target_truth"] = round(base_t, 2) if base_t is not None else None
    for route, outs in levels.items():
        info = {}
        for name, img in outs.items():
            safety = level_safety(target, img, p["target"])
            entry = {"dE_vs_target": round(mean_de(img, target), 2), "safe": safety["passed"], "failures": safety["failures"],
                     "clip_growth": safety["clip_growth"], "high_chroma_dE": high_chroma_de(target, img)}
            if truth is not None:
                d = mean_de(img, truth)
                entry["dE_truth"] = round(d, 2)
                entry["reduction"] = round(1 - d / base_t, 3) if base_t else None
            info[name] = entry
            save_png(img, out_path(f"outputs/{case_id}/{route}_{name}.png"))
        row[route] = info
    # baseline: the current formal reference chain
    formal_out = out_path(f"outputs/{case_id}/formal_reference.png")
    if formal_out.exists():
        formal_out.unlink()
    formal = run_formal_color_runtime(target_path, formal_out, reference_path=reference_path).to_dict()
    produced = load_rgb(formal_out) if formal["output_path"] and formal_out.exists() else target
    row["formal"] = {"action": formal["result_action"], "dE_vs_target": round(mean_de(produced, target), 2)}
    if truth is not None:
        d = mean_de(produced, truth)
        row["formal"].update({"dE_truth": round(d, 2), "reduction": round(1 - d / base_t, 3) if base_t else None})
    panels = [("目标", target), ("参考", reference)] + [(f"R1 {n}", levels["R1_WB"][n]) for n in LEVELS] + [("现有参考校色", produced)]
    if truth is not None:
        panels.append(("标准答案", truth))
    sheet(f"{case_id}  {kind}", panels, out_path(f"review/{case_id}.jpg"))
    print(json.dumps({k: row[k] for k in ("case", "usable", "dE_target_truth", "seconds_per_route")}
                     | {"R1": {n: row["R1_WB"][n].get("reduction", row["R1_WB"][n]["dE_vs_target"]) for n in LEVELS},
                        "R2": {n: row["R2_WB_TONE"][n].get("reduction", row["R2_WB_TONE"][n]["dE_vs_target"]) for n in LEVELS},
                        "formal": row["formal"].get("reduction", row["formal"]["dE_vs_target"])}, ensure_ascii=False), flush=True)
    return row


def main() -> int:
    block_network()
    started = datetime.now(timezone.utc).isoformat()
    sources = {**CLEAN, **SERIES}
    before = {k: sha256(v) for k, v in sources.items()}
    tmp = out_path("inputs/.keep").parent
    rows = []
    clean = {k: load_rgb(v) for k, v in sources.items()}

    def target_file(name: str, cast: str) -> tuple[np.ndarray, Path]:
        img = add_cast(clean[name], CASTS[cast])
        return img, save_png(img, tmp / f"{name}_{cast}.png")

    # 1. ground truth: own clean image as reference
    for name in CLEAN:
        for cast in CASTS:
            img, path = target_file(name, cast)
            rows.append(run_case(f"GT_{name}_{cast}", "ground_truth", img, clean[name], clean[name], path, CLEAN[name]))
    # 2. same series: the reference is a different clean image of the same series
    for tgt, cast, ref in (("S13_huawei", "yellow", "S14_oppo"), ("S14_oppo", "blue", "S13_huawei"),
                           ("S01_flower", "blue", "S09_flower"), ("S09_flower", "yellow", "S01_flower")):
        img, path = target_file(tgt, cast)
        rows.append(run_case(f"SERIES_{tgt}_{cast}_ref_{ref}", "same_series", img, clean[ref], clean[tgt], path, sources[ref]))
    # 3. identity: the reference is the target itself
    for name in ("S13_huawei", "S07_orange", "S03_fashion"):
        rows.append(run_case(f"IDENTITY_{name}", "identity", clean[name], clean[name], None, CLEAN[name], CLEAN[name]))
    # 4. same tone: two clean images already in the same style
    rows.append(run_case("SAMETONE_S13_ref_S14", "same_tone", clean["S13_huawei"], clean["S14_oppo"], None, CLEAN["S13_huawei"], CLEAN["S14_oppo"]))
    rows.append(run_case("SAMETONE_S01_ref_S09", "same_tone", clean["S01_flower"], clean["S09_flower"], None, SERIES["S01_flower"], SERIES["S09_flower"]))

    after = {k: sha256(v) for k, v in sources.items()}
    summary = {
        "task_id": TASK_ID, "started_at_utc": started, "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "network": "BLOCKED_IN_PROCESS_SOCKET_GUARD", "levels": LEVELS, "casts": CASTS,
        "real_pairs": "NOT_PROVIDED" if not REAL_PAIRS.exists() else "SEE_ROWS",
        "gates": {"strong_reduction_min": GATE_STRONG_REDUCTION, "medium_reduction_min": GATE_MEDIUM_REDUCTION,
                  "series_medium_reduction_min": GATE_SERIES_MEDIUM_REDUCTION, "identity_max_dE": GATE_IDENTITY_MAX_DE,
                  "same_tone_medium_max_dE": GATE_SAME_TONE_MEDIUM_MAX_DE, "seconds_max": GATE_SECONDS},
        "samples_unchanged": before == after, "rows": rows,
    }
    out_path("summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
