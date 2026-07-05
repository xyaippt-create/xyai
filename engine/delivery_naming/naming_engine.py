from __future__ import annotations

import csv
import re
import shutil
from dataclasses import dataclass, field
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Iterable


DEFAULT_TEMPLATES = {
    "safe_delivery": "{index}_{original_name}_{mode}_{resolution}",
    "commercial_project": "{index}_{industry}_{title}_{mode}",
    "page_type": "{index}_{industry}_{page_type}_{title}",
    "custom_example": "{index}_{industry}_{title}_{keywords}_{date}",
    "index_industry_filename": "{index}_{industry}_{original_name}",
}

WINDOWS_ILLEGAL_CHARS = set('\\/:*?"<>|')
PLACEHOLDER_RE = re.compile(r"{([a-zA-Z0-9_]+)}")
DEFAULT_MISSING_VALUE = "待确认"


@dataclass(frozen=True)
class SourceFile:
    path: Path
    fields: dict[str, str] = field(default_factory=dict)
    manual_name: str | None = None

    @property
    def original_name(self) -> str:
        return self.path.stem

    @property
    def extension(self) -> str:
        return self.path.suffix


@dataclass(frozen=True)
class NamingSettings:
    template: str
    start_index: int = 1
    index_width: int = 3
    separator: str = "_"
    prefix: str = ""
    suffix: str = ""
    mode: str = "1080P"
    resolution: str = "1080P"
    date_value: str = field(default_factory=lambda: date.today().isoformat())
    output_dir: Path | None = None
    max_stem_length: int = 120
    missing_value: str = DEFAULT_MISSING_VALUE
    preserve_extension: bool = True


@dataclass(frozen=True)
class RenameRow:
    source_path: Path
    source_name: str
    target_name: str
    target_path: Path | None
    template: str
    fields_used: dict[str, str]
    field_sources: dict[str, str]
    missing_fields: list[str]
    conflict_status: str
    status: str
    applied: bool = False


def sanitize_filename_part(value: object, missing_value: str = DEFAULT_MISSING_VALUE) -> str:
    text = str(value if value not in (None, "") else missing_value).strip()
    cleaned = "".join("_" if char in WINDOWS_ILLEGAL_CHARS or ord(char) < 32 else char for char in text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or missing_value


def parse_manifest_csv(text: str) -> list[dict[str, str]]:
    if not text.strip():
        return []
    sample = text.lstrip("\ufeff")
    dialect = csv.Sniffer().sniff(sample.splitlines()[0] + "\n")
    reader = csv.DictReader(StringIO(sample), dialect=dialect)
    return [{str(key).strip(): str(value or "").strip() for key, value in row.items()} for row in reader]


def _index_value(position: int, settings: NamingSettings) -> str:
    return str(settings.start_index + position).zfill(max(1, settings.index_width))


def _field_value(name: str, source: SourceFile, position: int, settings: NamingSettings) -> tuple[str, str, bool]:
    system_fields = {
        "index": _index_value(position, settings),
        "original_name": source.original_name,
        "mode": settings.mode,
        "resolution": settings.resolution,
        "date": settings.date_value,
        "sep": settings.separator,
    }
    if source.manual_name and name == "manual_name":
        return source.manual_name, "manual", False
    if name in source.fields and source.fields[name]:
        return source.fields[name], "manifest", False
    if name in system_fields and system_fields[name]:
        return system_fields[name], "system", False
    return settings.missing_value, "missing", True


def _render_stem(source: SourceFile, position: int, settings: NamingSettings) -> tuple[str, dict[str, str], dict[str, str], list[str]]:
    if source.manual_name:
        stem = source.manual_name
        fields_used = {"manual_name": source.manual_name}
        field_sources = {"manual_name": "manual"}
        missing_fields: list[str] = []
    else:
        fields_used = {}
        field_sources = {}
        missing_fields = []

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            value, origin, missing = _field_value(name, source, position, settings)
            safe_value = sanitize_filename_part(value, settings.missing_value)
            fields_used[name] = safe_value
            field_sources[name] = origin
            if missing:
                missing_fields.append(name)
            return safe_value

        stem = PLACEHOLDER_RE.sub(replace, settings.template)
    if settings.prefix:
        stem = f"{settings.prefix}{settings.separator}{stem}"
    if settings.suffix:
        stem = f"{stem}{settings.separator}{settings.suffix}"
    return sanitize_filename_part(stem, settings.missing_value), fields_used, field_sources, missing_fields


def _limit_stem(stem: str, extension: str, max_stem_length: int) -> str:
    limit = max(1, max_stem_length - len(extension))
    return stem[:limit].rstrip(" ._") or DEFAULT_MISSING_VALUE


def _dedupe_name(name: str, used_names: set[str]) -> tuple[str, str]:
    if name.lower() not in used_names:
        used_names.add(name.lower())
        return name, "ok"
    stem = Path(name).stem
    suffix = Path(name).suffix
    counter = 2
    while True:
        candidate = f"{stem}_{counter:02d}{suffix}"
        if candidate.lower() not in used_names:
            used_names.add(candidate.lower())
            return candidate, "renamed_duplicate"
        counter += 1


def build_rename_plan(sources: Iterable[SourceFile], settings: NamingSettings, existing_names: Iterable[str] | None = None) -> list[RenameRow]:
    used_names = {name.lower() for name in existing_names or []}
    rows: list[RenameRow] = []
    for position, source in enumerate(sources):
        extension = source.extension if settings.preserve_extension else ""
        stem, fields_used, field_sources, missing_fields = _render_stem(source, position, settings)
        stem = _limit_stem(stem, extension, settings.max_stem_length)
        target_name, conflict_status = _dedupe_name(f"{stem}{extension}", used_names)
        target_path = (settings.output_dir / target_name) if settings.output_dir else None
        if missing_fields:
            status = "needs_confirmation"
        elif conflict_status != "ok":
            status = "conflict_resolved"
        else:
            status = "ready"
        rows.append(
            RenameRow(
                source_path=source.path,
                source_name=source.path.name,
                target_name=target_name,
                target_path=target_path,
                template=settings.template if not source.manual_name else "{manual_name}",
                fields_used=fields_used,
                field_sources=field_sources,
                missing_fields=missing_fields,
                conflict_status=conflict_status,
                status=status,
            )
        )
    return rows


def export_rename_map_csv(rows: Iterable[RenameRow]) -> str:
    output = StringIO()
    fieldnames = [
        "source_path",
        "source_name",
        "target_path",
        "target_name",
        "template",
        "fields_used",
        "field_sources",
        "missing_fields",
        "conflict_status",
        "status",
        "applied",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "source_path": str(row.source_path),
                "source_name": row.source_name,
                "target_path": str(row.target_path or ""),
                "target_name": row.target_name,
                "template": row.template,
                "fields_used": repr(row.fields_used),
                "field_sources": repr(row.field_sources),
                "missing_fields": ";".join(row.missing_fields),
                "conflict_status": row.conflict_status,
                "status": row.status,
                "applied": str(row.applied).lower(),
            }
        )
    return output.getvalue()


def apply_copy_plan(rows: Iterable[RenameRow], output_dir: Path) -> list[RenameRow]:
    output_dir.mkdir(parents=True, exist_ok=True)
    applied_rows: list[RenameRow] = []
    created: list[Path] = []
    try:
        for row in rows:
            target_path = output_dir / row.target_name
            if target_path.exists():
                raise FileExistsError(f"target exists: {target_path}")
            shutil.copy2(row.source_path, target_path)
            created.append(target_path)
            applied_rows.append(
                RenameRow(
                    source_path=row.source_path,
                    source_name=row.source_name,
                    target_name=row.target_name,
                    target_path=target_path,
                    template=row.template,
                    fields_used=row.fields_used,
                    field_sources=row.field_sources,
                    missing_fields=row.missing_fields,
                    conflict_status=row.conflict_status,
                    status=row.status,
                    applied=True,
                )
            )
    except Exception:
        for path in created:
            try:
                path.unlink()
            except OSError:
                pass
        raise
    return applied_rows
