# Codex Changelog

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

## 2026-06-17 - V0.4.6 T02 golden image set

### 已完成

- 建立 `tests/golden_v046/` 黄金测试集目录结构。
- 新增 `manifest.json` 与 `manifest.csv`，记录 ready、missing、synthetic、future reference color match 字段。
- 新增 `tests/tools/verify_golden_v046.py` 完整性校验脚本。
- 新增 `tests/run_golden_v046.py` Phase 1 基线运行脚本。
- 新增 `docs/reports/V046_T02_GOLDEN_SET.md`。

### 验证结果

- `tests/tools/verify_golden_v046.py`：PASS。
- `tests/run_golden_v046.py`：PASS，19 个 ready 样本全部完成，7 个样本 `quality_1080p_pass=false`，13 个样本出现文件体积扩张警告。

### 未解决

- Core Set 目前 7 个 ready、12 条 missing、5 条 excluded，未用低价值图片凑满。
- 5 个旧模式大图输出样本因体积过大未作为提交版 golden 输入纳入仓库，已作为 excluded 缺口保留。
- Extended Set 当前为缺口表与未来参考色彩字段预留。
- 低质量活动照片仍缺少可提交或可私有测试样本。
