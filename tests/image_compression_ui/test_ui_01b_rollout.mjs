import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (relativePath) => fs.readFileSync(path.join(ROOT, relativePath), "utf8");

const pages = {
  processing: read("src/DashboardPage.jsx"),
  diagnosis: read("src/ImageDiagnosisPage.jsx"),
  compression: read("src/CompressionPage.jsx"),
  color: read("src/ColorCorrectionPage.jsx"),
  retouch: read("src/LocalRetouchPage.jsx"),
  outputs: read("src/OutputCenterPage.jsx"),
  delivery: read("src/SmartDeliveryPage.jsx"),
  settings: read("src/SystemSettingsPage.jsx"),
};
const feedback = read("src/UnifiedFeedback.jsx");
const sharedUi = read("src/HddeUI.jsx");
const shell = read("src/AppShell.jsx");
const styles = read("src/index.css");

test("UI-01B rolls the shared page hierarchy through formal work areas", () => {
  for (const key of ["diagnosis", "compression", "color", "retouch", "outputs", "delivery", "settings"]) {
    assert.match(pages[key], /HddePageHeader/, `${key} must use the shared formal page header`);
  }
  assert.match(styles, /UI-01B — roll the precision-workspace language/);
  assert.match(styles, /\.hdde-detail-header,[\s\S]*\.hdde-compare-header,[\s\S]*\.hdde-report-header/);
});

test("UI-01B keeps one current-task hierarchy and one sequential preparation surface", () => {
  assert.match(pages.processing, /<h2 id="processing-queue-title">任务列表<\/h2>/);
  assert.doesNotMatch(pages.processing, /<p className="hdde-eyebrow">处理中心<\/p>/);
  assert.doesNotMatch(pages.processing, /正式目录 READY|正式目录 BLOCKED/);
  assert.match(styles, /\.hdde-processing-steps[\s\S]*gap: 0;[\s\S]*overflow: hidden;/);
});

test("UI-01B gives output center and retouch actionable restrained empty states", () => {
  assert.match(pages.outputs, /当前分类还没有正式成品/);
  assert.match(pages.outputs, /前往处理中心生成结果/);
  assert.match(pages.outputs, /onNavigate\?\.\("\/processing"\)/);
  assert.match(pages.retouch, /hdde-retouch-canvas-wrap \$\{session \? "has-image" : "is-empty"\}/);
  assert.match(styles, /\.hdde-retouch-canvas-wrap\.is-empty \.hdde-retouch-canvas[\s\S]*visibility: hidden/);
  assert.match(styles, /\.hdde-retouch-stage\.is-empty[\s\S]*var\(--surface-subtle\)/);
});

test("UI-01B translates historical output metadata into the formal product names", () => {
  assert.match(pages.outputs, /"4k": "4K高清画质增强"/);
  assert.match(pages.outputs, /processingType === "1080p"\) return "1080P标准增强 \/ 安全增强"/);
  assert.match(pages.outputs, /formalCategoryLabel\(category\)/);
  assert.doesNotMatch(pages.outputs, />\{category\.label\}</);
});

test("UI-01B removes duplicate settings facts and obsolete public wording", () => {
  assert.doesNotMatch(pages.settings, /hdde-settings-theme-summary|APPEARANCE|LOCAL DIRECTORIES|PLATFORM|UPDATES|ABOUT/);
  assert.equal((pages.settings.match(/<SettingsSection\n/g) || []).length, 3);
  const publicSources = Object.values(pages).join("\n")
    + read("src/TaskDetailPage.jsx")
    + read("src/ImageSliderComparePage.jsx")
    + read("src/QualityReportPage.jsx")
    + read("src/LaunchPage.jsx");
  assert.doesNotMatch(publicSources, /4K增强适配|1080P标准版|1080P安全增强版|当前为独立 Beta 功能|Beta Entry|LOCAL RETOUCH/);
  for (const label of ["4K高清增强", "1080P标准增强", "1080P安全增强", "4K高清画质增强"]) {
    assert.ok(read("src/appRoutes.js").includes(label) || publicSources.includes(label), `missing formal label: ${label}`);
  }
});

test("UI-01B closes diagnosis compression output delivery and feedback hierarchy", () => {
  assert.match(pages.diagnosis, /DIAGNOSIS_STEPS/);
  assert.match(pages.diagnosis, /导入图片.*诊断结论.*推荐动作.*进入处理/);
  assert.match(pages.diagnosis, /hdde-diagnosis-outcome-preview/);

  assert.doesNotMatch(pages.compression, /ImageProcessingPreflightPanel|阶段5预检|图片分析与处理建议|分析并推荐/);
  assert.match(pages.compression, /不确定如何处理？先进行图片诊断/);
  assert.match(pages.compression, /长图输出核对/);

  assert.match(pages.outputs, /hdde-output-next-step/);
  assert.ok(pages.outputs.indexOf("加入交付清单") < pages.outputs.indexOf("打开成品"));
  assert.match(pages.delivery, /交付副本明细/);
  assert.match(pages.delivery, /源成品未移动/);

  assert.match(feedback, /hdde-feedback-context/);
  assert.match(feedback, /hdde-feedback-upload/);
  assert.doesNotMatch(feedback, />取消<\/button>/);
  assert.match(feedback, /aria-label="关闭问题反馈"[^>]*>×<\/button>/);
});

test("UI-01B follow-up keeps diagnosis work areas balanced and retouch header compact", () => {
  assert.match(styles, /--hdde-diagnosis-workspace-height: 520px/);
  assert.match(styles, /\.hdde-diagnosis-layout\[data-state="idle"\][\s\S]*align-items: stretch/);
  assert.match(styles, /\.hdde-diagnosis-layout\[data-state="idle"\][\s\S]*\.hdde-diagnosis-run[\s\S]*margin-top: 16px/);
  assert.doesNotMatch(pages.retouch, /eyebrow="局部工作区"/);
  assert.match(styles, /\.hdde-retouch-page > \.hdde-page-header[\s\S]*margin-bottom: 4px;[\s\S]*padding: 0 0 12px/);
});

test("UI-01B uses one title hierarchy across formal pages and compatibility subpages", () => {
  for (const key of ["processing", "diagnosis", "compression", "color", "retouch", "outputs", "delivery", "settings"]) {
    assert.match(pages[key], /HddePageHeader/, `${key} must use the shared page title component`);
  }
  for (const token of [
    "--font-weight-page-title",
    "--line-height-page-title",
    "--line-height-page-description",
    "--page-title-description-gap",
    "--page-header-workspace-gap",
  ]) assert.ok(styles.includes(token), `missing title-system token: ${token}`);
  assert.match(styles, /Final cascade for the shared formal-page title hierarchy/);
  assert.match(styles, /\.hdde-page-header h1,[\s\S]*\.hdde-detail-heading h1,[\s\S]*\.hdde-compare-header h1,[\s\S]*\.hdde-report-heading h1/);
  assert.match(styles, /\.hdde-status-pill,[\s\S]*\.hdde-processing-readiness,[\s\S]*\.hdde-color-review-header-actions > span/);
  assert.match(styles, /\.hdde-section-header h2,[\s\S]*\.hdde-processing-section-heading h2,[\s\S]*\.hdde-settings-section__header h2/);
});

test("UI-01B uses one shared page frame and header rhythm across formal pages", () => {
  for (const key of ["processing", "diagnosis", "compression", "color", "retouch", "outputs", "delivery", "settings"]) {
    assert.match(pages[key], /hdde-page-frame/, `${key} must opt into the shared formal-page frame`);
  }
  assert.match(shell, /hdde-topbar-inner/);
  assert.match(styles, /--page-frame-content-max-width: 1360px/);
  assert.match(styles, /--page-frame-inline-gutter: 22px/);
  assert.match(styles, /--page-frame-top-spacing: 22px/);
  assert.match(styles, /\.hdde-app-shell \.hdde-topbar \{[\s\S]*padding-inline: 0/);
  assert.match(styles, /\.hdde-topbar-inner,[\s\S]*\.hdde-page-frame[\s\S]*padding-inline: var\(--page-frame-inline-gutter\)/);
  assert.match(styles, /\.hdde-page-stack > \.hdde-page-header[\s\S]*var\(--page-header-workspace-gap\)/);
  assert.doesNotMatch(styles, /hdde-work-page|work-page-inline-gutter/);
});

test("UI-01B keeps every formal page title on the same top baseline", () => {
  const pageHeaderSource = sharedUi.slice(
    sharedUi.indexOf("export function HddePageHeader"),
    sharedUi.indexOf("export function HddeStatusPill"),
  );
  assert.doesNotMatch(pageHeaderSource, /eyebrow|hdde-eyebrow/);
  assert.match(
    styles,
    /\.hdde-page-frame \.hdde-page-header \.hdde-page-header__title-row \{ margin-top: 0; \}/,
  );
});
