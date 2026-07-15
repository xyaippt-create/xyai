# 影界 HDDE｜图片尺寸缩小 PoC v1

## 1. 任务定义

本次 PoC 只验证图片尺寸缩小：在不放大、不裁切、不拉伸、不补边，保持原始宽高比、原格式、完整构图和关键显示属性的前提下，对比三种高质量降采样方法对中文、Logo、人物、产品结构、渐变和透明边缘的保护能力。

尺寸缩小会改变像素，不属于无损压缩。本次不验证指定 KB/MB、上传平台限额、格式转换、WebP、AVIF、自动裁切、锐化、降噪、调色或 AI 重绘。

## 2. Git与执行现场

- 分支：`codex/image-resize-poc`
- 基线 HEAD：`700373fcb7b6f6d742d9241cb75e18dd1230622e`
- 唯一正式证据目录：`D:\Codex\04_Visual-Master-Pro\tmp\image_resize_poc_v1\20260713_150702`
- 候选数量：8张样本 × 3种方法 × 2档尺寸，共48个
- Pillow：12.2.0
- OpenCV：4.13.0
- 当前未接入 UI、API、SSE、正式 pipeline、任务合同或结果状态

## 3. 固定样本

| 类型 | 样本 | 格式 | 原始尺寸 |
| --- | --- | --- | ---: |
| 中文大标题 | `chengdu_yanhuo.png` | PNG | 1122×1402 |
| 极小中文 | `ChatGPT Image 2026年7月1日 12_19_06 (10)_1080p_beta.png` | PNG | 1919×1080 |
| 细线、Logo与产品结构 | `lixiang_l9.png` | PNG | 1122×1402 |
| 深色材质与金属高光 | `jewelry_yaoshi_zhiguang.png` | PNG | 1058×1487 |
| 浅色中文信息图 | `办公室久坐舒缓指南.png` | PNG | 1672×941 |
| 真实透明 Alpha | `03_product_transparent_alpha.png` | PNG | 360×450 |
| 人物或集体照 | `real_group_meeting_04.jpg` | JPEG | 2133×1600 |
| 历史压缩图 | `case_original_jpg_vmp_v036_optimized.jpg` | JPEG | 500×333 |

原建议极小中文样本只有120×80，且实际不含中文，因此按任务允许范围替换为既有运行目录中的1919×1080商业PPT样本。该样本实际包含多组中文姓名、职位、说明和底部极小中文。

## 4. 技术路线

对每张原图分别直接生成75%和50%两档候选，不对候选继续缩放或重复编码。三条路线为：

- Pillow LANCZOS
- OpenCV INTER_AREA
- Pillow BICUBIC

PNG保持PNG并使用统一编码参数；JPEG保持JPEG且只进行一次最终编码。RGBA输入统一采用预乘 Alpha 降采样，完全透明像素的RGB在输出前归零。

## 5. 技术门禁结果

- 48/48候选尺寸精确符合目标
- 48/48候选可完整解码
- 48/48保持原格式
- ICC、EXIF Orientation、XMP记录结果符合门禁
- JPEG量化表和采样方式保持
- 原图SHA-256全部未变化
- 独立二次复验：48/48通过
- 未发现候选写入正式输出目录

`cropped`、`stretched`、`padded` 结论来自“直接使用单一比例缩放”实现以及尺寸、比例规则校验，是代码路径推断，不是图像内容检测结果。

独立二次复验覆盖结构、路径、尺寸、格式、元数据和SHA-256，不替代中文清晰度、人物质感、产品材质和透明边缘的人工视觉判断。

## 6. 方法结果

| 方法 | 候选数 | 平均体积减少比例 | 中位处理耗时 | 当前建议 |
| --- | ---: | ---: | ---: | --- |
| Pillow LANCZOS | 16 | 55.4533% | 0.191138秒 | 当前固定样本下的默认路线 |
| OpenCV INTER_AREA | 16 | 58.6162% | 0.148286秒 | 仅照片类备选 |
| Pillow BICUBIC | 16 | 56.9756% | 0.160651秒 | 不建议采用 |

体积数据同时包含尺寸缩小与统一输出编码的影响，不代表固定压缩比例，也不等同于真正无损压缩收益。

## 7. 视觉结论与风险

当前固定样本的100%盲测证据显示：

- LANCZOS对中文、Logo、细线和产品文字的清晰度保护最稳定，可作为当前固定样本下的默认路线。
- INTER_AREA在人物和照片样本中未表现出相对LANCZOS的决定性优势，只保留为照片类备选。
- BICUBIC整体更软，不建议作为默认路线。
- 50%缩小时，极小中文仍属于高风险边界，必须人工复核，不得默认放行。
- 未观察到明显裁切、拉伸、补边、渐变断层、人物新增色块或可见品牌色漂移。

Alpha自动门禁只验证完全透明像素满足 `Alpha=0` 时 `RGB=0`。半透明边缘是否出现黑边、白边或色彩污染，仍必须通过100%视觉证据人工判断。

## 8. 证据文件

正式结论只引用唯一有效运行目录中的以下文件：

- `golden_samples_manifest.csv`
- `resize_candidates_results.csv`
- `resize_visual_review_manifest.csv`
- `resize_metadata_comparison.json`
- `resize_method_mapping.json`
- `resize_downsampling_report.md`
- `sha256_manifest.csv`
- `independent_secondary_verification.json`
- `independent_secondary_verification.md`
- `native_crops/`
- `blind_contact_sheets/`

`tmp`证据、候选图片、CSV、JSON和对比图不属于仓库提交资产。

## 9. 阶段结论

图片尺寸缩小 PoC v1 在当前固定黄金样本上的技术验证结论为PASS。

Pillow LANCZOS是当前固定样本下的默认路线；该结论不代表正式产品能力已经完成，不承诺适用于所有输入，也不代表UI、API、SSE、正式pipeline、任务合同或结果状态已经接入。进入正式产品链路前，仍需保留50%极小中文和半透明边缘的人工视觉门禁。
