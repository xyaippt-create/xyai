import cv2
import numpy as np


def _resize_to_height(image, target_height: int):
    height, width = image.shape[:2]
    if height == target_height:
        return image
    target_width = int(round(width * target_height / height))
    return cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_AREA)


def build_compare_image(before, after):
    """Build a developer-only side-by-side comparison image."""

    target_height = min(before.shape[0], after.shape[0])
    left = _resize_to_height(before, target_height)
    right = _resize_to_height(after, target_height)
    divider = np.full((target_height, 8, 3), 28, dtype=np.uint8)
    return np.concatenate([left, divider, right], axis=1)
