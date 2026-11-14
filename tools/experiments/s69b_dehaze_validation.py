"""S69-B: validate the level-pick de-haze change (v2 frozen at HEAD vs the working copy).

Split (declared in the task card before coding, not changed during execution):
  tune       = the 8 S69-A TUNE images, clean and haze model A
  validation = the 3 HOLDOUT images (clean, haze A), haze model B on all 11 images,
               and the 13 design-tone recheck images
Read-only on samples. Evidence: artifacts/s69_color_full_scan/s69b_gates.json
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools" / "experiments"))

import numpy as np
from PIL import Image

import s69a_gate_validation as s69a
from engine.color_correction import level_pick as v3
from engine.color_correction import reference_level_pick as ref
from engine.color_correction.level_pick import _to_linear, _to_srgb

OUT = REPO / "artifacts" / "s69_color_full_scan"
DESIGN = OUT / "s69a_design_tone_recheck"


def add_haze_b(rgb, amt=0.15, grey=0.6):
    """Haze model B (validation only): blend in linear light toward the linear value of sRGB `grey`."""
    lin = _to_linear(rgb.astype(np.float32) / 255.0)
    g = float(_to_linear(np.array([grey], np.float32))[0])
    return (np.clip(_to_srgb(lin * (1 - amt) + amt * g), 0, 1) * 255 + 0.5).astype(np.uint8)


def run(mod, img, truth):
    an = mod.analyze_level_pick(img)
    row = {"category": an.category, "grey": "GREY" in an.category, "recommended": an.recommended_level, "haze": dict(an.haze)}
    for level in ("light", "medium", "strong"):
        out = mod.render_level(img, an, level)
        row[level] = s69a.mde(out, truth)
        if level == "strong":
            row["strong_move"] = s69a.mde(out, img)
            row["strong_safe"] = mod.level_safety(img, out, an)["passed"]
    return row


def haze_gates(rows, side):
    out = {}
    for model in ("A", "B"):
        cases = [r for r in rows if r["kind"] == f"HAZE_{model}"]
        found = [r for r in cases if r[side]["grey"]]
        red = [1 - r[side]["strong"] / r["input_de"] for r in found]
        out[model] = {
            "detected": f"{len(found)}/{len(cases)}",
            "missed": [r["case"] for r in cases if not r[side]["grey"]],
            "strong_reduction_median": round(float(np.median(red)), 3) if red else None,
            "light_worse": [r["case"] for r in found if r[side]["light"] > r["input_de"]],
            "strong_worse": {r["case"]: round(r[side]["strong"] - r["input_de"], 3) for r in found if r[side]["strong"] > r["input_de"]},
            "by_group": {g: [r["case"] for r in found if r["group"] == g] for g in ("TUNE", "HOLDOUT")},
        }
    clean = [r for r in rows if r["kind"] == "CLEAN"]
    design = [r for r in rows if r["kind"] == "DESIGN"]
    out["clean_flagged"] = {r["case"]: r[side]["strong_move"] for r in clean if r[side]["grey"]}
    out["design_flagged"] = {r["case"]: r[side]["strong_move"] for r in design if r[side]["grey"]}
    out["unsafe_strong"] = [r["case"] for r in rows if not r[side]["strong_safe"]]
    return out


def cast_regression():
    """Re-score the S69-A cast cases with the working copy; gates 1-5 must equal the frozen v2 record."""
    frozen = json.loads((OUT / "s69a_gates.json").read_text(encoding="utf-8"))
    rows = []
    for group, srcs in (("TUNE", s69a.TUNE), ("HOLDOUT", s69a.HOLDOUT)):
        for name, path in srcs.items():
            clean = s69a.load(path)
            cases = [("clean", "CLEAN", clean, None)]
            cases += [(c, "GT", s69a.add_cast(clean, ab), tag) for c, (ab, tag) in s69a.CASTS.items()]
            cases += [("mid_yellow14", "GT_MID", s69a.add_midtone_cast(clean, (0.0, 14.0)), "YELLOW")]
            for cast, kind, img, tag in cases:
                ev = s69a.evaluate(v3, img, clean)
                rows.append({"case": f"{name}__{cast}", "image": name, "group": group, "kind": kind, "truth_tag": tag,
                             "cast_de": s69a.mde(img, clean), "old": ev, "new": ev})
    keys = ("g1b_visible_recommended_correction", "g1_strong_reduction_median", "g2_worse_than_cast", "g3_wrong_direction",
            "g4_clean_recommended_correction", "g5_design_tone_temp")
    report = {}
    for scope, sel in (("TUNE", ("TUNE",)), ("HOLDOUT", ("HOLDOUT",)), ("ALL", ("TUNE", "HOLDOUT"))):
        now = s69a.gates([r for r in rows if r["group"] in sel])["new"]
        was = frozen["summary"][scope]["new"]
        report[scope] = {k: {"v2": was[k], "v3": now[k], "same": was[k] == now[k]} for k in keys}
    changed = {}
    frozen_rows = {r["case"]: r["new"] for r in frozen["rows"] if r["kind"] in ("GT", "GT_MID", "CLEAN")}
    for r in rows:
        f = frozen_rows[r["case"]]
        if (f["category"], f["recommended"]) != (r["new"]["category"], r["new"]["recommended"]) or abs(f["strong_de"] - r["new"]["strong_de"]) > 0.05:
            changed[r["case"]] = {"v2": [f["category"], f["recommended"], f["strong_de"]],
                                  "v3": [r["new"]["category"], r["new"]["recommended"], r["new"]["strong_de"]]}
    return {"gates": report, "rows_changed": changed}


def reference_regression(v2):
    """33 S65/S66 groups: rendered pixels must equal the frozen outputs; list advice that moved v2 -> v3."""
    from s66a_reference_level_pick_validation import S65, case_files
    groups = json.loads((S65 / "summary.json").read_text(encoding="utf-8"))["rows"]
    exact, advice_changed = 0, {}
    for case in [g["case"] for g in groups]:
        t_path, r_path = case_files(case)
        target, reference = (np.asarray(Image.open(p).convert("RGB")) for p in (t_path, r_path))
        plan = ref.plan_reference(target, reference)
        for level in ("light", "medium", "strong"):
            frozen = np.asarray(Image.open(S65 / "outputs" / case / f"R3_ALIGN_{level}.png").convert("RGB"))
            exact += bool(np.array_equal(ref.render_reference_level(target, plan, level), frozen))
        ref.analyze_level_pick = v2.analyze_level_pick
        try:
            old = ref.plan_reference(target, reference).to_record()["recommended_level"]
        finally:
            ref.analyze_level_pick = v3.analyze_level_pick
        new = plan.to_record()["recommended_level"]
        if old != new:
            advice_changed[case] = [old, new]
    return {"groups": len(groups), "exact_levels": exact, "expected_levels": 3 * len(groups), "advice_changed": advice_changed}


def preview_seconds(v2):
    src = Image.open(s69a.TUNE["S07_orange"]).convert("RGB").resize((3840, 2160), Image.LANCZOS)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "t.png"
        src.save(path, compress_level=1)
        times = {}
        for label, mod in (("v2", v2), ("v3", v3), ("v2_again", v2), ("v3_again", v3)):
            t = time.perf_counter()
            mod.build_level_pick_preview(path)
            times[label] = round(time.perf_counter() - t, 2)
    return times


def main() -> int:
    v2 = s69a.frozen_module()
    rows = []
    for group, srcs in (("TUNE", s69a.TUNE), ("HOLDOUT", {} if "--quick" in sys.argv else s69a.HOLDOUT)):
        for name, path in srcs.items():
            clean = s69a.load(path)
            for kind, img in (("CLEAN", clean), ("HAZE_A", s69a.add_haze(clean)), ("HAZE_B", add_haze_b(clean))):
                rows.append({"case": f"{name}__{kind}", "group": group, "kind": kind, "input_de": s69a.mde(img, clean),
                             "v2": run(v2, img, clean), "v3": run(v3, img, clean)})
            print(name, "done", flush=True)
    for path in ([] if "--quick" in sys.argv else sorted(DESIGN.glob("C*.jpg"))):
        img = s69a.load(path)
        rows.append({"case": f"design_{path.stem}", "group": "VALIDATION", "kind": "DESIGN", "input_de": 0.0,
                     "v2": run(v2, img, img), "v3": run(v3, img, img)})
    if "--quick" in sys.argv:  # tuning view: the tune set only, validation results stay unseen
        tune = [r for r in rows if r["group"] == "TUNE"]
        print(json.dumps(haze_gates(tune, "v3"), ensure_ascii=False, indent=1))
        for r in tune:
            v = r["v3"]
            print(f'{r["case"]:22s} in={r["input_de"]:.2f} {v["category"]:12s} L={v["light"]:.2f} M={v["medium"]:.2f} S={v["strong"]:.2f} safe={v["strong_safe"]}')
        return 0
    report = {"version": v3.LEVEL_PICK_VERSION, "haze": {"v2": haze_gates(rows, "v2"), "v3": haze_gates(rows, "v3")}}
    print(json.dumps(report, ensure_ascii=False, indent=1), flush=True)
    if "--quick" not in sys.argv:
        report["cast_regression"] = cast_regression()
        report["reference"] = reference_regression(v2)
        report["preview_seconds_4k"] = preview_seconds(v2)
        print(json.dumps({k: report[k] for k in ("cast_regression", "reference", "preview_seconds_4k")}, ensure_ascii=False, indent=1))
    report["rows"] = rows
    (OUT / ("s69b_gates_quick.json" if "--quick" in sys.argv else "s69b_gates.json")).write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
