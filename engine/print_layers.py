"""Region-based poster reconstruction for the print editor. Coordinates follow the EXIF-upright source."""

import hashlib
import subprocess
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Literal

import cv2
import numpy as np
from PIL import Image, ImageCms, ImageColor, ImageDraw, ImageOps
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from engine.image_processing_routing.four_k_v1 import FourKV1ProcessingError
from engine.print_upscale import plan_print_upscale, upscale_rgb_for_print
from runtime.system_info import resource_root


Unit = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Offset = Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)]
Color = Annotated[str, Field(pattern="^#[0-9a-fA-F]{6}$")]
Point = tuple[Unit, Unit]
MODEL = "realesrgan-x4plus"


class LayerError(ValueError):
    """An actionable error for this editor."""


class Region(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["ink", "texture"]
    rect: tuple[Unit, Unit, Unit, Unit]
    ink: Color
    dx: Offset = 0
    dy: Offset = 0
    scale: float = Field(default=1, ge=0.1, le=4, allow_inf_nan=False)


class Recipe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    paper: Color
    regions: list[Region] = Field(max_length=48)
    subject: list[Point] = Field(max_length=256)
    cutouts: list[Annotated[list[Point], Field(min_length=3, max_length=128)]] = Field(default_factory=list, max_length=16)
    snap: bool = True

    @classmethod
    def read(cls, text):
        if len(text) > 65536:
            raise LayerError("分层选区过多，请简化后重试。")
        try:
            recipe = cls.model_validate_json(text)
        except ValidationError as exc:
            raise LayerError("分层参数无效，请重新检查选区。") from exc
        if not recipe.regions and not recipe.subject:
            raise LayerError("请先标记文字、纹理字或照片主体。")
        if 0 < len(recipe.subject) < 3:
            raise LayerError("主体轮廓至少需要三个点。")
        if recipe.cutouts and not recipe.subject:
            raise LayerError("请先绘制主体外轮廓，再标记镂空。")
        return recipe


def read_poster(data):
    try:
        with Image.open(BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as im:
            if im.width * im.height > 16_000_000 or getattr(im, "n_frames", 1) != 1:
                raise LayerError("分层编辑支持 1600 万像素以内的单帧海报。")
            if im.mode not in ("RGB", "L", "P", "RGBA", "LA") or (im.format == "PNG" and data[24] == 16):
                raise LayerError("分层编辑支持 8 位 RGB 和灰度海报。")
            ext = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[im.format]
            with ImageOps.exif_transpose(im) as upright:
                if ("A" in upright.getbands() or "transparency" in upright.info) and upright.convert("RGBA").getchannel("A").getextrema()[0] != 255:
                    raise LayerError("分层编辑需要带实色底的海报。透明图可使用等比出图。")
                profile = upright.info.get("icc_profile")
                if profile:
                    source = upright.convert("L" if upright.mode in ("L", "LA") else "RGB")
                    rgb = ImageCms.profileToProfile(source, ImageCms.ImageCmsProfile(BytesIO(profile)),
                                                    ImageCms.createProfile("sRGB"), outputMode="RGB")
                else:
                    rgb = upright.convert("RGB")
                return np.asarray(rgb).copy(), ext
    except (OSError, SyntaxError, ImageCms.PyCMSError, Image.DecompressionBombError) as exc:
        raise LayerError("无法解码海报或读取色彩配置。") from exc


def subject_mask(rgb, recipe):
    h, w = rgb.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    if not recipe.subject:
        return mask
    points = np.rint(np.asarray(recipe.subject) * (w-1, h-1)).astype(np.int32)
    if abs(cv2.contourArea(points)) < 9:
        raise LayerError("主体轮廓过小，请重新标记。")
    cv2.fillPoly(mask, [points], 255)
    if recipe.snap:
        band = max(3, min(15, round(min(w, h)*0.012)))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*band+1, 2*band+1))
        labels = np.zeros_like(mask)
        labels[cv2.dilate(mask, kernel)>0] = cv2.GC_PR_BGD
        labels[mask>0] = cv2.GC_PR_FGD
        labels[cv2.erode(mask, kernel)>0] = cv2.GC_FGD
        if np.any(labels==cv2.GC_FGD) and np.any(labels==cv2.GC_BGD):
            x,y,bw,bh = cv2.boundingRect(cv2.dilate(mask,kernel))
            window=np.s_[max(0,y-2):min(h,y+bh+2), max(0,x-2):min(w,x+bw+2)]
            local=labels[window].copy()
            cv2.setRNGSeed(317)
            cv2.grabCut(rgb[window].copy(),local,None,np.zeros((1,65)),np.zeros((1,65)),3,cv2.GC_INIT_WITH_MASK)
            mask[window]=(local%2)*255
    for hole in recipe.cutouts:
        points=np.rint(np.asarray(hole)*(w-1,h-1)).astype(np.int32)
        cv2.fillPoly(mask,[points],0)
    if not np.any(mask):
        raise LayerError("镂空后主体为空，请检查轮廓。")
    return mask


def _trace(patch, ink, paper, textured):
    # Subpixel isocontours: keep counters and nested rings in one even-odd fill.
    delta=np.asarray(ink,np.float32)-paper
    if np.dot(delta,delta)<900:
        raise LayerError("字色与纸色太接近，请取样笔画内部的颜色。")
    coverage=(patch.astype(np.float32)-paper) @ delta / np.dot(delta,delta)
    magnification=min(3, 3000/max(patch.shape[:2]))
    size=(max(1,round(coverage.shape[1]*magnification)),max(1,round(coverage.shape[0]*magnification)))
    fine=cv2.resize(coverage,size,interpolation=cv2.INTER_CUBIC)
    binary=(fine > (0.15 if textured else 0.5)).astype(np.uint8)
    if textured:
        radius=max(1,round(magnification*1.3))
        kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*radius+1,2*radius+1))
        binary=cv2.morphologyEx(binary,cv2.MORPH_CLOSE,kernel)
    contours,_=cv2.findContours(binary,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    paths=[]
    for contour in contours:
        if cv2.contourArea(contour) < magnification**2 * (2 if textured else 0.4):
            continue
        points=cv2.approxPolyDP(contour,0.33*magnification,True).reshape(-1,2)
        if len(points)>=3:
            paths.append((points.astype(np.float64)+0.5)/magnification)
    if not paths:
        raise LayerError("选区内未找到字形，请核对字色、纸色和边界。")
    return paths,coverage


def _curve_points(path):
    """Round shallow trace bends with quadratic joins; retain intentional corners."""
    before=np.roll(path,1,axis=0)-path
    after=np.roll(path,-1,axis=0)-path
    lb=np.maximum(np.linalg.norm(before,axis=1),1e-6)
    la=np.maximum(np.linalg.norm(after,axis=1),1e-6)
    u,v=before/lb[:,None],after/la[:,None]
    trim=np.minimum(2.0,0.4*np.minimum(lb,la))
    trim[np.sum(u*v,axis=1)>-0.48]=0
    a,b=path+u*trim[:,None],path+v*trim[:,None]
    t=np.linspace(0,1,5)[None,:,None]
    return ((1-t)**2*a[:,None,:]+2*(1-t)*t*path[:,None,:]+t**2*b[:,None,:]).reshape(-1,2)


def _surface(coverage, shape, ink, paper, seed):
    """Repaint a continuous tone field and native-resolution grain inside the letter mask."""
    w,h=shape
    # Masked smoothing prevents white paper from bleeding into the outline.
    support=(coverage>0.15).astype(np.float32)
    blur=lambda a: cv2.GaussianBlur(a,(0,0),3.0)
    tone=blur(np.clip(coverage,0,1)*support)/np.maximum(blur(support),0.001)
    # Retain bright particles using their local opacity profiles. A hard fill
    # would turn a soft speck into a flat disk at print scale.
    interior = cv2.erode(support.astype(np.uint8), np.ones((5, 5), np.uint8))
    local = cv2.GaussianBlur(coverage, (0, 0), 0.55)
    flecks = np.maximum(blur(coverage) - local - 0.045, 0) * interior
    tone = np.clip(tone - flecks * 1.35, 0.07, 1)
    tone = cv2.resize(tone, (w, h), interpolation=cv2.INTER_CUBIC)
    result=Image.new("RGB",(w,h))
    rng=np.random.default_rng(seed)
    for y in range(0,h,160):
        strip=tone[y:y+160]
        noise=rng.standard_normal(strip.shape,dtype=np.float32)*0.017
        specks=rng.random(strip.shape,dtype=np.float32)
        opacity=np.clip(strip+noise-np.maximum(specks-0.982,0)*28,0,1)
        result.paste(Image.fromarray(np.uint8(paper+(np.asarray(ink)-paper)*opacity[:,:,None])),(0,y))
    return result


def _photo_layer(rgb, mask, directory):
    x,y,w,h=cv2.boundingRect(mask)
    if w*h > 2_500_000:
        raise LayerError("主体选区超过 250 万像素，请缩小选区或使用等比出图。")
    roi=rgb[y:y+h,x:x+w].copy()
    selected=mask[y:y+h,x:x+w]
    # Extend only subject colors outside the matte to avoid colored text halos.
    outside=(selected==0).astype(np.uint8)
    _,labels=cv2.distanceTransformWithLabels(outside,cv2.DIST_L2,5,labelType=cv2.DIST_LABEL_PIXEL)
    palette=np.zeros((int(labels.max())+1,3),np.uint8)
    palette[labels[outside==0]]=roi[outside==0]
    roi=palette[labels]
    roi=cv2.addWeighted(roi,0.5,cv2.bilateralFilter(roi,5,14,3),0.5,0)
    tool=resource_root()/"external_tools"/"realesrgan-ncnn-vulkan"
    exe=tool/"realesrgan-ncnn-vulkan.exe"
    if not all(p.is_file() for p in [exe,tool/"models"/(MODEL+".bin"),tool/"models"/(MODEL+".param")]):
        raise LayerError("本地照片超分组件缺失，无法生成主体增强层。")
    with TemporaryDirectory(prefix=".print-sr-",dir=directory) as work:
        inp,out=Path(work)/"input.png",Path(work)/"result.png"
        Image.fromarray(roi).save(inp)
        try:
            run=subprocess.run([str(exe),"-i",str(inp),"-o",str(out),"-n",MODEL,"-s","4","-t","128","-f","png"],
                               cwd=tool,capture_output=True,timeout=480,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        except (subprocess.TimeoutExpired,OSError) as exc:
            raise LayerError("本地主体增强未完成，请检查显卡驱动或缩小主体选区。") from exc
        if run.returncode or not out.is_file():
            raise LayerError("本地超分引擎运行失败，请检查显卡或驱动后重试。")
        with Image.open(out) as sr:
            if sr.size!=(4*w,4*h):
                raise LayerError("主体超分尺寸校验失败。")
            ai=cv2.cvtColor(np.asarray(sr.convert("RGB")),cv2.COLOR_RGB2GRAY)
    base=cv2.resize(roi,(4*w,4*h),interpolation=cv2.INTER_CUBIC)
    yc=cv2.cvtColor(base,cv2.COLOR_RGB2YCrCb)
    diff=ai.astype(np.float32)-yc[:,:,0]
    detail=diff-cv2.GaussianBlur(diff,(0,0),3)
    yc[:,:,0]=np.uint8(np.clip(yc[:,:,0]+0.75*np.clip(detail,-28,28),0,255))
    return Image.fromarray(cv2.cvtColor(yc,cv2.COLOR_YCrCb2RGB))


def compose(rgb, recipe, size, directory=None, *, overlay=False):
    sh,sw=rgb.shape[:2]
    W,H=size
    factor=min(W/sw,H/sh)
    w,h=max(1,round(sw*factor)),max(1,round(sh*factor))
    sx,sy=w/sw,h/sh
    paper=np.array(ImageColor.getrgb(recipe.paper),np.float32)
    subject=subject_mask(rgb,recipe)
    original=Image.fromarray(rgb)
    base_upscale={"method":"LANCZOS","reason":"PREVIEW" if overlay else "NO_WORK_DIR"}
    if overlay or directory is None:
        canvas=original.resize((w,h),Image.Resampling.LANCZOS)
    else:
        # Unselected logos, small print and backgrounds get the same 4K reconstruction as proportional output.
        try:
            canvas,base_upscale=upscale_rgb_for_print(original,(w,h),directory,plan_print_upscale(sw,sh,w,h))
        except FourKV1ProcessingError as exc:
            raise LayerError(f"底图超清未完成：{exc}") from exc
    regions=[]
    draw=ImageDraw.Draw(canvas)
    for region in recipe.regions:
        x,y,x2,y2=np.rint(np.array(region.rect)*(sw,sh,sw,sh)).astype(int)
        if x2-x<2 or y2-y<2:
            raise LayerError("文字选区过小，请重新框选。")
        dx,dy=round((x+region.dx*sw)*sx),round((y+region.dy*sh)*sy)
        rw=max(1,round((x2-x)*sx*region.scale))
        rh=max(1,round((y2-y)*sy*region.scale))
        if dx < -1 or dy < -1 or dx+rw>w+1 or dy+rh>h+1:
            raise LayerError("移动或缩放后的图层超出画面，请调整位置。")
        regions.append((region,x,y,x2,y2,dx,dy,rw,rh))
        draw.rectangle((round(x*sx),round(y*sy),round(x2*sx)-1,round(y2*sy)-1),fill=recipe.paper)
    path_count=0
    for idx,(region,x,y,x2,y2,dx,dy,rw,rh) in enumerate(regions):
        ink=ImageColor.getrgb(region.ink)
        patch=rgb[y:y2,x:x2].copy()
        patch[subject[y:y2,x:x2]>0]=paper
        paths,coverage=_trace(patch,ink,paper,region.kind=="texture")
        path_count+=len(paths)
        mask=np.zeros((rh,rw),np.uint8)
        contours=[np.rint((_curve_points(p)*(rw/(x2-x),rh/(y2-y))-0.5)*16).astype(np.int32) for p in paths]
        cv2.fillPoly(mask,contours,255,lineType=cv2.LINE_AA,shift=4)
        fill=ink
        if overlay:
            fill=(23,128,213) if region.kind=="ink" else (194,121,25)
        elif region.kind=="texture":
            seed=int.from_bytes(hashlib.sha256(rgb[0,0].tobytes()+idx.to_bytes(2,"big")).digest()[:4],"big")
            fill=_surface(coverage,(rw,rh),ink,paper,seed)
        canvas.paste(fill,(dx,dy,dx+rw,dy+rh),Image.fromarray(mask))
    if np.any(subject):
        x,y,bw,bh=cv2.boundingRect(subject)
        target=(round(x*sx),round(y*sy),round((x+bw)*sx),round((y+bh)*sy))
        shape=(max(1,target[2]-target[0]),max(1,target[3]-target[1]))
        if overlay:
            roi=rgb[y:y+bh,x:x+bw]
            patch=Image.fromarray(cv2.addWeighted(roi,0.65,np.full_like(roi,(0,187,107)),0.35,0))
        else:
            patch=_photo_layer(rgb,subject,directory)
        alpha=Image.fromarray(subject[y:y+bh,x:x+bw]).resize(shape,Image.Resampling.BILINEAR)
        canvas.paste(patch.resize(shape,Image.Resampling.LANCZOS),target[:2],alpha)
    page=Image.new("RGB",(W,H),recipe.paper)
    page.paste(canvas,((W-w)//2,(H-h)//2))
    info={"contours":path_count,"regions":len(regions),
          "texture_regions":sum(r.kind=="texture" for r in recipe.regions),
          "subject_pixels":int(np.count_nonzero(subject)), "model":MODEL if np.any(subject) and not overlay else "",
          "base_upscale":base_upscale}
    return page, info
