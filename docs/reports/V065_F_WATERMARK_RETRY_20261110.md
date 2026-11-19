# V0.6.5 F 线批量水印仅重试失败项验收

## STATUS

- `FINAL_STATUS=PASS`（隔离候选） · `FREEZE_STATUS=NOT_READY`
- `VERSION=0.6.5-dev` · `BRANCH=codex/image-processing-routing-v1` · `HEAD=b4fdde85dc036537382fb16252e1f1473c215e61`
- 前端构建 `V0.6.5-dev+b4fdde85dc03.unknown.20261110T002344714Z`。构建记录的工作区标记为 `unknown`，现场 Git 确认有未提交变更。Edge 同时运行本轮后端源码。

## FILES_MODIFIED

- `backend/batch_watermark_api.py`、`src/BatchWatermarkPage.jsx`
- `tests/batch_watermark/test_batch_watermark_api.py`、`tests/image_compression_ui/test_batch_watermark_ui.mjs`
- `docs/09_CODEX_CHANGELOG.md`、本报告

## IMPLEMENTED

- 基线真实重启后，原图副本和参数可读，图片水印没有持久化 Logo，页面也没有重试入口。
- 重试沿用原批次、条目和 Task ID，使用已登记的参数。先核验原图副本路径和 SHA256，图片水印同时核验持久化的原透明 PNG Logo。缺失、被替换或发布状态无法确认的条目逐项提示重新发起。
- 沿用逐张进度和成品原子防覆盖发布。批次重试版本阻止重复执行，旧状态回包无法提前结束当前重试。已有成功和取消项不进入重试队列。

## VALIDATION

- 先通过健康接口及实际路径核对隔离数据根、任务记录和水印输出目录。真实 Edge 使用 NTFS 写入拒绝触发两组单张失败，随后撤销权限探针。
- 文字批次初始为 1 成功、1 写入失败、1 取消。解除写入限制后，原失败项成功。同名成品各自保存，原成功 Result ID、路径和 SHA256 一致，原取消项未执行。页面双击仅提交一次，完成后重放请求返回同一结果。
- 图片批次重启后读取原图、原参数和 Logo。分别改变原图副本和 Logo 字节，页面逐项说明 SHA256 校验失败，两次均未生成成品。恢复字节后可重试，Edge 捕捉到仅原失败项处理中，活动期间并发重复提交返回 409。旧批次缺少可核验 Logo 时逐项提示重新发起。
- 两个批次各只新增一份 PNG，完整解码后与原参数复算输出的 SHA256 一致。已有两份成品的 Result ID、路径和 SHA256 保持一致，输入文件哈希一致。
- 35 项 Python、17 项 Node、Vite 隔离构建和差异检查通过。
- [基线重启记录](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-retry-v065/baseline-restart.json) · [写入故障与文字重试](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-retry-v065/candidate-created.json) · [重启后 Edge 验证](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-retry-v065/candidate-restart.json) · [逐项成品核对](D:/CodexHome/.codex/visualizations/2026/11/09/01a1c2b4-5518-72a0-9163-75fe27215cf0/watermark-retry-v065/output-audit.json)

## BLOCKER

- 功能验收无阻断。实际开发模型及推理强度 `NOT_VERIFIED`，指定配置为 GPT‑6.1 Terra / xhigh。

## PROTECTION

- 暂存区为空，复查 46 个范围外已改 tracked 文件的哈希一致。并行变化出现在批量压缩验收目录，本轮全部操作限于自身文件及隔离根目录。
- 隔离目录的写入拒绝权限已恢复。未执行 Git 写操作、正式部署或冻结。
