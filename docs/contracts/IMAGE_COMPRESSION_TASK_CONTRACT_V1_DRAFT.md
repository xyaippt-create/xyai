# 影界 HDDE｜图片压缩统一任务合同 v1 草案

```text
document_status: DRAFT
proposal_level: D
implementation_status: NOT_IMPLEMENTED
contract_version: hdde.image-task.v1
field_count: 28
evidence_base_commit: 8764b2be09f977736eb66523a8efe1be7463c5be
```

## 1. 草案边界

本文档只定义未来统一任务合同字段、验证边界和旧字段来源。当前尚未实现正式 Python 合同类、状态枚举、路由器、图片执行器、原子保存、自动视觉通过、测试反馈包、用户反馈包、UI、API、SSE 或正式 pipeline 接入。

非适用字段不得静默忽略：必须为 `null` 或省略。非适用字段出现非空值时，统一返回 `INVALID_REQUEST`，并给出稳定 `failure_code`。

## 2. operation_mode

只允许：

```text
LOSSLESS_COMPRESSION
RESIZE_REDUCTION
UPLOAD_ADAPTATION
```

规则：

- 用户明确选择的主能力不得自动切换。
- `LOSSLESS_COMPRESSION` 遇到 JPEG 时必须安全拒绝；不得自动切换到上传适配或 JPEG 质量重编码。
- 上传适配内部允许采用受控 PNG 无损优化、尺寸缩小和 JPEG 高质量重编码策略，但它们不构成第四项主能力。
- 图像内容分析只能影响已选能力内部的安全策略，不得改变 `operation_mode`。

## 3. 字段级定义

| 字段 | 类型 | 必填 | 默认值 | 适用模式 | 允许值/校验规则 | 非适用处理 | failure_code | 当前映射来源 |
|---|---|---:|---|---|---|---|---|---|
| `contract_version` | string | 是 | 无 | 全部 | 必须等于 `hdde.image-task.v1` | 不适用 | `CONTRACT_VERSION_UNSUPPORTED` | 新增；由阶段3合同固定 |
| `task_id` | string | 是 | 无 | 全部 | 1–128字符；安全字符；本次执行唯一 | 不适用 | `TASK_ID_INVALID` | 上传 `task_id`；另两项未来由调用方生成 |
| `operation_mode` | enum | 是 | 无 | 全部 | 三个固定值之一 | 不适用 | `OPERATION_MODE_INVALID` | 由三项PoC身份映射 |
| `source_path` | string | 是 | 无 | 全部 | 本地绝对文件路径；存在、可读；不能是目录 | 不适用 | `SOURCE_PATH_INVALID` / `SOURCE_NOT_FOUND` | `original_path`、`source_path` |
| `source_sha256_expected` | string/null | 否 | null | 全部；测试/冻结任务优先 | null或64位小写十六进制 | 不适用 | `SOURCE_SHA256_EXPECTED_INVALID` / `SOURCE_SHA_MISMATCH` | frozen manifest、原图SHA清单 |
| `output_directory` | string | 是 | 无 | 全部 | 本地目录；可创建或可写；不得指向源文件 | 不适用 | `OUTPUT_DIRECTORY_INVALID` | `run_dir`、candidate/final目录 |
| `preserve_format` | bool | 是 | true | 全部 | 阶段3只允许true | 不适用 | `PRESERVE_FORMAT_REQUIRED` | 三项现状均保持格式 |
| `max_width` | int/null | 条件 | null | 仅UPLOAD_ADAPTATION | 正整数；上传三个限制至少一个非空 | 其他模式必须null/省略 | `LIMIT_INVALID` / `FIELD_NOT_APPLICABLE` | `limits.max_width` |
| `max_height` | int/null | 条件 | null | 仅UPLOAD_ADAPTATION | 正整数；上传三个限制至少一个非空 | 其他模式必须null/省略 | `LIMIT_INVALID` / `FIELD_NOT_APPLICABLE` | `limits.max_height` |
| `max_file_size_bytes` | int/null | 条件 | null | 仅UPLOAD_ADAPTATION | 正整数；上传三个限制至少一个非空 | 其他模式必须null/省略 | `LIMIT_INVALID` / `LIMITS_MISSING` | `limits.max_file_size_bytes` |
| `target_width` | int/null | 条件 | null | 仅RESIZE_REDUCTION | 正整数；不得大于源宽；与源比例误差≤1像素 | 其他模式必须null/省略 | `TARGET_DIMENSION_INVALID` / `FIELD_NOT_APPLICABLE` | `target_dimensions`拆分 |
| `target_height` | int/null | 条件 | null | 仅RESIZE_REDUCTION | 正整数；不得大于源高；与源比例误差≤1像素 | 其他模式必须null/省略 | `TARGET_DIMENSION_INVALID` / `FIELD_NOT_APPLICABLE` | `target_dimensions`拆分 |
| `scale_ratio` | number/null | 条件 | null | 仅RESIZE_REDUCTION | `0 < scale_ratio < 1`；与目标宽高二选一 | 其他模式必须null/省略 | `SCALE_RATIO_INVALID` / `RESIZE_ARGUMENT_CONFLICT` | 尺寸 `scale` |
| `resize_policy` | enum/null | 条件 | 按模式 | RESIZE_REDUCTION；UPLOAD内部只读策略 | `LANCZOS_HIGH_QUALITY`；明确照片测试可用`INTER_AREA_PHOTO_ONLY`；BICUBIC不允许正式请求 | LOSSLESS必须null；UPLOAD不得由用户覆写内部策略 | `RESIZE_POLICY_INVALID` / `FIELD_NOT_APPLICABLE` | `method`、方法报告 |
| `quality_policy` | enum | 是 | 按模式固定 | 全部 | LOSSLESS=`LOSSLESS_ONLY`；RESIZE=`SAME_FORMAT_HIGH_QUALITY`；UPLOAD=`UPLOAD_ADAPTATION_V1` | 不适用 | `QUALITY_POLICY_INVALID` | PNG/JPEG编码策略和`encoding_parameters` |
| `metadata_policy` | enum | 是 | `PRESERVE_SUPPORTED_STRICT` | 全部 | 当前只允许`PRESERVE_SUPPORTED_STRICT` | 不适用 | `METADATA_POLICY_INVALID` | 三项元数据检查 |
| `overwrite_policy` | enum | 否 | `FAIL_IF_EXISTS` | 全部 | `FAIL_IF_EXISTS`或`UNIQUE_SUFFIX`；禁止覆盖源文件 | 不适用 | `OVERWRITE_POLICY_INVALID` | 当前新run目录行为的合同化 |
| `output_naming_policy` | enum | 否 | `TASK_ID_SUFFIX` | 全部 | 当前只允许确定性`TASK_ID_SUFFIX` | 不适用 | `OUTPUT_NAMING_POLICY_INVALID` | 三套候选命名归一化 |
| `visual_review_policy` | enum | 是 | 按模式固定 | 全部 | `VALIDATION_STRICT`、`PRODUCT_RISK_GATED`、`STRICT_LOSSLESS_EVIDENCE`；见第4节 | 不适用 | `VISUAL_REVIEW_POLICY_INVALID` | 尺寸盲测、上传夹具、无损硬证据 |
| `request_context` | object | 否 | `{}` | 全部 | JSON对象；仅放调用来源、locale、追踪信息和旧证据标识；不得放密钥 | 不适用 | `REQUEST_CONTEXT_INVALID` | `sample_id`、`scenario`、实验方法说明 |
| `client_context` | object/null | 否 | null | 全部；诊断/反馈时使用 | 可脱敏的应用版本、OS摘要、执行模式；禁止账号、token、序列号 | 不适用 | `CLIENT_CONTEXT_INVALID` | 现有反馈包环境字段预留 |
| `run_id` | string/null | 条件 | null | 内部测试/诊断 | 测试作用域必填；1–128安全字符 | 普通任务允许null | `RUN_ID_INVALID` | 正式运行目录名 |
| `test_case_id` | string/null | 条件 | null | 内部测试 | 测试作用域必填；必须稳定唯一 | 普通任务允许null | `TEST_CASE_ID_INVALID` | `sample_id`、`scenario`组合 |
| `diagnostic_session_id` | string/null | 否 | null | 诊断/反馈 | UUID或ULID样式稳定ID；可关联多个task | 普通任务允许null | `DIAGNOSTIC_SESSION_ID_INVALID` | 新增预留 |
| `issue_report_id` | string/null | 条件 | null | 用户问题反馈 | `user_issue_context`非空时必填 | 无用户问题时必须null/省略 | `ISSUE_REPORT_ID_REQUIRED` / `FIELD_NOT_APPLICABLE` | 新增预留 |
| `expected_status` | string/null | 否 | null | 仅内部测试 | 必须来自技术、视觉或交付状态注册表，并由测试作用域说明层级 | 普通任务必须null/省略 | `EXPECTED_STATUS_INVALID` / `FIELD_NOT_APPLICABLE` | 回放断言、未来合同fixture |
| `required_checks` | array[string] | 否 | `[]` | 仅内部测试 | 每项必须是已注册检查名；去重；顺序稳定 | 普通任务必须空或省略 | `REQUIRED_CHECK_UNKNOWN` / `FIELD_NOT_APPLICABLE` | automatic/validation assertions |
| `user_issue_context` | object/null | 否 | null | 用户问题反馈 | 见第5节；附件和图片必须显式选择 | 无问题时必须null/省略 | `USER_ISSUE_CONTEXT_INVALID` | 新增预留 |

字段总数：28。

### 3.1 尺寸参数互斥规则

`RESIZE_REDUCTION` 必须满足以下一种且仅一种：

1. 提供 `scale_ratio`，`target_width/target_height` 均为null；
2. 提供 `target_width`和`target_height`，`scale_ratio`为null。

任一目标不得放大；零尺寸、负尺寸、仅提供宽或高、目标比例不一致、目标与比例同时非空均返回 `INVALID_REQUEST`。

### 3.2 上传限制规则

`UPLOAD_ADAPTATION` 的 `max_width`、`max_height`、`max_file_size_bytes` 至少一个非空。缺失限制返回 `LIMITS_MISSING`。外部请求不得提交尺寸候选序列、JPEG质量序列或 PoC `scenario=A–E` 作为产品路由参数。

## 4. visual_review_policy 边界

### `VALIDATION_STRICT`

- 用于 PoC、正式回归和阶段验收。
- 图像发生尺寸、像素或有损编码变化后必须具备视觉结论。
- 缺少结论时为 `PENDING`，交付状态为 `REVIEW_REQUIRED`。
- 当前尺寸缩小与上传适配的冻结证据按此策略解释。

### `PRODUCT_RISK_GATED`

- 只为未来产品策略预留。
- 本阶段不定义、实现或声称存在自动视觉通过算法。
- 后续风险策略未批准前，不得自动输出 `PASS`。
- 默认失败关闭，或明确要求用户确认。

### `STRICT_LOSSLESS_EVIDENCE`

- 仅适用于真正无损且格式、尺寸、解码像素、Alpha、非IDAT结构、元数据、完整解码和原图SHA硬证据全部通过的结果。
- 满足全部硬证据时，未来结果可使用 `visual_review_status=NOT_REQUIRED`。
- 任一要求缺失、false或未知时不得使用 `NOT_REQUIRED`。
- JPEG系数级真正无损当前未实现，因此不能使用该策略放行JPEG。

用户不得通过请求字段降低系统安全门禁。执行器可以把不安全的请求策略提升为更严格策略，但不能降低。

## 5. user_issue_context 预留

`user_issue_context` 只定义关联字段；本阶段不实现反馈包生成。

| 子字段 | 类型 | 必填/默认 | 规则 |
|---|---|---|---|
| `issue_category` | string | 是/无 | 受控问题分类；不从日志自动猜测 |
| `user_description` | string | 是/无 | 用户显式输入的UTF-8文本 |
| `reproduction_steps` | array[string] | 否/`[]` | 有序步骤，不自动采集剪贴板 |
| `expected_result` | string | 是/无 | 与实际结果分离 |
| `actual_result` | string | 是/无 | 不用错误日志代替用户描述 |
| `attachment_paths` | array[string] | 否/`[]` | 仅用户显式选择的本地文件 |
| `include_source_image` | bool | 否/false | 原图默认不包含 |
| `include_output_image` | bool | 否/false | 输出图默认不包含 |
| `include_diagnostic_logs` | bool | 否/false | 日志默认不包含 |
| `privacy_confirmation` | bool | 否/false | 包含任何附件、原图、输出图或日志前必须为true |

隐私确认不足时返回 `PRIVACY_CONFIRMATION_REQUIRED`，不得生成用户反馈包。实际采集、脱敏、预览和打包属于阶段3A；用户可见入口和手工提交属于阶段4。禁止后台静默上传。

## 6. 测试反馈包预留

内部测试任务预留：

- `run_id`
- `test_case_id`
- `diagnostic_session_id`
- `expected_status`
- `required_checks`

阶段3只定义稳定字段。统一诊断日志、路径脱敏、测试反馈包 v2 和完整性 SHA 属于阶段3A；本合同草案不表示生成器已经实现。

## 7. 失败关闭总则

- 未知顶层字段：`UNKNOWN_FIELD`。
- 未知枚举值：对应字段的 `*_INVALID`。
- 非适用字段非空：`FIELD_NOT_APPLICABLE`。
- 字段类型不符：`FIELD_TYPE_INVALID`。
- 缺少条件必填字段：对应 `*_REQUIRED` 或 `LIMITS_MISSING`。
- 用户选择真正无损但源格式为JPEG：请求本身可验证通过，执行结果必须为 `CANNOT_MEET_SAFELY`；禁止改变主能力。
- 合同验证失败时不创建输出，后续图片执行不得启动。

上述规则留待阶段3.2实现和测试；当前只是D级草案。

## 8. 请求校验顺序与首要失败码规则

本节只冻结未来验证器和合同fixture的确定性规则，仍为D级方案且 `implementation_status=NOT_IMPLEMENTED`。验证和执行按以下七个固定阶段进行，顺序不得调整：

| 阶段 | 固定检查范围 | 典型失败码/状态 |
|---:|---|---|
| 1 | 结构与未知字段 | `UNKNOWN_FIELD` |
| 2 | 合同版本、必填字段和基础类型 | `CONTRACT_VERSION_UNSUPPORTED`、`*_REQUIRED`、`FIELD_TYPE_INVALID` |
| 3 | 字段适用性 | `FIELD_NOT_APPLICABLE` |
| 4 | 枚举与单字段取值范围 | `QUALITY_POLICY_INVALID`及其他字段级`*_INVALID` |
| 5 | 跨字段冲突 | `RESIZE_ARGUMENT_CONFLICT`、`LIMITS_MISSING`等 |
| 6 | 资源与路径预检 | `SOURCE_NOT_FOUND`、`OUTPUT_DIRECTORY_INVALID`等 |
| 7 | 运行期处理错误 | `PROCESSING_FAILED`；具体错误由结果合同的运行期`failure_code`表达 |

固定确定性规则：

- 第1至第6阶段中，首个失败阶段决定首要 `failure_code`；不得以后续阶段错误覆盖。
- 其余已发现错误仍必须完整记录到结果合同的 `validation_failures`，不得因为已经选出首要错误而停止收集可安全确定的其他错误。
- 同一阶段有多个规范字段失败时，按第3节任务合同字段表中的字段顺序确定首要错误。
- 同时存在多个未知字段时，未知字段之间按字段名的 UTF-8 字典序确定首要未知字段。
- 第7阶段不是请求合同验证错误。请求验证和预检已通过后发生的运行期错误返回 `technical_status=PROCESSING_FAILED`，不得返回 `INVALID_REQUEST`。
- 固定优先关系为：`UNKNOWN_FIELD` 先于 `FIELD_NOT_APPLICABLE`；`FIELD_NOT_APPLICABLE` 先于 `QUALITY_POLICY_INVALID`及其他枚举值错误。

### 8.1 S3C-022确定性示例

`S3C-022` 同时保留三个违规：`unknown_future_field` 在第1阶段触发 `UNKNOWN_FIELD`；非适用的 `max_width` 在第3阶段触发 `FIELD_NOT_APPLICABLE`；`quality_policy=UNKNOWN_POLICY` 在第4阶段触发 `QUALITY_POLICY_INVALID`。因此首要 `failure_code` 唯一确定为 `UNKNOWN_FIELD`，另外两个错误仍必须进入 `validation_failures`。

### 8.2 合同fixture元数据边界

`test_setup` 是合同测试fixture的case级元数据，不是 `hdde.image-task.v1` 正式任务字段。测试框架必须先从case中分离 `test_setup`，再将 `request` 交给正式验证器；如果 `test_setup` 出现在正式 `request` 中，验证器仍须按第1阶段未知字段返回 `UNKNOWN_FIELD`。故障注入只能在请求验证与输出目录预检通过后执行；`S3C-021` 测试运行期写入失败，不测试请求非法。

## 9. 跨文件固定命名注册表

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

本注册表仅用于草案和fixture的命名一致性检查，不表示枚举或门禁代码已经实现。
