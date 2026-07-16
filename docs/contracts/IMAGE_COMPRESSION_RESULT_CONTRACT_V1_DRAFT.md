# 影界 HDDE｜图片压缩统一结果合同 v1 草案

```text
document_status: DRAFT
proposal_level: D
implementation_status: NOT_IMPLEMENTED
contract_version: hdde.image-result.v1
task_contract_version: hdde.image-task.v1
field_count: 50
evidence_base_commit: 8764b2be09f977736eb66523a8efe1be7463c5be
```

## 1. 草案边界

本文档只定义未来统一结果的字段、状态语义和旧 PoC 映射。正式结果类、序列化器、状态枚举、交付门禁、执行器、原子保存、反馈包、UI、API、SSE 和 pipeline 均未实现。

所有模式必须返回同一顶层结构。非适用、未检查和证据不足使用 `null`、空数组或明确的 `NOT_RUN/NOT_AVAILABLE`，不得使用字符串 `not_applicable` 污染布尔或数字字段。

## 2. 顶层字段定义

| 字段 | 类型 | 必填 | 来源 | 失败时值 | `NO_PROCESSING_NEEDED`时值 | 旧PoC映射 |
|---|---|---:|---|---|---|---|
| `contract_version` | string | 是 | 结果合同 | `hdde.image-result.v1` | 同左 | 新增 |
| `task_contract_version` | string | 是 | 请求合同 | `hdde.image-task.v1` | 同左 | 新增 |
| `task_id` | string | 是 | 请求 | 保留请求值 | 保留请求值 | 上传`task_id`；另两项未来生成 |
| `operation_mode` | enum | 是 | 请求 | 保留请求值 | 保留请求值 | 由三项PoC身份映射 |
| `run_id` | string/null | 是 | 请求/运行上下文 | 原值或null | 原值或null | 正式运行目录名 |
| `test_case_id` | string/null | 是 | 请求/测试上下文 | 原值或null | 原值或null | `sample_id`、`scenario`组合 |
| `diagnostic_session_id` | string/null | 是 | 请求/诊断上下文 | 原值或null | 原值或null | 新增 |
| `issue_report_id` | string/null | 是 | 请求/用户问题 | 原值或null | 原值或null | 新增 |
| `technical_status` | enum | 是 | 验证器/执行器 | `INVALID_REQUEST`或`PROCESSING_FAILED` | `NO_PROCESSING_NEEDED` | 上传`status`、无损/尺寸证据适配 |
| `visual_review_status` | enum | 是 | 视觉策略/夹具 | `NOT_AVAILABLE` | `NOT_REQUIRED` | 夹具/回放；尺寸复合文本适配为PENDING |
| `delivery_gate_status` | enum | 是 | 纯决策门禁 | `CANNOT_MEET_SAFELY` | `DELIVERY_READY` | 上传回放 |
| `delivery_eligible` | bool | 是 | 纯决策门禁 | false | true | 上传回放 |
| `delivery_decision_reason` | string | 是 | 纯决策门禁 | 明确失败原因 | 源文件已满足要求且未创建副本 | 上传回放 |
| `source_path` | string/null | 是 | 请求/源观察 | 无法解析时null | 原源路径 | `original_path`、`source_path` |
| `source_sha256` | string/null | 是 | 源观察 | 无法读取时null | 原源SHA | `original_sha256`、`source_sha256` |
| `source_format` | enum/null | 是 | 格式和魔数识别 | null | 原源格式 | `original_format`、`source_format` |
| `source_dimensions` | object/null | 是 | 源观察 | null | 原源尺寸 | `original_dimensions`、`source_dimensions` |
| `source_size_bytes` | int/null | 是 | 文件stat | null | 原源大小 | `original_size_bytes`、`source_size_bytes` |
| `output_created` | bool | 是 | 文件生命周期 | false | false | 新增；`no_processing_copy_created=false`提供现状证据 |
| `output_path` | string/null | 是 | 输出观察 | null | 等于`source_path` | `candidate_path`、`final_path` |
| `output_sha256` | string/null | 是 | 输出观察 | null | 等于`source_sha256` | `candidate_sha256`、`final_sha256` |
| `output_format` | enum/null | 是 | 输出观察 | null | 等于`source_format` | `output_format`或源格式 |
| `output_dimensions` | object/null | 是 | 输出观察 | null | 等于`source_dimensions` | `output_dimensions`、`final_dimensions` |
| `output_size_bytes` | int/null | 是 | 输出观察 | null | 等于`source_size_bytes` | `candidate_size_bytes`、`output_size_bytes`、`final_size_bytes` |
| `size_reduction_bytes` | int/null | 是 | 源大小减输出大小 | null | 0 | `saved_bytes`或派生 |
| `size_reduction_ratio` | number/null | 是 | 体积差/源大小 | null | 0 | `saved_ratio`或派生 |
| `dimension_scale_ratio` | number/null | 是 | 输出尺寸/源尺寸 | null | 1.0 | `scale`或尺寸派生 |
| `lossy` | bool/null | 是 | 策略和实际变换 | 未执行为null | false | 上传`lossy`；尺寸缩小必须派生true |
| `reencoded` | bool/null | 是 | 执行记录 | 未执行为null | false | 上传`reencoded`；另两项派生 |
| `resized` | bool/null | 是 | 尺寸比较 | 未执行为null | false | 从源/输出尺寸派生 |
| `metadata_preserved` | bool/null | 是 | `metadata_details`汇总 | 无证据null | true | 各模式元数据检查汇总 |
| `metadata_details` | object | 是 | 模式专用元数据比较 | 各子项null或已知false | 源未变：适用子项true，未适用项null | chunk/metadata comparison |
| `alpha_preserved` | bool/null | 是 | `alpha_details`汇总 | 无证据null | true | `alpha_exact`、`alpha_clean`、metadata comparison |
| `alpha_details` | object | 是 | Alpha观察和视觉证据 | 各子项null或已知false | 按源Alpha存在性填写；未适用项null | Alpha精确/预乘/透明RGB证据 |
| `processing_seconds` | number | 是 | 总计时 | 已耗时；最小0 | 实际限制检查耗时 | `elapsed_seconds`、`processing_seconds` |
| `stage_seconds` | object | 是 | 分阶段计时 | 已完成阶段或`{}` | 限制检查时间或`{}` | 上传`stage_seconds`；另两项适配 |
| `slowest_stage` | string/null | 是 | 阶段计时汇总 | 已知阶段或null | `limit_check`或null | 上传`slowest_stage` |
| `warnings` | array[string] | 是 | 验证/策略/人工备注 | 具体警告或`[]` | 可含`NO_SIZE_GAIN`，否则`[]` | `final_recommendation`、review notes、风险 |
| `failure_code` | string/null | 是 | 验证器/执行器 | 稳定机器码 | null | 从`rejection_reason`、`failure_reason`拆分 |
| `failure_reason` | string/null | 是 | 验证器/执行器 | 可读详情 | null | 三项`failure_reason` |
| `risk_reasons` | array[string] | 是 | 风险分析/视觉包 | 具体风险或`[]` | `[]` | 尺寸风险字段、`delivery_risk_reasons` |
| `candidate_delivery_role` | enum | 是 | 交付门禁 | `NONE`或`EVIDENCE_ONLY` | `SOURCE_NO_PROCESSING` | 上传回放；另两项新增 |
| `evidence_paths` | object | 是 | 适配器/证据导出 | 可保留失败证据；无则`{}` | 源证据引用或`{}` | 多套manifest、比较JSON、视觉来源 |
| `validation_status` | enum | 是 | 自动/独立验证 | `FAIL`或`NOT_RUN` | `PASS`（源完整性通过） | `technical_correctness_pass`、independent、automatic checks |
| `validation_failures` | array[object] | 是 | 验证器 | 失败明细 | `[]` | failed checks、rejection reasons |
| `asset_manifest_path` | string/null | 是 | 阶段3A证据导出 | null | null | SHA manifest/frozen manifest预留 |
| `asset_comparison_path` | string/null | 是 | 阶段3A资产保护 | null | null | formal before/after comparison预留 |
| `execution_log_path` | string/null | 是 | 阶段3A统一日志 | null | null | 当前三套均无统一JSONL |
| `test_feedback` | object/null | 是 | 阶段3A测试包 | null或独立失败对象 | null | 新增命名空间 |
| `user_feedback` | object/null | 是 | 阶段3A/4用户包 | null或独立失败对象 | null | 新增命名空间 |

字段总数：50。

`source_dimensions`和`output_dimensions`固定结构：

```json
{
  "width": 1122,
  "height": 1402
}
```

## 3. output_created 固定语义

`output_created` 表示本次任务是否实际创建了新的输出文件，不能由 `output_path` 是否非空推断。

当 `technical_status=NO_PROCESSING_NEEDED` 时必须满足：

```text
output_created = false
output_path = source_path
output_sha256 = source_sha256
output_format = source_format
output_dimensions = source_dimensions
output_size_bytes = source_size_bytes
size_reduction_bytes = 0
size_reduction_ratio = 0
dimension_scale_ratio = 1.0
lossy = false
reencoded = false
resized = false
metadata_preserved = true
alpha_preserved = true
candidate_delivery_role = SOURCE_NO_PROCESSING
```

调用方不得因为 `output_path` 指向源文件而误认为创建了副本。

## 4. metadata_details

`metadata_preserved` 是汇总结论，不能替代模式专用明细。

```json
{
  "icc_preserved": null,
  "exif_preserved": null,
  "dpi_preserved": null,
  "xmp_preserved": null,
  "orientation_semantics_correct": null,
  "png_non_idat_preserved": null,
  "png_plte_preserved": null,
  "png_trns_preserved": null,
  "jpeg_quantization_preserved": null,
  "jpeg_sampling_preserved": null,
  "unsupported_or_unchecked_items": []
}
```

除最后一个数组外，每个子字段只允许 `true`、`false`、`null`：

- `true`：该项适用、已检查且通过；
- `false`：该项适用、已检查且失败；
- `null`：不适用或证据不足；必须由 `unsupported_or_unchecked_items` 或证据路径说明原因。

汇总规则草案：任何适用项为false时 `metadata_preserved=false`；所有要求的适用项为true时可为true；存在必须检查但未检查的项时为null。不同模式的必需项不得被最低公共子集取代。

## 5. alpha_details

```json
{
  "alpha_present": null,
  "alpha_channel_preserved": null,
  "premultiplied_resize_used": null,
  "fully_transparent_rgb_zero": null,
  "semi_transparent_edges_reviewed": null,
  "alpha_exact": null
}
```

子字段均只允许 `true`、`false`、`null`。固定边界：

- 无损 PNG 的 `alpha_exact=true` 需要精确Alpha证据。
- 尺寸缩小和上传适配的 Alpha 缩小应记录 `premultiplied_resize_used`。
- `fully_transparent_rgb_zero=true` 只证明全透明像素的RGB清理，不代表半透明边缘安全。
- 半透明边缘发生变化且没有正式视觉结论时，`semi_transparent_edges_reviewed`必须为false或null，不能据此汇总为全面通过。
- 无 Alpha 图像的 `alpha_present=false`；其余不适用子项通常为null，而不是伪造为true。

## 6. 三层状态枚举

### 6.1 技术状态

```text
INVALID_REQUEST
NO_PROCESSING_NEEDED
TARGET_MET
TARGET_MET_WITH_REENCODE
CANNOT_MEET_SAFELY
PROCESSING_FAILED
```

`TARGET_MET_WITH_REENCODE` 只用于依赖受控有损质量重编码满足目标的结果。PNG IDAT 真正无损重压使用 `TARGET_MET`，同时通过 `reencoded=true`、`lossy=false`表达实际行为。

### 6.2 视觉状态

```text
NOT_REQUIRED
PENDING
PASS
PASS_WITH_NOTES
FAIL
NOT_AVAILABLE
```

### 6.3 交付状态

```text
DELIVERY_READY
DELIVERY_READY_WITH_NOTES
REVIEW_REQUIRED
CANNOT_MEET_SAFELY
```

## 7. 三层状态真值表

| 技术状态 | 视觉状态 | 附加条件 | 交付状态 | `delivery_eligible` | 候选角色 |
|---|---|---|---|---:|---|
| `INVALID_REQUEST` | `NOT_AVAILABLE` | 合同未通过 | `CANNOT_MEET_SAFELY` | false | `NONE` |
| `PROCESSING_FAILED` | `NOT_AVAILABLE` | 未产生可验证候选 | `CANNOT_MEET_SAFELY` | false | `NONE` |
| `CANNOT_MEET_SAFELY` | 任意 | 技术已安全停止 | `CANNOT_MEET_SAFELY` | false | 有证据候选则`EVIDENCE_ONLY`，否则`NONE` |
| `NO_PROCESSING_NEEDED` | `NOT_REQUIRED` | 源SHA及限制检查通过 | `DELIVERY_READY` | true | `SOURCE_NO_PROCESSING` |
| `NO_PROCESSING_NEEDED` | 其他 | 证据冲突 | `REVIEW_REQUIRED` | false | `SOURCE_NO_PROCESSING` |
| `TARGET_MET` | `NOT_REQUIRED` | 仅`STRICT_LOSSLESS_EVIDENCE`且全部硬证据完整 | `DELIVERY_READY` | true | `DELIVERY_CANDIDATE` |
| `TARGET_MET` | `NOT_REQUIRED` | 非严格无损或证据不完整 | `REVIEW_REQUIRED` | false | `EVIDENCE_ONLY` |
| `TARGET_MET` | `PENDING` | 等待视觉结论 | `REVIEW_REQUIRED` | false | `EVIDENCE_ONLY` |
| `TARGET_MET` | `PASS` | 技术检查通过 | `DELIVERY_READY` | true | `DELIVERY_CANDIDATE` |
| `TARGET_MET` | `PASS_WITH_NOTES` | 技术检查通过 | `DELIVERY_READY_WITH_NOTES` | true | `DELIVERY_CANDIDATE` |
| `TARGET_MET` | `FAIL` | — | `CANNOT_MEET_SAFELY` | false | `EVIDENCE_ONLY` |
| `TARGET_MET` | `NOT_AVAILABLE` | 应有视觉证据但缺失/冲突 | `REVIEW_REQUIRED` | false | `EVIDENCE_ONLY` |
| `TARGET_MET_WITH_REENCODE` | `NOT_REQUIRED` | 有损重编码不能免审 | `REVIEW_REQUIRED` | false | `EVIDENCE_ONLY` |
| `TARGET_MET_WITH_REENCODE` | `PENDING` | 等待视觉结论 | `REVIEW_REQUIRED` | false | `EVIDENCE_ONLY` |
| `TARGET_MET_WITH_REENCODE` | `PASS` | 技术检查通过 | `DELIVERY_READY` | true | `DELIVERY_CANDIDATE` |
| `TARGET_MET_WITH_REENCODE` | `PASS_WITH_NOTES` | 技术检查通过 | `DELIVERY_READY_WITH_NOTES` | true | `DELIVERY_CANDIDATE` |
| `TARGET_MET_WITH_REENCODE` | `FAIL` | — | `CANNOT_MEET_SAFELY` | false | `EVIDENCE_ONLY` |
| `TARGET_MET_WITH_REENCODE` | `NOT_AVAILABLE` | 应有视觉证据但缺失/冲突 | `REVIEW_REQUIRED` | false | `EVIDENCE_ONLY` |
| 未知状态或跨层冲突 | 任意 | 无法形成确定证据链 | `REVIEW_REQUIRED` | false | `EVIDENCE_ONLY`或`NONE` |

阶段2冻结映射保持不变：技术不可安全满足、视觉FAIL均不可交付；PASS、PASS_WITH_NOTES、PENDING分别映射到冻结的三个交付结果。严格无损硬证据完整是唯一新增的 `NOT_REQUIRED → DELIVERY_READY`模式边界，当前仍只是D级草案。

## 7.1 稳定 failure_code 边界

以下两个错误码用于分离请求/预检失败与运行期写入失败，语义不可互换：

| `failure_code` | 触发阶段与适用情况 | 固定结果映射 |
|---|---|---|
| `OUTPUT_DIRECTORY_INVALID` | 请求验证或执行前路径预检失败：输出目录不存在且无法创建、预检时不可写，或输出路径基础条件不成立 | `technical_status=INVALID_REQUEST`；`visual_review_status=NOT_AVAILABLE`；`delivery_gate_status=CANNOT_MEET_SAFELY`；`delivery_eligible=false`；`output_created=false`；`candidate_delivery_role=NONE` |
| `OUTPUT_WRITE_PERMISSION_DENIED` | 请求验证和目录预检均通过后，在临时写入、处理输出或原子保存阶段发生 `PermissionError` | `technical_status=PROCESSING_FAILED`；`visual_review_status=NOT_AVAILABLE`；`delivery_gate_status=CANNOT_MEET_SAFELY`；`delivery_eligible=false`；`output_created=false`；`candidate_delivery_role=NONE` |

`OUTPUT_DIRECTORY_INVALID` 只表示请求验证或执行前预检失败；`OUTPUT_WRITE_PERMISSION_DENIED` 只表示运行期写入权限失败。两者不得作为别名或互相回退。`fault_injection` 和 `test_setup` 都是测试fixture元数据，不是 `hdde.image-result.v1` 正式结果字段。

## 8. candidate_delivery_role

只允许：

```text
SOURCE_NO_PROCESSING
DELIVERY_CANDIDATE
EVIDENCE_ONLY
NONE
```

- 技术候选路径不自动等于交付候选。
- 视觉 `FAIL` 只能为 `EVIDENCE_ONLY`。
- 处理失败或请求无效为 `NONE`。
- 无需处理为 `SOURCE_NO_PROCESSING`。
- `real_alpha__D` 的冻结结果必须保持 `EVIDENCE_ONLY`。

## 9. evidence_paths

建议固定为对象并使用相对路径或路径令牌：

```json
{
  "technical_results": [],
  "metadata": [],
  "alpha": [],
  "sha256_manifests": [],
  "visual_review": [],
  "delivery_gate": [],
  "asset_protection": []
}
```

机器绝对路径可在本地运行记录中存在，但进入阶段3A可移交反馈包前必须脱敏或转换为 `$PROJECT_ROOT`、`$RUN_DIR` 等令牌。

## 10. 测试与用户反馈命名空间

不得共用一个扁平 feedback 对象。

### `test_feedback`

```json
{
  "feedback_package_id": null,
  "feedback_package_version": null,
  "feedback_package_status": null,
  "feedback_package_path": null,
  "feedback_package_sha256": null
}
```

### `user_feedback`

```json
{
  "feedback_package_version": null,
  "feedback_package_status": null,
  "feedback_package_path": null,
  "feedback_package_sha256": null,
  "submission_channel": null,
  "submission_status": null
}
```

阶段3.1只定义字段和边界。阶段3A实现诊断日志、隐私清理、预览、测试反馈包和用户反馈包生成；阶段4实现用户可见入口和手工提交。自动在线上传不在当前路线。

## 11. 跨文件固定命名注册表

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

本注册表只用于阶段3.1静态一致性检查。
