import cv2


def upscale_to_width(image, target_width: int):
    height, width = image.shape[:2]
    if width >= target_width:
        return image

    scale = target_width / width
    target_height = int(round(height * scale))
    return cv2.resize(
        image,
        (target_width, target_height),
        interpolation=cv2.INTER_CUBIC,
    )
