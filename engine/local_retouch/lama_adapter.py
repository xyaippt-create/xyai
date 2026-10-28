from __future__ import annotations

import hashlib
import io
import math
import os
import threading
import time
from pathlib import Path

import cv2 as cv
import numpy as np
import onnxruntime as ort
from PIL import Image

from .contracts import LocalRetouchResult


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "local_retouch" / "inpainting_lama_2025jan.onnx"
EXPECTED_MODEL_SHA256 = "7df918ac3921d3daf0aae1d219776cf0dc4e4935f035af81841b40adcf74fdf2"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_image(path: Path, flags: int) -> np.ndarray | None:
    """Decode through bytes so Windows Unicode paths remain supported."""
    try:
        encoded = np.frombuffer(Path(path).read_bytes(), dtype=np.uint8)
    except OSError:
        return None
    return cv.imdecode(encoded, flags)


def _valid_dpi(value: object) -> tuple[float, float] | None:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        return None
    try:
        dpi = (float(value[0]), float(value[1]))
    except (TypeError, ValueError):
        return None
    return dpi if all(math.isfinite(item) and item > 0 for item in dpi) else None


def _read_dpi(path: Path) -> tuple[float, float] | None:
    try:
        with Image.open(path) as opened:
            return _valid_dpi(opened.info.get("dpi"))
    except OSError:
        return None


def _write_png(
    path: Path,
    image: np.ndarray,
    *,
    dpi: tuple[float, float] | None = None,
) -> dict[str, float]:
    encode_started = time.perf_counter()
    encoded, buffer = cv.imencode(".png", image)
    if not encoded:
        raise RuntimeError("修整结果编码失败。")
    output = buffer.tobytes()
    if dpi is not None:
        with Image.open(io.BytesIO(output)) as opened:
            opened.load()
            rewritten = io.BytesIO()
            opened.save(rewritten, format="PNG", dpi=dpi)
            output = rewritten.getvalue()
    encode_ms = (time.perf_counter() - encode_started) * 1000.0
    write_started = time.perf_counter()
    Path(path).write_bytes(output)
    return {
        "IMAGE_ENCODE_MS": encode_ms,
        "WRITE_MS": (time.perf_counter() - write_started) * 1000.0,
    }


def _context_box_from_bounds(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    def axis_bounds(start: int, end: int, limit: int) -> tuple[int, int]:
        selection_size = end - start
        context_size = min(limit, max(256, 4 * selection_size))
        center = (start + end) // 2
        first = max(0, min(limit - context_size, center - context_size // 2))
        return first, first + context_size

    left, right = axis_bounds(x1, x2, width)
    top, bottom = axis_bounds(y1, y2, height)
    return left, top, right, bottom


def _context_box(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.where(mask > 0)
    if xs.size == 0 or ys.size == 0:
        raise ValueError("修整选区为空。")
    return _context_box_from_bounds(
        int(xs.min()),
        int(ys.min()),
        int(xs.max()) + 1,
        int(ys.max()) + 1,
        mask.shape[1],
        mask.shape[0],
    )


def _region_plan(mask: np.ndarray) -> tuple[str, list[tuple[int, int, int, int]]]:
    """Plan independent model crops without changing the single-region path."""
    inside = (mask > 0).astype(np.uint8)
    ys, xs = np.where(inside > 0)
    if xs.size == 0 or ys.size == 0:
        raise ValueError("修整选区为空。")
    selection_left = int(xs.min())
    selection_top = int(ys.min())
    selection_right = int(xs.max()) + 1
    selection_bottom = int(ys.max()) + 1
    selection_crop = inside[selection_top:selection_bottom, selection_left:selection_right]
    labels_count, _labels, stats, _centroids = cv.connectedComponentsWithStats(selection_crop, 8)
    component_boxes: list[tuple[int, int, int, int]] = []
    for component_index in range(1, labels_count):
        component_left = selection_left + int(stats[component_index, cv.CC_STAT_LEFT])
        component_top = selection_top + int(stats[component_index, cv.CC_STAT_TOP])
        component_right = component_left + int(stats[component_index, cv.CC_STAT_WIDTH])
        component_bottom = component_top + int(stats[component_index, cv.CC_STAT_HEIGHT])
        component_boxes.append(
            _context_box_from_bounds(
                component_left,
                component_top,
                component_right,
                component_bottom,
                mask.shape[1],
                mask.shape[0],
            )
        )

    if not component_boxes:
        raise ValueError("修整选区为空。")

    # Context crops that overlap belong to one reconstruction neighbourhood.
    # Re-run merging until transitive overlaps have collapsed.
    merged = component_boxes
    changed = True
    while changed:
        changed = False
        next_boxes: list[tuple[int, int, int, int]] = []
        for box in merged:
            bx1, by1, bx2, by2 = box
            for index, existing in enumerate(next_boxes):
                ex1, ey1, ex2, ey2 = existing
                if bx1 < ex2 and bx2 > ex1 and by1 < ey2 and by2 > ey1:
                    next_boxes[index] = (
                        min(bx1, ex1),
                        min(by1, ey1),
                        max(bx2, ex2),
                        max(by2, ey2),
                    )
                    changed = True
                    break
            else:
                next_boxes.append(box)
        merged = next_boxes

    height, width = mask.shape
    full_box = (0, 0, width, height)
    if len(merged) == 1:
        return ("FULL" if merged[0] == full_box else "LOCAL"), merged

    combined_area = sum((x2 - x1) * (y2 - y1) for x1, y1, x2, y2 in merged)
    if combined_area >= int(width * height * 0.82):
        box = _context_box(mask)
        return ("FULL" if box == full_box else "LOCAL"), [box]
    return "MULTI_LOCAL", sorted(merged, key=lambda item: (item[1], item[0]))


def _letterbox_for_model(
    image: np.ndarray,
    mask: np.ndarray,
    size: int = 512,
) -> tuple[np.ndarray, np.ndarray, tuple[int, int, int, int]]:
    height, width = mask.shape
    scale = min(size / width, size / height)
    target_width = max(1, min(size, int(round(width * scale))))
    target_height = max(1, min(size, int(round(height * scale))))
    interpolation = cv.INTER_AREA if scale < 1.0 else cv.INTER_CUBIC
    resized = cv.resize(image, (target_width, target_height), interpolation=interpolation)
    resized_mask = cv.resize(mask, (target_width, target_height), interpolation=cv.INTER_NEAREST)
    left = (size - target_width) // 2
    right = size - target_width - left
    top = (size - target_height) // 2
    bottom = size - target_height - top
    model_image = cv.copyMakeBorder(resized, top, bottom, left, right, cv.BORDER_REFLECT_101)
    model_mask = cv.copyMakeBorder(resized_mask, top, bottom, left, right, cv.BORDER_CONSTANT, value=0)
    return model_image, model_mask, (left, top, target_width, target_height)


def _restore_letterboxed_output(
    model_output: np.ndarray,
    transform: tuple[int, int, int, int],
    width: int,
    height: int,
) -> np.ndarray:
    left, top, target_width, target_height = transform
    content = model_output[top : top + target_height, left : left + target_width]
    return cv.resize(content, (width, height), interpolation=cv.INTER_CUBIC)


def _ellipse_kernel(radius: int) -> np.ndarray:
    size = max(1, int(radius)) * 2 + 1
    return cv.getStructuringElement(cv.MORPH_ELLIPSE, (size, size))


def _mask_expansion_radius(mask: np.ndarray) -> int:
    ys, xs = np.where(mask > 0)
    if xs.size == 0 or ys.size == 0:
        raise ValueError("Empty retouch selection.")
    selection_scale = max(int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
    if selection_scale <= 64:
        return 4
    image_scale = max(mask.shape)
    radius = round(2.5 + selection_scale * 0.035 + min(1.5, image_scale * 0.001))
    return int(np.clip(radius, 4, 12))


def _expanded_mask(mask: np.ndarray) -> tuple[np.ndarray, int]:
    radius = _mask_expansion_radius(mask)
    expanded = cv.dilate(mask, _ellipse_kernel(radius), iterations=1)
    return np.where(expanded > 0, 255, 0).astype(np.uint8), radius


def _support_ring(mask: np.ndarray, radius: int, inner_radius: int = 0) -> np.ndarray:
    outer = cv.dilate(mask, _ellipse_kernel(radius), iterations=1)
    inner = cv.dilate(mask, _ellipse_kernel(inner_radius), iterations=1) if inner_radius > 0 else mask
    return (outer > 0) & (inner == 0)


def _gradient_magnitude(image: np.ndarray) -> np.ndarray:
    gray = cv.cvtColor(image, cv.COLOR_BGR2GRAY).astype(np.float32)
    gray = cv.GaussianBlur(gray, (0, 0), 1.0)
    gx = cv.Sobel(gray, cv.CV_32F, 1, 0, ksize=3)
    gy = cv.Sobel(gray, cv.CV_32F, 0, 1, ksize=3)
    return cv.magnitude(gx, gy)


def _match_boundary_color(source: np.ndarray, candidate: np.ndarray, mask: np.ndarray, radius: int) -> np.ndarray:
    ring = _support_ring(mask, max(10, radius * 2), inner_radius=max(2, radius // 2))
    if int(np.count_nonzero(ring)) < 32:
        return candidate
    difference = source.astype(np.float32) - candidate.astype(np.float32)
    offset = np.median(difference[ring], axis=0)
    offset = np.clip(offset, -12.0, 12.0)
    corrected = candidate.astype(np.float32) + offset.reshape(1, 1, 3)
    return np.clip(np.rint(corrected), 0, 255).astype(np.uint8)


def _surface_features(xs: np.ndarray, ys: np.ndarray, width: int, height: int) -> np.ndarray:
    nx = (xs.astype(np.float32) - (width - 1) * 0.5) / max(1.0, width * 0.5)
    ny = (ys.astype(np.float32) - (height - 1) * 0.5) / max(1.0, height * 0.5)
    return np.column_stack((np.ones_like(nx), nx, ny, nx * ny, nx * nx, ny * ny))


def _has_long_structure(source: np.ndarray, mask: np.ndarray) -> bool:
    """Keep long card borders and rules on the structure-preserving inpaint path."""
    ys, xs = np.where(mask > 0)
    if xs.size == 0 or ys.size == 0:
        return False
    selection_width = int(xs.max() - xs.min() + 1)
    selection_height = int(ys.max() - ys.min() + 1)
    selection_scale = max(selection_width, selection_height)
    small_selection = selection_scale <= 96
    minimum_length = (
        max(24, int(selection_scale * 0.75))
        if small_selection
        else max(56, int(selection_scale * 0.42))
    )
    maximum_gap = (
        min(48, max(16, int(selection_scale * 0.50)))
        if small_selection
        else min(48, max(12, minimum_length // 3))
    )
    gray = cv.cvtColor(source, cv.COLOR_BGR2GRAY)
    edges = cv.Canny(cv.GaussianBlur(gray, (0, 0), 0.8), 30, 90)
    lines = cv.HoughLinesP(
        edges,
        1,
        np.pi / 180.0,
        threshold=max(12 if small_selection else 28, minimum_length // 4),
        minLineLength=minimum_length,
        maxLineGap=maximum_gap,
    )
    if lines is None:
        return False
    mask_left, mask_right = int(xs.min()), int(xs.max())
    mask_top, mask_bottom = int(ys.min()), int(ys.max())
    for line in lines[:, 0]:
        x1, y1, x2, y2 = (int(value) for value in line)
        # A preservable rule must continue through the selection from both
        # sides.  A glyph stroke with only one endpoint outside the mask is
        # part of the selected target, not background structure to retain.
        if mask[y1, x1] > 0 or mask[y2, x2] > 0:
            continue
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        if dx >= dy:
            crosses_selection = (
                dy <= max(3, int(dx * 0.35))
                and min(x1, x2) < mask_left
                and max(x1, x2) > mask_right
            )
        else:
            crosses_selection = (
                dx <= max(3, int(dy * 0.35))
                and min(y1, y2) < mask_top
                and max(y1, y2) > mask_bottom
            )
        if not crosses_selection:
            continue
        line_mask = np.zeros_like(mask)
        cv.line(line_mask, (x1, y1), (x2, y2), 255, 3, cv.LINE_AA)
        if int(np.count_nonzero((line_mask > 0) & (mask > 0))) >= 8:
            return True
    return False


def _simple_background_surface(
    source: np.ndarray,
    mask: np.ndarray,
    radius: int,
    write_mask: np.ndarray | None = None,
) -> tuple[np.ndarray | None, float, np.ndarray | None]:
    """Fit a local quadratic color surface only when the surrounding area is simple."""
    ring = _support_ring(
        mask,
        int(np.clip(radius * 4 + 16, 28, 72)),
        inner_radius=max(3, radius),
    )
    gradient = _gradient_magnitude(source)
    ring_values = gradient[ring]
    if ring_values.size < 96:
        return None, 0.0, None

    gradient_p90 = float(np.percentile(ring_values, 90))
    ys_mask, xs_mask = np.where(mask > 0)
    selection_scale = max(
        int(xs_mask.max() - xs_mask.min() + 1),
        int(ys_mask.max() - ys_mask.min() + 1),
    )
    if _has_long_structure(source, mask) or (96 < selection_scale <= 256 and gradient_p90 > 60.0):
        return None, 0.0, None

    low_gradient_limit = max(10.0, float(np.percentile(ring_values, 60)))
    samples = ring & (gradient <= low_gradient_limit)
    ys, xs = np.where(samples)
    if xs.size < 72:
        return None, 0.0, None
    large_surface = selection_scale > 256
    if large_surface:
        sample_values = source[ys, xs].astype(np.float32)
        background_center = np.median(sample_values, axis=0)
        color_distance = np.linalg.norm(sample_values - background_center, axis=1)
        distance_median = float(np.median(color_distance))
        distance_mad = float(np.median(np.abs(color_distance - distance_median)))
        color_limit = float(np.clip(
            distance_median + max(10.0, distance_mad * 3.5),
            14.0,
            32.0,
        ))
        color_reliable = color_distance <= color_limit
        mask_left, mask_right = int(xs_mask.min()), int(xs_mask.max())
        mask_top, mask_bottom = int(ys_mask.min()), int(ys_mask.max())
        side_membership = (
            ys < mask_top,
            ys > mask_bottom,
            xs < mask_left,
            xs > mask_right,
        )
        reliable_sides = np.zeros_like(color_reliable)
        reliable_side_count = 0
        for side in side_membership:
            side_count = int(np.count_nonzero(side))
            if side_count < 24 or float(np.mean(color_reliable[side])) < 0.55:
                continue
            reliable_sides |= side
            reliable_side_count += 1
        if reliable_side_count < 2:
            return None, 0.0, None
        reliable = color_reliable & reliable_sides
        ys, xs = ys[reliable], xs[reliable]
        if xs.size < 72:
            return None, 0.0, None
    if xs.size > 10000:
        take = np.linspace(0, xs.size - 1, 10000, dtype=np.int32)
        xs, ys = xs[take], ys[take]

    design = _surface_features(xs, ys, source.shape[1], source.shape[0])
    values = source[ys, xs].astype(np.float32)
    coefficients, *_ = np.linalg.lstsq(design, values, rcond=None)
    for _ in range(2):
        residual = np.linalg.norm(values - design @ coefficients, axis=1)
        keep = residual <= max(6.0, float(np.percentile(residual, 75)))
        if int(np.count_nonzero(keep)) < 64:
            break
        design = design[keep]
        values = values[keep]
        coefficients, *_ = np.linalg.lstsq(design, values, rcond=None)

    residual = np.linalg.norm(values - design @ coefficients, axis=1)
    residual_p85 = float(np.percentile(residual, 85))
    ring_ys, ring_xs = np.where(ring)
    ring_design = _surface_features(ring_xs, ring_ys, source.shape[1], source.shape[0])
    ring_residual = np.linalg.norm(
        source[ring_ys, ring_xs].astype(np.float32) - ring_design @ coefficients,
        axis=1,
    )
    smooth_support_ratio = float(np.mean(ring_residual <= 12.0))
    minimum_support = 0.75 if selection_scale <= 96 else 0.50
    if residual_p85 > 8.0 or smooth_support_ratio < minimum_support:
        return None, 0.0, None

    target_ys, target_xs = np.where(mask > 0)
    target_design = _surface_features(target_xs, target_ys, source.shape[1], source.shape[0])
    raw_target_surface = target_design @ coefficients
    local_values = values if large_surface else source[ring].astype(np.float32)
    range_margin = 8.0 if large_surface else 12.0
    lower = np.percentile(local_values, 1, axis=0) - range_margin
    upper = np.percentile(local_values, 99, axis=0) + range_margin
    if large_surface:
        range_excess = np.maximum(lower.reshape(1, 3) - raw_target_surface, 0.0)
        range_excess += np.maximum(raw_target_surface - upper.reshape(1, 3), 0.0)
        excess_magnitude = np.linalg.norm(range_excess, axis=1)
        if (
            float(np.percentile(excess_magnitude, 99)) > 18.0
            or float(np.mean(excess_magnitude > 0.0)) > 0.15
        ):
            return None, 0.0, None
    target_surface = np.clip(raw_target_surface, lower.reshape(1, 3), upper.reshape(1, 3))

    target_residual = np.linalg.norm(
        source[target_ys, target_xs].astype(np.float32) - target_surface,
        axis=1,
    )
    defect_threshold = max(14.0, residual_p85 * 2.5)
    defect_mask = np.zeros_like(mask)
    defective = target_residual > defect_threshold
    defect_mask[target_ys[defective], target_xs[defective]] = 255
    if int(np.count_nonzero(defect_mask)) < 12:
        return None, 0.0, None
    # Once the surrounding surface is proven simple and the selected target
    # differs from it, fill the complete repair selection.  Limiting the fill
    # to the detected high-residual pixels leaves glyph fragments behind.
    repair_mask = np.where(mask > 0, 255, 0).astype(np.uint8)

    prediction = source.copy()
    prediction[target_ys, target_xs] = np.clip(np.rint(target_surface), 0, 255).astype(np.uint8)
    surface = source.copy()
    surface[repair_mask > 0] = prediction[repair_mask > 0]
    if large_surface and write_mask is not None:
        user_mask = np.where(write_mask > 0, 255, 0).astype(np.uint8)
        if user_mask.shape != mask.shape:
            return None, 0.0, None
        distance = cv.distanceTransform(user_mask, cv.DIST_L2, 5)
        blend_weight = np.clip(distance / max(1.0, radius * 3.0), 0.0, 1.0)
        defective_map = cv.dilate(
            defect_mask,
            _ellipse_kernel(max(2, radius)),
            iterations=1,
        ) > 0
        blend_weight[defective_map] = 1.0
        blended_surface = (
            source.astype(np.float32) * (1.0 - blend_weight[:, :, None])
            + prediction.astype(np.float32) * blend_weight[:, :, None]
        )
        surface = np.clip(np.rint(blended_surface), 0, 255).astype(np.uint8)
        user_edge = (user_mask > 0) & (distance <= max(3.0, radius * 1.5)) & ~defective_map
        if int(np.count_nonzero(user_edge)) >= 32:
            edge_delta = np.abs(surface.astype(np.float32) - source.astype(np.float32))[user_edge]
            edge_luminance_delta = np.abs(
                edge_delta @ np.array([0.114, 0.587, 0.299], dtype=np.float32)
            )
            if (
                float(np.percentile(np.linalg.norm(edge_delta, axis=1), 90)) > 16.0
                or float(np.percentile(edge_luminance_delta, 90)) > 8.0
            ):
                return None, 0.0, None
        repair_mask = user_mask
    confidence = float(np.clip(
        0.45 + (8.0 - residual_p85) * 0.055 + (smooth_support_ratio - minimum_support) * 0.8,
        0.35,
        1.0,
    ))
    return surface, confidence, repair_mask


def _restore_simple_structure(
    source: np.ndarray,
    neural: np.ndarray,
    mask: np.ndarray,
    radius: int,
) -> np.ndarray:
    """Conservatively carry thin, locally continuous edges through the repair area."""
    ring = _support_ring(mask, max(12, radius * 3), inner_radius=max(3, radius))
    source_gradient = _gradient_magnitude(source)
    if int(np.count_nonzero(ring)) < 64 or float(np.mean(source_gradient[ring] > 18.0)) < 0.004:
        return neural
    classical = cv.inpaint(source, mask, float(np.clip(radius, 2, 6)), cv.INPAINT_NS)
    classical_gradient = _gradient_magnitude(classical)
    threshold = max(14.0, float(np.percentile(source_gradient[ring], 65)))
    structure = ((classical_gradient >= threshold) & (mask > 0)).astype(np.float32)
    structure = cv.GaussianBlur(structure, (0, 0), 0.8)
    weight = np.clip(structure * 0.45, 0.0, 0.45)[:, :, None]
    restored = neural.astype(np.float32) * (1.0 - weight) + classical.astype(np.float32) * weight
    return np.clip(np.rint(restored), 0, 255).astype(np.uint8)


def _candidate_harmonization_band_width(component: np.ndarray) -> float:
    area = float(np.count_nonzero(component))
    contours, _ = cv.findContours(component.astype(np.uint8), cv.RETR_EXTERNAL, cv.CHAIN_APPROX_NONE)
    perimeter = sum(float(cv.arcLength(contour, True)) for contour in contours)
    if perimeter <= 0.0:
        return 1.0
    return max(1.0, area / perimeter)


def _solve_correction_band(
    field: np.ndarray,
    unknown: np.ndarray,
) -> np.ndarray:
    unknown_pixels = int(np.count_nonzero(unknown))
    if unknown_pixels == 0:
        return field
    if unknown_pixels <= 16_384:
        neighbour_kernel = np.asarray(
            [[0.0, 0.25, 0.0], [0.25, 0.0, 0.25], [0.0, 0.25, 0.0]],
            dtype=np.float32,
        )
        for _ in range(2000):
            averaged = cv.filter2D(
                field,
                cv.CV_32F,
                neighbour_kernel,
                borderType=cv.BORDER_REPLICATE,
            )
            change = float(np.max(np.abs(averaged[unknown] - field[unknown])))
            field[unknown] = averaged[unknown]
            if change < 1e-4:
                break
        return field

    inpaint_mask = np.where(unknown, 255, 0).astype(np.uint8)
    solved = field.copy()
    for channel in range(field.shape[2]):
        channel_result = cv.inpaint(field[:, :, channel], inpaint_mask, 3.0, cv.INPAINT_NS)
        solved[:, :, channel][unknown] = channel_result[unknown]
    return solved


def _candidate_only_composite(
    source: np.ndarray,
    candidate: np.ndarray,
    mask: np.ndarray,
    *,
    expansion_radius: int | None = None,
) -> np.ndarray:
    inside = mask > 0
    if not np.any(inside):
        return source.copy()
    resolved_expansion_radius = (
        _mask_expansion_radius(mask)
        if expansion_radius is None
        else max(1, int(expansion_radius))
    )
    result = source.copy()
    labels_count, labels, stats, _centroids = cv.connectedComponentsWithStats(
        inside.astype(np.uint8),
        8,
    )
    for component_index in range(1, labels_count):
        component_left = int(stats[component_index, cv.CC_STAT_LEFT])
        component_top = int(stats[component_index, cv.CC_STAT_TOP])
        component_width = int(stats[component_index, cv.CC_STAT_WIDTH])
        component_height = int(stats[component_index, cv.CC_STAT_HEIGHT])
        x1 = max(0, component_left - 1)
        y1 = max(0, component_top - 1)
        x2 = min(mask.shape[1], component_left + component_width + 1)
        y2 = min(mask.shape[0], component_top + component_height + 1)
        component_mask = np.where(
            labels[y1:y2, x1:x2] == component_index,
            255,
            0,
        ).astype(np.uint8)
        region = _candidate_only_composite_region(
            source[y1:y2, x1:x2],
            candidate[y1:y2, x1:x2],
            component_mask,
            expansion_radius=resolved_expansion_radius,
        )
        component_inside = component_mask > 0
        result_crop = result[y1:y2, x1:x2]
        result_crop[component_inside] = region[component_inside]
    return result


def _candidate_only_composite_region(
    source: np.ndarray,
    candidate: np.ndarray,
    mask: np.ndarray,
    *,
    expansion_radius: int,
) -> np.ndarray:
    inside = mask > 0
    if not np.any(inside):
        return source.copy()

    source_lab = cv.cvtColor(source.astype(np.float32) / 255.0, cv.COLOR_BGR2LAB)
    candidate_lab = cv.cvtColor(candidate.astype(np.float32) / 255.0, cv.COLOR_BGR2LAB)
    outside_delta = (source_lab - candidate_lab) * (~inside)[:, :, None]
    distance = cv.distanceTransform(mask, cv.DIST_L2, 5)
    safe_interior_radius = max(1, int(expansion_radius))
    labels_count, labels = cv.connectedComponents(inside.astype(np.uint8), 8)
    correction = np.zeros_like(candidate_lab, dtype=np.float32)
    candidate_core = np.zeros_like(inside)
    neighbour_kernel = np.asarray(
        [[0.0, 0.25, 0.0], [0.25, 0.0, 0.25], [0.0, 0.25, 0.0]],
        dtype=np.float32,
    )

    for component_index in range(1, labels_count):
        component = labels == component_index
        # The outside boundary is only a safe harmonization reference when the
        # component has an interior deeper than the mask expansion used to
        # build the candidate. Thin glyphs have no such interior; propagating
        # their surrounding source delta would restore the removed glow.
        if float(distance[component].max()) <= float(safe_interior_radius):
            candidate_core |= component
            continue
        band_width = min(
            _candidate_harmonization_band_width(component),
            float(distance[component].max()),
        )
        component_core = component & (distance >= band_width)
        if not np.any(component_core):
            component_core = component & (distance == distance[component].max())
        component_band = component & ~component_core
        candidate_core |= component_core

        ys, xs = np.where(component)
        x1 = max(0, int(xs.min()) - 1)
        y1 = max(0, int(ys.min()) - 1)
        x2 = min(mask.shape[1], int(xs.max()) + 2)
        y2 = min(mask.shape[0], int(ys.max()) + 2)
        crop_component = component[y1:y2, x1:x2]
        crop_core = component_core[y1:y2, x1:x2]
        field = outside_delta[y1:y2, x1:x2].copy()
        field[crop_component] = 0.0
        field[crop_core] = 0.0

        crop_outside = (~crop_component).astype(np.float32)
        outside_neighbour_count = cv.filter2D(
            crop_outside,
            cv.CV_32F,
            neighbour_kernel,
            borderType=cv.BORDER_CONSTANT,
        )
        outside_neighbour_sum = cv.filter2D(
            outside_delta[y1:y2, x1:x2],
            cv.CV_32F,
            neighbour_kernel,
            borderType=cv.BORDER_CONSTANT,
        )
        crop_seam = crop_component & (outside_neighbour_count > 0.0)
        field[crop_seam] = outside_neighbour_sum[crop_seam] / outside_neighbour_count[crop_seam, None]
        crop_unknown = component_band[y1:y2, x1:x2] & ~crop_seam

        field = _solve_correction_band(field, crop_unknown)

        correction_crop = correction[y1:y2, x1:x2]
        correction_crop[crop_component] = field[crop_component]

    corrected_lab = candidate_lab + correction
    corrected_lab[:, :, 0] = np.clip(corrected_lab[:, :, 0], 0.0, 100.0)
    corrected_lab[:, :, 1:] = np.clip(corrected_lab[:, :, 1:], -127.0, 127.0)
    corrected = cv.cvtColor(corrected_lab, cv.COLOR_LAB2BGR)
    corrected = np.rint(np.clip(corrected, 0.0, 1.0) * 255.0).astype(np.uint8)

    result = source.copy()
    result[inside] = corrected[inside]
    zero_correction = inside & np.all(correction == 0.0, axis=2)
    result[zero_correction] = candidate[zero_correction]
    result[candidate_core] = candidate[candidate_core]
    result[~inside] = source[~inside]
    return result


class LamaOnnxAdapter:
    """LaMa-specific runtime hidden behind the product-level retouch contract."""

    engine_id = "lama_onnx_2025jan"

    def __init__(self, model_path: Path | None = None) -> None:
        self.model_path = Path(model_path or DEFAULT_MODEL_PATH).resolve()
        self._session: ort.InferenceSession | None = None
        self._session_lock = threading.Lock()
        self._model_sha256: str | None = None
        self._last_timings_ms: dict[str, float | str] = {}

    @property
    def last_timings_ms(self) -> dict[str, float | str]:
        return dict(self._last_timings_ms)

    def availability(self) -> dict[str, object]:
        if not self.model_path.is_file():
            return {"available": False, "engine_id": self.engine_id, "reason": "本地修整模型尚未就绪。"}
        actual_sha = self._model_sha256 or _sha256(self.model_path)
        self._model_sha256 = actual_sha
        if actual_sha != EXPECTED_MODEL_SHA256:
            return {"available": False, "engine_id": self.engine_id, "reason": "本地修整模型完整性校验失败。"}
        return {
            "available": True,
            "engine_id": self.engine_id,
            "runtime": f"onnxruntime {ort.__version__}",
            "provider": "CPUExecutionProvider",
            "model_sha256": actual_sha,
        }

    def _require_session(self) -> ort.InferenceSession:
        available = self.availability()
        if not available["available"]:
            raise RuntimeError(str(available["reason"]))
        with self._session_lock:
            if self._session is None:
                options = ort.SessionOptions()
                options.log_severity_level = 3
                options.intra_op_num_threads = max(1, min(8, os.cpu_count() or 1))
                self._session = ort.InferenceSession(
                    str(self.model_path),
                    sess_options=options,
                    providers=["CPUExecutionProvider"],
                )
        return self._session

    def _candidate_for_box(
        self,
        color: np.ndarray,
        user_mask: np.ndarray,
        model_mask: np.ndarray,
        box: tuple[int, int, int, int],
        expansion_radius: int,
    ) -> tuple[np.ndarray, str, float, dict[str, float]]:
        x1, y1, x2, y2 = box
        patch = color[y1:y2, x1:x2]
        patch_model_mask = model_mask[y1:y2, x1:x2]
        patch_user_mask = user_mask[y1:y2, x1:x2]
        measured = {
            "REGION_PREPARE_MS": 0.0,
            "MODEL_INPUT_PREPARE_MS": 0.0,
            "MODEL_INIT_MS": 0.0,
            "MODEL_INFERENCE_MS": 0.0,
            "POSTPROCESS_MS": 0.0,
        }

        analysis_started = time.perf_counter()
        surface, _surface_confidence, surface_mask = _simple_background_surface(
            patch,
            patch_model_mask,
            expansion_radius,
            patch_user_mask,
        )
        measured["REGION_PREPARE_MS"] = (time.perf_counter() - analysis_started) * 1000.0
        if surface is not None:
            postprocess_started = time.perf_counter()
            surface_ys, surface_xs = np.where(surface_mask > 0)
            clone_center = (
                (int(surface_xs.min()) + int(surface_xs.max())) // 2,
                (int(surface_ys.min()) + int(surface_ys.max())) // 2,
            )
            surface_scale = max(
                int(surface_xs.max() - surface_xs.min() + 1),
                int(surface_ys.max() - surface_ys.min() + 1),
            )
            candidate_patch = surface
            if 96 < surface_scale <= 256:
                surface_full = color.copy()
                surface_full[y1:y2, x1:x2] = surface
                surface_mask_full = np.zeros_like(model_mask)
                surface_mask_full[y1:y2, x1:x2] = surface_mask
                try:
                    seamless = cv.seamlessClone(
                        surface_full,
                        color,
                        surface_mask_full,
                        (clone_center[0] + x1, clone_center[1] + y1),
                        cv.NORMAL_CLONE,
                    )
                    candidate_patch = seamless[y1:y2, x1:x2]
                except cv.error:
                    pass
            measured["POSTPROCESS_MS"] = (time.perf_counter() - postprocess_started) * 1000.0
            return candidate_patch, "SURFACE", 0.0, measured

        input_started = time.perf_counter()
        resized, resized_mask, letterbox_transform = _letterbox_for_model(patch, patch_user_mask)
        image_blob = resized.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
        mask_blob = (resized_mask[None, None] > 0).astype(np.float32)
        measured["MODEL_INPUT_PREPARE_MS"] = (time.perf_counter() - input_started) * 1000.0
        model_init_started = time.perf_counter()
        session = self._require_session()
        measured["MODEL_INIT_MS"] = (time.perf_counter() - model_init_started) * 1000.0
        inference_started = time.perf_counter()
        raw = session.run(None, {"image": image_blob, "mask": mask_blob})[0]
        inference_seconds = time.perf_counter() - inference_started
        measured["MODEL_INFERENCE_MS"] = inference_seconds * 1000.0
        postprocess_started = time.perf_counter()
        candidate_patch = np.clip(raw[0].transpose(1, 2, 0), 0, 255).astype(np.uint8)
        candidate_patch = _restore_letterboxed_output(
            candidate_patch,
            letterbox_transform,
            x2 - x1,
            y2 - y1,
        )
        candidate_patch = _match_boundary_color(
            patch,
            candidate_patch,
            patch_model_mask,
            expansion_radius,
        )
        measured["POSTPROCESS_MS"] = (time.perf_counter() - postprocess_started) * 1000.0
        return candidate_patch, "LAMA", inference_seconds, measured

    def process(self, source_path: Path, mask_path: Path, output_path: Path) -> LocalRetouchResult:
        total_started = time.perf_counter()
        timings: dict[str, float | str] = {
            "TOTAL_MS": 0.0,
            "IMAGE_DECODE_MS": 0.0,
            "MODEL_CHECK_MS": 0.0,
            "MODEL_INIT_MS": 0.0,
            "MASK_PREPARE_MS": 0.0,
            "REGION_PREPARE_MS": 0.0,
            "MODEL_INPUT_PREPARE_MS": 0.0,
            "MODEL_INFERENCE_MS": 0.0,
            "POSTPROCESS_MS": 0.0,
            "COMPOSITE_MS": 0.0,
            "IMAGE_ENCODE_MS": 0.0,
            "WRITE_MS": 0.0,
            "VERIFY_MS": 0.0,
            "INTEGRITY_MS": 0.0,
            "REGION_ROUTE": "UNKNOWN",
            "CANDIDATE_ROUTE": "UNKNOWN",
        }
        source_path = Path(source_path).resolve()
        mask_path = Path(mask_path).resolve()
        output_path = Path(output_path).resolve()

        decode_started = time.perf_counter()
        source_dpi = _read_dpi(source_path)
        source = _read_image(source_path, cv.IMREAD_UNCHANGED)
        timings["IMAGE_DECODE_MS"] = (time.perf_counter() - decode_started) * 1000.0

        mask_started = time.perf_counter()
        mask = _read_image(mask_path, cv.IMREAD_GRAYSCALE)
        if source is None or mask is None:
            raise ValueError("无法读取当前工作图或修整选区。")
        if source.shape[:2] != mask.shape[:2]:
            raise ValueError("修整选区尺寸与当前工作图不一致。")
        mask = np.where(mask >= 128, 255, 0).astype(np.uint8)
        mask_pixels = int(np.count_nonzero(mask))
        if mask_pixels == 0:
            raise ValueError("请先在图片上标记需要修整的区域。")
        model_mask, expansion_radius = _expanded_mask(mask)
        timings["MASK_PREPARE_MS"] = (time.perf_counter() - mask_started) * 1000.0

        prepare_started = time.perf_counter()
        if source.ndim == 2:
            color = cv.cvtColor(source, cv.COLOR_GRAY2BGR)
            alpha_channel = None
        elif source.shape[2] == 4:
            color = source[:, :, :3].copy()
            alpha_channel = source[:, :, 3].copy()
        else:
            color = source[:, :, :3].copy()
            alpha_channel = None

        region_route, region_boxes = _region_plan(model_mask)
        timings["REGION_ROUTE"] = region_route
        timings["REGION_PREPARE_MS"] = (time.perf_counter() - prepare_started) * 1000.0

        model_check_started = time.perf_counter()
        available = self.availability()
        timings["MODEL_CHECK_MS"] = (time.perf_counter() - model_check_started) * 1000.0
        if not available["available"]:
            raise RuntimeError(str(available["reason"]))
        blended = color.copy()
        inference_seconds = 0.0
        candidate_routes: list[str] = []
        for box in region_boxes:
            x1, y1, x2, y2 = box
            candidate_patch, candidate_route, region_inference_seconds, measured = (
                self._candidate_for_box(
                    color,
                    mask,
                    model_mask,
                    box,
                    expansion_radius,
                )
            )
            candidate_routes.append(candidate_route)
            inference_seconds += region_inference_seconds
            for timing_key, timing_value in measured.items():
                timings[timing_key] = float(timings[timing_key]) + timing_value

            composite_started = time.perf_counter()
            blended[y1:y2, x1:x2] = _candidate_only_composite(
                blended[y1:y2, x1:x2],
                candidate_patch,
                mask[y1:y2, x1:x2],
                expansion_radius=expansion_radius,
            )
            timings["COMPOSITE_MS"] = float(timings["COMPOSITE_MS"]) + (
                time.perf_counter() - composite_started
            ) * 1000.0
        timings["CANDIDATE_ROUTE"] = (
            candidate_routes[0]
            if len(set(candidate_routes)) == 1
            else "MIXED"
        )

        final = cv.merge((*cv.split(blended), alpha_channel)) if alpha_channel is not None else blended
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_name(f".{output_path.stem}.writing{output_path.suffix}")
        if temporary.exists():
            temporary.unlink()
        write_timings = _write_png(temporary, final, dpi=source_dpi)
        timings.update(write_timings)
        verify_started = time.perf_counter()
        try:
            with Image.open(temporary) as opened:
                opened.load()
                if opened.size != (source.shape[1], source.shape[0]):
                    raise RuntimeError("修整结果尺寸验证失败。")
            os.replace(temporary, output_path)
        finally:
            temporary.unlink(missing_ok=True)
        timings["VERIFY_MS"] = (time.perf_counter() - verify_started) * 1000.0

        integrity_started = time.perf_counter()
        source_sha256 = _sha256(source_path)
        timings["INTEGRITY_MS"] = (time.perf_counter() - integrity_started) * 1000.0
        timings["TOTAL_MS"] = (time.perf_counter() - total_started) * 1000.0
        self._last_timings_ms = {
            key: round(value, 3) if isinstance(value, float) else value
            for key, value in timings.items()
        }

        return LocalRetouchResult(
            engine_id=self.engine_id,
            output_path=output_path,
            width=source.shape[1],
            height=source.shape[0],
            format="PNG",
            mask_pixels=mask_pixels,
            inference_seconds=round(inference_seconds, 4),
            source_sha256=source_sha256,
        )
