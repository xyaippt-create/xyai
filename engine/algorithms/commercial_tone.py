import cv2


def apply_commercial_tone(image, warmth: float = 0.0, saturation: float = 0.0):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype("float32")
    hsv[:, :, 1] *= 1.0 + saturation
    hsv[:, :, 1] = hsv[:, :, 1].clip(0, 255)
    toned = cv2.cvtColor(hsv.astype("uint8"), cv2.COLOR_HSV2BGR)

    if warmth == 0:
        return toned

    b, g, r = cv2.split(toned.astype("float32"))
    r *= 1.0 + max(0.0, warmth)
    b *= 1.0 + max(0.0, -warmth)
    return cv2.merge((b.clip(0, 255), g, r.clip(0, 255))).astype("uint8")
