# V0.6.5 F 线批量水印逐张进度验收

## STATUS

- `FINAL_STATUS=PASS`（隔离候选） · `FREEZE_STATUS=NOT_READY`
- `VERSION=0.6.5-dev` · `BRANCH=codex/image-processing-routing-v1` · `HEAD=b4fdde85dc036537382fb16252e1f1473c215e61`
- 候选构建 `V0.6.5-dev+b4fdde85dc03.unknown.20261110T001148111Z`。构建记录的工作区标记为 `unknown`，现场 Git 确认有未提交改动。

## FILES_MODIFIED

- `src/BatchWatermarkPage.jsx`、`tests/image_compression_ui/test_batch_watermark_ui.mjs`、`docs/09_CODEX_CHANGELOG.md`、本报告。

## IMPLEMENTED

- 在上一轮已验收构建中，后台已经返回「完成／处理中／等待处理」，页面三行仍显示「处理中」，直到创建批次的 POST 返回。
- 运行期间单路轮询现有批次 GET，按客户端条目 ID 刷新状态、失败原因和成品名。进度条和汇总均根据当前行计算，终态包含取消项。查询中断保留最近的有效快照。终态关闭轮询，旧请求即使晚到也无法回写。
- 水印预览依赖输入身份和参数，逐行状态变化不会重新发起预览请求。处理、取消和历史记录读取沿用原接口。

## VALIDATION

- 真实 Microsoft Edge `157.0.4341.42` 加载隔离构建。混合批次的 POST 尚未返回时，已显示 1 成功、1 失败、1 处理中、3 等待，进度 33%。首张带入成品已有可读的磁盘成品，损坏 PNG 已显示实际失败原因。批次最终为 5 成功、1 失败。
- 浏览器探针拦截一次真实 GET 的交付，模拟一次查询失败。界面保留六条最近有效状态，之后恢复读取。另将真实中间态响应延迟到取消批次终态之后交付，页面维持 2 成功、2 取消、100%，轮询未重启。
- 取消时已有 1 张完成、1 张处理中和 2 张等待。已完成和正在处理的两张均有成品，两条等待记录取消且未生成成品。
- 核对 10 条输入、页面与后端记录。7 份 PNG 成品完整解码，尺寸与来源一致，原件 SHA256 保持一致，两张同名图片输出路径互异。基线服务生成的旧格式批次 `watermark_batch_36530695d38f4250` 仍能按旧链接打开，Result ID 与文件哈希一致。浏览器无控制台错误。
- 水印 Python 测试 34 项、前端 Node 测试 16 项、Vite 隔离构建和差异检查通过。
- [复现记录](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-progress-v065/baseline-edge.json) · [运行中截图](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-progress-v065/after-live.png) · [候选浏览器记录](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-progress-v065/candidate-edge.json) · [成品核对](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-progress-v065/artifact-audit.json)

## BLOCKER

- 功能验收无阻断。实际开发模型及推理强度 `NOT_VERIFIED`，指定配置为 GPT‑6.1 Terra / xhigh。

## PROTECTION

- 暂存区为空。上一轮水印候选和并行改动纳入保护基线。构建、Edge 及测试数据使用独立目录。本轮未执行 Git 写操作、正式部署或冻结。
- 复查时发现输出中心、样式、压缩校验及相关测试与产物有并行更新，均原样保留。本报告的 Edge 证据对应上述隔离构建，构建完成后写入的并行改动未打入候选。
