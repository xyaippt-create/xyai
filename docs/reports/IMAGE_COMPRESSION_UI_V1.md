# 影界 HDDE V0.5.1｜阶段4 图片压缩最终产品化收口报告

## 1. 当前结论

- 分支：`codex/image-compression-ui-v1`
- 阶段3冻结基线：`b0144038c6386aba7147227939471f06f9d83862`
- 阶段3冻结引擎、50字段结果合同和22项夹具：未修改
- 自动测试、真实 HTTP 服务闭环和磁盘结构：通过
- 真实浏览器 UI 验收：Google Chrome / Chromium 真实 GUI 已完成
- `FEATURE_IMPLEMENTATION: PASS_WITH_NOTES`
- `FEATURE_SCOPE: FROZEN`
- `FEEDBACK_PACKAGE_COMPLETENESS: PASS`
- `FEEDBACK_PACKAGE_SUMMARY_CONSISTENCY: PASS`
- `FEEDBACK_PACKAGE_DOWNLOAD: PASS`
- `BROWSER_ACCEPTANCE: PASS_WITH_NOTES`
- `STAGE_4_FINAL_STATUS: PASS_WITH_NOTES`
- `STAGE_4_COMMIT_READINESS: READY`
- `SELF_AUDIT: PASS_WITH_NOTES`

Codex 已在 Google Chrome（Chromium）中完成真实本地文件选择、页面按钮执行、视觉状态核对、截图保存和反馈包下载点击。验收记录22/22完成：原8类8/8通过、长图7/7通过、固定短边5/5通过、F01反馈包真实点击下载通过；本地保留30张截图和25份结构化证据。视觉复核属于 Codex 执行的 AI 辅助 GUI 复核，不是用户本人复核。当前控制接口未暴露 DevTools Network，网络层由 API、真实服务和下载自动回归补充覆盖，因此作为非阻断备注保留；Microsoft Edge 未单独完成专项兼容性验证。O08 的验收说明写“1B”，当前 UI 最小值为“0.01KB”，界面按实际最小值完成安全阻止验证，此文字差异不判定为功能失败。

本轮未执行 `git add`、commit、push、tag、PR、reset、stash 或 clean。

## 2. 产品层实现

阶段4只在 API/UI 产品层增加：

- 本地 multipart intake、opaque `source_token`、安全预览；
- PNG无损压缩、尺寸缩小、上传适配三模式 UI；
- JPEG 真正无损执行前禁用；
- 长图识别、三种预览模式、100%真实像素查看、全屏、顶部/中部/底部锚点；
- 长图原图/结果单栏切换与归一化滚动位置同步；
- 长图宽度风险预检、600px以下硬阻止、600—749px二次确认；
- 无候选时只显示原图，不复制原图冒充结果；
- 固定短边尺寸缩小主策略；
- 三固定功能目录与扁平化结果文件；
- 与输出图片同目录、同 `output_stem` 的测试反馈 ZIP；
- 人工视觉复核与交付门禁闭环。

API 正式运行响应仍保持：

```json
{
  "result": { "...": "hdde.image-result.v1 严格50字段" },
  "ui": { "...": "阶段4产品显示和验证字段" }
}
```

`target_short_side`、长图验证和反馈包字段均未写入冻结50字段 `result`。

## 3. 长图识别与安全门禁

产品层长图识别：

- `height / width >= 3`；或
- 高度至少4000且比例明显高于普通9:16竖图；
- 横图不按竖向长图处理；
- 普通4:5和9:16样本不会仅因高分辨率误判。

长图默认行为：

- 预览默认“适合宽度”；
- 上传适配默认 `max_width=1080`、`max_height=null`、`max_file_size=2MB`；
- 尺寸缩小默认“按短边—短边1080”；
- 尺寸发生变化后保持 `visual_review_status=PENDING`、`delivery_gate_status=REVIEW_REQUIRED`、`delivery_eligible=false`；
- 不自动声明文字安全、二维码可扫描或视觉通过。

安全门禁：

- 输出宽度 `<600`：执行前硬阻止；
- `600—749`：必须确认“我已了解长图小字可能明显变弱”；
- `750—899`：强警告；
- `900—1079`：复核提示；
- `>=1080`：风险较低，但仍需人工复核。

1266×9088长图设置最大高度1080时，预计约150×1080，API 在创建任务和输出文件前返回 `LONG_IMAGE_WIDTH_TOO_LOW`。

## 4. 固定短边尺寸缩小策略

### 4.1 调整原因

旧的“长图优先固定宽度”不足以统一横图、竖图、方图、竖向长图和横向超宽图；固定总高度还会把1266×9088长图压成约150×1080。正式主策略改为：

> 尺寸缩小默认采用固定短边；对于竖向长图，固定短边等价于固定输出宽度。

### 4.2 计算规则

前后端均实现同义纯函数：

```text
source_short_side = min(source_width, source_height)
scale = target_short_side / source_short_side
target_width = round_half_up(source_width × scale)
target_height = round_half_up(source_height × scale)
```

API 不信任前端预计值，会按 intake 得到的源尺寸重新计算成对 `target_width`、`target_height`，再交给冻结阶段3引擎。

### 4.3 方向样例

| 原图 | 目标短边 | 输出 |
| --- | ---: | --- |
| 1266×9088竖向长图 | 1080 | 1080×7753 |
| 1266×9088竖向长图 | 900 | 900×6461 |
| 1920×1080横图 | 900 | 1600×900 |
| 1080×1350竖图 | 900 | 900×1125 |
| 1200×1200方图 | 1080 | 1080×1080 |
| 6000×1000超宽图 | 900 | 5400×900 |

### 4.4 1266×9088真实执行验证

临时测试夹具：

```text
tmp/stage4_e2e_final/SHORT-SIDE-E2E-01_中文商业PPT长图.jpg
```

真实 5173代理→8787 API 输出：

```text
1080 × 7753
visual_review_status = PENDING
delivery_gate_status = REVIEW_REQUIRED
delivery_eligible = false
```

输出完整保留13个纵向内容区，无裁切、无补边、无拉伸。文字与细线最终可用性仍保留人工视觉复核，不自动给出视觉 PASS。

### 4.5 禁止放大和无需处理

- 目标短边大于原图短边：`TARGET_SHORT_SIDE_UPSCALE_BLOCKED`；
- 目标短边等于原图短边：`NO_PROCESSING_NEEDED`；
- 两种情况均不登记任务、不创建输出文件、不创建反馈包、不静默改回原尺寸。

### 4.6 前后端一致性

- JavaScript 与 Python 固定短边纯函数使用相同正整数校验和正数 `.5` 向上舍入规则；
- API 外层 `ui` 同时返回预计尺寸与实际尺寸；
- 1266×9088、1920×1080、1080×1350实跑结果与前端预计一致；
- 自动测试允许的最大差异为1像素，当前样例差异为0。

### 4.7 参数互斥

尺寸缩小 UI 最终提供：

- 按短边：只提交 `target_short_side`；
- 按比例：只提交 `scale_ratio`；
- 指定宽度：只提交 `target_width`；
- 指定高度：只提交 `target_height`。

API 对零参数或多种尺寸参数并存返回400，并在解析输出根目录前结束。

### 4.8 与上传适配的边界

固定短边只作为“尺寸缩小”的默认策略。上传适配继续使用真实平台限制：

- `max_width`
- `max_height`
- `max_file_size_bytes`

长图 `max_height` 默认空；用户主动设置危险高度时，前后端都计算预计短边并执行安全门禁。

### 4.9 输出命名

按短边输出示例：

```text
SHORT-SIDE-E2E-01_中文商业PPT长图_尺寸缩小_短边1080_20260716-152954_44d8.jpg
```

文件名保留中文、清理 Windows 非法字符、限制安全长度、保留实际扩展名，并通过时间和4位 `short_id` 防止覆盖。

### 4.10 反馈包最终结构

同名反馈包：

```text
SHORT-SIDE-E2E-01_中文商业PPT长图_尺寸缩小_短边1080_20260716-152954_44d8_测试反馈包.zip
```

普通图ZIP固定包含：

```text
summary.md
task.json
result.json
review.json
environment.json
validation.json
warnings.json
manifest.json
manifest.sha256
evidence/README.md
```

只有真实长图额外生成 `long_image_validation.json`。`result.json` 保持冻结50字段；`validation.json` 统一保存合同、SHA、完整解码、格式/尺寸/比例、裁切/补边/拉伸/放大、路径、短边、上传限制和交付门禁验证；`summary.md` 根据真实状态动态生成，不再使用通用人工复核结论。

`manifest.json` 与 `manifest.sha256` 都排除自身及彼此，对全部其他文件使用稳定正斜杠相对路径复算SHA256和体积。默认不包含原图、输出图、token、账号、密钥或私人绝对路径。

### 4.11 自动测试

- 固定短边前端纯函数与参数测试：覆盖22项要求；
- 阶段4前端总测试：`68/68 PASS`；
- 阶段4 API 总测试：`75/75 PASS`；
- 真实服务/磁盘闭环：`79/79 PASS`；
- 反馈包六类真实HTTP回放：`6/6 PASS`。

### 4.12 浏览器证据

固定短边5类场景已在 Google Chrome 真实 GUI 中逐项完成本地文件选择、页面执行、状态核对与截图保存，结果为 `SHORT_SIDE_BROWSER_E2E: 5/5 PASS`。对应自动测试和真实服务结果仅作为补充证据，没有替代浏览器点击。

### 4.13 已知限制

非正常 EXIF Orientation 的图片会按显示方向报告 intake 宽高，但冻结阶段3引擎不支持安全方向归一化；阶段4在创建正式任务前返回 `EXIF_ORIENTATION_REQUIRES_NORMALIZATION`，要求用户旋转后另存。该路径失败关闭，不会按错误方向处理。

## 5. 三固定功能目录与扁平化结果

默认根目录：

```text
D:\影界文件\图片压缩输出
```

已实际创建并通过 API 核验：

```text
PNG无损压缩
尺寸缩小
上传适配
```

`GET /api/image-compression/output-settings` 返回200、根目录可写、三个映射与磁盘一致。

新任务：

- 结果直接写入当前模式功能目录；
- 不创建日期目录；
- 不创建 `task_id` 或 `compression_<uuid>` 目录；
- 不创建单任务目录；
- 不创建测试反馈包子目录；
- 失败或执行前阻止不创建空文件；
- 既有历史目录不删除、不移动、不重命名、不合并。

“打开输出目录”：

- 有候选任务时打开登记的功能目录；
- 执行前打开当前模式对应的功能目录；
- 不打开根目录、临时目录或历史任务目录。

## 6. 测试反馈 ZIP

反馈包直接放在输出图片所在功能目录，文件名使用相同 `output_stem`：

```text
<output_stem>_测试反馈包.zip
```

当前包包含摘要、脱敏50字段结果、统一验证、长图验证、尺寸验证和 manifest；默认不包含原图、输出图、私人绝对路径、账号或密钥。SHA256 按实际 ZIP 字节计算，实跑回读一致。

生成接口 `POST /api/image-compression/test-feedback-package` 返回：

- `package_name`
- `package_size_bytes`
- `package_sha256`
- `download_url`
- `display_path`
- `function_directory_path`
- `created_at`
- `expires_at`
- `can_open_folder`

`display_path` 仅用于显示和复制本地路径；`download_url` 固定为不含绝对路径的 `/api/image-compression/feedback-package/<opaque_token>`。下载令牌角色独立为 `feedback_package`，不能与 source/preview token 混用，过期、伪造、跨任务、文件缺失、路径异常或 SHA 不一致均安全拒绝。

反馈包续期前会重新校验原登记路径、ZIP有效性和生成时SHA。过期链接即使未先访问就直接重新生成，旧链接仍明确返回410；已被修改的既有ZIP不会以新的SHA被重新登记。

前端结果区保存并校验反馈包合同，渲染真实 `<a download>` 链接，同时显示包名、体积、路径、SHA摘要和有效期，并提供打开所在文件夹、复制文件路径操作。更换图片、清空任务、重新处理、新任务或令牌过期后清除旧链接。

无候选或无法安全满足的已完成任务允许生成不包含原图和输出图的诊断反馈包，仍直接写入当前模式固定功能目录，不创建额外子目录。诊断包同样使用包含操作、时间和短ID的唯一 `output_stem`，同一源文件重复任务不会发生同名冲突。

本轮真实 5173代理→8787 HTTP 验证覆盖：

- PNG无损压缩反馈包；
- 尺寸缩小反馈包；
- 上传适配反馈包；
- 长图尺寸缩小反馈包；
- 无候选诊断反馈包。

五类均完成 ZIP 下载、正常打开、中文文件名、SHA一致、页面合同路径与磁盘路径一致。

```text
FEEDBACK_PACKAGE_GENERATION: PASS
FEEDBACK_PACKAGE_DOWNLOAD_URL_RETURNED: PASS
FEEDBACK_PACKAGE_LINK_RENDERED: PASS
FEEDBACK_PACKAGE_DOWNLOAD_HTTP: PASS
FEEDBACK_PACKAGE_BROWSER_CLICK: PASS
FEEDBACK_PACKAGE_SHA_ALIGNMENT: PASS
FEEDBACK_PACKAGE_PATH_ALIGNMENT: PASS
FEEDBACK_PACKAGE_UI_CLOSURE: PASS
```

## 7. 验证汇总

| 验证 | 结果 |
| --- | --- |
| Python语法编译 | PASS |
| 阶段3冻结回归 | 39/39 PASS |
| 冻结合同夹具 | 22/22 PASS |
| 阶段4 API | 75/75 PASS |
| 阶段4前端纯函数/会话 | 68/68 PASS |
| Vite正式构建 | PASS |
| 真实5173代理→8787服务闭环 | 79/79 PASS |
| 反馈包六类真实HTTP下载 | 6/6 PASS |
| 反馈包标准结构与双manifest | PASS |
| 默认根目录实际API核验 | PASS |
| Google Chrome真实GUI验收 | 22/22 PASS |
| 原8类浏览器E2E | 8/8 PASS |
| 长图浏览器E2E | 7/7 PASS |
| 固定短边浏览器E2E | 5/5 PASS |
| 反馈包浏览器真实点击下载 | PASS |
| `git diff --check` | PASS |
| staging | 空 |

真实服务证据：

```text
tmp/stage4_e2e_final/live_api_e2e_results.json
tmp/stage4_e2e_final/live_output_20260716_171816/
tmp/stage4_feedback_download_e2e/live_feedback_e2e_results.json
tmp/stage4_feedback_download_e2e/live_output_20260716_171349/
tmp/stage4_edge_acceptance_final/
```

## 8. 真实浏览器 E2E

验收执行环境与结论：

- 执行主体：Codex；
- 浏览器：Google Chrome；
- 浏览器引擎：Chromium；
- 验收类型：真实 GUI；
- 视觉复核：AI 辅助 GUI 复核；
- 验收记录：22/22完成且均为PASS；
- 原8类浏览器 E2E：`8/8 PASS`；
- 长图7类浏览器 E2E：`7/7 PASS`；
- 固定短边5类浏览器 E2E：`5/5 PASS`；
- 测试反馈包真实链接鼠标点击下载：`PASS`；
- 截图：30张；
- 结构化证据：25份；
- DevTools Network：当前控制接口未暴露，非阻断；
- Microsoft Edge：未单独完成专项兼容性验证。

真实GUI验收证据保存在：

```text
tmp/stage4_edge_acceptance_final/
├─ README.md
├─ 验收记录.csv
├─ screenshots/（30张截图）
├─ evidence/（25份结构化证据）
├─ 素材清单.md
└─ assets/（10个测试素材）
```

F01 由 Chrome 页面可见下载链接真实点击触发，ZIP实体可打开，包含10项标准内容，manifest与SHA校验通过。控制接口未暴露浏览器下载副本路径，因此仅按真实下载事件、页面状态和源ZIP完整性如实记录，不以HTTP测试冒充浏览器点击。O08 的“1B”与当前 UI 最小值“0.01KB”差异作为验收说明备注保留，不改变已验证产品行为。

最终状态：

```text
BROWSER_ACCEPTANCE: PASS_WITH_NOTES
FEATURE_IMPLEMENTATION: PASS_WITH_NOTES
FEATURE_SCOPE: FROZEN
STAGE_4_FINAL_STATUS: PASS_WITH_NOTES
STAGE_4_COMMIT_READINESS: READY
```

## 9. 边界与保护

- 不修改 `engine/image_compression/*`；
- 不修改阶段3合同或夹具；
- 不开发批量处理；
- 不执行在线上传；
- 不引入任意源路径或输出路径 API；
- 不删除、移动或迁移历史输出目录；
- 不提交测试图片、输出图、ZIP、临时证据或保护文件。

最终 Git 操作：

```text
RESET: NONE
STASH: NONE
CLEAN: NONE
FILES_STAGED: NONE
COMMIT: NONE
PUSH: NONE
TAG: NONE
PR: NONE
NEXT_STAGE_STARTED: NO
```
