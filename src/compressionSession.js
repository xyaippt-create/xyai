export const FILE_SELECTION_STATES = Object.freeze({
  IDLE: "IDLE",
  FILE_SELECTING: "FILE_SELECTING",
  INTAKE_PENDING: "INTAKE_PENDING",
  FILE_READY: "FILE_READY",
  ERROR: "ERROR",
});

export const TOKEN_SESSION_ERROR_CODE = "TOKEN_NOT_FOUND_OR_EXPIRED";
export const TOKEN_SESSION_ERROR_MESSAGE = "图片会话已失效，请重新选择图片。";
export const FUNCTION_DIRECTORY_BY_MODE = Object.freeze({
  DELIVERY_OPTIMIZATION: "交付优化",
  LOSSLESS_COMPRESSION: "PNG无损压缩",
  RESIZE_REDUCTION: "尺寸缩小",
  UPLOAD_ADAPTATION: "上传适配",
});

export const REQUIRED_INTAKE_FIELDS = Object.freeze([
  "source_token",
  "display_name",
  "format",
  "width",
  "height",
  "size_bytes",
  "has_alpha",
  "source_sha256",
  "safe_preview_url",
  "expires_at",
]);

export const REQUIRED_FEEDBACK_PACKAGE_FIELDS = Object.freeze([
  "task_id",
  "package_name",
  "package_size_bytes",
  "package_sha256",
  "download_url",
  "display_path",
  "function_directory_path",
  "created_at",
  "expires_at",
  "can_open_folder",
]);

export function captureFileFromChangeEvent(event) {
  const files = event?.currentTarget?.files;
  return files?.length === 1 ? files[0] : null;
}

export function describeSelectedFile(file) {
  if (!file) return null;
  return {
    name: String(file.name || ""),
    size: Number(file.size || 0),
    type: String(file.type || ""),
    lastModified: Number(file.lastModified || 0),
  };
}

export function validateIntakeData(data) {
  if (!data || typeof data !== "object") throw new Error("图片接收响应缺少数据。")
  const missing = REQUIRED_INTAKE_FIELDS.filter((field) => !(field in data));
  if (missing.length) throw new Error(`图片接收响应缺少字段：${missing.join(", ")}。`);
  return data;
}

export async function performFileIntake(file, {
  request,
  createFormData = () => new FormData(),
  onTransition = () => {},
} = {}) {
  if (!file) throw new TypeError("必须提供一个图片 File 对象。")
  if (typeof request !== "function") throw new TypeError("必须提供图片接收请求函数。")
  const capturedFile = file;
  const selectedFile = describeSelectedFile(capturedFile);
  onTransition(FILE_SELECTION_STATES.FILE_SELECTING, { selectedFile });
  await Promise.resolve();
  const form = createFormData();
  form.append("file", capturedFile);
  onTransition(FILE_SELECTION_STATES.INTAKE_PENDING, { selectedFile });
  const payload = await request("/api/image-compression/intake", { method: "POST", body: form });
  const data = validateIntakeData(payload?.data);
  onTransition(FILE_SELECTION_STATES.FILE_READY, { selectedFile, data });
  return { data, selectedFile, form };
}

export function newFileSessionPatch(file) {
  return {
    selectedFile: describeSelectedFile(file),
    fileInfo: null,
    resultData: null,
    reviewNote: "",
    showReviewNote: false,
    zoom: { source: false, output: false },
    state: FILE_SELECTION_STATES.FILE_SELECTING,
    error: "",
  };
}

export function intakeSuccessPatch(data, selectedFile) {
  return {
    selectedFile,
    fileInfo: validateIntakeData(data),
    resultData: null,
    state: FILE_SELECTION_STATES.FILE_READY,
    error: "",
  };
}

export function resetImageSessionPatch(message = "") {
  return {
    selectedFile: null,
    fileInfo: null,
    resultData: null,
    reviewNote: "",
    showReviewNote: false,
    zoom: { source: false, output: false },
    state: message ? FILE_SELECTION_STATES.ERROR : FILE_SELECTION_STATES.IDLE,
    error: message,
  };
}

export function normalizeFeedbackPackage(data) {
  if (!data || typeof data !== "object") throw new Error("测试反馈包响应缺少数据。");
  const missing = REQUIRED_FEEDBACK_PACKAGE_FIELDS.filter((field) => !(field in data));
  if (missing.length) throw new Error(`测试反馈包响应缺少字段：${missing.join(", ")}。`);
  const taskId = String(data.task_id || "");
  const packageName = String(data.package_name || "");
  const downloadUrl = String(data.download_url || "");
  const displayPath = String(data.display_path || "");
  const functionDirectoryPath = String(data.function_directory_path || "");
  const createdAt = String(data.created_at || "");
  const expiresAt = String(data.expires_at || "");
  if (!taskId) throw new Error("测试反馈包任务编号无效。");
  if (
    !packageName
    || !packageName.toLowerCase().endsWith(".zip")
    || /[\\/]/.test(packageName)
    || [...packageName].some((character) => character.charCodeAt(0) < 32)
  ) {
    throw new Error("测试反馈包文件名无效。");
  }
  if (
    !/^\/api\/image-compression\/feedback-package\/[A-Za-z0-9_-]+$/.test(downloadUrl)
    || downloadUrl.includes("..")
    || /^file:/i.test(downloadUrl)
    || /^[A-Za-z]:[\\/]/.test(downloadUrl)
  ) {
    throw new Error("测试反馈包下载地址不安全。");
  }
  const packageSize = Number(data.package_size_bytes);
  if (!Number.isInteger(packageSize) || packageSize <= 0) throw new Error("测试反馈包体积无效。");
  if (!/^[a-f0-9]{64}$/i.test(String(data.package_sha256 || ""))) throw new Error("测试反馈包 SHA256 无效。");
  const normalizedDisplayPath = displayPath.replace(/\\/g, "/");
  const normalizedFunctionDirectory = functionDirectoryPath.replace(/\\/g, "/").replace(/\/+$/, "");
  if (
    !normalizedFunctionDirectory
    || normalizedDisplayPath !== `${normalizedFunctionDirectory}/${packageName}`
  ) {
    throw new Error("测试反馈包显示路径与功能目录不一致。");
  }
  const createdAtMilliseconds = Date.parse(createdAt);
  const expiresAtMilliseconds = Date.parse(expiresAt);
  if (
    !Number.isFinite(createdAtMilliseconds)
    || !Number.isFinite(expiresAtMilliseconds)
    || expiresAtMilliseconds <= createdAtMilliseconds
  ) {
    throw new Error("测试反馈包有效期无效。");
  }
  if (typeof data.can_open_folder !== "boolean") throw new Error("测试反馈包目录操作标记无效。");
  return {
    ...data,
    task_id: taskId,
    package_name: packageName,
    package_size_bytes: packageSize,
    package_sha256: String(data.package_sha256 || "").toLowerCase(),
    download_url: downloadUrl,
    display_path: displayPath,
    function_directory_path: functionDirectoryPath,
    created_at: createdAt,
    expires_at: expiresAt,
    can_open_folder: data.can_open_folder,
  };
}

export function feedbackPackageDownloadHref(data, apiBase = "") {
  const feedbackPackage = normalizeFeedbackPackage(data);
  return `${String(apiBase || "").replace(/\/$/, "")}${feedbackPackage.download_url}`;
}

export function feedbackPackageExpired(data, nowMilliseconds = Date.now()) {
  if (!data) return false;
  const expiresAt = Date.parse(String(data.expires_at || ""));
  return !Number.isFinite(expiresAt) || expiresAt <= Number(nowMilliseconds);
}

export function attachFeedbackPackage(resultData, data) {
  const feedbackPackage = normalizeFeedbackPackage(data);
  const taskId = String(resultData?.result?.task_id || "");
  if (!taskId || feedbackPackage.task_id !== taskId) throw new Error("测试反馈包与当前任务不匹配。");
  return {
    ...resultData,
    ui: { ...(resultData?.ui || {}), feedback_package: feedbackPackage },
  };
}

export function feedbackPackageUiState(data, { generating = false, error = "", nowMilliseconds = Date.now() } = {}) {
  let feedbackPackage = null;
  let contractError = "";
  if (data) {
    try {
      feedbackPackage = normalizeFeedbackPackage(data);
    } catch (reason) {
      contractError = reason.message;
    }
  }
  const expired = feedbackPackage ? feedbackPackageExpired(feedbackPackage, nowMilliseconds) : false;
  return {
    feedbackPackage,
    generating: Boolean(generating),
    expired,
    error: String(error || contractError || ""),
    showDownload: Boolean(feedbackPackage && !expired && !contractError),
    showGenerate: !feedbackPackage || expired || Boolean(contractError),
    generateDisabled: Boolean(generating),
    generateLabel: generating ? "正在生成测试反馈包……" : expired ? "重新生成测试反馈包" : "生成测试反馈包",
  };
}

export function isTokenSessionError(reason) {
  return reason?.code === TOKEN_SESSION_ERROR_CODE;
}

export function serverSessionChanged(previousSessionId, nextSessionId) {
  return Boolean(previousSessionId && nextSessionId && previousSessionId !== nextSessionId);
}

export function normalizeOutputSettings(data) {
  const builtInDefaultRoot = String(data?.built_in_default_root || "");
  const savedDefaultRoot = String(data?.saved_default_root || builtInDefaultRoot);
  return {
    builtInDefaultRoot,
    savedDefaultRoot,
    outputRootWritable: Boolean(data?.output_root_writable),
  };
}

export function effectiveOutputRoot(settings, currentTaskOutputRoot = "") {
  return String(currentTaskOutputRoot || settings?.savedDefaultRoot || settings?.builtInDefaultRoot || "");
}

export function functionOutputDirectory(root, operationMode) {
  const base = String(root || "").replace(/[\\/]+$/, "");
  const directory = FUNCTION_DIRECTORY_BY_MODE[operationMode] || "";
  if (!base || !directory) return "";
  const separator = base.includes("\\") ? "\\" : "/";
  return `${base}${separator}${directory}`;
}

export function applyOutputSelection(settings, currentTaskOutputRoot, path, scope) {
  const selected = String(path || "");
  if (scope === "saved_default") {
    return {
      settings: { ...settings, savedDefaultRoot: selected, outputRootWritable: true },
      currentTaskOutputRoot: "",
    };
  }
  return { settings, currentTaskOutputRoot: selected };
}

export function restoreBuiltInOutput(settings) {
  return {
    settings: { ...settings, savedDefaultRoot: settings?.builtInDefaultRoot || "", outputRootWritable: true },
    currentTaskOutputRoot: "",
  };
}

export function buildCompressionRunPayload({ sourceToken, operationMode, params, currentTaskOutputRoot = "", longImageRiskConfirmed = false }) {
  const payload = { source_token: sourceToken, operation_mode: operationMode, params };
  if (currentTaskOutputRoot) payload.current_task_output_root = currentTaskOutputRoot;
  if (longImageRiskConfirmed) payload.long_image_risk_confirmation = true;
  return payload;
}
