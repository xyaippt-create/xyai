import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  AlternativeSuggestions,
  ERROR_CODE_META,
  PREFLIGHT_ACTION_META,
  PREFLIGHT_PURPOSES,
  PREFLIGHT_STATUS_META,
  REASON_CODE_META,
  buildPreflightRequestPlan,
  buildAlternativeDisplayItems,
  buildRecommendationPrefill,
  canApplyRecommendation,
  errorCodeMeta,
  isCurrentPreflightResponse,
  preflightActionMeta,
  preflightStatusMeta,
  reasonCodeMeta,
} from "../../src/imageProcessingPreflight.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const panel = fs.readFileSync(path.join(root, "src", "ImageProcessingPreflightPanel.jsx"), "utf8");
const page = fs.readFileSync(path.join(root, "src", "CompressionPage.jsx"), "utf8");
const dashboard = fs.readFileSync(path.join(root, "src", "DashboardPage.jsx"), "utf8");
const settings = fs.readFileSync(path.join(root, "src", "SystemSettingsPage.jsx"), "utf8");
const shell = fs.readFileSync(path.join(root, "src", "AppShell.jsx"), "utf8");

const safeToken = "safe-source-token_123";

function renderAlternatives(alternatives) {
  return renderToStaticMarkup(React.createElement(AlternativeSuggestions, { alternatives }));
}

const longImageAlternatives = [{
  action: "RESIZE_REDUCTION",
  targets: { resize_strategy: "FIXED_SHORT_SIDE", target_short_side: 750 },
  required_targets: ["max_bytes"],
  description: "用于长图安全回放",
}];

function plan(purpose, targets = {}) {
  return buildPreflightRequestPlan({ sourceToken: safeToken, purpose, targets });
}

function result(action, overrides = {}) {
  return { preflight_status: "READY", recommended_action: action, executable: true, recommended_parameters: {}, ...overrides };
}

function readProcessingOutputDirectoryResolver() {
  const start = dashboard.indexOf("function resolveProcessingOutputDirectory(");
  const end = dashboard.indexOf("\nconst JPG95_REVIEW_OPTIONS", start);
  assert.ok(start >= 0 && end > start, "processing output directory resolver must remain independently testable");
  const declaration = dashboard.slice(start, end);
  return Function(`const PROCESSING_MODE_SAFE_BETA = "safe_1080p_beta"; const PROCESSING_MODE_FOUR_K = "4k_v1"; ${declaration}; return resolveProcessingOutputDirectory;`)();
}

const resolveProcessingOutputDirectory = readProcessingOutputDirectoryResolver();

test("处理中心目录只由workdir响应提供且health不能覆盖", () => {
  assert.doesNotMatch(dashboard, /\/api\/health/);
  assert.match(dashboard, /\/api\/app\/workdir/);
  assert.match(dashboard, /setWorkdirInfo\(data\)/);
  assert.doesNotMatch(dashboard, /default_output_dir|setDefaultOutputDir/);
});

test("health与workdir两种返回顺序都保持标准和Beta目录映射", () => {
  const healthResponse = { default_output_dir: "D:\\internal\\tmp\\runtime_data\\output" };
  const workdirResponse = {
    output_dir: "D:\\影界文件\\输出\\1080P标准增强",
    beta_output_dir: "D:\\影界文件\\输出\\1080P安全增强",
  };
  const resolveAfter = (responses) => {
    let workdirInfo = null;
    for (const response of responses) {
      if (response.endpoint === "workdir") workdirInfo = response.data;
    }
    return {
      standard: resolveProcessingOutputDirectory(workdirInfo, "standard"),
      beta: resolveProcessingOutputDirectory(workdirInfo, "safe_1080p_beta"),
    };
  };
  const expected = {
    standard: workdirResponse.output_dir,
    beta: workdirResponse.beta_output_dir,
  };
  assert.deepEqual(resolveAfter([{ endpoint: "health", data: healthResponse }, { endpoint: "workdir", data: workdirResponse }]), expected);
  assert.deepEqual(resolveAfter([{ endpoint: "workdir", data: workdirResponse }, { endpoint: "health", data: healthResponse }]), expected);
});

test("标准和Beta目录使用明确模式枚举且Beta缺失时只回退标准目录", () => {
  assert.match(dashboard, /const PROCESSING_MODE_STANDARD = "standard"/);
  assert.match(dashboard, /const PROCESSING_MODE_SAFE_BETA = "safe_1080p_beta"/);
  assert.equal(resolveProcessingOutputDirectory({ output_dir: "standard", beta_output_dir: "beta" }, "standard"), "standard");
  assert.equal(resolveProcessingOutputDirectory({ output_dir: "standard", beta_output_dir: "beta" }, "safe_1080p_beta"), "beta");
  assert.equal(resolveProcessingOutputDirectory({ output_dir: "standard" }, "safe_1080p_beta"), "standard");
});

test("图片压缩输出设置不并入处理中心目录状态", () => {
  assert.doesNotMatch(dashboard, /\/api\/image-compression\/output-settings/);
  assert.match(page, /\/api\/image-compression\/output-settings/);
});

test("四种purpose保持合同枚举和中文标签", () => {
  assert.deepEqual(PREFLIGHT_PURPOSES.map((item) => item.value), ["REDUCE_FILE_SIZE", "REDUCE_DIMENSIONS", "MEET_UPLOAD_LIMITS", "IMPROVE_LOW_QUALITY"]);
  assert.deepEqual(PREFLIGHT_PURPOSES.map((item) => item.label), ["减小文件体积", "缩小图片尺寸", "满足上传限制", "改善低清质量"]);
  assert.equal(PREFLIGHT_PURPOSES.length, 4);
});

test("不同purpose只生成合同允许的目标字段", () => {
  assert.deepEqual(plan("REDUCE_FILE_SIZE", { maxSizeKb: "256" }).request.targets, { max_bytes: 262144 });
  assert.deepEqual(plan("REDUCE_DIMENSIONS", { resizeStrategy: "FIXED_SHORT_SIDE", resizeValue: "900" }).request.targets, { resize_strategy: "FIXED_SHORT_SIDE", target_short_side: 900 });
  assert.deepEqual(plan("MEET_UPLOAD_LIMITS", { maxWidth: "1200", maxHeight: "", maxSizeKb: "" }).request.targets, { max_width: 1200 });
  assert.deepEqual(plan("IMPROVE_LOW_QUALITY").request.targets, {});
});

test("四种尺寸策略转换正确且一次只提交一种策略", () => {
  const cases = [
    ["FIXED_SHORT_SIDE", "750", "target_short_side", 750],
    ["SCALE_RATIO", "75", "scale_ratio", 0.75],
    ["FIXED_WIDTH", "1000", "target_width", 1000],
    ["FIXED_HEIGHT", "800", "target_height", 800],
  ];
  for (const [strategy, value, field, expected] of cases) {
    const targets = plan("REDUCE_DIMENSIONS", { resizeStrategy: strategy, resizeValue: value }).request.targets;
    assert.equal(targets.resize_strategy, strategy);
    assert.equal(targets[field], expected);
    assert.equal(Object.keys(targets).length, 2);
  }
});

test("参数缺失和非法值时不生成请求", () => {
  for (const candidate of [
    buildPreflightRequestPlan({ sourceToken: "", purpose: "REDUCE_FILE_SIZE", targets: {} }),
    buildPreflightRequestPlan({ sourceToken: safeToken, purpose: "", targets: {} }),
    plan("REDUCE_DIMENSIONS", { resizeStrategy: "FIXED_WIDTH", resizeValue: "" }),
    plan("REDUCE_DIMENSIONS", { resizeStrategy: "FIXED_WIDTH", resizeValue: "-1" }),
    plan("REDUCE_DIMENSIONS", { resizeStrategy: "SCALE_RATIO", resizeValue: "100" }),
    plan("MEET_UPLOAD_LIMITS", { maxWidth: "", maxHeight: "", maxSizeKb: "" }),
  ]) {
    assert.equal(candidate.valid, false);
    assert.equal(candidate.request, null);
  }
});

test("合法请求只包含安全source token和固定四字段", () => {
  const request = plan("REDUCE_FILE_SIZE").request;
  assert.deepEqual(Object.keys(request).sort(), ["file_token", "purpose", "requested_action", "targets"]);
  assert.equal(request.file_token, safeToken);
  assert.equal(request.requested_action, null);
  assert.doesNotMatch(JSON.stringify(request), /[A-Za-z]:[\\/]|file:\/\//);
});

test("JPEG缺少最大体积仍允许调用正式预检而不猜测目标", () => {
  const requestPlan = plan("REDUCE_FILE_SIZE");
  assert.equal(requestPlan.valid, true);
  assert.deepEqual(requestPlan.request.targets, {});
});

test("六种status集中映射且未知状态安全失败", () => {
  assert.deepEqual(Object.keys(PREFLIGHT_STATUS_META), ["READY", "READY_WITH_WARNING", "NO_PROCESSING_NEEDED", "UNSUPPORTED_MODE", "BLOCKED_UNSAFE", "ROUTE_TO_ENHANCEMENT"]);
  for (const value of Object.values(PREFLIGHT_STATUS_META)) assert.ok(value.label && value.tone);
  assert.equal(preflightStatusMeta("UNKNOWN_STATUS").unknown, true);
  assert.equal(preflightStatusMeta("UNKNOWN_STATUS").tone, "danger");
});

test("六种action集中映射且未知动作不可执行", () => {
  assert.deepEqual(Object.keys(PREFLIGHT_ACTION_META), ["NO_PROCESSING", "LOSSLESS_COMPRESSION", "RESIZE_REDUCTION", "UPLOAD_ADAPTATION", "FUTURE_ENHANCEMENT", "UNSUPPORTED"]);
  assert.equal(preflightActionMeta("UNKNOWN_ACTION").executable, false);
  assert.equal(preflightActionMeta("UNKNOWN_ACTION").unknown, true);
});

test("reason code 24/24都有完整可操作中文元数据", () => {
  assert.equal(Object.keys(REASON_CODE_META).length, 24);
  for (const meta of Object.values(REASON_CODE_META)) {
    assert.equal(typeof meta.title, "string");
    assert.equal(typeof meta.description, "string");
    assert.ok(["info", "warning", "danger"].includes(meta.severity));
    assert.equal(typeof meta.requiresAction, "boolean");
    assert.equal(typeof meta.suggestedAction, "string");
  }
});

test("error code 10/10都有重试、重传、文件检查和系统异常标记", () => {
  assert.equal(Object.keys(ERROR_CODE_META).length, 10);
  for (const meta of Object.values(ERROR_CODE_META)) {
    assert.equal(typeof meta.message, "string");
    assert.equal(typeof meta.canRetryParameters, "boolean");
    assert.equal(typeof meta.requiresReupload, "boolean");
    assert.equal(typeof meta.requiresFileCheck, "boolean");
    assert.equal(typeof meta.systemError, "boolean");
  }
});

test("未知reason和error使用安全fallback且不会误判为可执行", () => {
  assert.equal(reasonCodeMeta("NEW_REASON").unknown, true);
  assert.equal(reasonCodeMeta("NEW_REASON").severity, "danger");
  assert.equal(errorCodeMeta("NEW_ERROR", 500).unknown, true);
  assert.equal(errorCodeMeta("NEW_ERROR", 500).systemError, true);
  assert.equal(canApplyRecommendation(result("NEW_ACTION")), false);
});

test("HTTP 400、404、422和500错误语义分离", () => {
  assert.equal(errorCodeMeta("INVALID_TARGET_VALUE", 400).canRetryParameters, true);
  assert.equal(errorCodeMeta("TOKEN_NOT_FOUND_OR_EXPIRED", 404).requiresReupload, true);
  assert.equal(errorCodeMeta("IMAGE_DECODE_FAILED", 422).requiresFileCheck, true);
  assert.equal(errorCodeMeta("UNKNOWN", 500).systemError, true);
});

test("executable false、NO_PROCESSING、FUTURE和UNSUPPORTED均无预填入口", () => {
  for (const candidate of [
    result("LOSSLESS_COMPRESSION", { executable: false }),
    result("NO_PROCESSING", { executable: false, preflight_status: "NO_PROCESSING_NEEDED" }),
    result("FUTURE_ENHANCEMENT", { executable: false, preflight_status: "ROUTE_TO_ENHANCEMENT" }),
    result("UNSUPPORTED", { executable: false, preflight_status: "UNSUPPORTED_MODE" }),
  ]) {
    assert.equal(canApplyRecommendation(candidate), false);
    assert.equal(buildRecommendationPrefill(candidate), null);
  }
});

test("三种可执行推荐只转换为阶段4预填参数", () => {
  assert.deepEqual(buildRecommendationPrefill(result("LOSSLESS_COMPRESSION")), { mode: "LOSSLESS_COMPRESSION" });
  assert.deepEqual(buildRecommendationPrefill(result("RESIZE_REDUCTION", { recommended_parameters: { resize_strategy: "FIXED_SHORT_SIDE", target_short_side: 900 } })), { mode: "RESIZE_REDUCTION", resizeStrategy: "short_side", resizeValue: "900" });
  assert.deepEqual(buildRecommendationPrefill(result("UPLOAD_ADAPTATION", { recommended_parameters: { max_width: 1200, max_bytes: 524288 } })), { mode: "UPLOAD_ADAPTATION", uploadLimits: { maxWidth: "1200", maxHeight: "", maxSize: "512", sizeUnit: "KB" } });
});

test("旧响应序号不能覆盖新请求", () => {
  assert.equal(isCurrentPreflightResponse(3, 3), true);
  assert.equal(isCurrentPreflightResponse(2, 3), false);
  assert.match(panel, /new AbortController\(\)/);
  assert.match(panel, /controllerRef\.current\?\.abort\(\)/);
  assert.match(panel, /isCurrentPreflightResponse\(sequence, sequenceRef\.current\)/);
});

test("更换图片、修改purpose和修改目标都会使旧推荐失效", () => {
  assert.match(panel, /\[fileInfo\?\.source_token\]/);
  assert.match(panel, /图片已更换，原推荐结果已失效/);
  assert.match(panel, /处理目的已修改，原推荐结果已失效/);
  assert.match(panel, /目标参数已修改，原推荐结果已失效/);
  assert.match(panel, /status: "STALE"/);
});

test("正式API只在显式按钮调用且请求支持取消", () => {
  assert.match(panel, /request\("\/api\/image-processing\/preflight"/);
  assert.match(panel, /data-testid="preflight-analyze"/);
  assert.match(panel, /onClick=\{analyze\}/);
  assert.match(panel, /signal: controller\.signal/);
  const effects = [...panel.matchAll(/useEffect\(\(\) => \{([\s\S]*?)\n  \}, \[[^\]]*\]\);/g)]
    .map((match) => match[1]);
  assert.equal(effects.length, 1);
  assert.doesNotMatch(effects[0], /request\("\/api\/image-processing\/preflight"/);
});

test("图片压缩正式页面不再接入重复诊断与推荐面板", () => {
  assert.doesNotMatch(page, /ImageProcessingPreflightPanel|applyPreflightRecommendation|buildRecommendationPrefill/);
  assert.doesNotMatch(page, /阶段5预检|图片分析与处理建议|分析并推荐/);
  assert.match(page, /href="\/image-diagnosis"/);
});

test("图片压缩执行按钮和运行函数保持独立", () => {
  assert.match(page, /const runCompression = async \(\) =>/);
  assert.match(page, /data-testid="compression-run" onClick=\{runCompression\}/);
  assert.match(page, /data-testid="compression-reprocess" onClick=\{runCompression\}/);
});

test("画像展示覆盖合同用户字段且不渲染原始JSON", () => {
  for (const field of ["format", "mime_type", "width", "height", "short_side", "long_side", "aspect_ratio", "orientation", "size_bytes", "has_alpha", "is_animated", "frame_count", "is_long_image", "is_ultra_wide", "resolution_bucket", "processing_eligibility"]) {
    assert.match(panel, new RegExp(`profile\\.${field}`));
  }
  assert.doesNotMatch(panel, /JSON\.stringify\(result|<pre>/);
});

test("长图、动画多帧、Alpha和像素层级有明确非画质文案", () => {
  assert.match(panel, /长图/);
  assert.match(panel, /动画 \/ 多帧/);
  assert.match(panel, /透明通道/);
  assert.match(panel, /像素层级/);
  assert.doesNotMatch(panel, /2K观感|4K观感|画质等级/);
});

test("16类前端状态由基础状态、六种结果和四类错误共同覆盖", () => {
  for (const value of ["请先上传图片", "请选择本次真实处理目的", "PARAMETERS_INCOMPLETE", "参数已就绪", "LOADING", "SUCCESS", "STALE", "ERROR"]) {
    assert.match(panel + fs.readFileSync(path.join(root, "src", "imageProcessingPreflight.js"), "utf8"), new RegExp(value));
  }
  for (const status of Object.keys(PREFLIGHT_STATUS_META)) assert.ok(panel.includes("result.preflight_status") && PREFLIGHT_STATUS_META[status]);
});

test("目录异常时系统设置和处理中心遵循正式目录阻断合同", () => {
  assert.doesNotMatch(settings, /label="配置默认输出目录"/);
  assert.doesNotMatch(settings, /D:\\Codex\\04_Visual-Master-Pro/);
  assert.doesNotMatch(settings, /当前使用临时目录|project_tmp|runtime_fallback/);
  assert.match(settings, /workdir\.directory_ready === false/);
  assert.match(settings, /选择新目录/);
  assert.match(dashboard, /const blockedFormalPath = workdirInfo\?\.app_data_root \|\| workdirInfo\?\.failed_path \|\| "";/);
  assert.match(dashboard, /const blockedFormalReason = workdirInfo\?\.failure_reason \|\| directoryMessage;/);
  assert.match(dashboard, /disabled=\{!canStartExecution\}/);
  assert.match(dashboard, /href="\/settings"/);
});

test("主题切换和左侧导航保持原接线", () => {
  assert.match(shell, /APP_ROUTES\.filter\(\(item\) => item\.showInNavigation !== false\)/);
  assert.doesNotMatch(shell, /FeatureStatusBadge/);
  for (const mode of ["system", "dark", "light"]) assert.match(shell, new RegExp(`value: "${mode}"`));
});

test("补充01：替代动作以中文真实渲染", () => {
  assert.match(renderAlternatives(longImageAlternatives), /图片尺寸缩小/);
});

test("补充02：targets真实渲染为建议参数区", () => {
  assert.match(renderAlternatives(longImageAlternatives), /data-testid="alternative-suggested-parameters"/);
});

test("补充03：长图安全替代短边750完整渲染", () => {
  assert.match(renderAlternatives(longImageAlternatives), /短边：750像素/);
});

test("补充04：参数字段使用中文标签", () => {
  const html = renderAlternatives([{ action: "UPLOAD_ADAPTATION", targets: { max_width: 1200 } }]);
  assert.match(html, /最大宽度：1200像素/);
  assert.doesNotMatch(html, /max_width/);
});

test("补充05：像素参数带明确单位", () => {
  assert.match(renderAlternatives([{ action: "RESIZE_REDUCTION", targets: { target_height: 1200 } }]), /目标高度：1200像素/);
});

test("补充06：required_targets真实渲染为仍需填写区", () => {
  const html = renderAlternatives([{ action: "UPLOAD_ADAPTATION", required_targets: ["max_bytes"] }]);
  assert.match(html, /data-testid="alternative-required-parameters"/);
  assert.match(html, /仍需填写/);
  assert.match(html, /最大文件体积/);
});

test("补充07：targets与required_targets分区且语义不同", () => {
  const html = renderAlternatives(longImageAlternatives);
  assert.match(html, /建议参数[\s\S]*短边：750像素/);
  assert.match(html, /仍需填写[\s\S]*最大文件体积/);
});

test("补充08：空targets不渲染建议参数空壳", () => {
  assert.doesNotMatch(renderAlternatives([{ action: "UPLOAD_ADAPTATION", targets: {} }]), /alternative-suggested-parameters/);
});

test("补充09：空required_targets不渲染仍需填写空壳", () => {
  assert.doesNotMatch(renderAlternatives([{ action: "UPLOAD_ADAPTATION", required_targets: [] }]), /alternative-required-parameters/);
});

test("补充10：替代方案不渲染原始JSON", () => {
  const html = renderAlternatives(longImageAlternatives);
  assert.doesNotMatch(html, /\{"|"action"|"targets"/);
});

test("补充11：复杂未知值不出现object字符串", () => {
  assert.doesNotMatch(renderAlternatives([{ action: "UPLOAD_ADAPTATION", targets: { future_field: { nested: true } } }]), /\[object Object\]/);
});

test("补充12：undefined值被安全隐藏", () => {
  assert.doesNotMatch(renderAlternatives([{ action: "UPLOAD_ADAPTATION", targets: { max_width: undefined } }]), /undefined/);
});

test("补充13：null值被安全隐藏", () => {
  assert.doesNotMatch(renderAlternatives([{ action: "UPLOAD_ADAPTATION", targets: { max_width: null }, required_targets: null }]), /null/);
});

test("补充14：未知字段使用安全fallback且不崩溃", () => {
  const html = renderAlternatives([{ action: "FUTURE_ACTION", targets: { future_field: { nested: true } } }]);
  assert.match(html, /未知推荐动作/);
  assert.match(html, /其他参数（future field）/);
  assert.match(html, /复杂参数，请检查系统版本/);
});

test("补充15：空替代数组清除旧替代方案输出", () => {
  assert.equal(renderAlternatives([]), "");
  assert.deepEqual(buildAlternativeDisplayItems(null), []);
});

test("补充16：替代方案组件不触发自动处理", () => {
  const html = renderAlternatives(longImageAlternatives);
  assert.doesNotMatch(html, /compression-run|image-compression\/run|自动处理/);
});

test("补充17：替代方案组件不创建任务", () => {
  assert.doesNotMatch(renderAlternatives(longImageAlternatives), /task_id|创建任务|\/api\/tasks/);
});

test("补充18：替代方案组件不触发下载", () => {
  assert.doesNotMatch(renderAlternatives(longImageAlternatives), /download|下载|final_output_url/);
});

test("补充19：活动reason映射仍为24项", () => {
  assert.equal(Object.keys(REASON_CODE_META).length, 24);
});

test("补充20：活动error映射仍为10项", () => {
  assert.equal(Object.keys(ERROR_CODE_META).length, 10);
});
