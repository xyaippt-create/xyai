import { FEATURE_STATUSES } from "./platformStatus.js";

export const APP_ROUTES = Object.freeze([
  {
    key: "processing",
    name: "处理中心",
    path: "/processing",
    status: FEATURE_STATUSES.ENABLED,
    pageTitle: "处理中心",
    description: "使用现有画质核心工作台执行真实1080P任务并查看处理结果。",
    implementationType: "existing",
    plannedCapabilities: ["真实图片导入", "1080P安全交付", "任务结果与输出查看"],
  },
  {
    key: "batch",
    name: "批量优化",
    path: "/batch",
    status: FEATURE_STATUSES.IN_DEVELOPMENT,
    pageTitle: "批量优化",
    description: "面向多文件任务编组、批次状态查看和批量交付流程。",
    implementationType: "placeholder",
    plannedCapabilities: ["多文件任务编组", "批次级处理状态", "批量结果汇总"],
  },
  {
    key: "color-correction",
    name: "颜色校正",
    path: "/color-correction",
    status: FEATURE_STATUSES.IN_DEVELOPMENT,
    pageTitle: "颜色校正",
    description: "用于颜色偏差分析、品牌色保护和人工复核。",
    implementationType: "placeholder",
    plannedCapabilities: ["颜色偏差分析", "品牌色保护提示", "人工复核入口"],
  },
  {
    key: "compression",
    name: "图片压缩",
    path: "/compression",
    status: FEATURE_STATUSES.PLANNED,
    pageTitle: "图片压缩",
    description: "用于比较文件体积与可见画质收益，并由人工决定是否采用候选文件。",
    implementationType: "placeholder",
    plannedCapabilities: ["体积收益比较", "格式候选查看", "人工采用判断"],
  },
  {
    key: "retouch",
    name: "标记修整",
    path: "/retouch",
    status: FEATURE_STATUSES.PLANNED,
    pageTitle: "交付标记与局部修整",
    description: "用于记录交付标记、定位局部问题并组织人工修整流程。",
    implementationType: "placeholder",
    plannedCapabilities: ["交付标记检查", "局部问题定位", "人工修整工作流"],
  },
  {
    key: "tasks",
    name: "任务队列",
    path: "/tasks",
    status: FEATURE_STATUSES.IN_DEVELOPMENT,
    pageTitle: "任务队列",
    description: "用于集中查看任务阶段、异常状态和后续质检入口。",
    implementationType: "placeholder",
    plannedCapabilities: ["任务阶段查看", "异常状态定位", "任务详情入口"],
  },
  {
    key: "compare",
    name: "对比质检",
    path: "/compare",
    status: FEATURE_STATUSES.ENABLED,
    pageTitle: "对比质检",
    description: "使用真实任务资产进行原图与处理结果的滑杆对比和局部检查。",
    implementationType: "existing",
    plannedCapabilities: ["滑杆对比", "局部放大镜", "真实质量指标"],
  },
  {
    key: "quality-report",
    name: "质量报告",
    path: "/quality-report",
    status: FEATURE_STATUSES.ENABLED,
    pageTitle: "质量报告",
    description: "读取真实任务报告，展示质量指标、风险和交付建议。",
    implementationType: "existing",
    plannedCapabilities: ["真实质量指标", "风险说明", "人工终审建议"],
  },
  {
    key: "smart-delivery",
    name: "智能交付",
    path: "/smart-delivery",
    status: FEATURE_STATUSES.IN_DEVELOPMENT,
    pageTitle: "智能交付",
    description: "用于组织命名规则、交付清单和人工确认流程。",
    implementationType: "placeholder",
    plannedCapabilities: ["交付命名规则", "交付清单", "人工确认流程"],
  },
  {
    key: "outputs",
    name: "输出中心",
    path: "/outputs",
    status: FEATURE_STATUSES.IN_DEVELOPMENT,
    pageTitle: "输出中心",
    description: "用于集中查看真实输出文件状态、目录入口和结果文件信息。",
    implementationType: "placeholder",
    plannedCapabilities: ["输出文件状态", "本地目录入口", "结果文件汇总"],
  },
  {
    key: "history",
    name: "历史任务",
    path: "/history",
    status: FEATURE_STATUSES.PLANNED,
    pageTitle: "历史任务",
    description: "用于查看本地任务记录和已有结果状态；当前尚无持久化任务列表。",
    implementationType: "placeholder",
    plannedCapabilities: ["历史任务索引", "结果状态回看", "本地记录筛选"],
  },
  {
    key: "settings",
    name: "系统设置",
    path: "/settings",
    status: FEATURE_STATUSES.IN_DEVELOPMENT,
    pageTitle: "系统设置",
    description: "用于承载主题偏好、本地目录状态和平台信息。",
    implementationType: "placeholder",
    plannedCapabilities: ["主题与界面偏好", "本地目录状态", "平台信息"],
  },
]);

export const COMPATIBILITY_ROUTES = Object.freeze([
  {
    key: "safe-1080p-beta",
    name: "1080P安全增强 Beta",
    path: "/safe-1080p-beta",
    status: FEATURE_STATUSES.BETA,
    pageTitle: "1080P安全增强 Beta",
    description: "保留现有Beta兼容入口，不进入一级导航。",
    implementationType: "compatibility",
    plannedCapabilities: [],
  },
]);

export const DEFAULT_APP_PATH = "/processing";

export function normalizeAppPath(pathname) {
  const rawPath = String(pathname || "/").split(/[?#]/, 1)[0] || "/";
  if (rawPath === "/") return "/";
  return rawPath.length > 1 ? rawPath.replace(/\/+$/, "") : rawPath;
}

export function findAppRoute(pathname) {
  const path = normalizeAppPath(pathname);
  return APP_ROUTES.find((route) => route.path === path) || COMPATIBILITY_ROUTES.find((route) => route.path === path) || null;
}
