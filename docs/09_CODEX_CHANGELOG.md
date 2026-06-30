# Codex Changelog

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
