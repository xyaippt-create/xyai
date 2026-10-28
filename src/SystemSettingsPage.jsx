import React, { useEffect, useState } from "react";
import { useAppTheme } from "./AppShell.jsx";
import { HddePageHeader } from "./HddeUI.jsx";
import { PRODUCT_VERSION_LABEL } from "./productVersion.js";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

let settingsSnapshotPromise = null;

export function readApiData(payload) {
  if (payload?.data && typeof payload.data === "object" && !Array.isArray(payload.data)) return payload.data;
  return payload && typeof payload === "object" && !Array.isArray(payload) ? payload : {};
}

function apiErrorMessage(payload, path, status) {
  const detail = payload?.detail;
  if (detail && typeof detail === "object") {
    return detail.message || detail.reason || `${path} 请求失败（HTTP ${status}）。`;
  }
  return payload?.message || detail || `${path} 请求失败（HTTP ${status}）。`;
}

export async function requestApiPayload(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    if (!response.ok) throw new Error(`${path} 请求失败（HTTP ${response.status}）。`);
    throw new Error(`${path} 返回了无法解析的响应。`);
  }
  if (!response.ok || payload?.success === false) {
    throw new Error(apiErrorMessage(payload, path, response.status));
  }
  return payload;
}

export async function requestApi(path, options = {}) {
  return readApiData(await requestApiPayload(path, options));
}

function noStorePath(path) {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}recheck=${Date.now()}`;
}

export async function requestWorkdirStatus() {
  return requestApi(noStorePath("/api/app/workdir"), { cache: "no-store" });
}

export async function requestRestoreDefaultDirectory() {
  return requestApiPayload("/api/app/workdir/reset-default", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
}

export function loadSettingsSnapshot({ fresh = false } = {}) {
  if (fresh) settingsSnapshotPromise = null;
  if (!settingsSnapshotPromise) {
    const requestOptions = fresh ? { cache: "no-store" } : {};
    const healthPath = fresh ? noStorePath("/api/health") : "/api/health";
    const workdirPath = fresh ? noStorePath("/api/app/workdir") : "/api/app/workdir";
    settingsSnapshotPromise = Promise.allSettled([
      requestApi(healthPath, requestOptions),
      requestApi(workdirPath, requestOptions),
    ]).then(([health, workdir]) => ({
      health: health.status === "fulfilled"
        ? { status: "success", data: health.value, error: "" }
        : { status: "error", data: {}, error: "运行信息暂不可用，请确认本地后端服务已启动后刷新页面。" },
      workdir: workdir.status === "fulfilled"
        ? { status: "success", data: workdir.value, error: "" }
        : { status: "error", data: {}, error: "本地目录信息暂不可用，请确认本地后端服务已启动后刷新页面。" },
    }));
  }
  return settingsSnapshotPromise;
}

function hasValue(value) {
  return value !== undefined && value !== null && value !== "";
}

function displayValue(value) {
  if (Array.isArray(value)) return value.length ? value.join("、") : "接口未提供";
  return hasValue(value) ? String(value) : "接口未提供";
}

export function resolveFormalOutputRoot(appDataRoot) {
  const rawRoot = String(appDataRoot || "").trim();
  if (!rawRoot) return "";
  const separator = rawRoot.includes("\\") ? "\\" : "/";
  const normalizedRoot = rawRoot.replace(/[\\/]+$/, "") || separator;
  return normalizedRoot.endsWith(separator)
    ? `${normalizedRoot}输出`
    : `${normalizedRoot}${separator}输出`;
}

export function resolveDirectoryStatus(requestStatus, workdir) {
  if (requestStatus === "loading") {
    return { label: "正在读取", tone: "muted", showPaths: false, problem: "", impact: "", suggestion: "" };
  }
  if (requestStatus === "error") {
    return {
      label: "状态读取失败",
      tone: "negative",
      showPaths: false,
      problem: "暂时无法读取工作目录状态。",
      impact: "当前无法确认输出目录是否可用。",
      suggestion: "请确认本地后端服务已启动，然后刷新页面重试。",
    };
  }
  if (workdir.directory_ready === false) {
    return {
      label: "正式目录未就绪",
      tone: "negative",
      showPaths: true,
      problem: workdir.failure_reason || workdir.directory_message || "正式目录当前不可用。",
      impact: "依赖正式目录的图片处理任务已阻断，不会改用项目临时目录。",
      suggestion: "请恢复当前目录后重新检测，或选择一个可写的新正式目录。",
    };
  }
  if (workdir.app_data_root_exists === false) {
    return {
      label: "目录不存在",
      tone: "negative",
      showPaths: false,
      problem: "当前工作目录不存在。",
      impact: "应用无法确认正常的文件输入和输出位置。",
      suggestion: "请恢复或重新创建正式工作目录，然后重新启动应用。",
    };
  }
  if (workdir.app_data_root_writable === false) {
    return {
      label: "目录不可写",
      tone: "negative",
      showPaths: false,
      problem: "当前工作目录不可写。",
      impact: "新任务可能无法保存输出文件。",
      suggestion: "请检查目录权限和磁盘状态，然后重新启动应用。",
    };
  }
  if (workdir.app_data_root_exists === true && workdir.app_data_root_writable === true) {
    return { label: "正常可用", tone: "positive", showPaths: true, problem: "", impact: "", suggestion: "" };
  }
  return {
    label: "状态异常",
    tone: "negative",
    showPaths: false,
    problem: "工作目录状态信息不完整。",
    impact: "当前无法确认目录是否存在并且可写。",
    suggestion: "请刷新页面；如果问题持续，请确认本地后端服务状态。",
  };
}

function SettingsSection({ title, description, children }) {
  return (
    <section className="hdde-settings-section">
      <header className="hdde-settings-section__header">
        <div>
          <h2>{title}</h2>
        </div>
        <p>{description}</p>
      </header>
      <div className="hdde-settings-section__body">{children}</div>
    </section>
  );
}

function ReadOnlyRow({ label, value, status, valueAddon = null, path = false }) {
  const rendered = displayValue(value);
  return (
    <div className="hdde-settings-row">
      <div className="hdde-settings-row__label">{label}</div>
      <div
        className={`hdde-settings-row__value ${path ? "hdde-settings-row__value--path" : ""}`}
        title={hasValue(value) ? String(value) : undefined}
      >
        {status ? (
          <span className="hdde-settings-fact" data-tone={status.tone}>{status.label}</span>
        ) : valueAddon ? (
          <span className="hdde-settings-row__value-group">
            <span>{rendered}</span>
            {valueAddon}
          </span>
        ) : rendered}
      </div>
    </div>
  );
}

function RequestState({ status, error, loadingText }) {
  if (status === "loading") return <div className="hdde-settings-message" data-tone="loading">{loadingText}</div>;
  if (status === "error") return <div className="hdde-settings-message" data-tone="error">{error}</div>;
  return null;
}

export default function SystemSettingsPage() {
  const { themeMode, themeModes, selectThemeMode } = useAppTheme();
  const [snapshot, setSnapshot] = useState({
    health: { status: "loading", data: {}, error: "" },
    workdir: { status: "loading", data: {}, error: "" },
  });
  const [directoryAction, setDirectoryAction] = useState({ status: "idle", message: "" });

  useEffect(() => {
    let active = true;
    loadSettingsSnapshot().then((nextSnapshot) => {
      if (active) setSnapshot(nextSnapshot);
    });
    return () => {
      active = false;
    };
  }, []);

  const health = snapshot.health.data;
  const workdir = snapshot.workdir.data;
  const directoryStatus = resolveDirectoryStatus(snapshot.workdir.status, workdir);
  const formalOutputRoot = workdir.formal_output_root || resolveFormalOutputRoot(workdir.app_data_root);
  const isDefaultFormalDirectory = workdir.is_default_app_data_root === true;

  const handleSelectFormalDirectory = async () => {
    setDirectoryAction({ status: "loading", message: "正在等待本地目录选择…" });
    try {
      const payload = await requestApiPayload("/api/app/workdir/select-popup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (payload?.status === "cancelled") {
        setDirectoryAction({ status: "idle", message: "已取消选择正式目录。" });
        return;
      }
      const nextSnapshot = await loadSettingsSnapshot({ fresh: true });
      setSnapshot(nextSnapshot);
      setDirectoryAction({ status: "success", message: "正式目录已保存并通过校验。" });
    } catch (error) {
      setDirectoryAction({ status: "error", message: error.message || "正式目录选择失败。" });
    }
  };

  const handleRecheckFormalDirectory = async () => {
    setDirectoryAction({ status: "loading", message: "正在重新检测正式目录…" });
    try {
      const nextWorkdir = await requestWorkdirStatus();
      setSnapshot((current) => ({
        ...current,
        workdir: { status: "success", data: nextWorkdir, error: "" },
      }));
      settingsSnapshotPromise = null;
      setDirectoryAction({
        status: nextWorkdir.directory_ready ? "success" : "idle",
        message: nextWorkdir.directory_ready ? "正式目录已恢复可用。" : "重新检测完成：正式目录仍未就绪。",
      });
    } catch (error) {
      setDirectoryAction({ status: "error", message: error.message || "重新检测正式目录失败。" });
    }
  };

  const handleRestoreDefaultDirectory = async () => {
    if (isDefaultFormalDirectory) {
      setDirectoryAction({ status: "idle", message: "当前已是默认目录。" });
      return;
    }
    setDirectoryAction({ status: "loading", message: "正在恢复默认正式目录…" });
    try {
      const payload = await requestRestoreDefaultDirectory();
      const nextSnapshot = await loadSettingsSnapshot({ fresh: true });
      setSnapshot(nextSnapshot);
      setDirectoryAction({ status: "success", message: payload.message || "已恢复默认正式目录并通过校验。" });
    } catch (error) {
      setDirectoryAction({ status: "error", message: error.message || "恢复默认正式目录失败。" });
    }
  };

  return (
    <div className="hdde-settings-page hdde-page-frame hdde-page-stack" data-testid="system-settings-page">
      <HddePageHeader
        eyebrow="偏好与运行环境"
        title="系统设置"
        description="管理界面主题、正式目录与只读产品信息。目录变更仍执行既有安全校验。"
      />
      <SettingsSection
        title="外观设置"
        description="选择界面主题。选中状态即为当前设置，无需重复确认。"
      >
        <div className="hdde-settings-theme-options" role="group" aria-label="系统设置主题模式">
          {themeModes.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={themeMode === option.value}
              className={themeMode === option.value ? "is-selected" : ""}
              onClick={() => selectThemeMode(option.value)}
            >
              <span>{option.label}</span>
              <small>{option.value === "system" ? "响应系统外观变化" : `固定使用${option.label}界面`}</small>
            </button>
          ))}
        </div>
      </SettingsSection>

      <SettingsSection
        title="本地目录"
        description="正式目录是图片处理任务的唯一工作根目录；新目录只有在创建与可写校验通过后才会保存。"
      >
        <RequestState status={snapshot.workdir.status === "loading" ? "loading" : "success"} error="" loadingText="正在读取本地目录信息…" />
        {snapshot.workdir.status !== "loading" ? (
          <div className="hdde-settings-rows">
            <ReadOnlyRow label="工作目录状态" status={{ label: directoryStatus.label, tone: directoryStatus.tone }} />
          </div>
        ) : null}
        {directoryStatus.problem ? (
          <div className="hdde-settings-message" data-tone={directoryStatus.tone === "warning" ? "warning" : "error"}>
            <strong>{directoryStatus.problem}</strong>
            <span>当前影响：{directoryStatus.impact}</span>
            <span>建议：{directoryStatus.suggestion}</span>
          </div>
        ) : null}
        <div className="hdde-settings-rows">
          {snapshot.workdir.status === "success" && directoryStatus.showPaths ? (
            <>
              <ReadOnlyRow label="正式根目录" value={workdir.app_data_root || workdir.failed_path} path />
              {workdir.directory_ready ? (
                <ReadOnlyRow label="正式输出根目录" value={formalOutputRoot} path />
              ) : null}
            </>
          ) : null}
        </div>
        <div className="hdde-settings-message" data-tone={directoryAction.status === "error" ? "error" : "loading"}>
          <button type="button" onClick={handleSelectFormalDirectory} disabled={directoryAction.status === "loading"}>
            {directoryAction.status === "loading" ? "处理中…" : "选择新目录"}
          </button>
          <button type="button" onClick={handleRecheckFormalDirectory} disabled={directoryAction.status === "loading"}>
            {directoryAction.status === "loading" ? "检测中…" : "重新检测"}
          </button>
          <button
            type="button"
            onClick={handleRestoreDefaultDirectory}
            disabled={directoryAction.status === "loading" || isDefaultFormalDirectory}
            title={isDefaultFormalDirectory ? "当前已是默认目录" : undefined}
          >
            恢复默认
          </button>
          {directoryAction.message ? <span>{directoryAction.message}</span> : null}
        </div>
      </SettingsSection>

      <SettingsSection
        title="产品与版本"
        description="集中展示当前版本与官方联系信息。"
      >
        <RequestState status={snapshot.health.status} error={snapshot.health.error || "运行信息暂不可用。"} loadingText="正在读取平台运行信息…" />
        <div className="hdde-settings-product-layout">
          <div className="hdde-settings-rows">
            <ReadOnlyRow label="软件名称" value="影界 HDDE" />
            <ReadOnlyRow label="产品版本" value={health.version || PRODUCT_VERSION_LABEL} />
            <ReadOnlyRow label="版权信息" value="© 2026 雪原PPT设计·品牌视觉" />
            <ReadOnlyRow label="官方邮箱" value="xueyaippt@outlook.com" />
          </div>
          <figure className="hdde-settings-contact-qr">
            <img
              src="/assets/contact/wechat-qr.png"
              alt="影界 HDDE 官方微信二维码"
              width="104"
              height="104"
              loading="lazy"
            />
            <figcaption>扫码联系</figcaption>
          </figure>
        </div>
      </SettingsSection>
    </div>
  );
}
