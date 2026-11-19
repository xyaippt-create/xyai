# V0.6.5 批量水印隔离候选验收

## STATUS

- `FINAL_STATUS=PASS`（隔离候选） · `FREEZE_STATUS=NOT_READY`
- 版本 `0.6.5-dev` · 分支 `codex/image-processing-routing-v1` · HEAD `b4fdde85dc036537382fb16252e1f1473c215e61`
- 以任务要求现场核对的 HEAD 为基线。构建身份 `V0.6.5-dev+b4fdde85dc03.unknown.20261109T235253342Z`，其中 `unknown` 是构建记录中的工作区标记，现场 Git 检查确认工作区已有未提交变更。

## FILES_MODIFIED

- `src/BatchWatermarkPage.jsx`、`backend/batch_watermark_api.py`
- `tests/image_compression_ui/test_batch_watermark_ui.mjs`、`tests/batch_watermark/test_batch_watermark_api.py`
- `docs/09_CODEX_CHANGELOG.md`、本报告

## IMPLEMENTED

- 基线 Edge 中，运行期间追加的 `extra.png` 留在页面并被标为失败，实际请求仅处理了原来的 `same.png`。从输出中心带入的成品在追加本地图片后消失。前端分别按返回数组下标回填、将无本地 File 对象的条目当成历史行，触发了两处错配。
- 提交时固定图片清单和参数，运行中禁用增删及参数编辑，保留取消入口。上传表单和结果按同一个客户端条目 ID 对应，服务端 Task 和 Result 保持独立身份。待加载的输出中心成品解析完成后合入清单。单张成品无法读取时记录该条目的真实失败原因。
- 复用水印引擎、文件命名和防覆盖发布。已有批次读取和旧提交格式继续可用。

## VALIDATION

- `python -m unittest discover -v -s tests/batch_watermark` 34 项通过，覆盖反序上传、重复 ID 拒绝、成品失效、同名发布、DPI、Alpha 和原图保护。
- `node --test tests/image_compression_ui/test_batch_watermark_ui.mjs` 16 项通过，覆盖乱序回填、重复回执拒绝及历史恢复。Vite 隔离构建通过。
- Microsoft Edge `157.0.4341.42` 加载隔离构建。真实请求未替换，验证脚本仅延迟向页面交付部分响应，以稳定复现输入锁定及成品加载顺序。运行中点「继续添加」未弹出文件选择器，直接送达文件变更事件也未改动清单。页面无 JavaScript 或控制台错误。

| 批次 | 输入 | 页面与后端状态 | 实际成品 |
| --- | --- | --- | --- |
| 混合 | 输出中心既有水印成品，420×270 | 完成，保留原 Result 来源 | `history_影界水印_261110_02_影界水印_261110_02.png` |
| 混合 | 红色 `same.png`，820×520 | 完成 | `same_影界水印_261110_04.png` |
| 混合 | 绿色 `same.png`，650×460 | 完成 | `same_影界水印_261110_05.png` |
| 混合 | `broken.png` | 失败，无法读取源图片 | 无 |
| 取消 | 已开始的 `slow.png`，4600×3900 | 完成 | `slow_影界水印_261110.png` |
| 取消 | 两张 `same.png` 和 `extra.png` | 三条各自取消 | 无 |

- 输出中心显示混合批次的三条独立 Result。修复前生成的批次 `watermark_batch_21979e712ae24cbd` 在候选中按原链接打开，原 Result ID、状态及文件哈希一致。
- 逐张复核输入 SHA256、源副本、成品 SHA256、解码、尺寸、Alpha 和水印像素区域。原始文件与带入成品 SHA256 保持一致，四份成品路径互异。
- [修复前 Edge 记录](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-v065/baseline-edge.json) · [候选 Edge 记录](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-v065/candidate-edge.json) · [逐图核对](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-v065/pixel-audit.json) · [候选构建日志](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-v065/candidate-build.log)

## BLOCKER

- 功能验收无阻断。当前聊天未提供 GPT‑6.1 Terra / xhigh 切换入口，执行模型配置无法按指定值确认。

## PROTECTION

- 暂存区为空。已有水印页页眉改动和项目日志内容保留。构建、浏览器验证与写入均使用隔离目录，正式部署、冻结和 Git 写操作均未执行。
- 工作区复查核对了 44 个其他已修改文件的哈希。执行期间，现有批量压缩状态文档与验收目录出现并行变更，已原样保留。Git 可枚举的基线条目无缺失。本轮文件差异检查通过。
