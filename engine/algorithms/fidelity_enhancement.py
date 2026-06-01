import cv2

from engine.analysis.image_type_detector import detect_image_type

from .color_fidelity import lock_color_to_reference
from .compression_repair import repair_compression_artifacts
from .edge_safe_enhance import enhance_true_edges
from .highlight_protection import compress_clipped_highlights, protect_highlights
from .structure_recovery import recover_structure
from .text_clarity import enhance_text_regions


def upscale_fidelity(image, scale: int = 2):
    scale = 4 if int(scale) == 4 else 2
    height, width = image.shape[:2]
    return cv2.resize(image, (width * scale, height * scale), interpolation=cv2.INTER_LANCZOS4)


def _mode_profile(mode: str, image_type: str) -> dict[str, float]:
    profile = {
        "repair": 0.22,
        "text": 0.34,
        "edge": 0.24,
        "structure": 0.24,
        "post_edge": 0.12,
        "highlight": 0.88,
    }
    if mode == "text_safe":
        profile.update({"repair": 0.18, "text": 0.56, "edge": 0.20, "structure": 0.20, "post_edge": 0.10})
    elif mode == "ai_image_clean":
        profile.update({"repair": 0.36, "text": 0.30, "edge": 0.17, "structure": 0.20, "post_edge": 0.08, "highlight": 0.92})
    elif mode == "sharp_4k":
        profile.update({"repair": 0.23, "text": 0.38, "edge": 0.34, "structure": 0.34, "post_edge": 0.18})

    if image_type == "text_poster":
        profile["text"] += 0.18
        profile["edge"] -= 0.04
    elif image_type == "architecture":
        profile["edge"] += 0.12
        profile["structure"] += 0.14
    elif image_type == "artifact":
        profile["highlight"] += 0.08
        profile["structure"] += 0.10
        profile["edge"] -= 0.04
    elif image_type == "portrait_indoor":
        profile["edge"] -= 0.10
        profile["structure"] -= 0.08
        profile["highlight"] += 0.08
    elif image_type == "ink_gray":
        profile["repair"] -= 0.08
        profile["edge"] -= 0.12
        profile["structure"] -= 0.10
        profile["post_edge"] -= 0.06

    return {key: max(0.0, min(float(value), 0.72 if key != "highlight" else 1.0)) for key, value in profile.items()}


def enhance_fidelity(image, mode: str = "fidelity", scale: int = 2):
    original = image
    image_type = detect_image_type(original).image_type
    profile = _mode_profile(mode, image_type)

    result = compress_clipped_highlights(original, amount=0.08)
    result = repair_compression_artifacts(result, profile["repair"])

    if mode == "text_safe" or image_type == "text_poster":
        result = enhance_text_regions(result, profile["text"])

    result = recover_structure(result, image_type=image_type, strength=profile["structure"])
    result = enhance_true_edges(result, strength=profile["edge"])
    result = protect_highlights(original, result, strength=profile["highlight"])

    result = upscale_fidelity(result, scale=scale)

    # Upscaling softens real contours; apply a restrained second pass only after enlargement.
    result = recover_structure(result, image_type=image_type, strength=profile["structure"] * 0.45)
    result = enhance_true_edges(result, strength=profile["post_edge"])
    if mode in {"text_safe", "sharp_4k"} or image_type == "text_poster":
        result = enhance_text_regions(result, profile["text"] * 0.82)

    result = protect_highlights(original, result, strength=profile["highlight"])
    return lock_color_to_reference(original, result, chroma_strength=0.97, luma_strength=0.10)
