"""Named watermark settings, independent of batch inputs and history."""

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from engine.batch_watermark.engine import decode_watermark_logo


def register_watermark_presets(app, require_roots, parse_spec, read_upload):
    base = "/api/batch-watermark/presets"

    @contextmanager
    def database(*, create=False):
        _, root, _ = require_roots()
        path = root / ".hdde-watermark-presets.sqlite3"
        try:
            for suffix in ("", "-journal", "-wal", "-shm"):
                target = Path(str(path) + suffix)
                if target.resolve() != target:
                    raise OSError("unsafe preset storage")
            if not create and not path.exists():
                yield None
                return
            with closing(sqlite3.connect(path)) as db, db:
                if create:
                    db.execute("""CREATE TABLE IF NOT EXISTS presets (
                        id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, spec TEXT NOT NULL,
                        logo_name TEXT, logo BLOB, logo_sha256 TEXT
                    )""")
                yield db
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "已有同名方案，请换一个名称。") from exc
        except (OSError, sqlite3.Error) as exc:
            raise HTTPException(503, "常用方案存储无法访问，请检查正式目录后重试。") from exc

    @app.get(base)
    def list_presets():
        with database() as db:
            rows = db.execute("SELECT id, name, spec, logo_name FROM presets ORDER BY rowid DESC") if db else ()
            return {"data": [dict(id=i, name=n, spec=json.loads(s), logo_name=f) for i, n, s, f in rows]}

    @app.post(base)
    async def save_preset(name: str = Form(...), spec_json: str = Form(...), watermark_file: UploadFile | None = File(None)):
        name = name.strip()
        if not 1 <= len(name) <= 80:
            raise HTTPException(422, "请输入 1 至 80 字的方案名称。")
        spec = parse_spec(spec_json)
        logo_name = logo = digest = None
        if spec.kind == "image":
            if watermark_file is None:
                raise HTTPException(422, "请重新选择透明 PNG Logo。")
            try:
                logo = await read_upload(watermark_file, role="Logo")
                decode_watermark_logo(logo).close()
            except ValueError as exc:
                raise HTTPException(422, f"{exc} 请重新选择透明 PNG Logo。") from exc
            logo_name = Path(watermark_file.filename or "Logo.png").name
            digest = hashlib.sha256(logo).hexdigest()
        preset_id = uuid.uuid4().hex
        fields = ("kind", "opacity", "position", "margin_x", "margin_y")
        fields += ("image_width_percent",) if spec.kind == "image" else ("text", "font_id", "color", "text_size", "rotation", "tile")
        config = {key: getattr(spec, key) for key in fields}
        with database(create=True) as db:
            db.execute("INSERT INTO presets (id, name, spec, logo_name, logo, logo_sha256) VALUES (?, ?, ?, ?, ?, ?)",
                       (preset_id, name, json.dumps(config, ensure_ascii=False), logo_name, logo, digest))
        return {"data": dict(id=preset_id, name=name, spec=config, logo_name=logo_name)}

    @app.get(base + "/{preset_id}/logo")
    def preset_logo(preset_id: str):
        with database() as db:
            row = db.execute("SELECT logo, logo_sha256 FROM presets WHERE id = ?", (preset_id,)).fetchone() if db else None
        if not row or not row[0] or hashlib.sha256(row[0]).hexdigest() != row[1]:
            raise HTTPException(409, "此方案的 Logo 无法读取，请重新选择透明 PNG Logo。")
        return Response(row[0], media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.delete(base + "/{preset_id}")
    def delete_preset(preset_id: str):
        with database() as db:
            if not db or not db.execute("DELETE FROM presets WHERE id = ?", (preset_id,)).rowcount:
                raise HTTPException(404, "该方案已不存在。")
        return {"success": True}
