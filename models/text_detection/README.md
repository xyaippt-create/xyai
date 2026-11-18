# HDDE 4K Text Detection Model

Used by 4K quality enhancement to find text regions; it only produces a mask, never pixels or text content.

- file: `text_detection_cn_ppocrv3_2023may.onnx`
- SHA256: `03f550c6b406fda8bf54bd8327815f6c7e2edd98cea02348c93d879254366587`
- source: `https://huggingface.co/opencv/text_detection_ppocr` (downloaded 2026-11-18 with the product owner's approval)
- upstream: PaddleOCR PP-OCRv3 Chinese detection model `ch_PP-OCRv3_det_infer` (`https://github.com/PaddlePaddle/PaddleOCR`)
- license: Apache-2.0 (the OpenCV model repository states that all files in the directory use this license); full text in `LICENSE-Apache-2.0.txt`, taken from that repository's `LICENSE` on 2026-11-18
- modification: none
- runtime: ONNX Runtime, CPU execution provider

The model binary is local-only and ignored by Git. Product code verifies the exact SHA before loading it; if the model is missing or does not match, 4K processing still completes with the v4 result and the task report says text clarity was not applied.
