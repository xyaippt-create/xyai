# V0.4.6 T02 黄金测试集报告

日期：2026-06-17
项目：VisualMasterPro / 影界
任务：T02 建立 V0.4.6 黄金测试集
结论：PASS_WITH_SAMPLE_GAPS

## 1. 执行摘要

T02 已建立 V0.4.6 黄金测试集目录、Manifest、完整性校验脚本和 Phase 1 基线运行脚本。本任务未修改图像算法、质量门、API、SSE、任务调度、输出选择、前端或默认输入目录。

当前 manifest 共 84 条记录：19 个 ready 样本、60 个 missing 缺口记录、5 个 excluded 记录。Smoke Set 已达到 7 个 ready 样本；Core Set 已建立 24 条记录，其中 7 个 ready、12 个 missing、5 个 excluded；Extended Set 已建立 48 条缺口和未来能力预留记录。已提交 ready 输入体积约 0.466 MB。

5 个旧模式大图输出样本因单文件体积过大，未作为提交版 golden 输入纳入仓库，已在 manifest 中以 `status=excluded` 保留为 Core 缺口证据，不做静默删除或伪装覆盖。

## 2. Git 基线

| 项目 | 值 |
|---|---|
| 稳定工程底座 | V0.4.5.3 |
| Phase 1 生产代码冻结 Commit | `8bf051cd3fcc6e8f7c363c2b43eac819c1c4e6b3` |
| Phase 1 完整基线 Commit | `e98afe81ec401f04458fbaccaaa0d80b81f2fda8` |
| Phase 1 基线 Tag | `v0.4.6-phase1-baseline` |
| T02 起点 HEAD | `0012e95175351889e8ad187c9363ce26fb336320` |

## 3. 目录结构

```text
tests/golden_v046/
├── README.md
├── manifest.json
├── manifest.csv
├── smoke/
├── core/
│   ├── text_poster/
│   ├── product_kv/
│   ├── portrait/
│   ├── architecture/
│   ├── landscape/
│   └── unknown/
├── extended/
├── synthetic/
├── private/
└── references/
```

`private/` 已加入 `.gitignore`，不提交私人样本。Phase 1 基线运行输出写入 `tests/results/golden_v046_phase1/`，该目录继续由现有 `tests/results/` 忽略规则排除。

## 4. Smoke Set 清单

| sample_id | 预期类型 | 主要风险 |
|---|---|---|
| `smoke_text_poster_cn_small_legacy` | text_poster | small_chinese_text |
| `smoke_product_png_legacy` | product_kv | quality_gate_failed |
| `smoke_transparent_png_legacy` | unknown | alpha_edge |
| `smoke_portrait_ready` | portrait | skin_plastic |
| `smoke_architecture_low` | architecture | line_ghosting |
| `smoke_landscape_ultrawide` | landscape | pseudo_texture |
| `smoke_original_unprocessed_jpg` | unknown | jpeg_blocking |

历史链路样本继续保留 `legacy_phase1_sample=true`。同时新增一个未经过影界处理的合成原始 JPG 样本，用于补足 JPG 输入链路；它不替代真实商业照片。

## 5. Core Set 覆盖

Core Set 目标为 24 条记录，当前 7 个 ready、12 个 missing、5 个 excluded。

| 类型 | Ready | Missing | Excluded | 说明 |
|---|---:|---:|---:|---|
| text_poster | 2 | 2 | 0 | 覆盖中文小字、数字、Logo、合成微小字 |
| product_kv | 1 | 0 | 3 | 保留低质量产品 PNG；旧 KV、化妆品、食品大图输出转为 excluded |
| portrait | 0 | 3 | 1 | 缺少可提交真实低质量人物或商业人像 |
| architecture | 1 | 2 | 1 | 覆盖宽幅建筑线条；旧大图输出转为 excluded |
| landscape | 1 | 3 | 0 | 缺少更多真实树叶、草地、远景照片 |
| unknown | 2 | 2 | 0 | 覆盖 RGBA、未知原始图 |

缺口均以 `status=missing` 或 `status=excluded` 写入 manifest，未使用无关图片凑数量。

## 6. Extended Set 缺口

Extended Set 已建立 48 条记录，当前均为 missing 或未来能力预留。字段包含 `reference_group_id`、`is_reference_image`、`color_mismatch_type` 和 `future_feature`，用于后续参考图色彩统一能力；T02 未实现颜色匹配算法。

## 7. 六类图像覆盖

Ready 样本按预期类型统计：

| 类型 | Ready 数量 | 主要风险 |
|---|---:|---|
| text_poster | 4 | 中文小字、数字、Logo、细线 |
| product_kv | 3 | 产品材质、高光、品牌色、低质量 PNG |
| portrait | 1 | 皮肤、头发、衣物、低对比 |
| architecture | 2 | 建筑线条、宽幅环境、重影风险 |
| landscape | 2 | 远景、树叶草地、伪纹理 |
| unknown | 7 | Alpha、渐变、未知分类、JPG 压缩 |

Ready 样本格式为 18 个 PNG、1 个 JPEG。

## 8. 低质量照片覆盖

| 场景 | 状态 | 对应样本 |
|---|---|---|
| 低质量人物照片 | ready | `smoke_portrait_ready` |
| 低质量活动照片 | missing | `missing_low_quality_activity_photo` |
| 低质量环境或建筑照片 | ready | `smoke_architecture_low` |
| 低质量产品照片 | ready | `core_product_low_png` |

低质量活动照片仍需要用户提供可公开提交或可本地私有测试的素材。

## 9. 完整性校验

命令：

```text
D:\Codex\04_Visual-Master-Pro\.venv\Scripts\python.exe tests\tools\verify_golden_v046.py
```

结果：

```json
{
  "ready": 19,
  "missing": 60,
  "warnings": [],
  "errors": []
}
```

结论：PASS。校验覆盖必填字段、ready 文件存在性、SHA256、格式、尺寸、颜色模式、Alpha 标记、重复内容提示、private 路径是否被 Git 跟踪，以及公开来源元数据。

## 10. Phase 1 基线运行

命令：

```text
D:\Codex\04_Visual-Master-Pro\.venv\Scripts\python.exe tests\run_golden_v046.py
```

结果：

| 指标 | 数值 |
|---|---:|
| Ready 样本运行数 | 19 |
| 成功数量 | 19 |
| 失败数量 | 0 |
| `quality_1080p_pass=false` 数量 | 7 |
| 文件体积扩张警告数量 | 13 |
| 总处理耗时 | 54.988s |

`quality_1080p_pass=false` 样本：

```text
smoke_text_poster_cn_small_legacy
smoke_product_png_legacy
smoke_original_unprocessed_jpg
core_text_synthetic_microcopy
core_product_low_png
synthetic_gradient_band
synthetic_fine_line_table
```

## 11. 已知失败与缺口

- 普通 PNG 质量守门失败继续保留。
- 中文小字图质量守门失败继续保留。
- 部分样本文件体积扩张明显。
- Phase 2 中频细节与材质增强尚未开始。
- 部分样本当前分类结果与预期类型不一致，后续 T04 需要审计。
- Core Set 仍缺 12 个可提交样本，并有 5 个旧大图样本被标记为 excluded。
- Extended Set 当前是缺口表与未来参考色彩字段预留。
- 低质量活动照片仍缺少可提交或可私有测试样本。

## 12. 私有样本与隐私处理

当前 Private 数量为 0。`tests/golden_v046/private/` 已被 `.gitignore` 排除。完整性校验脚本会检查 private 路径是否被 Git 跟踪。

本次没有从互联网下载图片，没有提交客户私人照片，没有移动或覆盖原图。

## 13. 是否可以进入 T03

可以进入 T03。当前结论为 `PASS_WITH_SAMPLE_GAPS`，T03 应基于现有 ready 样本和缺口表拆分质量失败原因，不得把缺口伪装为已覆盖。
