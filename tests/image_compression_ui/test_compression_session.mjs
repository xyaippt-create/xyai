import assert from "node:assert/strict";
import test from "node:test";

import {
  FILE_SELECTION_STATES,
  TOKEN_SESSION_ERROR_CODE,
  TOKEN_SESSION_ERROR_MESSAGE,
  applyOutputSelection,
  buildCompressionRunPayload,
  captureFileFromChangeEvent,
  effectiveOutputRoot,
  feedbackPackageDownloadHref,
  feedbackPackageExpired,
  feedbackPackageUiState,
  functionOutputDirectory,
  intakeSuccessPatch,
  isTokenSessionError,
  newFileSessionPatch,
  normalizeOutputSettings,
  attachFeedbackPackage,
  normalizeFeedbackPackage,
  performFileIntake,
  resetImageSessionPatch,
  restoreBuiltInOutput,
  serverSessionChanged,
} from "../../src/compressionSession.js";

const file = (name) => ({ name, size: 321, type: "image/png", lastModified: 123 });
const intakeData = (token, name = "fixture.png") => ({
  source_token: token,
  display_name: name,
  format: "PNG",
  width: 120,
  height: 80,
  size_bytes: 321,
  has_alpha: true,
  source_sha256: "a".repeat(64),
  safe_preview_url: `/api/image-compression/preview/${token}`,
  expires_at: "2026-07-16T00:00:00+00:00",
});

class FakeFormData {
  constructor() { this.entries = []; }
  append(name, value) { this.entries.push([name, value]); }
}

async function runIntake(selectedFile, data = intakeData("token-1")) {
  const transitions = [];
  let requestCall = null;
  const response = await performFileIntake(selectedFile, {
    createFormData: () => new FakeFormData(),
    request: async (path, options) => {
      requestCall = { path, options };
      return { success: true, data };
    },
    onTransition: (state, payload) => transitions.push({ state, payload }),
  });
  return { response, transitions, requestCall };
}

test("01 file change事件捕获唯一File", () => {
  const selected = file("first.png");
  assert.equal(captureFileFromChangeEvent({ currentTarget: { files: [selected] } }), selected);
  assert.equal(captureFileFromChangeEvent({ currentTarget: { files: [] } }), null);
});

test("02 异步intake期间File对象不丢失", async () => {
  const selected = file("captured.png");
  const { response } = await runIntake(selected);
  assert.equal(response.form.entries[0][1], selected);
});

test("03 multipart字段名严格为file", async () => {
  const { response, requestCall } = await runIntake(file("multipart.png"));
  assert.equal(requestCall.path, "/api/image-compression/intake");
  assert.equal(requestCall.options.method, "POST");
  assert.deepEqual(response.form.entries.map(([name]) => name), ["file"]);
});

test("04 intake 200按序进入FILE_READY", async () => {
  const { transitions } = await runIntake(file("ready.png"));
  assert.deepEqual(transitions.map(({ state }) => state), [
    FILE_SELECTION_STATES.FILE_SELECTING,
    FILE_SELECTION_STATES.INTAKE_PENDING,
    FILE_SELECTION_STATES.FILE_READY,
  ]);
});

test("05 intake 200保留安全预览", async () => {
  const { response } = await runIntake(file("preview.png"), intakeData("preview-token"));
  assert.equal(response.data.safe_preview_url, "/api/image-compression/preview/preview-token");
});

test("06 token 404统一清理图片会话", () => {
  const reason = { code: TOKEN_SESSION_ERROR_CODE, httpStatus: 404 };
  assert.equal(isTokenSessionError(reason), true);
  const reset = resetImageSessionPatch(TOKEN_SESSION_ERROR_MESSAGE);
  assert.equal(reset.fileInfo, null);
  assert.equal(reset.resultData, null);
  assert.equal(reset.reviewNote, "");
  assert.equal(reset.state, FILE_SELECTION_STATES.ERROR);
});

test("07 token失效只保留一条明确错误", () => {
  const reset = resetImageSessionPatch(TOKEN_SESSION_ERROR_MESSAGE);
  assert.equal(reset.error, TOKEN_SESSION_ERROR_MESSAGE);
  assert.equal(Object.values(reset).filter((value) => value === TOKEN_SESSION_ERROR_MESSAGE).length, 1);
});

test("08 重新选择图片清除旧错误", () => {
  const next = newFileSessionPatch(file("retry.png"));
  assert.equal(next.error, "");
  assert.equal(next.state, FILE_SELECTION_STATES.FILE_SELECTING);
});

test("09 连续选择两张图片使用新token", () => {
  const first = intakeSuccessPatch(intakeData("token-a", "a.png"), { name: "a.png" });
  const second = intakeSuccessPatch(intakeData("token-b", "b.png"), { name: "b.png" });
  assert.notEqual(first.fileInfo.source_token, second.fileInfo.source_token);
  assert.equal(second.fileInfo.display_name, "b.png");
});

test("10 更换图片清理旧task和result", () => {
  const previous = { resultData: { result: { task_id: "old-task" } }, error: "old" };
  const next = { ...previous, ...newFileSessionPatch(file("replacement.png")) };
  assert.equal(next.resultData, null);
  assert.equal(next.error, "");
});

test("11 页面初始状态无红色错误", () => {
  const initial = resetImageSessionPatch();
  assert.equal(initial.state, FILE_SELECTION_STATES.IDLE);
  assert.equal(initial.error, "");
});

test("12 服务会话变化可原子重置且刷新无矛盾状态", () => {
  assert.equal(serverSessionChanged("server-a", "server-b"), true);
  const reset = resetImageSessionPatch(TOKEN_SESSION_ERROR_MESSAGE);
  assert.equal(reset.fileInfo, null);
  assert.equal(reset.state, FILE_SELECTION_STATES.ERROR);
  assert.notEqual(reset.error, "请先选择 PNG、JPG 或 JPEG 图片。");
});

const outputSettings = normalizeOutputSettings({
  built_in_default_root: "D:\\影界文件\\输出\\图片压缩",
  saved_default_root: "D:\\长期默认",
  output_root_writable: true,
});

test("13 当前任务输出目录覆盖长期默认", () => {
  const applied = applyOutputSelection(outputSettings, "", "D:\\本次任务", "current_task");
  assert.equal(effectiveOutputRoot(applied.settings, applied.currentTaskOutputRoot), "D:\\本次任务");
  assert.equal(applied.settings.savedDefaultRoot, "D:\\长期默认");
});

test("14 恢复默认目录同时清除当前覆盖", () => {
  const restored = restoreBuiltInOutput(outputSettings);
  assert.equal(restored.settings.savedDefaultRoot, "D:\\影界文件\\输出\\图片压缩");
  assert.equal(restored.currentTaskOutputRoot, "");
});

test("15 三项能力使用同一生效目录", () => {
  const roots = ["LOSSLESS_COMPRESSION", "RESIZE_REDUCTION", "UPLOAD_ADAPTATION"].map((operationMode) => (
    buildCompressionRunPayload({ sourceToken: "token", operationMode, params: {}, currentTaskOutputRoot: "D:\\统一目录" }).current_task_output_root
  ));
  assert.deepEqual(roots, ["D:\\统一目录", "D:\\统一目录", "D:\\统一目录"]);
});

test("16 页面显示目录与固定功能目录一致", () => {
  const root = "D:\\统一目录";
  assert.equal(functionOutputDirectory(root, "LOSSLESS_COMPRESSION"), "D:\\统一目录\\PNG无损压缩");
  assert.equal(functionOutputDirectory(root, "RESIZE_REDUCTION"), "D:\\统一目录\\尺寸缩小");
  assert.equal(functionOutputDirectory(root, "UPLOAD_ADAPTATION"), "D:\\统一目录\\上传适配");
});

const feedbackPackage = (overrides = {}) => ({
  task_id: "task-a",
  package_name: "中文长图_测试反馈包.zip",
  package_size_bytes: 18432,
  package_sha256: "b".repeat(64),
  download_url: "/api/image-compression/feedback-package/opaque_token_123",
  display_path: "D:\\影界文件\\输出\\图片压缩\\尺寸缩小\\中文长图_测试反馈包.zip",
  function_directory_path: "D:\\影界文件\\输出\\图片压缩\\尺寸缩小",
  created_at: "2026-07-16T08:00:00+00:00",
  expires_at: "2026-07-16T10:00:00+00:00",
  can_open_folder: true,
  ...overrides,
});

test("17 未生成和生成中状态不显示伪下载链接", () => {
  assert.equal(feedbackPackageUiState(null).showDownload, false);
  const generating = feedbackPackageUiState(null, { generating: true });
  assert.equal(generating.generateDisabled, true);
  assert.equal(generating.generateLabel, "正在生成测试反馈包……");
});

test("18 成功反馈包显示真实相对下载链接和用户可读信息", () => {
  const data = normalizeFeedbackPackage(feedbackPackage());
  const state = feedbackPackageUiState(data, { nowMilliseconds: Date.parse("2026-07-16T09:00:00+00:00") });
  assert.equal(state.showDownload, true);
  assert.equal(feedbackPackageDownloadHref(data), data.download_url);
  assert.equal(feedbackPackageDownloadHref(data, "http://127.0.0.1:8787"), `http://127.0.0.1:8787${data.download_url}`);
  assert.match(data.package_name, /中文长图/);
  assert.equal(data.package_size_bytes, 18432);
  assert.match(data.display_path, /尺寸缩小/);
});

test("19 不安全或过期反馈包不显示下载链接并允许重新生成", () => {
  assert.throws(() => normalizeFeedbackPackage(feedbackPackage({ download_url: "file:///D:/private.zip" })), /不安全/);
  const expired = feedbackPackageUiState(feedbackPackage(), { nowMilliseconds: Date.parse("2026-07-16T11:00:00+00:00") });
  assert.equal(expired.showDownload, false);
  assert.equal(expired.showGenerate, true);
  assert.equal(expired.generateLabel, "重新生成测试反馈包");
  assert.equal(feedbackPackageExpired(feedbackPackage(), Date.parse("2026-07-16T11:00:00+00:00")), true);
});

test("20 反馈包只能附着到当前task且新任务不会复用旧链接", () => {
  const current = { result: { task_id: "task-a" }, ui: { feedback_package: null } };
  assert.equal(attachFeedbackPackage(current, feedbackPackage()).ui.feedback_package.task_id, "task-a");
  assert.throws(() => attachFeedbackPackage({ result: { task_id: "task-b" }, ui: {} }, feedbackPackage()), /不匹配/);
  assert.equal(newFileSessionPatch(file("replacement.png")).resultData, null);
  assert.equal(resetImageSessionPatch().resultData, null);
});

test("21 生成失败不产生伪链接且打开目录与下载职责分离", () => {
  const state = feedbackPackageUiState(null, { error: "生成失败" });
  assert.equal(state.showDownload, false);
  assert.equal(state.showGenerate, true);
  assert.equal(state.error, "生成失败");
  assert.notEqual(functionOutputDirectory("D:\\输出", "RESIZE_REDUCTION"), feedbackPackage().download_url);
});

test("22 反馈包合同拒绝伪造文件名、路径、时间和布尔类型", () => {
  assert.throws(() => normalizeFeedbackPackage(feedbackPackage({ package_name: "../private.zip" })), /文件名无效/);
  assert.throws(() => normalizeFeedbackPackage(feedbackPackage({
    display_path: "D:\\其他目录\\中文长图_测试反馈包.zip",
  })), /路径与功能目录不一致/);
  assert.throws(() => normalizeFeedbackPackage(feedbackPackage({
    expires_at: "2026-07-16T07:00:00+00:00",
  })), /有效期无效/);
  assert.throws(() => normalizeFeedbackPackage(feedbackPackage({
    can_open_folder: "false",
  })), /目录操作标记无效/);
});
