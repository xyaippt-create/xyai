# VisualMasterPro V0.3.6 后端质量守门与输出目录同步包

同步时间：2026-06-05 12:27:50  
项目路径：`D:\Codex\04_Visual-Master-Pro`

本同步包用于同步给 ChatGPT / Gemini，说明 VisualMasterPro / 影界 V0.3.6 后端阶段的最新状态。当前阶段暂停前台 UI 升级，重点完成 1080P 高清交付、双层质量守门、正式输出目录收敛、自动格式选择、Alpha 检测和 final 输出合同稳定化。

---

## 1. 本轮修改文件

本轮实际修改：

```text
main.py
backend/v036_output_core.py
```

未主动修改前端文件。

当前工作区中仍存在此前未提交的前端与同步资产变更，但本轮没有回滚、覆盖或删除。

---

## 2. 核心目标

V0.3.6 的目标不是进入 4K，也不是接入 Real-ESRGAN / SwinIR / HAT，而是先把本地 1080P 忠实高清交付跑稳。

核心原则：

- 保持原图比例
- 不裁切
- 不拉伸
- 不补边
- 不主动改色
- 不重绘内容
- 输出不是原图复制
- 正式目录只保留最终交付图
- 中间产物进入 work/debug/test，不污染正式交付目录

---

## 3. 1080P 尺寸规则已修复

旧问题：

```text
16:9 图片可能输出 1919×1080
```

已修复为硬规则：

```text
16:9  -> 1920×1080
21:9  -> 2520×1080
1:1   -> 1080×1080
9:16  -> 1080×1920
其他比例 -> 保持原比例，以 1080P 高清交付基准输出
fidelity_original -> 保持原尺寸
```

验证结果：

```text
640×360  -> 1920×1080
840×360  -> 2520×1080
500×333  -> 500×333
```

---

## 4. 新增双层质量守门

新增两层质量门：

```text
resolution_gate
visual_quality_gate
```

只有两层都通过，才返回：

```json
{
  "quality_1080p_pass": true
}
```

新增字段：

```text
resolution_gate_pass
visual_quality_gate_pass
quality_1080p_pass
quality_1080p_level
visual_quality_note
```

`quality_1080p_level` 可选值：

```text
failed
acceptable
standard
excellent
```

当前轻量管线验证结果：

```text
16:9 测试图：standard
21:9 测试图：standard
fidelity_original：standard
真实 Alpha 测试图：acceptable
```

---

## 5. 新增 debug_quality 字段

`debug_quality` 已补齐以下字段：

```text
input_width
input_height
output_width
output_height
target_width
target_height
aspect_ratio
aspect_preset
scale_policy
resolution_gate_pass
visual_quality_gate_pass
quality_1080p_pass
quality_1080p_level
visual_quality_note
clarity_score
clarity_gain
text_clarity_score
text_clarity_gain
edge_quality_score
edge_quality_gain
detail_stability_score
color_fidelity_score
artifact_risk
pseudo_hd_risk
compression_damage_risk
quality_before_compression
quality_after_compression
compression_quality_drop
compression_allowed
final_quality_source
has_alpha
has_real_alpha
alpha_used
selected_format_reason
quality_gate
warnings
```

---

## 6. 无感压缩逻辑

当前流程：

```text
生成高清 main_output
生成 optimized_output 候选
对 optimized_output 做质量守门
候选通过且体积更小 -> final 使用 optimized_output
候选失败或体积不优 -> final 回退 main_output
```

新增字段：

```text
quality_before_compression
quality_after_compression
compression_quality_drop
compression_allowed
final_quality_source
compression_note
```

示例：

```json
{
  "final_quality_source": "optimized_output",
  "compression_allowed": true,
  "compression_note": "已完成无感体积优化，画质守门通过，文字、边缘和色彩保持稳定。"
}
```

---

## 7. 输出目录合同

正式输出目录：

```text
输出成品/images/
```

只允许保存最终交付图：

```text
*_vmp_v036_final.*
```

中间输出目录：

```text
输出成品/work/
```

保存：

```text
*_vmp_v036_main.png
*_vmp_v036_optimized.*
```

调试目录：

```text
输出成品/debug/
```

测试与历史占位隔离目录：

```text
输出成品/test/archived/
```

已增加自动隔离规则，以下文件不会留在正式目录：

```text
*_main.*
*_optimized.*
*_candidate.*
*_temp.*
*_debug.*
async_test*
smoke_test*
demo_test*
vmp_async_test*
```

验证中，旧占位文件：

```text
vmp_async_test_vmp_v03_4k.png
```

已从正式目录移动到：

```text
test/archived/
```

---

## 8. final_output_url 合同

当前合同：

```text
final_output_url 指向正式 images 目录的最终图
enhancedUrl 等于 final_output_url
main_output_url 指向 work 目录
optimized_output_url 指向 work 目录
```

示例：

```json
{
  "enhancedUrl": "/api/file/outputs/sixteen_vmp_v036_final.jpg",
  "final_output_url": "/api/file/outputs/sixteen_vmp_v036_final.jpg",
  "main_output_url": "/api/file/work/sixteen_vmp_v036_main.png",
  "optimized_output_url": "/api/file/work/sixteen_vmp_v036_optimized.jpg"
}
```

---

## 9. Alpha 检测逻辑

新增字段：

```text
has_alpha
has_real_alpha
alpha_used
selected_format_reason
```

规则：

```text
RGBA 但 Alpha 全为 255 -> has_alpha=true, has_real_alpha=false，可参与 JPG/WebP 自动选择
RGBA 且存在真实透明区域 -> has_real_alpha=true，强制 PNG
```

验证结果：

```text
RGBA 全不透明：has_alpha=true, has_real_alpha=false, alpha_used=false
RGBA 真实透明：has_alpha=true, has_real_alpha=true, alpha_used=true, selected_output_format=png
```

---

## 10. debug_keep_intermediate

新增上传字段：

```text
debug_keep_intermediate
```

默认：

```text
false
```

当前策略：

- 无论 `debug_keep_intermediate=false` 还是 `true`，正式 `images/` 目录只保留 final 图。
- `main_output` 与 `optimized_output` 保留在 `work/`，供调试和接口引用。
- 不允许中间图进入正式交付目录。

验证：

```text
debug_keep_intermediate=true
images/: 仅 debug_keep_vmp_v036_final.jpg
work/: debug_keep_vmp_v036_main.png, debug_keep_vmp_v036_optimized.jpg
```

---

## 11. API 合同变化

### POST /api/upload

支持字段：

```text
file
mode
scale
format
output_profile
output_format
debug_keep_intermediate
```

默认值：

```text
output_profile=delivery_1080p
output_format=auto
debug_keep_intermediate=false
```

### GET /api/v1/tasks/{task_id}

返回字段已补齐：

```text
taskId
streamEndpoint
originalUrl
enhancedUrl
main_output_url
optimized_output_url
final_output_url
output_profile
output_format
selected_output_profile
selected_output_format
final_output_type
input_width
input_height
output_width
output_height
target_width
target_height
aspect_ratio
aspect_preset
scale_policy
input_size_bytes
main_size_bytes
optimized_size_bytes
final_size_bytes
file_size_ratio
compression_saved_ratio
quality_preserved
compression_note
output_changed
hash_equal
pixel_diff_score
has_alpha
has_real_alpha
alpha_used
selected_format_reason
debug_quality
debug_timing
output_contract
```

---

## 12. SSE 日志变化

仍保持：

```text
event: restoration.log
data: {...}
data: [DONE]
```

第 10 条附近会输出 1080P 质量守门信息：

```text
1080P 质量守门：尺寸目标 1920×1080，正在检测文字清晰度、边缘质量、色彩忠实度与伪高清风险。
```

最终日志会包含：

```text
quality_1080p_pass
quality_level
text_clarity_gain
edge_quality_gain
color_fidelity
pseudo_hd_risk
final_output_url
size_ratio
output_changed
hash_equal
pixel_diff_score
final_output_type
```

---

## 13. 本地验证摘要

验证环境使用项目内安全目录：

```text
D:\Codex\04_Visual-Master-Pro\tests\outputs\v036_backend_validation_final\
```

验证结果：

```text
Python 语法检查：通过
POST /api/upload：200 success
GET /api/v1/tasks/task_vmp_v03_core/stream：200
SSE [DONE]：存在
GET /api/v1/tasks/task_vmp_v03_core：200
16:9：1920×1080
21:9：2520×1080
fidelity_original：500×333
output_changed：true
hash_equal：false
official images：仅 final
work：仅 main/optimized
test/archived：隔离旧测试占位图
```

验证生成文件：

```text
tests/outputs/v036_backend_validation_final/output/images/sixteen_vmp_v036_final.jpg
tests/outputs/v036_backend_validation_final/output/images/wide21_vmp_v036_final.jpg
tests/outputs/v036_backend_validation_final/output/images/origin_vmp_v036_final.jpg
tests/outputs/v036_backend_validation_final/output/work/sixteen_vmp_v036_main.png
tests/outputs/v036_backend_validation_final/output/work/sixteen_vmp_v036_optimized.jpg
tests/outputs/v036_backend_validation_final/output/test/archived/vmp_async_test_vmp_v03_4k.png
```

---

## 14. 给 Gemini / ChatGPT 的重点判断问题

请重点评估：

1. V0.3.6 当前的 1080P 尺寸策略是否适合作为正式合同。
2. `standard / acceptable / excellent` 的阈值是否需要更严格或更贴近视觉主观评价。
3. 当前 light fidelity 管线是否应在 V0.3.7 继续增强文字和边缘，而不是进入 4K。
4. `optimized_output` 通过质量守门后作为 final 是否合理。
5. 真实 Alpha 强制 PNG、全不透明 Alpha 参与 JPG/WebP 自动选择是否符合交付逻辑。
6. 是否需要进一步把 `task_registry` 从单任务内存字典升级为多任务队列。

---

## 15. 下一步建议

建议进入：

```text
VisualMasterPro V0.3.7 Quality Metrics Calibration
```

优先级：

1. 用真实测试图标定质量阈值。
2. 增强中文文字可读性指标。
3. 增强边缘稳定性指标，避免单纯拉普拉斯判断。
4. 增加真实图片对比报告接口。
5. 为每次上传生成独立 task_id，避免单任务覆盖。
6. 在 V0.3.7 稳定后，再进入 V0.4 4K 或模型接入。
