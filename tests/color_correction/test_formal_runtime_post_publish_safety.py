from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from engine.color_correction.formal_runtime import _validate_result_contract_before_publish
from engine.output.publish_safety import publish_image_bytes_with_metadata


def _png_bytes() -> bytes:
    payload = io.BytesIO()
    Image.new("RGB", (19, 13), (31, 79, 143)).save(payload, format="PNG")
    return payload.getvalue()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


INVALID_RESULT_STATES = (
    (
        "D3_RESULT_ACTION_MISMATCH",
        {
            "d3_final_action": "ACCEPT_CORRECTED",
            "result_action": "REVIEW_REQUIRED",
            "output_selected": "REVIEW_CANDIDATE",
            "output_will_exist": True,
        },
    ),
    (
        "CORRECTED_RESULT_WITHOUT_VERIFIED_OUTPUT",
        {
            "d3_final_action": "ACCEPT_CORRECTED",
            "result_action": "ACCEPT_CORRECTED",
            "output_selected": "NONE",
            "output_will_exist": False,
        },
    ),
    (
        "ORIGINAL_RESULT_MUST_NOT_MATERIALIZE_CANDIDATE",
        {
            "d3_final_action": "ACCEPT_ORIGINAL",
            "result_action": "ACCEPT_ORIGINAL",
            "output_selected": "ORIGINAL",
            "output_will_exist": True,
        },
    ),
)


class FormalRuntimePostPublishSafetyTests(unittest.TestCase):
    def _publish(self, root: Path) -> Path:
        target = root / "color-final.png"
        published, _metadata, _validation = publish_image_bytes_with_metadata(_png_bytes(), target)
        self.assertEqual(published, target.resolve())
        self.assertTrue(target.is_file())
        return target

    def test_case_a_post_publish_invariant_errors_never_unlink_committed_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            target = self._publish(Path(raw))
            committed_sha = _sha256(target)

            with patch.object(Path, "unlink", autospec=True) as unlink:
                for error_code, state in INVALID_RESULT_STATES:
                    with self.subTest(error_code=error_code):
                        with self.assertRaisesRegex(RuntimeError, error_code):
                            _validate_result_contract_before_publish(**state)
                        self.assertTrue(target.is_file())
                        self.assertEqual(_sha256(target), committed_sha)
                unlink.assert_not_called()

    def test_case_b_reoccupied_path_is_never_deleted_or_modified_by_invariant_errors(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            target = self._publish(Path(raw))
            target.unlink()
            sentinel = b"third-party-reoccupation-sentinel"
            target.write_bytes(sentinel)
            competitor_sha_before = _sha256(target)

            with patch.object(Path, "unlink", autospec=True) as unlink:
                for error_code, state in INVALID_RESULT_STATES:
                    with self.subTest(error_code=error_code):
                        with self.assertRaisesRegex(RuntimeError, error_code):
                            _validate_result_contract_before_publish(**state)
                        self.assertTrue(target.is_file())
                        self.assertEqual(_sha256(target), competitor_sha_before)
                unlink.assert_not_called()

            self.assertEqual(target.read_bytes(), sentinel)


if __name__ == "__main__":
    unittest.main()
