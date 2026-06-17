# V0.4.6 T01 Phase 1 Baseline Freeze Report

Date: 2026-06-17
Project: VisualMasterPro / 褰辩晫
Task: T01 鍐荤粨 V0.4.6 Phase 1 鍩虹嚎
Conclusion: PASS_WITH_BLOCKERS

## 1. Executive Summary

T01 completed the read-only baseline audit for the current V0.4.6 Phase 1 working tree. The four core samples were processed, source hashes were preserved, final outputs were generated in an isolated test directory, diagnostic fields were captured, and the V0.4.5.3 API/SSE regression script passed.

This is not a fully frozen release baseline yet. The working tree contains uncommitted production-code changes, so the current V0.4.6 Phase 1 state cannot be uniquely reproduced by Git commit alone. Two known quality-gate failures also remain: ordinary PNG and Chinese small-text PNG both report `quality_1080p_pass=false`.

T02 condition: 瀛樺湪闃绘柇锛屾殏涓嶈兘杩涘叆T02

## 2. Git And Code Status

Baseline commit:

| Item | Value |
|---|---|
| Branch | `main` |
| HEAD | `780d49bd470a1015245f9d359e03704ea6bcc5c2` |
| HEAD short | `780d49b` |
| HEAD time | `2026-06-16 07:54:02 +0800` |
| HEAD subject | `V0.4.5.3 stable output folder native picker and output_dir pipeline` |
| Tags at HEAD | none |
| Stash | none |
| `780d49b` ancestor of `HEAD` | true |

Current Git status:

```text
 M AGENTS.md
 M backend/v036_output_core.py
 M engine/algorithms/text_clarity.py
 M main.py
?? docs/03_CURRENT_STATUS_V0.4.5.1.md
?? docs/09_CODEX_CHANGELOG.md
?? docs/reports/
?? docs/sync/
?? runtime/baseline_validation_20260617/
?? runtime/diagnostics/
?? tests/baseline_v046_phase1.py
?? tests/diagnostics/
?? tests/results/
```

T01 did not intentionally change production code, image algorithms, API, SSE, frontend, task scheduling, output selection, or `default_input_dir`. The production files already dirty before this freeze audit remain a blocker for true baseline freezing:

| File | Status |
|---|---|
| `backend/v036_output_core.py` | modified |
| `engine/algorithms/text_clarity.py` | modified |
| `main.py` | modified |
| `AGENTS.md` | modified |

## 3. Runtime Environment

| Item | Value |
|---|---|
| OS | `Windows-11-10.0.26200-SP0` |
| Python | `3.12.13` |
| Virtual env | `D:\Codex\04_Visual-Master-Pro\.venv` |
| FastAPI | `0.137.1` |
| Uvicorn | `0.49.0` |
| OpenCV | `4.13.0` |
| NumPy | `2.4.6` |
| Pillow | `12.2.0` |
| Node.js | `v24.16.0` |
| npm | `11.13.0` |
| React | `^18.2.0` |
| Vite | `^5.2.0` |
| Tailwind CSS | `^3.4.1` |
| Backend command | `D:\Codex\04_Visual-Master-Pro\.venv\Scripts\python.exe main.py --web` |
| Frontend command | `npm.cmd run dev` |
| Backend port | `8787` |
| Frontend port | `5173` |
| Env vars captured | `APPDATA=SET` |

## 4. Core Sample List

All source inputs kept the same SHA-256 hash before and after T01.

| Sample | Input | Format | Size | Source SHA-256 | Source unchanged |
|---|---|---:|---:|---|---|
| JPG | `D:\Codex\04_Visual-Master-Pro\tests\outputs\v036_api_validation\output\images\case_original_jpg_vmp_v036_optimized.jpg` | JPEG | 7,743 B | `e63b4d7e91e5bbea6c3a1e70402671381e977e86a4687b90fae5e72121096fb7` | true |
| 鏅€?PNG | `D:\Codex\04_Visual-Master-Pro\runtime\v044_validation\inputs\test_1.png` | PNG | 3,476 B | `de686150a6bb65246fc308e98c136a300774e776adbb363155f7294a4f71e663` | true |
| 閫忔槑 PNG | `D:\Codex\04_Visual-Master-Pro\tests\outputs\v036_backend_validation_final\input\realalpha.png` | PNG RGBA | 39,614 B | `886a52a64c1057466bcd1549d4ee7299058e0281782edcd43b21198f21fa4385` | true |
| 涓枃灏忓瓧鍥?| `D:\Codex\04_Visual-Master-Pro\backend\backend_uploads\楂樻竻娴嬭瘯.png` | PNG | 2,107 B | `178449c424d745333c6c5c476386bf24260772b2e406974f94611e1493a42cfa` | true |

## 5. Three-Way Output Comparison

Historical V0.4.5.3 output selection rule: latest file matching `*20260617_08*.png` in the historical diagnostic output directories. This avoids using post-Phase-1 14:xx rerun outputs as the historical baseline.

| Sample | V0.4.5.3 historical output | V0.4.6 Phase 1 output | Output exists |
|---|---|---|---|
| JPG | `tests\diagnostics\output\core\JPG\case_original_jpg_vmp_v036_optimized_褰辩晫楂樻竻_1080P_fidelity_20260617_084128.png` | `tests\results\v046_phase1_baseline\JPG\case_original_jpg_vmp_v036_optimized_褰辩晫楂樻竻_1080P_fidelity_20260617_150222.png` | true |
| 鏅€?PNG | `tests\diagnostics\output\core\鏅€歅NG\test_1_褰辩晫楂樻竻_1080P_fidelity_20260617_084130.png` | `tests\results\v046_phase1_baseline\鏅€歅NG\test_1_褰辩晫楂樻竻_1080P_fidelity_20260617_150224.png` | true |
| 閫忔槑 PNG | `tests\diagnostics\output\core\閫忔槑PNG\realalpha_褰辩晫楂樻竻_1080P_fidelity_20260617_084131.png` | `tests\results\v046_phase1_baseline\閫忔槑PNG\realalpha_褰辩晫楂樻竻_1080P_fidelity_20260617_150226.png` | true |
| 涓枃灏忓瓧鍥?| `tests\diagnostics\output\core\涓枃灏忓瓧鍥綷楂樻竻娴嬭瘯_褰辩晫楂樻竻_1080P_text_safe_20260617_084134.png` | `tests\results\v046_phase1_baseline\涓枃灏忓瓧鍥綷楂樻竻娴嬭瘯_褰辩晫楂樻竻_1080P_text_safe_20260617_150230.png` | true |

## 6. Diagnostic Fields Summary

| Sample | image_type | Output | Output size | Time | quality_1080p_pass | Level | text_clarity | small_text | edge_clean | pseudo_hd | artifact | Result |
|---|---|---:|---:|---:|---|---|---:|---:|---:|---|---|---|
| JPG | `text_poster` | 1622x1080 PNG | 94,805 B | 2.122s | true | `standard` | 46.6452 | 41.1161 | 46.6452 | low | low | PASS |
| 鏅€?PNG | `product_kv` | 1728x1080 PNG | 190,985 B | 2.568s | false | `failed` | 29.8266 | 28.1199 | 29.8266 | low | low | PASS_WITH_KNOWN_ISSUE |
| 閫忔槑 PNG | `product_kv` | 1920x1080 PNG | 651,143 B | 3.507s | true | `standard` | 39.6729 | 37.4538 | 39.6729 | low | low | PASS |
| 涓枃灏忓瓧鍥?| `text_poster` | 1620x1080 PNG | 121,992 B | 2.608s | false | `failed` | 28.1225 | 25.3631 | 28.1225 | low | low | PASS_WITH_KNOWN_ISSUE |

Additional captured diagnostics:

| Sample | `v046_text_engine_active` | `v046_quality_profile` |
|---|---|---|
| JPG | true | `1080P+ small text readability` |
| 鏅€?PNG | false | `1080P+ small text readability` |
| 閫忔槑 PNG | false | `1080P+ small text readability` |
| 涓枃灏忓瓧鍥?| true | `1080P+ small text readability` |

## 7. API And SSE Regression

Command:

```text
D:\Codex\04_Visual-Master-Pro\.venv\Scripts\python.exe tests\diagnostics\test_v0453_api_pipeline.py
```

Result: PASS

| Sample | `/api/upload` | Polling | SSE | SSE reconnect | Double SSE | `final_output_url` |
|---|---|---|---|---|---|---|
| JPG | PASS | PASS | PASS | PASS | PASS | PASS |
| 鏅€?PNG | PASS | PASS | PASS | PASS | PASS | PASS |
| 閫忔槑 PNG | PASS | PASS | PASS | PASS | PASS | PASS |
| 涓枃灏忓瓧鍥?| PASS | PASS | PASS | PASS | PASS | PASS |

Failure SSE case:

| Case | Result | Notes |
|---|---|---|
| `diagnostic_failed_task` | PASS | SSE returned failed status and completed with `[DONE]` behavior. |

API regression confirms upload starts background processing, polling reaches `completed`, SSE reconnect/double subscribe do not duplicate processing, and `final_output_url` points to a real served file.

## 8. Directory Isolation

| Path role | Path | Exists |
|---|---|---|
| Runtime uploads legacy path | `D:\Codex\04_Visual-Master-Pro\runtime\uploads` | false |
| Actual upload cache | `D:\Codex\04_Visual-Master-Pro\runtime\v04_inputs` | true |
| Runtime work | `D:\Codex\04_Visual-Master-Pro\runtime\work` | true |
| Logs | `D:\Codex\04_Visual-Master-Pro\logs` | true |
| T01 diagnostics | `D:\Codex\04_Visual-Master-Pro\runtime\diagnostics\v046_t01` | true |
| V0.4.6 golden directory | `D:\Codex\04_Visual-Master-Pro\tests\golden_v046` | false |
| T01 output directory | `D:\Codex\04_Visual-Master-Pro\tests\results\v046_phase1_baseline` | true |
| API diagnostic output directory | `D:\Codex\04_Visual-Master-Pro\tests\diagnostics\output\api` | true |
| Formal default output directory | `C:\Users\xyppt\Desktop\闆師Ai澧炲己寮曟搸\杈撳嚭鎴愬搧` | true |

T01 outputs are isolated under `tests\results\v046_phase1_baseline`. API regression outputs are isolated under `tests\diagnostics\output\api`. `runtime\work` remains temporary processing storage and is not used as formal final output storage.

## 9. Known Failures And Blockers

| Severity | Item | Status |
|---|---|---|
| Blocker | V0.4.6 Phase 1 production code is uncommitted | Current baseline cannot be uniquely reproduced by Git commit alone. |
| Blocker | Dirty production files exist | `backend/v036_output_core.py`, `engine/algorithms/text_clarity.py`, and `main.py` are modified. |
| Known issue | 鏅€?PNG quality gate | `quality_1080p_pass=false`, `quality_1080p_level=failed`. |
| Known issue | 涓枃灏忓瓧鍥?quality gate | `quality_1080p_pass=false`, `quality_1080p_level=failed`. |
| Known issue | Output size warnings | All four samples produced file-size expansion warnings. |
| Non-blocking audit note | `tests\golden_v046` absent | T01 used isolated result outputs, not a golden set. |

## 10. Differences From History

V0.4.5.3 already fixed the upload/SSE/final output path chain. T01 confirms that those regressions remain passing after the current V0.4.6 Phase 1 working-tree changes.

V0.4.6 Phase 1 adds captured diagnostic fields around the 1080P+ small-text readability path, including `small_text_readability_score`, `text_edge_clean_score`, `v046_text_engine_active`, and `v046_quality_profile`. These fields are visible in the core result JSON. API response field names remain compatible with the existing regression tests.

The present difference from a release-grade freeze is traceability: V0.4.6 Phase 1 is still represented by dirty working-tree changes on top of `780d49b`, not by a dedicated commit or tag.

## 11. Blockers Before T02

T02 should not start until the following are resolved:

1. Commit or otherwise explicitly freeze the V0.4.6 Phase 1 production-code state.
2. Re-run T01 baseline after the freeze point so the baseline maps to an exact commit or tag.
3. Decide whether `quality_1080p_pass=false` for ordinary PNG and Chinese small-text PNG is acceptable as a known issue, or must be fixed before T02.

T02 condition: 瀛樺湪闃绘柇锛屾殏涓嶈兘杩涘叆T02

## 12. New Or Modified Files From T01

T01 intentionally added read-only audit artifacts only:

| File | Purpose |
|---|---|
| `tests/baseline_v046_phase1.py` | Read-only baseline capture script for four core samples. |
| `runtime/diagnostics/v046_t01/v046_t01_baseline.json` | Machine-readable baseline results, hashes, environment, Git, and directory audit. |
| `tests/results/v046_phase1_baseline/` | Isolated V0.4.6 Phase 1 sample outputs. |
| `tests/diagnostics/v0453_api_pipeline_results.json` | Refreshed API/SSE regression evidence. |
| `docs/reports/V046_T01_PHASE1_BASELINE.md` | This report. |

No production-code file was intentionally edited as part of T01.

## 13. T01.1 Git Baseline Freeze Update

T01.1 executed on 2026-06-17 after the initial T01 audit. The Phase 1 production-code changes were reviewed and frozen into a Git baseline.

| Item | Value |
|---|---|
| Initial freeze commit before report refresh | `8bf051cd3fcc6e8f7c363c2b43eac819c1c4e6b3` |
| Initial freeze short commit | `8bf051c` |
| Initial freeze commit time | `2026-06-17 16:05:23 +0800` |
| Commit subject | `V0.4.6 Phase 1 small-text readability baseline` |
| Tag | `v0.4.6-phase1-baseline` |
| Baseline retest started | `2026-06-17T16:06:04` |
| Baseline retest finished | `2026-06-17T16:06:13` |
| Baseline retest result | PASS |
| API/SSE regression result | PASS |

Diff review result:

| Area | Result |
|---|---|
| Phase 1 small-text readability changes | Confirmed in `backend/v036_output_core.py` and `engine/algorithms/text_clarity.py`. |
| V0.4.5.3 task/SSE baseline continuity | Confirmed in `main.py`; required for the current Phase 1 baseline to keep upload, polling, SSE, and final output behavior stable. |
| Phase 2 / mid-frequency algorithm changes | Not found in the T01.1 production diff. |
| Temporary debug or test-only production logic | Not found. |
| New hard-coded local preview URL or frontend disk path | Not found. |
| API/SSE contract drift | Regression PASS; no field rename or frontend contract change found. |
| Formal output selection drift | Not found; final output path/suffix protection remains intact. |

T01.1 sample retest:

| Sample | image_type | quality_1080p_pass | quality_1080p_level | text_clarity_score | Output size | Time | Source hash unchanged |
|---|---|---|---|---:|---:|---:|---|
| JPG | `text_poster` | true | `standard` | 46.6452 | 94,805 B | 2.221s | true |
| 普通 PNG | `product_kv` | false | `failed` | 29.8266 | 190,985 B | 2.050s | true |
| 透明 PNG | `product_kv` | true | `standard` | 39.6729 | 651,143 B | 2.655s | true |
| 中文小字图 | `text_poster` | false | `failed` | 28.1225 | 121,992 B | 1.809s | true |

T01.1 API/SSE retest:

| Check | Result |
|---|---|
| `/api/upload` | PASS |
| Task polling | PASS |
| SSE success stream | PASS |
| SSE reconnect | PASS |
| Double SSE subscribe | PASS |
| Failure SSE failed status | PASS |
| Failure SSE `[DONE]` behavior | PASS |
| `final_output_url` served file | PASS |

Known issues retained after T01.1:

| Item | Status |
|---|---|
| 普通 PNG quality gate | Still `quality_1080p_pass=false`; not fixed in T01.1. |
| 中文小字图 quality gate | Still `quality_1080p_pass=false`; not fixed in T01.1. |
| File-size expansion warnings | Still present for all four samples. |
| Historical V0.4.5.3 comparison | Still based mainly on historical diagnostic outputs selected by `*20260617_08*.png`. |

T02 condition after T01.1: 可以进入T02
