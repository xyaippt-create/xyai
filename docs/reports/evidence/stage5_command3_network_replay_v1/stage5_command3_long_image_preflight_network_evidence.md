# 阶段5指令三｜真实 Chrome 长图预检网络证据说明

## 1. 证据结论

本证据来自真实 Google Chrome 页面交互，不是 curl、TestClient、fixture 回放或 mock API。Chrome 打开当前生产构建，上传真实 `1000 × 5000` PNG 长图，选择“缩小图片尺寸”，输入目标短边 `599`，点击“分析并推荐”。同源本地反向代理仅转发请求到当前项目真实后端，并在请求经过时生成脱敏结构化证据。

```text
REAL_CHROME_REPLAY: PASS
PREFLIGHT_REQUEST_CAPTURED: YES
PREFLIGHT_REQUEST_SOURCE: REAL_CHROME
CHROME_NETWORK_EVIDENCE: PASS
```

## 2. 真实请求

- 开始时间：`2026-07-18T07:24:09.506140+00:00`
- 完成时间：`2026-07-18T07:24:09.530947+00:00`
- 持续时间：`26.054 ms`
- URL：`http://127.0.0.1:5174/api/image-processing/preflight`
- Method：`POST`
- Content-Type：`application/json`
- 浏览器信号：`Google Chrome`、`Sec-Fetch-Mode: cors`、`Sec-Fetch-Site: same-origin`

脱敏请求体：

```json
{
  "file_token": "[REDACTED_VALID_TOKEN]",
  "purpose": "REDUCE_DIMENSIONS",
  "targets": {
    "resize_strategy": "FIXED_SHORT_SIDE",
    "target_short_side": 599
  },
  "requested_action": null
}
```

请求不包含绝对路径、原始图片二进制、Cookie、Authorization 或用户完整文件路径。正式证据没有保留 token 原文；preview URL 中的 token 同样替换为 `[REDACTED_TOKEN]`。

## 3. 真实响应

- HTTP Status：`200`
- `preflight_status`：`BLOCKED_UNSAFE`
- `recommended_action`：`UNSUPPORTED`
- `executable`：`false`
- 长图画像：`is_long_image=true`，原始尺寸 `1000 × 5000`
- 阻止原因：`ESTIMATED_SHORT_SIDE_LT_600`
- 替代动作：`RESIZE_REDUCTION`
- 真实字段位置：`response_body.alternatives[0].targets.target_short_side`
- 真实字段值：`750`
- `required_targets`：当前真实替代方案未返回该字段，因此为 `NOT_APPLICABLE`；证据未人工补造空字段。

真实替代方案结构：

```json
{
  "action": "RESIZE_REDUCTION",
  "targets": {
    "resize_strategy": "FIXED_SHORT_SIDE",
    "target_short_side": 750
  }
}
```

页面在同一次 Chrome 会话中显示“图片尺寸缩小”和“缩小策略：固定短边 · 短边：750像素”，证明用户可见值来自真实响应而非前端固定文案。

## 4. Chrome 视觉复核

- 1440×900浅色：PASS，`scrollWidth == clientWidth == 1440`。
- 1920×1080深色：PASS，`scrollWidth == clientWidth == 1920`。
- 跟随系统：PASS，本次实际生效为深色。
- 控制台错误：`0`。
- Stage5预检面板绝对路径：无。
- 内容裁切：无。
- 自动处理入口：无。

正式截图：

- `stage5_command3_long_image_preflight_1440x900_light.png`
- `stage5_command3_long_image_preflight_1920x1080_dark.png`

截图SHA256：

- 1440×900：`c5e9d93f72233d9d0cda4a13e02015e16f8fed2507ba0d076da45982f5ab09d9`
- 1920×1080：`be99518a9afa7982580ce15573957801e71be73b00f9f001a08e3428e3b52d10`

## 5. 副作用核验

预检前后对图片压缩正式输出根目录使用相对路径、大小和SHA256形成机器清单并逐项比较：

- 文件总数：`3 → 3`
- 图片文件：`2 → 2`
- 反馈包ZIP：`1 → 1`
- 文件清单与SHA256：完全一致
- 顶层目录：`PNG无损压缩`、`上传适配`、`尺寸缩小`，完全一致
- 会话网络请求中 `/run`、任务创建、下载、反馈包请求：`0`

因此：

```text
AUTO_PROCESSING_TRIGGERED: NO
TASK_SIDE_EFFECTS: NONE
OUTPUT_SIDE_EFFECTS: NONE
DOWNLOAD_SIDE_EFFECTS: NONE
FEEDBACK_PACKAGE_SIDE_EFFECTS: NONE
```

阶段4 intake 为取得本轮真实 source token 的必要步骤；没有调用任何处理或下载接口。

## 6. 日志与结构化文件

- 等价网络证据：`stage5_command3_long_image_preflight_network.json`（4931 bytes）
- 请求摘要：`stage5_command3_long_image_preflight_request_sanitized.json`（831 bytes）
- 响应摘要：`stage5_command3_long_image_preflight_response_sanitized.json`（1759 bytes）
- Chrome UI证据：`stage5_command3_chrome_ui_evidence.json`（1819 bytes）
- 后端日志：`stage5_command3_backend.log`（非空；记录启动、监听、请求、状态和关闭）
- 前端日志：`stage5_command3_frontend.log`（非空；记录生产构建、Chrome请求、状态和关闭）
- 副作用前清单：`stage5_command3_side_effects_before.json`
- 副作用后清单：`stage5_command3_side_effects_after.json`
- 副作用比较：`stage5_command3_side_effects_comparison.json`

结构化请求SHA256：`a705c05572e14af7d961d16a197fe58a4f84b8146a5b2da51871bbc719585535`

结构化响应SHA256：`92d0b29d24198f5818f4271d6a5bc60480f38ed853e99ee3b16f8e9d29a2759d`

正式证据采用“真实 Chrome → 同源脱敏反向代理 → 当前项目真实8787后端”的等价捕获方案。代理没有生成业务响应、没有修改请求语义；请求与响应体均来自实际转发流量。

会话中 `/api/image-compression/output-settings` 返回既有HTTP 400，但页面使用原有fallback且控制台错误为0；该请求与本轮预检endpoint及其HTTP 200证据无关，本轮未修改相关业务逻辑。
