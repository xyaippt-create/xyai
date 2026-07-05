# Codex Changelog

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
