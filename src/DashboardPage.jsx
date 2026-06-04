import React, { useMemo, useRef, useState } from "react";

const API_BASE = "http://localhost:8787";

const modes = [
  {
    id: "fidelity",
    name: "原图忠实增强",
    signal: "FIDELITY",
    description: "保持构图、颜色与画风，进行可信清晰优化。"
  },
  {
    id: "text_safe",
    name: "文字保护增强",
    signal: "TEXT SAFE",
    description: "优先处理小字、标题与海报说明文字。"
  },
  {
    id: "ai_image_clean",
    name: "AI图像清洁",
    signal: "AI CLEAN",
    description: "控制 diffusion 脏纹理、假 HDR 与电子锐边。"
  },
  {
    id: "sharp_4k",
    name: "4K清晰增强",
    signal: "4K CORE",
    description: "用于大屏预览和高清展示的结构补偿。"
  }
];

const seedFiles = [];
const DECOR_LABEL = "font-sans text-xs font-light uppercase tracking-[0.42em] text-emerald-500/60";
const PAGE_FOOTER = "© 2026 雪原系统. 保留所有权利。 V0.3 CORE Restorator Pipeline";
let GLOBAL_IS_UPLOADING = false;
let GLOBAL_UPLOAD_XHR = null;

function TopStatusStream({ runtimeSnapshot }) {
  const lines = [
    "Runtime Core 已就绪",
    "Quality Core Pipeline 待命",
    "AI Restoration Slot 预留",
    runtimeSnapshot?.runtimeReady ? "启动自检完成" : "等待启动快照"
  ];

  return (
    <div className="flex items-center gap-3 overflow-hidden rounded-full border border-white/10 bg-white/[0.045] px-4 py-3 backdrop-blur-xl">
      <span className="h-2 w-2 shrink-0 rounded-full bg-aurora shadow-[0_0_22px_rgba(183,255,212,0.9)]" />
      <div className="flex min-w-0 gap-6 text-xs text-white/58">
        {lines.map((line) => (
          <span key={line} className="whitespace-nowrap tracking-[0.18em]">
            {line}
          </span>
        ))}
      </div>
    </div>
  );
}

function SnowfieldMark() {
  return (
    <div className="relative flex h-28 w-28 shrink-0 items-center justify-center">
      <div className="absolute inset-0 rounded-full border border-glacier/30 bg-glacier/10 blur-[1px]" />
      <div className="absolute inset-3 rounded-full border border-white/10" />
      <div className="relative text-center">
        <div className="text-3xl font-black tracking-[0.16em] text-white [text-shadow:0_8px_32px_rgba(143,244,255,0.45)]">雪原</div>
        <div className="mt-2 font-display text-[0.58rem] uppercase tracking-[0.42em] text-glacier/70">Snowfield</div>
      </div>
    </div>
  );
}

function ImportPanel({ onFiles, uploadState }) {
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef(null);
  const folderInputRef = useRef(null);

  const handleInputChange = (event) => {
    const selectedFiles = Array.from(event.currentTarget.files || []);
    onFiles(selectedFiles);
    event.currentTarget.value = "";
  };

  const handleDrop = (event) => {
    event.preventDefault();
    setDragging(false);
    onFiles(Array.from(event.dataTransfer.files || []));
  };

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`rounded-lg border p-6 transition ${
        dragging ? "border-glacier/80 bg-glacier/10" : "border-white/10 bg-white/[0.045]"
      }`}
    >
      <p className={DECOR_LABEL}>Input Field</p>
      <h2 className="mt-3 text-2xl font-semibold text-white">图片拖拽导入</h2>
      <p className="mt-3 text-sm leading-7 text-white/55">
        将图片拖入此处，或使用本地文件选择器接入。当前前端为高保真交互层，后续与本地 Python Runtime 连接。
      </p>
      <div className="mt-6 grid grid-cols-2 gap-3">
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          onChange={handleInputChange}
        />
        <input
          ref={folderInputRef}
          type="file"
          accept="image/*"
          multiple
          webkitdirectory=""
          className="hidden"
          onChange={handleInputChange}
        />
        <button type="button" onClick={() => fileInputRef.current?.click()} className="rounded-lg border border-glacier/30 bg-glacier/10 px-5 py-3 text-sm text-glacier">
          添加图片
        </button>
        <button type="button" onClick={() => folderInputRef.current?.click()} className="rounded-lg border border-white/10 bg-white/5 px-5 py-3 text-sm text-white/70">
          选择文件夹
        </button>
      </div>
      <p className={`mt-4 min-h-5 text-xs ${uploadState.error ? "text-ember" : "text-white/42"}`}>
        {uploadState.message}
      </p>
    </div>
  );
}

function SelectedImageTable({ images, uploadProgress }) {
  const renderStatus = (status) => {
    if (status === "uploading") {
      return (
        <div className="flex w-full min-w-[120px] flex-col items-end">
          <span className="whitespace-nowrap text-xs font-medium text-yellow-400">正在上传... {uploadProgress}%</span>
          <div className="mt-1 h-[2px] w-full overflow-hidden rounded-full bg-white/5">
            <div
              className="h-full bg-gradient-to-r from-emerald-500 to-cyan-400 transition-all duration-200 ease-out"
              style={{ width: `${uploadProgress}%` }}
            />
          </div>
        </div>
      );
    }
    if (status === "ready") {
      return <span className="whitespace-nowrap text-emerald-400 font-bold animate-pulse">ready</span>;
    }
    if (status === "fail") {
      return <span className="whitespace-nowrap text-rose-500 font-medium">上传失败</span>;
    }
    return <span className="whitespace-nowrap text-white/42">{status || "等待"}</span>;
  };

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col rounded-lg border border-white/10 bg-white/[0.045] p-6">
      <div className="mb-5 flex items-end justify-between">
        <div>
          <p className={DECOR_LABEL}>Queue</p>
          <h2 className="mt-3 text-2xl font-semibold text-white">待处理列表</h2>
        </div>
        <span className="rounded-full border border-white/10 px-3 py-1 text-xs text-white/50">{images.length} 张</span>
      </div>
      <div className="flex flex-1 flex-col overflow-hidden rounded-lg border border-white/10">
        <div className="grid grid-cols-[1.5fr_0.8fr_0.7fr_0.7fr_0.6fr] bg-white/[0.06] px-4 py-3 text-xs tracking-[0.18em] text-white/42">
          <span>文件名</span>
          <span>尺寸</span>
          <span>大小</span>
          <span>类型</span>
          <span>状态</span>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          {images.length === 0 ? (
            <div className="flex h-full min-h-[16rem] items-center justify-center px-8 text-center">
              <div>
                <p className={DECOR_LABEL}>Empty Queue</p>
                <p className="mt-4 text-sm leading-7 text-white/48">尚未添加图片。请从左侧导入本地图片，系统会在上传成功后将状态标记为 ready。</p>
              </div>
            </div>
          ) : (
            images.map((image) => (
              <div key={image.id} className="grid grid-cols-[1.5fr_0.8fr_0.7fr_0.7fr_0.6fr] border-t border-white/8 px-4 py-4 text-sm text-white/68">
                <span className="truncate pr-4">{image.name}</span>
                <span>{image.dimension}</span>
                <span>{image.size}</span>
                <span>{image.type}</span>
                <span>{renderStatus(image.status)}</span>
              </div>
            ))
          )}
          </div>
      </div>
    </div>
  );
}

function ModePanel({ activeMode, setActiveMode }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-white/10 bg-white/[0.045] p-6">
      <p className={DECOR_LABEL}>Restoration Modes</p>
      <h2 className="mt-3 text-2xl font-semibold text-white">四大增强模式</h2>
      <div className="mt-5 grid min-h-0 flex-1 gap-3 overflow-y-auto pr-1">
        {modes.map((mode) => (
          <button
            key={mode.id}
            type="button"
            onClick={() => setActiveMode(mode.id)}
            className={`rounded-lg border p-4 text-left transition ${
              activeMode === mode.id ? "border-glacier/70 bg-glacier/12" : "border-white/10 bg-polar-900/60 hover:bg-white/[0.07]"
            }`}
          >
            <div className="flex items-center justify-between gap-4">
              <span className="text-base font-medium text-white">{mode.name}</span>
              <span className="font-sans text-[0.62rem] font-light uppercase tracking-[0.36em] text-emerald-500/50">{mode.signal}</span>
            </div>
            <p className="mt-2 text-xs leading-6 text-white/48">{mode.description}</p>
          </button>
        ))}
      </div>
    </div>
  );
}

function PhysicalContractPanel({ activeMode, scale, setScale, format, setFormat }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.045] p-6">
      <p className={DECOR_LABEL}>Output Parameters</p>
      <h2 className="mt-3 text-2xl font-semibold text-white">输出图片参数</h2>
      <div className="mt-5 grid grid-cols-2 gap-4">
        <label className="space-y-2">
          <span className="text-xs tracking-[0.2em] text-white/42">Scale</span>
          <select value={scale} onChange={(event) => setScale(event.target.value)} className="w-full rounded-lg border border-white/10 bg-polar-900 px-4 py-3 text-white">
            <option value="2">2x</option>
            <option value="4">4x</option>
          </select>
        </label>
        <label className="space-y-2">
          <span className="text-xs tracking-[0.2em] text-white/42">Format</span>
          <select value={format} onChange={(event) => setFormat(event.target.value)} className="w-full rounded-lg border border-white/10 bg-polar-900 px-4 py-3 text-white">
            <option value="png">PNG</option>
            <option value="jpg">JPG</option>
          </select>
        </label>
      </div>
      <div className="mt-5 rounded-lg border border-white/10 bg-polar-900/70 p-4 text-xs leading-6 text-white/52">
        当前参数：`--mode {activeMode}`、`--scale {scale}`、`--format {format}`。正式输出默认不添加角标。
      </div>
    </div>
  );
}

export default function DashboardPage({ runtimeSnapshot, onBackToLaunch, onStartTask, onUploadComplete }) {
  const [activeMode, setActiveMode] = useState("fidelity");
  const [scale, setScale] = useState("2");
  const [format, setFormat] = useState("png");
  const [images, setImages] = useState(seedFiles);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadState, setUploadState] = useState({ message: "后端地址：http://localhost:8787/api/upload", error: false });

  const activeModeLabel = useMemo(() => modes.find((mode) => mode.id === activeMode)?.name || "原图忠实增强", [activeMode]);

  const handleUploadError = (fileName, message = "上传失败，请确认后端服务已启动。") => {
    setImages((prev) => prev.map((item) => (item.name === fileName ? { ...item, status: "fail" } : item)));
    setUploadState({ message, error: true });
    setUploadProgress(0);
    GLOBAL_IS_UPLOADING = false;
    GLOBAL_UPLOAD_XHR = null;
  };

  const handleFileUpload = (originFile) => {
    if (!originFile || (typeof File !== "undefined" && !(originFile instanceof File))) {
      console.error("[Upload Error] 传入的文件对象非法或为空");
      return;
    }
    if (GLOBAL_IS_UPLOADING) {
      console.warn("[Global Singleton Lock] 成功拦截并发高频请求，主通道安全通车");
      return;
    }

    const shadowFile = originFile;
    GLOBAL_IS_UPLOADING = true;
    setUploadProgress(0);
    const newImageItem = {
        id: Date.now(),
        name: shadowFile.name,
        size: `${(shadowFile.size / 1024 / 1024).toFixed(2)} MB`,
        dimension: "上传中",
        type: "physical_upload",
        status: "uploading"
      }
    setImages((prev) => {
      const exists = prev.some((item) => item.name === shadowFile.name);
      if (exists) {
        return prev.map((item) => (item.name === shadowFile.name ? { ...item, ...newImageItem, id: item.id } : item));
      }
      return [...prev, newImageItem];
    });

    const uploadMode = activeMode || "fidelity";
    const uploadScale = scale || "2";
    const uploadFormat = (format || "png").toLowerCase();
    const formData = new FormData();
    formData.append("file", shadowFile);
    formData.append("mode", uploadMode);
    formData.append("scale", uploadScale);
    formData.append("format", uploadFormat);

    setUploadState({ message: `正在上传并修复：${shadowFile.name}`, error: false });
    const xhr = new XMLHttpRequest();
    GLOBAL_UPLOAD_XHR = xhr;
    xhr.open("POST", `${API_BASE}/api/upload`, true);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        const percentComplete = Math.round((event.loaded / event.total) * 100);
        setUploadProgress(percentComplete);
      }
    };

    xhr.onload = () => {
      try {
        if (xhr.status >= 200 && xhr.status < 300) {
          const payload = JSON.parse(xhr.responseText);
          if (payload.status === "success" || payload.success === true) {
            const data = {
              ...payload.data,
              originalUrl: `${API_BASE}${payload.data.originalUrl}`,
              enhancedUrl: `${API_BASE}${payload.data.enhancedUrl}`
            };

            console.log("[Upload Success] 进度100%完成，物理链路全线贯通:", data);
            setUploadProgress(100);
            setImages((prev) =>
              prev.map((item) =>
                item.name === shadowFile.name
                  ? {
                      ...item,
                      dimension: `${data.sourceWidth} × ${data.sourceHeight} → ${data.width} × ${data.height}`,
                      type: data.mode,
                      status: "ready",
                      originalUrl: data.originalUrl,
                      enhancedUrl: data.enhancedUrl
                    }
                  : item
              )
            );
            setUploadState({ message: `修复完成：${shadowFile.name}`, error: false });
            onUploadComplete?.(data);
            GLOBAL_IS_UPLOADING = false;
            GLOBAL_UPLOAD_XHR = null;
            return;
          }
        }
        throw new Error(`上传响应异常，状态码: ${xhr.status}`);
      } catch (error) {
        handleUploadError(shadowFile.name, error.message || "上传响应解析失败。");
      }
    };

    xhr.onerror = () => handleUploadError(shadowFile.name);
    xhr.onabort = () => {
      console.log("[Upload Abort] 重复并发请求已被全局原子锁优雅中断");
      handleUploadError(shadowFile.name, "上传已中断。");
    };
    xhr.send(formData);
  };

  const handleFiles = (files) => {
    const imageFiles = Array.from(files || []).filter((file) => file.type.startsWith("image/"));
    if (!imageFiles.length) {
      setUploadState({ message: "未检测到可上传的图片文件。", error: true });
      return;
    }
    handleFileUpload(imageFiles[0]);
  };

  return (
    <section className="relative h-[100dvh] w-screen overflow-hidden flex flex-col p-6 bg-[#090e10] text-slate-100 select-none animate-[fadeInUp_0.6s_ease-out_both] opacity-0 translate-y-2">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_22%_12%,rgba(143,244,255,0.15),transparent_24rem),radial-gradient(circle_at_80%_6%,rgba(183,255,212,0.1),transparent_22rem)]" />
      <div className="relative z-10 mx-auto flex h-full w-full max-w-7xl flex-col">
        <header className="flex h-[70px] shrink-0 items-center gap-5">
          <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-lg border border-glacier/30 bg-glacier/10 text-center">
            <div>
              <div className="text-base font-black tracking-[0.14em] text-white">雪原</div>
              <div className="mt-1 font-display text-[0.48rem] uppercase tracking-[0.28em] text-emerald-500/60">V0.3</div>
            </div>
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-4">
              <div className="min-w-0">
                <p className={DECOR_LABEL}>Visual Master Pro</p>
                <h1 className="mt-1 truncate text-3xl font-semibold tracking-[0.08em] text-white">画质核心工作台</h1>
              </div>
              <div className="min-w-0 flex-1 px-4">
                <TopStatusStream runtimeSnapshot={runtimeSnapshot} />
              </div>
              <button type="button" onClick={onBackToLaunch} className="shrink-0 rounded-lg border border-white/10 px-4 py-2 text-sm text-white/55 hover:bg-white/5">
                返回启动页
              </button>
            </div>
          </div>
        </header>

        <div className="min-h-0 w-full flex-1 overflow-hidden py-5">
          <div className="grid h-full w-full grid-cols-1 items-stretch gap-8 lg:grid-cols-3">
          <div className="flex h-full min-h-0 flex-col gap-4 overflow-hidden">
            <ImportPanel onFiles={handleFiles} uploadState={uploadState} />
            <ModePanel activeMode={activeMode} setActiveMode={setActiveMode} />
          </div>

          <div className="flex h-full min-h-0 flex-col justify-between gap-6 overflow-hidden">
            <SelectedImageTable images={images} uploadProgress={uploadProgress} />
          </div>

          <div className="flex h-full min-h-0 flex-col gap-6 overflow-hidden">
            <PhysicalContractPanel activeMode={activeMode} scale={scale} setScale={setScale} format={format} setFormat={setFormat} />
            <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-white/10 bg-white/[0.045] p-6">
              <p className={DECOR_LABEL}>Pipeline</p>
              <h2 className="mt-3 text-2xl font-semibold text-white">状态映射</h2>
              <div className="mt-5 min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
                {["图像类型检测", "压缩损伤修复", "文字清晰增强", "真实边缘保护", "色彩锁定", "质量对比"].map((stage, index) => (
                  <div key={stage} className="flex items-center gap-3 rounded-md border border-white/10 bg-polar-900/70 px-4 py-3">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-glacier/10 text-xs text-glacier">{index + 1}</span>
                    <span className="text-sm text-white/62">{stage}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
          </div>
        </div>

        <div className="relative z-50 mt-auto flex h-[112px] shrink-0 flex-col items-center justify-between pb-6">
          <div className="w-full max-w-3xl rounded-lg border border-glacier/20 bg-glacier/10 px-6 py-4 shadow-cinematic">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <p className={DECOR_LABEL}>Execution</p>
                <p className="mt-2 text-sm leading-6 text-white/55">
                  当前模式：{activeModeLabel} · {scale}x · {format.toUpperCase()} · 已选择 {images.length} 张
                </p>
              </div>
              <button
                type="button"
                onClick={() =>
                  onStartTask?.({
                    mode: activeMode,
                    scale,
                    format,
                    imageCount: images.length,
                    source: "DashboardPage"
                  })
                }
                className="min-w-[18rem] rounded-lg border border-glacier/50 bg-glacier/20 px-8 py-4 text-sm font-semibold tracking-[0.32em] text-glacier shadow-[inset_0_1px_0_rgba(255,255,255,0.16)] transition hover:bg-glacier/30"
              >
                开启核心修复管线
              </button>
            </div>
          </div>
          <footer className="text-center font-display text-[0.62rem] tracking-[0.24em] text-white/24">
            {PAGE_FOOTER}
          </footer>
        </div>
      </div>
    </section>
  );
}
