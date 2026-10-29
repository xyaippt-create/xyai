"""S66-C regression: every S65/S66-A group keeps its pixels; list where the advice changed.

Read-only on samples. Evidence goes to artifacts/s66c_reference_advice/regression.json.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools" / "experiments"))

from engine.color_correction.reference_level_pick import NOTICEABLE_OFFSET, plan_reference, render_reference_level  # noqa: E402
from s66a_reference_level_pick_validation import S65, case_files  # noqa: E402

OUT = REPO_ROOT / "artifacts" / "s66c_reference_advice"


def main() -> int:
    rows = json.loads((S65 / "summary.json").read_text(encoding="utf-8"))["rows"]
    results, exact, changed = [], 0, []
    for case in [row["case"] for row in rows]:
        target_path, reference_path = case_files(case)
        target = np.asarray(Image.open(target_path).convert("RGB"))
        reference = np.asarray(Image.open(reference_path).convert("RGB"))
        started = time.perf_counter()
        plan = plan_reference(target, reference)
        seconds = round(time.perf_counter() - started, 2)
        record = plan.to_record()
        parity = {}
        for level in ("light", "medium", "strong"):
            frozen = np.asarray(Image.open(S65 / "outputs" / case / f"R3_ALIGN_{level}.png").convert("RGB"))
            parity[level] = bool(np.array_equal(render_reference_level(target, plan, level), frozen))
            exact += parity[level]
        old_advice = "medium" if plan.usable and float(plan.description.get("offset") or 0) >= NOTICEABLE_OFFSET else "original"
        row = {"case": case, "plan_seconds": seconds, "parity": parity, "summary": plan.description.get("summary"),
               "old_recommended": old_advice, "new_recommended": record["recommended_level"],
               "reason": record["recommendation_reason"], "notice": record["notice"],
               "target_self": record["target_self_measurement"], "reference_self": record["reference_self_measurement"]}
        if old_advice != record["recommended_level"]:
            changed.append(case)
        results.append(row)
    summary = {"groups": len(results), "exact_levels": exact, "expected_levels": 3 * len(results),
               "advice_changed": changed, "median_plan_seconds": float(np.median([r["plan_seconds"] for r in results])),
               "max_plan_seconds": max(r["plan_seconds"] for r in results), "samples": results}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "regression.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "samples"}, ensure_ascii=False))
    return 0 if exact == 3 * len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
