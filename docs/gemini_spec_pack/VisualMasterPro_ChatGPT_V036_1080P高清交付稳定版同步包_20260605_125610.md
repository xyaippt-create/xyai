# VisualMasterPro / 影界 V0.3.6 1080P 高清交付稳定版同步包

同步时间：2026-06-05 12:56:10  
项目路径：`D:\Codex\04_Visual-Master-Pro`  
同步对象：ChatGPT  

本同步包用于把当前 VisualMasterPro / 影界项目的最新后端状态同步给 ChatGPT，用于后续视觉判断、质量策略分析、参数校准和 V0.3.7 / V0.4 规划。

---

## 1. 当前阶段结论

VisualMasterPro V0.3.6 已完成“1080P 高清交付稳定版”后端收口。

本轮核心目标只有一个：

```text
1080P 必须真正站住。
```

当前已确认：

- 16:9 输出为 `1920×1080`
- 21:9 输出为约 `2520×1080`
- `1915×821` 这类 21:9 通信工程图不再被压成 `2048×877`
- `quality_1080p_pass` 必须同时依赖尺寸守门和画质守门
- 用户输出目录只保留一张最终图
- 中间图不再污染用户桌面输出目录
- `enhancedUrl` 与 `final_output_url` 保持一致，继续兼容旧前端

---

## 2. 本轮修改文件

本轮实际修改：

```text
main.py
backend/v036_output_core.py
```

本轮没有修改：

```text
src/DashboardPage.jsx
src/TaskDetailPage.jsx
前端 UI
XHR 上传方式
SSE EventSource
[DONE] 完成逻辑
```

---

## 3. 1080P 尺寸规则

`delivery_1080p` 当前尺寸规则：

```text
16:9  -> 1920×1080
21:9  -> 2520×1080
1:1   -> 1080×1080
9:16  -> 1080×1920
其他比例 -> 保持原比例，以 1080P 高度或短边为基准
fidelity_original -> 保持原尺寸
```

禁止：

- 裁切
- 拉伸
- 补边
- 改变比例
- 所有图片强制压成 1920×1080
- 21:9 被压成 2048×877

---

## 4. 已修复 21:9 2048 宽度限制

此前发现的问题：

```text
输入：1915×821
错误输出：2048×877
```

当前修复结果：

```text
输入：1915×821
输出：2520×1080
aspect_preset=21:9
resolution_gate_pass=true
```

说明：

`delivery_1080p` 阶段已移除 2048 宽度上限、旧 scale 限制、2K width cap 或按宽度限制导致高度不足 1080 的逻辑。

---

## 5. 双层质量守门

当前 `quality_1080p_pass` 不能只看尺寸。

必须同时满足：

```text
resolution_gate_pass = true
visual_quality_gate_pass = true
```

才允许：

```text
quality_1080p_pass = true
```

如果尺寸未达标：

```text
quality_1080p_pass=false
quality_1080p_level=failed
```

如果尺寸达标但文字、边缘、色彩、细节、伪高清风险不达标：

```text
quality_1080p_pass=false
```

---

## 6. quality_1080p_level

当前等级：

```text
failed      未达到 1080P 高清交付
acceptable  基本可用，适合测试
standard    达到 1080P 高清交付标准
excellent   高质量 1080P 输出
```

判断原则：

- 尺寸失败不能进入 `standard` 或 `excellent`
- 画质失败不能进入 `standard` 或 `excellent`
- 只尺寸达标但画质一般，最多 `acceptable`
- `excellent` 必须保守返回，不轻易给

---

## 7. 当前质量字段

后端已在 `POST /api/upload`、`GET /api/v1/tasks/{task_id}`、`debug_quality`、`output_contract` 中补齐或预留以下字段：

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
final_output_url
enhancedUrl
output_changed
hash_equal
pixel_diff_score
```

---

## 8. final_output_url 合同

当前规则：

```text
final_output_url 必须指向最终交付图
enhancedUrl 必须等于 final_output_url
```

普通用户模式：

```text
main_output_url = null
optimized_output_url = null
```

调试模式：

```text
main_output_url -> /api/file/work/xxx_main.png
optimized_output_url -> /api/file/work/xxx_optimized.jpg
```

---

## 9. 用户输出目录收口

用户侧正式输出目录：

```text
C:\Users\xyppt\Desktop\雪原Ai增强引擎\输出成品\
```

当前合同：

```text
该目录只允许出现一张最终图
```

不允许出现：

```text
images/
work/
debug/
test/
main_output
optimized_output
debug_quality
debug_timing
output_contract
async_test
smoke_test
demo_test
vmp_async_test
```

本轮已将原来的：

```text
输出成品/images/
输出成品/work/
输出成品/debug/
输出成品/test/
```

收口为：

```text
输出成品/最终图
```

---

## 10. 后台中间文件处理

后端仍保留三层处理逻辑：

```text
main_output       高清主图
optimized_output  体积优化候选图
final_output      最终交付图
```

但普通模式下：

```text
main_output / optimized_output 默认生成后清理
用户输出目录不会看到中间图
```

调试模式：

```text
debug_mode=true
```

中间图保存在项目内部：

```text
D:\Codex\04_Visual-Master-Pro\runtime\work
D:\Codex\04_Visual-Master-Pro\runtime\debug
D:\Codex\04_Visual-Master-Pro\runtime\test
```

---

## 11. SSE 日志状态

SSE 仍保持：

```text
event: restoration.log
data: {...}
data: [DONE]
```

最终日志包含：

```text
quality_1080p_pass
quality_1080p_level
resolution_gate_pass
visual_quality_gate_pass
output_width
output_height
final_output_url
enhancedUrl
output_changed
hash_equal
pixel_diff_score
```

---

## 12. 实测结果

### 16:9 测试图

```text
输入：640×360
输出：1920×1080
aspect_preset=16:9
resolution_gate_pass=true
visual_quality_gate_pass=true
quality_1080p_pass=true
quality_1080p_level=standard
final_output_url=/api/file/outputs/sixteen_9_vmp_v036_final.jpg
enhancedUrl=/api/file/outputs/sixteen_9_vmp_v036_final.jpg
main_output_url=null
optimized_output_url=null
```

输出目录只包含：

```text
sixteen_9_vmp_v036_final.jpg
```

### 21:9 通信工程测试图

```text
输入：1915×821
输出：2520×1080
aspect_preset=21:9
resolution_gate_pass=true
visual_quality_gate_pass=true
quality_1080p_pass=true
quality_1080p_level=standard
final_output_url=/api/file/outputs/comm_21_9_1915x821_vmp_v036_final.jpg
enhancedUrl=/api/file/outputs/comm_21_9_1915x821_vmp_v036_final.jpg
main_output_url=null
optimized_output_url=null
```

输出目录只包含：

```text
comm_21_9_1915x821_vmp_v036_final.jpg
```

### fidelity_original 测试图

```text
输入：500×333
输出：500×333
scale_policy=保持原尺寸，仅做忠实清洁增强
quality_1080p_pass=true
quality_1080p_level=standard
```

输出目录只包含：

```text
fidelity_original_vmp_v036_final.jpg
```

---

## 13. 21:9 测试图完整 debug_quality

```json
{
  "input_width": 1915,
  "input_height": 821,
  "output_width": 2520,
  "output_height": 1080,
  "target_width": 2520,
  "target_height": 1080,
  "aspect_ratio": 2.332521,
  "aspect_preset": "21:9",
  "scale_policy": "保持原比例，不裁切、不拉伸、不补边，以 1080P 高清交付基准输出。",
  "resolution_gate_pass": true,
  "visual_quality_gate_pass": true,
  "quality_1080p_pass": true,
  "quality_1080p_level": "standard",
  "visual_quality_note": "清晰度 44.4587，文字 35.5991，边缘 27.2345，色彩忠实 98.0153，伪高清风险 low。",
  "clarity_score": 44.4587,
  "clarity_gain": 1.83,
  "text_clarity_score": 35.5991,
  "text_clarity_gain": 0.0723,
  "edge_quality_score": 27.2345,
  "edge_quality_gain": 2.0588,
  "detail_stability_score": 90.6198,
  "color_fidelity_score": 98.0153,
  "artifact_risk": "low",
  "pseudo_hd_risk": "low",
  "compression_damage_risk": "low",
  "quality_before_compression": 55.7462,
  "quality_after_compression": 55.4457,
  "compression_quality_drop": 0.3005,
  "compression_allowed": true,
  "final_quality_source": "optimized_output",
  "output_changed": true,
  "hash_equal": false,
  "pixel_diff_score": 1.524202
}
```

---

## 14. 本轮验证文件

验证使用项目内安全目录：

```text
D:\Codex\04_Visual-Master-Pro\tests\outputs\v036_1080p_stable_validation\
```

实际生成：

```text
D:\Codex\04_Visual-Master-Pro\tests\outputs\v036_1080p_stable_validation\sixteen_9\output\sixteen_9_vmp_v036_final.jpg
D:\Codex\04_Visual-Master-Pro\tests\outputs\v036_1080p_stable_validation\comm_21_9_1915x821\output\comm_21_9_1915x821_vmp_v036_final.jpg
D:\Codex\04_Visual-Master-Pro\tests\outputs\v036_1080p_stable_validation\fidelity_original\output\fidelity_original_vmp_v036_final.jpg
```

语法检查：

```text
main.py 通过
backend/v036_output_core.py 通过
```

---

## 15. 给 ChatGPT 的重点判断问题

请 ChatGPT 重点评估：

1. 当前 16:9 / 21:9 / 1:1 / 9:16 的 1080P 尺寸合同是否合理。
2. `quality_1080p_level` 当前阈值是否需要进一步校准。
3. `standard` 是否应该更严格，尤其是文字清晰度与边缘稳定性。
4. `fidelity_original` 是否应该使用单独字段，例如 `quality_original_pass`，避免和 1080P 语义混淆。
5. 当前默认清理 main/optimized 是否合理，还是应在内部日志中保留更多可追踪证据。
6. V0.3.7 是否应优先做“真实测试图质量阈值校准”，而不是进入 4K 或大模型。

---

## 16. 下一步建议

建议下一阶段：

```text
VisualMasterPro V0.3.7 Quality Calibration
```

优先事项：

1. 用真实展板、建筑、文物、PPT、截图图片校准质量阈值。
2. 建立更可靠的中文文字清晰度评价。
3. 建立更可靠的边缘稳定性评价。
4. 增加“伪高清风险”更严格判定。
5. 增加质量报告接口，但默认不打扰用户。
6. 保持用户输出目录单图交付逻辑。
