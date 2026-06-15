# VisualMasterPro 给 Gemini 的 V0.3.6 后台输出方案同步包

同步时间：2026-06-05 07:12

项目路径：

```text
D:\Codex\04_Visual-Master-Pro
```

## 1. 当前阶段定位

当前进入 VisualMasterPro / 影界 V0.3.6 后端阶段。

本轮不做前台 UI 升级，不进入 4K，不接 Real-ESRGAN / SwinIR / HAT，不改上传方式，不破坏 XHR 上传和 SSE 日志流。

V0.3.6 的核心目标是：

```text
1080P 高清交付 + 输出方案选择 + 文件格式选择 + 最终输出字段稳定化
```

核心原则：

- 影界不是普通压缩工具，而是高清交付引擎。
- 体积尽量小，但不能以画质下降为代价。
- 不能为了压缩牺牲中文文字清晰度、边缘质量、色彩忠实度、画面层次和整体通透感。

## 2. 已完成后台能力

新增核心文件：

```text
backend/v036_output_core.py
```

该文件负责：

- `output_profile` 输出方案解析
- `output_format` 输出格式解析
- 1080P 高清交付尺寸计算
- 原比例输出，不裁切、不拉伸、不补边
- 高清主图 `main_output`
- 体积优化候选图 `optimized_output`
- 最终交付图 `final_output`
- 质量守门
- 文件体积优化判断
- `final_output_url` 稳定化
- hash、像素差异、输出真实性检测
- 压缩收益与质量保持字段

## 3. 新增 POST /api/upload 字段

接口：

```text
POST http://localhost:8787/api/upload
```

仍然使用 XHR + FormData。

文件字段保持不变：

```text
file
```

新增字段：

```text
output_profile
output_format
```

旧字段继续兼容：

```text
format
```

如果前端未传 `output_format`，后端会读取旧字段 `format`。

如果 `output_format` 和 `format` 都没有，则默认：

```text
output_format = auto
```

## 4. output_profile 合同

支持三个值：

```text
delivery_1080p
preview_light
fidelity_original
```

默认：

```text
delivery_1080p
```

### delivery_1080p

中文含义：高清交付 1080P

用途：

- 默认主输出方案
- 保持原比例
- 达到 1080P 高清交付标准
- 质量优先
- 允许合理体积增加
- 需要经过体积优化和质量守门

### preview_light

中文含义：轻量优化版

用途：

- 体积优先
- 适合快速预览、PPT 快速插入、分享场景
- 可以自动选择 JPG / WebP
- 但不能明显损伤文字、边缘、色彩和层次

### fidelity_original

中文含义：原尺寸忠实增强

用途：

- 输出尺寸与原图一致
- 不主动放大
- 只做轻度清洁、文字清晰、边缘稳定和色彩锁定

## 5. output_format 合同

支持四个值：

```text
auto
png
jpg
webp
```

默认：

```text
auto
```

自动选择逻辑：

- 透明图：PNG
- 文字密集 / UI / PPT 截图：JPG 95，并启用质量守门
- 照片 / 场景 / 渐变图：JPG 94–95
- `preview_light`：优先 WebP
- 如果候选格式导致画质下降，则回退高清主图

## 6. 1080P 尺寸规则

V0.3.6 已修正：

```text
1080P 不等于所有图片固定 1920×1080
```

当前规则：

- 16:9 → 1920×1080
- 21:9 → 约 2520×1080
- 1:1 → 1080×1080
- 9:16 → 1080×1920
- 其他比例 → 保持原比例，以 1080P 短边基准输出
- `fidelity_original` → 保持原尺寸

禁止：

- 强制所有图片输出 1920×1080
- 裁切
- 拉伸
- 补边
- 改变构图比例

## 7. 三层输出文件

V0.3.6 每次任务生成三类输出：

```text
main_output
optimized_output
final_output
```

含义：

- `main_output`：高清主图，通常为 PNG 基准图
- `optimized_output`：体积优化候选图，可能是 JPG / WebP
- `final_output`：最终交付图，前端默认展示和下载

规则：

如果优化候选通过质量守门，并且体积更小：

```text
final_output_url = optimized_output_url
```

如果优化候选未通过，或候选不比主图更小：

```text
final_output_url = main_output_url
```

旧字段：

```text
enhancedUrl
```

仍然保留，并继续指向最终交付图，避免破坏现有前端。

## 8. 返回字段稳定化

`POST /api/upload` 和 `GET /api/v1/tasks/{task_id}` 均开始返回以下字段：

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
```

如果任务尚未完成，部分字段会返回 `null`，不会导致前端报错。

## 9. SSE 日志变化

接口保持：

```text
GET /api/v1/tasks/task_vmp_v03_core/stream
```

仍然输出 11 条 `restoration.log`，最后仍发送：

```text
data: [DONE]
```

第 10 条现在包含输出方案和格式策略：

```text
输出方案：delivery_1080p，保持原比例，以 1080P 短边基准生成高清交付图。格式策略：auto → jpg。
```

第 11 条现在包含最终结果：

```text
任务完成：final_output 已生成；quality_preserved=True；size_ratio=...；output_changed=True；hash_equal=False；pixel_diff_score=...；final_output_type=...；total_time=...s
```

第 11 条 payload 额外携带：

```text
debug_quality
debug_timing
output_contract
```

其中 `output_contract` 包含：

```text
main_output_url
optimized_output_url
final_output_url
output_profile
output_format
selected_output_profile
selected_output_format
final_output_type
quality_preserved
compression_note
```

## 10. 验收结果

本轮使用工作区内安全目录完成 API/SSE 验证，不触碰用户桌面目录。

验证结果：

```text
Python 语法检查：通过
前端构建：通过
POST /api/upload：200 success
SSE：200
restoration.log：11 条
[DONE]：true
final_output_url：稳定返回
输出文件访问：200
quality_preserved：true
output_changed：true
hash_equal：false
```

## 11. 关键测试样例

### 16:9 delivery_1080p + auto

输入：

```text
640×360
```

输出：

```text
1920×1080
aspect_preset = 16:9
selected_output_format = jpg
final_output_type = optimized_output
quality_preserved = true
```

### 21:9 delivery_1080p + auto

输入：

```text
840×360
```

输出：

```text
2520×1080
aspect_preset = 21:9
selected_output_format = jpg
final_output_type = optimized_output
quality_preserved = true
```

结论：

```text
21:9 已保持比例，没有被错误压成 1920×1080。
```

### fidelity_original + jpg

输入：

```text
500×333
```

输出：

```text
500×333
aspect_preset = custom
final_output_type = main_output
selected_output_format = png
quality_preserved = true
```

说明：

虽然请求了 JPG，但候选 JPG 没有比高清主图更优，最终回退到主图 PNG。

### preview_light + auto

输入：

```text
640×360
```

输出：

```text
1920×1080
selected_output_format = webp
final_output_type = optimized_output
compression_saved_ratio = 0.788
quality_preserved = true
```

结论：

轻量预览版已优先使用 WebP，并通过质量守门。

## 12. 给 Gemini 的下一步建议

请 Gemini 后续只围绕“前端展示这些后端字段”进行设计，不要破坏当前真实链路。

建议下一步前端增强：

1. 工作台增加 `output_profile` 三卡片选择：
   - 高清交付 1080P
   - 轻量优化版
   - 原尺寸忠实增强
2. 工作台增加 `output_format` 选择：
   - 自动
   - PNG
   - JPG
   - WebP
3. 对比页默认使用：

```text
final_output_url
```

4. 质量报告页展示：

```text
main_output_url
optimized_output_url
final_output_url
quality_preserved
compression_note
compression_saved_ratio
pixel_diff_score
```

5. 不要改 XHR 上传。
6. 不要改 SSE EventSource。
7. 不要把 `enhancedUrl` 删除，它仍是旧前端兼容字段。
8. 后续前端下载按钮应优先使用 `final_output_url`。

## 13. 禁止改动提醒

Gemini 不应做以下事情：

- 不要把上传改回 fetch。
- 不要删除 XHR 上传。
- 不要删除 `[DONE]` 逻辑。
- 不要把所有图强行显示成 1920×1080。
- 不要只用 `enhancedUrl`，应逐步升级到 `final_output_url`。
- 不要为了视觉效果隐藏质量守门字段。
- 不要改变后端接口路径。
