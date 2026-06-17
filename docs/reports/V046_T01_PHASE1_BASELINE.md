# V0.4.6 T01 Phase 1 Baseline Freeze Report

Date: 2026-06-17
Project: VisualMasterPro / 影界
Task: T01 / T01.1 / T01.2A Phase 1 基线冻结与文档收口
Conclusion: PASS

## 1. 执行摘要

T01 完成了 V0.4.6 Phase 1 工作区的只读基线审计：四张核心样本已处理，原图 SHA-256 保持不变，最终输出进入隔离测试目录，诊断字段已采集，V0.4.5.3 API/SSE 回归通过。

T01.1 完成了 Git 基线冻结与复测。T01.2A 进一步核对 `8bf051c..e98afe8` 的差异性质，确认该区间只包含报告与轻量 API 诊断证据变化，不包含生产代码、前端、依赖或运行配置变化。

两级基线关系：

| 项目 | 值 |
|---|---|
| Phase 1 生产代码冻结 Commit | `8bf051cd3fcc6e8f7c363c2b43eac819c1c4e6b3` |
| Phase 1 生产代码冻结短 Commit | `8bf051c` |
| Phase 1 完整基线 Commit | `e98afe81ec401f04458fbaccaaa0d80b81f2fda8` |
| Phase 1 完整基线短 Commit | `e98afe8` |
| Phase 1 基线 Tag | `v0.4.6-phase1-baseline` |
| Tag 指向 | `e98afe81ec401f04458fbaccaaa0d80b81f2fda8` |

T02 condition: 可以进入T02

## 2. Git 与代码状态

原始稳定底座：

| 项目 | 值 |
|---|---|
| Branch | `main` |
| V0.4.5.3 底座 HEAD | `780d49bd470a1015245f9d359e03704ea6bcc5c2` |
| V0.4.5.3 短 HEAD | `780d49b` |
| HEAD time | `2026-06-16 07:54:02 +0800` |
| HEAD subject | `V0.4.5.3 stable output folder native picker and output_dir pipeline` |

T01 初始状态曾为 `PASS_WITH_BLOCKERS`，原因是当时 Phase 1 生产代码尚未形成可恢复的 Git 提交。T01.1 后该阻断已解除。

`8bf051c..e98afe8` 差异核对结果：

| 文件 | 分类 | 说明 |
|---|---|---|
| `docs/reports/V046_T01_PHASE1_BASELINE.md` | B. 基线报告或诊断证据 | 增补 T01.1 复测和基线关系。 |
| `tests/diagnostics/v0453_api_pipeline_results.json` | B. 基线报告或诊断证据 | 刷新 API/SSE 回归轻量 JSON。 |

未发现以下类别变化：

| 类别 | 结果 |
|---|---|
| E. 生产代码 | 无 |
| F. 前端代码 | 无 |
| G. 影响运行行为的配置或依赖 | 无 |
| H. 来源不明 | 无 |

## 3. 运行环境

| 项目 | 值 |
|---|---|
| OS | `Windows-11-10.0.26200-SP0` |
| Python | `3.12.13` |
| Virtual env | `D:\Codex\04_Visual-Master-Pro\.venv` |
| FastAPI | `0.137.1` |
| Uvicorn | `0.49.0` |
| OpenCV | `4.13.0` |
| NumPy | `2.4.6` |
| Pillow | `12.2.0` |
| Node.js | `v24.16.0` |
| npm | `11.13.0` |
| React | `^18.2.0` |
| Vite | `^5.2.0` |
| Tailwind CSS | `^3.4.1` |
| Backend command | `D:\Codex\04_Visual-Master-Pro\.venv\Scripts\python.exe main.py --web` |
| Frontend command | `npm.cmd run dev` |
| Backend port | `8787` |
| Frontend port | `5173` |
| Env vars captured | `APPDATA=SET` |

## 4. 核心样本清单

四张原图在 T01 / T01.1 中均保持 SHA-256 不变。

| 样本 | 输入 | 格式 | 大小 | 原图 SHA-256 | 原图未变 |
|---|---|---:|---:|---|---|
| JPG | `D:\Codex\04_Visual-Master-Pro\tests\outputs\v036_api_validation\output\images\case_original_jpg_vmp_v036_optimized.jpg` | JPEG | 7,743 B | `e63b4d7e91e5bbea6c3a1e70402671381e977e86a4687b90fae5e72121096fb7` | true |
| 普通 PNG | `D:\Codex\04_Visual-Master-Pro\runtime\v044_validation\inputs\test_1.png` | PNG | 3,476 B | `de686150a6bb65246fc308e98c136a300774e776adbb363155f7294a4f71e663` | true |
| 透明 PNG | `D:\Codex\04_Visual-Master-Pro\tests\outputs\v036_backend_validation_final\input\realalpha.png` | PNG RGBA | 39,614 B | `886a52a64c1057466bcd1549d4ee7299058e0281782edcd43b21198f21fa4385` | true |
| 中文小字图 | `D:\Codex\04_Visual-Master-Pro\backend\backend_uploads\高清测试.png` | PNG | 2,107 B | `178449c424d745333c6c5c476386bf24260772b2e406974f94611e1493a42cfa` | true |

## 5. 三方输出对照

V0.4.5.3 历史输出选择规则：在历史诊断输出目录中选择匹配 `*20260617_08*.png` 的最新文件，避免把 Phase 1 后续 14:xx 复跑输出误作历史基线。

| 样本 | V0.4.5.3 历史输出 | V0.4.6 Phase 1 输出 | 输出存在 |
|---|---|---|---|
| JPG | `tests\diagnostics\output\core\JPG\case_original_jpg_vmp_v036_optimized_影界高清_1080P_fidelity_20260617_084128.png` | `tests\results\v046_phase1_baseline\JPG\case_original_jpg_vmp_v036_optimized_影界高清_1080P_fidelity_20260617_160604.png` | true |
| 普通 PNG | `tests\diagnostics\output\core\普通PNG\test_1_影界高清_1080P_fidelity_20260617_084130.png` | `tests\results\v046_phase1_baseline\普通PNG\test_1_影界高清_1080P_fidelity_20260617_160606.png` | true |
| 透明 PNG | `tests\diagnostics\output\core\透明PNG\realalpha_影界高清_1080P_fidelity_20260617_084131.png` | `tests\results\v046_phase1_baseline\透明PNG\realalpha_影界高清_1080P_fidelity_20260617_160608.png` | true |
| 中文小字图 | `tests\diagnostics\output\core\中文小字图\高清测试_影界高清_1080P_text_safe_20260617_084134.png` | `tests\results\v046_phase1_baseline\中文小字图\高清测试_影界高清_1080P_text_safe_20260617_160611.png` | true |

## 6. 诊断字段摘要

T01.1 复测结果如下，诊断数值保持与 T01 核心结论一致，耗时允许轻微波动。

| 样本 | image_type | 输出 | 输出大小 | 耗时 | quality_1080p_pass | Level | text_clarity | small_text | edge_clean | pseudo_hd | artifact | 结果 |
|---|---|---:|---:|---:|---|---|---:|---:|---:|---|---|---|
| JPG | `text_poster` | 1622x1080 PNG | 94,805 B | 2.221s | true | `standard` | 46.6452 | 41.1161 | 46.6452 | low | low | PASS |
| 普通 PNG | `product_kv` | 1728x1080 PNG | 190,985 B | 2.050s | false | `failed` | 29.8266 | 28.1199 | 29.8266 | low | low | PASS_WITH_KNOWN_ISSUE |
| 透明 PNG | `product_kv` | 1920x1080 PNG | 651,143 B | 2.655s | true | `standard` | 39.6729 | 37.4538 | 39.6729 | low | low | PASS |
| 中文小字图 | `text_poster` | 1620x1080 PNG | 121,992 B | 1.809s | false | `failed` | 28.1225 | 25.3631 | 28.1225 | low | low | PASS_WITH_KNOWN_ISSUE |

附加诊断字段：

| 样本 | `v046_text_engine_active` | `v046_quality_profile` |
|---|---|---|
| JPG | true | `1080P+ small text readability` |
| 普通 PNG | false | `1080P+ small text readability` |
| 透明 PNG | false | `1080P+ small text readability` |
| 中文小字图 | true | `1080P+ small text readability` |

T01 初始审计值保留如下，不作为 T01.2A 重新计算结果：

| 样本 | 输出 | 输出大小 | 耗时 | quality_1080p_pass | Level | text_clarity | small_text | edge_clean | 结果 |
|---|---:|---:|---:|---|---|---:|---:|---:|---|
| JPG | 1622x1080 PNG | 94,805 B | 2.122s | true | `standard` | 46.6452 | 41.1161 | 46.6452 | PASS |
| 普通 PNG | 1728x1080 PNG | 190,985 B | 2.568s | false | `failed` | 29.8266 | 28.1199 | 29.8266 | PASS_WITH_KNOWN_ISSUE |
| 透明 PNG | 1920x1080 PNG | 651,143 B | 3.507s | true | `standard` | 39.6729 | 37.4538 | 39.6729 | PASS |
| 中文小字图 | 1620x1080 PNG | 121,992 B | 2.608s | false | `failed` | 28.1225 | 25.3631 | 28.1225 | PASS_WITH_KNOWN_ISSUE |

T01 初始输出路径保留如下：

| 样本 | T01 初始输出 |
|---|---|
| JPG | `tests\results\v046_phase1_baseline\JPG\case_original_jpg_vmp_v036_optimized_影界高清_1080P_fidelity_20260617_150222.png` |
| 普通 PNG | `tests\results\v046_phase1_baseline\普通PNG\test_1_影界高清_1080P_fidelity_20260617_150224.png` |
| 透明 PNG | `tests\results\v046_phase1_baseline\透明PNG\realalpha_影界高清_1080P_fidelity_20260617_150226.png` |
| 中文小字图 | `tests\results\v046_phase1_baseline\中文小字图\高清测试_影界高清_1080P_text_safe_20260617_150230.png` |

## 7. API 与 SSE 回归

命令：

```text
D:\Codex\04_Visual-Master-Pro\.venv\Scripts\python.exe tests\diagnostics\test_v0453_api_pipeline.py
```

结果：PASS

| 样本 | `/api/upload` | 任务轮询 | SSE | SSE 重连 | 双 SSE 订阅 | `final_output_url` |
|---|---|---|---|---|---|---|
| JPG | PASS | PASS | PASS | PASS | PASS | PASS |
| 普通 PNG | PASS | PASS | PASS | PASS | PASS | PASS |
| 透明 PNG | PASS | PASS | PASS | PASS | PASS | PASS |
| 中文小字图 | PASS | PASS | PASS | PASS | PASS | PASS |

失败任务 SSE：

| 用例 | 结果 | 说明 |
|---|---|---|
| `diagnostic_failed_task` | PASS | SSE 返回 failed 状态，并按 `[DONE]` 行为结束。 |

API 回归确认：上传后会启动后台处理，轮询可到达 `completed`，SSE 重连/双订阅不会重复处理，`final_output_url` 指向可访问的真实输出文件。

## 8. 目录隔离

| 路径角色 | 路径 | 存在 |
|---|---|---|
| Runtime uploads legacy path | `D:\Codex\04_Visual-Master-Pro\runtime\uploads` | false |
| Actual upload cache | `D:\Codex\04_Visual-Master-Pro\runtime\v04_inputs` | true |
| Runtime work | `D:\Codex\04_Visual-Master-Pro\runtime\work` | true |
| Logs | `D:\Codex\04_Visual-Master-Pro\logs` | true |
| T01 diagnostics | `D:\Codex\04_Visual-Master-Pro\runtime\diagnostics\v046_t01` | true |
| V0.4.6 golden directory | `D:\Codex\04_Visual-Master-Pro\tests\golden_v046` | false |
| T01 output directory | `D:\Codex\04_Visual-Master-Pro\tests\results\v046_phase1_baseline` | true |
| API diagnostic output directory | `D:\Codex\04_Visual-Master-Pro\tests\diagnostics\output\api` | true |
| Formal default output directory | `C:\Users\xyppt\Desktop\雪原Ai增强引擎\输出成品` | true |

T01 输出隔离在 `tests\results\v046_phase1_baseline`。API 回归输出隔离在 `tests\diagnostics\output\api`。`runtime\work` 仅作为临时处理目录，不作为正式 final 输出目录。

## 9. 已知问题

| 严重性 | 项目 | 状态 |
|---|---|---|
| Known issue | 普通 PNG quality gate | `quality_1080p_pass=false`，`quality_1080p_level=failed`，本轮未修复。 |
| Known issue | 中文小字图 quality gate | `quality_1080p_pass=false`，`quality_1080p_level=failed`，本轮未修复。 |
| Known issue | 输出体积扩张警告 | 四张样本均存在文件体积扩张警告。 |
| Non-blocking audit note | `tests\golden_v046` absent | T01/T01.1 使用隔离结果输出，不等同于正式黄金测试集。 |
| Roadmap note | Phase 2 未开始 | 中频细节与材质增强尚未进入 Phase 2 开发。 |

## 10. 与历史版本的差异

V0.4.5.3 已修复上传、SSE、final 输出路径链路。T01/T01.1 确认这些回归项在 V0.4.6 Phase 1 基线上仍然通过。

V0.4.6 Phase 1 增加了 1080P+ 小字可读性相关诊断字段，包括 `small_text_readability_score`、`text_edge_clean_score`、`v046_text_engine_active` 和 `v046_quality_profile`。这些字段已在核心结果 JSON 中可见，API 字段保持兼容。

V0.4.5.3 对照目前主要来自历史诊断输出，选择规则为 `*20260617_08*.png`。

## 11. T01.1 Git 基线冻结

T01.1 于 2026-06-17 执行，完成 Phase 1 生产代码冻结和复测。

| 项目 | 值 |
|---|---|
| Phase 1 生产代码冻结 Commit | `8bf051cd3fcc6e8f7c363c2b43eac819c1c4e6b3` |
| Phase 1 生产代码冻结短 Commit | `8bf051c` |
| Commit time | `2026-06-17 16:05:23 +0800` |
| Commit subject | `V0.4.6 Phase 1 small-text readability baseline` |
| Baseline retest started | `2026-06-17T16:06:04` |
| Baseline retest finished | `2026-06-17T16:06:13` |
| Baseline retest result | PASS |
| API/SSE regression result | PASS |

差异审查结果：

| 区域 | 结果 |
|---|---|
| Phase 1 小字可读性变化 | 已确认在 `backend/v036_output_core.py` 与 `engine/algorithms/text_clarity.py` 中。 |
| V0.4.5.3 task/SSE 基线延续 | 已确认在 `main.py` 中，用于保持上传、轮询、SSE 和 final 输出行为稳定。 |
| Phase 2 / 中频算法变化 | 未发现。 |
| 临时 debug 或测试专用生产逻辑 | 未发现。 |
| 本地盘符预览 URL 或前端硬编码路径 | 未发现。 |
| API/SSE 契约漂移 | 回归 PASS，未发现字段重命名或前端契约变化。 |
| 正式输出选择漂移 | 未发现，final 输出路径与后缀保护仍有效。 |

## 12. T01.2A 文档收口

T01.2A 采用以下正式基线关系，不移动现有 Tag，不重写 Git 历史：

| 项目 | 值 |
|---|---|
| Phase 1 生产代码冻结 Commit | `8bf051cd3fcc6e8f7c363c2b43eac819c1c4e6b3` |
| Phase 1 完整基线 Commit | `e98afe81ec401f04458fbaccaaa0d80b81f2fda8` |
| Phase 1 基线 Tag | `v0.4.6-phase1-baseline` |
| Tag 指向 | `e98afe81ec401f04458fbaccaaa0d80b81f2fda8` |
| Tag 与 HEAD 关系 | Tag 固定完整基线提交；T01.2A 文档提交允许位于 Tag 之后。 |

T01.2A 只修复文档乱码、版本关系和 Markdown 格式，不修改 Phase 1 生产代码。

最终结论：可以进入 T02 黄金测试集建设；T02 不负责修改画质算法，不负责修复 `quality_1080p_pass`，T02 完成前不得进入 Phase 2。
