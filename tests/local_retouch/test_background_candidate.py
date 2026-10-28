from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2 as cv
import numpy as np

from engine.local_retouch import lama_adapter as lama


class BackgroundCandidateTests(unittest.TestCase):
    def test_valid_neural_structure_is_not_repainted_by_classical_inpaint(self):
        # A known-correct model return isolates post-processing from model quality.
        for diagonal in (False, True):
            with self.subTest(diagonal=diagonal), tempfile.TemporaryDirectory() as temporary:
                clean = np.full((128, 128, 3), 190, np.uint8)
                clean[:, 60:] = (90, 50, 30)
                cv.line(clean, (64, 5), (64, 122), (18, 18, 18), 3)
                if diagonal:
                    cv.line(clean, (65, 30), (100, 100), (230, 190, 120), 2)
                mask = np.zeros(clean.shape[:2], np.uint8)
                mask[38:92, 52:79] = 255
                source = clean.copy()
                source[55:70, 58:69] = (10, 10, 245)
                expanded, radius = lama._expanded_mask(mask)
                model_clean, _, transform = lama._letterbox_for_model(clean, mask)
                mapped = lama._restore_letterboxed_output(model_clean, transform, 128, 128)
                expected_candidate = lama._match_boundary_color(source, mapped, expanded, radius)

                class KnownCorrectSession:
                    def run(self, outputs, inputs):
                        return [model_clean.transpose(2, 0, 1)[None].astype(np.float32)]

                root = Path(temporary)
                lama._write_png(root / "source.png", source)
                lama._write_png(root / "mask.png", mask)
                adapter = lama.LamaOnnxAdapter()
                adapter._session = KnownCorrectSession()
                with (
                    patch.object(adapter, "availability", return_value={"available": True}),
                    patch.object(lama, "_simple_background_surface", return_value=(None, 0.0, None)),
                    patch.object(lama, "_candidate_only_composite", wraps=lama._candidate_only_composite) as compose,
                ):
                    adapter.process(root / "source.png", root / "mask.png", root / "final.png")
                candidate = compose.call_args.args[1]
                np.testing.assert_array_equal(candidate, expected_candidate)
                final = lama._read_image(root / "final.png", cv.IMREAD_COLOR)
                np.testing.assert_array_equal(final[mask == 0], source[mask == 0])

    def test_non_square_model_mapping_keeps_mask_and_landmarks_aligned(self):
        source = np.zeros((420, 272, 3), np.uint8)
        mask = np.zeros(source.shape[:2], np.uint8)
        source[164:190, 109:132] = (220, 100, 40)
        mask[164:190, 109:132] = 255
        image, selected, transform = lama._letterbox_for_model(source, mask)
        self.assertEqual(transform, (90, 0, 332, 512))
        self.assertEqual(set(np.unique(selected)), {0, 255})
        mapped = lama._restore_letterboxed_output(image, transform, 272, 420)
        self.assertEqual(mapped.shape, source.shape)
        for rendered in (source, mapped):
            ys, xs = np.where(rendered[:, :, 0] > 110)
            self.assertLess(abs(float(xs.mean()) - 120), .6)
            self.assertLess(abs(float(ys.mean()) - 176.5), .6)


if __name__ == "__main__":
    unittest.main()
