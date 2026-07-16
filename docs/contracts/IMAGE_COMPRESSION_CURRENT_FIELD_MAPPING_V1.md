# 影界 HDDE｜图片压缩三项能力当前字段映射 v1

```text
document_status: CURRENT_STATE_FREEZE
evidence_base_commit: 8764b2be09f977736eb66523a8efe1be7463c5be
target_contract_version: hdde.image-task.v1
target_result_contract_version: hdde.image-result.v1
evidence_level: A
implementation_status: NOT_IMPLEMENTED
```

## 1. 文档边界

本文档冻结无损压缩、尺寸缩小、上传适配三项 PoC 在证据基线上的真实字段和迁移映射。它不是统一合同的正式实现，不代表正式 Python 合同类、状态枚举、路由器、执行器、原子保存、反馈包、UI、API、SSE 或 pipeline 已经存在。

本文档中的现状结论为 A 级证据；所有目标合同字段和迁移方案均为 D 级提案，不得写成现有正式能力。

权威证据：

- 无损压缩提交：`700373fcb7b6f6d742d9241cb75e18dd1230622e`
- 尺寸缩小提交：`1c237fb2539b381faa65105100f7ea83cc07cd9d`
- 上传适配冻结提交：`8764b2be09f977736eb66523a8efe1be7463c5be`
- 无损正式运行：`tmp/image_compression_poc_v1/20260713_122537`
- 尺寸缩小正式运行：`tmp/image_resize_poc_v1/20260713_150702`
- 上传适配正式运行：`tmp/image_upload_adaptation_poc_v1/20260715_153812`
- 上传适配最终回放：`tmp/image_upload_adaptation_delivery_gate_replay_v1/20260716_071239`

## 2. 三项能力现状接口

### 2.1 无损压缩

- 当前入口：`tools/experiments/image_compression_lossless_poc.py` 的最终静态 PNG robustness 入口。
- 当前输入来源：`--run-dir`、兼容参数 `--png-robustness`、脚本内固定业务 PNG 和受控边界样本；没有任务合同。
- 当前主结果字段（37）：`sample_id`、`sample_group`、`sample_type`、`original_path`、`candidate_path`、`original_size_bytes`、`candidate_size_bytes`、`saved_bytes`、`saved_ratio`、`elapsed_seconds`、`technical_correctness_pass`、`output_smaller`、`format_preserved`、`magic_preserved`、`dimensions_preserved`、`color_type_preserved`、`color_mode_preserved`、`channel_count_preserved`、`bit_depth_preserved`、`interlace_preserved`、`filtered_scanlines_exact`、`pixel_exact`、`alpha_exact`、`icc_preserved`、`exif_preserved`、`dpi_phys_preserved`、`xmp_preserved`、`plte_preserved`、`trns_preserved`、`all_non_idat_preserved`、`complete_decode`、`original_sha256_preserved`、`original_sha256`、`candidate_sha256`、`candidate_kept`、`failure_reason`、`final_recommendation`。
- 拒绝结果额外字段：`actual_chunk_types`、`expected_outcome`、`actual_outcome`、`rejection_reason`、`candidate_exists_after`。
- 旧字段总数：主结果与拒绝结果去重后 42。
- 技术状态表达：任务行使用 `technical_correctness_pass`；运行级使用 `overall=PASS|PARTIAL|BLOCKED|FAIL`。
- 视觉状态表达：没有三层合同中的视觉状态；严格像素、Alpha 和结构证据用于证明无需人工视觉判断。
- 交付状态表达：没有正式交付状态。
- 原图保护：处理前后核对原图 SHA256；候选只写入隔离运行目录；失败和无收益候选删除。
- 输出身份：`candidate_kept=true` 仅表示技术正确且变小的候选被保留，不等于统一合同中的正式交付身份。
- 失败行为：APNG、CRC 错误、未知 critical chunk 被拒绝；JPEG 系数级真正无损直接 BLOCKED；异常删除候选。
- 无收益行为：`fallback_optimized_no_gain` 保持原图，候选不保留。
- 元数据证据：非 IDAT chunk 字节与顺序、ICC、EXIF、DPI/pHYs、XMP、PLTE、tRNS。
- Alpha 证据：`alpha_exact`、像素精确结果及透明相关 chunk。
- SHA 证据：`png_sha256_manifest.csv`、`original_sha256`、`candidate_sha256`、`original_sha256_preserved`。
- 正式产物：`business_samples_results.csv`、`boundary_samples_results.csv`、`rejected_samples_results.csv`、`png_chunk_comparison.json`、`png_metadata_comparison.json`、`png_pixel_alpha_verification.json`、`independent_secondary_verification.json`、`png_robustness_summary.json`。

边界冻结：静态 PNG 只替换 IDAT 压缩数据；JPEG 真正无损未实现，不得降级为质量重编码。

### 2.2 尺寸缩小

- 当前入口：`tools/experiments/image_resize_downsampling_poc.py`。
- 当前输入来源：`--run-dir`、8 个固定样本、固定 `scale=0.75|0.50`、固定三方法；没有任务合同。
- 当前主结果字段（50）：`sample_id`、`sample_type`、`original_file_name`、`original_path`、`candidate_path`、`original_format`、`output_format`、`original_dimensions`、`target_dimensions`、`output_dimensions`、`scale`、`method`、`method_version`、`encoding_parameters`、`original_size_bytes`、`output_size_bytes`、`saved_bytes`、`saved_ratio`、`elapsed_seconds`、`target_dimensions_exact`、`no_enlarge`、`aspect_ratio_preserved`、`aspect_pixel_error`、`cropped`、`stretched`、`padded`、`format_preserved`、`complete_decode`、`color_mode_expected`、`alpha_clean`、`alpha_transparent_rgb_max`、`icc_preserved`、`exif_orientation_correct`、`dpi_result`、`xmp_preserved`、`jpeg_quantization_preserved`、`jpeg_sampling_preserved`、`original_sha256_preserved`、`mean_color_drift_max`、`edge_energy`、`gradient_unique_levels`、`chinese_risk`、`logo_risk`、`people_risk`、`product_packaging_risk`、`gradient_risk`、`alpha_risk`、`visual_review_status`、`final_recommendation`、`failure_reason`。
- 视觉清单额外字段：`original_overview_path`、`blind_overview_path`、`roi_name`、`original_native_crop_path`、`blind_crop_sheet_path`、`anonymous_candidate_crop_paths`。
- 旧字段总数：主结果与视觉清单去重后 56。
- 技术状态表达：没有稳定任务级技术状态；依赖空 `failure_reason`、48/48 hard gate 和独立复验。
- 视觉状态表达：固定复合文本 `100pct_blind_evidence_generated;user_confirmation_required`，不是稳定枚举。
- 交付状态表达：没有正式交付状态。
- 原图保护：所有方法和比例均直接从原图生成，最终复核原图 SHA；禁止级联缩小。
- 输出身份：方法比较候选，不是交付候选。
- 失败行为：候选检查失败写入 `failure_reason`；结构性异常可终止整次 PoC。
- 无收益行为：不适用；用户明确缩小即生成候选，未定义“体积无收益则保持原图”。
- 元数据证据：ICC、EXIF orientation、DPI、XMP、JPEG量化表、JPEG采样参数。
- Alpha 证据：预乘 Alpha 缩小、全透明像素 RGB 清零、`alpha_clean`、`alpha_transparent_rgb_max`。
- SHA 证据：`sha256_manifest.csv` 和 `original_sha256_preserved`。
- 正式产物：`resize_candidates_results.csv`、`resize_visual_review_manifest.csv`、`resize_metadata_comparison.json`、`resize_method_mapping.json`、`independent_secondary_verification.json`、盲测和原生裁切证据。

边界冻结：Pillow LANCZOS 为默认候选；INTER_AREA 仅照片类备选；BICUBIC 不进入默认路线；技术通过不等于视觉可交付。

### 2.3 上传适配

- 当前入口：`tools/experiments/image_upload_adaptation_poc.py` 的 `prepare`、`run`、`replay-delivery-gate`。
- 当前输入来源：固定 frozen manifest；任务字段为 `task_id`、`sample_id`、`scenario`、`scenario_description`、`limits`；`limits` 包含 `max_width`、`max_height`、`max_file_size_bytes`、`smax`、`dimension_candidates`。
- 技术结果字段（35）：`aspect_pixel_error`、`automatic_checks`、`candidate_count`、`failure_reason`、`final_dimensions`、`final_jpeg_quality`、`final_path`、`final_sha256`、`final_size_bytes`、`lossy`、`max_file_size_bytes`、`max_height`、`max_width`、`metadata_comparison`、`no_processing_copy_created`、`processing_seconds`、`reencoded`、`review_status`、`safety_stop`、`sample_id`、`sample_type`、`scenario`、`scenario_description`、`slowest_stage`、`smax`、`source_dimensions`、`source_format`、`source_path`、`source_sha256`、`source_size_bytes`、`stage_seconds`、`status`、`task_id`、`technical_gate_passed`、`visual_review`。
- 候选尝试字段（15）：`attempt_kind`、`dimensions`、`elapsed_seconds`、`file_size_bytes`、`generation_parent`、`jpeg_quality`、`meets_file_size`、`path`、`postprocess`、`prior_candidate_used`、`scale`、`sha256`、`source_path`、`source_sha256`、`task_id`。
- 视觉夹具字段（10）：`task_id`、`visual_review_status`、`review_notes`、`review_notes_availability`、`review_source_path`、`review_source_reference`、`review_source_sha256`、`review_source_type`、`review_note_source_path`、`review_note_source_sha256`。
- 最终回放字段（15）：`task_id`、`technical_status`、`technical_status_source`、`visual_review_status`、`delivery_gate_status`、`delivery_eligible`、`delivery_decision_reason`、`delivery_risk_reasons`、`candidate_delivery_role`、`candidate_path`、`candidate_sha256`、`source_path`、`source_sha256`、`review_notes`、`review_notes_availability`。
- 旧字段总数：上述任务、限制、技术结果、尝试、夹具和回放去重后 67。
- 技术状态表达：`NO_PROCESSING_NEEDED`、`TARGET_MET`、`TARGET_MET_WITH_REENCODE`、`CANNOT_MEET_SAFELY`，并保留异常状态候选。
- 视觉状态表达：技术结果使用 `visual_review/review_status`；最终夹具和回放使用稳定视觉枚举。
- 交付状态表达：`DELIVERY_READY`、`DELIVERY_READY_WITH_NOTES`、`REVIEW_REQUIRED`、`CANNOT_MEET_SAFELY`。
- 原图保护：frozen manifest SHA、固定源 SHA、所有候选从不可变源像素生成、最终正式资产前后清单复核。
- 输出身份：技术结果的 `final_path` 仍只是技术候选；交付身份由 `candidate_delivery_role` 和门禁结果决定。
- 失败行为：低于 PoC 搜索下限或找不到安全候选时 `CANNOT_MEET_SAFELY`；异常为处理失败。
- 无收益行为：源文件已满足限制时返回源路径，不创建副本。
- 元数据证据：`metadata_comparison` 中的 ICC、EXIF、orientation、DPI、XMP、color mode、Alpha presence。
- Alpha 证据：全透明 RGB 自动检查；半透明边缘保留为视觉风险，不能由单一自动检查放行。
- SHA 证据：源、311次尝试、23个最终技术候选、夹具、回放、正式资产保护清单。
- 正式产物：`frozen_manifest.json`、`task_results.json`、`candidate_attempts.json`、`automatic_audit.json`、`visual_review_package/`、最终 fixture、`delivery_gate_replay.json`、`validation_results.json`、`post_execution_audit.json`。

冻结交付分布：`DELIVERY_READY=11`、`DELIVERY_READY_WITH_NOTES=19`、`CANNOT_MEET_SAFELY=10`、`REVIEW_REQUIRED=0`。`real_alpha__D` 必须保持 `FAIL → CANNOT_MEET_SAFELY → delivery_eligible=false → EVIDENCE_ONLY`。

## 3. 旧字段到统一任务合同映射

下表覆盖 17 个指定旧字段或新测试字段。目标合同均为 D 级提案。

| 旧能力 | 旧字段 | 旧类型 | 旧语义 | 统一字段 | 迁移方式 | 语义损失 | 适配器 | 无法映射时处理 |
|---|---|---|---|---|---|---|---|---|
| 三项 | `sample_id` | string | 固定样本身份 | `test_case_id` + `request_context.legacy_sample_id` | 测试用例主键与样本标识分开保存 | 有 | 是 | 不猜测为正式 `task_id` |
| 上传 | `task_id` | string | 固定矩阵任务ID | `task_id` | 一一映射 | 无 | 否 | 缺失即 `TASK_ID_INVALID` |
| 上传 | `scenario` | string A–E | PoC限制场景 | `test_case_id` + `request_context.legacy_scenario` | 仅作为测试来源，不进入产品路由 | 有 | 是 | 产品请求不得接受A–E暗码 |
| 上传 | `limits.max_width` | int | 最大宽度 | `max_width` | 一一映射 | 无 | 是 | 非上传模式非空即拒绝 |
| 上传 | `limits.max_height` | int | 最大高度 | `max_height` | 一一映射 | 无 | 是 | 同上 |
| 上传 | `limits.max_file_size_bytes` | int | 最大体积 | `max_file_size_bytes` | 一一映射 | 无 | 是 | 同上 |
| 尺寸/尝试 | `scale` | number/string | 相对原图比例 | `scale_ratio` | 解析为 number | 可能 | 是 | 非法或超界即拒绝 |
| 尺寸 | `target_dimensions` | string `WxH` | 目标尺寸 | `target_width` + `target_height` | 严格解析并校验比例 | 无 | 是 | 解析失败即拒绝 |
| 尺寸 | `method` | string | 三种候选方法 | `resize_policy` | LANCZOS/AREA映射；BICUBIC仅证据记录 | 有 | 是 | 不支持的方法拒绝 |
| 尺寸 | `method_version` | string | 实验依赖版本 | `request_context.evidence_method_version` | 作为证据上下文，不作为用户策略 | 有 | 是 | 不进入执行决策 |
| 尺寸 | `encoding_parameters` | string | 实际编码参数描述 | `quality_policy` + `request_context.legacy_encoding_parameters` | 策略枚举与原始说明并存 | 有 | 是 | 不从自由文本推导安全策略 |
| 无损/尺寸 | `original_path` | string | 原图路径 | `source_path` | 一一映射 | 无 | 是 | 无法规范化即拒绝 |
| 上传 | `source_path` | string | 源文件路径 | `source_path` | 一一映射 | 无 | 否 | 缺失即拒绝 |
| 三项 | `run_dir` | path | 实验运行目录 | `run_id` + `output_directory` | 目录名成为run_id，目录路径成为输出根 | 可能 | 是 | 不能把机器绝对路径直接外发 |
| 尺寸/夹具 | `visual_review_status` | string | 复合文本或枚举视觉结论 | 无直接任务字段；测试时进入 `expected_status`/证据引用 | 不作为用户请求覆盖门禁 | 有 | 是 | 复合文本必须解析或标记未知 |
| 新测试 | `required_checks` | array[string] | 指定合同回归检查 | `required_checks` | 一一映射 | 无 | 否 | 未注册检查即拒绝 |
| 新测试 | `expected_status` | string | 测试期望状态 | `expected_status` | 仅测试作用域一一映射 | 无 | 否 | 普通产品请求携带即拒绝 |

## 4. 旧字段到统一结果合同映射

下表覆盖 34 个指定旧字段。技术候选与交付候选必须分离。

| 旧字段 | 来源 | 统一字段 | 迁移规则 | 语义损失/适配要求 |
|---|---|---|---|---|
| `original_path` | 无损/尺寸 | `source_path` | 规范化但保留源值证据 | 路径脱敏由阶段3A处理 |
| `source_path` | 上传 | `source_path` | 一一映射 | 无 |
| `candidate_path` | 无损/尺寸/回放 | `output_path` | 仅技术结果路径；角色另判 | 必须适配候选身份 |
| `final_path` | 上传技术结果 | `output_path` | 仅表示技术候选路径 | 不能据此判为可交付 |
| `original_sha256` | 无损 | `source_sha256` | 一一映射 | 无 |
| `source_sha256` | 上传 | `source_sha256` | 一一映射 | 无 |
| `candidate_sha256` | 无损/回放 | `output_sha256` | 有候选时映射 | 失败时null |
| `final_sha256` | 上传技术结果 | `output_sha256` | 一一映射 | 不赋予交付身份 |
| `original_dimensions` | 无损/尺寸 | `source_dimensions` | `WxH`解析为对象 | 需要严格适配器 |
| `source_dimensions` | 上传 | `source_dimensions` | `WxH`解析为对象 | 需要严格适配器 |
| `target_dimensions` | 尺寸 | `evidence_paths`关联的测试预期；结果以`output_dimensions`为准 | 仅保留目标证据 | 不新增结果顶层目标字段 |
| `output_dimensions` | 尺寸 | `output_dimensions` | `WxH`解析为对象 | 需要适配器 |
| `original_size_bytes` | 无损/尺寸 | `source_size_bytes` | 一一映射 | 无 |
| `source_size_bytes` | 上传 | `source_size_bytes` | 一一映射 | 无 |
| `candidate_size_bytes` | 无损 | `output_size_bytes` | 有候选时映射 | `not_applicable`必须转null |
| `final_size_bytes` | 上传 | `output_size_bytes` | 有技术候选或无需处理时映射 | 无 |
| `saved_bytes` | 无损/尺寸 | `size_reduction_bytes` | 一一映射 | 失败时null |
| `saved_ratio` | 无损/尺寸 | `size_reduction_ratio` | 解析为number | 失败时null |
| `scale` | 尺寸/尝试 | `dimension_scale_ratio` | 解析为number | 无 |
| `status` | 上传 | `technical_status` | 按统一枚举映射；`INPUT_INVALID`改为`INVALID_REQUEST` | 需要适配器 |
| `technical_correctness_pass` | 无损 | `validation_status` + `validation_failures` | true→PASS；false→FAIL；字符串不适用→NOT_RUN/null | 不能直接成为技术状态 |
| `review_status` | 上传技术结果 | 不直接映射 | 拆分到技术、视觉和交付三层 | 严重语义混合，必须适配 |
| `visual_review_status` | 尺寸/夹具/回放 | `visual_review_status` | 稳定枚举一一映射；复合文本转PENDING并保留原文证据 | 需要适配器 |
| `final_recommendation` | 无损/尺寸 | `warnings`或证据说明 | 中文建议不作为状态 | 有语义损失 |
| `failure_reason` | 三项 | `failure_reason` | 机器码与可读详情拆分 | 需派生`failure_code` |
| `automatic_checks` | 上传 | `validation_status`、`validation_failures`、`evidence_paths` | 保留完整对象并计算汇总 | 不得压成单布尔值 |
| `metadata_comparison` | 上传 | `metadata_details` | 按子项映射；无证据为null | 模式深度不同 |
| `stage_seconds` | 上传 | `stage_seconds` | 一一映射 | 无 |
| `slowest_stage` | 上传 | `slowest_stage` | 一一映射 | 无 |
| `delivery_gate_status` | 回放 | `delivery_gate_status` | 一一映射 | 无 |
| `delivery_eligible` | 回放 | `delivery_eligible` | 一一映射 | 无 |
| `candidate_delivery_role` | 回放 | `candidate_delivery_role` | 一一映射 | 无 |
| `review_notes` | 夹具/回放 | `warnings` + `evidence_paths.review` | 保留原始数组和来源 | 不得丢失来源 |
| `review_notes_availability` | 夹具/回放 | `evidence_paths.review.notes_availability` | 原值保留 | 不作为视觉状态 |

固定语义：

- 上传适配技术结果中的 `final_path` 只是候选路径。
- 只有交付门禁完成后才能确定 `candidate_delivery_role` 与 `delivery_eligible`。
- `TARGET_MET` 不等于可以交付。
- 尺寸缩小的复合 `visual_review_status` 不能直接进入统一枚举；适配后只能是 `PENDING`，除非另有正式视觉结论。
- 字符串 `not_applicable` 不能进入强类型布尔或数字字段；必须转换为 `null`，并通过明细或 `validation_status=NOT_RUN` 保留原因。

## 5. 冲突与缺失清单

1. 三套 PoC 没有统一任务入口。
2. 无损压缩缺少正式三层状态。
3. 尺寸缩小缺少统一技术状态。
4. 尺寸缩小视觉状态不是稳定枚举。
5. 上传适配 `review_status` 混合技术、视觉和无需处理语义。
6. 三套元数据检查深度不同。
7. 三套结果 JSON/CSV 结构不一致。
8. 当前没有统一 `output_created`。
9. 当前没有统一原子保存。
10. 当前没有统一诊断日志。
11. 当前绝对路径不能直接进入后续可移交反馈包。
12. JPEG 系数级真正无损仍未实现。
13. 技术候选路径和正式交付身份只在上传回放中被明确分开。
14. 无损拒绝结果的 `not_applicable` 破坏强类型字段。
15. 尺寸缩小方法比较、风险标签和正式执行策略仍混在同一结果行。

## 6. 不可丢失的正式证据

统一化时不得降级或删除：

- PNG 非 IDAT chunk 的原始字节、顺序和比较结果；
- filtered scanlines 精确证据或解码像素精确证据；
- Alpha 精确、预乘缩小、全透明像素 RGB、半透明边缘视觉证据；
- ICC、EXIF、DPI/pHYs、XMP；
- PNG PLTE、tRNS；
- JPEG 量化表和采样参数；
- 原图 SHA256 与处理后复核；
- 每个候选 SHA256 和候选来源链；
- 自动技术检查和独立二次验证；
- 人工视觉结果、备注及其来源 SHA；
- 最终交付门禁与交付资格；
- 正式运行资产保护 before/after 比较；
- `real_alpha__D` 的视觉 FAIL、`CANNOT_MEET_SAFELY`、`delivery_eligible=false`、`EVIDENCE_ONLY` 证据。

## 7. 映射统计与无法一一映射字段

- 无损压缩冻结旧字段：42；其中主结果字段37，拒绝结果新增5。
- 尺寸缩小冻结旧字段：56；其中主结果字段50，视觉清单新增6。
- 上传适配冻结旧字段：67；覆盖任务、限制、技术结果、候选尝试、视觉夹具和交付回放。
- 任务映射表：17项。
- 结果映射表：34项。

无法一一映射、必须由适配器拆分或作为证据保留：

- `sample_id`
- `scenario`
- `run_dir`
- `method_version`
- `encoding_parameters`
- 尺寸缩小复合 `visual_review_status`
- `target_dimensions`（结果侧）
- `technical_correctness_pass`
- `review_status`
- `final_recommendation`
- `automatic_checks`
- `review_notes`
- `review_notes_availability`
- `not_applicable` 字符串值

这些映射只被本文档冻结；适配器、枚举和验证逻辑留待阶段3.2及后续切片实现。

## 8. 跨文件固定命名注册表

```text
task_contract_version: hdde.image-task.v1
result_contract_version: hdde.image-result.v1
contract_fixture_version: hdde.stage3-contract-cases.v1

operation_mode:
LOSSLESS_COMPRESSION
RESIZE_REDUCTION
UPLOAD_ADAPTATION

technical_status:
INVALID_REQUEST
NO_PROCESSING_NEEDED
TARGET_MET
TARGET_MET_WITH_REENCODE
CANNOT_MEET_SAFELY
PROCESSING_FAILED

visual_review_status:
NOT_REQUIRED
PENDING
PASS
PASS_WITH_NOTES
FAIL
NOT_AVAILABLE

delivery_gate_status:
DELIVERY_READY
DELIVERY_READY_WITH_NOTES
REVIEW_REQUIRED
CANNOT_MEET_SAFELY

candidate_delivery_role:
SOURCE_NO_PROCESSING
DELIVERY_CANDIDATE
EVIDENCE_ONLY
NONE
```

本注册表仅冻结名称，不表示相应枚举代码已经实现。
