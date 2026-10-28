from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

import cv2 as cv
import numpy as np

from engine.local_retouch import lama_adapter


REPO = Path(__file__).resolve().parents[2]
S06_SOURCE = REPO / "artifacts/4k_stage1_baseline/golden_samples/S06__huawei.png"
S06_MASK = REPO / "output/local_retouch_neural_poc_20260810_120000/review_package/S06/mask.png"


def _read_image(path: Path, mode: int) -> np.ndarray:
    image = cv.imdecode(np.fromfile(path, dtype=np.uint8), mode)
    if image is None:
        raise AssertionError(f"cannot decode {path}")
    return image


def _boundary_added_jump_p90(source: np.ndarray, result: np.ndarray, mask: np.ndarray) -> float:
    inside = mask > 0
    added: list[float] = []
    for dy, dx in ((0, 1), (1, 0)):
        first_mask = inside[: inside.shape[0] - dy or None, : inside.shape[1] - dx or None]
        second_mask = inside[dy:, dx:]
        crossing = first_mask != second_mask
        source_first = source[: source.shape[0] - dy or None, : source.shape[1] - dx or None].astype(np.float32)
        source_second = source[dy:, dx:].astype(np.float32)
        result_first = result[: result.shape[0] - dy or None, : result.shape[1] - dx or None].astype(np.float32)
        result_second = result[dy:, dx:].astype(np.float32)
        source_jump = np.mean(np.abs(source_first - source_second), axis=2)[crossing]
        result_jump = np.mean(np.abs(result_first - result_second), axis=2)[crossing]
        added.extend(np.maximum(result_jump - source_jump, 0.0).tolist())
    return float(np.percentile(np.asarray(added, dtype=np.float32), 90))


def _component_core(mask: np.ndarray) -> np.ndarray:
    inside = mask > 0
    distance = cv.distanceTransform(mask, cv.DIST_L2, 5)
    labels_count, labels = cv.connectedComponents(inside.astype(np.uint8), 8)
    core = np.zeros_like(inside)
    for component_index in range(1, labels_count):
        component = labels == component_index
        contours, _ = cv.findContours(component.astype(np.uint8), cv.RETR_EXTERNAL, cv.CHAIN_APPROX_NONE)
        perimeter = sum(float(cv.arcLength(contour, True)) for contour in contours)
        band_width = min(
            max(1.0, float(np.count_nonzero(component)) / perimeter),
            float(distance[component].max()),
        )
        component_core = component & (distance >= band_width)
        if not np.any(component_core):
            component_core = component & (distance == distance[component].max())
        core |= component_core
    return core


def _composite(source: np.ndarray, candidate: np.ndarray, mask: np.ndarray) -> np.ndarray:
    compositor = getattr(lama_adapter, "_candidate_only_composite", None)
    if compositor is None:
        raise AssertionError("production candidate-only compositor is missing")
    return compositor(source, candidate, mask)


class CandidateOnlyCompositorTests(unittest.TestCase):
    def test_a_mask_outside_and_candidate_core_are_exact(self):
        source = np.full((48, 64, 3), 54, dtype=np.uint8)
        candidate = np.full_like(source, 132)
        mask = np.zeros(source.shape[:2], dtype=np.uint8)
        cv.rectangle(mask, (17, 11), (46, 36), 255, -1)

        result = _composite(source, candidate, mask)
        outside = mask == 0
        core = _component_core(mask)

        self.assertTrue(np.array_equal(result[outside], source[outside]))
        self.assertTrue(np.array_equal(result[core], candidate[core]))

    def test_b_source_defect_is_not_reintroduced(self):
        source = np.full((45, 55, 3), 72, dtype=np.uint8)
        candidate = np.full_like(source, 118)
        mask = np.zeros(source.shape[:2], dtype=np.uint8)
        cv.rectangle(mask, (15, 10), (39, 34), 255, -1)
        source[18:27, 23:32] = (20, 25, 235)

        result = _composite(source, candidate, mask)
        defect = np.zeros(mask.shape, dtype=bool)
        defect[18:27, 23:32] = True
        source_delta = source.astype(np.float32) - candidate.astype(np.float32)
        result_delta = result.astype(np.float32) - candidate.astype(np.float32)
        denominator = float(np.dot(source_delta[defect].ravel(), source_delta[defect].ravel()))
        source_projection = float(np.dot(source_delta[defect].ravel(), result_delta[defect].ravel()) / denominator)

        self.assertLess(abs(source_projection), 0.01)
        self.assertEqual(int(np.count_nonzero(result[defect, 2] > 160)), 0)

    def test_c_boundary_continuity_beats_binary_hard_composite(self):
        source = np.full((56, 72, 3), 48, dtype=np.uint8)
        candidate = np.full_like(source, 148)
        mask = np.zeros(source.shape[:2], dtype=np.uint8)
        cv.rectangle(mask, (18, 12), (53, 43), 255, -1)
        inside = mask > 0
        hard = source.copy()
        hard[inside] = candidate[inside]

        result = _composite(source, candidate, mask)

        self.assertGreater(_boundary_added_jump_p90(source, hard, mask), 90.0)
        self.assertLess(_boundary_added_jump_p90(source, result, mask), 2.0)

    def test_d_neutral_boundary_is_a_no_op(self):
        yy, xx = np.indices((52, 68), dtype=np.uint8)
        source = np.stack((60 + xx, 70 + yy, 80 + xx // 2), axis=2).astype(np.uint8)
        candidate = source.copy()
        mask = np.zeros(source.shape[:2], dtype=np.uint8)
        cv.rectangle(mask, (16, 12), (51, 39), 255, -1)
        core = _component_core(mask)
        candidate[core] = np.clip(candidate[core].astype(np.int16) + 12, 0, 255).astype(np.uint8)

        result = _composite(source, candidate, mask)

        expected = source.copy()
        expected[mask > 0] = candidate[mask > 0]
        self.assertTrue(np.array_equal(result, expected))

    def test_e_small_thin_and_irregular_masks_are_bounded(self):
        source = np.full((41, 47, 3), 64, dtype=np.uint8)
        candidate = np.full_like(source, 154)
        masks: list[np.ndarray] = []
        single = np.zeros(source.shape[:2], dtype=np.uint8)
        single[20, 23] = 255
        masks.append(single)
        thin = np.zeros_like(single)
        thin[7:35, 17] = 255
        masks.append(thin)
        irregular = np.zeros_like(single)
        cv.rectangle(irregular, (8, 8), (31, 13), 255, -1)
        cv.rectangle(irregular, (8, 8), (13, 32), 255, -1)
        cv.circle(irregular, (31, 28), 7, 255, -1)
        masks.append(irregular)

        for mask in masks:
            with self.subTest(mask_pixels=int(np.count_nonzero(mask))):
                result = _composite(source, candidate, mask)
                self.assertEqual(result.dtype, np.uint8)
                self.assertEqual(result.shape, source.shape)
                self.assertTrue(np.array_equal(result[mask == 0], source[mask == 0]))
                self.assertTrue(np.isfinite(result).all())

    def test_f_production_s06_removes_binary_hard_seam(self):
        self.assertTrue(lama_adapter.DEFAULT_MODEL_PATH.is_file(), "formal LaMa model is required")
        source_sha256 = hashlib.sha256(S06_SOURCE.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "s06-production.png"
            lama_adapter.LamaOnnxAdapter().process(S06_SOURCE, S06_MASK, output)
            source = _read_image(S06_SOURCE, cv.IMREAD_COLOR)
            mask = np.where(_read_image(S06_MASK, cv.IMREAD_GRAYSCALE) >= 128, 255, 0).astype(np.uint8)
            result = _read_image(output, cv.IMREAD_COLOR)

        self.assertEqual(hashlib.sha256(S06_SOURCE.read_bytes()).hexdigest(), source_sha256)
        self.assertEqual(int(np.max(np.abs(result.astype(np.int16) - source.astype(np.int16))[mask == 0])), 0)
        self.assertLess(_boundary_added_jump_p90(source, result, mask), 5.0)

    def test_g_disconnected_components_match_independent_repairs(self):
        yy, xx = np.indices((180, 320), dtype=np.uint16)
        source = np.stack((35 + xx // 3, 55 + yy // 2, 75 + xx // 4), axis=2).astype(np.uint8)
        candidate = np.clip(source.astype(np.int16) + (38, 27, 16), 0, 255).astype(np.uint8)
        first = np.zeros(source.shape[:2], dtype=np.uint8)
        second = np.zeros_like(first)
        cv.rectangle(first, (18, 24), (67, 82), 255, -1)
        cv.circle(second, (270, 132), 31, 255, -1)
        combined = cv.bitwise_or(first, second)

        combined_result = _composite(source, candidate, combined)
        independent_result = _composite(source, candidate, first)
        independent_result = _composite(independent_result, candidate, second)

        self.assertTrue(np.array_equal(combined_result, independent_result))
        self.assertTrue(np.array_equal(combined_result[combined == 0], source[combined == 0]))

    def test_h_large_harmonization_band_is_bounded_and_preserves_exact_outside(self):
        source = np.full((420, 560, 3), (62, 78, 96), dtype=np.uint8)
        candidate = np.full_like(source, (136, 142, 151))
        mask = np.zeros(source.shape[:2], dtype=np.uint8)
        cv.rectangle(mask, (80, 65), (480, 355), 255, -1)

        result = _composite(source, candidate, mask)

        self.assertTrue(np.array_equal(result[mask == 0], source[mask == 0]))
        self.assertTrue(np.array_equal(result[_component_core(mask)], candidate[_component_core(mask)]))
        self.assertLess(_boundary_added_jump_p90(source, result, mask), 3.0)


if __name__ == "__main__":
    unittest.main()
