import React, { useEffect, useRef, useState } from "react";
import { appendPrintSource } from "./printPreflight.js";
import { pickRegionColors } from "./printLayerColors.js";

const names = { ink: "文字与圆章", texture: "纹理字", subject: "照片主体", hole:"主体镂空" };
const colors = { ink: "#2082cd", texture: "#c67817", subject: "#149567" };
const defaultRecipe = { version: 1, paper: "#ffffff", regions: [], subject: [], cutouts: [], snap: true };
const clamp = value => Math.max(0, Math.min(1, value));

export default function PrintLayerEditor({ source, onReady, busy }) {
  const [recipe, setRecipe] = useState(defaultRecipe);
  const [kind, setKind] = useState("ink");
  const [ink, setInk] = useState("#aa171b");
  const [sample, setSample] = useState("");
  const [index, setIndex] = useState(-1);
  const [draft, setDraft] = useState(null);
  const [preview, setPreview] = useState(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [hole,setHole]=useState([]);
  // Per region: false when its background is a gradient or photo that one paper colour would replace.
  const [flat,setFlat]=useState([]);
  const paperChosen = useRef(false);
  const [zoom,setZoom]=useState(1);
  const start = useRef(null);
  const revision = useRef(0);
  const photo = useRef(null);
  const w = source.width, h = source.height;
  const active = recipe.regions[index];
  useEffect(() => {
    const image = new Image();
    image.src = source.url;
    photo.current = image;
    return () => { revision.current++; };
  }, [source.url]);

  function update(next) {
    revision.current++;
    setRecipe(next);
    setPreview(null);
    setError("");
    onReady(null);
  }
  function modifyRegion(fields) {
    update({ ...recipe, regions: recipe.regions.map((item,i) => i === index ? { ...item, ...fields } : item) });
  }
  function point(event) {
    const svg = event.currentTarget;
    const p = new DOMPoint(event.clientX, event.clientY).matrixTransform(svg.getScreenCTM().inverse());
    return [clamp(p.x/w), clamp(p.y/h)];
  }
  function pointerDown(event) {
    if (busy || checking || event.button !== 0) return;
    const p = point(event);
    if (kind==="hole" && !sample) {
      if (hole.length<128) {setHole([...hole,p]);onReady(null);setPreview(null);}
      return;
    }
    if (sample) {
      if (!photo.current?.naturalWidth) return;
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 1;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(photo.current, Math.min(w-1, Math.floor(p[0]*w)), Math.min(h-1,Math.floor(p[1]*h)), 1,1,0,0,1,1);
      const value = "#" + [...ctx.getImageData(0,0,1,1).data].slice(0,3).map(v=>v.toString(16).padStart(2,"0")).join("");
      if (sample === "paper") { paperChosen.current = true; update({ ...recipe, paper:value }); }
      else { setInk(value); if (active) modifyRegion({ink:value}); }
      setSample("");
      return;
    }
    if (kind === "subject") {
      if (recipe.subject.length < 256) update({ ...recipe, subject:[...recipe.subject,p] });
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    start.current = p;
    setDraft([...p,...p]);
  }
  function rectangle(p) {
    const [x,y] = start.current;
    return [Math.min(x,p[0]),Math.min(y,p[1]),Math.max(x,p[0]),Math.max(y,p[1])];
  }
  function pointerUp(event) {
    if (!start.current) return;
    const rect = rectangle(point(event));
    start.current = null; setDraft(null);
    if ((rect[2]-rect[0])*w < 2 || (rect[3]-rect[1])*h < 2) return;
    if (recipe.regions.length >= 48) { setError("每张海报最多 48 个图文选区。"); return; }
    const picked = regionColors(rect);
    const regionInk = picked?.ink || ink;
    if (picked) setInk(regionInk);
    setIndex(recipe.regions.length);
    setFlat([...flat, picked ? picked.flat : true]);
    const paper = picked && !paperChosen.current && !recipe.regions.length ? picked.paper : recipe.paper;
    update({ ...recipe, paper, regions:[...recipe.regions,{kind, rect, ink:regionInk, dx:0, dy:0, scale:1}] });
  }
  // Start a new region from the poster's own colours (sampled at most 160 px on the long side).
  function regionColors(rect) {
    const image = photo.current;
    if (!image?.naturalWidth) return null;
    const sx = rect[0]*image.naturalWidth, sy = rect[1]*image.naturalHeight;
    const sw = Math.max(1, (rect[2]-rect[0])*image.naturalWidth), sh = Math.max(1, (rect[3]-rect[1])*image.naturalHeight);
    const ratio = Math.min(1, 160 / Math.max(sw, sh));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(sw*ratio)); canvas.height = Math.max(1, Math.round(sh*ratio));
    const ctx = canvas.getContext("2d");
    try {
      ctx.drawImage(image, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
      return pickRegionColors(ctx.getImageData(0, 0, canvas.width, canvas.height).data);
    } catch { return null; }
  }
  async function inspect(candidate=recipe, expectedHash="") {
    const id = revision.current;
    setChecking(true); setError("");
    try {
      const body = new FormData();
      appendPrintSource(body, source);
      body.append("layers",JSON.stringify(candidate));
      const r = await fetch("/api/print-output/layers/preview",{method:"POST",body});
      const data = await r.json();
      if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : data.detail?.message || "分层检查失败。");
      if(expectedHash && expectedHash!==data.source_sha256) throw new Error("该方案属于另一张原图。");
      if (revision.current === id) { setRecipe(data.recipe);setPreview(data);onReady(data.recipe);setHole([]);
        setFlat(data.recipe.regions.map(r => regionColors(r.rect)?.flat ?? true)); }
    } catch (e) { if (revision.current === id) setError(e.message); }
    finally { setChecking(false); }
  }
  function exportPlan() {
    const payload={format:"hdde-print-layers-v1",source_sha256:preview.source_sha256,recipe:preview.recipe};
    const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:"application/json"}));
    const a=document.createElement("a");a.href=url;a.download=source.name+".分层方案.json";a.click();
    setTimeout(()=>URL.revokeObjectURL(url),2000);
  }
  async function importPlan(input) {
    const selected=input.files?.[0];input.value="";
    if(!selected)return;
    revision.current++; onReady(null);setPreview(null);
    try {
      if(selected.size>262144)throw new Error("方案文件过大。");
      const data=JSON.parse(await selected.text());
      if(data.format!=="hdde-print-layers-v1" || !/^[0-9a-f]{64}$/.test(data.source_sha256)) throw new Error("请选择影界导出的分层方案。");
      await inspect(data.recipe,data.source_sha256);setIndex(-1);
    } catch(e){setError(e.message);}
  }
  function box(r,i,color) {
    return <rect key={i} x={r[0]*w} y={r[1]*h} width={(r[2]-r[0])*w} height={(r[3]-r[1])*h}
      fill={color} fillOpacity=".08" stroke={color} strokeWidth={i === index ? 2.5 : 1.5} vectorEffect="non-scaling-stroke" />;
  }
  return <fieldset className="print-layer-tools" disabled={busy || checking} aria-labelledby="print-layer-title">
    <div className="print-layer-body">
    <div className="print-panel-heading">
      <div className="hdde-color-section-title"><span aria-hidden="true">3</span><h2 id="print-layer-title">分层编辑</h2></div>
      <label className="print-zoom">标注视图<select value={zoom} onChange={e=>setZoom(Number(e.target.value))}>
        <option value="1">适应窗口</option><option value="2">放大两倍</option><option value="4">放大四倍</option>
      </select></label>
    </div>
    <div className="print-presets" role="group" aria-label="标记图层">
      {Object.entries(names).map(([k,n])=><button type="button" aria-pressed={kind===k} key={k}
        disabled={k==="hole" && recipe.subject.length<3} onClick={()=>{setKind(k);setSample("");setIndex(-1);setHole([]);}}>{n}</button>)}
    </div>
    <p>{sample ? "点击原图取色。" : kind === "hole" ? "点击围出主体内部的背景，完成后确认这处镂空。" : kind === "subject" ? "沿照片主体外缘依次点选，末点会与起点连接。" : "在原图上拖出矩形，框住同一字色、同一底色的一组图文。"}</p>
    <div className="print-layer-workspace">
    <div className="print-layer-stage"><svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} aria-label="海报分层画布"
      style={zoom>1?{width:w*zoom,height:h*zoom,maxWidth:"none",maxHeight:"none"}:undefined}
      onPointerDown={pointerDown} onPointerMove={e=>{if(start.current)setDraft(rectangle(point(e)));}}
      onPointerUp={pointerUp} onPointerCancel={()=>{start.current=null;setDraft(null);}}>
      <image href={source.url} width={w} height={h} />
      {recipe.regions.map((r,i)=>box(r.rect,i,colors[r.kind]))}
      {draft && box(draft,"draft",colors[kind])}
      {recipe.subject.length>0 && <polygon points={recipe.subject.map(([x,y])=>[x*w,y*h].join(",")).join(" ")}
        fill={colors.subject} fillOpacity=".18" stroke={colors.subject} strokeWidth="2" vectorEffect="non-scaling-stroke" />}
      {recipe.subject.map(([x,y],i)=><circle key={i} cx={x*w} cy={y*h} r={Math.max(w,h)/260} fill={colors.subject} />)}
      {[...recipe.cutouts,hole].filter(p=>p.length).map((poly,i)=><polygon key={i} points={poly.map(([x,y])=>[x*w,y*h].join(",")).join(" ")} stroke="#bb2a62" fill="#bb2a62" fillOpacity=".22" vectorEffect="non-scaling-stroke"/>)}
    </svg></div>
    <div className="print-layer-sidebar">
    <h3>选区设置</h3>
    <div className="print-actions">
      <label>纸色<input type="color" value={recipe.paper} onChange={e=>{paperChosen.current=true;update({...recipe,paper:e.target.value});}}/></label>
      <button type="button" aria-pressed={sample==="paper"} onClick={()=>setSample(sample==="paper"?"":"paper")}>从原图取纸色</button>
      {(kind === "ink" || kind === "texture") && <>
        <label>字色<input type="color" value={active?.ink || ink} onChange={e=>{setInk(e.target.value);if(active)modifyRegion({ink:e.target.value});}}/></label>
        <button type="button" aria-pressed={sample==="ink"} onClick={()=>setSample(sample==="ink"?"":"ink")}>从原图取字色</button>
      </>}
    </div>
    {!!recipe.regions.length && <div className="print-layer-list">
      <label>编辑图文选区<select value={index} onChange={e=>{const i=Number(e.target.value);setIndex(i);if(i>=0){setKind(recipe.regions[i].kind);setInk(recipe.regions[i].ink);}}}>
        <option value="-1">选择选区</option>
        {recipe.regions.map((r,i)=><option key={i} value={i}>{i+1} · {names[r.kind]}</option>)}
      </select></label>
      {active && <div className="print-actions">
        {[["dx","水平移动（%）"],["dy","垂直移动（%）"],["scale","字形缩放（%）"]].map(([k,n])=><label key={k}>{n}
          <input type="number" min={k==="scale"?10:-100} max={k==="scale"?400:100} step="1"
            value={Math.round(active[k]*100)} onChange={e=>modifyRegion({[k]:Number(e.target.value)/100})}/></label>)}
        <button type="button" onClick={()=>{update({...recipe,regions:recipe.regions.filter((_,i)=>i!==index)});setFlat(flat.filter((_,i)=>i!==index));setIndex(-1);}}>删除选区</button>
      </div>}
    </div>}
    {(kind==="subject" || recipe.subject.length>0) && <div className="print-subject-controls">
      <label><input type="checkbox" checked={recipe.snap} onChange={e=>update({...recipe,snap:e.target.checked})}/>主体边缘吸附</label>
      <button type="button" disabled={!recipe.subject.length} onClick={()=>update({...recipe,subject:recipe.subject.slice(0,-1),cutouts:recipe.subject.length<=3?[]:recipe.cutouts})}>撤销轮廓点</button>
      <button type="button" disabled={!recipe.subject.length} onClick={()=>{update({...recipe,subject:[],cutouts:[]});setHole([]);setKind("subject");}}>清除主体</button>
    </div>}
    {kind==="hole" && <div className="print-actions">
      <button type="button" disabled={hole.length<3} onClick={()=>{update({...recipe,cutouts:[...recipe.cutouts,hole]});setHole([]);}}>确认这处镂空</button>
      <button type="button" disabled={!hole.length} onClick={()=>setHole(hole.slice(0,-1))}>撤销镂空点</button>
      <button type="button" disabled={!recipe.cutouts.length} onClick={()=>update({...recipe,cutouts:recipe.cutouts.slice(0,-1)})}>移除上处镂空</button>
    </div>}
    </div></div>
    {checking && <p role="status">正在提取轮廓…</p>}
    {preview && <><img className="print-mask-preview" src={preview.preview} alt="分层选区预览"/>
      <p role="status">蓝色为文字轮廓，橙色为纹理字，绿色为主体。已提取 {preview.contours} 条闭合轮廓。</p></>}
    {flat.some(f=>!f) && <p role="alert">选区 {flat.map((f,i)=>f?null:i+1).filter(Boolean).join("、")} 的底色是渐变或照片。分层会把这块底色换成单一纸色，并按字色重画文字，会改变原图设计；这类海报建议直接用等比出图。</p>}
    {error && <p role="alert">{error}</p>}
    </div>
    <div className="print-actions print-layer-footer">
      <button type="button" className="hdde-secondary-action" onClick={()=>inspect()} disabled={!!hole.length || (!recipe.regions.length && !recipe.subject.length)}>检查分层选区</button>
      <label className="hdde-secondary-action print-picker">载入分层方案<input type="file" aria-label="载入分层方案" accept=".json" onChange={e=>importPlan(e.target)}/></label>
      {preview && <button type="button" onClick={exportPlan}>保存分层方案</button>}
    </div>
  </fieldset>;
}
