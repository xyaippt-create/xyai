# Codex Changelog

## 2026-10-29 - Image delivery redundancy cleanup (behaviour unchanged)

- SHA256: `backend/image_compression_api._sha256_file` and `backend/batch_compression_api.file_sha` are now the shared `engine.image_compression.common.sha256_file`; the module names stay because tests patch them.
- Smart delivery execute: the 23 fields shared by the completed and failed result of an entry are built once (same keys and order, response unchanged); the three-step source Task lookup (live Task → shared fact → Result retained after Task deletion) is one helper, `delivery_task_record`, used by both callers.
- Removed the frontend `groupDeliveryCandidates` (multi-scheme leftover, used only by its own two tests) and those tests.
- Batch import no longer keeps a second copy of each image for the token TTL: once the batch snapshot is verified, the intake copy's authorizations are expired and the existing ownership-checked `prune_tokens()` removes it. Failure to release only logs a warning. A real-app test checks that only the unrelated single-image intake remains.
- Kept on purpose: `/api/image-compression/select-candidate` (backend tests use it as a contract that only the Winner can be selected); `engine/image_compression/legacy_adapters.py` (legacy evidence converter, only its own test uses it, still-needed status 未确认); the duplicate field aliases in delivery responses (public fields read by frontend and tests); per-page `formatBytes` / `requestJson` copies (they format and resolve URLs differently, so merging them would change display and behaviour); `DUPLICATE_FINAL_NAME` (still reachable when a source name has issues). Desktop app not re-run; the batch import change is covered by the real-app test runtime. No Git write.

## 2026-10-29 - Image delivery in-memory tables: bounded run cache, delivery runs reopen after restart

- Measured first: `token_registry` is already bounded by its 1 h TTL. Preview tokens are reused while valid and `prune_tokens()` runs on every token lookup, so the earlier review overstated it. `expired_feedback_tokens` grows by one per expired test feedback package and was left as is.
- `smart_delivery_run_registry` kept every run forever and was empty after a restart, so "打开交付目录 / 打开交付文件" for a persisted delivery id returned `SMART_DELIVERY_RUN_NOT_FOUND`. The in-memory cache is now capped at `SMART_DELIVERY_RUN_CACHE_SIZE = 64`; a missing run is rebuilt from its persisted `delivery:{id}` fact. Paths come only from the fact and must still sit directly in the formal 智能交付 directory. New delivery facts also record `delivery_item_id` (additive); older facts open by folder or by Result id.
- `batch_preview_tokens` dropped entries whose token was already pruned.
- Tests: 2 added in `test_smart_delivery_api.py` (reopen after restart; cache capped at 1 with the evicted run reopening from its fact). The batch-preview pruning has no dedicated test. Desktop: a delivery made by an earlier app instance (`delivery_20261029_091013_1ed7dc1a`) reopened its folder with 200; an unknown id still returns 404. No Git write.

## 2026-10-29 - Batch compression Results deliverable through Smart Delivery

- Root cause: the Output Center snapshot nests batch Results under their batch card. `build_smart_delivery_plan` and the frontend `loadBatchOutputItems` only looked at top-level items, so every batch Result got 404 `UNIFIED_RESULT_NOT_FOUND`, and the batch panel kept its delivery checkboxes disabled ("输出中心中没有找到此 Result 的正式成品").
- Backend: plan building also looks up batch children that are `available` and whose id is in `output_center_index`, i.e. file present and SHA-bound to the Result by the existing snapshot check. Unbound or wrong-SHA children stay undeliverable; `require_output_center_item` still verifies the batch binding. Frontend: `loadBatchOutputItems` flattens batch children; `isBatchDeliveryEligible` accepts the child's batch status `COMPLETED` and requires `available !== false`.
- Tests: 2 real-app backend tests (`test_batch_output_contract.py`: deliver batch Results by result_id with SHA check; a wrong registered SHA stays 404 with no copy) and 1 frontend test. Related backend 201/201 and frontend suites passed.
- Desktop (8797, formal root, `dist/` rebuilt without emptying): a 3-image batch in the batch panel → all rows selectable → 批量交付（3）→ 3 × preflight + execute, all 已交付, panel reports SHA closure. The three copies in `输出/智能交付` (`验收_交付_1-3_影界压缩_261029_02.jpg`) are byte-identical to their Winners. Acceptance files remain in the formal directory. No Git write.

## 2026-10-29 - Desktop acceptance of image delivery P0/P1 fixes; shutdown-interrupted batch items kept for recovery

- Rebuilt `dist/` without emptying old assets (8787 belongs to another session) and ran an own desktop instance on 8797 (formal root `D:\影界文件`). Passed in the real app: single 38.76 MB PNG → 14.06 MB JPG; API stayed responsive during the 40 MB intake (238 pings, p50 24 ms, max 58 ms). Single delivery from SmartDeliveryPage with the execute response dropped by the test harness: the server completed the delivery, the page confirmed it through `/api/smart-delivery/requests/{key}`, showed success, one copy, SHA equal to the Result. Batch of three samples completed with Results registered. During a 40 MB batch encode, 166 pings had p50 26 ms / p95 72 ms, 2 over 500 ms (max 1.7 s).
- Found during acceptance: closing the app while a batch item was encoding marked it FAILED (`cannot schedule new futures after shutdown`). The launcher waits only 15 s for the backend, then interpreter shutdown refuses new thread work while the batch drain still runs. This was pre-existing (the original code failed at the later `to_thread(publish)`); the P1 hashing change only moved the failure point earlier. `work()` now keeps such an item QUEUED with `recovery_active` while the service is closing (identity/path `ValueError`s still fail). Verified in the app: shutdown during a 40 MB encode → item kept → after restart it resumed and completed with one output file, no `_02`. One test added. The launcher's 15 s limit and its "正式 Backend 未能正常退出" exit while draining are unchanged.
- Not a regression: the reported 62% saving comes from the synthetic noisy samples; HEAD and current code produce byte-identical winners (q98 JPG, 62.5%) and 99.1% on a noise-free variant. `engine/image_compression/` is unchanged.
- Open, pre-existing, outside this change: batch Results are nested under their batch entry in the Output Center snapshot, so `/api/smart-delivery/preflight` with their `result_ids` returns 404 `UNIFIED_RESULT_NOT_FOUND`; batch delivery of those Results was not verified. The 4K image `验收_大图_批量` from the first shutdown is a FAILED batch item in the formal registry. Acceptance outputs remain in `输出/图片压缩/交付优化` (`accept_big_*`, `验收_交付_1-3_*`, `验收_大图_关闭恢复_*`) and `输出/智能交付` (`accept_big_*`). No Git write.

## 2026-10-29 - Image delivery low-risk P1: event-loop blocking, duplicate hashing, preflight facts, single-delivery idempotency

- Event loop: single intake / result reuse intake decode, single compression output verification, batch import decode, batch Source/Winner hashing and the smart-delivery copy now run in `asyncio.to_thread`. A same-plan execute guard (`SMART_DELIVERY_IN_PROGRESS`, 409) replaces the accidental serialisation the blocking copy used to give. Output Center snapshot and plan building stay on the loop on purpose (they rebuild shared in-memory indexes, including batch bindings, that other handlers read); the first preflight still hashes its files on the loop.
- Duplicate work: compression output was fully decoded and hashed twice back to back; now once, after the metadata-written check. Batch items verified the Source three times before encoding; `BatchJob.checked_source()` verifies once per job start, while the post-encode and post-publication re-checks stay. The just-verified private Winner and a freshly published target (already re-read by the publisher) are no longer hashed again. Smart-delivery plans reuse a file hash while path/size/mtime/inode are unchanged (bounded to 512 entries); the delivery copy still verifies real bytes against the registered SHA, covered by a same-size, same-mtime tamper test.
- Preflight with an unknown `result_id` no longer writes a persistent `delivery_eligibility` fact; only a registered Result is marked ineligible.
- Single-Result delivery from `SmartDeliveryPage` and `TaskDetailPage` now sends an idempotency key through the shared `executeSingleResultDelivery` (`src/batchDelivery.js`). A lost response is confirmed through `/api/smart-delivery/requests/{key}` instead of resubmitting; a definite failure rotates the key. Multi-item delivery is unchanged (the server scopes keys to one Result).
- Tests: 2 backend and 2 frontend added; one source assertion in `test_smart_delivery_ui.mjs` updated from the inline execute call to the helper. Frontend build checked into a scratch directory; `dist/` was not rebuilt. Not run in the desktop app; restart the backend and rebuild the frontend to use it. No Git write.

## 2026-10-29 - Image delivery P0 fixes: batch dispatcher, interrupted delivery requests, preflight stat

- Batch compression dispatcher (`backend/batch_compression_api.py`): a worker that failed outside its own recovery was re-raised by `dispatch()` before it was removed from `active`, so every later dispatcher run died at once and remaining items stayed PROCESSING until a backend restart (reproduced). Finished tasks are now removed first; a failure is logged, the batch is paused and a PROCESSING item returns to QUEUED with its saved receipt, so resuming continues without regenerating a Winner.
- Smart delivery execute (`backend/image_compression_api.py`): with an idempotency key, any exception after the PROCESSING request fact was written left it PROCESSING forever, so the same key could only replay "processing". Execution is now wrapped: verified copies with failed registration settle as COMPLETED with the real response; nothing copied settles FAILED_DEFINITE (409, retry with a new key works); a copy without a response settles FAILED_UNCONFIRMED. If the registry rejects the settle write, the in-process outcome is preferred. PROCESSING facts now carry `server_session_id`; one from another backend session older than 10 minutes is reported `SMART_DELIVERY_OUTCOME_UNCONFIRMED` instead of "processing". Response data is built before registry writes (no content change).
- Preflight: the earlier review overstated this one — a deleted file already returns 404 `OUTPUT_ITEM_MISSING`. Only a locked/permission-denied file or a race after lookup raised 500 from `stat()`; it is now a `DELIVERY_SOURCE_UNREADABLE` blocking issue.
- Tests: 1 dispatcher test (`test_a06_batch_stability.py`) and 4 delivery tests (`test_smart_delivery_api.py`) added. Not run in the desktop app; the running backend must be restarted to use the fix. No Git write.

## 2026-10-28 - V0.6.1-dev 4K SR route v3: region-aware strength and tiny-text stroke control

- Product-owner closing requests: soften hair/skin/high-contrast contours without losing clarity; control tiny-text edges separately for stroke continuity without emphasising source jaggies. `four_k_v1.py` now builds source-measured maps (`_structure_maps`): flat areas (5×5 std) get SR high-frequency ×0.45 and fine lift 0.15; hard contours (3×3 range) get a 0.30·tanh soft cap on SR high-frequency and lift 0.40; tiny strokes (5×5 black/top-hat >0.20 in dense 7×7 clusters) are smoothed σ0.6 then re-sharpened with a σ1.6 unsharp bounded to the local 5×5 range, with lift off and back-projection residual smoothed σ1.0 there. Contract `fidelity_fusion` lists the new parameters.
- Nine samples (eight golden + reported poster) v2→v3: flat-area grain −13% to −46%, high-contrast detail gain over LANCZOS kept at 77–95%, source-consistency PSNR still above LANCZOS on all (43.5–67.5 dB), color shift unchanged. Visual: hair wire highlights and SR forehead crosshatch reduced; "锦江流韵" strokes continuous and closer to source glyphs. Rejected: hard cap 0.10 with a loose text mask (lost half the detail gain).
- `process_4k_v1_image` is pixel-identical to the prototype on S03/S07/YR (71.9–78.8s); `tests/image_processing_routing` 129/129. Report and crops in `artifacts/4k_v2_testset/` (`evidence/v3_*.png`). Not yet run through the desktop UI; the running backend must be restarted to use v3. Not committed.

## 2026-10-28 - V0.6.1-dev 4K SR route v2: back-projection consistency after golden-sample test

- Ran the new 4K route on the eight stage-1 golden samples (S01–S08). Found a real regression in v1: Real-ESRGAN altered legible small Chinese glyphs (S07 "锦江流韵 / 烟火日常"). Added `_back_project` (4 iterations, INTER_AREA down / INTER_LINEAR residual up, no blur) after `_fuse_detail`, contract key `fidelity_fusion.back_projection_iterations=4`. Strokes return to source glyph structure while keeping SR sharpness.
- Golden metrics v1→v2: source-consistency PSNR +15–20 dB on all eight (49–64 dB, above LANCZOS), overshoot reduced on 7/8, sharpness −10% but still 8–16× LANCZOS, detail beyond source unchanged, color shift ≤0.16/255. Rejected alternatives: consistency gating with base high-frequency gain (white halos), gating with toggle edge steepening (jagged strokes, icon rims), blurred back-projection residual (weaker glyph correction). Known trade-offs: heavily compressed JPG noise (S04) is kept, not denoised; illegible source text (S05 AI-garbled glyphs) is sharpened as-is.
- `process_4k_v1_image` output is pixel-identical to the prototype (S05, S07); `tests/image_processing_routing` 129/129. Report and evidence crops: `artifacts/4k_v2_testset/4K_V2_GOLDEN_TEST_REPORT.md`, `artifacts/4k_v2_testset/evidence/`. Backend restart is required for the running service to use v2. No Git write.

## 2026-10-28 - V0.6.1-dev 4K route upgraded to SR detail enhancement with source-fidelity fusion

- Product-owner decision (2026-10-28) supersedes the frozen LANCZOS-only 4K V1 route and the Stage-2 "route B adoption NO" closure. Contract `4k_v1_contract_2.0`, route `REALESRGAN_X4PLUS_FIDELITY_FUSION`, boundary `SR_DETAIL_ENHANCEMENT_WITH_SOURCE_FIDELITY_GUARD`, completed conclusion `DETAIL_ENHANCEMENT_COMPLETED`. Request contract, target long edge 3840, aspect/crop/stretch/padding policy, output directory, naming, publish/metadata gates and the already-4K no-op are unchanged.
- Pipeline: bundled realesrgan-ncnn-vulkan `realesrgan-x4plus` native x4 → INTER_AREA to target; low frequencies (Gaussian σ=2) taken from the LANCZOS upscale of the original (no tone/color drift), SR high frequencies on top, 0.35 of the original texture the SR flattened restored (avoids plastic food/fabric/skin), then a 0.6 fine-scale luma lift clamped to the local 3×3 range ±0.01 (no halos). Alpha is LANCZOS from the original. SR progress streams into task progress 45–75. SR missing/failure fails the task (`SR_ENGINE_UNAVAILABLE` / `SR_ENGINE_FAILED`); no silent LANCZOS fallback. 4K SSE watch window raised 180s→1800s for SR runtime.
- Reported "output only 1536×2048": the stored formal output for the reported image is 2880×3840 (source 1086×1448); the 1536×2048 copy came from attachment downscaling outside the engine, not from the 4K route.
- Real run on that source (formal-structure scratch root): 64s, 2880×3840, pixel-identical across two runs, Laplacian variance 8.6→78.2, detail beyond source Nyquist 0.56→1.27, global color shift ≤0.02/255, PNG 6.6MB→11.3MB. Visual crops: small Chinese title/slogan strokes crisp, face/hair sharper, knit ribs separated, bowl pattern lines clean, food texture kept. `tests/image_processing_routing` 129/129 passed (contract/product-loop tests updated for the new route and streamed progress). Frontend validator/copy updated for the new route. No Git write.
- In-app verification: production frontend rebuilt; an isolated backend from current source (127.0.0.1:8797, formal root `D:\影界文件`) ran the real 4K UI flow (mode select → upload → 开始处理). Task completed in 68.9s, Result registered, output `输出/4K画质增强/yangrou_paomo_poster_影界4K_261028.png` 2880×3840, pixel-identical to the engine run; compare/summary page showed 1086×1448 → 2880×3840 and the new copy; `validateQualityReport` accepted the real task report. Found and fixed: the UI progress bar used SSE event count (`index/total`) and jumped to 99% once SR emitted progress events — `streamTask` now prefers the stream's real `task_progress`. Also replaced the stale "高质量尺寸调整能力边界" processing-center subtitle and the one frontend test that pinned the old 4K copy; frontend tests 387/387, build passed. The formal 8787 service was not restarted and still runs the old backend; restart it to pick up the new route (dist is already rebuilt). Direct-URL loads of `/task-detail/compare|report` show empty states because task state is in-memory; this is pre-existing and unchanged.

## 2026-10-03 - V0.6.1-dev D61-05 formal desktop acceptance blocked by refresh exit

- Rebuilt the production frontend and normally restarted the shared formal services. The actual EdgeChromium desktop loaded current D61 source and seven matching production asset SHA values, using the unchanged formal root/settings. Actual user A/B upload, reference replacement/removal/reupload and ordinary mode retained Source identity and preview; overwrite remains NOT_REPRODUCED. Existing actual A/B ACCEPT_ORIGINAL negative tasks remained failed without Result after restart.
- Ten consecutive formal desktop color runs passed (five ordinary, five reference): decoded official files, dimensions/SHA, persisted Task/Result Registry identity, Output Center cards, OS open and continuation identity. A compression and C retouch smoke each passed. Full service and native-window restart preserved all ten Results, open/continuation, original 34 outputs and settings SHA. Actual local feedback ZIPs passed current/no-task/failed-task binding; foreign 4K contexts were rejected with HTTP409. Coordinated current tests passed frontend380/380 without skips, D61 Python70/70, OC57/57 and build.
- STATUS=BLOCKED, NOT_FROZEN. Refreshing a valid color route twice destroyed the native window: frozen packaged_launcher.on_loaded reapplies its initial /processing requirement on every page load. Root cause and native process failures were preserved; no production launcher edit was made. A reviewable minimal patch proposal is evidence only and is not loaded. A separate unmodified real-photo ACCEPT_CORRECTED positive path also remains unverified; existing D01 success samples do not substitute for it. No color/4K algorithm, fallback or Git write occurred. See docs/reports/D61_05_FORMAL_DESKTOP_ACCEPTANCE_20261003.md.

## 2026-10-02 - V0.6.1-dev D61 color stability partial closure

- Real color runs reproduced completed/success responses with ACCEPT_ORIGINAL and no Result, a null-Result React crash, and feedback from the color page binding the previous 4K task. Color completion now requires the existing writer verification and successful shared Registry commit; no-output/save/registration failures expose failed tasks without Result identity. Color UI contains null Result rendering and publishes the current color task context; feedback rejects foreign-feature targets and tasks. No color algorithm, 4K algorithm, alternate output path, retry or fallback was introduced.
- Final related backend 28/28, color/feedback frontend 26/26, adjacent frontend 71/71, feedback 13/13 and production build passed. Ten final-source real Edge color runs produced decodable files with matching dimensions/SHA, Registry identity, Output Center discovery and continuation identity. Local feedback ZIPs were verified for no-task, failed-task and successful-task color contexts.
- STATUS=PARTIAL, NOT_FROZEN. The reported overwrite through the reference-upload button remains NOT_REPRODUCED despite all five source-identity operations passing. Full fixes were tested on isolated real services; the shared formal service was not restarted while owned by S-line validation. Formal desktop acceptance and other intermittent hangs remain UNKNOWN. Existing dirty work and concurrent S-line changes were preserved; no Git write occurred. See docs/reports/D61_STABILITY_FIX_20261002.md.

## 2026-10-02 - V0.6.1-dev S61-OC-02 thumbnail persistence and large-image compatibility

- Reproduced omission of a fully validated 180MP PNG, persistent HTTP 200/HIT responses for a corrupt thumbnail cache, card loss when cache descriptors fail, and loss of a registered single Result when its file is missing. Output Center now reads bounded PNG/JPEG/WebP headers without decoding source pixels or changing Pillow's global guard; thumbnail/cache failures are separated from Result availability.
- Thumbnail requests retain the 768px edge and four-request limit, validate bounded cached images, regenerate corrupt cache files atomically, reject resolved cache path escapes, and enforce a local 40MP preview budget. Cache version v2 invalidates previously cached bad responses. Unavailable previews retain real cards and file-state actions; explicit persisted missing Results remain visibly missing, with unavailable file actions. Batch identity, compression/watermark algorithms and the three frozen performance source files remain unchanged.
- Frontend 377/377, related Python 57/57 and production build passed. Eight real format/size cases include full-stream/CRC-validated 100MP and 180MP PNGs; normal thumbnails decode within 768px and transparent PNG alpha remains intact. The real EdgeChromium desktop shell was closed, both isolated services restarted, and a new desktop process loaded the same single/batch thumbnails, large-image fallback and missing Result identity. Real cache faults preserved open-file, open-folder and continuation binding. Cache-presence permission errors are also contained by the preview-only failure boundary.
- Final formal first-12-card cold paint was 931ms, warm reopens 157/377/376ms, page paints 167-189ms, expansion 48ms and refresh 931ms. The list includes explicitly registered missing history (144 cards); first-12 and paged identities remain complete and unique. Seven historical batches / 49 items / 26 successful outputs were rechecked on an audited isolated copy, leaving all 133 original evidence files unchanged. Clearing new single/batch records retained 15 isolated outputs across restart; all 34 original formal outputs and settings SHA were unchanged.
- Final S61-OC-02 status is BLOCKED / NOT_FROZEN despite the completed scoped repair and runtime evidence. During final integrity checks, the parallel `V0.6.1｜D线｜颜色校正` task changed App.jsx feedback wiring after the verified snapshot. Current shared frontend is 379/380: one compression-advice source assertion still requires the former exact feedback-route set. The current shared build and cold/warm gates pass, but paging during parallel activity is slower and not closed out. The App.jsx baseline hash mismatch remains recorded, rather than accepted or rolled back. No D-line code/test was changed to clear that failure. Images above the local preview budget intentionally show `预览不可用`; existing processing eligibility remains authoritative. No installer, packaged executable, full-software startup optimization or Git write was performed. See `docs/reports/S61_OC_02_THUMBNAIL_LARGE_IMAGE_REPORT.md`.

## 2026-10-02 - V0.6.1-dev S61-OC-01R assertion alignment and performance closure

- Classified the sole frontend failure as an obsolete assertion: S61-OC-00 legitimately replaced selection from top-level file cards with selection from single cards plus available batch children. Updated only the existing test's selection-list assertion; retained all checks and all 377 test cases. Production and S61-OC-01 performance source files remain byte-identical.
- Fresh frontend 377/377, related Python 51/51 and production build succeeded. A full formal-runtime restart with a fresh Edge context measured cold visible first-12 cards at 929 ms, warm reopens at 146-401 ms, next-page request-to-paint at 102 ms, expansion at 49 ms and refresh at 931 ms; all identities agreed.
- GET-only runtime checks matched persisted nine-field identity for seven batches / 49 items and verified 26 unique Result files, decoded dimensions, preview bytes and SHA, including cleared batches. Real UI selected 17 successful compression/watermark children and verified the exact detail filename and eligibility request; KEEP_ORIGINAL, failed and canceled rows were not selectable. All 34 original formal output paths/hashes and settings SHA remained unchanged; staging, branch and HEAD were preserved and no Git write occurred.
- S61-OC-01 is PASS_AND_FROZEN for the measured Output Center scope. Full software-launch duration, packaged application and installer remain outside this closure. See `docs/reports/S61_OC_01R_ASSERTION_AND_PERFORMANCE_CLOSEOUT_REPORT.md` and the updated S61-OC-01 report.

## 2026-10-02 - V0.6.1-dev S61-OC-01 Output Center performance measurement

- Reproduced current batch-card cold-load stalls on the formal 8787/5173 development instance; no historical 3887 ms sample was reused. A read-only profile took 89 ms and read current directories once, while Vite's whole-repository watcher stalled its event loop and module/proxy delivery. Excluding runtime/validation directories reduced monitored entries from 11,153 to 1,079.
- Kept S61-OC-00 batch projection, Output Center bindings and processing algorithms byte-identical. Deferred unused page imports in App through existing route slots and made direct `/outputs` startup-mask timing use the navigation clock; retained brand assets, other-route timing and workspace mount conditions.
- Two final full restarts with fresh Edge contexts measured visible first-12 cards at 938/926 ms and six warm reopens at 185-447 ms; next-page request-to-paint was 100 ms, expand 44-47 ms, refresh 921/929 ms. Launcher-to-ready separately took 8.26/7.94 s; these results do not claim full application launch within 1 s or packaged-application performance.
- Real seven-case compression/watermark regression covered 49 items and 26 decoded, SHA-verified successful outputs, KEEP_ORIGINAL, failure, cancellation, clear, continuation, refresh and restart. Final UI checks decoded 18 successful batch thumbnails and verified exact continued WebP Result bytes. All 34 pre-existing formal output hashes and settings stayed unchanged. An initial isolation-default mistake created two task-owned test files in the formal directory; verified files were preserved outside it and the original formal file set restored before the corrected isolated matrix.
- Status remains BLOCKED / not frozen: 51 focused Python checks and the production build passed; expanded frontend checks are 376/377, with one pre-existing source-regex assertion incompatible with the frozen batch selection path. No Git write occurred. Evidence, timing boundaries, failed attempts and remaining risk are recorded in `docs/reports/S61_OC_01_OUTPUT_CENTER_PERFORMANCE_REPORT.md`.

## 2026-09-21 - V0.6.1-dev S61-OC-00 batch results and Output Center binding

- Reproduced file-based pagination splitting batches and omitting KEEP_ORIGINAL/failed/canceled items, and watermark parent-Task deletion losing nested Result lookup while leaving the files intact. Added the shared `HDDE_BATCH_RESULTS_V1` view using explicit persisted Batch/Item/Source/Task/Result identities; filenames and timestamps never establish membership.
- Persisted compression item outcomes and unique watermark child Tasks, retained real Result references when clearing Tasks, joined exact completed compression facts over stale snapshots, and validated child path/SHA/Task/Result bindings before enabling actions. Non-success items have no Result, output path or output SHA. WebP Result metadata/file access now supports continued compression without widening other processors' format contracts.
- Output Center now pages one card per batch, expands every item, displays compression counts/bytes, supports per-success previews/open/continue, and clears display records without deleting outputs. Watermark cancellation persists unstarted canceled items. Existing single-image cards and processing algorithms are unchanged.
- Validation: 87 directly related Python tests and 53 frontend checks passed, plus production build and compilation. Real 3/10-image mixed-format compression and 3/10-image watermark matrices covered success, KEEP_ORIGINAL, failure and cancellation. Refresh, backend/frontend restart, and a real EdgeChromium desktop close/reopen preserved identities and hashes. The main 8787/5173 instance was restarted and verified; all 30 pre-existing formal output hashes and settings stayed unchanged. Two additional reference-color lifecycle tests fail identically on captured pre-change code and remain outside this stage. See `docs/reports/S61_OC_00_BATCH_OUTPUT_REPORT.md` for evidence and scope.

## 2026-09-21 - V0.6.1-dev A61-06 smart compression and preserve-format split

- Split the target-format contract into default `SMART_COMPRESSION`, explicit `PRESERVE_FORMAT`, and the existing manual JPG/PNG/WebP targets. Smart mode reuses the established PNG candidate, JPEG search, quality gate, Winner and `KEEP_ORIGINAL` paths: only opaque PNG compares PNG and JPEG; JPEG, transparent PNG and WebP remain on their source-format route. Quality thresholds, JPEG search policy and encoding parameters are unchanged.
- Single and batch requests now share the same target normalization and result facts. The UI exposes the five required choices and exact helper text, and a smart PNG-to-JPG result visibly reports the format transition, before/after bytes, saving percentage and a muted decision explanation. A61-05 conversion advice remains available under the explicit preserve-format mode and still requires a separate user submission.
- Focused Python checks pass 30/30, expanded Result/Output Center/Smart Delivery checks pass 129/129, large-search regression passes 11/11, the frontend suite passes 377/377, and the production build passes. Isolated real runtime and Chromium validation produced a 2,173,999-byte opaque PNG to 293,062-byte JPEG result (86.52% smaller) versus a 2,065,027-byte preserve-format PNG (5.01% smaller), completed single and batch Smart Delivery with matching Winner/Result/Delivery SHA values, loaded Output Center thumbnails/previews, and retained JPG/WebP/transparent-PNG format boundaries without changing source SHA values.

## 2026-09-14 - V0.6.1-dev C61 retouch quality-equivalent performance repair

- Added phase-level production timings and a repeatable 1080P/3K-4K/12MP/24MP benchmark. The real bottleneck was the Candidate-Only compositor: full-image Lab conversion plus up to 2,000 diffusion iterations made a 3K-4K large selection spend 128.198 s in composition while LaMa inference stayed near 2.55 s. Cold ONNX Session creation remains a separate one-time cost of roughly 7.4-8.2 s; warm calls reuse the same Session.
- Kept the exact user Mask as the only write boundary and the neural model input. Candidate composition is now component-local, while large harmonization bands use a bounded OpenCV correction-field solve instead of the Python-driven iterative diffusion. The existing small-band solver remains unchanged. Protected S05/S06/S07 outputs are byte-identical to the prior production results, and all measured outputs preserve non-Mask pixels exactly.
- Added conservative `LOCAL` / `MULTI_LOCAL` / `FULL` region planning. Only disconnected non-overlapping context windows use serial multi-ROI inference, and all regions reuse one adapter and ONNX Session. No morphological Mask normalization was added because the current round-cap brush plus backend threshold has no reproduced fragmentation or hole defect.
- Focused validation passes: Python 38/38, frontend local-retouch 25/25, Python compilation and Vite production build. A real isolated Chromium flow completed rectangle repair, continued with brush repair, compared, confirmed and saved a 1086x1448 PNG Result; all relevant HTTP requests returned 200 and Console had zero errors/warnings. Four continuous real repairs kept outside-Mask delta at zero with no continued RSS rise. No formal-directory or Git write was performed.

## 2026-09-14 - V0.6.1-dev A61-01/A61-02/A61-03 target formats and compression

- Replaced cross-format AUTO semantics with one `SYSTEM_AUTO` contract shared by single and batch compression: JPEG remains JPEG, PNG remains PNG and WebP remains WebP. Each route uses only its source-format compression family and retains the existing Winner or `KEEP_ORIGINAL` decision when no smaller qualified file exists.
- Added explicit JPG, PNG and WebP targets to both entry points. Cross-format conversion occurs only after a user selection; lossless PNG/WebP outputs receive persisted-file pixel, alpha, metadata and identity verification. Transparent PNG/WebP converted to JPG is deterministically composited on white and reported in the result evidence.
- Kept the target select as the primary field and placed its dynamic, muted helper directly below it. The four visible options are `系统自动（默认）`, `JPG`, `PNG` and `WebP`; the old PNG/JPG automatic-comparison copy is no longer in the current UI.
- Added an explicit JPG target to single-image delivery optimization and static WebP intake. Both reuse the existing JPEG search, quality gate and unique Winner publication. PNG/WebP conversion keeps a valid JPEG even when it is larger, with actual disk sizes and a clear no-size-benefit message; JPG compression retains the existing KEEP_ORIGINAL rule. Real transparency and unsupported animation fail explicitly.
- Reproduced the ordinary-search 4 MP analysis-bound failure on a 3840x2160 JPEG: every JPEG candidate was rejected and the source was kept. The ordinary search now uses the existing full-resolution metric implementation and final persisted-file gate without changing thresholds or quality search settings.
- Reused the decoded RGB source across candidate gates and avoided JPEG pixel decoding for metadata-only reads. Metadata writes still verify decoded pixels, and final publication still reopens and verifies files. In fixed-route sequential comparisons, 9 samples took 57.130 s before versus 47.341 s after (17.13% less); a 3-sample repeat improved 14.54% in aggregate, with one sample improving only 2.07%. Output SHA, quality results and candidate/encode/write counts were identical. Source decodes observed for the 8 PNG/JPEG samples fell from 289 to 120; WebP decode counting is not covered by that probe.
- Batch WebP conversions retain the target format in their existing verification receipt, including recovery after a lost final batch save and retained Result. Focused core/API/metadata/batch/frontend tests, production build, real browser single-image and batch pause/resume/cancel paths passed. Disk SHA, sizes, ratios, output-center identity and 100% image crops were checked in isolated task output. The 4K/24 MP benchmark inputs are disclosed derivatives, not native camera-resolution samples. No dependency, version, formal settings or Git state change was made.
- A61-03-01 extended the shared image-file contract used by Result enumeration, output-center metadata, previews, thumbnails and Smart Delivery to WebP (`.webp`, `image/webp`) without changing compression routing or quality decisions. Focused Python tests and a new isolated real browser run passed for single WebP plus a JPG/PNG/WebP batch; WebP and PNG Result copies were visible, previewable and delivered with matching source/delivery SHA values, while the JPEG sample retained the existing `KEEP_ORIGINAL` outcome.

## 2026-09-13 - V0.6.1-dev system settings restore-default directory

- Added a secondary `恢复默认` action beside the existing directory controls. The backend exposes and restores the existing authoritative formal root instead of duplicating a Windows path in the frontend; the action reuses current path safety, directory creation, writability and persistence contracts, and becomes disabled when the configured root already equals the default.
- Restore derives all saved output settings from the existing default root and directory constants, does not delete or migrate the previous custom directory, and skips the settings write when already at default. Focused frontend/backend tests cover authority, persistence, repeated no-op, old-file preservation and a post-restart new Task using the restored root.
- Isolated current-code Chromium verified select custom directory, recheck, restore, refresh and full backend restart with the expected `D:\影界文件` / `D:\影界文件\输出` display and zero Console errors. The repository settings file and custom-directory sentinel remained byte-identical; no Git write was performed.

## 2026-09-12 - V0.6.0 W60-03 Windows internal-test installer

- Reused the frozen W60-02 onedir application in the existing Inno Setup path and produced a per-user `影界 HDDE` installer. The installer validates an existing WebView2 Runtime or runs the embedded Microsoft-signed Evergreen bootstrapper, while preserving the development/internal-test version identity and leaving code signing unconfigured.
- Added a fail-closed Setup-content gate that independently extracts the finished installer, binds all 336 application files to the source app-tree hashes, permits only the exact Microsoft bootstrapper as the additional payload, and rejects missing, mismatched, unknown, user-data, cache, log, Result, Registry, feedback, test-output and personal-path content.
- Build `W60-03-01a089c2b` passed production/PyInstaller, app-tree and extracted-installer gates. Real install over the legitimate V0.5.9 baseline, installed-path launch, same-version overwrite, formal uninstall and reinstall all passed; the formal user-data and LocalAppData state fingerprints stayed unchanged. An isolated installed-app image resize produced a decodable 960x710 JPEG without changing the source, opening a system browser, leaving a listener or orphan process. No Git write was performed.

## 2026-09-10 - V0.6.0 W60-02 minimum Windows desktop executable

- Added a Windows pywebview/EdgeChromium shell that owns a loopback-only FastAPI server on an OS-selected port, serves the production React bundle at `/processing`, prevents a concurrent second instance, and shuts down its server after the desktop window closes. Packaged logs and WebView2 data live under LocalAppData rather than the install directory.
- Replaced broad package inclusion with an exact program-resource allowlist and a fail-closed app-tree scanner. Build `W60-02-01a089c2c` contains 336 files (426,703,480 bytes); the independent re-scan found zero forbidden paths, non-allowlisted images, loose bytecode, personal/formal path strings, or package-data errors.
- The exact packaged `影界 HDDE.exe` passed two isolated real launches on dynamic ports 6588 and 34532 with EdgeChromium, `/processing`, no system-browser process, standard window-close shutdown, zero remaining listeners/WebView2 children, and successful concurrent-instance rejection. The readable 2,050-file formal-data scope kept the same total size and metadata hash before and after; three pre-existing ACL-denied candidate directories remained outside direct enumeration. No Git write was performed.

## 2026-09-10 - V0.6.0 S60-EDIT-03R continuation semantics and real multi-round closure

- Output Center continuation keeps the fixed five-processor order while separating processing history from current eligibility. Color correction, compression, retouch and watermark remain repeatable after prior processing; enhancement is unavailable only after that enhancement has already completed. The backend-provided reason is displayed unchanged.
- Color `ACCEPT_ORIGINAL` is now a completed decision with no new Result, output or `RESULT_REGISTERED` event. Candidate-producing decisions retain the existing Result contract. Invalid thumbnail cache identities also evict their stale in-memory index entry so subsequent access returns the formal missing-result response.
- Color output settings now derive from the resolved and validated runtime root, including validation runtimes, instead of an unexpanded settings field. Focused Python tests pass 127/127, the full frontend suite passes 368/368, Python compilation and the production build pass.
- An isolated real chain completed compression -> LaMa retouch -> compression -> watermark with unique Task/Result/output identities, preserved source SHA, restart recovery and repeat color/enhancement policy checks. Clean Chromium verified no-reupload color and retouch entrances, explicit no-new-Result UI for `ACCEPT_ORIGINAL`, zero Console errors and no failed relevant requests. An early validation output-setting mistake created three task-owned compression files under the formal output root; all three were identified and removed immediately, with zero remaining task-owned formal files. No Git write was performed.

## 2026-09-09 - V0.6.0 R60-06 orphan Task recovery and stable newest-first display

- Extended the existing startup reconciliation to started, non-terminal `image_compression` facts that have no formal Result. Because compression execution ownership is process-local and has no persisted recovery queue, these facts are terminalized as interrupted failures after a restart; unstarted pending facts remain protected. Status/progress aliases now move together, and compression detail no longer attaches the enhancement-only SSE progress writer.
- The unified Task API remains the only list source and now orders by `created_at DESC, task_id DESC`, including pagination and latest-task fallback. Mixed in-memory `datetime` and persisted ISO-string timestamps are normalized before comparison so cross-feature tasks keep one deterministic order. This changes display order only; queue and executor scheduling are unchanged.
- Focused lifecycle, restart, active-protection, deletion, stable-pagination and frontend tests pass; the production build and Python compilation pass. Formal runtime and real-browser evidence are recorded separately in the task closeout. No Git write was performed.

## 2026-09-09 - V0.6.0 S60-01/S60-02/S60-03 progressive lists and persistent clear

- Moved Output Center pagination ahead of Result/Delivery/card hydration: a shallow header-only index now applies global category, search and time ordering, then hydrates only the selected page. The UI requests 12 items first and follows with explicit 32-item pages; thumbnail cache, four-request limit, original-on-demand behavior and all existing Result/Delivery/action contracts remain unchanged.
- Added compatible pagination to the shared Task list. Processing Center restores 24 Task facts first and then 50-item pages, cancels stale development-mode requests, and reloads the authoritative source after clear. Current/history clear continues to delete only supported Task facts while preserving retained Result, Delivery and output files.
- The old formal 266-output endpoint measured 3559.84-3862.45 ms for `limit=12` (median 3753.99 ms). The patched code, run read-only against the same formal files and 494 registry facts, measured 194.43 ms cold and 182.07 ms warm median with the formal registry unchanged. An isolated 120-output runtime measured 791.16/115.84 ms cold/warm; the paged Task API measured 50.27 ms cold and 12.32 ms warm median for the first 24 of 494 facts, versus the old formal full-list request timing out after 30 seconds.
- Focused Python tests pass 16/16 and focused frontend tests pass 70/70; Python compilation and the production build pass. Real Chromium confirmed 12 initial cards, four initial thumbnails, no original preview request, thumbnail concurrency 4, paged completion to 120 items, Task pages 24+50, current 5/history 60 UI clear persistence after refresh, 120 preserved outputs and zero Console errors. Evidence is under `output/playwright/`. The already-running formal 5173/8787 chain was not stopped; therefore its existing Python process still requires a later normal product restart to load the backend patch. No Git write was performed.

## 2026-09-09 - V0.6.0 A-line batch Delivery UNKNOWN closeout

- Tightened only the batch Delivery client outcome classifier: an execute or confirmation error without a trustworthy business code is now `UNKNOWN`, including malformed/truncated HTTP 200 JSON, HTTP 200 without `data`, network loss and HTTP 408 without a business code. The original Result and idempotency key remain persisted and refresh recovery confirms the existing request.
- Existing definite integrity failures remain unchanged: `RESULT_IDENTITY_MISMATCH`, `RESULT_NOT_DELIVERABLE`, `RESULT_ARTIFACT_MISSING` and equivalent registered business failures stay `FAILED_DEFINITE`, invalidate eligibility and are removed from selection. Backend Smart Delivery idempotency, compression, Winner, Quality Gate and A06 recovery code were not changed.
- New counterexamples fail before the production change and pass afterward. The focused batch Delivery suite passes 16/16; the full frontend suite, 196 image-compression UI/API Python tests, 59 frozen single-image tests, isolated Vite build, Python compilation and diff checks pass.
- Current isolated Chrome exercised a normal Delivery and a server-successful Delivery whose HTTP 200 body was deliberately truncated. The UI persisted `UNKNOWN`, refresh restored the same key, and an explicit same-key execute replay returned the original Delivery with `idempotent_replay=true`. The target Result has one Delivery record and registered Winner/actual Winner/Delivery SHA256 values are identical. Output Center shows both exact Results and the clean browser chain has zero Console errors. Evidence: `output/playwright/a-line-final-fix-20260909/`. No Git write was performed.

## 2026-09-08 - V0.6.0 A06-D01 batch preview, selection and delivery UI

- Added 56px Result thumbnails with the existing Output Center preview, exact-Result eligibility, per-item selection/select-all, and a batch delivery action that runs the existing Smart Delivery preflight and execute independently for every selected Winner. The batch path creates neither a new Result nor a new Winner, does not retry unknown execute outcomes, and reports per-item failures without stopping later items.
- Tightened the existing batch states without changing A06 recovery or control semantics: waiting has no meaningless progress bar; import displays saved-source count and filename with no premature controls; running/paused expose only valid actions; terminal state presents one before-to-after size relationship and secondary outcome counts.
- Frontend tests pass 352/352 and the relevant Python suites pass 227/227; Vite build, Python compilation and diff checks pass. Isolated real Chromium covered waiting, import, processing, pause, cancellation, completion, thumbnails/modal preview, exact select-all eligibility, dark/light themes and 720px without page-level horizontal overflow.
- A deliberate isolated Winner replacement produced `RESULT_IDENTITY_MISMATCH`: that item created no Delivery while the next selected Result completed, with registered Result SHA = current Winner SHA = Delivery SHA. Current Output Center showed the exact Results and the existing single-item Smart Delivery preflight remained ready. No task-owned identity appeared under `D:\影界文件`; unrelated formal compression/retouch activity and a concurrent Output Center source edit were preserved and not attributed to this task. No Git write was performed.

## 2026-09-08 - V0.6.0 A06-FIX-01 retained Result recovery closure

- When a completed Task has been deleted but its formal Result retained, batch reconciliation now reads the exact reserved Result identity from the existing registry. The saved verification receipt is joined only for validation; current Source/output SHA, quality and unique-Winner checks still apply. GET, cancel, restart and the worker entrance never recreate the deleted Task, operation/trace or Winner. Invalid identities and unbound receipts fail closed.
- Four added regression tests cover retained-Result restart with the private candidate removed, GET/cancel/worker replay prevention, replaced formal bytes and seven identity/receipt rejection cases. Related Python tests pass 228/228; frontend tests 341/341, Vite compilation without replacing shared dist, Python compilation and diff checks pass. No frontend, concurrency policy, single-image algorithm, Quality Gate, metadata or shared registry changes were made.
- Current production runtime with one isolated batch-save fault was exercised through the real browser: Result registration, supported Task deletion, cold restart, batch recovery, Output Center and Smart Delivery. The original operation/trace and Result identity survive; the processing entrance runs once, and the registered Winner and delivered bytes have equal SHA256. Normal five-image cancellation ends with three completed and two canceled; a definite missing-batch 404 clears local identity, enables add/clear and causes no automatic POST.
- Normal recovery/cancel/delivery browser paths have zero Console errors; the deliberate 404 has one expected resource error. The first isolated startup's output-directory probe was denied before any image submission; only dedicated validation settings were corrected. Formal-root before/after hashes match for all 741 files. Evidence: `output/playwright/a06-result-recovery-20260908/`. This closes the recovery repair only, not a global worktree freeze or formal-runtime deployment; no Git writes were performed.

## 2026-09-06 - V0.6.0 A06-FIX-01 cancellation and missing-batch recovery

- Reconcile stale batch rows against existing Task/Result facts and current Source/output SHA before GET/control/restart recovery. Failed batch persistence no longer erases a registered Winner or KEEP_ORIGINAL. Cancel retains completed identities and drains interrupted publication receipts through the existing recovery path.
- A definite GET 404 clears the stale local batch identity and phantom rows, restores add/clear, and displays a recreation prompt. Timeout/500/unknown transport errors retain exact-ID recovery. No automatic resubmission, new registry, concurrency change or frozen single-image change was introduced.
- New counterexamples fail before the patch. Final relevant Python tests pass 210/210 and frontend tests 341/341; Vite compilation without replacing shared dist, Python compilation and diff checks pass. Real isolated Chromium covers normal cancel (1 Winner, 1 kept, 3 canceled), post-Result save-failure cancel (2 Winners, 3 canceled), 404 recovery, and cold restart from a genuinely stale PROCESSING disk snapshot. The recovered Result also completes Smart Delivery with identical registered/source/delivery hashes.
- Eight public Winners match eight Output Center entries and all files decode with correct identities. Normal/recovered browser paths have zero Console errors and uncaught exceptions; the deliberate abort/404 phase has two expected resource errors. Evidence: `output/playwright/a06-fix-01-20260906t025605z/`.
- Concurrent shared-API input-retention/color-preview changes are preserved and attributed by exact in-memory baseline-hash reconstruction. Other formal activity has no Task/Result/Batch overlap with this isolated validation. This repair is not a global worktree freeze or formal-runtime deployment. No Git writes were performed.

## 2026-09-06 - V0.6.0 D60-05F-R1 token and registered-asset lifetimes

- Decoupled expired intake authorization from file retention. Cleanup derives references from the existing shared Task/Result facts, including active inputs, retained Results, source lineage and private reference inputs needed by historical tasks. No additional asset registry, public DTO fields or TTL change was introduced.
- Unreferenced expired uploads still delete only within owned intake leaves under the formal cache root; live duplicate tokens and remaining task references prevent premature deletion. Existing task deletion retains Result facts and releases unused reference inputs. A future explicit collector is still needed for assets whose last reference disappears after token cleanup or whose in-memory token is lost on restart.
- Automatic color tasks now recover terminal facts and hash-checked preview authorization in the same way as reference tasks; expired processing tokens are never revived. Color decisions, the deterministic executor, quality gates, D3, reference matching, metadata and publication are unchanged.
- Validation: 85 focused tests pass, including ten new lifecycle tests. New isolated automatic/reference tasks cover ACCEPT_CORRECTED and ACCEPT_ORIGINAL, actual expiry cleanup, process restart, unchanged registered image hashes, Result previews, Output Center and Result reuse. Real Chromium also reopened both reference triptychs and the automatic comparison, then loaded an existing Result through Output Center into retouch, with no Console errors. This is lifecycle-fix acceptance only, not a D-line freeze or authorization for D60-06.

## 2026-09-06 - V0.6.0 A06 batch compression stability

- Moved A05's browser-only queue to durable batch facts in the existing shared registry, with bounded workers, pause/drain/resume, queued-item cancellation and exact-batch refresh/restart recovery. Each item still invokes the frozen single-image optimizer; prepared receipts, stable Result IDs and verified publication prevent replayed Winners after interruption.
- Corrected only the PNG Alpha summary mapping to the verifier's `alpha_preserved` field. Compression algorithms, quality thresholds, Winner/KEEP_ORIGINAL semantics, identity verification, metadata and Smart Delivery remain unchanged. Existing batch layout gains progress, active filename/elapsed time and minimal pause/resume/cancel controls.
- Real isolated runs completed 10 inputs (8 Winners, 2 kept) and 30 distinct mixed inputs (28 Winners, 2 kept), including pause, refresh and a backend restart while processing. Separate cancellation retained 1 Winner and 1 kept item while canceling 3 queued items; a deliberately invalid image did not prevent later KEEP/Winner completion. Across 69 inputs, 54 public Winners exactly match 54 Output Center entries, with no orphan/duplicate output; real Delivery bytes match the registered Result SHA.
- Workers 1/2/3 took 92.816/79.620/84.092 seconds on the same mixed four-image set with identical outputs; default 2 is bounded by an active-pixel budget. The 30-image backend OS peak working set was 760,844,288 bytes. Large-image latency/low savings remain accepted limitations; the interrupted 30-image wall time is not a throughput benchmark.
- Relevant Python tests pass 203/203 and frontend tests 338/338; Vite compilation without overwriting shared dist, Python compilation and diff checks pass. Evidence is in `output/playwright/a06-20260906-1788649163157/validation.json`. Protected dirty changes from other lines are preserved and shared-API deltas are attributed; no Git writes or formal-app deployment are included.

## 2026-09-06 - V0.6.0 D60-05F reference-color product integration

- Added a separate reference-color request and local mode inside Color Correction, reusing managed intake, the frozen D60-05C decision, D60-02 executor, D3 replay, existing metadata/publish, Result, Output Center and Delivery. The automatic request remains unchanged; no parameter or strength controls were added.
- Added reference-intent target evidence without changing existing protection thresholds. Target remains the principal source; reference provenance contains fingerprints/digest, and the unified public task projection excludes private reference intake fields. The unified Result page displays target/reference/result with the existing review and delivery authority.
- Restart verification exposed a process-local color-task lookup: terminal reference tasks now read their existing shared facts, and preview tokens are regenerated from registered image hashes. No Task is recreated, no decision is rerun, and the Registry schema is unchanged.
- Current isolated real API coverage includes ten fixed pair categories: four accepted corrections and six original-preserved results. The latter are safety outcomes, not matching-effect PASS. PNG/JPEG/DPI output, independent replay, output/Delivery hashes, Result reuse, browser mode/input/loading/result/Delivery flow and default automatic mode were exercised. No new human aesthetic acceptance or D-line freeze is granted; D60-04 final freeze remains a separate prerequisite.

## 2026-09-05 - V0.6.0 A05 basic batch image compression

- Added multi-file selection, item removal/clear, serial per-image progress and a byte-accurate summary inside the existing compression page. The page-session queue calls the frozen intake/run APIs with `DELIVERY_OPTIMIZATION`; no backend scheduler, algorithm, quality gate, identity, metadata or delivery contract was changed.
- Each input remains an independent Task with at most one public Winner. KEEP_ORIGINAL creates neither a copy nor a Result. Failures remain visible and do not stop later images or inflate saved bytes. Completed rows reuse the existing Result-to-Smart-Delivery and Output Center paths.
- Frontend tests pass 330/330 and relevant Python tests pass 192/192, including 12 new orchestration tests and 3 actual-API batch tests. Vite compilation, Python compilation and diff checks pass. Isolated real Chromium completed a 3-image batch (2 Winners, 1 kept) and a 10-image batch (8 Winners, 2 kept), plus an invalid-input isolation case, with zero Console errors. Current artifacts, SHA bindings and verification scope are recorded in `output/playwright/a05-20260905-1788616964123/validation.json`.
- Queue state survives in-app route changes only; pause/restart recovery and advanced concurrency remain outside A05. Existing large-image speed/gain limitations remain unchanged. Separate formal-directory activity was observed and preserved; none of the isolated validation Task IDs or output paths overlaps formal data.

## 2026-09-05 - V0.6.0 A03-RL-P1 stale tests and runtime diagnosis

- Corrected only the three stale test cases in the batch-watermark and processing-center Node suites: persisted batches remain batch-id-only/read-only, Result preview inputs stay valid, and the current runnable queue accepts either a local file or source Result. No production UI, watermark behavior or navigation was changed.
- Added a task-scoped exclusive wall-clock profiler and ran the current production engine on existing Chinese-commercial, realistic-photo and high-frequency 4K sources. PNG generation accounts for 58.62% of measured business time; Source-content decoding 16.34% and remaining metadata work 9.85%. IDAT recompression costs 131.045 seconds across these samples with no improvement over their existing best PNG. Raw phases, profiler overhead, artifact hashes and limits are retained in `output/a03rl_p1_20260905/PROFILE_FINDINGS.md` and its referenced JSON.
- Made no production performance change: dropping non-equivalent PNG search or changing shared validation/metadata reuse requires further safety evidence. The three large Winners and the 1.80 MiB success case remain byte-identical; the latter is still 263,218 bytes with eight encodes. Frontend 318/318, Python 149/149, Vite build, Python compilation and diff checks pass. This closes the test correction and diagnosis scope, not an A03-RL performance freeze.

## 2026-09-05 - V0.6.0 S60-01 Output Center progressive image loading

- Changed the existing Output Center list to remain metadata-first: image dimensions and format are read from headers without pixel decode, while cards use versioned 768-pixel thumbnails generated only when requested under the existing formal `.运行缓存` tree. Source size and nanosecond modification time invalidate stale cache entries; Result, Delivery, preview, source-preview and formal output identities remain unchanged.
- Added viewport-visible priority, a 640-pixel next-viewport prefetch band, stable placeholders, queued offscreen cancellation and a shared four-request concurrency bound. Normal cards no longer request formal originals; comparison still requests the registered result and source on demand.
- Focused Node tests pass 15/15, focused Python `unittest` tests pass 4/4, Python compilation and the production build pass. Isolated real Chromium with more than 100 formal outputs confirmed bounded progressive loading, zero original requests on initial load, incremental loading after scroll, cache HIT, preserved search/sort/selection/delivery/continue/open/compare actions and zero Console errors.

## 2026-09-05 - V0.6.0 C60-RETOUCH-03B candidate post-processing correction

- Captured current production source, masks, ROI, model input/raw tensor, mapped output, color correction, structure recovery, pre-compose candidate and final output for S06/S07. Raw LaMa already simplifies screen/umbrella texture; the subsequent NS inpaint mix independently adds the visible grey smear over S06's phone edge. Color correction is pixel-neutral on both samples.
- Removed only the production NS structure-recovery call. The model, context/resize policy, surface reconstruction, original Mask write contract and Candidate-Only compositor remain unchanged. The legacy helper remains available to reproduce the isolated ablation; production no longer calls it.
- Added known-correct neural edge/diagonal counterexamples (failed before the change, pass afterward) and a non-square mapping check. Local Retouch tests pass 35/35, including RealLaMa 9 and compositor 6; Python compilation and targeted diff checks pass. S05 is byte-identical; S05/S06/S07 retain zero outside-Mask changes and exact candidate cores.
- C-line remains NOT_FROZEN/BLOCKED: removing NS visibly improves S06's contour but does not restore its X-shaped screen texture. Native-sampling and 512-pixel real-context controls also fail that structure gate and are not integrated; S07 remains REVIEW. Evidence is under `output/playwright/c60_retouch_03b_candidate_20260905` and does not establish universal LaMa limitations or delivery readiness.

## 2026-09-04 - V0.6.0 A02-FINAL Result identity freeze

- Updated the stale A01 route test to verify the existing `CompressionPage` mount semantically: the sole `/compression` route still passes `onNavigate`, while the valid `continueResultId` Result-reuse input remains present without adding a navigation entry. Production UI and routing code were not changed.
- Revalidated Result identity against the current production implementation. A dedicated unchanged task completed select, preflight and execute with registered, candidate, copied and delivered SHA256 values identical; a separate dedicated replacement task returned `RESULT_IDENTITY_MISMATCH` from execute and select, disabled delivery, published no Delivery and left no private temporary residue.
- Re-ran the six-class A02 lossless benchmark after the identity changes. All classes retain zero changed pixels and zero maximum channel difference with passing Alpha, ICC, DPI and metadata checks; the current frontend suite passes 310/310, related Python suites pass 122/122 plus 39/39, and the production build and compile checks pass.

## 2026-09-04 - V0.6.0 S60-EDIT-01 continue processing from existing Result

- Added a strict server-side Result-to-Source bridge for completed unified Results. The bridge resolves only the requested Result inside the configured formal root, requires the registered output SHA256 to match the current file, and creates a processor-owned intake copy without exposing or accepting a browser file path.
- Added a restrained Continue Processing action to Output Center. Its live capability list currently exposes only Image Compression and Local Retouch; each route receives an opaque Result identity, creates its normal intake/session, and persists `source_origin`, `source_result_id`, `source_task_id`, `source_feature_key`, and `source_result_sha256` on the new independent Task/Result.
- Added focused backend and frontend regressions for A-to-B-to-C lineage, restart persistence, strict missing/incomplete/damaged/unsafe-source failures, and React StrictMode intake idempotence. Formal Chromium validation completed a real compression-to-retouch continuation chain, preserved every prior Result, decoded every output, and recovered the chain after a cold formal-runtime restart.

## 2026-09-04 - V0.6.0 A02-FIX-01 Result identity and Smart Delivery integrity

- Bound strict-lossless verification to the final candidate's Source and Output SHA256 identities. Candidate selection now re-hashes the current formal file and invalidates mismatched artifacts instead of returning cached pixel, Alpha or metadata evidence.
- Extended the existing Result-to-Output-Center mapping with the registered Output SHA256. Smart Delivery preflight re-hashes current content, while execute streams into a private temporary delivery file, hashes the exact copied bytes against the registered Result identity, and publishes only after the identity matches.
- Added the two required replacement counterexamples plus the unchanged positive chain. Identity mismatch now returns `RESULT_IDENTITY_MISMATCH`, leaves delivery in failed rather than completed state, and publishes neither a formal delivery file nor private temporary residue.

## 2026-09-04 - V0.6.0 A02 strict PNG lossless optimization

- A02 now generates bounded safe PNG variants, verifies persisted Source and candidate files in canonical RGBA, and publishes only the smallest candidate with zero changed pixels and passing Alpha/ICC/DPI/EXIF/current metadata gates.
- The existing A01 three-scheme and Result/Output Center/Smart Delivery contracts remain compatible. The PNG card adds truthful `像素一致` and lossless-gain evidence; all-255 Alpha can be removed only after RGBA identity is proven, while real transparency remains exact.
- Validation: Python 95/95, frontend 304/304, production build and compilation pass; six benchmark classes pass, and isolated Chromium produced two real formal results plus one SHA-identical Smart Delivery copy.

## 2026-09-04 - V0.6.0 A01 fixed delivery options and recommended result

- Upgraded the existing `/compression` surface to “图片交付优化” without adding a top-level route. The new default mode generates fixed PNG lossless, JPG high-quality and JPG balanced candidates from the same source decode, records stable per-candidate facts, marks JPG options inapplicable for real transparency, and uses a deterministic PNG-versus-high-quality recommendation rule.
- Kept the frozen 50-field compression result compatible by binding the recommended or user-selected candidate to the existing single-result fields and Result identity, while exposing the three candidate records through an additive response list. Selection updates the existing Output Center and Smart Delivery binding instead of creating a parallel delivery contract.
- Added a recommendation-first result layout with two alternative cards, factual size/dimension/format/scene fields, explicit selected state, candidate preview switching and the existing delivery/folder actions. Focused backend plus Output Center/Smart Delivery regression passes 91/91, the configured frontend suite passes 303/303, and the production build passes. Isolated 8877/5177 Chromium runs processed a real meeting photo and a Chinese DJI infographic into six decodable formal outputs and confirmed the lossless selection reaches existing Smart Delivery preflight.

## 2026-09-04 - V0.6.0 D60-02 deterministic basic color executor

- Added one serializable, range-bounded `CorrectionParameters` contract for Exposure, Brightness, Contrast, Temperature, Tint, Saturation, Vibrance, Highlights and Shadows, with a fixed execution order and no automatic diagnosis or hidden enhancement.
- Added the managed-sRGB deterministic executor and D3 source-plus-parameter replay identity. Neutral controls remain pixel-exact, non-neutral safe candidates remain `REVIEW_REQUIRED`, and execution safety fails closed on dtype, dimensions, Alpha, non-finite values, channel range, clipping, crushed shadows, damaged highlights or unexpected tone-only color cast.
- Preserved the existing ICC/EXIF/metadata and atomic publication path while carrying only legitimate source DPI through JPEG/PNG encoding; absent DPI is not fabricated. Focused Python and Node regressions pass 167/167. A retained real-image validation covers nine bidirectional/monotonic controls, 13 portrait/commercial/text/cast/tone samples, three deterministic combinations, exact D3 replay and four formal JPEG/PNG/DPI publications; all source hashes remain unchanged.

## 2026-09-03 - V0.5.9 F59-03 batch-watermark final font and parameter controls

- Added the official Source Han Sans CN Medium 2.005R face under the existing SIL OFL 1.1 notice and made the explicit `source_han_sans_cn_medium` identity the new-task default. The historical `source_han_sans` identity remains bound to Regular so restored records do not silently change face.
- Replaced opacity, size and rotation sliders with shared-state scrubbable numeric inputs, and replaced the native color input with a compact swatch/HEX control plus a lightweight Hue and saturation/value popover. The four text parameters retain one 2×2 control system at 1440px and 700px.
- Matched margin controls to the existing renderer: centered axes disable their unused edge margin, while tiled text hides the unused nine-grid/margin controls without changing tile spacing. Result delivery actions now share the same secondary style. Focused Python tests pass 30/30, focused UI tests pass 15/15, the production build passes, and formal UI/API output checks cover Medium, Serif Heavy, tiled text, 32/94 margins, three colors, transparent PNG watermarking, source protection and pixel-identical preview/export.

## 2026-09-03 - V0.5.9 F59-02B batch-watermark text and precision controls

- Reduced the visible text-watermark font choices to the two bundled Source Han faces, made Source Han Sans the new-task/default contract, and normalized explicit legacy default-font identifiers to that bundled font without changing the renderer or font assets.
- Replaced the eight-button preset wall with one editable text field and a compact preset menu, and added self-previewing font choices using the exact bundled faces.
- Added editable HEX, opacity, text-size and rotation fields alongside the existing picker/sliders. Valid edits immediately update the shared preview/batch specification; empty, malformed, fractional-step and out-of-range drafts receive field-level errors instead of silent fallback.

## 2026-09-02 - V0.5.9 F59-01 bundled watermark fonts and text presets

- Bundled the pinned Source Han Sans CN Regular and Source Han Serif CN Heavy faces with their OFL license texts and provenance notice, then added stable `font_id` values to the existing watermark specification and renderer facts. Exact bundled selections now fail explicitly when their asset is unavailable instead of silently changing fonts; missing `font_id` remains compatible with historical tasks through the existing default-font behavior.
- Added a local font selector and eight common text presets to the existing text-watermark controls. Presets only write into the editable text field, while preview, normal text, tiled text and batch export continue to share the same backend Watermark Engine.
- Focused Python tests pass 28/28, focused frontend tests pass 12/12, F-line UI regression passes 28/28 and the production build passes. The formal launcher instance completed three real three-image batches covering both bundled fonts, normal/tiled text and transparent PNG watermarking; decoded preview/export pixels matched exactly and all nine outputs were visible in Output Center.

## 2026-09-03 - V0.5.9 RETOUCH-01 brush selection visual alignment

- Unified the brush visual overlay with the rectangle fill's single `rgba(47, 143, 131, 0.18)` token, removing the brush-only opacity definition while retaining the shared draft/committed rendering path. Brush size, source coordinates, stroke geometry, undo/redo, white Mask generation, repair scope, rectangle selection visuals and backend contracts remain unchanged.

## 2026-09-02 - V0.5.9 RETOUCH-01 selection visual tokens

- Set the editable rectangle's primary Canvas border to the requested `0.25px` without moving its path, handles or source-pixel selection geometry, and removed the legacy `4px` dark under-stroke that still dominated the visible border weight at DPR 1.
- Replaced only the active rectangle's blue visual treatment with border/handle stroke `#2F8F83`, fill `rgba(47, 143, 131, 0.18)` and white handle fill. Existing brush/erase Mask overlay colors, selection state, coordinate conversion, request Mask and backend processing contracts remain unchanged.
- Focused UI tests and the production build pass. Windows Chromium at 100% page scale and DPR 1 confirmed the requested Canvas values, eight handles and stable create/move/resize geometry on horizontal, vertical, product and people images across light and dark image regions; the full real repair path also retained exact visible-selection/request-Mask alignment and zero changed pixels outside the Mask.

## 2026-09-02 - V0.5.9 RETOUCH-01 single rectangle selection editing

- Replaced the rectangle tool's write-once mask operation with one editable source-pixel selection that supports creation, body drag, four-edge and four-corner resize, explicit deletion and recreation while remaining clamped to the displayed image instead of its letterbox area.
- The rendered selection, hit testing and final full-resolution mask now share the same source-coordinate state and deterministic pixel rounding. Window resizing only reprojects the overlay, pointer interruption cancels transient edits, and a successful repair clears the consumed selection without changing the existing backend request, Result, Delivery or Output Center contracts.
- Focused UI geometry and source-contract tests pass 21/21, local-retouch backend regression passes 23/23, and the production build passes. Real Chromium validation covered horizontal PNG, portrait PNG, ultra-wide PNG and a left-edge JPEG: all eight resize directions, four-side clamping, letterbox rejection, interrupted drag, delete/recreate, viewport resize, exact visible-selection-to-request-mask bounds, real repair confined to the requested mask and light/dark rendering. The product authority remains `V0.5.8-dev`; this entry records the V0.5.9 task track only.

## 2026-09-02 - V0.5.8 G-line image diagnosis product removal

- Removed the standalone image-diagnosis navigation, route, page, API registration, task intake/runtime, Engine/Adapter contracts, feature-specific feedback registration, Benchmark maintenance scripts and exclusive tests after confirming there were no runtime consumers outside G-line.
- Preserved the shared Task Registry and added a display-only compatibility boundary for 23 existing formal `image_diagnosis` records: Processing Center labels them as retired, excludes them from runnable/delivery counts and provides no dead route or continuation action. Existing formal records, temporary files and historical Benchmark outputs remain untouched.
- Kept 1080P, 4K, color correction, local retouch, compression, batch watermark, Processing Center and Output Center contracts unchanged; shared regression and formal-runtime evidence are recorded in the task report.

## 2026-09-02 - V0.5.8 metadata user-keyword and contact closure

- Preserved non-HDDE XMP `dc:subject` values while replacing only exact known HDDE product/legacy values with one current `影界 HDDE` tag; user IPTC keywords that merely contain the product name remain untouched.
- Removed the exact HDDE contact email from governed non-Comment XMP/IPTC locations, including individual `dc:subject` values, retained the canonical Comment, and kept Title, Author, ICC, EXIF, Orientation, DPI and the dynamic product-version source unchanged.
- Real-file CASE C/D/E/F/F2/G, the complete metadata-writer suite and the unified no-overwrite output contract pass on the protected working tree; 1080P state propagation, output publication and image algorithms were not changed.

## 2026-09-02 - V0.5.8 result-ready SSE timing correction

- Removed the standard processing stream's premature non-terminal `1080P 输出完成` claim and stop replaying synthetic stage messages as soon as the task reaches `completed` or `failed`; the terminal result event remains gated by the existing task status and formal output pipeline.
- A failing-before/passing-after regression now proves a completed task does not replay the fixed stage delay. Same-image Chrome validation observed no premature completion event, zero new console errors, and a browser-readable result 234 ms after the first sampled completed API state; output safety, metadata, 4K/color contracts, Processing Center tests, and the production build pass without changing publish or image algorithms.

## 2026-09-02 - V0.5.8 COLOR-PREVIEW-01 task-bound result preview paths

- Replaced Color Result's filename-based original preview and restart-ephemeral candidate preview URLs with task-scoped source/result file endpoints backed by the persisted Shared Result Registry paths. Both endpoints resolve only the requested task identity inside the configured formal root; no latest-task fallback or raw Windows path is exposed to the browser.
- Added a cold-restart regression proving exact source/result bytes remain readable from the same task after the in-memory preview registry is gone. Existing task persistence tests pass 11/11, focused Color Result/Delivery API regression passes, and focused Processing Center/Color UI contracts pass 54/54.
- Formal 8787/5173 Playwright validation created a real Color V2 task, decoded both 1672 x 941 previews, moved the comparison slider from 50 to 55, reloaded the Result Page without losing either image, and completed a real Delivery whose saved PNG matches the Result SHA256. Color algorithms, V2 D1 to D2 to D3, Feedback, Timeline and formal V3 integration were unchanged.

## 2026-09-02 - V0.5.8 G-line diagnosis real-world quality gate review

- Corrected the real-world Benchmark's unsupported-ICC expectations and separated the Display P3 safety-boundary case from eligible defect scoring; preserved the existing 16-bit, ICC and Alpha fail-closed behavior.
- Replaced single-metric blur decisions with conservative multi-evidence checks plus a low-light insufficient-evidence branch, and stopped low-severity resolution facts from automatically recommending 1080P processing.
- Focused Python tests pass 17/17, focused Node route/recovery tests pass 6/6, Python compilation and the production frontend build pass, and all six controlled 16-bit/ICC/Alpha regression gates pass.
- Real-world R2 results are TN 17/17, TP 1/6 and recommendation 21/24. The G-line remains blocked and not frozen because reliable localized/semantic defect detection is unproven; no formal runtime acceptance or Git write operation was performed.

## 2026-09-02 - V0.5.8 F58-WM-05 batch watermark workspace proportion and result closure

- Bounded the desktop three-column workbench to the visible workspace, gave the file and parameter regions independent scrolling, and made the preview image fill the available stage with `object-fit: contain`; portrait previews now remain complete with only the intended inner padding instead of inheriting height from the parameter/result column.
- Removed the execution area's auto-bottom spacing and fixed responsive Grid row stretching so progress, the single batch action and result remain a compact continuous workflow at both 1440x900 and 1024x768.
- Removed the duplicate `TOTAL / COMPLETED / FAILED` result summary and the redundant processing-center action. The result card now keeps only the truthful completion state, per-file outcomes, one open-folder action and one Output Center action.
- Focused batch-watermark, Output Center and route-transition UI tests pass 24/24, the production build passes, and the formal-launcher Playwright path verifies real text/image previews, partial failure, both completion actions, light/dark themes and zero final-session console errors. Backend, Watermark Engine, output publication, API fields, product version and Git references were unchanged.

## 2026-09-02 - V0.5.8 H-OUTPUT-UI-02 runtime acceptance and image containment

- Real formal-launcher and Playwright acceptance exposed a CSS Grid alignment defect: portrait thumbnails could size themselves beyond the fixed image track, visually extending beneath the filename row and cropping the card image. The output thumbnail now stretches to its assigned track and caps the image at that track so `object-fit: contain` remains effective.
- Added a focused source-contract assertion for the track containment. Output Center tests pass 12/12, 360 viewport-position cases pass, the production build passes, and the configured UI suite is 280/281 with only the independently registered AppShell/BatchWatermarkPage double-`main` regression remaining.
- Real `/outputs` acceptance covered two-column cards, image-only hover open/close, five-item switching, viewport edges, scroll dismissal, click/detail binding, long filenames, search, sorting, delivery entry, light/dark/system themes and horizontal, portrait, PPT-like and non-standard ratios. Backend, Result/Output/Delivery, disk naming and formal-directory contracts were unchanged.

## 2026-09-02 - V0.5.8 COLOR-DELIVERY-02 Feedback and Timeline identity closure

- Removed the compatibility Feedback endpoint's `DEFAULT_TASK_ID` to latest-task fallback. Missing current business identity now fails with `CONTEXT_NOT_RESOLVABLE` instead of guessing a recent task.
- Correlated Delivery and Retry child traces to their exact source task/result identity, retained parent operation/trace provenance, and persisted failed delivery attempts so `DELIVERY_FAILED → DELIVERY_RETRY_STARTED → DELIVERY_SUCCEEDED` remains auditable on the same Result.
- Timeline now distinguishes presence from completeness and requires the full Process/Result/Delivery/Feedback chain before `PASS`; retry failures add an ordered retry-chain requirement. Focused Python tests passed 58/58, focused UI contracts passed 22/22, the production build passed, and real Playwright 4K→color→Delivery→Feedback produced a four-file package with exact color identity, complete Timeline and no 4K log contamination. V2 D1→D2→D3 and `FORMAL_V3_INTEGRATION=NO` remain unchanged.

## 2026-09-02 - V0.5.8 COLOR-DELIVERY-01 Result, Delivery and Feedback identity closure

- Kept Color Core V2 D1→D2→D3 and `REVIEW_REQUIRED` unchanged, but made a verified user confirmation explicitly authorize the current `REVIEW_CANDIDATE` as a Unified Result through `HUMAN_CONFIRMED_REVIEW`; empty formal-result fields no longer resolve to the repository directory, and candidate preview URLs remain separate from formal Result URLs.
- Bound Result-page delivery, retry and Feedback to the exact color `feature/module/operation/trace/task/result/delivery` context. Task-page Feedback now remains disabled until that exact context is loaded, so it cannot fall back to a recent, global or Processing Center task during route-loading races.
- Added `DELIVERY_CREATED` trace coverage and a controlled recoverable-copy-failure regression proving `FAILED → Retry → SUCCEEDED` on the same task/result identity. Color V2/ICC tests, focused API/Feedback/UI tests, production build and a real Playwright color→delivery→feedback plus color→4K→color isolation path passed; V3 was not integrated and no Git write operation was performed.

## 2026-09-02 - V0.5.8 H-OUTPUT-UI-01 output center image browsing

- Reworked the existing two-column output cards into image-first cards with a bounded `contain` preview area, single-line real-filename truncation and one compact metadata line; selection, search, sorting and delivery state remain on their existing sources.
- Added a pointer-only React Portal hover preview with right/left collision handling, viewport clamping, scroll/resize dismissal and no card or Grid reflow. Removed the duplicate persistent image from the right panel and narrowed that panel while preserving its complete real filename, metadata and actions.
- Added focused source-contract and positioning regressions. Output Center tests pass 12/12 and the production build passes; the configured UI suite remains 279/280 because the pre-existing AppShell single-main-landmark test still detects two `<main>` elements outside this task's authorized scope. Backend, Result/Output/Delivery contracts, file names, formal directories and Git references were unchanged.

## 2026-09-01 - V0.5.8 SYS58-04R2 private-candidate commit-window integrity

- Removed `FILE_SHARE_WRITE` from the Windows private-output handle and kept that same exclusive-writer handle open continuously through write, flush/fsync, private validation, no-replace rename and committed-byte verification. An independent process can no longer acquire a write handle during the validated-to-commit window.
- Added SHA256 identity evidence read through the same open handle after commit; the published metadata report now records the validated and committed hashes and requires them to match. Post-commit mismatch handling remains non-destructive and never performs path-based rollback.
- Added real Windows child-process counterexamples for post-validation tampering and writer acquisition before validation, plus an unsupported-platform fail-closed contract. Non-Windows now returns `SAFE_PUBLISH_UNSUPPORTED` instead of relying on an unproven advisory or hard-link fallback. Image algorithms, metadata contents, output naming, UI, product version and Git references were unchanged.

## 2026-09-01 - V0.5.8 SYS58-04R1 color post-publish rollback safety

- Moved the three formal color Result-state invariant checks ahead of exclusive publication and made them path-independent. Once the shared publisher commits a color output, later state, response, or source-integrity exceptions no longer perform path-based deletion or rollback.
- Added focused post-commit counterexamples covering all three former invariant failures and same-path third-party reoccupation. Both require zero `unlink()` calls and byte-identical preservation of the committed or competitor file.

## 2026-09-01 - V0.5.8 SYS58-04 unified metadata no-overwrite publication safety

- Moved 4K, 1080P, color-correction and compression outputs to one private metadata-and-validation stage followed by a same-directory exclusive no-replace publication. Formal targets are no longer published first and then rewritten with `os.replace()`.
- Reused the proven Windows handle-bound `FileRenameInfo` contract with `ReplaceIfExists=false`; occupied targets remain byte-identical, collision retry retains `_02` naming, and metadata or private-validation failure creates no formal target. Non-Windows publication uses atomic hard-link creation and fails instead of falling back to overwrite or partial final-file writes.
- Added deterministic normal, pre-existing target, metadata-window race, double-publisher, metadata/private-validation failure and publish-failure regressions, plus direct 4K, 1080P, color and compression metadata checks. Product version, image algorithms, naming rules, UI, routes, formal-directory selection and Git references were unchanged.

## 2026-09-01 - V0.5.8 unified final-output contract V1

- Unified formal image names for 4K, 1080P, color correction, local retouch, compression and batch watermark as `{original}_影界{功能短名}_{YYMMDD}.{ext}`. Repeated outputs now start at `_02`, never `_01`, and all touched publication paths use exclusive no-replace writes; Smart Delivery defaults to the exact source filename and applies the same `_02` collision rule.
- Added one raw-container metadata writer for PNG, JPEG and WebP. It writes the current product version as `影界 HDDE V0.5.8-dev`, the official three-line contact comment and `影界 HDDE` keyword while preserving source metadata, ICC, decoded pixels and Alpha; existing Author and Copyright are not replaced.
- Kept Task/Result/Delivery, SSE, `final_output_url`, formal-directory routing and processing algorithms unchanged. Focused Python/API/UI tests, production build, isolated real-browser 4K→Output Center→Smart Delivery, byte identity and Windows Explorer visibility checks passed; no Git write operation was performed.

## 2026-09-01 - V0.5.8 system product-version beta badge

- Added an independent `内测版` status badge beside the System Settings product version by reusing the existing HDDE status-pill component and semantic theme tokens.
- Kept `0.5.8-dev` / `V0.5.8-dev` unchanged in the authoritative product-version source and did not add the user-facing status to backend, build, diagnostics or feedback version fields.
- Preserved the SYS58-02 product-information structure, copyright, official email, byte-identical WeChat QR asset, responsive layout and all business capabilities.

## 2026-09-01 - V0.5.8 system product information and official contact

- Reduced System Settings product information to the formal name, unified version, updated copyright and official email, removing the non-global delivery-resolution and output-format rows without leaving hidden placeholders.
- Added the user-supplied 1254×1254 WeChat QR code as a byte-preserved static asset and displayed it at 104×104 with `object-fit: contain`, its original quiet zone, accessible alternative text and the restrained `扫码联系` caption.
- Kept the existing HDDE card system, light/dark theme tokens, formal directory controls, business APIs, image-processing features and Git references unchanged.

## 2026-09-01 - V0.5.7 historical capability-scope truth closure

- Built one version-wide capability matrix and candidate contract from current code, formal routes and focused tests, separating formal, limited, isolated, unproven and deferred capability claims. The current 4K implementation remains proportional Pillow Lanczos size adaptation to a 3840-pixel long edge; real 4K quality gain and commercial color restoration remain not proven.
- Recorded 36 current `4K画质增强` user-observable claims as a product naming decision because the core name exceeds the proven size-adaptation boundary. Confirmed Color Core V2 and UI-05 formal boundaries, the session-bound local-retouch limitation, Task/Result/Delivery fail-closed behavior and formal startup contract.
- Detected that the authoritative repository advanced concurrently to `0.5.8-dev`, so this V0.5.7 document is a historical scope baseline rather than a current Release Candidate freeze. Also recorded two D57 v0.10 source/test drifts against the v0.9 frozen evidence. No runtime, UI, product-version or Git state was changed by this closure task.

## 2026-09-01 - V0.5.8 unified product version and settings truth

- Advanced the single authoritative product version source from `0.5.7-dev` / `V0.5.7-dev` to `0.5.8-dev` / `V0.5.8-dev`; backend runtime information, diagnostics, frontend settings, launch surfaces and build identity continue to consume that source without page-level version literals.
- Removed the misleading global `默认交付分辨率 / 1080P` row from System Settings while retaining the backend `target_resolution` API field, feature-specific 1080P contracts, current output formats, copyright, contact details and the existing card layout.
- Updated only the directly related truth contracts and retained the existing release name, business behavior, formal directories and Git state.

## 2026-09-01 - V0.5.8 F58-WM-04 batch watermark UI/UX closeout

- Kept the established three-region batch-watermark workbench and made only contract-level UI corrections: concise `颜色` / `大小` parameter labels, the frozen `打开文件夹` completion action, and an indeterminate processing progress bar instead of a fabricated fixed 5% value.
- Added polite batch-count/result announcements and a direct color-input label without changing routes, API fields, Watermark Engine behavior, output publication, product version or AppShell structure.
- Extended the focused UI contract test to reject legacy/duplicate completion labels and synthetic progress while preserving the real preview, image/text modes, relative sizing, Output Center action and dedicated formal route.

## 2026-09-01 - V0.5.8 F58-WM-03R2 handle-bound atomic publication closure

- Replaced path-resolved `os.rename` publication with `SetFileInformationByHandle(FileRenameInfo)` on the same Windows handle that created, received, flushed and fsynced the private output. The UTF-16 target buffer is NUL-backed, `ReplaceIfExists` remains false, and occupied targets return a collision while the same handle continues to `_2`/`_3`.
- Added deterministic source-rebinding attacks with zero, one and two occupied formal candidates. After an attacker moves the owned temporary pathname and installs foreign bytes at that name, the formal output SHA256 still equals the bytes written through the current handle; foreign temporary files and occupied formal files remain unchanged, and no owned file remains at the attacker path.
- Retained handle-bound failure deletion, post-publication old-name protection and 24-writer stress coverage. Formal API collisions produced `_9`/`_10` without changing the source or protected `_5`-`_8` outputs. UI, API fields, watermark rendering, product version and Git references were not changed; unverified non-Windows publication remains fail-closed.

## 2026-09-01 - V0.5.8 F58-WM-03R handle-owned temporary-file cleanup closure

- Replaced post-close temporary-path cleanup with a Windows handle-owned lifecycle. Private files are created atomically with `CreateFileW`, kept open through write, flush, fsync and no-replace rename, and marked for deletion on failure through `SetFileInformationByHandle(FileDispositionInfo)` before the owning handle is closed.
- Successful publication now closes only the handle and never touches the released temporary pathname. Failure cleanup targets the open file object rather than a UUID, path, hash, timestamp or ownership flag; unverified non-Windows publication fails closed instead of falling back to path-based deletion.
- Added deterministic attacks that reuse the released temporary pathname after successful publication and immediately after handle-bound failure cleanup. Both preserve the replacement bytes and SHA256, while the formal output remains valid; the existing collision, 24-writer stress, partial-failure, source-hash, Output Center and frontend regressions remain passing. Product version and Git references were not changed.

## 2026-09-01 - V0.5.8 F58-WM-03 private-temp atomic publication closure

- Moved batch-watermark output encoding to a same-directory, per-call UUID private temporary file and completed write, flush and fsync before any formal output name is published.
- Published completed files with an atomic no-replace operation (Windows rename; atomic hard-link publication on non-Windows) and retained `_2`/`_3` collision retry. Failure cleanup now addresses only the current call's private temporary path; formal candidate and published paths are never unlinked, truncated, replaced or overwritten.
- Added adversarial replacement, private-write failure, consecutive collision, successful decode/no-residue and 24-writer same-name filesystem stress regressions. Watermark rendering, API fields, UI, AppShell, formal-root resolution, other output capabilities, product version and Git references remain unchanged.

## 2026-09-01 - V0.5.8 F58-WM-02 concurrent output safety closure

- Replaced the batch-watermark output `exists()` precheck with direct exclusive-create candidate attempts. `FileExistsError` now advances to the next `_2`/`_3` suffix without unlinking, truncating or modifying the occupied file.
- Limited incomplete-file cleanup to a candidate successfully created by the current call before its own write, flush or fsync failure. Added real two-writer concurrency, occupied-name SHA preservation, consecutive-collision, own-partial cleanup and sequential-conflict regressions.
- Watermark rendering, API response fields, UI, AppShell, formal-root resolution, other output capabilities, product version and Git references remain unchanged.

## 2026-09-01 - V0.5.8 F58-WM-01 batch watermark

- Added the formal `批量水印` workflow with a unified `WatermarkSpec`, an isolated Pillow-based overlay engine, real backend preview, per-file batch states, honest full/partial/failed summaries, formal output-root resolution and collision-safe derived naming.
- Added text watermarks (Chinese/English, color, opacity, size, rotation, nine-grid position, margins and automatic tile spacing) and transparent-PNG watermarks (Alpha preservation, opacity, nine-grid position, margins and source-width-relative sizing) without resizing or enhancing the source image.
- Added the first-level AppShell route and production workbench page, connected Output Center discovery, and verified text, tiled-text and PNG-logo batches through the formal launcher and a real browser. Source SHA256 values remained unchanged; PNG pixels outside the overlay stayed exact, while JPEG changes were limited to necessary controlled re-encoding.
- Product version and Git references were not changed. Complex font management, artistic text, image-watermark tiling and folder-import expansion remain outside this frozen first-version scope.

## 2026-09-01 - V0.5.7 D57-COLOR-04 capability-scope closure

- Froze D57-COLOR-04 as `RESEARCH_PROTOTYPE_WITH_UNCLOSED_EVIDENCE_GAPS`: its controlled engineering safety contract is valid, but automatic protected-region coverage, commercial threshold calibration, an independent formal Artifact Validator, current-source-bound real GT results and data-rights evidence remain unproved.
- Preserved the formal Color Core V2 route and explicitly prohibited D57 production adoption, automatic delivery and commercial GO. The 11-record real-source manifest remains unchanged as historical v0.7 execution evidence; it has no GT or rights fields and does not bind the current v0.9 source.
- Defined the nine-condition commercial reopen gate and recorded that isolated D57 research does not itself block V0.5.7 release. No runtime, API, UI, formal output path, image asset, product version or Git reference was changed.

## 2026-09-01 - V0.5.7 UI/UX P1-07 file identity display and search closure

- Removed the frontend-wide legacy retouch-token rewrite from complete real filenames; user text and mixed historical filenames now remain byte-for-byte visible.
- Output Center now displays and searches the API `file_name` basename as file identity while keeping the independent `local_retouch` product label mapped to `瑕疵修复`; Smart Delivery, Task/Result/Delivery, formal directories and disk files remain unchanged.
- Split strict API `file_name` identity from filesystem-path basename and URL parsing. The identity function now preserves `#`, `?` and leading spaces exactly; path and URL inputs use dedicated helpers and direct counterexamples cover each boundary.

## 2026-09-01 - V0.5.7 Smart Delivery retouch provenance-boundary closure

- Bound historical local-retouch suffix normalization to the registered `original_filename`. The backend now preserves `Path(original_filename).stem` byte-for-byte and normalizes a legacy token only when the remaining source stem exactly matches a known HDDE timestamp suffix; missing or unprovable provenance performs `SAFE_NO_REWRITE` and records `PROVENANCE_BOUNDARY=UNAVAILABLE`.
- Removed the Smart Delivery page's second filename display mapper from the new-delivery preview and completion chain. Both states now display the backend-issued `delivery_file_name` directly; no CSS, retouch algorithm, Task/Result/Delivery public contract or output-directory contract changed.
- Real-browser validation completed both the counterexample `客户_影界瑕疵修整_项目.png` through local retouch and delivery, and the preserved historical `normal_chinese_title_影界瑕疵修整_20260901_090958.png` through Smart Delivery conflict handling. User stems stayed unchanged, only the generated legacy suffix was normalized, source/delivery hashes matched, and the browser console had zero errors.
- Reconfirmed the current unavailable-file facts as 2 Results and 3 Deliveries and verified that their two deleted Task records remain absent. The 14 protected historical retouch files retained the same paths, sizes and SHA256 values.

## 2026-09-01 - V0.5.7 historical file truth and defect-repair naming closure

- Retained deleted Task behavior while reconciling preserved Result and Delivery facts against live files at startup. Missing retained files now persist `FILE_UNAVAILABLE`, return a truthful structured error, remain excluded from Output Center actions, and do not restore deleted Tasks.
- Unified the current `local_retouch` user-facing name, feedback label, generated filename and formal output directory as `瑕疵修复` without changing the stable internal identifier, Mask/LaMa behavior, Result contract or Delivery contract. Historical generated filename suffixes are mapped only for display.
- Migrated 14 existing files from `输出/标记修整` to `输出/瑕疵修复` through the existing atomic migration path with no collisions; file count, total size and SHA256 values were unchanged. `瑕疵修整`, `局部修复` and `标记修整` remain read-only path aliases and are not new output targets.

## 2026-09-01 - V0.5.7 UI-05 backend resume authority and transactional recovery

- Replaced frontend-cache authorization with a backend-owned resume authority check that verifies the persisted Task/Result binding, live in-memory Session, working/source/formal assets and hashes. Refresh and deep-link paths query that authority; unknown, missing, expired or mismatched state fails closed to “重新处理”.
- Split resume into idempotent `PREPARE` and `COMMIT` phases. The browser decodes both the stable working image and source image before COMMIT; failed image loads do not consume eligibility. A repeated COMMIT returns idempotent success only while the current backend Resume Authority remains valid and the authorized Session is identical; Task, Result, Session, binding or asset invalidation fails closed instead of replaying historical success.
- Formal-startup Playwright validation covered the normal Result-to-resume flow, refresh, deep link, injected working-image failure and retry, a second independent Result, Delivery bound to the second Result, and backend-restart downgrade. Focused regressions additionally cover valid-authority duplicate COMMIT and Task deletion between the first COMMIT and its retry. Product version, image algorithms, 4K, Color Core V2, D57, formal startup chain and Git refs were unchanged.

## 2026-09-01 - V0.5.7 4K / 1080P naming and output-directory closure

- Unified current user-facing names as `4K画质增强` and `1080P画质` while preserving stable internal identifiers and read-only aliases for historical recommendation actions. The 4K screen still states that the current implementation is a proportional high-quality size adjustment and does not prove real detail reconstruction or quality gain.
- Unified new formal outputs under `<app_data_root>/输出/4K画质增强` and `<app_data_root>/输出/1080P画质`. Standard and safe 1080P modes now share the same formal output and input-cache root; the Output Center reads only the two current contracts. Historical Task/Result/Delivery records are not rewritten and resolve moved legacy paths through the existing read compatibility layer.
- Migrated the two existing files from `4K高清增强` and `1080P标准增强` without overwrite and verified their sizes and SHA256 values after migration. Empty `1080P安全增强` and the retired diagnostic feedback directory were removed. Migration now blocks on different-content name collisions instead of silently renaming them. No image-processing algorithm, Task state, Result contract, Delivery contract, upload flow, CSS, navigation architecture, product version or Git state was changed.

## 2026-09-01 - V0.5.7 UI-05-FIX-AUDIT truthful retouch resume action

- The normal in-app UI-05 path passed, but a real-browser counterexample found that refreshing or deep-linking a registered local-retouch Result discarded the in-memory Workbench context while the Result page still offered “返回调整 / 重新处理”. Clicking it entered an empty Workbench and reported that the formal Result did not belong to the current context.
- Bound the Result action to the exact live retouch task, Result and session held by the mounted Workbench. A matching live context now exposes “返回调整” and preserves the existing resume-adjustment path; a refreshed, deep-linked, stale or mismatched Result exposes “重新处理” and enters a clean import flow instead of claiming that the old Workbench can be restored. Failed resume attempts are retryable after navigation.
- The fail-before browser path now ends in a clean reprocess state, and the same-session browser path still returns to the accumulated working revision. Focused UI tests passed 56/56, the three targeted API/Delivery regressions passed, Vite production build passed, and both browser paths had zero console errors. LaMa, Mask behavior, working-version generation, backend APIs, Task/Result/Delivery records, formal directories, Color Core V2 and the product version were unchanged. UI technical audit is closed; human visual signoff remains pending and release freeze remains NO.

## 2026-08-31 - V0.5.7 D57-COLOR-04 low-Alpha illuminant-authority repair

- The independent read-only audit rejected v0.4 because its binary `Alpha > 1%` analysis domain also supplied unweighted illuminant evidence. A controlled counterexample contained no fully opaque neutral pixel: 240 `Alpha=3/255` neutral-looking pixels contributed only about 2.82 opaque-equivalent pixels visually, yet counted as 240 complete neutral samples, produced `CANDIDATE_READY`, and changed all 400 pixels in an unrelated opaque product region while every recorded safety gate passed.
- Separated transform application authority from illuminant-estimation authority. RGB inputs retain their unprotected analysis domain; RGBA illuminant count, spatial coverage, median, confidence and source-only replay now use only unprotected fully opaque source pixels. Partial-Alpha pixels can still receive the bounded transform after the existing outcome gate, but cannot determine the global illuminant. No candidate pixel, caller-supplied expectation or arbitrary high-Alpha threshold enters the authority path.
- The fail-before low-Alpha regression now blocks with `INSUFFICIENT_DISTRIBUTED_NEUTRAL_EVIDENCE`; all 11 prototype tests, all 94 color-correction tests and all 37 formal color API tests pass. The prototype remains isolated from the formal package and runtime. D57-COLOR-04 remains in progress, its 30-image GO/NO-GO remains `NOT_EVALUABLE_MISSING_REAL_ASSETS`, commercial color restoration remains `NOT_PROVEN`, and the repaired technical gate remains pending independent automatic audit.

## 2026-08-31 - V0.5.7 D57-COLOR-04 Alpha-outcome safety audit repair

- The read-only audit confirmed that v0.3 removed candidate-pixel self-certification, but rejected safety closure for two remaining authority defects. Candidate-versus-replay black/white composites proved only implementation agreement: an eligible warm-cast fixture could change one unsupported partial-Alpha pixel by 9 RGB bytes while recording zero replay residual and retaining `CANDIDATE_READY`. The unproved one-byte replay tolerance also accepted a coherent one-byte partial-Alpha mutation even though both controlled legitimate candidates replayed exactly.
- Split replay integrity from Alpha outcome safety. Candidate pixels must now match the source-only float64 replay byte-for-byte. Alpha outcome authority starts only from source-similar opaque clusters containing at least four local pixels and propagates for at most 12 four-neighbour steps through source-similar pixels whose independently replayed correction field remains within the controlled composite-residual boundary. Unsupported partial-Alpha pixels and discontinuous replay outcomes fail closed; source-to-replay RGB and black/white composite changes are recorded separately from candidate-to-replay integrity.
- The fail-before unsupported-pixel and one-byte synchronized-mutation regressions now pass together with all 10 prototype tests, all 93 color-correction tests and all 37 formal color API tests. The prototype remains isolated from the formal package and runtime. D57-COLOR-04 remains in progress, its 30-image GO/NO-GO remains `NOT_EVALUABLE_MISSING_REAL_ASSETS`, commercial color restoration remains `NOT_PROVEN`, and the repaired technical gate remains pending independent automatic audit.

## 2026-08-31 - V0.5.7 D57-COLOR-04 source-only replay audit repair

- Revoked the preceding isolated white-balance safety-gate closure after automatic audit proved that adjacent partial-Alpha candidate pixels could mutually authorize a coherently corrupted component: synchronized correction vectors produced zero local residual without any candidate-independent color authority.
- Removed local-neighbor support and candidate-to-candidate correction residuals from acceptance. The safety gate now recomputes neutral evidence, bounded gains, source-luminance preservation and blend weights from the source and analysis mask only through a separate float64 path; actual candidates are compared per pixel against that replay, and partial-Alpha RGB fails closed beyond the one-byte quantization boundary. Alpha-weighted black/white composites remain recorded against the independent replay but, because their correction deltas are mathematically equivalent when Alpha is pixel-exact, they are not presented as two independent authorities. No caller-supplied expected image or candidate-derived reference is accepted.
- The fail-before synchronized-component regression now passes together with all 9 prototype tests, all 92 color-correction tests and all 37 formal color API tests. The prototype remains isolated from the formal package and runtime. D57-COLOR-04 remains in progress, its 30-image GO/NO-GO remains `NOT_EVALUABLE_MISSING_REAL_ASSETS`, commercial color restoration remains `NOT_PROVEN`, and independent automatic audit is still required before this technical gate can be treated as closed.

## 2026-08-31 - V0.5.7 D57-COLOR-04 isolated white-balance safety-gate closure

- Closed the three defects found by the read-only audit of the isolated white-balance prototype. Aggregate clipping growth no longer has acceptance authority: every newly clipped shadow or highlight channel is detected against its own source channel and blocks non-compensatorily, even when an old clipped pixel is released elsewhere.
- Added final-uint8 linear-luminance mean/P95/max absolute-error gates and partial-Alpha local-support plus Alpha-weighted black/white-composite continuity gates. Unsupported partial-Alpha pixels, sparse composite fringes, relocated clipping and post-quantization exposure drift fail closed; successful diagnostics explicitly identify their thresholds as controlled engineering boundaries rather than D57-COLOR-02 commercial thresholds.
- The 8 prototype tests, all 91 color-correction tests and all 37 formal color API tests pass. The prototype remains absent from the formal package surface and runtime, and public API, SSE, FinalAction, UI, Settings, formal directories, dependencies, product version and Git refs remain unchanged. D57-COLOR-04 remains an isolated prototype in progress, its 30-image GO/NO-GO remains `NOT_EVALUABLE_MISSING_REAL_ASSETS`, and commercial color restoration remains `NOT_PROVEN`.

## 2026-08-31 - V0.5.7 4K EXIF orientation dimension-planning correction

- Corrected the formal Pillow Lanczos 4K route so EXIF display orientation is applied before source and target dimensions are planned. Previously, an orientation-6 portrait stored as landscape pixels was planned from the raw width and height, then resized after rotation into landscape target dimensions, violating the frozen aspect-ratio contract.
- Strengthened the focused regression after automatic audit: a pixel-level check now starts from four asymmetric JPEG color quadrants and verifies their intended clockwise corner identities at native output coordinates within JPEG decoding tolerance, absence of residual EXIF orientation, 2560x3840 aspect preservation, source SHA256 preservation and successful output verification. This distinguishes real pixel rotation from a dimension-only stretch and detects mirroring or the wrong rotation direction. Existing API, UI, output format, formal directory, PNG encoding, quality-capability boundary, product version and Git refs are unchanged; this remains high-quality size adaptation and does not establish real 4K detail gain.

## 2026-08-31 - V0.5.7 D57-COLOR-04 isolated no-data V3 white-balance prototype

- Recorded the user's explicit decision to continue algorithm engineering without the missing D57-COLOR-02 materials, while preserving the contract boundary that no 30-image GO/NO-GO, formal integration or commercial conclusion is authorized by synthetic evidence.
- Added one isolated white-balance prototype that requires spatially distributed neutral evidence, estimates bounded gains in linear sRGB, preserves source linear luminance, and restores hard protected regions, Alpha-at-or-below-1% hidden RGB and the full Alpha channel byte-for-byte. Unsupported precision, insufficient evidence, negligible casts, failed improvement or clipping growth fail closed; successful candidates remain `ISOLATED_REVIEW_ONLY` and the module is not exported by the formal color package.
- The five prototype tests, all 88 color-correction tests, all 37 formal color API tests and Python compilation pass. D57-COLOR-02 remains incomplete, the D57-COLOR-04 GO/NO-GO remains `NOT_EVALUABLE_MISSING_REAL_ASSETS`, and commercial color restoration remains `NOT_PROVEN`. Public API, SSE, FinalAction, UI, Settings, formal runtime, formal directories, dependencies, product version and Git refs are unchanged.

## 2026-08-31 - V0.5.7 D57-COLOR-03-R11 non-transferable person-region decision instance seal

- Revoked the R10 completion claim after its automatic audit reproduced a full private-credential graft. Two D1 decisions over the same uniform source, with different person boxes but identical public `to_dict()` records, could transfer both the donor region contract and donor binding to a third decision instance; R10 accepted the graft. A structural clone carrying the same public fields and full private credential also reached `CANDIDATE_READY`. Candidate identity V2 could only bind the already-wrong region context downstream and did not repair D1 authorization.
- Replaced the transferable semantic digest with a process-local HMAC whose signed payload includes the exact D1 object identity, full public semantic snapshot and private region contract. Its runtime-only credential also holds a weak owner reference, so a copied credential cannot inherit ownership and a released owner's object ID cannot later be reused to revive it. Region resolution now additionally requires the exact `ColorUsabilityDecision` type. Whole-pair grafts, dataclass copies and structural clones therefore fail closed before pixel execution, while missing contracts retain their existing blocker and the public constructor remains unchanged. The runtime-only fields are excluded from equality and remain absent from Shadow, Replay, API and formal result records.
- Advanced D1/D2/D3/formal implementation versions without changing their schemas or public field structure. The two new fail-before regressions, four focused contract tests, all 83 color-correction tests, all 37 formal color API tests and Python compilation pass. D57-COLOR-03 is technically complete at R11; D57-COLOR-02 remains incomplete, D57-COLOR-04 remains unauthorized and commercial color restoration remains `NOT_PROVEN`. UI, SSE, FinalAction, Settings, formal directories, dependencies, product version and Git refs are unchanged.

## 2026-08-31 - V0.5.7 D57-COLOR-03-R10 person-region seal and audit-evidence closure

- Revoked the R9 completion claim after the read-only audit reproduced a same-source whole-contract graft: the private region digest authenticated only the replacement contract's own dimensions, mode and boxes, not the D1 semantic record that created it. R9 had also introduced exposure-only Lab a/b brand thresholds before D57-COLOR-02 supplied authoritative brand references, while the public audit exposed only `brand_delta_e`; the reported `BRAND_COLOR_PASS` could not be recomputed from its published metric.
- Kept the original public `ColorUsabilityDecision` constructor compatible by making the two runtime guards private non-init fields. D1 now seals each private region contract against the complete public D1 semantic snapshot; missing, damaged, mutated or coherently grafted contracts fail closed before pixel execution. Candidate identity V2 additionally hashes an opaque, source-bound person-region context, without serializing coordinates, region mode or the seal into D1, D2, D3, Shadow, Replay, API or formal Result records.
- Removed the unauthorized exposure-specific brand a/b gate and restored the pre-existing full Delta-E brand protection rule for both routes. Its decision is now directly recomputable from the already published `brand_delta_e`; D01_04 consequently keeps the Original, creates no formal Candidate output and gains no delivery eligibility. D1/D2/D3/formal implementation versions were advanced for traceability without changing schemas or public field structure. Python compilation, all 81 color-correction tests and all 37 formal color API tests pass. D57-COLOR-03 is technically complete at R10; D57-COLOR-02 remains incomplete, D57-COLOR-04 remains unauthorized and commercial color restoration remains `NOT_PROVEN`. UI, SSE, FinalAction, Settings, formal directories, dependencies, product version and Git refs are unchanged.

## 2026-08-31 - V0.5.7 D57-COLOR-03-R9 bound person-region contract

- Revoked the R8 completion claim after the read-only audit found three incompatible meanings for an omitted or empty person-region request: D1 treated `None` as automatic detection and `[]` as explicit none, D2 treated both as automatic detection, and D3 collapsed both to an empty tuple while independently detecting again during trusted replay. The formal runtime therefore did not guarantee that D1 analysis, D2 protection and D3 audit used the same person regions.
- D1 now resolves one private three-state contract (`AUTO`, `EXPLICIT_NONE`, or `EXPLICIT_BOXES`), canonicalizes all retained boxes in source-image coordinates, and binds the contract to source dimensions with an integrity digest. Automatic detection still runs on the bounded D1 analysis image, then maps once to source coordinates; D2, D3 and formal candidate rematerialization only reuse the D1-bound regions. A missing, malformed, altered, mode-mismatched or coordinate-mismatched contract fails closed. No face coordinates, contract mode or digest enter D1, D2, D3, Shadow, Replay or formal result records.
- Correct region reuse exposed an existing exposure-audit mismatch: product regions were judged with total Delta-E even though the exposure executor intentionally changes L*. Exposure candidates now protect brand/product chroma through bounded Lab a/b drift, matching the existing skin policy, while color candidates retain the original full Delta-E gate. The 3 focused R9 regressions, all 26 D3 tests, all 79 color-correction tests, all 37 formal color API tests and Python compilation pass. D57-COLOR-03 is technically complete at R9; D57-COLOR-02 remains incomplete, D57-COLOR-04 remains unauthorized and commercial color restoration remains `NOT_PROVEN`. Public APIs, SSE, FinalAction, UI, Settings, formal directories, dependencies, product version and Git refs are unchanged.

## 2026-08-31 - V0.5.7 D57-COLOR-03-R8 source/analysis person-coordinate closure

- Revoked the R7 completion claim after the read-only audit found that D1 resized large inputs to a longest side of 960 pixels but applied explicit source-image person regions unchanged. D1 could therefore analyze a different person/skin area from D2 and D3 on ordinary commercial-resolution images, while the R7 240x180 fixture never entered the resize path.
- Defined explicit person regions as source-image `(x, y, width, height)` coordinates and mapped a D1-only copy once to the actual analysis width and height with bounded endpoint coverage. Face boxes detected on D1 analysis pixels remain in analysis coordinates and are not scaled again; D2 and D3 continue receiving the unchanged source-coordinate regions. No color, skin or exposure threshold changed.
- A fail-before 1200x800 RGBA regression now verifies the correctly mapped trusted-skin region, hidden-RGB semantic isolation, equal D2 parameters and visible candidates, equal D3 pass state and authority, and the non-rescaled automatic-detection branch. The focused regression, all 24 D3 audit tests, all 77 color-correction tests, all 37 formal color API tests and Python compilation pass. D57-COLOR-03 is technically complete at R8; D57-COLOR-02 remains incomplete, D57-COLOR-04 remains unauthorized and commercial color restoration remains `NOT_PROVEN`. Public API, SSE, FinalAction, UI, Settings, formal directories, dependencies, product version and Git refs are unchanged.

## 2026-08-31 - V0.5.7 D57-COLOR-03-R7 person-region Alpha-domain closure

- Revoked the R6 completion claim after the read-only audit found that D1's canonical person-scene facts and main person mask did not intersect detected or explicit person boxes with the Alpha-greater-than-1-percent validity mask. Low-Alpha RGB inside a person box could therefore change trusted-skin medians and other person facts despite leaving every visible pixel unchanged; the R6 Cross-Affine independent-refit result itself remains valid.
- Restricted both D1 person masks to the valid Alpha analysis domain without changing any color, skin or exposure thresholds. Added one end-to-end RGBA regression with identical visible pixels, Alpha and explicit person regions but different hidden RGB; it binds equality across D1 semantics excluding the source fingerprint, D2 executor parameters and visible candidate pixels, and D3 pass state, authority and final action.
- The 7 focused person/RGBA tests, all 76 color-correction tests and all 37 formal color API tests pass. D57-COLOR-03 is technically complete at R7, while D57-COLOR-02 remains incomplete, D57-COLOR-04 remains unauthorized and commercial color restoration remains `NOT_PROVEN`; no public API, SSE, FinalAction, UI, Settings, formal directory, dependency, product version or Git ref changed.

## 2026-08-31 - V0.5.7 D57-COLOR-03-R6 independent Cross-Affine refit and RGBA analysis domain

- Revoked the R5 completion claim after the read-only audit proved two remaining authority defects: D3 replayed Cross-Affine from the D2-recorded matrix, allowing a coherently damaged matrix and candidate to agree, while hidden or near-transparent RGBA RGB could still influence D2/D3 analysis despite D1 excluding it.
- Unified D1, D2 and D3 on the existing Alpha-greater-than-1-percent analysis domain. Invalid RGB is neutralized before resize or face detection and excluded from white-balance, exposure, protection, target-fit, scoring and audit metrics; fully transparent hidden RGB and all Alpha values remain pixel-exact in the materialized output.
- Replaced Cross-Affine matrix-contract replay with an independent D3 reconstruction of source evidence, targets, deterministic sampling, ridge fit and constrained application. D2 prediction and fit records are now consistency checks only, and coherent matrix-plus-candidate mutation or deterministic D2 fit faults fail closed. Five focused gates, the adapted legacy fault-injection regression, all 75 color-correction tests and all 37 formal color API tests pass. D57-COLOR-03 is technically complete at R6, but D57-COLOR-02 remains incomplete, D57-COLOR-04 remains unauthorized, and commercial color restoration remains `NOT_PROVEN`; no public API, SSE, FinalAction, UI, Settings, formal directory, dependency, product version or Git ref changed.

## 2026-08-31 - V0.5.7 D57-COLOR-03-R5 independent source replay

- Revoked the R4 completion claim after the read-only audit proved that the selected attempt's `candidate_rgb01` and the materialized candidate shared the same executor lineage, so a deterministic executor defect or coherent mutation could corrupt both while retaining reference equality.
- Removed all acceptance authority from D2 attempt pixels. D3 now rebuilds the selected exposure and Safe-WB transform from the bound source, D1 facts and constrained parameters through an independent implementation, and replays Cross-Affine from its bounded matrix contract. Actual person regions are retained only as a non-serialized immutable tuple and are independently checked against the source or explicit audit request; public records do not gain face-coordinate fields.
- Added regressions for synchronized candidate/attempt-array corruption, deterministic D2 executor corruption, and coherent shared-parameter mutation. Python compilation, 19 D3 tests, all 71 color-correction tests and 37 formal color API tests pass. D57-COLOR-02 remains incomplete, D57-COLOR-04 remains unauthorized, commercial color restoration remains `NOT_PROVEN`, and no public API, SSE, UI, Settings, formal directory, dependency, product version or Git ref changed.

## 2026-08-31 - V0.5.7 D57-COLOR-03-R4 trusted transparency reference

- Revoked the R3 completion claim after the read-only audit proved that 16 synchronously corrupted opaque pixels could authorize matching semi-transparent corruption, while a thin nonzero-Alpha bridge could reconnect distant reference areas. The recorded nearest-reference distance did not participate in the R3 decision.
- Bound D3 to the unique selected, passing D2 executor trace instead of deriving authority from the mutable candidate payload. Missing, duplicate or parameter-mismatched traces now fail closed; every visible candidate pixel must match the pre-materialization executor RGB result, and semi-transparent magnitude, joint RGB vector and Alpha-weighted composite continuity are checked independently against that per-pixel reference.
- Retained opaque-component count and bounded Alpha-connectivity facts as diagnostics only, explicitly removed their acceptance authority, and kept legitimate wide Alpha gradients eligible when their pixels match the trusted trace. Added coherent opaque-plus-semi corruption, thin-bridge, disconnected-component, trusted-trace contract and realistic local-gradient regressions. Python compilation, 16 D3 tests, all 68 color-correction tests and 37 formal color API tests pass. D57-COLOR-02 remains incomplete, D57-COLOR-04 remains unauthorized, commercial color restoration remains `NOT_PROVEN`, and no public API, SSE, UI, Settings, formal directory, dependency, product version or Git ref changed.

## 2026-08-25 - V0.5.7 D57-COLOR-03-R3 local joint RGB transparency gate

- Revoked the R2 completion claim after the read-only audit and direct reproduction proved that independent per-channel P01/P99 bounds could authorize an RGB combination never observed on opaque pixels, and that a semi-transparent component with no opaque pixels could borrow reference authority from a separate object. Both cases retained `SIDE_EFFECT_PASS=YES`, `AUTO_PROVEN`, and `ACCEPT_CORRECTED` before this repair.
- Retained the lower-method opaque P99 as a global magnitude precheck, but bound every semi-transparent pixel to the spatially nearest real opaque RGB correction vector inside the same nonzero-Alpha connected component. Each component now requires at least 16 opaque reference pixels; missing component-local evidence fails closed to `NET_GAIN=NEGATIVE`, `ACCEPTANCE_AUTHORITY=NONE`, and `ACCEPT_ORIGINAL`.
- Replaced the duplicated black/white signed-range authority with one Alpha-weighted local composite-continuity gate. Because pixel-exact unchanged Alpha makes black- and white-background correction deltas mathematically identical, both background facts remain observable but no longer masquerade as independent safety evidence.
- Added single-pixel, single-column joint-vector recombination and disconnected-component borrowing regressions while preserving the safe Alpha-gradient path. Python compilation, 13 D3 audit tests, 10 formal color-management tests, and all 65 color-correction tests pass. Color Core V2, D1/D2 candidate parameters, public API/SSE/FinalAction, UI, Settings, formal directories, dependencies, product version, and Git refs remain unchanged; D57-COLOR-02 remains incomplete, D57-COLOR-04 remains unauthorized, and commercial color restoration remains `NOT_PROVEN`.

## 2026-08-24 - V0.5.7 D57-COLOR-03-R2 transparent-edge non-compensatory gate

- Revoked the R1 completion claim after the read-only audit proved that one opaque outlier could raise the global maximum reference and allow a sparse semi-transparent color fringe to retain `SIDE_EFFECT_PASS=YES`, `AUTO_PROVEN`, and `ACCEPT_CORRECTED` despite a 0.269681 black/white composite delta.
- Replaced the global opaque maximum with a lower-method P99 reference requiring at least 16 opaque pixels, plus signed per-channel P01/P99 bounds that reject an equal-magnitude correction moving in the wrong color direction. Semi-transparent RGB and Alpha-scaled black/white composite limits now enter the same non-compensatory side-effect gate; both reproduced bypasses return `NET_GAIN=NEGATIVE`, `ACCEPTANCE_AUTHORITY=NONE`, and `ACCEPT_ORIGINAL`, while the safe Alpha gradient remains auto-accepted.
- Added the sparse-fringe-plus-opaque-outlier regression and retained the full Alpha/hidden-RGB, ICC, metadata, bit-depth, D1/D2/D3, metric-attribution, and formal API coverage. The 21 focused color-management/D3 tests and all 100 related tests pass. White-balance, exposure, skin, Color Core, public API/SSE/FinalAction, UI, Settings, formal directories, dependencies, product version, Git refs, and the Git index remain unchanged; D57-COLOR-04 is still unauthorized and commercial color restoration remains `NOT_PROVEN`.

## 2026-08-24 - V0.5.7 D57-COLOR-03-R1 color-truth and transparent-edge closure

- Closed the three D57-COLOR-03 audit blockers without reopening D57-COLOR-02: conflicting PNG sRGB/gAMA/cHRM or EXIF/Interop color facts now fail closed before D1/D2/D3, create no formal output, and leave the source unchanged.
- Replaced label-based sRGB ICC acceptance with a Pillow ImageCms/LittleCMS semantic-equivalence probe; a profile retaining an sRGB description but carrying mutated colorimetry is rejected.
- Preserved source RGB under fully transparent pixels through D2, added D3 facts for fully and partially transparent pixels plus black/white composites, and added a final encoder guard. The complete related suite passes 99/99 tests. Color Core parameters, public API/SSE/FinalAction, UI, Settings, formal directories, dependencies, product version, Git refs, and the Git index were not changed; D57-COLOR-02 remains incomplete, D57-COLOR-04 remains unauthorized, and commercial color restoration remains `NOT_PROVEN`.

## 2026-08-24 - V0.5.7 E4K-09B runtime-profile evidence truth closure

- Corrected the existing E4K-09B evidence without rerunning the baseline, API path, performance profile, or rejected candidate. The retained 3840×2161, 8,104,186-byte baseline still passes file and decoded-pixel SHA256 verification, but per-run file and decoded-pixel hashes were not retained; direct, E2E, and candidate consistency are therefore execution-time observations that are not independently replayable.
- Preserved the recorded 3,467.291 ms core median, 2,362.902 ms PNG-write median, 3,809.792 ms observable-completion median, and 45.548% candidate observation. Because the baseline drifted during sustained runs and the baseline/candidate blocks were not paired and interleaved, only the exploratory threshold was crossed; the formal speed gate remains `NOT_PROVEN`, with no performance generalization claimed.
- Restricted protection claims to the three recorded metadata-tree digests and explicit single-file content hashes. Complete E4K-09/E4K-09A or other frozen-tree pre/post proof is unavailable and was not reconstructed retroactively. The candidate remains `REJECT_SIZE_BUDGET`, no optimization is accepted, formal runtime/API/UI/version/dependency/model code remains unchanged, and real 4K quality gain remains `NOT_PROVEN`.

## 2026-08-24 - V0.5.7 D57-COLOR-03 color-management foundation

- Kept D57-COLOR-02 incomplete because all 30 source/GT/rights groups remain unavailable, and authorized only the independent D57-COLOR-03 technical foundation; generated color, alpha, profile, and bit-depth fixtures are test vectors rather than commercial evidence, D57-COLOR-04 remains unauthorized, and commercial color restoration remains `NOT_PROVEN`.
- Added one fail-closed formal color-management boundary for single-frame 8-bit RGB/RGBA JPEG and PNG. D1, D2, and D3 now consume the same explicit sRGB/RGB working pixels; valid sRGB ICC inputs use Pillow ImageCms/LittleCMS, untagged supported inputs use an explicit sRGB assumption, and JPEG/PNG outputs embed an sRGB profile that matches their pixels instead of reattaching an unverified source profile or dropping PNG ICC.
- Verified pixel-exact Alpha preservation, RGB/BGR order, normalized orientation, lossless PNG pixels, source hash preservation, and explicit rejection of damaged/non-sRGB profiles, CMYK, animation, and unsupported bit depths. Native 16-bit automatic processing remains `SAFE_BLOCKED` rather than silently quantized. The 9 new foundation tests, 50 frozen D1/D2/D3/metric tests, and 37 formal color API tests pass; no algorithm parameter, public API/SSE/FinalAction, UI, directory, model, training, or product-version change was made.

## 2026-08-24 - V0.5.7 E4K-09A capability truth and runtime baseline closure

- Unified the user-visible 4K wording as `4K尺寸适配` and stated the exact boundary: proportional long-edge adaptation to 3840 pixels does not prove AI super-resolution, real-detail reconstruction, or quality gain. Historical action aliases and the frozen `输出/4K高清增强` directory contract remain compatible and unchanged.
- Added the single-machine, single-bound-sample runtime baseline for the unchanged `PILLOW_LANCZOS_SAFE_RESIZE` route. Three runs produced the same 3840×2161, 8,104,186-byte PNG and identical SHA256; mean elapsed time was 811.564 ms. `REAL_4K_QUALITY_GAIN` remains `NOT_PROVEN`, and no runtime optimization is claimed.
- Real isolated Playwright execution exposed a stale same-task context on the first consumer result page. Task routes now refresh the formal task fact once without changing API contracts, and the repeated upload → processing → immediate result path rendered both real assets, dimensions, size, canonical capability wording, and an enabled delivery decision with zero browser errors or warnings. The 271-test UI suite, 22 focused Python tests, JSON validation, and isolated production build pass.

## 2026-08-24 - V0.5.7 UI no-candidate truthfulness correction

- Corrected the final remaining compression result inconsistency: `NO_PROCESSING_NEEDED` with `output_created=false` and `SOURCE_NO_PROCESSING` no longer enters the confirmed-candidate presentation or instructs the user to open an output directory. The page now states that the source already meets the requirement, that no new deliverable was created, and that the user may continue with the source or adjust parameters and retry.
- Candidate delivery readiness is now true only when a real candidate exists and its existing backend delivery gate is ready. Backend, API, Task, Result, Delivery, formal-directory, and version contracts remain unchanged.
- A fail-before test reproduced the missing state. The complete 270-test UI suite, targeted frozen status/API tests, Vite production build, and the same real-backend Playwright path pass; ReproSight run `20260824t014118z-compression-no-processing-result-truthfuln` is `verified` with before/after evidence and zero browser Console errors.

## 2026-08-24 - V0.5.7 UI final development closeout

- Closed the remaining audited P1/P2 UI pool without changing backend, API, Task, Result, Delivery, formal-directory, or version contracts. Processing history and empty views no longer render current zero-state summaries, workdir detection is neutral while loading, backend delivery status remains authoritative, delivery completion uses the Shell width more effectively, and all visible 11px CSS text declarations now use the 12px baseline.
- Kept Image Compression on its existing specialized page while completing the user-visible Input → Processing → Result → Confirm → Delivery sequence: output-directory delivery is gated until backend review confirms `DELIVERY_READY`, and a confirmed result exposes an explicit delivery action.
- Fail-before coverage reproduced the state-truthfulness and compression-gate defects. Validation passes with 11/11 focused tests, 269/269 UI tests, 77/77 compression API tests, Vite production build, nine-route isolated Playwright coverage, and three verified ReproSight reports. UI development closeout is complete; subjective human visual signoff and release freeze remain separate and are not claimed.

## 2026-08-24 - V0.5.7 UI-004 result truthfulness and unknown-route recovery

- Result pages now prefer the task-level canonical `result-file` reference over stale compatibility previews and keep confirmation disabled until the browser has actually loaded the current result asset. Unavailable results show a bounded recovery message and recheck action without exposing internal paths or changing Task, Result, Delivery, or backend contracts.
- Unknown paths continue through the existing `UnknownRoutePage`; processing-mode lookup no longer dereferences missing route metadata, so the page renders and can return to the processing center without a React root crash.
- Fail-before tests reproduced both defects. The focused 46-test set and Vite production build pass; isolated Playwright checks verified a reachable canonical result, an unreachable result that stays blocked after retry, and a recoverable unknown route with zero route-page Console errors. UI-004 can freeze independently, while the remaining V0.5.7 P1/P2 UI issue pool is not declared closed.

## 2026-08-23 - V0.5.7-dev unified development version sync

- Updated the single authoritative product version source from `V0.5.6-dev` to `V0.5.7-dev`, preserving the existing release name and all runtime, API, UI, and delivery contracts.
- Synchronized the active product-version and System Settings assertions plus the current-status entry. Historical reports, contracts, frozen 4K artifacts, and their recorded V0.5.6 hashes remain immutable.

## 2026-08-23 - V0.5.7 UI-003 remaining frontend API isolation

- Replaced the remaining hard-coded formal `localhost:8787` API bases in Image Diagnosis, Image Compare, and Quality Report with the existing `VITE_API_BASE_URL` / same-origin Vite proxy contract; no page structure, copy, CSS, backend API, task state, or delivery behavior changed.
- Added focused source-contract coverage for all three pages. The 46 related UI tests and Vite production build pass, with zero formal-8787 strings in both `src` and the built frontend bundle.
- Playwright completed a real image-diagnosis task against isolated ports `15177`/`18791`; the successful task request and the compare/report missing-task compatibility checks remained same-origin, with zero requests to formal 8787. Formal settings and all files under `D:\影界文件` remained unchanged.

## 2026-08-23 - V0.5.7 UI-002 settings API isolation

- Removed the System Settings page's hard-coded formal `localhost:8787` base and bound its requests to the existing same-origin Vite proxy / configured API target contract.
- Preserved the UI-001 formal output-root presentation, backend workdir and API contracts, Task/Result/Delivery behavior, formal settings, and all files under `D:\影界文件`; no CSS, navigation, or save-path logic was changed.
- Validation passed: 20/20 focused Node tests, Vite production build, and Playwright normal/recheck/theme plus real directory-blocked/recheck paths against isolated non-8787 backends. All settings requests remained same-origin and the formal 8787 request count was zero; blocked-environment 503 console entries came only from the existing global color-batch preload.

## 2026-08-23 - V0.5.7 UI-001 settings formal output-root presentation

- System Settings now derives and displays one user-visible `正式输出根目录` from the authoritative `app_data_root`; the normal and compatibility 1080P child directories are no longer exposed as separate settings rows.
- Kept the backend workdir fields, formal path resolution, settings persistence, Task/Result/Delivery contracts, and all files under `D:\影界文件` unchanged. No CSS or navigation change was made.
- Validation passed: 19/19 focused Node tests, Vite production build, formal launcher backend/proxy health, and Playwright loading/normal/isolated-blocked plus light/dark theme checks. Browser console errors and warnings were both zero.

## 2026-08-23 - V0.5.7 D57-COLOR-00 commercial color restoration contract

- Frozen the product and technical contract for D-line commercial color restoration: the target is reliable color and recoverable-exposure restoration rather than styling, beautification, HDR hallucination, or universal automatic correction.
- Bound V1 to JPEG/PNG, explicit color-management and recoverability facts, non-generative bounded candidates, non-compensatory commercial safety gates, GT-A-to-GT-E evidence authority, and the existing D1-to-D3 plus Task/Result/Delivery contracts. `CANNOT_RECOVER_SAFELY` remains a blocker reason mapped through existing non-deliverable behavior rather than a new public Final Action.
- Separated the remaining work into seven non-overlapping stages after this contract. Only D57-COLOR-01 metric attribution repair is authorized next; V3 capability, formal integration, version promotion, UI changes, and commercial release remain `NOT_PROVEN` / not authorized in this stage.
- Correction 01 closed the contract-freeze blockers: blind `ACCEPT_CORRECTED` direct-use evidence now requires a >=95% point rate and >=90% Wilson 95% lower bound with nonzero and per-route evidence sufficiency; GT-D creation and V2/V3/control review now use frozen, anonymous, randomized, independently adjudicated evidence; and the current ICC facts distinguish JPEG reattachment from unproven PNG ICC embedding and the still-unproven CMM/workspace path. `CONTRACT_FREEZE_AUDIT=PASS`, `D57_COLOR_00=COMPLETE`, and only `D57-COLOR-01` is authorized next.
- D57-COLOR-01 separated raw Reference measurements from `COLOR_EXECUTOR_GRADE`, `EXPOSURE_EXECUTOR_GRADE`, actual-chain `EXPOSURE_STAGE_INCREMENT_GRADE`, `COMBINED_PIPELINE_GRADE`, and the non-authoritative commercial-delivery decision. `COLOR_EXECUTOR_CREDIT` now means proven positive color contribution: pure-color rows require `RECOVERED`/`IMPROVED`, combined rows require `COLOR_ONLY`/`COLOR_PLUS_EXPOSURE`, and every other result receives `NO`; the existing `invalid_color_credit` gate checks this contract bidirectionally. Pure-color evidence excludes `CAST_PLUS_EXPOSURE`, all category winners remain `NOT_EVALUABLE`, `RECOVERED` still requires every applicable controlled Reference-region gate, and missing GT-B brand ROI remains `NOT_EVALUABLE`.
- The final isolated metric-credit rerun retained five references, 20 controlled errors, and 40 candidates with 20/20 error and 40/40 candidate SHA matches against the revoked baseline and both prior metric evidence sets. Seventeen rows receive positive color credit, 23 receive none, and all ten combined rows receive none; four combined improvements remain attributed to Exposure only because standalone Exposure, actual-chain Exposure increment, and the combined pipeline all improve. All ten mandatory metric gates pass, `METRIC_CONTRACT_STATUS=PASS` is derived, commercial color capability remains `NOT_PROVEN`, `QUALITY_BASELINE_AUTHORITY=VALID_FOR_CONTROLLED_METRIC_USE`, and `D57_COLOR_01=COMPLETE` authorizes only `D57-COLOR-02`, which must pre-freeze source-group counting and one sample-level verdict from independent reviewers before Wilson evidence is calculated.

## 2026-08-21 - V0.5.7 E4K-03 reuse correction 02

- Added `CANDIDATE_SELECTION_CONTRACT_V1`: only eligible `ADOPT` candidates enter comparison, the existing E1-02/Benchmark evidence is evaluated in the frozen seven-level non-weighted order, runtime is used only after all quality and safety evidence ties, and candidate/model names have no selection authority.
- Multiple ADOPT candidates without one evidence-based winner now return `UNRESOLVED_MULTI_ADOPT` and `NEEDS_SELECTION_REVIEW`; current Swin2SR remains `REJECT`, `BEST_CANDIDATE=NONE`, `MODEL_ADOPTION=NONE`, and `REAL_4K_QUALITY_GAIN=NOT_PROVEN` without model inference or Benchmark reruns.
- Migrated active E4K-03 Runtime, Smoke Summary, Candidate Manifest, Candidate Summary, and Comparison reports to `observed_sampled_rss_max_bytes` with true peak memory explicitly not proven. Raw historical `candidate_runtime.json` evidence was preserved; active stale peak-memory field count is zero.

## 2026-08-21 - V0.5.7 E4K-03 reuse correction 01

- Bound `model_load_status=PASS` into final model eligibility; a failed or missing load status now produces runtime `FAIL`, blocks eligibility, and cannot authorize Benchmark.
- Replaced the fixed E4K-03 comparison conclusion with one dynamic ADOPT aggregation used by Candidate Summary and Comparison. Existing Swin2SR evidence remains `REJECT`, `MODEL_ADOPTION=NONE`, and `REAL_4K_QUALITY_GAIN=NOT_PROVEN` without rerunning inference or the 16-case Benchmark.
- Corrected derived reporting to `observed_sampled_rss_max_bytes=2109227008` with `true_peak_memory=NOT_PROVEN`, and explicitly separated unchanged E4K-02 Artifact/control semantics from the E4K-03 shared-source extension. Added eight reporting tests and two load-gate tests; all 127 HD Core tests pass, while protected model/Benchmark/ROI/review assets and formal hashes remain unchanged.

## 2026-08-21 - V0.5.7 E4K-01 E1-02 Quality & Delivery Gate V1

- Added the isolated E1-02 Gate over the frozen E1-01 contract, reusing `rerender_candidate_comparisons`, all 16 valid cases, 8 GT cases, fixed ROI/full-image comparisons, existing quality proxies, text-like masks, and image-type heuristics without changing formal 4K execution.
- Separated eligibility, hard safety, GT-relative net-gain evidence, and delivery decisions. Zero-gain, Blur, Oversharpen, Halo/Ringing, Color Shift, and Oracle controls are isolated from product Candidate statistics; proxy sharpness/high-frequency scores cannot independently authorize gain.
- Generated `artifacts/e1_02_quality_delivery_gate_v1`: 16/16 zero-gain controls had no gain false positive, all four negative controls were rejected by their required gates, and 8/8 GT Oracle controls were detected while product gain counts remained zero and `REAL_4K_QUALITY_GAIN=NOT_PROVEN`.
- Closed the final gate weaknesses with canonical replay binding and recomputation, phase-correlation/ECC geometry evidence, independent mandatory sub-gate statuses, GT controls that cannot bypass Safety, target-specific local-color/high-frequency damage controls, text Broken/Stick/Double-Edge controls, and asset/hash-bound human-review evidence. Added 37 focused tests and passed the 66-test E1-02/E1-01/HD Core/formal-4K regression set. E1-01 tree content, `four_k_v1.py`, `main.py`, and `product_version.json` remained unchanged; no production route or UI integration was added.
- E4K-01 Gate Correction 02 added a fixed 11-item `MANDATORY_GATE_AGGREGATION_V1`, a single fail-closed PRODUCT delivery authority, separate review binding/product admissibility, control-fixture/test-vector isolation, and a PRODUCT PASS global invariant. The five fail-before cases failed on the old implementation and passed after the delta patch; 52 focused tests and the expanded 81-test related regression set pass. The regenerated 364-file Artifact contains 88 parseable JSON files, zero missing references, `CONTROL_FIXTURE_PRODUCT_AUTHORIZATION_COUNT=0`, `MANDATORY_GATE_COMPLETE=YES`, and `PRODUCT_PASS_GLOBAL_INVARIANT=PASS`; product quality gain remains unproven and no production route, UI, E1-01, or model work was added.

## 2026-08-17 - V0.5.6-dev UB-01 mature 4K upper-bound comparison

- Ran the one already-local official `Real-ESRGAN-x4plus` NCNN/Vulkan comparator against seven frozen E1-01 GT cases covering Resize, Resize+JPEG, Blur+JPEG, Multi-resize, Screenshot-like, and all seven key ROI roles. Generated isolated INPUT / SAFE_BASE / MATURE_COMPARATOR / GT full-image sheets and SAFE_BASE / MATURE_COMPARATOR / GT ROI sheets without rerunning SAFE_BASE or including any closed E-line Candidate.
- Closed UB-01 as `UPPER_BOUND_NOT_CONFIRMED`: the comparator produces obvious perceptual sharpness, especially on Blur+JPEG portrait content, but native GT crops show regenerated face identity, guessed Chinese strokes, rewritten small Logo/product text, and GT-inconsistent material micro-texture. Overshoot increased in all seven cases, so no repeatable trustworthy scope exceeded SAFE_BASE.
- `TARGET_FEASIBLE=NOT_CONFIRMED`, UB-02 is not authorized, and the next action is product-target reassessment rather than another core-algorithm PoC. E1-01 assets, Settings, and the formal 4K directory remain untouched.

## 2026-08-17 - V0.5.6-dev E-CORE-03-01 single learned reconstruction GT PoC

- Selected exactly one already-local, licensed candidate: the non-generative fidelity-oriented `SRMD_NCNN_VULKAN_X4_NF` model (`srmdnf_x4`, noise `-1`) running through the existing NCNN/Vulkan binary on Intel Iris Xe. No model download, rotation, training, runtime registration, or formal-route change was performed.
- Reused six frozen E1-01 GT cases and the existing four-way Candidate rerender/ROI contract. The learned candidate reads degraded INPUT only, emits an x4 master, and is geometry-normalized to the frozen 4K dimensions; SAFE_BASE is byte-reused for comparison and GT is accessed after candidate generation for validation only.
- Closed the candidate as `DROP`: 0/6 full images passed the joint GT-direction gate, only 3/11 Screenshot-like ROIs had local metric-direction improvement, and 5/6 cases increased overshoot versus SAFE_BASE. Direct ROI inspection found edge hardening rather than repeatable GT-consistent text, identity, product, or material recovery. Alpha remained byte-identical on the RGBA control and the repeated model execution was pixel-exact deterministic.
- Generated isolated full-image and ROI comparison assets plus a validation manifest. Six targeted tests and manifest validation pass; E1-01 assets, SAFE_BASE execution, Settings, and the formal 4K directory remain unchanged. E2 stays locked and no human review is required for this dropped candidate.
- Final contract closure now binds every selected case to the frozen E1-01 `case_id`/sample/degradation/INPUT/GT facts and verifies declared core image hashes. It preserves Alpha byte identity only as a factual sub-check, marks the unperformed full Alpha, tile-seam, and Fidelity gates as not evaluated/not required for DROP, records the existing rejection reason explicitly, and keeps `DROP_AND_CLOSED` without rerunning the PoC or regenerating outputs.

## 2026-08-17 - V0.5.6 D4-A formal runtime binding closure

- Replaced the backend color task's legacy `process_single_image` acceptance path with the formal D1-to-D3 runtime. D3 now supplies the only final authority: exposure `ACCEPT_CORRECTED` selects the verified Candidate, `ACCEPT_ORIGINAL` selects the untouched source without creating a Candidate output, and color `REVIEW_REQUIRED` remains a non-deliverable review Candidate or a Candidate-free review state.
- Removed the legacy processor and concrete legacy Result from the `engine.color_correction` package exports. The old core remains available only as an explicit implementation-module compatibility asset; no production caller uses it as a Result authority.
- Bound Output Center and Smart Delivery eligibility to matching D3/Result `ACCEPT_CORRECTED` plus `CORRECTED_CANDIDATE`. D4 replay metrics now come from the same formal runtime and expose sample expectation, D1 action, D3 action, Result action, and selected output. D01_02/D01_03 remain review-only, D01_04 is accepted, KEEP_ORIGINAL creates no modified output, and a controlled side-effect Candidate is rejected to Original.

## 2026-08-17 - V0.5.6 D4 real-sample full-chain benchmark

- Added a fixed, hash-bound D4 manifest over the 15 unique authoritative D01 real sources and mapped each existing label to the frozen V0.5.6 Final Action policy without using current D1 output as expected truth. Derived ambient controls and deterministic Replay images remain supplementary checks and are explicitly excluded from the real Benchmark count.
- Added an isolated D1-to-D3 replay that preserves D1 source-binding semantics for RGB/RGBA and bit depth, materializes only `ACCEPT_CORRECTED` outputs, verifies D2 Candidate identity, PNG decodability, original-file immutability, side-effect gates, Final Action/output consistency, and all high-risk false-accept/public-bypass counters.
- The 15-case chain is internally consistent and its sole accepted exposure output passes, but freeze is blocked: only 15/240 unique real samples and 9/13 target categories are present; ordinary cast, real too-bright, color-plus-exposure, and real normal-cool coverage are missing. Existing local-only labels D01_09/D01_14 are safely kept Original but leave problem-detection recall at 5/7, so V0.5.6 Color V1 is not marked frozen.

## 2026-08-17 - V0.5.6 D3 authoritative Candidate handoff closure

- Removed the externally supplied D2-result parameter from the public D3 contract. `audit_candidate(image, decision, ...)` now calls the frozen `generate_candidate` entrypoint inside the same call, then immediately audits that invocation's Candidate; copied, reconstructed, or serialized D2 DTOs have no public parameter through which they can request an authoritative Final Action.
- Kept the D3 quality metrics and thresholds unchanged. D2 `PROTECTION_BLOCKED` and executor-limit results fail closed before pixel audit; `KEEP_ORIGINAL` remains Candidate-free; D01_02/D01_03 remain review-only; D01_04 and qualified dark exposure retain `AUTO_PROVEN` only after all existing gates pass.
- Replaced helper-only side-effect coverage with a public-entry E2E executor-regression injection. A Candidate containing controlled skin damage, highlight clipping, and shadow crushing now traverses the internal D2-to-D3 handoff and is rejected by Side Effect / Net Gain as `ACCEPT_ORIGINAL`. D1, D2, correction parameters, UI, and all other frozen modules remain unchanged.

## 2026-08-17 - V0.5.6-dev E-CORE-02-01 local degradation evidence PoC

- Added an isolated INPUT-only, deterministic local-evidence classifier over seven frozen E1-01 cases (six controlled-GT cases plus one clear real-input control). It emits only `SHARP_STABLE`, `SOFT_RECOVERABLE`, `JPEG_DEGRADED`, `RESAMPLING_DEGRADED`, or `UNCERTAIN`, together with patch JSON, ROI decisions, local maps, overlays, and INPUT/GT validation sheets; it performs no restoration, reconstruction, SAFE_BASE execution, model inference, or runtime routing.
- Round 1 observed a case-level JPEG signal and safe `UNCERTAIN` fallback behavior, but did not establish patch-level spatial localization truth. Blur+JPEG produced no reliable soft-state separation, Multi-resize was predominantly misclassified as sharp, the clear control did not reliably establish sharp regions, and confidence was not calibrated to local truth.
- Closed the hypothesis as `DROP`: `PROVEN_SCOPE` is empty, Round 2 and E-CORE-02-02 are not authorized, and all E1-01 assets, Settings, formal 4K state, and non-manifest PoC outputs remain unchanged during final adjudication. The closure entry now accepts only the complete official 7-case/6-GT manifest and its in-root output references, binds every case ID to the frozen E1-01 sample/degradation/INPUT/GT facts using normalized paths, rejects incomplete, cross-case, or path-escaped substitutions before writing, and records `UNCERTAIN` separately as a useful fail-closed fallback and failed technical proof.

## 2026-08-17 - V0.5.6 D3 Result Audit / output quality gate V1

- Added a D3-only Candidate-vs-Original audit. It accepts only the private D2 result contract, replays the supported `generate_candidate` path against the same source fingerprint, D1 versions, budget, and person regions, and rejects stale, missing, mismatched, malformed, manually shaped, or pixel-tampered results before any acceptance decision.
- Added independent RGB/Lab output gates for residual color/exposure state, highlight clipping, shadow crushing, skin, neutral and strong/brand colors, spatial color consistency, reverse cast, scene intent, side effects, and net gain. D2 metrics remain context only and are not used as D3 proof.
- Added explicit `AUTO_PROVEN` / `REVIEW_ONLY` / `NONE` authority. D01_02/D01_03 remain review-only despite positive technical audits; D01_04 and the qualified dark exposure control may accept the Candidate; a bright control that remains `TOO_BRIGHT` and controlled skin/highlight/shadow damage fall back to Original. D4 records contain only versions, a content-bound Candidate identity, audit facts, gates, authority, and action—no images, paths, or person identity.

## 2026-08-17 - V0.5.6 D2 public DTO contract closure

- Froze the supported D2 package surface to version constants, read-only enums, and the fully gated `generate_candidate` entrypoint. Concrete plan, executor-attempt, and candidate-result implementations are now module-private and are no longer exported from either `candidate_generation.__all__` or `engine.color_correction`.
- Confirmed that no current production Result, Delivery, save/output, D3 placeholder, or color caller trusts `CANDIDATE_READY`, `modified`, or a plan executor directly. The existing runtime color caller remains on the separate frozen Color Core API; D2 has no ungated production consumer.
- Expanded the public-surface regression to enumerate every supported callable, reject public concrete DTO constructors and calls without a D1 decision, and retain the existing missing/stale contract, source-mismatch, `KEEP_ORIGINAL`, D01_02/D01_03 review-candidate, and D01_04 exposure-candidate coverage. No D1 rule or correction parameter changed.

## 2026-08-17 - V0.5.6 D2 public contract final closeout

- Privatized the D2 correction-plan builder as `_build_correction_plan` and removed its package/module exports. The only public D2 execution function is now `generate_candidate`; no legacy alias or unchecked plan-building fallback remains.
- Kept the execution order fixed at source binding, exact D1 schema/engine/rule version validation, D1 action gate, internal plan construction, executor, and Candidate. Contract failures remain `PROTECTION_BLOCKED` with no executor, no Candidate, and no source-pixel mutation.
- Added a public-surface regression alongside the existing stale/missing contract, source-mismatch, `KEEP_ORIGINAL`, review-only color, and legal exposure-AUTO cases. No D1 rule, Safe WB, `cross_affine_balanced`, exposure parameter, UI, 4K, or other frozen module was changed.

## 2026-08-17 - V0.5.6 D2 source binding and D1 version gate closeout

- Added a path-free `SOURCE_FINGERPRINT` to the D1 decision. It hashes full-resolution, orientation-normalized RGB/RGBA content together with dimensions, channel count, dtype, bit depth, and numeric representation; BGR/RGB channel order is canonicalized, while no image bytes, path, person identity, or business semantics are persisted in Shadow/Replay.
- D2 now verifies the current input fingerprint and the exact supported D1 schema, engine, and rule versions before building an executable correction plan. Missing, malformed, mismatched, stale, or unsupported contracts fail closed as `PROTECTION_BLOCKED` with no Candidate and no executor call.
- Added real D01_01/D01_15 mismatch regressions, stale/missing contract cases, correct D01_04 exposure pairing, D01_02/D01_03 color-candidate preservation, channel-order stability, and zero-pixel-change assertions. D1 rules, Safe WB, `cross_affine_balanced`, exposure parameters, UI, 4K, and all other frozen modules remain unchanged.

## 2026-08-17 - V0.5.6 D2 safe color/exposure Candidate V1

- Added a D1-consuming D2 contract that emits no pixels for `KEEP_ORIGINAL`, produces review-only color Candidates for eligible directional `REVIEW_REQUIRED` inputs, and produces exposure Candidates only for D1-authorized `TOO_DARK` / `TOO_BRIGHT`. Every Candidate remains pending D3 and cannot become a formal Result in D2.
- Reused the existing Safe WB and frozen `cross_affine_balanced` executors behind shared `MILD` / `MODERATE` budgets and protection gates. Color execution preserves source Lab luminance and guards skin, neutral, strong/brand colors, clipping, saturation, and scene intent; exposure uses an independent bounded Lab-L curve with no CLAHE, HDR, sharpening, contrast enhancement, or color-plan coupling.
- Added hash-bound D01_02/D01_03 executor validation against the fixed D01_01 authority reference, exposure dark/bright controls, local-person/mixed/dominant-color/normal-scene protections, explicit unsupported 16-bit color-executor handling, and the privacy-minimal D2-to-D3 record. D1 authorization, UI, 4K, local retouch, naming, and formal Result/Delivery wiring remain unchanged.

## 2026-08-17 - V0.5.6-dev E1-02 Selective Fine Detail PoC round 1

- Added one isolated, deterministic INPUT-supported luminance-detail ablation: `GLOBAL_DETAIL` applies the bounded residual without regional selection, while `SELECTIVE_DETAIL` uses the same residual with local texture evidence, strong-edge suppression, flat-region suppression, and a 6-level amplitude clamp. No network, SR model, segmentation, runtime route, Settings, or UI was added or changed.
- Reused eight fixed E1-01 controlled-GT cases and all seven ROI roles. Both routes use the existing E1-01 Candidate rerender entry, with separate four-way evidence plus direct five-way INPUT / SAFE_BASE / GLOBAL_DETAIL / SELECTIVE_DETAIL / GT full-image and ROI review assets.
- Round 1 completed with 8/8 cases, 16 Candidate outputs, and 14 ROI comparisons. Technical execution and protection gates pass without rerunning SAFE_BASE; visible/selective real-information gain and all fidelity/artifact judgments remain `PENDING_HUMAN_VISUAL_REVIEW`, so E1-03 is not yet authorized.

## 2026-08-17 - V0.5.6-dev E1-03 Restore-Then-Reconstruction PoC

- Reused six E1-01 GT cases and the frozen SAFE_BASE/ROI contract to compare INPUT, SAFE_BASE, DIRECT, RESTORED_INPUT, RESTORE_THEN_RECONSTRUCTION, and GT. Restoration uses the existing input-evidence compression repair at its fixed default strength before the frozen safe reconstruction; E1-02 Selective Detail is not imported or executed.
- Added deterministic OpenCV containment for the isolated restoration call, six-way full-image/ROI outputs, GT diagnostics, and explicit visual adjudication without rerunning SAFE_BASE or changing Settings, source assets, the E1-01 manifest, or the formal 4K directory.
- Closed round 1 as `DROP`: only 3/11 ROIs in the two Resize+JPEG cases showed small metric-direction improvements, while direct visual inspection found no visible GT-consistent recovered text, identity, logo, structure, or material information. Blur+JPEG, Multi-resize, and Screenshot-like cases were directionally negative; no round 2 was authorized.

## 2026-08-17 - V0.5.6-dev E1-01 real-information-gain minimal baseline

- Fixed a reusable 8-sample, 16-case E1-01 baseline from the existing Stage-1 golden snapshots, including seven real existing assets and one explicitly labelled `SYNTHETIC_CONTROL`. Controlled GT cases cover Resize, Resize+JPEG, Blur+JPEG, Multi-resize, and Screenshot-like degradation with byte-repeatable parameters.
- Reused the frozen `process_4k_v1_image` SAFE_BASE route and the existing 14 normalized ROI definitions. Every case exposes the same INPUT / SAFE_BASE / empty CANDIDATE / optional GT contract, direct side-by-side output, and 1-3 role-matched ROI crops without adding a UI or benchmark framework.
- Added one candidate-aware rerender entry that reads an existing E1-01 manifest and caller-supplied Candidate, rejects missing, undecodable, or wrong-sized files, and produces full-image plus ROI four-way comparisons in a separate output root without rerunning SAFE_BASE or modifying the frozen baseline.
- Frozen the visible-gain and fidelity fields plus the rule that sharpening, high-frequency growth, harder edges, noise/JPEG amplification, unsupported texture, rewritten text/Logo/face/product structure, or metric-only improvement cannot establish real information gain. Settings, formal 4K output, source snapshots, product routes, and other development lines remain unchanged.

## 2026-08-17 - D1 color AUTO separability final validation

- Added hash-bound matched normal-warm and normal-cool person controls derived from the frozen human-accepted D01_02/D01_03 outputs. Geometry, person/background structure, and PNG transport stay fixed; only the previously authority-labelled normal ambient transform differs. The normal-cool control and D01_03 produce the same categorical Post-ISP signature across neutral, highlight, spatial, person/skin, illuminant, and scene-intent facts, while the pre-fix rule incorrectly authorized the normal-cool control.
- Recorded the resulting technical conclusion as `COLOR_AUTO_SEPARABILITY=NOT_PROVEN`: the current JPEG/PNG facts can agree on visible cool/warm appearance but cannot establish whether that appearance is ambient intent or erroneous cast. No skin target, 3.5 direction boundary, existing appearance threshold, or exposure route was adjusted.
- Restored the frozen person/skin contract to protection-only. `PERSON_SKIN_RELATION` and the remaining Post-ISP reference families are recorded for appearance/risk explanation but cannot authorize global color AUTO; D01_02/D01_03 now safely route to review pending independent evidence. Existing 8/16-bit stability, mixed-light, D01_08, dominant-color, Ground Truth, Shadow/Replay, and exposure AUTO behavior remain covered.

## 2026-08-17 - D1 COLOR_AUTO_AUTHORIZATION_V1 closeout

- Added the explicit `AUTHORIZED` / `DENIED` / `UNCERTAIN` color-auto contract. Authorization is intentionally narrow and requires four agreeing semantic reference families: skin-excluded neutral regions, highlight low-chroma regions, spatial multi-region consistency, and the frozen person/skin color relationship; global RGB/Lab, aggregate appearance, and legacy D-01 cast output remain excluded as same-source votes.
- Reused the existing authority-labelled D01_02 yellow-cast and D01_03 blue-cast samples as positive Ground Truth. Both now reach `AUTO_CORRECT`, while D01_13 legitimate warm-person intent, D01_08 local blue-light contamination, controlled ambient warm/cool sweeps, dominant-color cases, and mixed light remain protected.
- Added authority integrity, false-positive matrix, real 8/16-bit PNG equivalence, public-contract, and Shadow/Replay regressions. No correction parameters, D2 executor, color thresholds, UI, 4K, preprocessing, or frozen Color Core route changed.

## 2026-08-17 - D1 color-correction usability decision V1.3 quantization stability closeout

- Added a shared 8/16-bit RGB encoding uncertainty envelope derived from the 8-bit half-LSB, 16-bit half-LSB, and float32 roundoff. The full RGB-to-Lab/HSV appearance path is re-evaluated at channel-wise envelope corners without changing the existing warm/cool/Lab thresholds or reducing native 16-bit facts to 8-bit.
- Added an explicit `boundary_unstable` gate: if the encoding envelope crosses an appearance classification boundary, color status becomes `UNCERTAIN`, action becomes `REVIEW_REQUIRED`, and Shadow/Replay evidence records the feature ranges, observed directions, stable margin, and conflict reason.
- Added real PNG codec sweeps for warm and cool paths across 8-bit and 16-bit encodings, explicit warm/cool boundary regressions, and stable neutral/warm/cool controls. The gate is bounded to boundary points and does not authorize color AUTO or alter D2, UI, 4K, preprocessing, or frozen Color Core behavior.

## 2026-08-16 - D1 color-correction usability decision V1.2 root-cause closeout

- Separated post-ISP color appearance from correction justification. Global RGB/Lab, neutral Lab, tonal bands, spatial cells, and legacy D-01 global-cast output are explicitly one source family and no longer authorize automatic color correction; unresolved uniform warm/cool appearance routes to review.
- Kept 8/16-bit PNG values in one normalized float32 fact domain and moved D-01 person/local-light safety facts onto that canonical domain. Real 8/16-bit encodings now share color, exposure, and action decisions without forcing all 16-bit inputs to review.
- Removed silent skipping from the authoritative D01_08 gate and added hard failures for missing, unreadable, or incomplete authority resources. Replay labels now treat controlled yellow/blue samples as post-ISP appearance evidence only; no D2 parameters, UI, 4K, preprocessing, or frozen Color Core route changed.

## 2026-08-16 - D1 color-correction usability decision V1.1 closeout

- Added an observation-only D1 contract that fuses skin-excluded neutral evidence, global/low-chroma facts, spatial uniform-versus-mixed evidence, illuminant state, dominant-color risk, scene intent, exposure facts, and explicit support/conflict evidence before emitting `AUTO_CORRECT`, `KEEP_ORIGINAL`, or `REVIEW_REQUIRED`.
- Added an explicit ambient-versus-cast ambiguity gate: plausible low-saturation uniform warm/cool shifts now require review unless independent D-01 consensus or extreme multiband evidence establishes a global error. Reused the frozen D-01 person/skin facts to route local LED contamination to review without invoking global white balance.
- Preserved 16-bit PNG samples through fact extraction, recorded the real per-channel bit depth, and added equivalent 8/16-bit status checks. The privacy-minimal Shadow Data replay now has 15 authority-labelled cases covering cast, exposure, true warm/cool ambiguity, normal dark, person/skin, local LED contamination, neutral, dominant brand/wood colors, and mixed light. No correction parameters, local correction, UI, 4K, or frozen Color Core route changed.

## 2026-08-14 - V0.5.6-dev pre-release bug sweep

- Reconciled enhancement tasks left started but nonterminal across an application restart: when no formal Result exists, startup now records a real interrupted failure instead of restoring an orphaned 99% task as the current running task. Completed tasks and tasks with registered Results remain untouched.
- Consumed all rejecting View Transition promises so legacy compare/report deep-link convergence no longer emits an unhandled `AbortError` while continuing to route into the unified Result page.
- Added focused regressions for restart interruption and route-transition rejection handling. Image algorithms, local-retouch versions, naming/OCR, Feedback, and Task/Result/Delivery contracts were not changed.

## 2026-08-14 - V0.5.6-dev N2-02 local perspective text recovery

- Added an isolated N2-02 executor that accepts only N2-01 `GEOMETRIC_ABNORMAL` or `FRAGMENTED` decisions plus explicit local four-point text regions. It rectifies cropped BGR/8-bit regions with cubic interpolation, enlarges them 2x, and reruns the actual Windows OCR adapter; it never applies an unconditional whole-image warp and does not handle `OCR_EMPTY`, `LOW_CONFIDENCE`, or 3D text.
- Kept both `NORMAL` and `PERSPECTIVE_RECOVERY` candidates and added conservative arbitration based on reliable title evidence, character completeness, and structural agreement. A reliable NORMAL candidate is immutable, unrelated recovered text is rejected, and no measured gain retains the original result.
- Reused the integrity-bound N2-01 files and added a deterministic perspective-plus-fragmentation derivative from the frozen medium-perspective sample without changing the N2-01 baseline. Live Windows OCR improved medium perspective from `0.6154` to `1.0000` accuracy, strong perspective from `0.0000` to `1.0000`, and the perspective-fragmented control from `0.0000` to `1.0000`; normal/light samples remained unchanged and the no-text control produced no recovered text.
- Added a repeatable N2-02 validation entry, frozen local-region PNG/SHA evidence, and dedicated tests. N1 naming, Result/Delivery, 4K, color correction, UI, and 3D-text recovery remain unchanged.

## 2026-08-14 - V0.5.6-dev N2-01 complex OCR real baseline and Recovery trigger

- Added an isolated OCR Recovery routing contract that can only emit `OCR_EMPTY`, `LOW_CONFIDENCE`, `FRAGMENTED`, or `GEOMETRIC_ABNORMAL` into Recovery; reliable normal OCR is explicitly classified as `NORMAL_RELIABLE` and excluded. The layer performs no pixel transformation, perspective correction, 3D-text reconstruction, or OCR rewriting.
- Frozen eight actual PNG samples with source/sample SHA-256 provenance: a real Chinese title, controlled light/medium/strong homographies derived from that real title, a controlled fragmented derivative, a real embossed 3D-text crop, a real low-confidence design-text crop, and a real no-text control. Each frozen record contains the live Windows OCR output, engine confidence availability/value, routing status, and Recovery decision; no Mock result is accepted as baseline evidence.
- Added a repeatable live Windows OCR entry and N2-01-specific tests covering all four baselines, the five-state trigger matrix, sample/source integrity, normal-OCR non-trigger behavior, and frozen-result reproducibility. N1 naming, Result/Delivery, 4K, color correction, and UI remain unchanged.

## 2026-08-14 - V0.5.6-dev N1-02 visual batch distinction

- Added a batch-only comparison pass after the existing N1-01 per-image naming route. Repeated VISUAL labels now use only explicit per-image naming evidence, prioritizing subject, scene, action/state, and viewpoint before weaker attributes; the N1-01 no-text naming chain itself is unchanged.
- Semantically identical observations and byte-identical images keep the same content label and use the existing sequence-only filename distinction. The batch pass never parses captions or invents absent visual facts, and final filenames remain collision-safe.
- Excluded reliable OCR labels and `USER_CONFIRMED` items from automatic batch distinction. Real API validation covered seven no-text person/product/architecture/business images, highly similar crops, one reliable OCR title image, and confirmed-item regeneration without changing Result/Delivery, OCR algorithms, 4K, color correction, or UI.

## 2026-08-14 - V0.5.6-dev UI-05-FIX immutable original preview source

- Separated the local-retouch immutable original preview from the Workbench working source: `/source` now reads and SHA-validates `upload_path`, while `/working-source` exclusively serves the current `working_path` to the Workbench.
- Kept the registered formal Result on the latest completed working revision and preserved the existing Result-to-Delivery trace. Added targeted byte/SHA coverage for first completion, resumed editing, second completion, and latest-Result Delivery.
- LaMa, Mask behavior, working-version generation, rollback, original files, formal Result storage, Delivery execution, and naming logic were not changed.

## 2026-08-14 - V0.5.6-dev UI-05 local-retouch unified result and delivery wiring

- Changed the existing local-retouch `确认 → save` completion action to navigate only after a real registered Result is returned, then reuse the existing `/task-detail` comparison, review, return-adjustment, and direct Delivery flow. No retouch report page or parallel Result system was added.
- Kept V1/V2/V3 working results temporary. Returning from the unified Result uses one explicit resume-adjustment transition that preserves the registered Result and formal file while restoring the same stable working image, revision history, Mask workflow, and Workbench state for continued editing.
- Added local-retouch comparison metadata to the registered Result and kept Delivery copy-only. LaMa, repair behavior, Mask logic, working-version generation, batch naming, top-level navigation, original protection, and the Task/Result/Delivery identity contract were not changed.

## 2026-08-14 - V0.5.6-dev UI-03 direct result delivery

- Changed the `/task-detail` confirmation action to reuse the existing Smart Delivery preflight and execution endpoints directly for one registered `result_id`. A ready server-issued plan creates the real copy-only Delivery without forcing ordinary users through the full settings page.
- Added a focused `成品已保存` state with the delivered filename, necessary specifications, a user-friendly formal-output location, open-folder, continue-processing, and Output Center actions. API failures and failed delivery items retain their real messages and never enter the saved state.
- Kept Smart Delivery unchanged as the advanced naming and conflict-resolution path: blocked or changed preflight redirects to the existing page. Batch naming, OCR, `USER_CONFIRMED`, local retouch, algorithms, formal directories, top-level navigation, and the Task/Result/Delivery data contract remain unchanged.

## 2026-08-14 - V0.5.6-dev UI-02 unified result information structure

- Consolidated the completed `/task-detail` state into one user result sequence: real before/after assets first, scan-friendly review focus, one product summary, collapsed technical details, and the existing two result decisions.
- Moved processing timelines, technical metrics, engine/strategy facts, capability boundaries, and full color-correction records into secondary technical details. The main layer no longer repeats result, delivery, dimension, protection, or next-step prose and does not render task IDs or engineering paths.
- Redirected the historical task compare/report deep links back to `/task-detail` while preserving the underlying Task, Result, comparison assets, registered `result_id`, and Smart Delivery contract. No algorithm, backend, formal-directory, batch-naming, retouch, or top-level navigation behavior changed.

## 2026-08-14 - V0.5.6-dev UI-01 unified processing result flow

- Routed successful 1080P, 4K, and single-image color-correction completion into the existing task-scoped `/task-detail` result carrier; the historical color-result route now redirects to the same result entry.
- Reduced the result-stage decisions to `返回调整 / 重新处理` and `确认结果并交付`; comparison, report, file-opening, and task-detail actions no longer compete as peer next steps.
- Kept the real Task → Result → Delivery chain intact: delivery navigation uses only the registered `result_id`, while Smart Delivery retains authoritative preflight, confirmation, copy, and status writes. No algorithm, SSE, formal-directory, top-level navigation, batch-naming, or retouch branch changed.

## 2026-08-14 - Local retouch continuous-edit discoverability R1

- Kept every successful retouch result directly editable in the existing Workspace, added a stable current-result state and effective edit-depth display, and separated Mask undo/redo wording from result-level rollback.
- Added a presentation-only continue action that only returns focus to the editable canvas, plus one user-facing confirm-and-save action that reuses the existing confirm then save APIs without creating intermediate formal Results.
- Reduced success, rollback, failure, and final-save feedback to one short workspace status source. Retouch algorithms, the continuous working-result state machine, original protection, formal Result registration, Output Center, and Delivery contracts are unchanged.

## 2026-08-14 - OCR-independent visual batch naming fallback

- Removed the effective OCR dependency from batch-name arbitration: empty, unavailable, low-confidence, or rejected OCR now leaves the existing local VISUAL semantics active and produces a short Chinese suggestion when real subject, scene, action, state, or category evidence exists.
- Added one bounded VISUAL normalization for evidence-backed multi-person laptop/table meeting scenes so visible laptops no longer reduce a business meeting photo to the generic `电子产品` category.
- Broad VISUAL-only suggestions remain `needs_confirmation`, use project and confirmed batch context only as bounded naming context, never fall back to `图片_01`, and still refuse to fabricate a name when the visual model provides no semantic evidence.
- Kept reliable structural OCR naming, item-level `USER_CONFIRMED` freeze priority, source protection, Result/Delivery contracts, OCR algorithms, 4K, color correction, and global UI unchanged.

## 2026-08-14 - Unified feedback business-target binding

- Added a transient, reference-only Feedback Target so the Shell feedback entry prefers the explicitly failed business operation over Runtime fallback; starting a new operation clears the previous Target, and the mechanism accepts every registered feature key without module-specific branching.
- Empty-upload HTTP 400 responses now expose their existing feature/operation/trace/task/route/stage references. Context capture resolves only exact matching runtime events, keeps the business failure as the primary error, and continues to use the unchanged Feedback Trace V1 and V3 ZIP contracts.

## 2026-08-14 - Automated validation runtime-log isolation

- Removed the Vite development proxy's silent fallback to the formal backend port. Development and browser validation now require an explicit `HDDE_API_TARGET`, preventing an unconfigured run from sending test actions to the product instance.
- Kept `HDDE_RUNTIME_ROOT_OVERRIDE` scoped to runtime logs and added one shared real-App test helper that explicitly isolates the independent Settings and formal-root resolvers before App initialization. Added a hidden server validation-root option plus a batch-naming API regression that proves temporary logs and runtime files are real while formal logs, Settings, feedback, outputs, and Task/Result/Delivery facts remain unpolluted.
- Production startup and runtime logging are unchanged when no validation override is present. The historical 2026-08-13 17:29:32 formal log record is retained without modification.

## 2026-08-13 - V1 pre-release unified UI/UX implementation

- Unified current user-visible enhancement names to `1080P画质增强` and `4K画质增强` through a presentation mapping while preserving `safe_1080p_beta`, historical aliases, formal directories, APIs, and runtime task/result/delivery identities. The 4K shortcut now keeps the shared processing page title and navigation context selected.
- Added one shared conclusion-first result hierarchy, four action levels, semantic status language, 44px interaction targets, SVG utility icons, accessible focus/disabled states, and responsive output-center search/sort/detail behavior. Color correction, compression, task detail, compare, quality report, smart delivery, and immersive retouch reuse the same visual logic without changing algorithms or Settings contracts.
- Removed duplicate page feedback entries and ordinary-user exposure of Task/Result/Delivery and build/dirty identifiers. The Shell remains the single normal feedback entry, with a workspace-local entry only where the immersive retouch Shell topbar is intentionally hidden; no-task context capture is verified across eight formal page sources without HTTP 400.

## 2026-08-13 - HDDE user feedback V3 single ZIP package

- Replaced the legacy V2 three-file report with one validated `影界HDDE_问题反馈_FB-*.zip` containing exactly `feedback.json`, `related.log`, `timeline.json`, and `manifest.json`; the manifest records payload sizes and SHA-256 values and the generator reopens the temporary package before an exclusive final promotion.
- Consumed the frozen Feedback Trace Contract V1 without changing its fields or facts. Runtime log selection now requires exact persisted identifiers or explicit same-runtime event evidence, excludes conflicting traces/tasks, and reports `NOT_FOUND` instead of using an unsafe time-only guess.
- Updated the existing feedback dialog to download the real backend ZIP and retained its backend-unavailable local safe mode as the same four-file V3 format, with persistent generation status, privacy review, and package self-validation. No original/output image, Settings payload, full runtime log, or automatic upload is included.

## 2026-08-13 - Feedback Trace Contract V1

- Added one shared, existing-facts-only feedback trace contract for the 14 currently exposed user modules. Common identity and lifecycle fields are separated from feature-specific module diagnostics; unavailable or inapplicable Task, Result, Delivery, error, and event links remain explicit rather than inferred.
- Reused the shared Task/Result/Delivery registry, runtime/build identity, runtime log, error diagnostics, and feedback context. Stable operation/trace identities now persist through applicable image processing, compression, color, diagnosis, retouch, batch naming, batch processing, and smart-delivery paths without changing image algorithms, formal Result/Delivery semantics, Settings, or UI presentation.

## 2026-08-13 - D-line Color Core V2 final freeze closure

- Recorded the user-confirmed final visual decision as `HUMAN_FINAL_REVIEW=PASS`, `COLOR_CORE_V2=PROVEN_AND_FROZEN`, and `D_LINE_COLOR_CORE=COMPLETE`; no color algorithm, parameter, runtime interface, or evaluation output was changed during this closure.
- Frozen the production routes `cross_affine_balanced` and `guided_rgb_lab_field_selective` with Safety Gate 2.0 inside the existing D-01/D-02/D-03/D-04 chain. V2-G1/V2-G2 evaluation and PoC assets remain evidence only and are not runtime dependencies; runtime Ground Truth use remains disabled.
- Preserved originals, Settings, historical formal results, and the formal color-correction output contract. The accepted V2-B record remains the 15/15 run under `output/evaluation/v2_b_color_core_v2_20260813/final_v2_b_20260813_r3`; no Git write operation was performed.

## 2026-08-13 - HDDE internal safe HD base engineering

- Composed an isolated internal chain around the existing `process_4k_v1_image` executor: measurement-only degradation facts, frozen 4K safe reconstruction, source-alpha bypass, strict baseline-pixel risk rejection, baseline fallback, and lossless PNG delivery encoding. SRMD, semantic detection, new models, GPU integration, UI, Settings, Task/Result/Delivery, processing-center, and formal-output integration remain disabled.
- Ran three representative crops and three real images on the current CPU/Pillow path. All outputs decoded at the planned 4K dimensions, remained pixel-identical to the frozen safe baseline, and introduced no RGB high-frequency or edge changes. The real transparent PNG preserved all source-derived alpha pixels, including 542,493 semi-transparent pixels and 68,365 alpha-boundary pixels.
- A controlled added-edge candidate was rejected and the final output fell back pixel-exactly to the existing safe baseline. Sources, Settings, `D:\影界文件`, and the formal 4K directory remained unchanged. This proves only `HD_CORE_SAFE_BASE`; it does not prove real-information gain or `HD_CORE_V1`.

## 2026-08-13 - Processing-center Task record clearing

- Changed the existing current/history clear actions from page-only hiding to persistent Task deletion through the shared task registry. Safe pending tasks are removed only before execution is claimed; completed, failed, and cancelled tasks are removable, while running, processing, started-pending, blocked, and unknown states remain protected.
- The registry transaction deletes Task keys and aliases while retaining any formal Result as a result-keyed fact with its source Task, Delivery, and output references. Pending queue/batch/index and task-only cache references are revoked; Result, Delivery, original, formal output files, and output-center access remain intact across refresh and restart.

## 2026-08-13 - 4K enhancement V1 product and technical contract freeze

- Added the frozen 4K enhancement V1 authority contract defining the four-part commercial-delivery objective, all ten HD core responsibilities, unified CPU/Intel and NVIDIA hardware strategy, fidelity red lines, and explicit non-product scope.
- Frozen the current technical dispositions without rerunning prior PoCs: safe baseline and source-alpha bypass remain kept; SRMD and FiDeSR CUDA remain research-only; PLKSR-Tiny, SwinIR Lightweight x2, controlled RealESRGAN detail, and FiDeSR OpenVINO migration remain dropped; the HD core remains not proven.
- Frozen all seven completion gates from real-information breakthrough through final V1 acceptance. No model, parameter, unproven threshold, production executor, UI, Settings, diagnosis recommendation, Task/Result/Delivery contract, processing-center flow, or formal output path was changed.

## 2026-08-13 - V2-01 global color recovery technical PoC

- Compared three isolated, weight-free sRGB color-recovery candidates against the current HDDE baseline: trusted-neutral Bradford adaptation, Gray-Edge Bradford adaptation, and Shades-of-Gray CAT02 adaptation. All candidates reused the existing D-01 global-error-cast decision and D-04 safety review; no production executor was replaced.
- Gray-Edge and Shades-of-Gray failed the existing safety gate on the controlled warm-cast sample and fell back to current HDDE. Trusted-neutral Bradford passed both cast samples and kept all 13 non-cast outputs byte-identical to current HDDE, but only the warm-cast result showed a clear additional recovery; the cool-cast result remained incremental and did not establish a bidirectional visual breakthrough.
- Generated an original/current/best large comparison for B0, B1, normal people, mixed light, red/blue products, and legitimate warm light. The PoC result is `POC_NOT_PROVEN`; no dependency, model weight, formal output, Settings mutation, product integration, or V2-02 work was introduced.

## 2026-08-13 - Controlled perceptual / generative useful-detail PoC round 1

- Preflighted SinSR as the preferred one-step diffusion candidate, but its official x4 CUDA/xformers/ResShift path did not fit the current CPU-only host; used the single permitted switch to the official BSD-3-Clause RealESRGAN_x2plus perceptual candidate.
- Compared six exact same-source crops through A/LANCZOS, B/SRMD, and C/SRMD fidelity anchor plus a separately stored, source-supported generated luminance-detail layer. Low frequency, RGB color relationships, and source alpha remained outside the generator.
- Manual review found edge hardening and unsupported microtexture rather than confirmed new information, with decisive reinterpretation risk on complex texture. RealESRGAN_x2plus is dropped, the separation/control method remains research-only, and full-image Stage B was not triggered. Source images, Settings, and the formal 4K directory remained unchanged.

## 2026-08-13 - D-04.2 automatic color correction effective gain

- Increased only evidence-gated execution inside the existing architecture: trustworthy global cast recovery now has a stronger measured Lab response, true global underexposure receives a more effective coordinated midtone/highlight curve, floating-black low-contrast scenes receive stronger bounded tonal and large-scale separation, and existing local-person/LED masks receive a safer effective response. D-01 decisions, ORIGINAL/LOCAL_REQUIRED semantics, product/warm/dark/highlight protection, and D-04 rollback architecture are unchanged.
- Re-ran the same fixed 15 images in one isolated evaluation. Exactly the six improvement samples changed versus D-04.1; the nine protection samples remained byte-identical by SHA-256. All improvement candidates passed the existing post-quality gate, while B2/C1 retained responsibility-specific skin convergence and C4 preserved the LED screen exactly.
- Generated the full and six-sample large comparison sheets plus structured JSON traces. The focused color-correction suite passed 33/33; source, Settings, and formal-output fingerprints remained unchanged. First-glance gain remains pending user review at original size and the automatic color-correction core is not frozen by this run.

## 2026-08-13 - 4K cross-family technical-bricks PoC round 3

- Skipped SPAN/SPAN-F after its official repository did not provide an auditable native x2 checkpoint list or a current Windows runtime path, then used the one permitted switch to the official Apache-2.0 SwinIR Lightweight x2 checkpoint.
- Compared six same-source 128x128 representative crops through A/LANCZOS, B/SRMD, and C/SwinIR at exact x2 with lossless PNG encoding and source-alpha bypass. Manual review found C broadly equivalent to B with no additional confirmed useful detail, so SwinIR Lightweight x2 was dropped and full-image Stage B was not triggered.
- Kept the safe baseline and source-alpha bypass; source, Settings, and the formal 4K output directory remained unchanged. No product executor, UI, diagnosis rule, Settings, formal contract, or Git state was changed.

## 2026-08-13 - 4K technical-bricks PoC round 2

- Reused the first-round Original/A/B results and six representative crops, then tested one new native x2 core in an isolated Stage A. RealPLKSR was switched once after a bounded CPU-performance probe; the final candidate was the official MIT-licensed PLKSR-Tiny x2 DF2K checkpoint.
- Generated full-resolution C outputs plus unified A/B/C comparisons, 100%/200% crops, hashes, sizes, and runtime records. Manual review found only modest edge clarity over the safe resize baseline and no clear useful-detail advantage over SRMD; PLKSR-Tiny is dropped and Stage B content routing was not triggered.
- Kept source-alpha bypass as a format-safety adapter after zero alpha delta against the baseline. Source images, Settings, and the formal 4K output directory remained unchanged; no UI, API, product executor, diagnosis rule, formal output contract, or Git state was changed.

## 2026-08-13 - D-04.1 low-contrast transparency convergence

- Strengthened only the existing `transparency_and_layering` route when measured `low_contrast` and `floating_black` evidence is present without global underexposure. The route now coordinates its five-point luminance curve with a bounded large-scale Lab-lightness separation; clarity, sharpening, dehaze, global saturation, white balance, local-person, and product-color systems remain unchanged.
- Re-ran the same fixed 15 images in an isolated evaluation directory. Only C2 changed versus the D-04 baseline; the other 14 outputs remained byte-identical by SHA-256. C2 kept highlight ratio unchanged and saturation nearly unchanged while black/white separation, dynamic range, and local contrast increased under the existing D-04 quality gate.
- Added focused coverage for the generalized floating-black trigger and its no-clarity/no-saturation boundary. The color-correction suite passed 33/33; source, Settings, and formal-output fingerprints remained unchanged.

## 2026-08-13 - 4K technical-bricks PoC round 1

- Added an isolated 9-sample A/B/C PoC: current Pillow LANCZOS 4K baseline, SRMD ncnn Vulkan x2 direct reconstruction, and diagnosis-gated preprocessing followed by the same x2 core.
- Generated full-resolution results, whole-image comparisons, 100%/200% crops, hashes, dimensions, unified-encoding sizes, and runtime records without changing UI, Settings, product APIs, formal output contracts, or the formal output directory.
- Human review found modest direct-SR gains mainly on dense Chinese/Logo/regular edges, with fidelity risk on skin, complex texture, and alpha edges. The two triggered preprocessing bricks did not recover useful detail and are dropped; the SR core remains research-only.

## 2026-08-13 - D-04 post-quality-gate final convergence

- Replaced the remaining blanket post-review strength reduction with bounded, responsibility-specific control for highlights, black/shadows, white balance/color, saturation/key color, dynamic range, skin, noise, and halo risks; non-converging global candidates fall back to the exact original.
- Formalized the `ORIGINAL -> GLOBAL_CANDIDATE -> GLOBAL_ACCEPTED -> LOCAL_CANDIDATE -> FINAL` trace, including independent global/local execution and gate results, reduced parameters with responsible quality flags, rollback level, final decision, and algorithm-applied state. A failed local candidate returns the accepted global pixels and never reruns global correction.
- Added controlled branch coverage for tone-only highlight reduction, exact original fallback, and exact local-to-global rollback after an injected local negative-gain candidate. The focused suite passed 32/32.
- Re-ran the fixed 15 images in an isolated D-04 directory. All D-01 decisions, output policies, and D-03 output hashes remained unchanged; B0/B1/B2 A2-GT gains and B0/B1/B2/C1/C2/C4 positive gains were preserved, B2/C2 kept their proven baselines, both final contact sheets were generated, and source/settings/formal-output fingerprints remained unchanged.

## 2026-08-13 - D-03 local person and complex-light correction

- Added a `LOCAL_REQUIRED`-only correction layer after the D-02 result, with independent rollback to the pre-local pixels when person evidence, target improvement, blending, or non-target drift checks fail.
- Added local face-anchor consensus for the local executor without changing D-01 perception: C1 receives luminance-only face/upper-body midtone recovery, while C4 reduces only measured blue contamination inside the person support and derives skin chroma guidance from the same face's unaffected side.
- Added protected screen/background drift, highlight, transition-gradient, local-skin, and exact non-target checks; no beauty, relighting, global yellow compensation, sharpening, denoising, or generated person content was introduced.
- Re-ran the fixed 15 images against the frozen D-02 baseline. Only C1 and C4 triggered the local executor; all other outputs and all D-01 decisions remained unchanged, both required contact sheets were generated, and source/settings fingerprints remained unchanged.

## 2026-08-13 - D-02 global color executor quality upgrade

- Replaced the weak global cast correction with spatial neutral-target Lab recovery, while retaining strong-color, endpoint, skin, mixed-light, product-color, and legitimate-warm protection.
- Added coordinated five-point tonal recovery for true global underexposure and a separate floating-black transparency curve for low-contrast scenes; the latter changes black, shadow, midtone, highlight, and white relationships without dehaze, HDR, saturation boosting, or sharpening.
- Defined `algorithm_applied` and `algorithm_pixel_changed` independently from output re-encoding changes, so `ORIGINAL` means no color or tonal algorithm even when a file contract changes output bytes or pixels.
- Re-ran the fixed 15 D-01 images through the real V6 engine in an isolated D-02 directory. The D-01 matrix and protected outputs remained unchanged, B0/B1/B2 moved closer to the A2 ground truth, C2 gained measured tonal separation, and source/settings fingerprints remained unchanged.

## 2026-08-13 - D-01 color perception and decision core

- Upgraded the existing single-image color-correction core to decide error versus environment, global versus local scope, improvement versus protection, and `ORIGINAL` / `LOW` / `NORMAL` / `LOCAL_REQUIRED` treatment before editing pixels.
- Added spatial neutral evidence, mixed/strong-local lighting, global and subject exposure, tonal risks, reliable person evidence, product/screen key-color protection, legitimate warm/dark intent, dark-material protection, and high-highlight gating without changing the API, Settings, or formal output contract.
- Ran all 15 supplied D-01 images through the real V6 engine in an isolated repository evaluation directory; every per-image matrix check passed, real outputs were produced, source SHA/size/mtime and Settings SHA/size/mtime remained unchanged, and the focused color-correction API suite passed 24/24.

## 2026-08-12 - Batch file naming runtime and feedback context closure

- Unified batch naming events on the existing `batch_file_naming` feature key and added batch intake, name preflight, confirmation freeze, final success, and controlled failure context to the shared `hdde.runtime` log path.
- Reused the existing exception diagnostics for copy and analysis failures so `error_id` and `trace_id` persist with the batch run fact and flow into the existing `HDDE-user-feedback-v2` context.
- Added the existing unified feedback action to completed batch naming runs; the generated package carries only batch/run/delivery IDs, naming mode, counts, stage, status, safe failure details, trace/error IDs, related events, and the redacted runtime-log reference. Naming, source-copy, Result, Delivery, and Smart Delivery contracts remain unchanged.

## 2026-08-12 - Shell-level route transition V1

- Added one restrained content-only route transition at the existing Shell boundary: 160ms exit, 200ms enter, 4-6px vertical travel, and an ease-out curve; the sidebar and top bar remain outside the animated snapshot.
- Route changes, including browser history navigation, use the same transition commit without adding keys or remount wrappers; same-route query or local state changes stay outside the page animation, and rapid navigation skips the preceding transition.
- Added `prefers-reduced-motion` bypass and focused contract coverage; no business page, theme, task, upload, form, cache, API, or processing contract changed.

## 2026-08-11 - Final dark in-app logo replacement

- Replaced the dark-theme Shell logo with the newly supplied 2254x698 black-background asset, preserving its bytes and existing fixed 64px Shell alignment contract.
- Kept the light logo, startup splashes, Header, navigation, and all business UI unchanged; the existing centered `contain` sizing remains authoritative.
- Updated the focused asset-integrity and dimensions baseline for the new official dark logo.

## 2026-08-11 - Dark-logo Shell alignment correction

- Restored the dark sidebar brand area to the shared 64px Shell header baseline, so its lower divider and navigation start align with the unchanged right-side Header at every desktop width.
- Removed only the dark logo asset's abnormal top and bottom black canvas while retaining the full logo subject, then fitted the resulting 1536x528 asset into the fixed brand area with centered `contain` sizing and stable horizontal clearance.
- Added focused guards against theme-specific parent-height overrides and verified that the existing light-theme brand sizing remains unchanged; no navigation, page, component, color, typography, or business contract changed.

## 2026-08-11 - Startup splash and dark-logo final sizing

- Replaced the light splash, dark splash, and dark-theme in-app logo with the newly supplied byte-preserved formal assets; the existing light-theme in-app logo remains unchanged.
- Switched both startup visuals from viewport-filling crop behavior to one centered 84% `contain` contract with edge-matched light/dark background fill, and fitted the opaque 3:2 dark logo into a restrained theme-only brand surface without stretching or cropping.
- Added focused asset-integrity, dimensions, aspect-ratio, splash-fit, background-fill, and dark-logo sizing assertions; no navigation, Task, Result, Delivery, processing, Settings, or formal-directory contract changed.

## 2026-08-11 - Real-image naming discrimination correction

- Kept the pinned local Florence model and N2 product flow, but expanded the caption-to-Content Descriptor mapping so concrete visual evidence such as jewelry, trophy holding, meeting groups, posters, commercial showrooms, aircraft imagery, and aerial city views reaches the final 2-to-8-character Chinese name.
- Replaced exact generic-name filtering with an evidence-backed discrimination gate: automatic names now carry semantic depth and naming evidence, while broad subject-only observations produce no filename and remain `needs_confirmation` for user input.
- Revalidated eight protected commercial/natural samples through the real local model; the meaningful results were `蓝宝石首饰`, `汽车外观`, `手持奖杯`, `会议合影`, `飞机海报`, `商业展厅`, and `城市俯瞰`, while the evidence-free test graphic remained review-required. Source SHA256 and mtime stayed unchanged.

## 2026-08-11 - Batch naming quality and reference-file correction

- Replaced broad auto-names such as `人物画面` with an explicit review-required state, and tightened evidence-backed subject/scene/action combinations for names such as `会议发言`, `会场全景`, `产品正面`, and `餐品展示`.
- Replaced the free-text reference field with local TXT/MD/DOCX upload, parse, replace, and delete actions. Parsed terms remain non-authoritative naming guidance and cannot establish identity, brand, model, institution, or location facts without visual or filtered OCR support.
- Kept the V1 30-image and 01-to-30 product gates, editable preview, copy-only output, source protection, and non-content Delivery behavior unchanged.

## 2026-08-11 - Official HDDE brand asset integration

- Added the supplied, byte-preserved light/dark logos, internal app icon, multi-size Windows ICO, desktop icon master, light/dark splash screens, and asset manifest under one formal public asset root.
- Replaced the sidebar placeholder mark and legacy generated favicon references with the official theme-aware assets, added a short theme-matched startup splash without changing the frozen application layout, and wired the supplied ICO plus brand asset directory into the existing PyInstaller specification.
- Added focused integrity, dimensions, alpha, ICO-size, theme-reference, splash-reference, and packaging-reference tests; no Task, Result, Delivery, processing, Settings, or formal-directory contract changed.

## 2026-08-11 - Batch image naming N2 product loop

- Added the existing Smart Delivery page's raw-image naming path for 1-to-30 local PNG/JPG/JPEG imports, three naming modes, optional local reference-file guidance, per-item local analysis/retry/edit/delete, order changes, and server-authoritative 01-to-30 previews.
- Added a dedicated product-layer preflight and copy-only execution path at `输出/智能交付/图片批量命名`; collisions and invalid items remain unwritten without stopping unrelated ready items, while every completed copy is verified byte-identical to its imported source.
- Preserved the frozen N1 engine and existing Result-to-Delivery semantics; no raw import is fabricated as a Result or Delivery mapping, no provenance metadata is written, and no Settings or formal-root policy changed.

## 2026-08-11 - V0.5.5-dev content naming N1 core

- Added decoupled Content Descriptor, Windows-local Simplified Chinese OCR adapter, Batch Naming Context, Naming Policy, and Filename Suggestion layers; observation evidence, text guidance, and user-confirmed overrides remain structurally separate.
- Added smart, project, and custom filename policies with user-visible order sequencing, 2-to-8 Chinese-character content-name validation, extension preservation, Windows safety gates, low-confidence confirmation state, and a 30-item V1 product limit outside the scalable core engine.
- N1-R1 replaced the product endpoint's heuristic classifier with a replaceable local Florence-2 adapter pinned to revision `f6c1a25888ffc1d945ee8a1a77ac833c7303d46e`; runtime loading is offline-only and verifies model/runtime-code hashes before executing the pinned local snapshot.
- OCR text without reliable confidence is retained only as observation evidence and cannot enter naming candidates; text references require an explicit visual or filtered OCR candidate and never become fact authority.
- Verified five real natural/commercial images across meeting space, speaker action, electronics display, automobile, and commercial interior; actual model semantics flowed through Content Descriptor to 2-to-8-character Chinese names while source SHA256 and mtime remained unchanged.
- Verified the formal RESULT_ID content-naming endpoint uses the same local semantic core, rejects 31-item V1 requests, preserves user overrides and the three naming policies, and keeps the lower-level formatter scalable beyond 30 items and two digits. Commercial fine-grained naming quality remains pending N2 human review.
- Closed the N1-R1 product-gate audit blocker: formal content-mode preflight now authoritatively normalizes numbering to enabled/start 1/two digits, rejects item 31, requires one `{seq}` token, and reuses the normalized plan during Delivery Copy execution; non-content delivery numbering remains configurable. The existing UI presents the content-mode controls as disabled with an explicit 01-to-30 explanation.
- Advanced the authoritative product version source to `V0.5.5-dev`; no Settings, formal-root policy, Result-to-Delivery contract, or formal product files were changed.

## 2026-08-11 - Smart Delivery content-based batch naming V1

- Added a read-only local content-suggestion adapter that reuses the existing visual type detector and exposes only broad, explainable visual categories plus layout evidence; low-confidence images are explicitly marked for user confirmation and no person, brand, product, location, or date identity is inferred.
- Extended the existing Smart Delivery rules and server-issued preflight plan with RESULT_ID-keyed editable content names, preserving the same conflict gates, preview signature, explicit confirmation, independent Delivery Copy, SHA protection, and RESULT-to-DELIVERY trace.
- Added the minimum UI controls inside the frozen Smart Delivery page and focused API/UI/source-protection tests; no Settings, formal-root policy, processing algorithm, Task/Result contract, or parallel delivery registry was changed.

## 2026-08-10 - UI-01B formal-page title baseline closure

- Removed the redundant page-level eyebrow from the shared formal header so every primary page title starts on the same top baseline; section-level eyebrows remain available where they carry real hierarchy.
- Kept the existing shared page frame, breadcrumb alignment, title typography, and business surfaces unchanged.

## 2026-08-10 - UI-01B formal-page alignment and header rhythm closure

- Replaced the work-page-only gutter with one `hdde-page-frame` and `hdde-page-stack` contract shared by the Shell breadcrumb, processing pages, diagnosis, correction, compression, retouch, output center, smart delivery, and settings.
- Standardized the desktop left start line, page-top spacing, header-to-content gap, and responsive gutters; the existing feedback dialog keeps its modal product role while sharing the same title/description spacing rhythm.

## 2026-08-10 - UI-01B shared work-page content gutter

- Added one shared `hdde-work-page` container contract for the processing center, image diagnosis, color correction, image compression, and local retouch workspaces; the 4K entry inherits the same rule through the processing center.
- Standardized the desktop content start line to a 22px safe gutter with responsive 16px/12px fallbacks, without changing upload, processing, Task/Result/Delivery, Settings, or formal-directory behavior.

## 2026-08-10 - Formal output directory naming closure

- Unified new formal output paths to `输出/4K高清增强`, `输出/1080P标准增强`, `输出/1080P安全增强`, `输出/颜色校正`, `输出/图片压缩`, `输出/标记修整`, and `输出/智能交付`; the 4K processing mode remains `4K高清画质增强`.
- Migrated the existing `4K增强` and `1080P标准版` directories by same-volume atomic rename after conflict preflight. All 79 files retained identical SHA256 values; no target was overwritten.
- Added compatibility resolution for historical Task/Result paths while new records use the formal names, and updated only the two directly related Settings path fields.

## 2026-08-10 - UI-01B formal-page rollout and redundancy closure

- 延续 UI-01A 精密工作台语言，将共享页面层级推广到图片压缩、颜色校正、标记修整、智能交付与既有详情/对比/报告页面；跨页面导航同时复位内容滚动位置。
- 处理中心将四步准备区收口为连续流程并移除重复任务标题；系统设置将五个重复信息区收敛为外观、本地目录、产品与版本三个权威区块；输出中心空状态补齐原因与下一步入口。
- 标记修整空载画布改为中性网格工作区，已载入图片仍使用既有深色画布；输出中心与反馈展示统一为正式增强命名，未修改处理算法、Task/Result/Delivery 合同或正式目录。

## 2026-08-10 - UI-01A precision workspace foundation

- 以品牌蓝 `#2D6FE8` 和中性表面建立明暗双主题语义令牌、统一字号/间距/圆角/焦点/禁用/低动效合同，并新增共享页面标题与本地图标组件。
- App Shell 收口为“工作台 / 图片处理 / 交付 / 系统”四组正式导航，移除导航状态徽标和重复页面标题信息；任务队列、历史任务、批量优化未恢复为一级入口。
- 图片诊断、输出中心、系统设置作为代表页接入统一页面结构；图片压缩、图片诊断、系统设置移除错误 Beta 身份，1080P正式命名统一为标准增强与安全增强。

## 2026-08-10 - Image Diagnosis V1 D2 product loop

- 新增一级“图片诊断”入口和正式页面，按结论、关键问题、技术证据三层呈现冻结D1真实结果，并将D1推荐原样映射到既有4K、1080P、颜色校正与图片压缩入口。
- `image_diagnosis` 在调用D1引擎前写入共享Task Registry，完成后在同一Task登记独立结构化Result；不生成无意义图片副本，不进入输出中心，也不建立平行Task/Result系统。
- 推荐动作通过浏览器内存中的当前`File`上下文交给既有正式页面，仅完成安全接收和模式预选，不自动执行处理；处理中心、历史任务、Runtime Log与Feedback Context继续消费统一事实源。

## 2026-08-10 - Image Diagnosis V1 D1 core

- Added a read-only `engine.image_diagnosis` boundary with a Pillow/OpenCV adapter, structured image facts, explainable quality issues, and evidence-based recommended actions; D1 does not create tasks, results, deliveries, or formal output files.
- Added conservative resolution, blur, noise, JPEG blockiness, exposure, highlight, shadow, white-balance, and color-cast diagnostics without a composite quality score or automatic processing.
- Added focused synthetic-sample tests for facts/EXIF/alpha, clear versus blurred content, exposure direction, color cast, noise, JPEG compression artifacts, recommendation consistency, and source SHA256/mtime protection.

## 2026-08-10 - F3 unified framework closure

- 1080P/4K、颜色校正、图片压缩与局部修整统一补齐FEATURE、TASK、RESULT事实字段；输出中心和智能交付继续复用既有合同，并将DELIVERY_ID回写到对应共享Task事实，未新增平行Registry。
- 处理中心在同一页面承载“当前任务 / 历史任务”，历史记录直接读取共享Task/Result/Delivery事实；任务队列、历史任务、批量优化兼容路由继续保留，但不再生成一级导航，既有批量队列与失败重试路径未删除。
- 现有Runtime Log补齐统一生命周期事件与product/test标识；Feedback Context统一携带真实版本、功能、任务、结果、交付、终态和正式目录状态，同时保持图片正文、完整日志及无关敏感数据隔离。

## 2026-08-10 - B-07 unified user feedback exit

- 全局、颜色校正、任务详情与质量报告入口统一复用同一反馈组件、上下文快照API和现有Feedback Context/ZIP生成器；用户打开反馈时冻结真实Task/Error/Runtime事实，后续轮询或任务变化不再改变反馈对象。
- 标准反馈合同升级为`HDDE-user-feedback-v2`，明确反馈包ID、合同版本、生成/捕获时间，包内自带有限相关事件、异常摘要、安全输入元数据、附件与隐私清单，不依赖继续读取用户`hdde.log`、Settings或任务目录。
- 前端仍可打开而后端不可达时，同一流程生成同合同的最低可用本地JSON反馈包；未知Task/Result保持不可用，附件只记录用户主动选择的脱敏技术清单且不自动加入或上传。
- 1080P安全报告与图片压缩页遗留的用户反馈按钮改接同一`UnifiedFeedback`流程；旧后端反馈API仅保留内部兼容，不再由当前用户入口直接调用，1080P历史基线与处理逻辑不变。
- 统一反馈包生成补齐独立`IDLE → GENERATING → SUCCESS/FAILED`交互状态：生成时禁用防重，成功时在操作区附近持续显示安全文件名与大小，后端不可达时明确标识本地安全降级，失败时显示脱敏原因、可用`ERROR_ID`并支持重新生成；反馈合同、B-06日志合同与A线处理逻辑不变。

## 2026-08-10 - B-06 precise local fault correlation

- 继续复用 `hdde.runtime`，在首次日志前建立每次应用运行唯一的 `RUNTIME_ID`，并由启动完成事件固定关联现有产品版本与B-01 Build ID；测试和Playwright可通过隔离运行根将日志物理写入临时目标，不接触正式 `hdde.log`。
- 真正程序异常新增可传播复用的 `ERROR_ID`、稳定脱敏 `ERROR_FINGERPRINT`、`TRACE_ID`、项目相对代码位置及少量调用摘要；同一根异常跨阶段重复记录时保持同一错误身份，普通成功和用户操作警告不生成错误身份。
- 颜色校正任务冻结功能、目的、批次、路由与安全源引用，反馈上下文只携带相关少量事件、安全图片技术元数据及诊断身份；完整业务文件名、绝对路径、敏感值、图片与完整日志均不进入诊断反馈。

## 2026-08-10 - F1 local-retouch unified feature/task/result chain

- `local_retouch` 使用稳定 `feature_key`，每次处理在调用现有 `LocalRetouchEngine → LamaOnnxAdapter` 前先向共享Task Registry登记独立 `retouch_task_*`，并保留pending、processing、completed/failed生命周期与源文件关系。
- Engine成功只生成临时Preview，不创建正式结果；人工确认保存后才生成独立 `retouch_result_*`，并在同一Task记录中建立 `SOURCE → TASK → RESULT`，新Task ID与Result ID严格分离。
- 处理中心继续读取现有 `/api/v1/tasks` 和共享Registry；`/tasks`兼容路由保留但不进入一级导航，未新增任务系统或修改LaMa、Mask、输出中心、智能交付及正式启动链。

## 2026-08-10 - F2 unified result to smart-delivery closure

- 输出中心从共享Task/Result Registry识别完整 `result_id`、`task_id`、`feature_key`、`source`、`result_file`，并将满足合同的正式结果标记为Unified Result；历史输出项继续兼容读取，未新增Output Registry。
- 智能交付新增 `result_ids` 正式输入并在服务端解析回真实输出中心成品；输出中心选择Unified Result后自动传递RESULT_ID，用户无需手工输入ID、路径或JSON。
- 交付记录以源 `result_id` 关联独立 `delivery_id` 和 `delivery_item_id`，同时保留TASK、FEATURE、SOURCE追溯；既有命名预检、冲突阻断、独占副本写入和源文件保护合同保持不变。

## 2026-08-10 - B-05 recent-feature runtime logging closure

- 复用现有 `hdde.runtime` 与正式 `诊断/日志/hdde.log`，为单图颜色校正、批处理队列、人工结果确认和B-04反馈报告生成补齐最低必要的开始、完成、失败及真实TASK_ID/BATCH_ID关联；不存在的RESULT_ID继续保持不存在。
- 处理中心与正式启动/依赖/目录异常继续复用既有正式日志；输出中心、智能交付和局部修整按A线边界标记 `DEFERRED_BY_A_LINE`，未修改其业务核心或结果关系。
- 正式日志新增统一绝对路径和敏感键值脱敏，保留安全文件名或 `诊断/日志/hdde.log` 引用；未建立第二套日志协议，也未将完整日志写入反馈包。

## 2026-08-10 - Delivery marker and local retouch V1 smart-delivery closure

- 局部修整正式结果继续复用阶段6智能交付；预检要求有效共享 `RESULT_ID` 与 `task_registry` 映射，拒绝仅凭目录文件或文件名进入交付。
- 智能交付预览与执行响应透传源正式结果ID和处理类型，执行结果同时绑定真实 `DELIVERY_ID`，形成可追溯的 `SOURCE → RETOUCH RESULT → DELIVERY COPY` 关系；既有命名、冲突和副本完整性合同保持不变。

## 2026-08-10 - B-04 unified recent-feature feedback context

- 新增共享只读 `Feedback Context` 事实适配器，复用现有任务ZIP反馈包与颜色校正JSON反馈报告，统一记录真实功能来源、阶段、状态、现有TASK_ID/RESULT_ID、安全文件引用及B-01/B-02/B-03运行摘要；不存在的业务事实保持为空，不生成虚假标识。
- 单图颜色校正、批处理/任务队列、处理中心、对比质检与运行异常完成覆盖；输出中心、智能交付、局部修整按A线边界标记 `DEFERRED_BY_A_LINE`，未修改其业务核心。
- 现有颜色校正反馈卡片增加脱敏上下文预览与本地附件主动选择提示；附件不写入报告、不自动上传，仍由用户决定是否随报告发送。

## 2026-08-09 - B-03 side-effect-free health check

- `GET /api/health` 不再调用会执行写探针的工作目录解析链，改为复用B-02启动校验快照与当前只读存在性检查；连续健康检查不创建临时探针文件、不改变Settings或正式目录元数据。
- 保留既有健康响应和路径字段，并以 `healthy`、`directory_ready`、`settings_status` 及 `degraded` 状态表达真实故障，不将不可写性伪装为永远健康。

## 2026-08-09 - B-02 unified read-only runtime status

- 新增只读 `GET /api/runtime/status`，统一返回现有产品版本、已编译Build ID、应用运行状态、Settings启动加载状态及正式根目录启动校验与当前只读存在性状态。
- Build ID直接读取B-01前端产物，不在运行时调用Git或生成新构建号；状态请求不写Settings、不探测写入、不创建或修复正式目录，也不回退项目tmp。

## 2026-08-09 - V0.5.4-dev unified version and build identity automation

- 将 `product_version.json` 的统一运行身份更新为 `V0.5.4-dev`，系统设置的平台信息与更新信息继续从同一版本源自动读取；版本工具最小增加 `-dev` 预发布标识支持。
- 当前构建改由Vite在构建时固定注入，包含产品版本、Git短SHA、工作区clean/dirty状态和UTC构建时间；同一产物稳定，新构建自动变化，正式页面运行时不读取Git或当前时间。
- 将平台信息中的“目标分辨率”改名为“默认交付分辨率”，准确表达默认1080P配置而不否认独立4K尺寸适配能力；历史 `1080P研究基线 V0.4.6 RC8A` 保持不变。

## 2026-08-02 - V0.5.4-dev Stage 2 visual quality closure V2

- 将颜色校正核心升级为自适应曝光与色调、可信中性色白平衡、选择性色彩平衡、局部层次与受控清晰度处理；所有动作仍只调整现有像素，不改变尺寸、构图、Alpha或内容。
- 会议逆光改为人物/前景与高亮背景独立度量和处理，结果报告记录两者真实增益；新增肤色、高亮背景、暗部噪声及低调设计色彩意图保护，避免普通图和黑金设计图被强行提亮或改色。
- 正式默认输出合同经代码确认仍为`D:\影界文件\输出\颜色校正`，无需修改Settings或目录逻辑；本轮A/B/C三组新对比等待用户人工视觉复核，阶段2状态为`TECHNICAL_PASS_VISUAL_REVIEW_REQUIRED`，未冻结且未进入阶段3。

## 2026-08-02 - V0.5.4-dev Stage 2 single-image automatic color correction

- 将`/color-correction`从占位页接入正式单图闭环：本地图片接收、正式输出目录、自动处理、前后滑杆、真实结果报告、打开结果/目录、复制路径和本地问题反馈报告。
- 新增独立可复用的单图颜色校正核心，采用中性色偏约束、受控亮度曲线、人脸/前景识别和高亮背景保护；不改变尺寸、构图、Alpha或原图，不使用生成式重绘。
- 复用阶段1同一任务注册表与`pending → processing → completed/failed`生命周期；输出完成前强制验证存在、解码、尺寸、格式、扩展名、SHA256与真实像素变化，失败不回退项目临时目录。
- 会议逆光真实样本识别11张人脸，人物/前景亮度由73.51提升至88.58，暗部风险由21.43%降至9.45%，高光风险由0.31%降至0.16%；正式输出为2133×1600 JPEG，本地反馈报告不包含图片、完整路径或外部上传。
- 颜色校正默认输出收口到正式根`输出/颜色校正`，不修改Settings；定向Python测试、前端合同测试、既有压缩生命周期回归、Vite构建和一条Playwright真实路径通过。

## 2026-08-02 - 4K half-product capability freeze

- 根据正式 `four_k_v1` 实现、既有PoC技术证据和用户人工复核结论，将4K能力冻结为 `PILLOW_LANCZOS_SAFE_RESIZE`：安全尺寸适配已完成，真实视觉增益与AI安全增益均未证明。
- `PHOTO_BALANCED` 以 `REJECTED_NO_GAIN` 退出，`CUNET_DEPTH` 以 `REJECTED_TECHNICAL` 退出；两条候选均不接入正式产品，保留LANCZOS安全路线，未来4K增强研究延期。
- 用户可见4K页面继续仅表达高质量尺寸适配与真实输出，并明确不代表细节重建、AI超分辨率或已证明画质增益；正式4K实现、接口和输出合同未修改。
- 下一任务登记为图片压缩正式版；本轮未开始图片压缩开发。

## 2026-07-30 - 4K core processing and single-image product loop

- 在冻结权威模块中实现单图Pillow LANCZOS执行、Alpha预乘缩放、ICC保留、正式PNG原子写入、成品解码/尺寸/原图哈希核对，并通过现有`/api/upload`、任务注册表与SSE返回真实处理阶段。
- 新增`4K增强适配`单图入口，复用现有任务详情、滑杆对比和质量报告组件；4K分支仅展示尺寸适配事实与能力边界，不展示1080P评分或技术路径字段。
- 真实S01样本经产品路径生成2732×3840 PNG，滑杆交互、共享报告、Console/Network、定向Python/前端测试和Vite build通过；Settings与冻结原图哈希保持不变。

## 2026-07-30 - 4K V1 route and single-image contract freeze

- 依据阶段1冻结标准与阶段2负结论，4K V1唯一正式路线确定为`PILLOW_LANCZOS_SAFE_RESIZE`；Route A保持淘汰，Route B保持增益未证明且不进入产品路线。
- 在现有`engine.image_processing_routing`权威入口冻结`4k_v1`/`delivery_4k_v1`请求参数、长边3840与ROUND_HALF_UP尺寸规则、原图直出保护、PNG输出、任务与阻断语义，以及上传、进度、对比、报告和打开结果所需字段。
- 能力边界固定为`HIGH_QUALITY_SIZE_ADAPTATION_ONLY`：不宣称细节重建、超分辨率或已证明画质增益；本轮未接入API/UI、未运行旧PoC或生成新画质包。

## 2026-07-23 - 4K Stage 2 automatic-audit remediation and review package rebuild

- 修复候选技术状态聚合：`success`现在由来源、解码、目标尺寸、比例、格式、Alpha、几何、方向、拼块缝和结构安全十项强制门禁共同计算；任一`REVIEW/FAIL/BLOCKED/UNKNOWN`均不能成功，几何结论改由真实`transform_trace`提供证据。
- 故障探针记录路径收紧为系统临时隔离根内相对路径；写入前统一解析实际目标并拒绝绝对路径、`..`穿越、符号链接/目录联接/重解析点以及Settings、正式目录、仓库和阶段资产路径。
- Route B在权重模糊后重新施加固定3像素Alpha硬保护带；S08实测保护像素560725、保护区RGB变化0、最大RGB变化0、Alpha变化0，黑底/白底/棋盘格合成变化均为0，非保护区仍有受控增量。
- 新批次`batch_20260723T090034_audit_remediation_8b1edb4b`只读重评旧Route A并保持`REJECTED_UNSAFE`，使用原模型、原执行器和统一参数重生成8张Route B；建立16行执行矩阵、8组全图、14组ROI、28份原生100%局部、Alpha证据和新旧批次替代清单。
- 定向测试`40/40 PASS`；新包仅恢复`PENDING_HUMAN_VISUAL_REVIEW`，不证明视觉增益、不冻结阶段、不进入阶段3。原阶段2批次、阶段1资产、Settings、Skill、报告模板及AGENTS保持不变，未执行Git写操作。

## 2026-07-22 - 4K Stage 2 conservative AI enhancement PoC review package

- 使用本地RealESRGAN_x4plus ncnn Vulkan固定模型与统一参数，对阶段1冻结8张原图真实执行两条候选路线，共生成16个4K PNG；全部通过尺寸、比例、解码、Alpha、无裁切/拉伸/补边等技术门禁。
- Route A直接AI结果在中文、Logo、人物身份、皮肤/头发、材质和复杂纹理中出现结构重构，已标记为`REJECTED_STRUCTURE_UNSAFE`；Route B采用LANCZOS安全底图与受控高频增量，结构安全技术预检通过，作为唯一人工复核候选。
- 复用阶段1全部14组冻结ROI，生成8组完整对照、14组语义对照和42份原生100%裁切；Route B相对LANCZOS的真实可见增益尚未证明，状态保持`PENDING_HUMAN_VISUAL_REVIEW`和`NOT_READY`，未进入阶段3。
- 运行前后8张来源图、8份快照、24个传统候选、阶段1目录树和Settings完全一致；未接入API/UI、未创建正式4K目录或项目根`runtime_data`，未执行Git写操作。

## 2026-07-22 - 4K Stage 1 frozen standard, golden samples and traditional baseline

- 冻结4K V1基础标准：原图直出、长边3840、统一四舍五入、保持比例，禁止裁切、拉伸、补边和从1080P结果二次放大；已达4K明确返回无需处理。
- 从现有真实/历史PoC原始输入固定8张黄金样本并建立字节级快照与完整SHA256 manifest；S08半透明样本的低复杂度覆盖限制保留在清单中，未下载或生成新样本。
- 独立实验入口真实生成Pillow BICUBIC、Pillow LANCZOS、OpenCV INTER_CUBIC共24个无损PNG候选；尺寸、比例、解码、格式、Alpha和原图保护全部通过。
- 修复冻结审核发现的三项证据缺口：重建14组同归一化语义ROI对照并增加42份候选原生100%局部，反向映射最大误差0.246659原图像素；候选六阶段异常统一记录样本、方法、阶段、类型和信息，隔离CLI故障探针退出码2且不生成候选。
- 使用修正对照重新核验后，唯一传统默认基线仍为Pillow LANCZOS；S01中文样本和S03人物样本各由两个独立Python进程重新读取原图生成，文件与像素SHA256完全一致。定向测试`16/16 PASS`，未接入API/UI、未写Settings、未创建正式4K目录或项目运行回退目录。

## 2026-07-22 - V0.5.3 formal directory migration and closure

- 正式目录统一收口为 `输出/1080P标准版`、`输出/1080P安全增强`、`输出/图片压缩` 与 `诊断/日志`、`诊断/反馈包`、`诊断/报告`；活动输入和运行缓存放入对应功能目录的隐藏子目录，不再重建旧一级目录。
- 新增幂等应用数据迁移：同盘优先原子移动，复制时执行大小与流式 SHA256 校验，同内容去重、异内容安全改名，失败保留源文件，仅删除迁移后为空的旧目录。
- 启动仅在 Settings 完整有效、正式根目录就绪且保存根目录一致时检查已知旧路径；正常状态快速返回 `NO_OP`，迁移失败保持目录功能阻断且不提前写 Settings。
- 已对 `D:\影界文件` 执行真实迁移：旧目录均为空，迁移/清理后两份根文件原地保留；Settings 仅更新标准输出、安全增强输出和图片压缩输出三个旧路径字段，独立第二次执行为 `NO_OP`。
- 验证：迁移专项 `4/4 PASS`、相关 Python `py_compile` 通过；未运行前端构建、Chrome E2E、全仓回归或批量图片处理，未执行 Git 写操作。

## 2026-07-20 - V0.5.3 formal directory governance and failure blocking

- 新增两阶段统一运行日志：启动早期仅输出控制台，正式目录就绪后按需写入 `诊断/日志/hdde.log`，采用 UTF-8、约 5MB 单文件和3份轮转；接入应用启动、Settings决策、目录校验、标准图片任务、路线、输出异常、结果、错误分类与耗时，文件日志失败仅降级控制台且不回退临时目录。
- 正式根目录与必需子目录统一使用原子创建所有权判定：仅当前 `mkdir` 成功返回时登记为本轮新建；并发创建触发 `FileExistsError` 时继续目录与可写性校验，但不纳入失败清理。

- 正式根目录只读取首次正式默认目录或用户已保存并通过校验的目录；删除正式启动、标准上传与安全增强链路中的项目 `tmp` / `runtime_data` 静默回退。
- 启动校验失败不再改写 `last_app_data_root`，`/api/app/workdir` 返回明确的 `directory_ready`、错误代码与用户提示，且不返回虚假的输出目录。
- 处理中心在正式目录未就绪时显示明确错误、提供系统设置入口并禁用处理；系统设置新增“选择并校验正式目录”，只有校验通过后才持久化用户主动选择。
- 收口图片压缩 intake、预检、执行、输出与文件访问入口的统一目录门禁；目录失败时不创建或改写 Settings，异常 workdir 响应和处理中心不再暴露或开放被拒绝路径。
- 将标准、压缩与安全增强实际使用的必需子目录纳入统一就绪检查；子目录冲突、创建失败或不可写时返回明确失败路径并阻断处理，仅逆序清理本次新建且仍为空的目录。
- 产品版本更新为 V0.5.3「本地目录治理与诊断基础」。

## 2026-07-18 - V0.5.2 Stage 5 image processing preflight, frontend recommendation panel and settings closure

- 新增统一图片画像、确定性处理路由与只读 `POST /api/image-processing/preflight`，复用阶段4 source token resolver，不增加 tombstone，不创建任务或输出。
- 请求体、枚举、目标与冲突错误统一返回 HTTP 400；token 不存在、过期、角色不匹配或源文件不可用统一返回 HTTP 404 `TOKEN_NOT_FOUND_OR_EXPIRED`；冻结合同中的 `IMAGE_DECODE_FAILED` 按合同优先级保留 HTTP 422。
- 新增 `product_version.json` 单一版本源、`tools/manage_version.py` 版本更新工具及前后端 V0.5.2 一致性接线，保留历史 `V0.4.6 RC8A` 研究基线文案。
- 系统设置删除重复功能状态面板和重复二级介绍区，保留顶部主标题、主题快捷切换、左侧导航、外观设置、本地目录、更新信息与关于影界；“可修改/只读”说明下沉到对应卡片。
- 图片压缩页接入阶段5预检推荐面板，支持4种 purpose、6种 status、6种 action、24项 reason code 与10项 error code；只在用户点击后调用正式预检 API，“使用推荐方案”只预填阶段4既有参数，不自动执行。
- 前端增加请求取消、响应序号和图片/目的/参数变更失效保护；Chrome 真实服务覆盖 PNG、JPEG、上传限制、尺寸缩小、长图、未来增强、动画多帧、token 404 和解码 422，并确认无任务、输出或反馈包副作用。
- 系统设置进一步删除“配置默认输出目录”，正常状态不显示仓库内部运行路径；只有真实 `project_tmp` 回退时显示用户可读警告，不修改目录解析与持久化逻辑。
- 验证：阶段5 `66/66`（fixture `48/48`）、阶段3 `39/39`、阶段4 API `75/75`、版本 `11/11`、前端 `104/104`、Vite build、真实 HTTP 服务和 Chrome `11/11` 专项验收均通过；冻结范围 `30/30`、受保护文件 `5/5`，未暂存、commit、push、tag 或创建 PR。

## 2026-07-16 - V0.5.1 Stage 4 image compression product closure

- 新增阶段4本地图片压缩 API/UI，保持阶段3冻结50字段结果合同不变，支持 PNG无损压缩、尺寸缩小、上传适配、人工视觉复核和安全预览。
- 长图增加适合宽度、100%真实像素、全图概览、全屏、顶部/中部/底部定位、单栏原图/结果切换及宽度风险预检；无候选时不复制原图冒充结果。
- 尺寸缩小默认改为固定短边，产品层接收 `target_short_side`，按统一舍入规则计算成对宽高后交给冻结引擎；目标短边相等返回无需处理，超过原图时执行前阻止放大。
- 上传适配的最大宽度与最大高度增加可切换的长宽比锁定；锁定后修改任一边会按已选原图比例自动更新另一边，默认保持未锁定以保留长图“高度不限”和平台独立硬限制能力。
- 人工视觉复核区修正主按钮继承全局上边距导致的错位，三个结论按钮统一同一基线、宽高和内容居中。
- 修复长图切换到100%真实像素后其他查看模式可能失效：上方原图预览与下方复核预览改用独立滚动状态，并阻止程序化滚动事件反向回写形成状态循环。
- 进一步修复100%预览的真实点击阻断：预览外框固定为所在工作台列宽，原始像素图片只在内部画布滚动，工具栏不再被固有图片宽度推离可视区域。
- 输出根目录固定映射为 `PNG无损压缩`、`尺寸缩小`、`上传适配` 三个目录；新结果扁平存放，文件名保留中文并包含操作、参数、时间和短ID，不创建日期、task或单任务目录。
- 测试反馈包改为与输出图片同目录、同 `output_stem` 的 `_测试反馈包.zip`，默认不包含原图、输出图或私人绝对路径，并记录长图与固定短边验证字段。
- 补齐测试反馈包安全下载闭环：生成接口返回独立的本地显示路径与 opaque `download_url`，新增限时 `feedback_package` 角色下载令牌、ZIP类型/中文文件名/SHA校验，并在结果区提供真实下载链接、打开目录和复制路径操作；更换图片、清空、重新处理及令牌过期会清除旧链接，无候选任务可生成不含图片的诊断反馈包。
- 自动审核修正无候选诊断反馈包误用源文件 stem 的问题：诊断包现在同样包含操作、时间和短ID，同一源文件重复任务不会发生同名冲突。
- 第二轮自动审核收紧反馈包续期：过期token未经访问直接续期时旧链接仍明确返回410；续期和重复生成前必须重新核对登记路径、ZIP有效性及原SHA，禁止把被篡改的既有ZIP以新SHA重新登记。
- 第三轮自动审核关闭下载校验与实际响应之间的文件替换时间窗：下载端对同一份已捕获ZIP字节复核体积、ZIP结构和双重SHA后再返回；前端同时严格校验包名、显示路径/功能目录、有效期和布尔字段类型。
- 测试反馈包最终统一为 `summary.md`、`task.json`、严格50字段 `result.json`、`review.json`、安全 `environment.json`、`validation.json`、`warnings.json`、`manifest.json`、`manifest.sha256` 和 `evidence/README.md`；普通图不再生成长图冗余文件，只有长图额外生成 `long_image_validation.json`，总结按真实技术/视觉/交付状态动态生成。
- 双manifest对除自身外的全部包内文件使用稳定相对路径、SHA256和体积校验；真实下载继续使用独立opaque反馈令牌，ZIP默认不包含原图、输出图、token或私人绝对路径。
- 验证：阶段3回归 `39/39 PASS`、阶段4 API `75/75 PASS`、前端纯函数/会话 `68/68 PASS`、真实5173代理至8787完整闭环 `79/79 PASS`、反馈包六类真实HTTP下载 `6/6 PASS`、Vite build与 `git diff --check` 通过。
- Codex 已在 Google Chrome（Chromium）中完成真实 GUI 验收：验收记录22/22完成，原8类8/8通过、长图7/7通过、固定短边5/5通过，反馈包可见链接真实点击下载通过，并保存30张截图和25份结构化证据。视觉结论为 AI 辅助 GUI 复核，不代表用户本人复核；当前控制接口未暴露 DevTools Network，由 API、真实服务和下载自动回归补充覆盖，作为非阻断备注保留；Microsoft Edge 未单独完成专项兼容性验证。O08 验收说明“1B”与当前UI最小值“0.01KB”的文字差异已保留为备注，不改变产品行为。阶段状态更新为 `BROWSER_ACCEPTANCE: PASS_WITH_NOTES`、`FEATURE_IMPLEMENTATION: PASS_WITH_NOTES`、`FEATURE_SCOPE: FROZEN`、`STAGE_4_FINAL_STATUS: PASS_WITH_NOTES`、`STAGE_4_COMMIT_READINESS: READY`；未commit、push或tag。

## 2026-07-12 - V0.4.6 RC8A portrait route and small-text truthfulness follow-up

- 修复大面积高置信单人人像被通用fast路线提前接收，以及24人合影因高text_ratio误入全图Real-ESRGAN的问题；新增独立人物RE执行资格门禁和 `portrait_group_guard` 证据。
- 人物上下文缺少身份/结构指标时以 `evidence_missing / portrait_metrics_missing` 阻断，不再允许非人物profile掩盖人物指标缺失。
- 小字链路增加局部放大亮度细节恢复、人物ROI排除、羽化回贴、笔画宽度/结构/过冲/halo/背景侵入及矩形边界检查；候选不足或增益不成立时真实回退。
- 纯内存与固定图块共41项通过；定向01/04/05/06各运行一次。01和06人物路线修复成立；04/05小字均为0增益，05另有容器边缘保护失败，因此小文字继续阻断收口。
- 后续根因修复建立04/05已保存ROI固定调试集，引入文字行几何证据、文字结构掩膜及容器长直线排除；纹理、光点、图标和容器线可输出 `not_applicable` 且保持不变。
- 固定ROI门禁仍为 `BLOCKED`：04三组辅助小字均无正增益；05仅姓名类形成安全正增益，说明和标签仍回退。按门禁未运行04/05完整图片，候选代码不具备提交资格。
- 端到端真实性门禁将 `insufficient_gain / blocked / evidence_missing / automatic_detection_failed / boundary_unverified` 统一映射为同步结果 `BLOCKED`，不再允许 `PASS_WITH_NOTES` 或 `pass_candidate`。
- 固定ROI门禁现同时要求自动候选命中、正确角色覆盖、结构确认和真实边界证据；回退改为文字结构掩膜羽化恢复并实测边界，`reliable_text=false` 时硬禁增强。当前04/05自动检测仍未命中目标角色，因此继续阻断且未运行完整图片。
- 发布链路改为完整画布自动检测后生成带bbox、自动角色及文字/背景/容器掩膜的候选契约，同一候选对象直接驱动小文字增强；手工ROI固定标记为debug-only且无发布、端到端门禁资格。
- 小文字候选状态统一为 `candidate_not_applied / candidate_applied_then_reverted / enhanced`，回退默认精确恢复stage input；边界审核与回退事实独立。新增可达自动结构通过路径及带检测ID、bbox、输入/代码签名和证据文件的人工确认契约。
- 新增17项完整画布端到端接线测试并通过，原14项与现17项回归同时通过；本轮状态为 `PASS_END_TO_END_WIRING`，但 `allow_full_image_run=false`，未处理自动检测召回率或文字角色分组。
- 修复source与stage尺寸变化时自动bbox/三类mask坐标契约：记录source/stage尺寸与坐标空间，按独立 `scale_x/scale_y` 使用floor/ceil映射bbox，三类二值mask以最近邻映射并固定阈值；契约失败在评分和增强前阻断。
- 零候选现区分 `no_applicable_text` 与 `evidence_missing`；后者无release/end-to-end资格。边界审核改为读取完整stage/output画布，逐边比较ROI内环与框外相邻环并记录实际可测边。
- 新增23项多尺度与跨边界专项并通过，原17项接线测试改为包含2倍画布，原14项与现17项继续通过。本轮状态为 `PASS_SCALE_AND_BOUNDARY_CONTRACT`，`allow_full_image_run=false`。
- 本轮未修改Dashboard、delivery guard、`final_output_url`、JPG95、版本号或非人物画质参数，未commit/push/tag。

## 2026-07-05 - V0.4.6 RC1 delivery_light lightweight delivery copy

- Beta 在 JPG95 candidate 通过安全门后新增 `delivery_light/` 轻量交付副本，直接复制 candidate，不重新编码，不替换 PNG final。
- 新增 `light_delivery_*` 字段并同步 Dashboard / Beta 报告页与反馈包 CSV，用于区分 PNG final、JPG95 candidate 和可直接取用的小体积交付副本。
- 本轮不改变 `output_path`、`output_size_bytes`、`output_format`、`final_output_url`、delivery guard、compression gate 或标准版 final 选择逻辑。

## 2026-07-05 - V0.4.7 planning delivery naming rule engine

- 新增 `engine/delivery_naming` 独立规则命名引擎，支持用户模板、序号位数、字段来源、字段缺失标记、Windows 文件名安全清理、重名消解和 `rename_map.csv` 导出。
- 新增 `tools/experiments/delivery_naming_smoke.py`，用临时文件验证规则命名、字段缺失、非法字符清理、重名处理和映射表字段。
- 本轮不接 Dashboard UI，不修改图像增强流程、`output_path`、`final_output_url`、delivery guard、compression gate 或标准版 final 选择逻辑。

## 2026-07-02 - V0.4.6 RC1 JPG95 candidate manual review recommendation

- C-2-B 仅接入路线 B：Dashboard / Beta 报告页可记录 JPG95 candidate 人工复核建议（建议采用 / 保留 PNG / 拒绝候选 / 继续检查）。
- 反馈包 CSV 增加 JPG95 candidate review 字段与 `candidate_is_final_output=false` 记录，继续保持 `output_path`、`output_size_bytes`、`output_format` 指向 PNG final。
- 本轮不替换 final output，不改变 `final_output_url`、delivery guard、compression gate、标准版 final 选择逻辑或 JPG95 candidate 生成阈值。

## 2026-07-02 - V0.4.6 RC1 feedback package size field alignment

- 对齐 1080P 安全增强 Beta 反馈包体积字段：`image_results.csv` 优先读取 `processed` 中的 `input_size_bytes`、`output_size_bytes`、`size_ratio`、contact sheet light 与 JPG95 candidate 字段，避免 Dashboard minimal package 缺少持久输入目录时 `input_size` 回退为 0。
- `diagnostics.json` 增加 `generated_at`、branch、dirty worktree、modified/untracked 计数与 `git status --short` 摘要，用于区分反馈包采集 commit 与当前未提交工作区状态。
- 本轮只修复反馈包 / CSV / diagnostics 字段一致性，不改变 final output、JPG95 candidate 采用策略、`final_output_url`、delivery guard、compression gate 或标准版流程。

## 2026-06-29 - V0.4.6 RC1 safe 1080P Beta selected input binding

- 修复 Dashboard 1080P安全增强 Beta 处理默认测试样本而非当前队列图片的问题。
- Dashboard Beta 请求改为 multipart 上传当前队列文件，不再发送默认测试样本目录作为输入源。
- Dashboard Beta 增加 `beta_run_id`、前端点击阶段日志与 `NEED_RESELECT` 状态，真实 `File` 对象失效时阻止请求并提示重新选择。
- Dashboard Beta 日志改为首层可读文本，并为 Beta fetch 增加 300 秒超时兜底，避免永久停留在 35%。
- Beta 后端阶段日志改为有界队列异步写入，避免 stderr 输出阻塞 uvicorn worker。
- Beta 输入被安全策略跳过时，API 和 Dashboard 透出 `BETA_INPUT_SKIPPED`、具体文件名、skip reason 与 metrics，不再显示泛化失败文案。
- 修正暖色/橙色高文字密度商业图被 `skip_portrait_metrics` 误杀的问题，高文字密度且有足够边缘结构的非人像商业图可进入 Beta 增强。
- 重新选择本地图片时清理旧 Beta 失败态、旧输出与旧错误，当前队列回到待生成状态。
- Beta API 读取并回显 `beta_run_id`，新增 `BETA_API_*` 请求、字段、文件、增强与响应阶段日志。
- Dashboard Beta 增加 `selected_file_names_encoded`，避免中文文件名在 multipart 边界被转码后影响输出命名。
- Beta API 加固 multipart 字段解析、中文文件名解码、临时文件保存和结果归一化，避免异常时返回裸 500。
- Beta API 业务失败改为 HTTP 200 + `ok=false` 结构化 JSON，避免浏览器 Network 只显示 `500 Internal Server Error`。
- Dashboard Beta 点击前校验真实 `File` 对象，文件访问失效时提示重新选择并阻止无效请求。
- Beta API 增加 `BETA_REQUEST_INPUT_FILES` 与 `BETA_RESOLVED_INPUT_FILES` 阶段日志；没有显式输入文件时返回 `BETA_INPUT_MISSING`。
- `safe_1080p_enhance.py` 在 flat/business 模式下只处理显式 `input_files`，并在结果中返回 input/output 映射。
- Dashboard Beta 前台按钮改为使用 `output_path` / `results` / `enhanced_files`，复制成品路径不再依赖普通任务 `final_output_url`；对比、报告、系统诊断与 batch report 在 Beta 下禁用或隐藏并说明原因。
- Dashboard Beta 队列行 `定位`、`查看对比`、`报告` 改为 Beta 专用行为：定位同步当前队列样本，对比使用 contact sheet / output_path，报告展示轻量结果摘要和反馈包入口。
- Dashboard Beta 对比查看按标准版对比结果骨架收口，交付报告按“质量报告终审 / 本地报告中心”骨架收口，保留 Beta 本地结果映射与反馈包入口，不强接标准 QualityReportPage。
- Dashboard 增加 1080P安全增强版 Beta 核心增强任务页，使用前端阶段状态和 API 返回结果映射 Progress Timeline / BETA STAGE LOG，不强接标准 SSE。
- Dashboard 主控区收口为“图片导入 / 处理模式 / 输出文件夹 / 开始处理”任务准备条，队列、交付看板与反馈包入口统一标准版和 Beta 展示字段。
- Dashboard Beta 对比页补充 contact sheet 网页预览排查与最小接入：若返回 `contact_sheet_url` / `contact_sheet_preview_url` 等可浏览器访问 URL 则直接渲染，否则保留本地预览未接入降级态并强化说明；不改后端 API、SSE、`final_output_url` 或标准版流程。
- Dashboard Beta 提交前收口：清理旧反馈包死代码，确认 contact sheet 无可用 URL 时继续保留本地预览未接入降级态，统一 Beta 对比页版本标识与返回工作台文案；不涉及后端 API、SSE、`final_output_url`、delivery guard 或标准版流程。
- Dashboard Beta 交付报告页进行视觉减负：压缩核心质量指标展示高度，收敛本地报告中心路径信息，输出绑定改为摘要展示；不改变后端接口、标准版流程和质量字段策略。
- Dashboard Beta 补齐输出体积诊断字段：区分 final output 与 contact sheet 体积，前端展示输入体积、成品体积、体积倍率、contact sheet 体积和输出格式；本轮只统计，不改变任何压缩、格式、增强或交付策略。
- 新增输出文件体积压缩试验脚本，支持 PNG/JPG/WebP 候选体积对比，区分 final output、透明 PNG、contact sheet / preview；本轮只做实验，不改变正式交付链路、压缩策略、`final_output_url` 或 delivery guard。
- 新增压缩候选视觉 QA 守门打包脚本，生成候选对比 contact sheet、视觉风险摘要与补丁 C 候选判断；本轮只做实验 QA，不接入正式链路、不改变 `final_output_url`、delivery guard 或 compression gate。
- Beta contact sheet / preview 接入轻量 JPG90 保存，新增 `contact_sheet_light`、`contact_sheet_light_size_bytes`、`contact_sheet_light_format` 和 `preview_only` 标记；final output、`final_output_url`、delivery guard、compression gate 与正式成品保存策略不变。
- C-2-A 新增 1080P安全增强版 Beta 非透明产品广告图 JPG95 candidate，仅在 `commercial_non_portrait`、无真实 alpha、低文字密度且体积收益达标时生成；candidate 仅供人工复核，不替换 `output_path`、`final_output_url`，不改变 delivery guard、compression gate 或标准版流程。
- Beta 测试反馈包支持 Dashboard multipart minimal package，缺少持久输入目录时不再只返回 `Diagnostic feedback package blocked`。
- 测试反馈包环境信息拆分为 Windows 友好显示字段与底层诊断字段，`10.0.xxxxx` 内核版本不再作为用户系统版本展示。

## 2026-06-29 - V0.4.6 RC1 safe 1080P Beta API timeout

- 修复 `/api/beta/safe-1080p/enhance` 在 Real-ESRGAN 子进程卡住时长期不返回的问题。
- Beta 后端增加阶段日志：请求、路径解析、增强开始、Real-ESRGAN 子进程、扁平输出写入、contact sheet、响应与失败。
- Real-ESRGAN 子进程增加 `timeout_seconds=300`，超时或异常返回结构化 `FAILED` JSON，前端可进入失败态并恢复按钮。
- Beta 阶段日志、stderr tail、error message 与失败 summary 增加用户名、设备名、IP、MAC 脱敏。
- 验证：`npm.cmd run build`、`py_compile`、1 张真实图脚本 smoke、Beta API smoke、`tests/diagnostics/test_v0453_api_pipeline.py` 均通过。

## 2026-06-17 - V0.4.6 quality engine phase 1

### 已完成

- 增强小字区域识别：增加微小笔画、低分辨率中文小字和说明文字的 mask 检测。
- 增强 `text_safe` 模式下的小字局部可读性处理，仅调整 Lab 亮度通道，不重绘内容、不改色相。
- 修正文本评分，避免中文小字图出现 `text_clarity_score=0` 的失真结果。
- 增加 V0.4.6 诊断字段：`v046_text_engine_active`、`v046_quality_profile`、`before_text_region_density`、`after_text_region_density`、`text_region_density_delta`。
- 新增 `tests/diagnostics/test_v046_quality_pipeline.py`。
- 通过 V0.4.6 核心诊断与 V0.4.5.3 API/SSE 回归。

### 验证结果

- `tests/diagnostics/test_v046_quality_pipeline.py`：PASS。
- `tests/diagnostics/test_v0453_core_pipeline.py`：PASS。
- `tests/diagnostics/test_v0453_api_pipeline.py`：PASS。

### 未解决

- 普通 PNG 与中文小字图仍未完全通过 1080P 质量守门。
- 多个低分辨率小样本输出体积比例仍偏高。
- 编号核心文档仍不完整。
## 2026-09-03 - V0.5.9 T59-01 internal feedback evaluation evidence

- Extended the existing Unified Feedback V3 flow with the three-state result evaluation, conditional high-value failure reasons, explicit Task/Result/Delivery status facts, and independent source/result image consent that defaults off.
- Feedback ZIPs now record per-image consent and attachment outcomes, optionally include byte-identical validated images under `evidence/`, keep text/log generation available when evidence is missing, and continue rejecting implicit latest-task binding and absolute-path disclosure.

## 2026-09-03 - V0.5.9 W59-02 packaged Windows runtime

- Added the repeatable production release chain: Vite production assets, current FastAPI backend, PyInstaller onedir launcher, frozen-resource resolution, and an Inno Setup per-user installer script derived from `product_version.json`.
- The packaged runtime now serves the current HDDE Web UI without Node/Vite, keeps settings outside the install directory, preserves `D:\影界文件`, supports normal shutdown, and was verified with real retouch, watermark, compression, output-center, metadata, and Unified Feedback V3 flows.
- Installer compilation remains gated only by Inno Setup 6 being unavailable on the build machine; no system-level installer dependency was installed automatically.

## 2026-09-09 - V0.6.0 S60 final runtime acceptance fixes

- 将统一任务详情中的 `enhancedUrl`、顶层及嵌套 Result 预览统一绑定到任务级 `result-file` 路由，修复 4K 正式结果误走旧输出目录并返回 404。
- 处理中心历史清除按后端上限分为每批最多 100 条，支持真实大历史列表持久化清除，同时保留活动 Task、Result、Delivery 与成品文件。
- 为处理中心工作目录与颜色批次只读请求补充卸载取消，StrictMode 首次请求会中止，不再产生两次有效公共状态响应。
- 相关前端 52 项、Python 12 项、Vite production build、`py_compile` 和正式 Playwright 用户路径验证通过。

## 2026-09-10 - V0.6.0 S60-02 shared state request deduplication

- 复核确认原重复请求测量实际运行于 Vite 开发服务器；两个请求调用栈均来自 `DashboardPage` mount effect 的 React StrictMode 开发态双执行，production dist 原本各只发送一次。
- 处理中心工作目录和颜色批次共享状态改为仅复用进行中的 Promise，settle 后立即清除，不缓存旧值；保留各自唯一 owner、颜色批次轮询和 24＋50 任务分页合同。

## 2026-09-12 - V0.6.0 W60-02-P0 package data leak gate

- 将 Windows app tree 数据门禁改为 fail-closed：最终文件必须同时具备 PyInstaller `Analysis` / `COLLECT` 来源和受控根规则，未知文件不再默认归类为第三方运行时。
- 增加业务数据名称合同、个人/正式路径内容检查、嵌套 ZIP 限额，以及使用 PyInstaller 官方读取器执行 CArchive、PKG、PYZ、`base_library.zip` 实际成员扫描；普通 ZIP/WHL 在正式 `pyinstaller_work` 分支也始终扫描，并按解析后的路径 identity 对 `base_library.zip` 去重。
- 新增逐文件 provenance manifest（最终路径、分类、来源、允许规则、包内哈希、当前源哈希），程序资源仍要求显式白名单和哈希一致。
- 全新隔离 Build `W60-02-01a089c2h` 的 336 个文件与 2575 个归档成员扫描通过；归档候选发现 6、实际扫描 5、去重 1，真实 EdgeChromium 桌面生命周期、动态端口、单实例、窗口关闭回收和正式数据零污染复验通过；installer 仍未生成。
- 修复普通 ZIP/WHL 的 PYC 假阴性：PYC 结构合法不再构成信任，未提供成员级 inventory、成员路径或 archive identity 不匹配均 fail-closed；`base_library.zip` 的模块、源码与 provenance 由 PyInstaller Analysis 逐成员绑定。全新 Build `W60-02-01a089c2i` 的 336 个文件与 2575 个归档成员扫描通过，两次真实桌面启动分别使用动态端口 5686、54885，正常关窗后无监听、孤儿或系统浏览器，正式数据 BEFORE/AFTER 完全一致。
- 将可信 PyInstaller work archive 与最终 archive/member 内容强制绑定：`base_library.zip`、PKG/CArchive 和 PYZ 均记录并校验 source/final archive SHA256 及逐成员 expected/actual SHA256，任一 source 缺失、expected hash 缺失或内容不匹配即 fail-closed。全新 Build `W60-02-01a089c2j` 的 336 个文件与 2575 个归档成员全部哈希匹配；两次真实 EdgeChromium 启动使用动态端口 42369、25792，标准关窗后 Backend、监听和本次 WebView2 进程归零，正式数据 BEFORE/AFTER 完全一致。
- 补齐所有 archive member 的稳定 `ARCHIVE_TYPE`，并增加成员 manifest schema fail-closed 校验；缺失、空值、类型错误或未知 archive 枚举均使 package gate 失败。全新 Build `W60-02-01a089c2k` 的 2575 个成员缺失必需字段 0、哈希不匹配 0、未知文件 0；一次真实 EdgeChromium smoke 使用动态端口 10411，标准关窗后 Backend、监听和本次 WebView2 进程归零。

## 2026-09-14 - V0.6.1 A61-04-02 JPG Quality Gate performance

- 将 JPG Quality Gate 中不随 Candidate 变化的 Source RGB、Luma、Sobel/Laplacian、Lab 与边缘统计改为 request-local 只读预计算，大图使用临时 memmap 维持全分辨率逐像素门禁。
- 24MP ROI 搜索在同一请求内复用 5 个固定 Source ROI 分析；Candidate 仍按正式落盘文件逐个解码，最终 Winner 复检保留。
- 相同 JPG 1080P、4K、24MP 样本的 Quality Evaluation 中位数分别降低 13.061%、20.047%、8.880%，总时间分别降低 11.075%、16.231%、6.729%；Winner、候选数、门禁数、输出字节与 SHA256 保持一致。
- Python 当前合同聚焦/回归组合分别以 3/3、11/11、26/26、20/20 通过，Node 28/28 通过；旧 `test_a03_single_winner` 模块仍有 3 个未迁移断言要求 PNG `SYSTEM_AUTO` 产生 JPG 候选，与 A61-03 默认保格式合同冲突。真实 4K JPG 浏览器路径、双预览、输出中心缩略图/悬停预览及 Smart Delivery 独立副本通过。PNG/WebP 真实文件基本回归通过，未修改它们的编码策略。

## 2026-09-14 - V0.6.1 A61-05 compression advice and feedback evidence

- 图片交付结果在 `SYSTEM_AUTO` 保持源格式且收益有限或保留原图时显示次级方向性建议；建议只更新现有目标格式控件，用户再次点击生成后才复用正式 JPG / PNG / WebP 转换链，不生成隐藏候选或预计体积。
- 图片压缩反馈上下文补齐 Task / Result / Trace、格式、尺寸、真实字节与压缩率、文件名和 SHA256；全局反馈入口可绑定当前压缩结果，反馈包读取当前生效的运行日志。
- 源图与结果图继续独立默认拒绝，只有本次明确授权才复制进 ZIP；已授权但缺失、越界、读取失败或内容变化时记录具体失败代码，并保留现有反馈 ZIP 字段兼容性。
- 五类真实 API 反馈 ZIP、377 项前端回归、14 项反馈 Python 回归、生产构建及 Playwright 桌面/720px/480px 用户路径通过；输出中心 WebP 预览/缩略图与 Smart Delivery 聚焦回归通过。本轮未修改压缩算法、Quality Gate、JPEG Search 或 `SYSTEM_AUTO` 合同。

## 2026-10-03 - D61 real A/B acceptance gate check

- 当前共享源码的 D61/颜色/反馈 Python 组合 70/70、输出中心相关 Python 57/57 和独立目录 production build 通过；前端全量为 379/380、跳过 0，唯一失败是旧压缩建议测试精确限定反馈路由集合，与 D61 新增颜色任务路由的合同冲突。保留失败，没有修改生产代码或无关断言。
- 收到真实 A/B 后，在正式实例的独立 Edge 会话验证六个上传/更换/删除/模式切换检查点及普通/参考两次执行；未复现 A 被 B 覆盖，两次均 ACCEPT_ORIGINAL、明确 failed 且 Result=null，Registry 与反馈当前 Task 匹配，没有伪造输出。原图、原 34 个正式输出及 settings SHA 不变。已按用户授权把样本和证据发给 D 线继续桌面/重启验收；全量断言冲突仍阻断冻结，详见 docs/reports/D61_AB_ACCEPTANCE_20261003.md。

## 2026-10-03 - D61-ABR positive/negative acceptance closure

- 依本轮授权确认生产颜色反馈路由正确，仅对齐旧压缩建议测试的一条路由集合断言并增加说明；当前前端全量 380/380、跳过 0，D61/反馈 Python 70/70、输出中心 Python 57/57 和独立 production build 全部通过。产品源码、算法、原34个正式输出和 settings SHA 保持不变。
- 正式原生桌面十个成功 Result 的文件/Registry/输出中心/继续输入及重启持久性验证成立，既有实际 A/B 的 ACCEPT_ORIGINAL 负路径沿用。颜色页刷新会触发冻结启动器的路径检查并关闭窗口；另选真实照片的严格 ACCEPT_CORRECTED 链尚未证明。D61-ABR 保持 BLOCKED、未冻结，未修改启动器或降低门禁；详见 docs/reports/D61_ABR_FINAL_REPORT_20261003.md。

## 2026-10-03 - D61-05 desktop refresh lifecycle fix

- 本轮用户明确授权启动器最小修复：仅首次 loaded 校验 /processing，后续刷新/导航/WebView 重载不再进入启动失败分支。修复前回归真实失败，修复后启动器15/15、前端380/380无跳过、D61 Python70/70、输出中心57/57及独立 production build 通过；冻结业务源码与原34输出/settings SHA保持。
- 正式 owned-backend 原生桌面三轮各10次颜色刷新和其他页面刷新/前进后退通过，完整重开后十个既有Result卡片、缩略图、打开和继续SHA绑定通过。既有真实A/B失败空Result与跨功能反馈HTTP409保持。十次成功输入确为受控偏色夹具，另五组真实照片未产生ACCEPT_CORRECTED，不冒充真实正链。
- 正常关闭导航刷新后的原生桌面仍三次后端线程未按时退出；另两次正常关闭exit0、owned进程与端口归零不能抹去失败。当前最终关闭根因NOT_YET_CONFIRMED，未盲改超时/后台生命周期。协调D61-06只读验收同样BLOCKED；保留未归属压缩任务，不回滚并行成果。D61保持NOT_FROZEN，S61-OC-02R门禁尚未启动。详见 docs/reports/D61_05_DESKTOP_REFRESH_FIX_20261003.md。


## 2026-10-03 - D61-06 shutdown and real derivative acceptance freeze

- 正式桌面后端保持自有线程，仅局部选择Selector loop并限制Uvicorn graceful等待5秒；真实双服务幂等/隔离测试通过，首次启动与刷新合同保留。真实关闭重开10/10 exit0无所属进程残留，未强制回收。
- 真实会议原照片作B、固定亮度保持的暖色派生PNG作A，正式UI真实产生ACCEPT_CORRECTED；Source/Reference/Task/Result/正式文件SHA一致，完整重开后缩略图/打开/继续及反馈绑定通过。既有真实负路径failed且Result=null、跨功能反馈409保持。
- 启动器16+D61 70+OC57共143/143、前端380/380无跳过、独立production build通过；原34/开始48输出、原50输入、settings与冻结业务源码不变，无Git写操作。D61已冻结，立即进入S61-OC-02R只读共享复核；详见docs/reports/D61_06_SHUTDOWN_AND_REAL_POSITIVE_CLOSEOUT_20261003.md。


## 2026-10-03 - S61-OC-02R shared recheck, performance gate blocked

- 真实复现并最小修复新增缺失 Result 卡片进入活文件详情探测的问题；缺失专页跳过详情解析，保留真实卡片身份和缺失状态。只加强原有缺失测试，批次合同、算法和已冻结 D61 源码保持。
- 当前输出中心 Python57/57、前端380/380无跳过、D61相邻Python70/70及独立 production build通过。真实100MP/180MP在刷新、前后端重启、原生完整重开后卡片保持；缓存损坏重建/预览失败/缺失状态及七组49子项26Result绑定通过。原34输出、开始48输出、D61正链、原图、settings及其余共享源码SHA不变，无Git写操作。
- 正式冷首屏约930–943ms，暖重开有达标轮，但最后安静复核940.6/765.7/927.6ms含真实超标，分页仍波动。只读真实服务器剖析定位路径解析/文件探针热点，尚未证明该次波动最终归属；不修改冻结OC-01/D61来清零。S61-OC-02R=BLOCKED，OC-02未冻结，不进入下一阶段；详见docs/reports/S61_OC_02R_SHARED_RECHECK_20261003.md。


## 2026-10-04 - S61-OC-02P native warm reopen and paging closure

- 真实剖析确认列表在分页后重复枚举/stat/header，逐卡重复解析缩略图目录，批次路径被重复resolve；前端定时加载非当前页。最小复用请求内清单、缓存目录和批次路径，后页改为滚动/按钮按需读取并锁定offset；不改变九字段批次、图像算法、D61、Pillow限制或正式数据。原有测试增强单次header/缓存根读取，并对齐按需分页；无跳过。
- 正式原生WebView2连续冷首屏928.7/928.6/930.5ms；最新production额外冷屏936.6ms。五次暖重开348.1–374.1ms；十次分页60.3–98.9ms，nearest-rank P95/max98.9ms；展开17.5ms、刷新933.5ms。首12卡静置只请求当前页，最终首屏17请求/重复0/缩略图峰值4；正常完整关闭无所属残留。旧失败、重探针开销和滚动点击测量竞争证据均保留。
- 输出中心Python57/57、D61 Python70/70、前端380/380无跳过、production build全部通过。真实100MP/180MP、损坏缓存重建、预览失败、缺失卡片在刷新/前后端和原生完整重开后保持；七组49子项26唯一Result、17成功子项继续处理绑定一致。原34/当前49正式输出、隔离42输出、51原图/真实A-B、settings及其余55相关源码SHA不变；旧dist29文件已完整备份。
- STATUS=PASS_AND_FROZEN；FREEZE_STATUS=S61-OC-02已冻结。OC-00已覆盖本轮所指列表记录清理，NEXT=直接进入S61-OC-04；本轮未开发OC04、整个软件启动或安装包。无Git写操作。见docs/reports/S61_OC_02P_PERFORMANCE_CLOSEOUT_20261004.md。


## 2026-10-07 - S61-OC-03 missing records and disjoint list cleanup

- 当前/历史按后端启动时已有Task/批次身份区分，保留全部入口；普通卡、批次卡和子项增加移除记录，两个域各有清除缺失与清空列表。持久移除列表索引，保留冻结Source/Task/Result事实和正式文件；启动/读取不自动清理。明确缺失与预览/权限/SHA失败隔离，首响应同步数量、批次统计、分页和空状态，取消详情/交付/继续处理选择。
- 已移除旧Result不占用或隐藏同路径的新明确Task/Result；九字段批次合同和来源事实未改。新增卡片控件的重复渲染经旧源码/旧构建同环境只读对照定位，普通卡片以稳定引用复用，最终正式原生冷首屏925.3ms、暖239.2–380.3ms、连续10页P95/max115.4ms、展开30.1ms、刷新924.8ms，缩略图峰值4。失败与测量器竞争证据保留。
- 最终Python64/64、D61相邻70/70、前端381/381无跳过、production build通过。真实单图/压缩/水印当前历史及部分/全部清理、四轮前后端/原生窗口重启通过；暂缓后续GET仍即时更新统计、详情与空状态。七组49子项26Result和17成功子项继续处理绑定一致；原34/当前49输出、51输入、settings及冻结源码SHA保持。
- 首次验收隔离压缩配置误沿用保存目录，产生5个新增测试文件；逐项归属/SHA确认后独立移动到证据目录保留字节，未删除或覆盖原输出。后续显式配置隔离根；异常未冒充通过。正式旧服务经正常事件退出并恢复为最新构建，无正式用户记录清理、算法/缩略图安全改动、安装包或Git写操作。
- STATUS=PASS_AND_FROZEN；FREEZE_STATUS=S61-OC-03已冻结；NEXT=进入S61-OC-04。本轮新合同补齐旧OC-02P仅整卡清除的覆盖范围，旧报告保留。见docs/reports/S61_OC_03_MISSING_RECORD_CLEANUP_20261007.md。

## 2026-10-07 - S61-OC-04 multi-round Result lineage

- 真实复现处理中心移除Task后保留Result顶层父边丢失/自Task覆盖；保留原有来源五字段，复用唯一Result解析并按需查询编辑链，轮次从父边计算，不造新身份、按文件名/时间补链或修改图片算法。输出详情按需查看三轮及初始Source，迟到响应不会替换其他选择；待确认/拒绝/无输出决定不伪装成功续编。明确外层Task与feedback_target Task冲突返回409，真实分支反馈ZIP分别绑定正确Task。
- 真实照片隔离输入完成压缩→水印→压缩三轮、批次具体成功子项续编、实际失败/null后从前成功结果恢复、并行双分支；10个新增输出独立登记并解码，10份Source路径不复用、六条续编输入SHA等于父ResultSHA。至少三轮服务及原生完整重开、刷新、真实打开/续编和祖先列表移除后下游保持均通过。七组49子项26Result及17成功子项绑定不变。
- 当前tests/output全量38/38、输出合同相关64/64、D61相邻70/70、前端382/382无跳过、production build通过。正式最后冷首屏926.4ms、五次暖377.0–381.8ms、十页P95/max129.4ms、展开17.6ms、刷新921.3ms；全部20次无埋点分页P95=129.4ms，包含早期一次163.8ms失败，诊断/旧字节对照证据保留，未改冻结性能代码。原34/当前49输出、51输入、settings及其余相关源码SHA保持，正式服务恢复最新构建，无Git写操作。
- STATUS=PASS_AND_FROZEN；FREEZE_STATUS=S61-OC-04已冻结；NEXT=进入S61-OC-05最终验收。本轮分页波动更深环境归因仍未确认，OC-05继续观察。见docs/reports/S61_OC_04_MULTI_ROUND_LINEAGE_20261007.md。

## 2026-10-07 - S61-OC-05 independent final acceptance blocked

- 默认只读验收，产品源码、已有测试、settings和dist修改0。当前输出Python38/38、批次/清理64/64、前端382/382无跳过及production build通过；D61/反馈相邻两组80项79通过1失败，旧统一反馈夹具缺顶层Task.feature_key，被既有严格颜色检查返回409。未改断言、弱化检查或跳过。
- 新隔离根实际重验JPG/PNG/透明PNG/WebP/4K/24MP/100MP/180MP、损坏缓存重建、预览失败保卡、缺失及刷新/服务和原生重开；17次列表完整像素解码0，Pillow上限89,478,485保持。七组49子项26Result、成功子项操作、当前历史清理及真实多轮链复核通过；48份隔离文件独立登记并保持SHA。
- 发现OC-03真实缺陷：同路径新单图Result当轮绑定正确，重启后output_center_hidden移除事实按Registry排序覆盖真实Task的路径详情，卡片Task/Result变空。原held副本、新文件、Task事实及SHA有效；本阶段只记录准确归属，不修改冻结代码。输出中心总冻结及OC-02本轮完整共享门禁=BLOCKED。
- 无测试负载正式WebView2：连续3冷931.8/922.7/931.8ms、5暖378.6–397.0ms、20页P95=98.9ms/max105.3ms、展开16.5ms、5次刷新全部≤1000ms；5轮正常关闭重开无所属残留，正式服务恢复。原34/当前49输出、51输入、settings、受保护相关文件和原dist保持，无Git写操作。
- STATUS=BLOCKED；FREEZE_STATUS=未最终冻结；NEXT=另开OC-03同路径重启绑定最小修复阶段，反馈测试契约随后处理，修复后重跑OC-05。见docs/reports/S61_OC_05_FINAL_ACCEPTANCE_20261007.md。

## 2026-10-07 - S61-OC-03R minimal rebind and feedback fixture fix, not frozen

- 输出详情与scope两处仅4行排除output_center_hidden事实，保留旧removed_result_id/Batch Item可见性和全部来源/结果，不迁移或清空移除表。旧反馈夹具仅补顶层feature_key；新增合法/缺失/错误功能/Result冲突回归，生产D61校验不变。真实单图/水印同路径新身份经刷新及三轮服务/原生重开保持，新单图继续编辑实际生成第三轮Result。
- 当前输出41/41、合同64/64、D61及反馈81/81、前端382/382无skip及production build通过。正式3/3正常关闭无所属残留，冷928.6/938.2/922.0ms、暖359.4–374.6ms、20页P9598.4/max104ms、展开16.9ms、刷新929.5ms；正式服务恢复。原34/当前49输出、51输入、settings、48既有隔离文件及冻结源码保持SHA，原dist未改、staging空、无Git写操作。
- 批量压缩写入器持续预留旧prepared.target，缺失也生成_02新路径；父Task清理未释放预留。用户明确维持原硬门禁，不允许替代通过；未改冻结写入器、算法或Result路径。STATUS=BLOCKED，FREEZE_STATUS=NOT_FROZEN。明确该门禁与冻结预留合同后再收口本阶段，随后独立重跑OC-05；没有总冻结。见docs/reports/S61_OC_03R_REBIND_FEEDBACK_CLOSEOUT_20261007.md。


## 2026-10-15｜S61-OC-03R1｜批量压缩路径合同对齐与冻结复核

仅对齐验收测试与注释，生产代码未修改：相同来源/目录重新执行保留旧文件，允许冻结预留规则生成_02等新路径，新Task/Batch Item/Result独立，旧移除事实不覆盖新绑定。真实3张批次重建、刷新/服务重启/原生重开、续编及正常关闭3/3通过；输出41、合同64、D61/反馈81、前端382零跳过和独立production build通过；冷943/935/935ms、暖最大373.2ms、分页20次P95 98.9/max99.0ms、展开24.2ms、刷新926ms。七组49子项/26 Result及34/49/51/settings/48资产不变，staging空、无Git写操作。STATUS=PASS_AND_FROZEN；FREEZE_STATUS=S61-OC-03R已冻结；NEXT=独立重跑S61-OC-05最终验收，不宣布整个输出中心冻结。报告：docs/reports/S61_OC_03R_REBIND_FEEDBACK_CLOSEOUT_20261007.md。


## 2026-10-15｜S61-OC-05R｜输出中心最终独立验收与冻结

默认只读验收，生产代码/测试/算法/合同/原dist未修改。输出41、合同64、D61及反馈81、前端382零跳过和独立production build全通过。本轮100MP/180MP、损坏缓存重建、预览失败/缺失、服务及原生重启、父Task删除保留水印嵌套Result、列表清理、多轮谱系/双分支反馈复核通过；7组49子项26成功Result和34/49/51/settings/48资产SHA保持。正式桌面正常关闭重开5/5、所属残留0，最终服务恢复ready；冷920.5/943.7/932.9ms、暖最大376.4ms、分页20次P95/max99.0ms、展开24.3ms、5次刷新最大930.8ms。STATUS=PASS_AND_FROZEN；OC_02_CLOSEOUT=S61-OC-02已冻结；FREEZE_STATUS=V0.6.1输出中心已最终冻结；NEXT=输出中心阶段关闭，不继续修改；后续如有新需求另开版本阶段。报告：docs/reports/S61_OC_05R_FINAL_ACCEPTANCE_20261015.md。

OC-05R恢复补记：原Popen恢复实例在工具命令结束后被回收；相同正式启动器使用隐藏/breakaway启动后，两次独立健康复读持续ready。未修改生产代码，正式根与资产SHA保持；最终动态证据final-formal-ready-and-cleanup.json，门禁已闭合。


## 2026-10-27｜S62-AI4K-POC｜AI生成图4K本地忠实增强候选验证

执行者：Claude。依据已批准的《AI生成图4K本地忠实增强》原则，在隔离环境用 Real-ESRGAN x2plus/x4plus 对 9 张用户 AI 生成图断网生成 3840 长边 PNG，叠加反投影缩回锁定与文字/Logo 保护（PP-OCRv4 + 手工框）。结构门禁 9/9 通过：缩回 PSNR 45.5–65.8 dB，ΔE2000 ≤ 0.183，保护区改变 0。R1 单张 55–60 s，但 4/9 体积超过 LANCZOS 的 1.5×（最大 1.949×）；R2 单张约 200 s 且体积 5/9 超限。两路线均 REJECTED_TECHNICAL，STATUS=BLOCKED，AI_SAFE_GAIN_STATUS=NOT_PROVEN；唯一前置条件为产品负责人校准体积预算，人工视觉复核未进行。正式 4K/1080P/API/UI/Settings/输出中心/版本均未修改，样本 SHA 不变，staging 空，无 Git 写操作。报告：artifacts/s62_ai4k_poc/REPORT.md。

体积预算校准补记（同日）：产品负责人将体积预算从同图 LANCZOS 1.5× 校准为 2.0×，按已记录数据重新汇总，未重跑模型。R1 技术与结构门禁全部通过（耗时 9/9，体积 9/9，最大 1.949×），ROUTE_DECISION=PENDING_HUMAN_REVIEW；R2 仍因耗时 0/9 淘汰。STATUS=REVIEW_PACKAGE_READY，AI_SAFE_GAIN_STATUS=PENDING_HUMAN_REVIEW，等待产品负责人按 artifacts/s62_ai4k_poc/HUMAN_REVIEW.md 复核。

执行方初审补记（同日）：应产品负责人要求做视觉初审。R1 在 S07 第 1764 行存在分块接缝（细节量突变 3–9×），自动接缝门禁仅测亮度而漏检；S08 地平线轻度多线伪细节；其余多为 2× 放大可见的轻微增益。初审倾向 R1 尚未证明稳定可见增益，最终结论仍由负责人判定。证据在 artifacts/s62_ai4k_poc/review/S07、S08 的 finding_*.png。

收口补记（同日）：为闭环 S07 分块接缝，执行器改为分块 256 + 重叠 48 线性羽化融合，并新增细节突变接缝门禁（旧版对 S07 读数 4.878，可检出），全量重跑 9×2。S07 硬分界线消失（2.081，剩余为模型交叉伪纹理，非分块缺陷）；S03 亮度接缝 1.570 经成品逐边界对比为真实边缘误报；S09 R1 217.9 s 为机器负载，单独复测 65.8 s。产品负责人同意初审：R1 尚未证明稳定可见增益。STATUS=POC_VALUE_NOT_PROVEN，FINAL_STATUS=BLOCKED_NO_QUALITATIVE_GAIN，AI_SAFE_GAIN_STATUS=NOT_PROVEN，R1 REJECTED_NO_GAIN，R2 REJECTED_TECHNICAL。正式代码未改，样本 SHA 不变，staging 空，无 Git 写操作。报告：artifacts/s62_ai4k_poc/REPORT.md。


## 2026-10-27｜S63-AICOLOR 草稿｜AI生成图偏色修正原则变更稿与 PoC 任务卡

执行者：Claude。只读扫描颜色校正：正式链对 9 张 AI 样图 9/9 保持原图（场景意图全部判 HIGH），9 月真实使用 18 次中 14 次保持原图；最强固定色温档只让 b* 变化约 1；正式执行器为基础执行器，与状态文档所写 Color Core V2 不一致。据此起草 docs/drafts/S63_AI_COLOR_CAST_PRINCIPLE_AND_POC_CARD_DRAFT.md（待负责人批准），未改代码、合同、页面或正式目录，staging 空，无 Git 写操作。

批准补记（同日）：产品负责人批准《AI生成图偏色修正（可选强度）》原则变更稿与 S63-AICOLOR-POC 任务卡；等待样本放入 D:\HDDE样本\AIColor 后执行。


## 2026-10-27｜S63-AICOLOR-POC｜AI生成图偏色修正（可选强度）候选验证

执行者：Claude。按已批准原则，在隔离环境对 15 张真实 AI 图（AI4K 9 + AIColor 6；负责人未补偏色专用图，类别改由测量决定）生成轻/中/强三档：低饱和中性簇 + 分亮度 Bradford 色适应 + 两端锚定灰雾曲线，单张三档 0.1–2.9 s。正式链基线 15/15 保持原图。通过：几何/ICC 15/15、三档递增 8/8、耗时。未过：中档 ΔE00≥3 仅 3/8；对照 S08 3.9>1.5；裁切 S02 中/强、S12 强超 0.5%；S02 肤色强档发粉（b* 20→4.6）。STATUS=BLOCKED，需一轮有界修复（肤色保护、强档溢出、分段估计收紧、暗部钉点）。样本 SHA 不变，正式链/页面/正式目录未改，staging 空，无 Git 写操作。报告：artifacts/s63_aicolor_poc/REPORT.md。

修复轮补记（同日）：经负责人批准，完成肤色保护（人脸邻域肤色保留 80%）、强档溢出（柔和收顶 0.995、暗部连续收底）、分段估计收紧（距全局中性 ≤9、≥4 格分布，分类同口径）、暗部钉点改外推，全量重跑 15 张。几何 15/15、三档递增 10/10、对照 5/5、裁切 0 违规、肤色 0 违规、最大 2.9 s 全部通过；仅中档可见度（整图平均 ΔE00≥3）4/10 未过，中性区口径为 7/10。STATUS=BLOCKED，需负责人校准该门禁口径（只需重新汇总，不用重跑）。复核包已就绪。正式链/页面/正式目录未改，样本 SHA 不变，staging 空，无 Git 写操作。

门禁校准补记（同日）：负责人将中档可见度门禁改为"中性区平均 ΔE00≥3 作预检，最终以人工复核为准"。执行器与 --resummarize 同步更新，按已保存成品重新汇总（未重跑）：预检 7/10，S03/S06/S11 标记待人工判定；其余门禁不变（全部通过）。STATUS=REVIEW_PACKAGE_READY，等待负责人按 artifacts/s63_aicolor_poc/HUMAN_REVIEW.md 复核。

收口补记（2026-10-28）：负责人授权执行方代为整体判定。15 张中有一档比原图好且可直接使用的为 3/10（S01、S02、S09 中档），低于冻结标准 ≥8/10；对照 5/5 未改坏，无任何伤害（S06 修正后质感变差，判为不能用）。主因是测量无法区分设计用色和偏色（7 张设计色调图被当成偏色），而不是修正能力。STATUS=POC_VALUE_NOT_PROVEN，FINAL_STATUS=BLOCKED_NO_QUALITATIVE_GAIN，复核权威记为 OWNER_DELEGATED_TO_EXECUTOR。正式链/页面/正式目录未改，样本 SHA 不变，staging 空，无 Git 写操作。


## 2026-10-28｜S64 草稿｜AI图挑档校色正式集成决策与两阶段任务卡

执行者：Claude。负责人同意改为"用户说修才修、修多少由用户挑"。起草 docs/drafts/S64_AI_COLOR_LEVEL_PICK_INTEGRATION_CARDS_DRAFT.md：第三种模式挑档校色（原图/轻/中/强预览，用户选定即人工确认交付，不新增 FinalAction），S64-A 后端与接口、S64-B 页面与真实桌面验收。待负责人批准；未改代码，staging 空，无 Git 写操作。

## 2026-10-28｜S64-A｜挑档校色后端与接口

执行者：Claude。新增 engine/color_correction/level_pick.py（S63 冻结方法的正式实现，支持 Alpha），以及 /api/color-correction/level-preview、level-run：预览存入受管缓存并只在本进程有效；选档后从源图重新渲染，像素摘要须与预览一致才写入正式 `输出\颜色校正`；结果复用人工确认交付（REVIEW_REQUIRED + REVIEW_CANDIDATE + confirmed + HUMAN_CONFIRMED_REVIEW）；选原图时不生成文件。原颜色任务的失败处理抽成共享函数，原有行为不变。开发中发现多线程并发 OpenBLAS 在 4K 上崩溃，改用 einsum 后连续 20 次无崩溃，与 S63 有 244 个像素差 1/255（ΔE00≤0.00006）。验证：15 张样本 14 档结果全部与预览逐像素一致、进入输出中心且可交付，选原图 0 文件；新测试 18/18；Python 80 个模块、1179 项，8 个失败模块与基线一致（唯一相关的 test_source_asset_lifecycle 用改动前 API 复现同样 3 项失败）；前端 382/382。4K 预览空闲时 4.1–4.9 s，负载下 10–16 s，未稳定满足 ≤5 s。STATUS=BLOCKED，待负责人裁定该门禁。页面未改，staging 空，无 Git 写操作，D:\影界文件 无写入。报告：artifacts/s64a_level_pick/REPORT.md。

S64-A 冻结补记（同日）：负责人接受 4K 预览耗时现状（常规尺寸 ≤5 s；4K 空闲时达标、负载下变慢）。S64-A=PASS_AND_FROZEN，开始 S64-B。

## 2026-10-28｜S64-B｜挑档校色页面与真实桌面验收

执行者：Claude。颜色校正页新增"挑档校色"：选一张图 → 四档并排预览（测量提示、系统建议、原尺寸放大）→ 选档生成结果并跳到统一结果页；选原图不生成文件。统一结果页识别挑档模式：选档即确认但不算已复核，显示"交付所选结果"，交付完成后不重复。真实桌面验收（正式 WebView2，CDP 驱动）中发现预览缓存泄漏（重启后遗留目录不清理、已用预览未删），已修复：用后即删，遗留目录超过 1 小时后自动清理。第二轮验收：S01、S02 选中档各生成 1 个结果，SHA 一致；S06 选原图 0 文件；刷新与返回不产生文件；输出中心打开成品返回 200；控制台 0 错误。前端 387/387，颜色后端 76 项全过，production build 通过（旧 dist 已备份）。结果按用户设置写入 D:\定制业务\政法委\新版\输出\颜色校正（两轮共 4 个验收文件）。STATUS=REVIEW_PACKAGE_READY，待负责人在真实软件中视觉签收。staging 空，无 Git 写操作。报告：artifacts/s64b_level_pick/REPORT.md。

S64-B 冻结补记（同日）：产品负责人签收挑档校色页面。S64-B=PASS_AND_FROZEN，S64（挑档校色）整体完成。


## 2026-10-28｜S65 草稿｜参考图挑档校色原则补充与 PoC 任务卡

执行者：Claude。只读扫描现有参考图校色：10 组测试（8 组以干净原图作参考、有标准答案）中 5 组保持原图、5 组改动不可见（ΔE00 0.2–0.6），离正确颜色最多近约 4%；8/10 组因“缺少共同中性色锚点”关闭颜色匹配。据此起草 docs/drafts/S65_REFERENCE_LEVEL_PICK_PRINCIPLE_AND_POC_CARD_DRAFT.md（待负责人批准）。未改代码，未触碰 4K 文件，staging 空，无 Git 写操作。

## 2026-10-28｜S65-REFCOLOR-POC｜参考图挑档校色第一轮

执行者：Claude。隔离执行器 tools/experiments/s65_refcolor_poc.py（只读复用 level_pick 内部函数）。33 组测试：24 组有标准答案（8 张图 × 偏黄/偏蓝/偏绿，参考为干净原图）、4 组同系列、3 组参考即自身、2 组色调一致。R1（白平衡匹配）明显强于现有参考图校色（后者 17/24 保持原图），但强档缩小 ≥60% 仅约 9/24，偏黄失败（S05 反向 +122%）；同系列门店组几乎无效。R2（加明暗匹配）有害，淘汰。根因：目标图与参考图各自独立选择中性色，偏色后选中不同表面。STATUS=BLOCKED，提议一轮有界修正：改为低饱和 a*b* 分布对齐、取消白端钉为中性、淘汰 R2。真实配对未提供。正式代码与 4K 文件未改，staging 空，无 Git 写操作。报告：artifacts/s65_refcolor_poc/REPORT.md。

S65 修正轮补记（同日）：经负责人批准，把中性色配对改为低饱和像素在对数色度空间的分布对齐（分三个亮度段，偏离整图过大的段回退到整图，不再钉白，R2 淘汰），全量重跑 33 组。R3 在有标准答案组中强档缩小 ≥60% 达 21/24、中档 ≥40% 达 22/24，三档 24/24 单调；现有参考图校色 0/24。参考即自身 3/3 通过；同系列 1/4、色调一致 1/2 未过，经实测发现门店两图的白本身不同，测试前提不成立。三档用时中位 1.5 s。STATUS=BLOCKED，待负责人裁定门禁口径（以人工复核为准或接受 21/24）。正式代码与 4K 文件未改，staging 空，无 Git 写操作。

S65 复核收口（同日）：负责人裁定门禁口径（有标准答案组接受 21/24、22/24，同系列与色调一致组以人工复核为准），并授权执行方代判。同系列 3/4=75% 有一档明显优于现有参考图校色、可直接使用，达标；无伤害。R3 路线 ACCEPTED，STATUS=REVIEW_PACKAGE_READY（价值成立，真实配对未验证）。正式接入需另开集成阶段。

## 2026-10-28｜S66 草稿｜参考图挑档校色正式接入决策与两阶段任务卡

执行者：Claude。基线 HEAD 已变为 39c591f（负责人提交，含此前颜色成果）。起草 docs/drafts/S66_REFERENCE_LEVEL_PICK_INTEGRATION_CARDS_DRAFT.md：建议用新流程升级“参考图校色”页签（旧 reference-run 后端保留不再调用），S66-A 后端与接口、S66-B 页面与真实桌面验收；写入与并行 4K 工作的共享文件协调规则。待负责人批准，未改代码，staging 空，无 Git 写操作。

## 2026-10-28｜S66-A｜参考图挑档后端与接口

执行者：Claude。新增 engine/color_correction/reference_level_pick.py（S65 R3 的正式实现，加 Alpha 处理）；level-preview 增加可选 reference_source_token，level-run 复核参考图 SHA，新运行模式 REFERENCE_LEVEL_PICK_COLOR_CORRECTION，复用 S64 会话、写入与人工确认交付。改动 API 前已确认该文件无他人未提交改动，未触碰 4K 文件。验证：33 组 99 档与 S65 逐像素一致；25 个选档结果与预览一致并进入输出中心可交付，8 组选原图 0 文件；参考图 SHA 全部不变、不进入输出中心；新测试 11/11，挑档校色 19/19；全量 81 个模块，失败 9 个（8 个同基线，新增 1 个为 4K 路由变化所致）。预览耗时空闲 1.8–2.4 s，处理器降频（约 55% 性能）或并行任务时 5.5–7 s。STATUS=BLOCKED，待负责人裁定耗时门禁。staging 空，无 Git 写操作。报告：artifacts/s66a_reference_level_pick/REPORT.md。

S66-A 冻结补记（同日）：负责人接受预览耗时现状（空闲达标，降频或负载下变慢）。S66-A=PASS_AND_FROZEN。S66-B 尚未开始，开始前须与并行进行的输出中心、4K 改动协调。

## 2026-10-28｜S66-B｜参考图挑档页面与真实桌面验收

执行者：Claude。按方案 A 改造 ColorCorrectionPage、TaskDetailPage、App、productDisplay、DashboardPage 与两个前端测试：参考图页签走 level-preview（带 reference_source_token）四档挑选，页面不再调用 reference-run；新模式 REFERENCE_LEVEL_PICK_COLOR_CORRECTION 沿用挑档交付语义，并以三图对照展示。经负责人确认重建 dist（附带他人未提交的 OutputCenterPage 轮次名称改动），旧 dist 已备份。真实桌面（8797；8787 被他人服务占用，未动）4 组：中、强两组生成结果，SHA 一致、参考图 SHA 已记录、可交付；选原图和不可用参考图两组 0 文件；全程未调用 reference-run，控制台 0 错误，输出中心无参考图，预览缓存无残留，输入图 SHA 不变。验收中修正：不可用参考图下被锁定的档位，原先误提示"未通过安全检查"，改为"参考图不可用，不可选"，重建后复验通过。前端 387/387，API 30/30。STATUS=REVIEW_PACKAGE_READY，待签收。staging 空，无 Git 写操作。报告：artifacts/s66b_reference_level_pick/REPORT.md。

S66-B 冻结补记（同日）：负责人签收。S66-B=PASS_AND_FROZEN，S66 参考图挑档（后端 + 页面）整体冻结。staging 空，无 Git 写操作。
