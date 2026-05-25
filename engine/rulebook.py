from pathlib import Path
import sys


def get_project_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


PROJECT_ROOT = get_project_root()


def _parse_scalar(value: str):
    value = value.strip()
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "None", "~"}:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _clean_lines(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        raw = line.rstrip()
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        lines.append(raw)
    return lines


def _parse_block(lines: list[str], index: int, indent: int):
    if index >= len(lines):
        return {}, index

    stripped = lines[index].strip()
    if stripped.startswith("- "):
        values = []
        while index < len(lines):
            line = lines[index]
            current_indent = _line_indent(line)
            if current_indent < indent or not line.strip().startswith("- "):
                break
            if current_indent > indent:
                nested, index = _parse_block(lines, index, current_indent)
                values.append(nested)
                continue
            values.append(_parse_scalar(line.strip()[2:]))
            index += 1
        return values, index

    values = {}
    while index < len(lines):
        line = lines[index]
        current_indent = _line_indent(line)
        if current_indent < indent:
            break
        if current_indent > indent:
            break

        stripped = line.strip()
        if ":" not in stripped:
            index += 1
            continue

        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        index += 1

        if raw_value:
            values[key] = _parse_scalar(raw_value)
            continue

        if index >= len(lines) or _line_indent(lines[index]) <= current_indent:
            values[key] = {}
            continue

        child_indent = _line_indent(lines[index])
        values[key], index = _parse_block(lines, index, child_indent)

    return values, index


def load_yaml_like(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    parsed, _ = _parse_block(_clean_lines(text), 0, 0)
    return parsed if isinstance(parsed, dict) else {"items": parsed}


def load_rule_pack(mode: str, project_root: str | Path | None = None) -> dict:
    root = Path(project_root) if project_root else PROJECT_ROOT
    return {
        "mode": load_yaml_like(root / "modes" / f"{mode}.yaml"),
        "global_visual_rules": load_yaml_like(root / "rules" / "global_visual_rules.yaml"),
        "pipeline_rules": load_yaml_like(root / "rules" / "pipeline_rules.yaml"),
        "ai_noise_rules": load_yaml_like(root / "ai_noise_rules" / "ai_dirty_patterns.yaml"),
        "material_rules": load_yaml_like(root / "material_rules" / "materials.yaml"),
        "visual_style_rules": load_yaml_like(root / "visual_style_rules" / "commercial_styles.yaml"),
    }
