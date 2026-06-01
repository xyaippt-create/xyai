import React, { useMemo, useRef, useState } from "react";

const API_BASE = "http://127.0.0.1:8787";

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
      className={`rounded-[1.75rem] border p-6 transition ${
        dragging ? "border-glacier/80 bg-glacier/10" : "border-white/10 bg-white/[0.045]"
      }`}
    >
      <p className="font-display text-xs uppercase tracking-[0.42em] text-glacier/70">Input Field</p>
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
          onChange={(event) => onFiles(Array.from(event.target.files || []))}
        />
        <input
          ref={folderInputRef}
          type="file"
          accept="image/*"
          multiple
          webkitdirectory=""
          className="hidden"
          onChange={(event) => onFiles(Array.from(event.target.files || []))}
        />
        <button type="button" onClick={() => fileInputRef.current?.click()} className="rounded-full border border-glacier/30 bg-glacier/10 px-5 py-3 text-sm text-glacier">
          添加图片
        </button>
        <button type="button" onClick={() => folderInputRef.current?.click()} className="rounded-full border border-white/10 bg-white/5 px-5 py-3 text-sm text-white/70">
          选择文件夹
        </button>
      </div>
      <p className={`mt-4 min-h-5 text-xs ${uploadState.error ? "text-ember" : "text-white/42"}`}>
        {uploadState.message}
      </p>
    </div>
  );
}

function SelectedImageTable({ images }) {
  return (
    <div className="rounded-[1.75rem] border border-white/10 bg-white/[0.045] p-6">
      <div className="mb-5 flex items-end justify-between">
        <div>
          <p className="font-display text-xs uppercase tracking-[0.42em] text-ember/70">Queue</p>
          <h2 className="mt-3 text-2xl font-semibold text-white">待处理列表</h2>
        </div>
        <span className="rounded-full border border-white/10 px-3 py-1 text-xs text-white/50">{images.length} 张</span>
      </div>
      <div className="overflow-hidden rounded-2xl border border-white/10">
        <div className="grid grid-cols-[1.5fr_0.8fr_0.7fr_0.7fr_0.6fr] bg-white/[0.06] px-4 py-3 text-xs tracking-[0.18em] text-white/42">
          <span>文件名</span>
          <span>尺寸</span>
          <span>大小</span>
          <span>类型</span>
          <span>状态</span>
        </div>
        {images.map((image) => (
          <div key={image.id} className="grid grid-cols-[1.5fr_0.8fr_0.7fr_0.7fr_0.6fr] border-t border-white/8 px-4 py-4 text-sm text-white/68">
            <span className="truncate pr-4">{image.name}</span>
            <span>{image.dimension}</span>
            <span>{image.size}</span>
            <span>{image.type}</span>
            <span className="text-aurora">{image.status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ModePanel({ activeMode, setActiveMode }) {
  return (
    <div className="rounded-[1.75rem] border border-white/10 bg-white/[0.045] p-6">
      <p className="font-display text-xs uppercase tracking-[0.42em] text-glacier/70">Restoration Modes</p>
      <h2 className="mt-3 text-2xl font-semibold text-white">四大增强模式</h2>
      <div className="mt-5 grid gap-3">
        {modes.map((mode) => (
          <button
            key={mode.id}
            type="button"
            onClick={() => setActiveMode(mode.id)}
            className={`rounded-2xl border p-4 text-left transition ${
              activeMode === mode.id ? "border-glacier/70 bg-glacier/12" : "border-white/10 bg-polar-900/60 hover:bg-white/[0.07]"
            }`}
          >
            <div className="flex items-center justify-between gap-4">
              <span className="text-base font-medium text-white">{mode.name}</span>
              <span className="font-display text-[0.62rem] uppercase tracking-[0.36em] text-glacier/60">{mode.signal}</span>
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
    <div className="rounded-[1.75rem] border border-white/10 bg-white/[0.045] p-6">
      <p className="font-display text-xs uppercase tracking-[0.42em] text-ember/70">Output Parameters</p>
      <h2 className="mt-3 text-2xl font-semibold text-white">输出图片参数</h2>
      <div className="mt-5 grid grid-cols-2 gap-4">
        <label className="space-y-2">
          <span className="text-xs tracking-[0.2em] text-white/42">Scale</span>
          <select value={scale} onChange={(event) => setScale(event.target.value)} className="w-full rounded-2xl border border-white/10 bg-polar-900 px-4 py-3 text-white">
            <option value="2">2x</option>
            <option value="4">4x</option>
          </select>
        </label>
        <label className="space-y-2">
          <span className="text-xs tracking-[0.2em] text-white/42">Format</span>
          <select value={format} onChange={(event) => setFormat(event.target.value)} className="w-full rounded-2xl border border-white/10 bg-polar-900 px-4 py-3 text-white">
            <option value="png">PNG</option>
            <option value="jpg">JPG</option>
          </select>
        </label>
      </div>
      <div className="mt-5 rounded-2xl border border-white/10 bg-polar-900/70 p-4 text-xs leading-6 text-white/52">
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
  const [uploadState, setUploadState] = useState({ message: "后端地址：http://127.0.0.1:8787/api/upload", error: false });

  const activeModeLabel = useMemo(() => modes.find((mode) => mode.id === activeMode)?.name || "原图忠实增强", [activeMode]);

  const uploadOneFile = async (file) => {
    const rowId = `upload_${Date.now()}_${file.name}`;
    setImages((prev) => [
      ...prev,
      {
        id: rowId,
        name: file.name,
        size: `${(file.size / 1024 / 1024).toFixed(2)} MB`,
        dimension: "上传中",
        type: "physical_upload",
        status: "uploading"
      }
    ]);

    const formData = new FormData();
    formData.append("file", file);
    formData.append("mode", activeMode);
    formData.append("scale", scale);
    formData.append("format", format);

    setUploadState({ message: `正在上传并修复：${file.name}`, error: false });
    const response = await fetch(`${API_BASE}/api/upload`, {
      method: "POST",
      body: formData
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(payload.error || "上传或修复失败");
    }

    const data = {
      ...payload.data,
      originalUrl: `${API_BASE}${payload.data.originalUrl}`,
      enhancedUrl: `${API_BASE}${payload.data.enhancedUrl}`
    };

    setImages((prev) =>
      prev.map((item) =>
        item.id === rowId
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
    setUploadState({ message: `修复完成：${file.name}`, error: false });
    onUploadComplete?.(data);
  };

  const handleFiles = async (files) => {
    const imageFiles = files.filter((file) => file.type.startsWith("image/"));
    if (!imageFiles.length) {
      setUploadState({ message: "未检测到可上传的图片文件。", error: true });
      return;
    }
    for (const file of imageFiles) {
      try {
        await uploadOneFile(file);
      } catch (error) {
        setUploadState({ message: error.message || "上传失败，请确认后端服务已启动。", error: true });
      }
    }
  };

  return (
    <section className="relative min-h-screen overflow-hidden bg-polar-950 px-6 py-6">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_22%_12%,rgba(143,244,255,0.15),transparent_24rem),radial-gradient(circle_at_80%_6%,rgba(183,255,212,0.1),transparent_22rem)]" />
      <div className="relative z-10 mx-auto max-w-7xl">
        <header className="mb-6 flex items-center gap-5">
          <SnowfieldMark />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <p className="font-display text-xs uppercase tracking-[0.55em] text-glacier/70">Visual Master Pro</p>
                <h1 className="mt-3 text-4xl font-semibold tracking-[0.08em] text-white">画质核心工作台</h1>
              </div>
              <button type="button" onClick={onBackToLaunch} className="rounded-full border border-white/10 px-4 py-2 text-sm text-white/55 hover:bg-white/5">
                返回启动页
              </button>
            </div>
            <div className="mt-5">
              <TopStatusStream runtimeSnapshot={runtimeSnapshot} />
            </div>
          </div>
        </header>

        <div className="grid gap-6 lg:grid-cols-[0.86fr_1.14fr_0.82fr]">
          <div className="space-y-6">
            <ImportPanel onFiles={handleFiles} uploadState={uploadState} />
            <ModePanel activeMode={activeMode} setActiveMode={setActiveMode} />
          </div>

          <div className="space-y-6">
            <SelectedImageTable images={images} />
            <div className="rounded-[1.75rem] border border-glacier/20 bg-glacier/10 p-6 shadow-cinematic">
              <p className="font-display text-xs uppercase tracking-[0.42em] text-glacier/70">Execution</p>
              <h2 className="mt-3 text-2xl font-semibold text-white">准备执行</h2>
              <p className="mt-3 text-sm leading-7 text-white/55">
                当前模式：{activeModeLabel}。处理时将优先保护原图构图、色彩与画风，面向真实画质恢复进行局部增强。
              </p>
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
                className="mt-6 w-full rounded-full border border-glacier/50 bg-glacier/20 px-6 py-4 text-sm font-semibold tracking-[0.28em] text-glacier hover:bg-glacier/30"
              >
                开启核心修复管线
              </button>
            </div>
          </div>

          <div className="space-y-6">
            <PhysicalContractPanel activeMode={activeMode} scale={scale} setScale={setScale} format={format} setFormat={setFormat} />
            <div className="rounded-[1.75rem] border border-white/10 bg-white/[0.045] p-6">
              <p className="font-display text-xs uppercase tracking-[0.42em] text-glacier/70">Pipeline</p>
              <h2 className="mt-3 text-2xl font-semibold text-white">状态映射</h2>
              <div className="mt-5 space-y-3">
                {["图像类型检测", "压缩损伤修复", "文字清晰增强", "真实边缘保护", "色彩锁定", "质量对比"].map((stage, index) => (
                  <div key={stage} className="flex items-center gap-3 rounded-xl border border-white/10 bg-polar-900/70 px-4 py-3">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-glacier/10 text-xs text-glacier">{index + 1}</span>
                    <span className="text-sm text-white/62">{stage}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
