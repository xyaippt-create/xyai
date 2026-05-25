import cv2


def enhance_micro_contrast(image, amount: float):
    amount = max(0.0, min(1.0, amount))
    if amount <= 0:
        return image

    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.split(lab)

    clahe = cv2.createCLAHE(
        clipLimit=1.0 + amount * 1.6,
        tileGridSize=(8, 8),
    )
    lightness = clahe.apply(lightness)

    merged = cv2.merge((lightness, a, b))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
