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

    特点：
    - 小字清晰
    - 边缘稳定
    - 版式安全
    """

    img = cv2.fastNlMeansDenoisingColored(
        img,
        None,
        3,
        3,
        7,
        21
    )

    lab = cv2.cvtColor(
        img,
        cv2.COLOR_BGR2LAB
    )

    l, a, b = cv2.split(lab)

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    )

    l = clahe.apply(l)

    img = cv2.merge((l, a, b))

    img = cv2.cvtColor(
        img,
        cv2.COLOR_LAB2BGR
    )

    blur = cv2.GaussianBlur(
        img,
        (0, 0),
        1.0
    )

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
    AI插画 / 国潮视觉 / 城市幻想 / 科技视觉

    核心方向：
    - 保留电影空气感
    - 保持干净通透
    - 避免HDR感
    - 避免塑料感
    - 不做暴力锐化
    """

    # 1. 轻度降噪
    img = cv2.fastNlMeansDenoisingColored(
        img,
        None,
        2,
        2,
        7,
        21
    )

    # 2. 温和层次
    lab = cv2.cvtColor(
        img,
        cv2.COLOR_BGR2LAB
    )

    l, a, b = cv2.split(lab)

    clahe = cv2.createCLAHE(
        clipLimit=1.35,
        tileGridSize=(8, 8)
    )

    l = clahe.apply(l)

    img = cv2.merge((l, a, b))

    img = cv2.cvtColor(
        img,
        cv2.COLOR_LAB2BGR
    )

    # 3. 极轻柔化
    # 去掉数码边缘
    # 保留电影空气感
    img = cv2.GaussianBlur(
        img,
        (0, 0),
        0.2
    )

    # 4. 极轻柔锐
    # 避免HDR感和脏纹理
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



def process_all(input_path, output_dir):

    input_path = Path(input_path)

    output_dir = Path(output_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    files = collect_images(input_path)

    if not files:
        print("没有找到图片，请确认输入目录。")
        return

    print(f"当前模式：{MODE}")
    print(f"目标宽度：{TARGET_WIDTH}px")
    print(f"发现 {len(files)} 张图片，开始处理。")

    for file in files:

        print(f"处理中：{file.name}")

        img = read_image_unicode(file)

        if img is None:
            print(f"跳过，无法读取：{file.name}")
            continue

        # 4K放大
        img = upscale_to_4k(img)

        # 画质增强
        img = enhance_image(img)

        # 输出文件名
        output_name = (
            file.stem
            + "_雪原Ai·PPT设计"
            + OUTPUT_FORMAT
        )

        output_path = output_dir / output_name

        ok = write_image_unicode(
            output_path,
            img
        )

        if ok:
            print(f"完成：{output_path}")
        else:
            print(f"保存失败：{output_path}")

    print("全部处理完成。")


if __name__ == "__main__":

    if len(sys.argv) < 3:

        print(
            "用法：python master_process.py 输入图片或输入文件夹 输出文件夹"
        )

        sys.exit(1)

    process_all(
        sys.argv[1],
        sys.argv[2]
    )