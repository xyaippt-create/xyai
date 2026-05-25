import cv2


def apply_material_logic(image, material_weights: dict[str, float]):
    glass = material_weights.get("glass", 0.0)
    metal = material_weights.get("metal", 0.0)
    skin = material_weights.get("skin", 0.0)
    food = material_weights.get("food", 0.0)

    result = image

    if glass > 0:
        result = cv2.addWeighted(result, 1.0 + glass * 0.04, result, 0, 0)

    if metal > 0:
        blur = cv2.GaussianBlur(result, (0, 0), 0.8)
        result = cv2.addWeighted(result, 1.0 + metal * 0.08, blur, -metal * 0.08, 0)

    if skin > 0:
        result = cv2.bilateralFilter(result, 5, 12 + skin * 12, 12 + skin * 12)

    if food > 0:
        hsv = cv2.cvtColor(result, cv2.COLOR_BGR2HSV).astype("float32")
        hsv[:, :, 1] *= 1.0 + food * 0.05
        result = cv2.cvtColor(hsv.clip(0, 255).astype("uint8"), cv2.COLOR_HSV2BGR)

    return result
