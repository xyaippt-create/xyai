from dataclasses import replace

from engine.config import ProcessingStrategy
from engine.rules.rule_loader import RuleSet


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _analysis_value(analysis, key: str, default: float = 0.0) -> float:
    if hasattr(analysis, key):
        return float(getattr(analysis, key))
    if isinstance(analysis, dict):
        return float(analysis.get(key, default))
    return default


def _analysis_list(analysis, key: str) -> list[str]:
    if hasattr(analysis, key):
        return list(getattr(analysis, key) or [])
    if isinstance(analysis, dict):
        return list(analysis.get(key, []) or [])
    return []


def _rule_text(rule_set: RuleSet) -> str:
    chunks: list[str] = []
    for document in rule_set.documents:
        chunks.append(str(document.data))
    return "\n".join(chunks)


def _base_strategy_from_scores(analysis) -> ProcessingStrategy:
    high_frequency = _analysis_value(analysis, "high_frequency_pollution")
    ai_dirty = _analysis_value(analysis, "ai_dirty_score")
    mid_frequency = _analysis_value(analysis, "mid_frequency_score")
    highlight = _analysis_value(analysis, "highlight_risk")
    color = _analysis_value(analysis, "color_pollution")
    atmosphere_gap = _analysis_value(analysis, "atmosphere_deficiency")
    sharpening = _analysis_value(analysis, "sharpening_risk")

    return ProcessingStrategy(
        noise_reduction_strength=_clamp(0.28 + ai_dirty * 0.55),
        high_frequency_control_strength=_clamp(0.25 + high_frequency * 0.6),
        mid_frequency_restore_strength=_clamp(0.24 + (1.0 - mid_frequency) * 0.55),
        light_compression_strength=_clamp(0.22 + highlight * 0.58),
        atmosphere_strength=_clamp(0.22 + atmosphere_gap * 0.58),
        color_harmony_strength=_clamp(0.2 + color * 0.62),
        sharpen_strength=_clamp(0.22 - high_frequency * 0.12 - sharpening * 0.14),
        texture_cleanliness_target=_clamp(0.72 + ai_dirty * 0.2),
        premium_style_target=0.82,
    )


def interpret_rules_to_strategy(analysis, rule_set: RuleSet, mode: str | None = None) -> ProcessingStrategy:
    """Translate visual rules and analyzer findings into processing strengths."""

    strategy = _base_strategy_from_scores(analysis)
    issues = " ".join(_analysis_list(analysis, "detected_issues") or _analysis_list(analysis, "problems_detected"))
    rule_text = _rule_text(rule_set)
    combined = f"{issues}\n{rule_text}"

    if any(token in combined for token in ["高频污染", "diffusion", "假HDR", "电子锐边", "AI 毛刺"]):
        strategy = replace(
            strategy,
            high_frequency_control_strength=_clamp(strategy.high_frequency_control_strength + 0.18),
            sharpen_strength=_clamp(strategy.sharpen_strength - 0.1),
            atmosphere_strength=_clamp(strategy.atmosphere_strength + 0.08),
            texture_cleanliness_target=_clamp(strategy.texture_cleanliness_target + 0.08),
        )

    if any(token in combined for token in ["中频结构不足", "中频结构偏弱", "材质体积不足", "结构丢失"]):
        strategy = replace(
            strategy,
            mid_frequency_restore_strength=_clamp(strategy.mid_frequency_restore_strength + 0.22),
            sharpen_strength=_clamp(strategy.sharpen_strength - 0.04),
            premium_style_target=_clamp(strategy.premium_style_target + 0.05),
        )

    if any(token in combined for token in ["高光", "假反射", "硬 HDR 光", "爆高光"]):
        strategy = replace(
            strategy,
            light_compression_strength=_clamp(strategy.light_compression_strength + 0.16),
            atmosphere_strength=_clamp(strategy.atmosphere_strength + 0.06),
        )

    if mode == "ppt_business":
        strategy = replace(
            strategy,
            sharpen_strength=_clamp(max(strategy.sharpen_strength, 0.16)),
            texture_cleanliness_target=_clamp(max(strategy.texture_cleanliness_target, 0.78)),
        )

    if mode == "cinematic":
        strategy = replace(
            strategy,
            atmosphere_strength=_clamp(strategy.atmosphere_strength + 0.18),
            light_compression_strength=_clamp(strategy.light_compression_strength + 0.1),
            sharpen_strength=_clamp(strategy.sharpen_strength - 0.08),
        )

    return strategy
