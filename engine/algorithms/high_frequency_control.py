import cv2


def control_high_frequency(image, sharpness: float, guard: float):
    sharpness = max(0.0, min(1.0, sharpness))
    guard = max(0.0, min(1.0, guard))
    if sharpness <= 0:
        return image

    blur = cv2.GaussianBlur(image, (0, 0), 1.0 + guard * 0.6)
    amount = min(0.35, sharpness * (1.0 - guard * 0.45))
    return cv2.addWeighted(image, 1.0 + amount, blur, -amount, 0)
