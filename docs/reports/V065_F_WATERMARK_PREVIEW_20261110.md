# V0.6.5 F 线批量水印大图预览提速验收

## STATUS

- `FINAL_STATUS=PASS`（隔离候选） · `FREEZE_STATUS=NOT_READY`
- `VERSION=0.6.5-dev` · `BRANCH=codex/image-processing-routing-v1` · `HEAD=b4fdde85dc036537382fb16252e1f1473c215e61`
- 候选构建 `V0.6.5-dev+b4fdde85dc03.unknown.20261110T003815482Z`。构建工作区标记为 `unknown`，现场 Git 核实为已有未提交改动的工作区。

## FILES_MODIFIED

- `engine/batch_watermark/engine.py`、`backend/batch_watermark_api.py`、`src/BatchWatermarkPage.jsx`
- `tests/batch_watermark/test_batch_watermark_api.py`、`docs/09_CODEX_CHANGELOG.md`、本报告

## IMPLEMENTED

- 基线中全尺寸 PNG 编码约 1.7–2.5 秒，服务端接收上传约 34–102 毫秒。先验证按原像素坐标合成再缩小的几何一致性，随后让水印工作台只编码最长边 1600 像素的显示副本。
- 保留原尺寸合成、PNG 色彩与透明度。参数、图片或 Logo 变化后只展示对应的新预览。失效素材显示真实原因，迟到响应不会改写当前画面。

## VALIDATION

生成样本前核对隔离数据根和实际水印输出路径。样本为实拍相机文件主帧的独立 JPEG（保留方向和 DPI）、同实拍内容派生的带 Alpha 渐变大图 PNG，以及透明 PNG Logo。真实 Edge `157.0.4341.42` 在本地隔离服务运行三组交错对照，顺序为基线→候选、候选→基线、基线→候选。

| 样本与操作 | 上传量 MB | 服务端接收 ms | 后端渲染含编码 ms | 收完响应至画面更新 ms | 操作至画面更新 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| JPG 文字首图 | 10.02→10.02 | 33→30 | 2562→696 | 707→100 | 3684→1145 |
| JPG 文字调参 | 10.02→10.02 | 29→30 | 2549→657 | 624→89 | 3612→1122 |
| PNG Logo 首图 | 27.70→27.70 | 104→123 | 2166→850 | 598→104 | 3240→1407 |
| PNG Logo 调参 | 27.70→27.70 | 85→80 | 2180→865 | 538→89 | 3284→1397 |

- 以上为中位数。每种模式每组测一次首图、两次调参。首图端到端降幅分别为 68.9% 和 56.6%，调参降幅分别为 68.9% 和 57.4%。响应从约 27–33 MB 降至约 4 MB。
- 缩小先验验证中，文字和 Logo 的边界偏差小于 1 像素，文字方向差小于 0.02°，平铺横向及隔行纵向周期为 282 和 426 像素，与投影值一致。六张实际候选预览与各自基线的 Lanczos 缩小参考逐 RGBA 像素一致，包含半透明边缘。
- 快速调参最后只显示「最终水印」，释放旧响应后仍保持当前帧。切图、换 Logo 的页面帧哈希分别与真实响应匹配。损坏原图及不透明 Logo 均显示预览不可用。
- 相同输入和参数的正式成品与改动前基准逐文件 SHA256 一致。JPEG 保持方向归一后的 3648×5472、72 DPI，PNG 保持 3200×4800、约 300 DPI，Alpha 哈希一致。
- 隔离 NTFS 写入失败及取消回归中，原成功行和取消行保留，文字水印只为原失败项新增一份成品，重复请求未多写。36 项 Python、17 项 Node、隔离构建及差异检查通过。
- [原始交错计时](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-preview-v065/interleave.json) · [预览像素与计时汇总](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-preview-v065/measurement-summary.json) · [正式成品核对](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-preview-v065/formal-audit.json)
- 截图对照 [文字基线](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-preview-v065/baseline-text-tile.png) · [文字候选](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-preview-v065/candidate-text-tile.png) · [Logo 基线](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-preview-v065/baseline-image-opacity.png) · [Logo 候选](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-preview-v065/candidate-image-opacity.png)

## BLOCKER

- 功能验收无阻断。GPT‑6.1 Terra / xhigh 的实际配置为 `NOT_VERIFIED`。

## PROTECTION

- 暂存区为空，范围外 47 个已改 tracked 文件的哈希一致，批量压缩并行产物原样保留。样本、浏览器证据、写入探针和构建均位于隔离目录，探针权限已恢复。未执行 Git 写操作、正式部署或冻结。
