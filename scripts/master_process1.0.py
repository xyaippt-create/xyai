import sys
import cv2
import numpy as np
from pathlib import Path

IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".webp"]

TARGET_WIDTH = 3840
OUTPUT_FORMAT = ".png"

# 可选模式：
# ai_art = AI海报 / 场景图 / 插画 / 科技视觉
# infographic = 地图 / PPT / 信息图 / UI图
MODE = "ai_art"


def read_image_unicode(path):
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def write_image_unicode(path, img):
    ext = Path(path).suffix
    success, encoded = cv2.imencode(ext, img)

    if success:
        encoded.tofile(str(path))

    return success


def upscale_to_4k(img):
    h, w = img.shape[:2]

    if w >= TARGET_WIDTH:
        return img

    scale = TARGET_WIDTH / w
    new_w = TARGET_WIDTH
    new_h = int(round(h * scale))

    return cv2.resize(
        img,
        (new_w, new_h),
        interpolation=cv2.INTER_CUBIC
    )


def enhance_infographic(img):
    """
    信息图模式：
    地图 / PPT / UI / 路线图
    """

    img = cv2.fastNlMeansDenoisingColored(
        img,
        None,
        3,
        3,
        7,
        21
    )

    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    )

    l = clahe.apply(l)
    img = cv2.merge((l, a, b))
    img = cv2.cvtColor(img, cv2.COLOR_LAB2BGR)

    blur = cv2.GaussianBlur(img, (0, 0), 1.0)

    img = cv2.addWeighted(
        img,
        1.18,
        blur,
        -0.18,
        0
    )

    return img


def enhance_ai_art(img):
    """
    AI海报柔锐模式：
    保留空气感，减少脏纹理，不做暴力锐化。
    """

    img = cv2.fastNlMeansDenoisingColored(
        img,
        None,
        2,
        2,
        7,
        21
    )

    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    clahe = cv2.createCLAHE(
        clipLimit=1.35,
        tileGridSize=(8, 8)
    )

    l = clahe.apply(l)
    img = cv2.merge((l, a, b))
    img = cv2.cvtColor(img, cv2.COLOR_LAB2BGR)

    img = cv2.GaussianBlur(
        img,
        (0, 0),
        0.2
    )

    blur = cv2.GaussianBlur(
        img,
        (0, 0),
        1.0
    )

    img = cv2.addWeighted(
        img,
        1.02,
        blur,
        -0.02,
        0
    )

    return img


def enhance_image(img):
    if MODE == "infographic":
        return enhance_infographic(img)

    if MODE == "ai_art":
        return enhance_ai_art(img)

    print(f"未知模式：{MODE}，自动使用 ai_art 模式。")
    return enhance_ai_art(img)


def collect_images(input_path):
    input_path = Path(input_path)

    if input_path.is_file():
        if input_path.suffix.lower() in IMAGE_EXTS:
            return [input_path]
        return []

    if input_path.is_dir():
        return [
            p for p in input_path.iterdir()
            if p.suffix.lower() in IMAGE_EXTS
        ]

    return []


def get_desktop_work_dirs():
    """
    双击 EXE 时自动使用桌面工作目录：
    桌面/雪原Ai增强引擎/输入图片
    桌面/雪原Ai增强引擎/输出成品
    """

    desktop = Path.home() / "Desktop"
    work_dir = desktop / "雪原Ai增强引擎"

    input_dir = work_dir / "输入图片"
    output_dir = work_dir / "输出成品"

    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    return input_dir, output_dir


def process_all(input_path, output_dir):
    input_path = Path(input_path)
    output_dir = Path(output_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    files = collect_images(input_path)

    if not files:
        print("没有找到图片。")
        print(f"请把图片放入：{input_path}")
        input("按回车键退出...")
        return

    print("雪原Ai增强引擎")
    print("----------------")
    print(f"当前模式：{MODE}")
    print(f"目标宽度：{TARGET_WIDTH}px")
    print(f"输入位置：{input_path}")
    print(f"输出位置：{output_dir}")
    print(f"发现 {len(files)} 张图片，开始处理。")

    for file in files:
        print(f"处理中：{file.name}")

        img = read_image_unicode(file)

        if img is None:
            print(f"跳过，无法读取：{file.name}")
            continue

        img = upscale_to_4k(img)
        img = enhance_image(img)

        output_name = (
            file.stem
            + "_雪原Ai·PPT设计"
            + OUTPUT_FORMAT
        )

        output_path = output_dir / output_name

        ok = write_image_unicode(output_path, img)

        if ok:
            print(f"完成：{output_path}")
        else:
            print(f"保存失败：{output_path}")

    print("全部处理完成。")
    print(f"输出位置：{output_dir}")
    input("按回车键退出...")


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        process_all(
            sys.argv[1],
            sys.argv[2]
        )
    else:
        input_dir, output_dir = get_desktop_work_dirs()
        process_all(
            input_dir,
            output_dir
        )