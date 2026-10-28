from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from engine.hd_core.candidate_framework import (
    E102EvaluationContext,
    PRODUCT,
    SAFETY_REJECTED,
    run_4k_candidate,
    sha256_file,
)
from engine.hd_core.swin2sr_candidate import (
    MODEL_ID,
    Swin2SRCandidateAdapter,
    build_swin2sr_definition,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
E1_01_MANIFEST = (
    REPO_ROOT / "artifacts" / "e1_01_real_information_baseline_v1" / "manifest.json"
)


def _fake_x4(tile: Image.Image) -> Image.Image:
    return tile.resize(
        (tile.width * 4, tile.height * 4), Image.Resampling.NEAREST
    )


class Swin2SRCandidateAdapterTest(unittest.TestCase):
    def _model_root(self, root: Path) -> Path:
        model_root = root / "model"
        model_root.mkdir()
        (model_root / "pytorch_model.bin").write_bytes(b"test-model-identity")
        return model_root

    def _fixture(self, root: Path) -> tuple[Path, Path]:
        source = root / "source.png"
        baseline = root / "baseline.png"
        rgba = np.zeros((24, 32, 4), dtype=np.uint8)
        rgba[..., 0] = np.arange(32, dtype=np.uint8)[None, :] * 7
        rgba[..., 1] = np.arange(24, dtype=np.uint8)[:, None] * 9
        rgba[..., 2] = 80
        rgba[..., 3] = np.arange(32, dtype=np.uint8)[None, :] * 8
        Image.fromarray(rgba, "RGBA").save(source)
        Image.fromarray(
            np.repeat(np.repeat(rgba, 3, axis=0), 3, axis=1), "RGBA"
        ).save(baseline)
        return source, baseline

    def test_adapter_output_alpha_geometry_and_runtime_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_root = self._model_root(root)
            source, baseline = self._fixture(root)
            adapter = Swin2SRCandidateAdapter(
                model_root,
                tile_core=16,
                tile_context=8,
                tile_inference=_fake_x4,
            )
            definition = build_swin2sr_definition(
                model_root / "pytorch_model.bin",
                revision="test-revision",
                tile_core=16,
                tile_context=8,
            )
            result = run_4k_candidate(
                source,
                root / "runs",
                definition=definition,
                executor=adapter,
                baseline_path=baseline,
                execution_nonce="ADAPTER_CONTRACT",
            )

            self.assertEqual(result["execution_status"], "COMPLETED")
            self.assertEqual(result["output_validation"]["status"], "PASS")
            self.assertEqual(result["comparison_surface"]["status"], "ELIGIBLE")
            self.assertEqual(result["candidate_class"], PRODUCT)
            self.assertEqual(result["candidate_identity_contract"]["model_id"], MODEL_ID)
            with Image.open(baseline) as baseline_image, Image.open(
                Path(str(result["candidate_reference"]))
            ) as candidate_image:
                self.assertEqual(candidate_image.size, baseline_image.size)
                self.assertEqual(candidate_image.mode, baseline_image.mode)
                self.assertEqual(
                    candidate_image.getchannel("A").tobytes(),
                    baseline_image.getchannel("A").tobytes(),
                )
            runtime_path = (
                Path(str(result["evidence_refs"]["run_directory"]))
                / "candidate_runtime.json"
            )
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            self.assertEqual(runtime["model_sha256"], sha256_file(model_root / "pytorch_model.bin"))
            self.assertEqual(runtime["backend"], "PYTORCH_RESEARCH_RUNTIME")
            self.assertEqual(runtime["precision"], "FP32")
            self.assertEqual(runtime["alpha_strategy"], "BASELINE_ALPHA_DERIVED_FROM_SOURCE_REATTACHED")
            self.assertEqual(runtime["tile_count"], 4)

    def test_adapter_repeat_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_root = self._model_root(root)
            source, baseline = self._fixture(root)
            adapter = Swin2SRCandidateAdapter(
                model_root,
                tile_core=16,
                tile_context=8,
                tile_inference=_fake_x4,
            )
            definition = build_swin2sr_definition(
                model_root / "pytorch_model.bin",
                revision="test-revision",
                tile_core=16,
                tile_context=8,
            )
            first = run_4k_candidate(
                source,
                root / "runs_first",
                definition=definition,
                executor=adapter,
                baseline_path=baseline,
                execution_nonce="DETERMINISM_FIRST",
            )
            second = run_4k_candidate(
                source,
                root / "runs_second",
                definition=definition,
                executor=adapter,
                baseline_path=baseline,
                execution_nonce="DETERMINISM_SECOND",
            )
            self.assertEqual(first["candidate_sha256"], second["candidate_sha256"])

    def test_product_candidate_maps_to_existing_e1_02_product_semantics(self) -> None:
        manifest = json.loads(E1_01_MANIFEST.read_text(encoding="utf-8"))
        case = next(item for item in manifest["cases"] if item["case_id"] == "E1C015")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_root = self._model_root(root)
            adapter = Swin2SRCandidateAdapter(
                model_root,
                tile_core=224,
                tile_context=16,
                tile_inference=_fake_x4,
            )
            definition = build_swin2sr_definition(
                model_root / "pytorch_model.bin",
                revision="test-revision",
            )
            result = run_4k_candidate(
                REPO_ROOT / case["input"]["path"],
                root / "runs",
                definition=definition,
                executor=adapter,
                baseline_path=REPO_ROOT / case["safe_base"]["path"],
                e1_02_context=E102EvaluationContext(E1_01_MANIFEST, "E1C015"),
                execution_nonce="PRODUCT_E1_MAPPING",
            )

            self.assertEqual(result["actual_run_binding_status"], "PASS")
            self.assertEqual(result["e1_02_candidate_class"], PRODUCT)
            self.assertEqual(result["e1_02_result"]["candidate_class"], PRODUCT)
            self.assertTrue(result["e1_02_result"]["human_review_required"])
            self.assertTrue(result["e1_02_result"]["human_review_pending"])
            self.assertFalse(result["e1_02_result"]["human_review_product_admissible"])
            self.assertEqual(result["candidate_state"], SAFETY_REJECTED)
            self.assertFalse(result["candidate_accepted"])
            self.assertEqual(result["safe_reference_selected"], "BASELINE")


if __name__ == "__main__":
    unittest.main()
