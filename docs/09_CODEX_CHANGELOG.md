# Codex Changelog

## 2026-06-29 - V0.4.6 RC1 safe 1080P Beta selected input binding

- 修复 Dashboard 1080P安全增强 Beta 处理默认测试样本而非当前队列图片的问题。
- Dashboard Beta 请求改为 multipart 上传当前队列文件，不再发送默认测试样本目录作为输入源。
- Dashboard Beta 增加 `selected_file_names_encoded`，避免中文文件名在 multipart 边界被转码后影响输出命名。
- Beta API 加固 multipart 字段解析、中文文件名解码、临时文件保存和结果归一化，避免异常时返回裸 500。
- Beta API 增加 `BETA_REQUEST_INPUT_FILES` 与 `BETA_RESOLVED_INPUT_FILES` 阶段日志；没有显式输入文件时返回 `BETA_INPUT_MISSING`。
- `safe_1080p_enhance.py` 在 flat/business 模式下只处理显式 `input_files`，并在结果中返回 input/output 映射。

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
