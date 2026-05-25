from engine.config import EnhancementProfile


PROFILES = {
    "cosmetics": EnhancementProfile(
        name="cosmetics",
        description="Cosmetics, fragrance, skin care, glass bottle, premium product rendering.",
        output_suffix="_cosmetics_master",
        cleanup_strength=0.42,
        micro_contrast=0.28,
        sharpness=0.14,
        high_frequency_guard=0.72,
        material_weights={"glass": 0.8, "skin": 0.35},
        style_tags=("premium", "clean", "transparent"),
    ),
    "food": EnhancementProfile(
        name="food",
        description="Food commercial image with appetite, freshness, and controlled texture.",
        output_suffix="_food_master",
        cleanup_strength=0.28,
        micro_contrast=0.36,
        sharpness=0.18,
        high_frequency_guard=0.55,
        material_weights={"food": 0.85},
        style_tags=("fresh", "warm", "appetizing"),
    ),
    "architecture": EnhancementProfile(
        name="architecture",
        description="Architecture image with clean lines, atmosphere, and material clarity.",
        output_suffix="_architecture_master",
        cleanup_strength=0.32,
        micro_contrast=0.42,
        sharpness=0.22,
        high_frequency_guard=0.58,
        material_weights={"glass": 0.45, "metal": 0.45},
        style_tags=("cg", "clean", "spatial"),
    ),
    "cinematic": EnhancementProfile(
        name="cinematic",
        description="Cinematic air, soft contrast, controlled highlights, commercial mood.",
        output_suffix="_cinematic_master",
        cleanup_strength=0.38,
        micro_contrast=0.24,
        sharpness=0.08,
        high_frequency_guard=0.82,
        material_weights={},
        style_tags=("cinematic", "air", "soft"),
    ),
    "ppt_business": EnhancementProfile(
        name="ppt_business",
        description="PPT and business visual image with clarity, layout safety, and readable detail.",
        output_suffix="_ppt_business_master",
        cleanup_strength=0.25,
        micro_contrast=0.45,
        sharpness=0.20,
        high_frequency_guard=0.46,
        material_weights={},
        style_tags=("business", "ppt", "readable"),
    ),
    "ai_commercial_kv": EnhancementProfile(
        name="ai_commercial_kv",
        description="AI commercial key visual with premium CG texture and reduced AI dirt.",
        output_suffix="_commercial_kv_master",
        cleanup_strength=0.45,
        micro_contrast=0.32,
        sharpness=0.13,
        high_frequency_guard=0.75,
        material_weights={"glass": 0.35, "metal": 0.25},
        style_tags=("kv", "premium", "cg"),
    ),
    "portrait_commercial": EnhancementProfile(
        name="portrait_commercial",
        description="Commercial portrait, beauty portrait, and brand image photography.",
        output_suffix="_portrait_commercial_master",
        cleanup_strength=0.48,
        micro_contrast=0.22,
        sharpness=0.05,
        high_frequency_guard=0.86,
        material_weights={"skin": 0.8},
        style_tags=("portrait", "beauty", "soft_light", "clean_skin"),
    ),
    "luxury_product": EnhancementProfile(
        name="luxury_product",
        description="Luxury product, jewelry, watch, black-gold premium product visual.",
        output_suffix="_luxury_product_master",
        cleanup_strength=0.36,
        micro_contrast=0.34,
        sharpness=0.10,
        high_frequency_guard=0.76,
        material_weights={"glass": 0.55, "metal": 0.75},
        style_tags=("luxury", "reflection", "black_gold", "premium"),
    ),
}


def list_profiles() -> list[str]:
    return sorted(PROFILES)


def get_profile(name: str) -> EnhancementProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        available = ", ".join(list_profiles())
        raise ValueError(f"Unknown profile '{name}'. Available profiles: {available}") from exc
