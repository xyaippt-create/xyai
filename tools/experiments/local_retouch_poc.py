from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PARENT = PROJECT_ROOT / "output"
DEFAULT_FIXTURE = PROJECT_ROOT / "tools" / "experiments" / "fixtures" / "local_retouch_poc_v1.json"
OUTPUT_NAME_PATTERN = re.compile(r"local_retouch_poc_\d{8}_\d{6}")
SAMPLE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
ROUTES = {
    "A_TELEA": cv2.INPAINT_TELEA,
    "B_NS": cv2.INPAINT_NS,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_image(path: Path) -> np.ndarray:
    encoded = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    if image is None or image.size == 0:
        raise ValueError(f"无法解码图片：{path}")
    return image


def write_png(path: Path, image: np.ndarray) -> None:
    ok, encoded = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    if not ok:
        raise ValueError(f"PNG 编码失败：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(str(path))


def validate_sample_id(value: Any) -> str:
    if not isinstance(value, str) or not SAMPLE_ID_PATTERN.fullmatch(value):
        raise ValueError("样本编号只能包含英文字母、数字、下划线或连字符，且不得具有路径语义。")
    return value


def _is_reparse_point(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400))
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(attributes & reparse_flag) or bool(callable(is_junction) and is_junction())


def ensure_isolated_output(path: Path, *, output_parent: Path = OUTPUT_PARENT) -> Path:
    approved_parent = output_parent.resolve()
    resolved = path.resolve()
    if resolved.parent != approved_parent or not OUTPUT_NAME_PATTERN.fullmatch(resolved.name):
        raise ValueError("PoC 输出必须是仓库 output 下唯一的 local_retouch_poc_<timestamp> 直属目录。")
    if _is_reparse_point(output_parent) or (path.exists() and _is_reparse_point(path)):
        raise ValueError("PoC 输出路径不得经过符号链接、目录联接或重解析点。")
    return resolved


def ensure_poc_target(output_root: Path, target: Path) -> Path:
    root = output_root.resolve(strict=True)
    if not root.is_dir() or _is_reparse_point(output_root):
        raise ValueError("PoC 隔离根目录无效或属于重解析路径。")

    candidate = target if target.is_absolute() else output_root / target
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"PoC 派生输出逃离隔离根目录：{target}") from exc

    lexical_root = output_root.absolute()
    lexical_candidate = candidate.absolute()
    try:
        relative = lexical_candidate.relative_to(lexical_root)
    except ValueError as exc:
        raise ValueError(f"PoC 派生输出不属于隔离根目录：{target}") from exc
    current = lexical_root
    for part in relative.parts:
        current /= part
        if _is_reparse_point(current):
            raise ValueError(f"PoC 派生输出不得经过符号链接、目录联接或重解析点：{current}")
    return resolved


def rectangle_mask(shape: tuple[int, int], spec: dict[str, Any]) -> np.ndarray:
    height, width = shape
    if spec.get("type") != "rectangle":
        raise ValueError("当前 PoC 只接受已经冻结的矩形 Mask。")
    x0, y0, x1, y1 = (int(spec[key]) for key in ("x0", "y0", "x1", "y1"))
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError(f"Mask 超出图片边界：{spec}")
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[y0:y1, x0:x1] = 255
    ratio = float(np.count_nonzero(mask)) / float(mask.size)
    if ratio <= 0.0 or ratio > 0.02:
        raise ValueError(f"Mask 必须是非空且不超过画面 2% 的小范围选区，当前={ratio:.6f}")
    return mask


def run_inpaint(image: np.ndarray, mask: np.ndarray, *, route: str, radius: float) -> tuple[np.ndarray, dict[str, Any]]:
    if route not in ROUTES:
        raise ValueError(f"不支持的候选路线：{route}")
    if mask.dtype != np.uint8 or mask.ndim != 2 or mask.shape != image.shape[:2] or not np.any(mask):
        raise ValueError("Mask 必须是与输入同尺寸的非空 uint8 单通道图片。")
    if image.ndim == 2:
        working = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        alpha = None
    elif image.ndim == 3 and image.shape[2] == 4:
        working = image[:, :, :3].copy()
        alpha = image[:, :, 3].copy()
    elif image.ndim == 3 and image.shape[2] == 3:
        working = image.copy()
        alpha = None
    else:
        raise ValueError(f"当前 PoC 不支持的像素结构：{image.shape}")

    started = time.perf_counter()
    repaired = cv2.inpaint(working, mask, float(radius), ROUTES[route])
    runtime_seconds = time.perf_counter() - started
    outside = mask == 0
    repaired[outside] = working[outside]
    outside_changed = int(np.count_nonzero(np.any(repaired[outside] != working[outside], axis=1)))
    if outside_changed:
        raise AssertionError("候选修改了 Mask 外像素。")

    if alpha is not None:
        candidate = np.dstack((repaired, alpha))
        alpha_status = "PASS_ALPHA_EXACT"
    else:
        candidate = repaired
        alpha_status = "NOT_APPLICABLE"
    return candidate, {
        "runtime_seconds": round(runtime_seconds, 6),
        "outside_mask_changed_pixels": outside_changed,
        "alpha_status": alpha_status,
    }


def selection_preview(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.shape[2] == 4:
        bgr = image[:, :, :3].astype(np.float32)
        alpha = image[:, :, 3:4].astype(np.float32) / 255.0
        height, width = image.shape[:2]
        yy, xx = np.indices((height, width))
        checker = np.where(((xx // 12 + yy // 12) % 2)[..., None] == 0, 224, 248).astype(np.float32)
        rgb = np.clip(bgr * alpha + checker * (1.0 - alpha), 0, 255).astype(np.uint8)
    else:
        rgb = image[:, :, :3].copy()
    marked = rgb.copy()
    red = np.zeros_like(marked)
    red[:, :, 2] = 255
    region = mask > 0
    marked[region] = cv2.addWeighted(marked[region], 0.45, red[region], 0.55, 0)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(marked, contours, -1, (0, 220, 255), 2)
    return marked


def load_fixture(path: Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    samples = payload.get("samples")
    if payload.get("source_policy") != "INTERNAL_SYNTHETIC_TEST_ASSETS_ONLY":
        raise ValueError("PoC 只允许使用明确标记的内部合成测试素材。")
    if not isinstance(samples, list) or not 5 <= len(samples) <= 6:
        raise ValueError("PoC 必须冻结 5 至 6 个样本。")
    return payload


def validate_fixture(payload: dict[str, Any]) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sample in payload["samples"]:
        sample_id = validate_sample_id(sample.get("sample_id"))
        if sample_id in seen:
            raise ValueError("样本编号必须唯一。")
        seen.add(sample_id)
        source = (PROJECT_ROOT / str(sample["relative_source_path"])).resolve()
        try:
            source.relative_to(PROJECT_ROOT)
        except ValueError as exc:
            raise ValueError("样本路径逃逸仓库范围。") from exc
        if not source.is_file():
            raise FileNotFoundError(source)
        actual_hash = sha256_file(source)
        if actual_hash != str(sample["source_sha256"]).lower():
            raise ValueError(f"样本哈希与冻结清单不一致：{sample_id}")
        image = read_image(source)
        mask = rectangle_mask(image.shape[:2], sample["mask"])
        validated.append({**sample, "source_path": source, "image": image, "mask_array": mask})
    return validated


def _public_sample(sample: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in sample.items() if key not in {"source_path", "image", "mask_array"}}


def _write_readme(output_dir: Path, manifest: dict[str, Any]) -> None:
    routes = "、".join(manifest["candidate_routes"])
    lines = [
        "# 交付标记与局部修整 PoC｜人工视觉复核",
        "",
        f"- 技术状态：{manifest['technical_status']}",
        f"- 候选路线：{routes}",
        "- 视觉结论：PENDING_HUMAN_VISUAL_REVIEW",
        "- 使用范围：仅限内部合成测试素材与隔离 PoC，不代表正式产品能力。",
        "",
        "逐样本查看 `review_package/<sample_id>/`：",
        "",
        "1. `original.*`：冻结输入；",
        "2. `selection.png`：红色区域为固定 Mask；",
        "3. `candidate_*.png`：候选真实输出。",
        "",
        "重点检查补丁感、纹理重复、边缘断裂、光影或色彩跳变，以及文字、透明边缘和合成人物结构风险。",
        "高风险样本允许结论为不适合当前自动修整，禁止为了通过而放宽选区或增加生成式重绘。",
    ]
    (output_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _candidate_record(candidate_path: Path, route: str, metrics: dict[str, Any], source: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
    decoded = read_image(candidate_path)
    dimensions_match = decoded.shape[:2] == source.shape[:2]
    alpha_exact = True
    if source.ndim == 3 and source.shape[2] == 4:
        alpha_exact = decoded.ndim == 3 and decoded.shape[2] == 4 and np.array_equal(decoded[:, :, 3], source[:, :, 3])
    technical_pass = dimensions_match and metrics["outside_mask_changed_pixels"] == 0 and alpha_exact
    return {
        "route": route,
        "candidate_path": str(candidate_path),
        "candidate_sha256": sha256_file(candidate_path),
        "output_size_bytes": candidate_path.stat().st_size,
        "dimensions": [int(decoded.shape[1]), int(decoded.shape[0])],
        "format": "PNG",
        "complete_decode": True,
        "geometry_gate": "PASS" if dimensions_match else "FAIL",
        "outside_mask_gate": "PASS" if metrics["outside_mask_changed_pixels"] == 0 else "FAIL",
        "alpha_status": metrics["alpha_status"] if alpha_exact else "FAIL",
        "runtime_seconds": metrics["runtime_seconds"],
        "technical_status": "PASS" if technical_pass else "FAIL",
        "structure_safety_status": "PENDING_HUMAN_VISUAL_REVIEW",
        "visual_gain_status": "PENDING_HUMAN_VISUAL_REVIEW",
        "route_decision": "PENDING_HUMAN_REVIEW",
    }


def _write_sha256_manifest(output: Path) -> None:
    write_json(output / "sha256_manifest.json", {
        str(path.relative_to(output)).replace("\\", "/"): sha256_file(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "sha256_manifest.json"
    })


def _technical_status(records: list[dict[str, Any]]) -> str:
    all_pass = all(
        sample["source_preserved"]
        and all(candidate["technical_status"] == "PASS" for candidate in sample["candidates"])
        for sample in records
    )
    return "PASS" if all_pass else "FAIL"


def append_routes(
    output_dir: Path,
    *,
    routes: Iterable[str],
    fixture_path: Path = DEFAULT_FIXTURE,
) -> dict[str, Any]:
    """Append only missing fixed routes to an existing package without rerunning prior candidates."""
    output = ensure_isolated_output(output_dir)
    manifest_path = output / "manifest.json"
    if not output.is_dir() or not manifest_path.is_file():
        raise FileNotFoundError(f"Existing PoC package is required: {output}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fixture = load_fixture(fixture_path)
    samples = validate_fixture(fixture)
    existing_routes = list(manifest.get("candidate_routes") or [])
    requested_routes = list(routes)
    if not requested_routes or any(route not in ROUTES for route in requested_routes):
        raise ValueError("Appended routes must come from the fixed route list.")
    if len(set(requested_routes)) != len(requested_routes):
        raise ValueError("Appended routes must not repeat.")
    if any(route in existing_routes for route in requested_routes):
        raise ValueError("A completed route must not be rerun.")
    if manifest.get("manifest_version") != "hdde.stage7a.local-retouch-poc.v1":
        raise ValueError("Existing package contract does not match this PoC version.")
    if Path(str(manifest.get("output_root"))).resolve() != output:
        raise ValueError("Existing manifest points to a different output root.")

    records_by_id = {str(record["sample_id"]): record for record in manifest.get("samples", [])}
    if set(records_by_id) != {str(sample["sample_id"]) for sample in samples}:
        raise ValueError("Existing package and frozen fixture have different samples.")

    radius = float(fixture["inpaint_radius"])
    prepared: list[tuple[dict[str, Any], dict[str, Any], list[tuple[str, np.ndarray, dict[str, Any]]]]] = []
    for sample in samples:
        record = records_by_id[str(sample["sample_id"])]
        source_path: Path = sample["source_path"]
        source = sample["image"]
        mask = sample["mask_array"]
        stat_before = source_path.stat()
        hash_before = sha256_file(source_path)
        if hash_before != record.get("source_sha256_after") or stat_before.st_mtime_ns != record.get("source_mtime_ns_after"):
            raise ValueError(f"Frozen source changed before route append: {sample['sample_id']}")
        for candidate in record.get("candidates", []):
            candidate_path = Path(str(candidate["candidate_path"]))
            if not candidate_path.is_file() or sha256_file(candidate_path) != candidate.get("candidate_sha256"):
                raise ValueError(f"Existing candidate changed before route append: {sample['sample_id']}")

        generated: list[tuple[str, np.ndarray, dict[str, Any]]] = []
        for route in requested_routes:
            candidate, metrics = run_inpaint(source, mask, route=route, radius=radius)
            generated.append((route, candidate, metrics))
        prepared.append((sample, record, generated))

    for sample, record, generated in prepared:
        source = sample["image"]
        mask = sample["mask_array"]
        sample_dir = ensure_poc_target(output, output / "review_package" / str(sample["sample_id"]))
        for route, candidate, metrics in generated:
            candidate_path = ensure_poc_target(output, sample_dir / f"candidate_{route.lower()}.png")
            if candidate_path.exists():
                raise FileExistsError(f"Will not overwrite candidate: {candidate_path}")
            write_png(candidate_path, candidate)
            record["candidates"].append(_candidate_record(candidate_path, route, metrics, source, mask))

        source_path: Path = sample["source_path"]
        stat_after = source_path.stat()
        hash_after = sha256_file(source_path)
        record["source_mtime_ns_after"] = stat_after.st_mtime_ns
        record["source_sha256_after"] = hash_after
        record["source_preserved"] = (
            record.get("source_sha256_before") == hash_after == sample["source_sha256"]
            and record.get("source_mtime_ns_before") == stat_after.st_mtime_ns
            and record.get("source_size_bytes") == stat_after.st_size
        )

    manifest["candidate_routes"] = existing_routes + requested_routes
    manifest["technical_status"] = _technical_status(manifest["samples"])
    manifest["updated_at"] = datetime.now().astimezone().isoformat()
    write_json(manifest_path, manifest)
    _write_readme(output, manifest)
    _write_sha256_manifest(output)
    return manifest


def create_poc(output_dir: Path, *, routes: Iterable[str] = ("A_TELEA",), fixture_path: Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    output = ensure_isolated_output(output_dir)
    if output.exists():
        raise FileExistsError(f"不会覆盖既有 PoC 目录：{output}")
    fixture = load_fixture(fixture_path)
    samples = validate_fixture(fixture)
    route_list = list(routes)
    if not route_list or any(route not in ROUTES for route in route_list) or len(set(route_list)) != len(route_list):
        raise ValueError("候选路线必须来自固定路线清单且不得重复。")
    output.mkdir(parents=True, exist_ok=False)
    review_root = output / "review_package"
    mask_root = output / "technical" / "masks"
    radius = float(fixture["inpaint_radius"])
    records: list[dict[str, Any]] = []
    for sample in samples:
        source_path: Path = sample["source_path"]
        source = sample["image"]
        mask = sample["mask_array"]
        stat_before = source_path.stat()
        hash_before = sha256_file(source_path)
        sample_dir = ensure_poc_target(output, review_root / sample["sample_id"])
        sample_dir.mkdir(parents=True, exist_ok=True)
        original_copy = ensure_poc_target(output, sample_dir / f"original{source_path.suffix.lower()}")
        shutil.copy2(source_path, original_copy)
        mask_path = ensure_poc_target(output, mask_root / f"{sample['sample_id']}__mask.png")
        write_png(mask_path, mask)
        selection_path = ensure_poc_target(output, sample_dir / "selection.png")
        write_png(selection_path, selection_preview(source, mask))
        candidates: list[dict[str, Any]] = []
        for route in route_list:
            candidate, metrics = run_inpaint(source, mask, route=route, radius=radius)
            candidate_path = ensure_poc_target(output, sample_dir / f"candidate_{route.lower()}.png")
            write_png(candidate_path, candidate)
            candidates.append(_candidate_record(candidate_path, route, metrics, source, mask))
        stat_after = source_path.stat()
        hash_after = sha256_file(source_path)
        source_preserved = (
            hash_before == hash_after == sample["source_sha256"]
            and stat_before.st_mtime_ns == stat_after.st_mtime_ns
            and stat_before.st_size == stat_after.st_size
        )
        records.append({
            **_public_sample(sample),
            "source_path": str(source_path),
            "source_size_bytes": stat_before.st_size,
            "source_mtime_ns_before": stat_before.st_mtime_ns,
            "source_mtime_ns_after": stat_after.st_mtime_ns,
            "source_sha256_before": hash_before,
            "source_sha256_after": hash_after,
            "source_preserved": source_preserved,
            "dimensions": [int(source.shape[1]), int(source.shape[0])],
            "mask_path": str(mask_path),
            "mask_sha256": sha256_file(mask_path),
            "mask_pixel_count": int(np.count_nonzero(mask)),
            "mask_ratio": round(float(np.count_nonzero(mask)) / float(mask.size), 8),
            "original_copy_path": str(original_copy),
            "selection_path": str(selection_path),
            "candidates": candidates,
        })
    manifest = {
        "manifest_version": "hdde.stage7a.local-retouch-poc.v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "output_root": str(output),
        "usage_scope": fixture["usage_scope"],
        "source_policy": fixture["source_policy"],
        "candidate_routes": route_list,
        "candidate_conditions": {"inpaint_radius": radius, "same_source_mask_dimensions_for_all_routes": True},
        "sample_count": len(records),
        "technical_status": _technical_status(records),
        "visual_review_status": "REQUIRED",
        "visual_recommendation": "PENDING_HUMAN_VISUAL_REVIEW",
        "formal_product_integration": False,
        "samples": records,
    }
    write_json(output / "manifest.json", manifest)
    _write_readme(output, manifest)
    _write_sha256_manifest(output)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HDDE 交付标记与局部修整隔离 PoC")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--routes", nargs="+", choices=tuple(ROUTES), default=["A_TELEA"])
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--append", action="store_true", help="Append only missing routes to an existing package")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir or OUTPUT_PARENT / datetime.now().strftime("local_retouch_poc_%Y%m%d_%H%M%S")
    if args.append:
        if args.output_dir is None:
            raise ValueError("--append requires --output-dir")
        manifest = append_routes(output_dir, routes=args.routes, fixture_path=args.fixture)
    else:
        manifest = create_poc(output_dir, routes=args.routes, fixture_path=args.fixture)
    print(json.dumps({
        "output_root": manifest["output_root"],
        "sample_count": manifest["sample_count"],
        "candidate_routes": manifest["candidate_routes"],
        "technical_status": manifest["technical_status"],
        "visual_review_status": manifest["visual_review_status"],
    }, ensure_ascii=False))
    return 0 if manifest["technical_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
