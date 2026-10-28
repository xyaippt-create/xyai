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
    "查看技术详情",
    "HddeResultHero",
    "colorResultConclusion",
    "本次变化",
    "安全保护",
    "nextAction",
    "建议复核",
    "已安全回退",
    "本次变化",
    "建议复核",
    "安全保护",
    "整体亮度",
    "色彩强度",
  ]) assert.ok(page.includes(contract), `missing UI contract: ${contract}`);
  for (const forbidden of ["UI Alpha", "尚未接入真实处理能力", "不生成任务、文件或处理结果"])
    assert.ok(!page.includes(forbidden), `placeholder text leaked: ${forbidden}`);
  assert.doesNotMatch(page, /<dd>\{task(?:\?|\.)\.task_id\}<\/dd>/, "formal UI must not visibly expose the internal runtime task id");
  assert.ok(!page.includes("{task.operation_mode}"), "internal operation mode must remain in task data, not the visible report");
  assert.ok(!page.includes("色彩纯度"), "user-facing saturation wording must use 色彩强度");
  assert.ok(!page.includes("曝光滑杆") && !page.includes("饱和度滑杆"), "manual adjustment wall must not be introduced");
  const advanced = page.indexOf('<HddeTechnicalDetails summary="查看技术详情"');
  assert.ok(advanced > page.indexOf('aria-label="结果报告"'));
  for (const technicalMetric of ["整体亮度", "黑位 / 中间调 / 白位", "局部层次", "色彩强度", "暗部 / 高光占比"])
    assert.ok(page.indexOf(technicalMetric) > advanced, `${technicalMetric} must stay in advanced processing information`);
});

test("保护状态统一显示保留原图且不暴露内部门禁术语", () => {
  const page = read("src/ColorCorrectionPage.jsx");
  const detail = read("src/TaskDetailPage.jsx");
  const dashboard = read("src/DashboardPage.jsx");
  for (const source of [page, detail, dashboard]) {
    assert.match(source, /本次未进行自动校正/);
    assert.match(source, /检测到自动调整可能影响原图质量，已保留原图。/);
    assert.doesNotMatch(source, /保护门禁阻止生成可审核结果|可审核结果/);
  }
  assert.match(page, /colorFailureMessage\(payload\.data\.task, payload\.data\.result\)/);
  assert.match(dashboard, /protectionBlocked[\s\S]*本次未进行自动校正/);
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
    "默认不包含图片",
    "附加当前结果图",
    "附加当前原图",
    "图片仅按本次明确勾选授权加入",
    "不含 Settings、完整日志或未经脱敏绝对路径",
  ]) assert.ok(feedback.includes(contract), `missing feedback context contract: ${contract}`);
  const shell = read("src/AppShell.jsx");
  assert.match(shell, /"color-correction": "color_correction"/);
  assert.doesNotMatch(page, /UnifiedFeedback|color-feedback-trigger/);
  assert.match(feedback, /data-testid="unified-feedback-attachments"[\s\S]*type="file"[\s\S]*multiple/);
  assert.doesNotMatch(feedback, /formData\.append\([^)]*files|fetch\([^)]*attachments/);
  assert.doesNotMatch(feedback, /<dd>\{preview\.(?:task_id|result_id)\}<\/dd>/);
  for (const style of [".hdde-feedback-upload", ".hdde-feedback-context"])
    assert.ok(css.includes(style), `missing feedback UI style: ${style}`);
});

test("结果页先确认颜色候选再按当前Result Identity交付和反馈", () => {
  const taskDetail = read("src/TaskDetailPage.jsx");
  const app = read("src/App.jsx");
  const shell = read("src/AppShell.jsx");
  assert.match(
    taskDetail,
    /isColorCorrection[\s\S]*\/api\/color-correction\/tasks\/\$\{encodeURIComponent\(taskId\)\}\/review[\s\S]*\/api\/smart-delivery\/preflight/,
  );
  assert.match(app, /feedbackTarget=\{currentResultFeedbackTarget\}/);
  assert.match(app, /feedbackDisabled=\{TASK_ROUTES\.has\(route\?\.key\) && !currentResultFeedbackTarget\}/);
  for (const field of ["feature_key", "module_id", "operation_id", "trace_id", "task_id", "result_id", "delivery_id"])
    assert.ok(app.includes(field), `current Result feedback target missing ${field}`);
  assert.match(shell, /feedbackTarget=\{feedbackTarget\}/);
  assert.match(shell, /disabled=\{feedbackDisabled\}/);
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

test("历史颜色校正结果入口收敛到统一处理结果，原复核数据合同保持可读", () => {
  const routes = read("src/appRoutes.js");
  const app = read("src/App.jsx");
  const page = read("src/ColorCorrectionPage.jsx");
  const dashboard = read("src/DashboardPage.jsx");
  assert.match(routes, /key:\s*"color-correction-review"[\s\S]*path:\s*"\/color-correction\/result"[\s\S]*showInNavigation:\s*false/);
  assert.match(app, /"color-correction-review": "\/task-detail"/);
  assert.match(app, /route\.key === "color-correction-review"[\s\S]*正在进入处理结果/);
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
  assert.match(dashboard, /onNavigate\(`\/task-detail\?task_id=\$\{encodeURIComponent\(item\.taskId\)\}`\)/);
  assert.match(dashboard, /item\.taskFamily === "color_correction" \? "复核结果" : isRetiredImageDiagnosisTask\(item\) \? "已下线" : "查看详情"/);
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

test("historical color previews fail into an explicit UI fallback", () => {
  const page = read("src/ColorCorrectionPage.jsx");
  const css = read("src/index.css");
  assert.ok(page.includes('data-testid="color-review-preview-fallback"'));
  assert.ok(page.includes("setPreviewUnavailable(true)"));
  assert.ok(css.includes(".hdde-color-preview-fallback"));
});

test("颜色校正同级模式按钮具有完全一致的局部尺寸合同", () => {
  const css = read("src/ColorCorrectionReference.css");
  assert.match(css, /\.hdde-reference-tabs\s*\{[\s\S]*?align-items:\s*center;/);
  assert.match(css, /\.hdde-reference-tabs button\s*\{[\s\S]*?width:\s*112px;[\s\S]*?height:\s*44px;[\s\S]*?margin:\s*0;[\s\S]*?padding:\s*9px 15px;/);
});
