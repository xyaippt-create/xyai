import cv2
import numpy as np


def edge_safe_sharpen(image, amount: float = 0.18, radius: float = 1.15):
    amount = max(0.0, min(float(amount), 1.0))
    if amount <= 0:
        return image

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 150)
    edge_mask = cv2.GaussianBlur(edges, (0, 0), 0.8).astype("float32") / 255.0
    edge_mask = edge_mask[:, :, None] * amount

    blur = cv2.GaussianBlur(image, (0, 0), radius)
    sharpened = cv2.addWeighted(image, 1.0 + amount * 0.55, blur, -amount * 0.55, 0)
    result = image.astype("float32") * (1.0 - edge_mask) + sharpened.astype("float32") * edge_mask
    return np.clip(result, 0, 255).astype("uint8")
