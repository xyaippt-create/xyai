# 图片处理统一预检合同 V1（候选草案）

状态：`READY_FOR_REVIEW`

schema_version：`1.0`

decision_version：`image_processing_routing_v1`

> 本文件仅冻结阶段5候选合同和确定性路由规则，不代表 API、业务模块或前端已经实现。所有推荐均为预检结果，禁止自动执行。

## 1. 目标与边界

候选接口：

```text
POST /api/image-processing/preflight
```

接口只接收阶段4本地 intake 签发的不透明安全 token。请求字段名固定为 `file_token`；其值来自阶段4响应中的 `source_token`，不得传入或持久化本地绝对路径。

预检接口只负责：验证请求、解析安全 token、读取/复用图片画像、计算确定性推荐、返回风险和替代方案。接口不得创建处理任务、输出文件、候选文件、反馈包或下载 token；不得修改原图、打开目录、上传网络或自动执行推荐动作。

HTTP 合同错误与合法业务状态严格分离：请求或 token 不合法使用 4xx；图片可被合法分析但当前路线不支持、无须处理或被安全门禁阻止时，HTTP 仍为 200，并通过 `preflight_status` 表达。

## 2. 请求合同

```json
{
  "file_token": "opaque-local-token",
  "purpose": "REDUCE_FILE_SIZE",
  "targets": {},
  "requested_action": null
}
```

顶层只允许以下字段：

| 字段 | 类型 | 必填 | 规则 |
| --- | --- | --- | --- |
| `file_token` | string | 是 | 仅允许阶段4安全 token，禁止路径 |
| `purpose` | enum | 是 | 见 2.1 |
| `targets` | object | 是 | 按 purpose 校验；无目标时使用空对象 |
| `requested_action` | enum/null | 是 | `null` 表示请求系统推荐；非空表示手动选择阶段4既有方式 |

未知顶层字段必须返回 `INVALID_REQUEST_BODY`。

### 2.1 purpose

只允许：

```text
REDUCE_FILE_SIZE
REDUCE_DIMENSIONS
MEET_UPLOAD_LIMITS
IMPROVE_LOW_QUALITY
```

不得增加或接受 `SMART_OPTIMIZATION`、`AUTO_ENHANCE`、“智能优化”、“一键优化”、“自动清晰”等模糊目标。

### 2.2 requested_action

只允许：

```text
null
LOSSLESS_COMPRESSION
RESIZE_REDUCTION
UPLOAD_ADAPTATION
```

手动选择仍必须经过完整预检，不得绕过禁止放大、长图安全门禁、格式限制或上传硬限制，也不得自动执行。

### 2.3 REDUCE_DIMENSIONS targets

四种策略每次必须且只能选择一种：

```json
{"resize_strategy":"FIXED_SHORT_SIDE","target_short_side":1080}
{"resize_strategy":"SCALE_RATIO","scale_ratio":0.75}
{"resize_strategy":"FIXED_WIDTH","target_width":1600}
{"resize_strategy":"FIXED_HEIGHT","target_height":900}
```

约束：

- `scale_ratio` 必须 `> 0` 且 `< 1`；
- 宽度、高度、短边目标必须为正整数；
- 缺失目标返回 `MISSING_RESIZE_TARGET`；
- 多策略或策略字段冲突返回 `CONFLICTING_TARGETS`；
- 目标小于原图才允许缩小；目标等于原图为无需处理；目标大于原图禁止放大。

### 2.4 MEET_UPLOAD_LIMITS targets

只允许 `max_width`、`max_height`、`max_bytes`，至少提供一项；全部缺失返回 HTTP 合同错误 `MISSING_UPLOAD_LIMITS`。各值必须为正整数，否则返回 `INVALID_TARGET_VALUE`。

### 2.5 REDUCE_FILE_SIZE targets

- PNG 严格无损不要求 `max_bytes`；
- JPEG 未提供 `max_bytes` 时不得推荐严格无损；
- JPEG 提供 `max_bytes` 后可根据原图是否已满足，返回无需处理或上传适配。
- 为计算长图安全预估，JPEG 的 `REDUCE_FILE_SIZE` 可在提供 `max_bytes` 的同时选填 `max_width`、`max_height`；它们采用与上传限制相同的正整数约束。

### 2.6 IMPROVE_LOW_QUALITY targets

本阶段不得接收增强参数。`targets` 必须为空对象，只能转交未来增强路线。

## 3. 图片画像合同

画像固定字段：

```text
format, mime_type, width, height, short_side, long_side, aspect_ratio,
orientation, size_bytes, size_kb, size_mb, has_alpha, is_animated,
frame_count, is_long_image, is_ultra_wide, resolution_bucket,
processing_eligibility, warnings
```

固定计算：

```text
short_side = min(width, height)
long_side = max(width, height)
aspect_ratio = width / height
size_kb = size_bytes / 1024
size_mb = size_bytes / 1048576
```

`aspect_ratio`、`size_kb`、`size_mb` 在响应中保留不超过 6 位小数。

### 3.1 orientation

```text
width > height  -> LANDSCAPE
height > width  -> PORTRAIT
width == height -> SQUARE
```

### 3.2 长图与超宽图

候选合同固定：

```text
is_long_image = (height / width >= 3) OR (height >= 4000)
is_ultra_wide = (width / height >= 3)
```

审计备注：阶段4当前实现为竖向图片且满足 `height / width >= 3`，或 `height >= 4000 AND height / width > 16/9`。因此 `height >= 4000` 的普通竖图在现状与本候选之间存在口径差异。指令2必须以本合同审定结果为唯一来源集中实现，禁止前后端继续复制不同公式；不得通过修改阶段3冻结核心解决该差异。

### 3.3 resolution_bucket

只表示像素尺寸，不表示画质：

```text
SHORT_SIDE_LT_600
SHORT_SIDE_600_1079
SHORT_SIDE_1080_1439
SHORT_SIDE_1440_2159
SHORT_SIDE_2160_4319
SHORT_SIDE_GE_4320
```

禁止使用 `LOW_QUALITY`、`HIGH_QUALITY`、`2K_QUALITY`、`4K_QUALITY`、`DELIVERY_READY`、`VISUAL_PASS`。

### 3.4 processing_eligibility 与格式

只允许：

```text
ELIGIBLE
ELIGIBLE_WITH_WARNING
UNSUPPORTED
```

阶段4真实已验证输入范围为静态 PNG、JPG/JPEG，扩展名必须与 magic 格式一致，最大本地接收体积 50 MB，并执行完整解码。动画、多帧或其他格式统一 `UNSUPPORTED`，不得静默只处理第一帧。

阶段4现有 `read_image_info` 可直接参考/调用其格式检测、完整解码、宽高、体积和 Alpha 读取；当前未输出 `mime_type`、`frame_count`、`is_animated`，阶段5需在新增画像层补齐，不得修改阶段3冻结目录。

## 4. 响应合同

```json
{
  "schema_version": "1.0",
  "decision_version": "image_processing_routing_v1",
  "profile": {},
  "purpose": "REDUCE_FILE_SIZE",
  "preflight_status": "READY",
  "recommended_action": "LOSSLESS_COMPRESSION",
  "executable": true,
  "reason_codes": [],
  "blocking_reasons": [],
  "warnings": [],
  "recommended_parameters": {},
  "estimated_output": {
    "width": null,
    "height": null,
    "short_side": null,
    "long_side": null,
    "max_bytes": null
  },
  "alternatives": []
}
```

### 4.1 preflight_status

只允许：

```text
READY
READY_WITH_WARNING
NO_PROCESSING_NEEDED
UNSUPPORTED_MODE
BLOCKED_UNSAFE
ROUTE_TO_ENHANCEMENT
```

### 4.2 recommended_action

只允许：

```text
NO_PROCESSING
LOSSLESS_COMPRESSION
RESIZE_REDUCTION
UPLOAD_ADAPTATION
FUTURE_ENHANCEMENT
UNSUPPORTED
```

### 4.3 executable

必须是明确布尔值。`true` 仅表示已有阶段4动作在当前参数下可安全进入后续“用户确认后执行”流程，不表示已执行，也不得由前端根据文本推断。

### 4.4 estimated_output

未知值必须为 `null`。允许确定性表达预计宽度、高度、短边、长边和目标最大体积；禁止伪造严格无损压缩后的确定体积、上传适配搜索完成前的确定输出体积或尚未处理时的画质结论。

## 5. 确定性路由矩阵

| 条件 | preflight_status | recommended_action | executable | 必含代码 |
| --- | --- | --- | ---: | --- |
| PNG + REDUCE_FILE_SIZE | READY | LOSSLESS_COMPRESSION | true | `PNG_STRICT_LOSSLESS_SUPPORTED`, warning `PNG_STRICT_LOSSLESS_MAY_HAVE_NO_GAIN` |
| JPEG + REDUCE_FILE_SIZE，无 max_bytes | READY_WITH_WARNING | UNSUPPORTED | false | `JPEG_STRICT_LOSSLESS_NOT_SUPPORTED`, `FILE_SIZE_TARGET_REQUIRED` |
| JPEG + REDUCE_FILE_SIZE，有 max_bytes 且已满足 | NO_PROCESSING_NEEDED | NO_PROCESSING | false | `NO_PROCESSING_REQUIRED` |
| JPEG + REDUCE_FILE_SIZE，有 max_bytes 且未满足 | READY | UPLOAD_ADAPTATION | true | `UPLOAD_LIMITS_REQUIRE_ADAPTATION` |
| REDUCE_DIMENSIONS，目标小于原图 | READY | RESIZE_REDUCTION | true | `TARGET_SMALLER_THAN_SOURCE` |
| REDUCE_DIMENSIONS，目标等于原图 | NO_PROCESSING_NEEDED | NO_PROCESSING | false | `TARGET_EQUALS_SOURCE`, `NO_PROCESSING_REQUIRED` |
| REDUCE_DIMENSIONS，目标大于原图 | BLOCKED_UNSAFE | UNSUPPORTED | false | `TARGET_EXCEEDS_SOURCE`, `NO_UPSCALE` |
| MEET_UPLOAD_LIMITS，全部已满足 | NO_PROCESSING_NEEDED | NO_PROCESSING | false | `UPLOAD_LIMITS_ALREADY_MET`, `NO_PROCESSING_REQUIRED` |
| MEET_UPLOAD_LIMITS，未满足且可安全处理 | READY / READY_WITH_WARNING | UPLOAD_ADAPTATION | true | `UPLOAD_LIMITS_REQUIRE_ADAPTATION` |
| MEET_UPLOAD_LIMITS，无法安全满足 | BLOCKED_UNSAFE | UNSUPPORTED | false | `UPLOAD_LIMITS_UNSAFE_TO_MEET` |
| IMPROVE_LOW_QUALITY | ROUTE_TO_ENHANCEMENT | FUTURE_ENHANCEMENT | false | `IMPROVE_LOW_QUALITY_REQUIRES_ENHANCEMENT` |
| 动画、多帧、不支持格式 | UNSUPPORTED_MODE | UNSUPPORTED | false | 对应格式/帧原因代码 |

PNG 严格无损必须保持 PNG 格式和像素尺寸，不保证体积一定下降；无收益不得生成伪候选。

### 5.1 长图安全规则

对长图的尺寸缩小或上传适配，先按参数计算预计尺寸，再以预计短边执行：

| 预计短边 | 结果 |
| ---: | --- |
| `< 600` | `BLOCKED_UNSAFE / UNSUPPORTED / false` |
| `600..749` | `READY_WITH_WARNING`，动作保持原路由决定，执行前需明确风险确认 |
| `>= 750` | 按其他规则继续判断 |

响应必须包含原始尺寸、预计尺寸、预计短边、风险原因和替代参数建议。长图默认不限制高度，始终禁止放大。

### 5.2 手动选择

- `requested_action` 非空时，`targets` 可包含 purpose 所需目标与所选动作所需参数的并集，但每组参数仍须独立满足本合同约束；
- 与 purpose 不一致但仍可能安全时，返回 `MANUAL_ACTION_CONFLICTS_WITH_PURPOSE` 并明确替代方案；
- 违反安全门禁时，返回 `MANUAL_ACTION_BLOCKED_BY_SAFETY_GATE`，且 `executable=false`；
- JPEG 手动选择 `LOSSLESS_COMPRESSION` 仍为不支持；
- 手动选择 `UPLOAD_ADAPTATION` 但缺少上传限制，仍返回 HTTP `MISSING_UPLOAD_LIMITS`。

## 6. 原因代码

业务原因代码固定候选：

```text
PNG_STRICT_LOSSLESS_SUPPORTED
PNG_STRICT_LOSSLESS_MAY_HAVE_NO_GAIN
JPEG_STRICT_LOSSLESS_NOT_SUPPORTED
FILE_SIZE_TARGET_REQUIRED
TARGET_SMALLER_THAN_SOURCE
TARGET_EQUALS_SOURCE
TARGET_EXCEEDS_SOURCE
NO_UPSCALE
NO_PROCESSING_REQUIRED
UPLOAD_LIMITS_ALREADY_MET
UPLOAD_LIMITS_REQUIRE_ADAPTATION
UPLOAD_LIMITS_UNSAFE_TO_MEET
IMPROVE_LOW_QUALITY_REQUIRES_ENHANCEMENT
ANIMATED_IMAGE_NOT_SUPPORTED
MULTI_FRAME_IMAGE_NOT_SUPPORTED
FORMAT_NOT_SUPPORTED
LONG_IMAGE_DETECTED
ULTRA_WIDE_IMAGE_DETECTED
ESTIMATED_SHORT_SIDE_LT_600
ESTIMATED_SHORT_SIDE_600_749
ESTIMATED_SHORT_SIDE_GE_750
ALPHA_CHANNEL_PRESENT
MANUAL_ACTION_CONFLICTS_WITH_PURPOSE
MANUAL_ACTION_BLOCKED_BY_SAFETY_GATE
```

约定：决定路由的代码放入 `reason_codes`；导致不可执行的安全原因同时放入 `blocking_reasons`；非阻断风险和事实提示放入 `warnings`。数组去重并保持上述声明顺序。

## 7. HTTP 合同错误

| error_code | 建议 HTTP | 触发条件 |
| --- | ---: | --- |
| `INVALID_REQUEST_BODY` | 400 | body 非对象、未知字段或结构错误 |
| `INVALID_PURPOSE` | 400 | purpose 不在固定枚举 |
| `INVALID_REQUESTED_ACTION` | 400 | requested_action 不在固定枚举 |
| `MISSING_RESIZE_TARGET` | 400 | 尺寸目的未提供策略/目标 |
| `CONFLICTING_TARGETS` | 400 | 同时提供多个尺寸策略或冲突字段 |
| `MISSING_UPLOAD_LIMITS` | 400 | 上传限制完全缺失 |
| `INVALID_TARGET_VALUE` | 400 | 数值类型或范围非法 |
| `TOKEN_NOT_FOUND_OR_EXPIRED` | 404 | token 不存在、过期、角色不匹配、源文件缺失或当前进程会话不可用；复用阶段4 `require_token` 现有语义，不增加过期 tombstone |
| `ABSOLUTE_PATH_NOT_ALLOWED` | 400 | token 字段包含绝对路径或路径形态输入 |
| `IMAGE_DECODE_FAILED` | 422 | 图片无法完整解码 |

不得用上述 HTTP 错误代码表达合法业务结果，也不得把业务原因代码作为 HTTP 错误返回。

## 8. 阶段4复用边界

- 可直接调用/参考：`engine.image_compression.common.detect_format`、`read_image_info` 的只读画像能力；阶段4 token registry 的 `require_token` 语义；现有确定性尺寸估算。
- 只能调用不能修改：`engine/image_compression/*`、阶段3合同和 fixture。
- 需要阶段5新增：统一画像模型、帧数/动画检测、MIME 映射、请求校验、纯路由决策函数、预检 API 适配和阶段5测试。
- 必须避免：在前端再次实现业务状态推断；在新旧后端复制长图阈值；让 `file_token` 解析结果中的绝对路径进入响应、日志或持久化合同。

## 9. 非目标

本合同不定义图片处理算法、JPEG 系数级严格无损、增强参数、批量任务、队列、数据库、云服务、OCR、AI 画质评分、1080P/4K/8K 增强或自动交付结论。
