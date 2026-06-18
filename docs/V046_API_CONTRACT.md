# V0.4.6 API 合同冻结说明

生成日期：2026-06-18

## 1. 正式处理链

V0.4.6 后台正式处理链保持：

```text
main.py
→ engine.pipeline.process_v046_delivery
→ v046_1080p_delivery
→ v046_delivery_adapter
→ process_v036_output
→ engine/algorithms/*
→ safe_copy_final
→ final_output_url
```

要求：

- `pipeline_call_count=1`
- 上传后立即后台启动任务
- SSE 只订阅日志和最终状态
- SSE 重连和双订阅不得重复启动处理
- `final_output_url` 指向真实最终文件

## 2. 默认输出目录

Windows 默认输出目录：

```text
D:\影界文件\输出成品
```

默认输入目录：

```text
D:\影界文件\输入图片
```

旧的雪原目录配置会在加载设置时回到当前默认输出目录。

## 3. 任务结果字段

V0.4.6 Phase 6 固定以下输出相关字段：

```text
output_directory
output_directory_source
final_output_path
final_output_filename
final_output_url
preview_output_url
enhancedUrl
downloadUrl
```

交付质量字段：

```text
final_delivery_status
final_delivery_reason
final_delivery_risk_level
final_delivery_recommended_usage
```

交付状态取值：

```text
PASS
PASS_WITH_LIMITATION
FAIL
```

## 4. 反馈诊断 ZIP API

创建反馈包：

```text
POST /api/v1/tasks/{task_id}/feedback-bundle
```

读取或创建反馈包：

```text
GET /api/v1/tasks/{task_id}/feedback-bundle
```

响应核心字段：

```text
feedback_bundle_status
feedback_bundle_path
feedback_bundle_size
feedback_bundle_redacted
feedback_bundle_error
```

约束：

- 默认写入 `D:\影界文件\诊断反馈`
- 不包含用户原图
- 不包含最终输出图
- 默认脱敏路径、账号和敏感字段

## 5. 错误约定

输出目录不可用或目标路径为文件时，上传接口返回 HTTP 400，并给出明确错误信息。

失败任务 SSE 必须发送 `[DONE]` 并结束连接。
