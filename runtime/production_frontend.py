from __future__ import annotations

from pathlib import Path


class ProductionFrontendError(RuntimeError):
    pass


def validate_production_frontend(dist_root: str | Path) -> Path:
    root = Path(dist_root).resolve()
    index_path = root / "index.html"
    if not index_path.is_file():
        raise ProductionFrontendError(f"生产前端入口不存在：{index_path}")
    assets_root = root / "assets"
    if not assets_root.is_dir() or not any(path.is_file() for path in assets_root.iterdir()):
        raise ProductionFrontendError(f"生产前端资源不完整：{assets_root}")
    return root


def register_production_frontend(app, dist_root: str | Path) -> Path:
    """Serve the built SPA after business API routes have been registered."""
    from fastapi.responses import FileResponse, JSONResponse

    root = validate_production_frontend(dist_root)
    index_path = root / "index.html"

    @app.get("/", include_in_schema=False)
    async def production_frontend_index():
        return FileResponse(index_path, headers={"Cache-Control": "no-cache"})

    @app.get("/{frontend_path:path}", include_in_schema=False)
    async def production_frontend_asset(frontend_path: str):
        normalized = str(frontend_path or "").lstrip("/")
        if normalized == "api" or normalized.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        candidate = (root / normalized).resolve()
        if root != candidate and root not in candidate.parents:
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        if candidate.is_file():
            cache = "public, max-age=31536000, immutable" if root / "assets" in candidate.parents else "no-cache"
            return FileResponse(candidate, headers={"Cache-Control": cache})
        return FileResponse(index_path, headers={"Cache-Control": "no-cache"})

    return root
