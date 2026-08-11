# AI Restoration Model Directory

Place local ONNX restoration or super-resolution models in this directory for offline PoC testing.

Supported model file type:

- `.onnx`

Runtime dependency:

- `onnxruntime`

Rules:

- Do not commit model files.
- Do not commit generated output images.
- Use `tools/experiments/ai_restoration_poc.py` for offline testing only.
- Keep main delivery pipeline unchanged until a model route proves visible quality gain on real business images.

Example:

```powershell
.\.venv\Scripts\python.exe tools\experiments\ai_restoration_poc.py --input-dir "D:\path\to\latest-real-images"
```
