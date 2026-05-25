import cv2


def clean_ai_noise(image, strength: float):
    strength = max(0.0, min(1.0, strength))
    if strength <= 0:
        return image

    luminance_strength = 1 + int(strength * 5)
    color_strength = 1 + int(strength * 4)
    cleaned = cv2.fastNlMeansDenoisingColored(
        image,
        None,
        luminance_strength,
        color_strength,
        7,
        21,
    )

    if strength < 0.45:
        return cleaned

    return cv2.bilateralFilter(cleaned, 5, 18, 18)
