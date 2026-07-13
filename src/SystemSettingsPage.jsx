import React, { useEffect, useState } from "react";
import { useAppTheme } from "./AppShell.jsx";
import { APP_ROUTES } from "./appRoutes.js";
import FeatureStatusBadge from "./FeatureStatusBadge.jsx";

const API_BASE = "http://localhost:8787";

let settingsSnapshotPromise = null;

function readApiData(payload) {
  if (payload?.data && typeof payload.data === "object" && !Array.isArray(payload.data)) return payload.data;
  return payload && typeof payload === "object" && !Array.isArray(payload) ? payload : {};
}

async function requestApi(path) {
  const response = await fetch(`${API_BASE}${path}`);
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    throw new Error(`${path} 返回了无法解析的响应。`);
  }
  if (!response.ok || payload?.success === false) {
    throw new Error(payload?.message || payload?.detail || `${path} 请求失败（HTTP ${response.status}）。`);
  }
  return readApiData(payload);
}

function loadSettingsSnapshot() {
  if (!settingsSnapshotPromise) {
    settingsSnapshotPromise = Promise.allSettled([
      requestApi("/api/health"),
      requestApi("/api/app/workdir"),
    ]).then(([health, workdir]) => ({
      health: health.status === "fulfilled"
        ? { status: "success", data: health.value, error: "" }
        : { status: "error", data: {}, error: health.reason?.message || "运行信息暂不可用。" },
      workdir: workdir.status === "fulfilled"
        ? { status: "success", data: workdir.value, error: "" }
        : { status: "error", data: {}, error: workdir.reason?.message || "本地目录信息暂不可用。" },
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

function booleanStatus(value, positive, negative) {
  if (value === true) return { label: positive, tone: "positive" };
  if (value === false) return { label: negative, tone: "negative" };
  return { label: "未提供", tone: "muted" };
}

function SettingsSection({ eyebrow, title, description, children }) {
  return (
    <section className="hdde-settings-section">
      <header className="hdde-settings-section__header">
        <div>
          <p className="hdde-eyebrow">{eyebrow}</p>
          <h2>{title}</h2>
        </div>
        <p>{description}</p>
      </header>
      <div className="hdde-settings-section__body">{children}</div>
    </section>
  );
}

function ReadOnlyRow({ label, value, status, path = false }) {
  const rendered = displayValue(value);
  return (
    <div className="hdde-settings-row">
      <div className="hdde-settings-row__label">{label}</div>
      <div
        className={`hdde-settings-row__value ${path ? "hdde-settings-row__value--path" : ""}`}
        title={hasValue(value) ? String(value) : undefined}
      >
        {status ? <span className="hdde-settings-fact" data-tone={status.tone}>{status.label}</span> : rendered}
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
  const { themeMode, resolvedTheme, themeModes, selectThemeMode } = useAppTheme();
  const [snapshot, setSnapshot] = useState({
    health: { status: "loading", data: {}, error: "" },
    workdir: { status: "loading", data: {}, error: "" },
  });

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
  const selectedThemeLabel = themeModes.find((option) => option.value === themeMode)?.label || "跟随系统";
  const effectiveThemeLabel = resolvedTheme === "light" ? "浅色" : "深色";
  const rootExists = booleanStatus(workdir.app_data_root_exists, "存在", "不存在");
  const rootWritable = booleanStatus(workdir.app_data_root_writable, "可写", "不可写");
  const lastOutputDir = workdir.last_output_dir || health.last_output_dir;

  return (
    <div className="hdde-settings-page" data-testid="system-settings-page">
      <div className="hdde-settings-page__intro">
        <div>
          <p className="hdde-eyebrow">REAL SETTINGS · ALPHA V1</p>
          <h1>基础设置与运行状态</h1>
        </div>
        <p>仅主题可修改；目录、平台信息与功能状态均为只读事实。</p>
      </div>

      <SettingsSection
        eyebrow="APPEARANCE"
        title="外观设置"
        description="复用平台唯一主题状态，并继续使用现有浏览器持久化。"
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
        <div className="hdde-settings-theme-summary" aria-live="polite">
          <span>当前选择：<strong>{selectedThemeLabel}</strong></span>
          <span>当前生效：<strong>{effectiveThemeLabel}</strong></span>
        </div>
      </SettingsSection>

      <SettingsSection
        eyebrow="LOCAL DIRECTORIES"
        title="本地目录"
        description="目录角色严格按现有接口字段分别显示，不合并、不推测、不提供修改入口。"
      >
        <RequestState status={snapshot.workdir.status} error={snapshot.workdir.error} loadingText="正在读取本地目录信息…" />
        <div className="hdde-settings-rows">
          {snapshot.workdir.status === "success" ? (
            <>
              <ReadOnlyRow label="工作根目录" value={workdir.app_data_root} path />
              <ReadOnlyRow label="工作根来源" value={workdir.app_data_root_source} />
              <ReadOnlyRow label="工作根存在状态" status={rootExists} />
              <ReadOnlyRow label="工作根写入状态" status={rootWritable} />
              <ReadOnlyRow label="工作根派生输出目录" value={workdir.output_dir} path />
              <ReadOnlyRow label="1080P安全增强 Beta 输出目录" value={workdir.beta_output_dir} path />
            </>
          ) : null}
          {snapshot.health.status === "success" ? (
            <ReadOnlyRow label="配置默认输出目录" value={health.default_output_dir} path />
          ) : null}
          {hasValue(lastOutputDir) ? <ReadOnlyRow label="上次使用输出目录" value={lastOutputDir} path /> : null}
        </div>
      </SettingsSection>

      <SettingsSection
        eyebrow="PLATFORM"
        title="平台信息"
        description="仅显示平台常量与当前接口明确返回的运行字段。"
      >
        <RequestState status={snapshot.health.status} error={snapshot.health.error || "运行信息暂不可用。"} loadingText="正在读取平台运行信息…" />
        <div className="hdde-settings-rows hdde-settings-rows--two-column">
          <ReadOnlyRow label="软件名称" value="影界 HDDE" />
          <ReadOnlyRow label="英文全称" value="HD Delivery Engine" />
          <ReadOnlyRow label="中文定位" value="高清交付引擎" />
          <ReadOnlyRow label="界面阶段" value="UI Alpha平台底座" />
          {snapshot.health.status === "success" ? (
            <>
              <ReadOnlyRow label="接口版本" value={health.version} />
              <ReadOnlyRow label="API Host" value={health.host} />
              <ReadOnlyRow label="API 端口" value={health.port} />
              <ReadOnlyRow label="目标分辨率" value={health.target_resolution} />
              <ReadOnlyRow label="当前支持模式" value={health.modes} />
              <ReadOnlyRow label="当前输出格式" value={health.outputFormats} />
            </>
          ) : null}
          {snapshot.workdir.status === "success" ? <ReadOnlyRow label="工作根来源" value={workdir.app_data_root_source} /> : null}
        </div>
      </SettingsSection>

      <SettingsSection
        eyebrow="FEATURE STATUS"
        title="功能状态"
        description="直接读取12项一级路由配置；此处仅表示功能开发状态。"
      >
        <div className="hdde-settings-feature-list">
          {APP_ROUTES.map((item, index) => (
            <div className="hdde-settings-feature-item" key={item.key}>
              <span className="hdde-settings-feature-index">{String(index + 1).padStart(2, "0")}</span>
              <span className="hdde-settings-feature-name">{item.name}</span>
              <FeatureStatusBadge status={item.status} compact source={`settings:${item.key}`} />
            </div>
          ))}
        </div>
      </SettingsSection>

      <SettingsSection
        eyebrow="UPDATES"
        title="更新信息"
        description="仅展示当前更新点位与开放状态；不执行检查、下载或安装。"
      >
        <div className="hdde-settings-rows hdde-settings-rows--two-column">
          <ReadOnlyRow label="产品版本" value="待统一版本来源" />
          <ReadOnlyRow label="产品阶段" value="UI Alpha" />
          <ReadOnlyRow label="当前构建" value="待接入构建信息" />
          <ReadOnlyRow label="更新渠道" value="Alpha" />
          <ReadOnlyRow label="检查更新" value="暂未开放" />
          <ReadOnlyRow label="更新说明" value="待正式发布机制建立后接入" />
          <ReadOnlyRow label="1080P研究基线" value="V0.4.6 RC8A" />
        </div>
      </SettingsSection>

      <SettingsSection
        eyebrow="ABOUT"
        title="关于影界"
        description="影界 HDDE 的只读产品信息与对外联系点位。"
      >
        <div className="hdde-settings-rows hdde-settings-rows--two-column">
          <ReadOnlyRow label="产品名称" value="影界 HDDE" />
          <ReadOnlyRow label="英文全称" value="HD Delivery Engine" />
          <ReadOnlyRow label="中文定位" value="高清交付引擎" />
          <ReadOnlyRow label="版权信息" value="© 雪原Ai·PPT设计" />
          <ReadOnlyRow label="官方联系方式" value="微信 xuey_aippt" />
          <ReadOnlyRow label="第三方依赖声明" value="待完成依赖审计" />
        </div>
      </SettingsSection>
    </div>
  );
}
