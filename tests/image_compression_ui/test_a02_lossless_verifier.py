import io
import hashlib
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from engine.image_compression.lossless_verifier import verify_lossless_png_files
from engine.output.metadata_writer import write_hdde_metadata_bytes


class A02LosslessVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        source = Image.new("RGBA", (32, 24), (20, 80, 160, 255))
        source.putpixel((5, 7), (24, 84, 164, 120))
        source.save(self.root / "source.png", format="PNG", dpi=(96, 96), compress_level=1)

    def tearDown(self):
        self.temporary.cleanup()

    def _write_candidate(self, image: Image.Image, filename: str):
        encoded = io.BytesIO()
        image.save(encoded, format="PNG", dpi=(96, 96), optimize=True)
        updated, report = write_hdde_metadata_bytes(
            encoded.getvalue(),
            source_data=(self.root / "source.png").read_bytes(),
        )
        path = self.root / filename
        path.write_bytes(updated)
        return path, report

    def test_persisted_files_pass_only_at_zero_pixel_difference(self):
        with Image.open(self.root / "source.png") as source:
            source.load()
            candidate, report = self._write_candidate(source.copy(), "candidate.png")
        verification = verify_lossless_png_files(
            self.root / "source.png",
            candidate,
            metadata_report=report,
        )
        self.assertEqual(verification["verification_status"], "PASS")
        self.assertTrue(verification["pixel_identical"])
        self.assertEqual(verification["pixel_diff_count"], 0)
        self.assertEqual(verification["max_channel_diff"], 0)
        self.assertTrue(verification["alpha_exact"])
        self.assertTrue(verification["metadata_verified"])
        self.assertTrue(verification["xmp_preserved"])
        self.assertTrue(verification["artifact_identity_stable"])
        self.assertEqual(verification["source_sha256"], hashlib.sha256((self.root / "source.png").read_bytes()).hexdigest())
        self.assertEqual(verification["output_sha256"], hashlib.sha256(candidate.read_bytes()).hexdigest())

    def test_one_channel_change_fails_with_real_diff_evidence(self):
        with Image.open(self.root / "source.png") as source:
            source.load()
            altered = source.copy()
        red, green, blue, alpha = altered.getpixel((0, 0))
        altered.putpixel((0, 0), (red + 1, green, blue, alpha))
        candidate, report = self._write_candidate(altered, "altered.png")
        verification = verify_lossless_png_files(
            self.root / "source.png",
            candidate,
            metadata_report=report,
        )
        self.assertEqual(verification["verification_status"], "FAIL")
        self.assertFalse(verification["pixel_identical"])
        self.assertFalse(verification["lossless_verified"])
        self.assertEqual(verification["pixel_diff_count"], 1)
        self.assertEqual(verification["max_channel_diff"], 1)


if __name__ == "__main__":
    unittest.main()
