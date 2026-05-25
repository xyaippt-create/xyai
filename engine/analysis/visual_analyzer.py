from dataclasses import asdict, dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class VisualAnalysis:
    high_frequency_pollution: float
    ai_dirty_score: float
    sharpening_risk: float
    mid_frequency_score: float
    highlight_risk: float
    color_pollution: float
    atmosphere_deficiency: float
    premium_score: int
    recommended_mode: str
    problems_detected: list[str]
    next_actions: list[str]
    detected_issues: list[str]
    visual_scores: dict[str, float | int]
    material_hints: list[str]
    suggested_strategy: dict[str, float]

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return float(np.clip((value - low) / (high - low), 0.0, 1.0))


def _risk_label(value: float) -> str:
    if value < 0.34:
        return "low"
    if value < 0.67:
        return "medium"
    return "high"


def _grade(value: float) -> str:
    if value < 0.34:
        return "weak"
    if value < 0.67:
        return "moderate"
    return "strong"


def analyze_high_frequency_pollution(image) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    edge_density = float((cv2.Canny(gray, 80, 180) > 0).mean())
    return float(np.clip(_normalize(laplacian_var, 140.0, 1400.0) * 0.65 + _normalize(edge_density, 0.04, 0.22) * 0.35, 0.0, 1.0))


def analyze_ai_dirty_score(image) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    local_mean = cv2.GaussianBlur(gray, (0, 0), 4.0)
    residual = cv2.absdiff(gray, local_mean)
    color = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturation_noise = cv2.Laplacian(color[:, :, 1], cv2.CV_64F).var()
    residual_score = _normalize(float(residual.mean()), 4.0, 26.0)
    chroma_noise_score = _normalize(float(saturation_noise), 80.0, 1000.0)
    return float(np.clip(residual_score * 0.72 + chroma_noise_score * 0.28, 0.0, 1.0))


def analyze_sharpening_risk(image) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    edge_density = float((cv2.Canny(gray, 90, 190) > 0).mean())
    return float(np.clip(_normalize(float(np.abs(laplacian).mean()), 2.5, 16.0) * 0.55 + _normalize(edge_density, 0.04, 0.2) * 0.45, 0.0, 1.0))


def analyze_mid_frequency_score(image) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    low = cv2.GaussianBlur(gray, (0, 0), 6.0)
    mid = cv2.GaussianBlur(gray, (0, 0), 1.4)
    band = cv2.absdiff(mid, low)
    return _normalize(float(band.std()), 4.0, 32.0)


def analyze_highlight_risk(image) -> float:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    value = hsv[:, :, 2]
    saturation = hsv[:, :, 1]
    highlight_mask = value > 215
    if not np.any(highlight_mask):
        return 0.0
    clipped_ratio = float((value > 246).mean())
    highlight_saturation = float(saturation[highlight_mask].mean())
    highlight_texture = float(cv2.Laplacian(value, cv2.CV_64F)[highlight_mask].var())
    return float(np.clip(_normalize(clipped_ratio, 0.01, 0.18) * 0.45 + _normalize(highlight_saturation, 16.0, 86.0) * 0.25 + _normalize(highlight_texture, 20.0, 700.0) * 0.3, 0.0, 1.0))


def analyze_color_pollution(image) -> float:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1].astype("float32")
    hue = hsv[:, :, 0].astype("float32")
    high_saturation_ratio = float((saturation > 185).mean())
    hue_spread = float(np.std(hue[saturation > 35])) if np.any(saturation > 35) else 0.0
    return float(np.clip(_normalize(high_saturation_ratio, 0.06, 0.38) * 0.55 + _normalize(hue_spread, 36.0, 70.0) * 0.45, 0.0, 1.0))


def analyze_atmosphere_deficiency(image) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    contrast = _normalize(float(gray.std()), 22.0, 82.0)
    high_frequency = analyze_high_frequency_pollution(image)
    mid_frequency = analyze_mid_frequency_score(image)
    all_clear_risk = float(np.clip(high_frequency * 0.55 + contrast * 0.25 + mid_frequency * 0.2, 0.0, 1.0))
    return all_clear_risk


def recommend_mode(analysis_values: dict[str, float], rule_pack: dict | None = None) -> str:
    _ = rule_pack
    if analysis_values["color_pollution"] > 0.62 or analysis_values["ai_dirty_score"] > 0.58:
        return "ai_commercial_kv"
    if analysis_values["highlight_risk"] > 0.58 and analysis_values["mid_frequency_score"] < 0.45:
        return "cinematic"
    if analysis_values["sharpening_risk"] > 0.62:
        return "ppt_business"
    return "ai_commercial_kv"


def build_problem_list(values: dict[str, float]) -> list[str]:
    candidates = [
        ("high_frequency_pollution", "高频污染偏高"),
        ("ai_dirty_score", "AI脏感偏高"),
        ("sharpening_risk", "锐化风险偏高"),
        ("highlight_risk", "高光风险偏高"),
        ("color_pollution", "色彩污染偏高"),
        ("atmosphere_deficiency", "空气感不足"),
    ]
    problems = [label for key, label in candidates if values[key] >= 0.5]
    if values["mid_frequency_score"] < 0.34:
        problems.append("中频结构偏弱")
    return problems


def build_material_hints(values: dict[str, float]) -> list[str]:
    hints = []
    if values["highlight_risk"] >= 0.35:
        hints.append("reflective_or_glossy_surface")
    if values["mid_frequency_score"] < 0.42:
        hints.append("weak_volume_structure")
    if values["color_pollution"] >= 0.35:
        hints.append("color_unification_needed")
    if values["atmosphere_deficiency"] >= 0.45:
        hints.append("background_depth_needed")
    if not hints:
        hints.append("generic_commercial_visual")
    return hints


def build_next_actions(values: dict[str, float]) -> list[str]:
    actions = []
    if values["ai_dirty_score"] >= 0.34:
        actions.append("优先抑制 diffusion 纹理、AI颗粒和高频脏纹理")
    if values["mid_frequency_score"] < 0.5:
        actions.append("恢复中频商业结构，保护体积、材质层次和主体筋骨")
    if values["highlight_risk"] >= 0.34:
        actions.append("压缩高光并平滑光影过渡，减少假HDR和数码高光")
    if values["color_pollution"] >= 0.34:
        actions.append("统一色彩关系，控制 AI 蓝、AI 橙和 HDR 彩色污染")
    if values["atmosphere_deficiency"] >= 0.45:
        actions.append("降低全画面同等清晰感，建立主体与背景的空气层次")
    if not actions:
        actions.append("保持克制增强，避免破坏当前商业质感")
    return actions


def build_suggested_strategy(values: dict[str, float]) -> dict[str, float]:
    return {
        "noise_reduction_strength": round(float(np.clip(0.28 + values["ai_dirty_score"] * 0.55, 0.0, 1.0)), 4),
        "high_frequency_control_strength": round(float(np.clip(0.25 + values["high_frequency_pollution"] * 0.6, 0.0, 1.0)), 4),
        "mid_frequency_restore_strength": round(float(np.clip(0.24 + (1.0 - values["mid_frequency_score"]) * 0.55, 0.0, 1.0)), 4),
        "light_compression_strength": round(float(np.clip(0.22 + values["highlight_risk"] * 0.58, 0.0, 1.0)), 4),
        "atmosphere_strength": round(float(np.clip(0.22 + values["atmosphere_deficiency"] * 0.58, 0.0, 1.0)), 4),
        "color_harmony_strength": round(float(np.clip(0.2 + values["color_pollution"] * 0.62, 0.0, 1.0)), 4),
    }


def analyze_visual_quality(image, rule_pack: dict | None = None) -> VisualAnalysis:
    values = {
        "high_frequency_pollution": analyze_high_frequency_pollution(image),
        "ai_dirty_score": analyze_ai_dirty_score(image),
        "sharpening_risk": analyze_sharpening_risk(image),
        "mid_frequency_score": analyze_mid_frequency_score(image),
        "highlight_risk": analyze_highlight_risk(image),
        "color_pollution": analyze_color_pollution(image),
        "atmosphere_deficiency": analyze_atmosphere_deficiency(image),
    }
    values["premium_score"] = int(round(
        (
            (1.0 - values["ai_dirty_score"]) * 0.22
            + (1.0 - values["high_frequency_pollution"]) * 0.18
            + values["mid_frequency_score"] * 0.18
            + (1.0 - values["highlight_risk"]) * 0.14
            + (1.0 - values["color_pollution"]) * 0.14
            + (1.0 - values["atmosphere_deficiency"] * 0.7) * 0.14
        ) * 100
    ))
    recommended = recommend_mode(values, rule_pack)
    detected_issues = build_problem_list(values)
    visual_scores = {
        "premium_score": values["premium_score"],
        "high_frequency_pollution": round(values["high_frequency_pollution"], 4),
        "ai_dirty_score": round(values["ai_dirty_score"], 4),
        "sharpening_risk": round(values["sharpening_risk"], 4),
        "mid_frequency_score": round(values["mid_frequency_score"], 4),
        "highlight_risk": round(values["highlight_risk"], 4),
        "color_pollution": round(values["color_pollution"], 4),
        "atmosphere_deficiency": round(values["atmosphere_deficiency"], 4),
    }
    return VisualAnalysis(
        high_frequency_pollution=values["high_frequency_pollution"],
        ai_dirty_score=values["ai_dirty_score"],
        sharpening_risk=values["sharpening_risk"],
        mid_frequency_score=values["mid_frequency_score"],
        highlight_risk=values["highlight_risk"],
        color_pollution=values["color_pollution"],
        atmosphere_deficiency=values["atmosphere_deficiency"],
        premium_score=values["premium_score"],
        recommended_mode=recommended,
        problems_detected=detected_issues,
        next_actions=build_next_actions(values),
        detected_issues=detected_issues,
        visual_scores=visual_scores,
        material_hints=build_material_hints(values),
        suggested_strategy=build_suggested_strategy(values),
    )


def risk_label(value: float) -> str:
    return _risk_label(value)


def grade_label(value: float) -> str:
    return _grade(value)
