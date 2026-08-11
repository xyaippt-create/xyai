import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (name) => fs.readFileSync(path.join(root, name), "utf8");

test("颜色校正路由接入正式页面", () => {
  const routes = read("src/appRoutes.js");
  const app = read("src/App.jsx");
  assert.match(routes, /key:\s*"color-correction"[\s\S]*status:\s*FEATURE_STATUSES\.ENABLED[\s\S]*implementationType:\s*"existing"/);
  assert.match(app, /route\.key === "color-correction"[\s\S]*<ColorCorrectionPage/);
});

test("正式页面提供完整单图闭环且没有占位文案或参数墙", () => {
  const page = read("src/ColorCorrectionPage.jsx");
  for (const contract of [
    "color-file-input",
    "开始自动校正",
    "color-before-after",
    "结果报告",
    "color-open-output",
    "color-open-folder",
    "color-copy-path",
    "color-feedback-trigger",
    "查看高级处理信息",
    "处理结论",
    "主要问题",
    "本次处理",
    "保护与文件安全",
    "逐图策略",
    "模块顺序",
    "对比与通透",
    "色彩强度",
    "强色区域",
    "处理后复核",
    "输出编码",
    "局部层次",
    "白平衡判断",
    "人物/背景增益",
    "未检测到需要独立处理的人物区域",
  ]) assert.ok(page.includes(contract), `missing UI contract: ${contract}`);
  for (const forbidden of ["UI Alpha", "尚未接入真实处理能力", "不生成任务、文件或处理结果"])
    assert.ok(!page.includes(forbidden), `placeholder text leaked: ${forbidden}`);
  assert.doesNotMatch(page, /<dd>\{task(?:\?|\.)\.task_id\}<\/dd>/, "formal UI must not visibly expose the internal runtime task id");
  assert.ok(!page.includes("{task.operation_mode}"), "internal operation mode must remain in task data, not the visible report");
  assert.ok(!page.includes("色彩纯度"), "user-facing saturation wording must use 色彩强度");
  assert.ok(!page.includes("曝光滑杆") && !page.includes("饱和度滑杆"), "manual adjustment wall must not be introduced");
  const advanced = page.indexOf('<details className="hdde-color-advanced">');
  assert.ok(advanced > page.indexOf('aria-label="结果报告"'));
  for (const technicalMetric of ["整体亮度", "黑位 / 中间调 / 白位", "局部层次", "色彩强度", "暗部 / 高光占比"])
    assert.ok(page.indexOf(technicalMetric) > advanced, `${technicalMetric} must stay in advanced processing information`);
});

test("颜色校正支持多图选择、移除和一次创建批量任务", () => {
  const page = read("src/ColorCorrectionPage.jsx");
  const app = read("src/App.jsx");
  for (const contract of [
    "multiple",
    "selectedItems",
    "color-selection-count",
    "color-file-list",
    "color-remove-file",
    "removeSelectedItem",
    "/api/color-correction/batches",
    "source_tokens",
    "onOpenProcessing",
    "开始处理 ${selectedItems.length} 张图片",
  ]) assert.ok(page.includes(contract), `missing batch UI contract: ${contract}`);
  assert.match(app, /onOpenProcessing=\{\(batchId\) => navigateTo\(`\/processing\?batch=/);
  assert.ok(page.includes('eyebrow="单图与多图处理"'));
  assert.ok(page.includes("每张最大 50 MB"));
});

test("问题反馈预览显示真实上下文且附件保持用户主动选择", () => {
  const page = read("src/ColorCorrectionPage.jsx");
  const feedback = read("src/UnifiedFeedback.jsx");
  const css = read("src/index.css");
  for (const contract of [
    "unified-feedback-context",
    "系统已整理的辅助信息",
    "问题来源",
    "发生阶段",
    "当前状态",
    "运行环境",
    "诊断事实",
    "unified-feedback-attachments",
    "附件（可选）",
    "附件不会自动加入反馈包或上传",
    "不含原图、结果文件、Settings、完整日志",
  ]) assert.ok(feedback.includes(contract), `missing feedback context contract: ${contract}`);
  assert.match(page, /sourceFeature="color_correction"/);
  assert.match(feedback, /data-testid="unified-feedback-attachments"[\s\S]*type="file"[\s\S]*multiple/);
  assert.doesNotMatch(feedback, /formData\.append\([^)]*files|fetch\([^)]*attachments/);
  assert.doesNotMatch(feedback, /<dd>\{preview\.(?:task_id|result_id)\}<\/dd>/);
  for (const style of [".hdde-feedback-upload", ".hdde-feedback-context"])
    assert.ok(css.includes(style), `missing feedback UI style: ${style}`);
});

test("处理中心轮询批次并显示逐图状态、汇总和真实结果操作", () => {
  const dashboard = read("src/DashboardPage.jsx");
  for (const contract of [
    "/api/color-correction/batches",
    "colorBatchTaskToQueueItem",
    "color-batch-summary",
    "activeColorBatch.total_count",
    "activeColorBatch.completed_count",
    "activeColorBatch.failed_count",
    "activeColorBatch.pending_review_count",
    "activeColorBatch.confirmed_count",
    "activeColorBatch.progress",
    "单张失败不会中断其他图片",
    "/api/color-correction/open-output",
    "/api/color-correction/open-output-folder",
    'taskFamily !== "color_correction"',
  ]) assert.ok(dashboard.includes(contract), `missing processing-center batch contract: ${contract}`);
});

test("真实颜色校正结果支持前后对比、人工确认和返回原批次", () => {
  const routes = read("src/appRoutes.js");
  const app = read("src/App.jsx");
  const page = read("src/ColorCorrectionPage.jsx");
  const dashboard = read("src/DashboardPage.jsx");
  assert.match(routes, /key:\s*"color-correction-review"[\s\S]*path:\s*"\/color-correction\/result"[\s\S]*showInNavigation:\s*false/);
  assert.match(app, /route\.key === "color-correction-review"[\s\S]*reviewTaskId=\{reviewTaskId\}[\s\S]*reviewBatchId=\{reviewBatchId\}/);
  for (const contract of [
    "/api/color-correction/tasks/${encodeURIComponent(reviewTaskId)}",
    "/api/color-correction/tasks/${encodeURIComponent(task.task_id)}/review",
    "color-review-before-after",
    "拖动查看原图与成品",
    "标记为已确认",
    "恢复为待确认",
    "返回批次",
    "打开成品",
    "打开所在目录",
    "不代表自动视觉评分或软件判定质量通过",
  ]) assert.ok(page.includes(contract), `missing result-review contract: ${contract}`);
  assert.match(dashboard, /onNavigate\(`\/color-correction\/result\?task_id=\$\{encodeURIComponent\(item\.taskId\)\}\$\{batchQuery\}`\)/);
  assert.match(dashboard, /item\.taskFamily === "color_correction" \? "复核结果" : item\.taskFamily === "image_diagnosis" \? "查看诊断" : "查看详情"/);
});

test("颜色校正样式保持12px最低可见字号和HDDE品牌令牌", () => {
  const css = read("src/index.css");
  const start = css.indexOf("Stage 2 single-image automatic color correction");
  const end = css.indexOf("End Stage 2 single-image automatic color correction");
  const scoped = css.slice(start, end);
  assert.ok(scoped.includes("var(--brand-primary)"));
  assert.doesNotMatch(scoped, /font-size:\s*(?:[0-9]|1[01])px/);
});

test("处理后复核按真实状态映射四种收窄结论文案", () => {
  const page = read("src/ColorCorrectionPage.jsx");
  for (const contract of [
    "本次处理已完成必要的画面安全检查，未发现需要回退的明显风险。",
    "本次处理已完成可执行的安全检查；部分项目因画面条件不足未单独判断，建议查看前后对比。",
    "检测到潜在画质风险，系统已自动降低处理强度。",
    "为避免画质劣化，本次采用了更轻的处理结果。",
    'candidateLevel === "ORIGINAL"',
    "!review?.post_review_complete",
    "review?.convergence_actions",
    'item?.status === "LOW_CONFIDENCE"',
    'item?.status === "NOT_APPLICABLE"',
  ]) assert.ok(page.includes(contract), `missing post-review copy contract: ${contract}`);
  assert.ok(!page.includes("处理后复核未发现需要自动回退的技术风险。"), "legacy unconditional safety claim must be removed");
  assert.match(page, /postReviewSummary\(result\.analysis\?\.post_process_review\)/);
});
