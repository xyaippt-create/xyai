from collections.abc import Callable

from engine.algorithms import (
    apply_commercial_tone,
    apply_material_logic,
    clean_ai_noise,
    control_high_frequency,
    enhance_micro_contrast,
    upscale_to_width,
)
from engine.config import EnhancementProfile


AlgorithmStep = tuple[str, Callable]


def build_algorithm_chain(profile: EnhancementProfile, rule_pack: dict) -> list[AlgorithmStep]:
    available_steps: dict[str, AlgorithmStep] = {
        "upscale": ("upscale", lambda image: upscale_to_width(image, profile.target_width)),
        "ai_noise_cleanup": ("ai_noise_cleanup", lambda image: clean_ai_noise(image, profile.cleanup_strength)),
        "material_logic": ("material_logic", lambda image: apply_material_logic(image, profile.material_weights)),
        "micro_contrast": ("micro_contrast", lambda image: enhance_micro_contrast(image, profile.micro_contrast)),
        "tone_control": ("commercial_tone", lambda image: apply_commercial_tone(image)),
        "high_frequency_control": (
            "high_frequency_control",
            lambda image: control_high_frequency(
                image,
                profile.sharpness,
                profile.high_frequency_guard,
            ),
        ),
    }

    if profile.name == "food":
        available_steps["tone_control"] = (
            "commercial_tone",
            lambda image: apply_commercial_tone(image, saturation=0.03),
        )

    if profile.name == "cinematic":
        available_steps["tone_control"] = (
            "commercial_tone",
            lambda image: apply_commercial_tone(image, warmth=0.01, saturation=-0.02),
        )

    pipeline_order = (
        rule_pack.get("pipeline_rules", {})
        .get("pipeline_order", [])
    )

    if not pipeline_order:
        pipeline_order = [
            "upscale",
            "ai_noise_cleanup",
            "material_logic",
            "micro_contrast",
            "tone_control",
            "high_frequency_control",
        ]

    chain: list[AlgorithmStep] = []
    for step_name in pipeline_order:
        if step_name == "material_logic" and profile.name not in {
            "cosmetics",
            "architecture",
            "food",
            "ai_commercial_kv",
        }:
            continue
        step = available_steps.get(step_name)
        if step:
            chain.append(step)

    return chain
