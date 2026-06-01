import cv2
import numpy as np


def preserve_original_color(reference, processed, strength: float = 0.88):
    strength = max(0.0, min(float(strength), 1.0))
    if reference.shape[:2] != processed.shape[:2]:
        reference = cv2.resize(reference, (processed.shape[1], processed.shape[0]), interpolation=cv2.INTER_CUBIC)

    ref_lab = cv2.cvtColor(reference, cv2.COLOR_BGR2LAB).astype("float32")
    out_lab = cv2.cvtColor(processed, cv2.COLOR_BGR2LAB).astype("float32")
    out_lab[:, :, 1] = out_lab[:, :, 1] * (1.0 - strength) + ref_lab[:, :, 1] * strength
    out_lab[:, :, 2] = out_lab[:, :, 2] * (1.0 - strength) + ref_lab[:, :, 2] * strength
    return cv2.cvtColor(np.clip(out_lab, 0, 255).astype("uint8"), cv2.COLOR_LAB2BGR)


def lock_color_to_reference(reference, processed, chroma_strength: float = 0.96, luma_strength: float = 0.18):
    """Keep output close to the original color without flattening enhanced luminance details."""
    chroma_strength = float(np.clip(chroma_strength, 0.0, 1.0))
    luma_strength = float(np.clip(luma_strength, 0.0, 1.0))
    ref = reference
    if ref.shape[:2] != processed.shape[:2]:
        ref = cv2.resize(ref, (processed.shape[1], processed.shape[0]), interpolation=cv2.INTER_CUBIC)

    ref_lab = cv2.cvtColor(ref, cv2.COLOR_BGR2LAB).astype("float32")
    out_lab = cv2.cvtColor(processed, cv2.COLOR_BGR2LAB).astype("float32")

    for channel in (1, 2):
        ref_mean, ref_std = cv2.meanStdDev(ref_lab[:, :, channel])
        out_mean, out_std = cv2.meanStdDev(out_lab[:, :, channel])
        ref_mean = float(ref_mean[0][0])
        ref_std = max(float(ref_std[0][0]), 1.0)
        out_mean = float(out_mean[0][0])
        out_std = max(float(out_std[0][0]), 1.0)
        matched = (out_lab[:, :, channel] - out_mean) * (ref_std / out_std) + ref_mean
        out_lab[:, :, channel] = out_lab[:, :, channel] * (1.0 - chroma_strength) + matched * chroma_strength

    ref_l = ref_lab[:, :, 0]
    out_l = out_lab[:, :, 0]
    ref_mean = float(ref_l.mean())
    out_mean = float(out_l.mean())
    out_l = out_l + (ref_mean - out_mean) * luma_strength
    out_lab[:, :, 0] = np.clip(out_l, 0, 255)
    return cv2.cvtColor(np.clip(out_lab, 0, 255).astype("uint8"), cv2.COLOR_LAB2BGR)
