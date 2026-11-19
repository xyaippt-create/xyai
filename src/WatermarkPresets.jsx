import React, { useEffect, useState } from "react";

const ENDPOINT = `${import.meta.env.VITE_API_BASE_URL || ""}/api/batch-watermark/presets`;

async function request(suffix = "", init = {}) {
  const response = await fetch(ENDPOINT + suffix, { cache: "no-store", ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail?.message || body.detail;
    throw new Error(typeof detail === "string" ? detail : "常用方案操作失败，请重试。");
  }
  return response;
}

export default function WatermarkPresets({ active, spec, logoFile, onApply, setApplying }) {
  const [open, setOpen] = useState(false);
  const [presets, setPresets] = useState([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!active || !open) return undefined;
    const controller = new AbortController();
    setLoading(true);
    setNotice("");
    setPresets([]);
    async function load() {
      try {
        const response = await request("", { signal: controller.signal });
        const { data } = await response.json();
        if (!controller.signal.aborted) setPresets(data);
      } catch (error) {
        if (!controller.signal.aborted) setNotice(error.message);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [active, open]);

  async function save(event) {
    event.preventDefault();
    setBusy(true);
    const form = new FormData();
    form.append("name", name.trim());
    form.append("spec_json", JSON.stringify(spec));
    if (spec.kind === "image" && logoFile) form.append("watermark_file", logoFile, logoFile.name);
    try {
      const response = await request("", { method: "POST", body: form });
      const { data } = await response.json();
      setPresets((rows) => [data, ...rows]);
      setName("");
      setNotice(`已保存「${data.name}」。`);
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function apply(preset) {
    setApplying(true);
    let file = null;
    try {
      if (preset.spec.kind === "image") {
        const response = await request(`/${preset.id}/logo`);
        file = new File([await response.blob()], preset.logo_name || "Logo.png", { type: "image/png" });
      }
      onApply(preset.spec, file);
      setNotice(`已套用「${preset.name}」。`);
    } catch {
      onApply(preset.spec, null, "此方案的 Logo 无法读取，请重新选择透明 PNG Logo。");
      setNotice("");
    } finally {
      setApplying(false);
    }
  }

  async function remove(preset) {
    setBusy(true);
    try {
      await request(`/${preset.id}`, { method: "DELETE" });
      setPresets((rows) => rows.filter((row) => row.id !== preset.id));
      setNotice(`已删除「${preset.name}」。`);
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
    }
  }

  const canSave = name.trim() && (spec.kind === "image" ? logoFile : spec.text.trim());
  return <details className="hdde-watermark-presets" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>常用方案</summary>
    <fieldset disabled={busy || loading}>
      <form onSubmit={save}>
        <input aria-label="方案名称" placeholder="方案名称" maxLength={80} value={name} onChange={(event) => setName(event.target.value)} />
        <button className="hdde-secondary-action" type="submit" disabled={!canSave}>保存为常用方案</button>
      </form>
      {presets.map((preset) => <div key={preset.id} className="hdde-watermark-preset-row">
        <button type="button" className="hdde-secondary-action" aria-label={`套用「${preset.name}」`} onClick={() => void apply(preset)}>{preset.name}</button>
        <button type="button" className="hdde-tertiary-action" aria-label={`删除「${preset.name}」`} onClick={() => void remove(preset)}>删除</button>
      </div>)}
    </fieldset>
    {loading || notice ? <p role="status">{loading ? "正在读取方案…" : notice}</p> : null}
  </details>;
}
