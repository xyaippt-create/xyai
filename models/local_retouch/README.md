# HDDE Local Retouch Model

Formal local-retouch runtime model:

- file: `inpainting_lama_2025jan.onnx`
- SHA256: `7df918ac3921d3daf0aae1d219776cf0dc4e4935f035af81841b40adcf74fdf2`
- source: `https://huggingface.co/opencv/inpainting_lama`
- upstream: `https://github.com/advimman/lama`
- license: Apache-2.0 (the OpenCV model repository states that all files in the directory use this license)
- runtime: ONNX Runtime, CPU execution provider

The model binary is local-only and ignored by Git. Product code verifies the exact SHA before loading it. The UI depends only on the `LocalRetouchEngine` contract and contains no model or runtime details.
