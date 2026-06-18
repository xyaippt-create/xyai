# V0.4.6 Phase 6 质量收口、辅助功能完成与后台冻结报告

生成日期：2026-06-18

## 1. Git 基线

- Phase 5 冻结 Commit：`cdbd01284516376a0fe872264ba26dcbeab195ab`
- Phase 6 开始 HEAD：`cdbd01284516376a0fe872264ba26dcbeab195ab`
- 本报告对应阶段：V0.4.6 Phase 6

## 2. 本阶段范围

Phase 6 不改变前台 UI，不进入 Gemini，不进入 2K/4K，不修改 Phase 1-5 的核心画质目标。

本阶段完成：

- 最终交付质量门与体积收益比判断；
- 渐变、高光和平滑区域风险守门；
- 默认输出目录收口到 `D:\影界文件\输出成品`；
- 输出目录、最终文件路径和最终交付状态字段固定；
- 诊断反馈 ZIP V1；
- API/SSE 与正式链路回归；
- 10 张定向样本与 19 张黄金集回归。

## 3. 10 张定向样本结果

执行目录：

- `tests/results/v046_phase6_targeted/`

总体结果：

- 完成：10/10
- `final_delivery_status=PASS`：4
- `final_delivery_status=PASS_WITH_LIMITATION`：6
- `final_delivery_status=FAIL`：0
- 透明 PNG：Alpha 保持，交付状态 PASS
- 平滑区域 fallback：0
- 体积 fallback：1，样本 `synthetic_highlight`

主要限制：

- `cn_small_text`、`ordinary_jpg`、`ordinary_png`、`real_product_photo`、`synthetic_gradient` 仍受历史 `quality_1080p_pass=false` 影响，交付状态为 `PASS_WITH_LIMITATION`。
- `synthetic_highlight` 触发 `very_large_size_limited_benefit`，交付状态为 `PASS_WITH_LIMITATION`。

## 4. 19 张黄金集回归结果

执行目录：

- `tests/results/v046_phase6_golden_regression/`

总体结果：

- 完成：19/19
- 质量门通过数量：12
- `final_delivery_status=PASS`：9
- `final_delivery_status=PASS_WITH_LIMITATION`：10
- `final_delivery_status=FAIL`：0
- 平均文件体积倍率：33.580532
- 体积 fallback 数量：2
- 平滑区域 fallback 数量：1

触发体积 fallback：

| sample_id | reason | file_size_ratio |
| --- | --- | ---: |
| `synthetic_highlight_clip` | `very_large_size_limited_benefit` | 18.8099 |
| `synthetic_brand_color_bars` | `very_large_size_limited_benefit` | 14.5139 |

触发平滑区域 fallback：

| sample_id | reason | gradient | band | highlight |
| --- | --- | --- | --- | --- |
| `synthetic_alpha_edges` | `smooth_region_guard` | low | low | high |

## 5. 文件体积控制

Phase 6 没有强行重编码或压缩正式输出，而是在已有 `compression_gate` 之后增加交付层判断：

- 记录 `phase6_size_growth_ratio`；
- 记录 `phase6_visible_benefit_score`；
- 记录 `phase6_benefit_size_ratio`；
- 对“体积显著增长但可见收益不足”的样本降级为 `PASS_WITH_LIMITATION`；
- 不把历史体积扩张伪装成已解决。

结论：体积控制门已生效。历史文件体积扩张仍作为已知问题保留。

## 6. 渐变、高光和平滑区域结果

新增最小诊断字段：

- `phase6_gradient_risk`
- `phase6_band_risk`
- `phase6_highlight_pollution_risk`
- `phase6_flat_region_uniformity`
- `phase6_smooth_region_fallback`
- `phase6_smooth_region_fallback_reason`

19 张黄金集中仅 `synthetic_alpha_edges` 触发平滑区域保护，原因是高光污染风险为 high。未发现 Phase 6 引入的新增颜色漂移。

## 7. 最终质量门分类

交付状态字段：

- `final_delivery_status`
- `final_delivery_reason`
- `final_delivery_risk_level`
- `final_delivery_recommended_usage`

规则：

- `PASS`：可按 1080P 屏幕、PPT 或 Web 交付使用；
- `PASS_WITH_LIMITATION`：输出存在历史质量门、体积收益比或平滑区域风险，需要人工复核；
- `FAIL`：阻断交付。

本轮未出现 `FAIL`。

## 8. 默认输出目录与输出路径

默认输出目录：

- `D:\影界文件\输出成品`

API 结果：

- `default_output_dir_match=true`
- `final_output_url_ok=true`
- 重名输出处理：`rename_collision_distinct=true`
- 权限失败：不可用输出路径返回 HTTP 400

最终输出字段已固定：

- `output_directory`
- `output_directory_source`
- `final_output_path`
- `final_output_filename`
- `final_output_url`

## 9. 反馈诊断 ZIP V1

反馈目录：

- `D:\影界文件\诊断反馈`

API 测试生成文件：

- `D:\影界文件\诊断反馈\影界诊断_V046_task_20260618_234413_d843429c_20260618_234428.zip`

ZIP 内容：

- `manifest.json`
- `task_summary.json`
- `diagnostics.json`
- `pipeline_trace.json`
- `quality_metrics.json`
- `system_info.json`
- `error_summary.txt`
- `README.txt`

确认：

- 不包含原图；
- 不包含最终输出图；
- 已脱敏绝对路径、邮箱和敏感字段；
- `feedback_bundle_status=PASS`。

## 10. API/SSE 回归

已验证：

- JPG 上传：PASS
- 普通 PNG 上传：PASS
- 透明 PNG 上传：PASS
- 中文小字图上传：PASS
- 任务轮询：PASS
- SSE：PASS
- SSE 重连：PASS
- 双订阅：PASS
- 失败任务 SSE：PASS
- `final_output_url`：PASS
- 最终文件真实存在：PASS
- `pipeline_call_count=1`：PASS

## 11. 主动色偏修复真实样本状态

Phase 6 未处理色彩算法。主动色偏修复属于 Phase 5 后续验证范围。

当前状态：

- 真实主动色偏修复样本：`SAMPLE_GAP`
- 未找到足够干净的真实偏色照片用于 RC1 前最终确认；
- 该缺口不阻断 Phase 6 后台冻结，但阻断“主动色偏修复已充分验证”的表述。

## 12. 已知问题

- 历史文件体积扩张仍存在；
- 部分文字、PNG 或合成样本仍受历史 `quality_1080p_pass=false` 影响；
- 部分高光、渐变或平滑区域样本需要人工复核；
- 华为历史色彩问题仍归入 Phase 5；
- 真实主动色偏修复样本仍需补齐。

## 13. 冻结结论

结论：`PASS_WITH_KNOWN_ISSUES`

允许：

- 后台能力冻结；
- 进入 Gemini UI 阶段；
- 准备 RC1。

限制：

- 不得宣称历史文件体积问题已完全解决；
- 不得宣称主动色偏修复已完成真实样本闭环；
- UI 阶段必须继续展示 `PASS_WITH_LIMITATION` 和人工复核状态。
