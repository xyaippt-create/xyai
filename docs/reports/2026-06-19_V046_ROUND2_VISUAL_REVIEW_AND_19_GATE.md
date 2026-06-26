# V0.4.6 Round 2 视觉复核与 19 张黄金集准入判断

生成日期：2026-06-19

## 1. 本轮结论

结论：`WAIT_FOR_HUMAN_VISUAL_REVIEW`

是否建议进入 19 张黄金集：`等待人工视觉确认后再决定是否进入 19 张黄金集`

说明：7 张样本的证据材料完整，指标方向整体为正，但 Codex 不能替代人工完成真实肉眼视觉判断。本轮只允许得出“等待人工 100% 裁切复核”的准入结论，不能直接视为生产算法通过或冻结。

## 2. 证据完整性

- 7 张样本证据完整：PASS
- 每张样本均包含 original / frozen / candidate / full compare / same scale compare / 100% crops / 200% preview crops / metrics JSON。
- 100% 裁切每张不少于 12 个文件；200% 预览裁切每张不少于 12 个文件。

## 3. 逐样本准入表

| sample_id | 类型 | 证据 | 指标 | 肉眼预判 | 风险 | 体积收益比 | 19张准入 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `wechat_longscreenshot_2026-06-12_111900_080` | 文字/信息图 | PASS | PASS | NEEDS_HUMAN_REVIEW | REVIEW | ACCEPTABLE | WAIT_FOR_HUMAN_REVIEW |
| `green_c_product_kv` | 产品/商业KV | PASS | PASS | NEEDS_HUMAN_REVIEW | REVIEW | ACCEPTABLE | WAIT_FOR_HUMAN_REVIEW |
| `purple_beauty_product_kv` | 产品/商业KV | PASS | PASS | NEEDS_HUMAN_REVIEW | REVIEW | ACCEPTABLE | WAIT_FOR_HUMAN_REVIEW |
| `dji_horizontal_infographic` | 文字/信息图 | PASS | PASS | NEEDS_HUMAN_REVIEW | REVIEW | ACCEPTABLE | WAIT_FOR_HUMAN_REVIEW |
| `liu_qiangdong_commercial_portrait` | 人物/角色海报 | PASS | PASS | NEEDS_HUMAN_REVIEW | REVIEW | WEAK | WAIT_FOR_HUMAN_REVIEW |
| `wei_zhongxian_character_card` | 人物/角色海报 | PASS | PASS | NEEDS_HUMAN_REVIEW | REVIEW | WEAK | WAIT_FOR_HUMAN_REVIEW |
| `andy_lau_commercial_portrait` | 人物/角色海报 | PASS | PASS | NEEDS_HUMAN_REVIEW | REVIEW | WEAK | WAIT_FOR_HUMAN_REVIEW |

## 4. 指标汇总

| sample_id | edge_delta_proxy | texture_delta_proxy | p95_delta_e | saturation_delta | size_ratio |
| --- | --- | --- | --- | --- | --- |
| `wechat_longscreenshot_2026-06-12_111900_080` | 0.08083 | 0.135424 | 1.414214 | -5.8e-05 | 1.091413 |
| `green_c_product_kv` | 0.068722 | 0.102385 | 1.0 | 5.4e-05 | 1.103935 |
| `purple_beauty_product_kv` | 0.08068 | 0.113404 | 1.414214 | 4.7e-05 | 1.102005 |
| `dji_horizontal_infographic` | 0.406641 | 0.282267 | 1.732051 | 0.000304 | 1.100956 |
| `liu_qiangdong_commercial_portrait` | 0.55257 | 0.217462 | 2.236068 | 0.000986 | 1.13712 |
| `wei_zhongxian_character_card` | 0.55266 | 0.324381 | 2.236068 | 0.001231 | 1.123306 |
| `andy_lau_commercial_portrait` | 0.327169 | 0.188796 | 2.0 | 0.000623 | 1.116747 |

## 5. 体积收益比判断

- 体积倍率范围：1.091413 - 1.13712
- `ACCEPTABLE` 数量：4
- `WEAK` 数量：3
- `NOT_ACCEPTABLE` 数量：0

体积增长约 1.09x - 1.14x，不属于严重膨胀，但必须由人工确认 100% 裁切收益是否支撑体积增长。

## 6. 风险点

- 文字风险：未从指标发现强风险，但需要人工检查字腔、灰边、重影、断笔。
- Logo 风险：未从指标发现强风险，但产品包装 Logo 和品牌字样必须人工检查。
- 人脸风险：候选对肤色变化指标较小，但人脸自然度、塑料感、假锐化必须人工检查。
- 品牌色风险：饱和度变化很小，但绿 C 橙色、DERMAFIRM 紫色、金色高光需人工复核。
- 低频平滑区风险：白底、浅灰背景、天空/云雾、海报渐变和高光区域必须人工复核。
- 体积收益比风险：所有样本均有体积增长，收益必须由视觉证据支撑。

## 7. 逐样本视觉复核索引

### wechat_longscreenshot_2026-06-12_111900_080

- 类型：文字/信息图
- 重点检查：小字清晰度、灰字/黑字边缘、灰边黑边重影糊边、白底和浅灰背景是否变脏
- 原图：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\01_original\wechat_longscreenshot_2026-06-12_111900_080.png`
- Frozen：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\02_frozen\wechat_longscreenshot_2026-06-12_111900_080.png`
- Candidate：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\03_candidate\wechat_longscreenshot_2026-06-12_111900_080.png`
- 整图对比：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\04_full_compare\wechat_longscreenshot_2026-06-12_111900_080.png`
- 同尺度对比：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\05_same_scale_compare\wechat_longscreenshot_2026-06-12_111900_080.png`
- 100% 裁切目录：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\06_crops_100pct\wechat_longscreenshot_2026-06-12_111900_080`（12 个文件）
- 200% 预览裁切目录：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\07_crops_200pct_preview\wechat_longscreenshot_2026-06-12_111900_080`（12 个文件）
- 指标：edge_delta_proxy=0.08083，texture_delta_proxy=0.135424，p95_delta_e=1.414214，saturation_delta=-5.8e-05，size_ratio=1.091413
- 当前判断：证据 PASS；指标 PASS；风险 REVIEW；19 张准入 WAIT_FOR_HUMAN_REVIEW
- 风险点：体积增长需要人工确认收益支撑；必须确认无文字、Logo、人脸、品牌色、低频平滑区损伤。

### green_c_product_kv

- 类型：产品/商业KV
- 重点检查：包装文字、Logo、透明瓶体、高光、白色平滑区、产品轮廓、透明材质是否塑料化
- 原图：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\01_original\green_c_product_kv.png`
- Frozen：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\02_frozen\green_c_product_kv.png`
- Candidate：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\03_candidate\green_c_product_kv.png`
- 整图对比：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\04_full_compare\green_c_product_kv.png`
- 同尺度对比：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\05_same_scale_compare\green_c_product_kv.png`
- 100% 裁切目录：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\06_crops_100pct\green_c_product_kv`（12 个文件）
- 200% 预览裁切目录：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\07_crops_200pct_preview\green_c_product_kv`（12 个文件）
- 指标：edge_delta_proxy=0.068722，texture_delta_proxy=0.102385，p95_delta_e=1.0，saturation_delta=5.4e-05，size_ratio=1.103935
- 当前判断：证据 PASS；指标 PASS；风险 REVIEW；19 张准入 WAIT_FOR_HUMAN_REVIEW
- 风险点：体积增长需要人工确认收益支撑；必须确认无文字、Logo、人脸、品牌色、低频平滑区损伤。

### purple_beauty_product_kv

- 类型：产品/商业KV
- 重点检查：DERMAFIRM 字样、紫色品牌色、银色高光、产品边缘、背景渐变、色带或脏块
- 原图：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\01_original\purple_beauty_product_kv.png`
- Frozen：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\02_frozen\purple_beauty_product_kv.png`
- Candidate：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\03_candidate\purple_beauty_product_kv.png`
- 整图对比：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\04_full_compare\purple_beauty_product_kv.png`
- 同尺度对比：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\05_same_scale_compare\purple_beauty_product_kv.png`
- 100% 裁切目录：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\06_crops_100pct\purple_beauty_product_kv`（12 个文件）
- 200% 预览裁切目录：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\07_crops_200pct_preview\purple_beauty_product_kv`（12 个文件）
- 指标：edge_delta_proxy=0.08068，texture_delta_proxy=0.113404，p95_delta_e=1.414214，saturation_delta=4.7e-05，size_ratio=1.102005
- 当前判断：证据 PASS；指标 PASS；风险 REVIEW；19 张准入 WAIT_FOR_HUMAN_REVIEW
- 风险点：体积增长需要人工确认收益支撑；必须确认无文字、Logo、人脸、品牌色、低频平滑区损伤。

### dji_horizontal_infographic

- 类型：文字/信息图
- 重点检查：中文小字、小图标、线条、浅色背景、中间结构、连接线、底部信息区
- 原图：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\01_original\dji_horizontal_infographic.png`
- Frozen：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\02_frozen\dji_horizontal_infographic.png`
- Candidate：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\03_candidate\dji_horizontal_infographic.png`
- 整图对比：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\04_full_compare\dji_horizontal_infographic.png`
- 同尺度对比：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\05_same_scale_compare\dji_horizontal_infographic.png`
- 100% 裁切目录：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\06_crops_100pct\dji_horizontal_infographic`（12 个文件）
- 200% 预览裁切目录：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\07_crops_200pct_preview\dji_horizontal_infographic`（12 个文件）
- 指标：edge_delta_proxy=0.406641，texture_delta_proxy=0.282267，p95_delta_e=1.732051，saturation_delta=0.000304，size_ratio=1.100956
- 当前判断：证据 PASS；指标 PASS；风险 REVIEW；19 张准入 WAIT_FOR_HUMAN_REVIEW
- 风险点：体积增长需要人工确认收益支撑；必须确认无文字、Logo、人脸、品牌色、低频平滑区损伤。

### liu_qiangdong_commercial_portrait

- 类型：人物/角色海报
- 重点检查：人脸自然度、肤色、发丝、服装纹理、背景城市、中文标题、假锐化或磨皮感
- 原图：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\01_original\liu_qiangdong_commercial_portrait.png`
- Frozen：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\02_frozen\liu_qiangdong_commercial_portrait.png`
- Candidate：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\03_candidate\liu_qiangdong_commercial_portrait.png`
- 整图对比：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\04_full_compare\liu_qiangdong_commercial_portrait.png`
- 同尺度对比：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\05_same_scale_compare\liu_qiangdong_commercial_portrait.png`
- 100% 裁切目录：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\06_crops_100pct\liu_qiangdong_commercial_portrait`（12 个文件）
- 200% 预览裁切目录：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\07_crops_200pct_preview\liu_qiangdong_commercial_portrait`（12 个文件）
- 指标：edge_delta_proxy=0.55257，texture_delta_proxy=0.217462，p95_delta_e=2.236068，saturation_delta=0.000986，size_ratio=1.13712
- 当前判断：证据 PASS；指标 PASS；风险 REVIEW；19 张准入 WAIT_FOR_HUMAN_REVIEW
- 风险点：体积增长需要人工确认收益支撑；必须确认无文字、Logo、人脸、品牌色、低频平滑区损伤。

### wei_zhongxian_character_card

- 类型：人物/角色海报
- 重点检查：毛发、服饰纹理、小字、红色标签、边框线、暗部结块、角色质感
- 原图：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\01_original\wei_zhongxian_character_card.png`
- Frozen：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\02_frozen\wei_zhongxian_character_card.png`
- Candidate：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\03_candidate\wei_zhongxian_character_card.png`
- 整图对比：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\04_full_compare\wei_zhongxian_character_card.png`
- 同尺度对比：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\05_same_scale_compare\wei_zhongxian_character_card.png`
- 100% 裁切目录：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\06_crops_100pct\wei_zhongxian_character_card`（12 个文件）
- 200% 预览裁切目录：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\07_crops_200pct_preview\wei_zhongxian_character_card`（12 个文件）
- 指标：edge_delta_proxy=0.55266，texture_delta_proxy=0.324381，p95_delta_e=2.236068，saturation_delta=0.001231，size_ratio=1.123306
- 当前判断：证据 PASS；指标 PASS；风险 REVIEW；19 张准入 WAIT_FOR_HUMAN_REVIEW
- 风险点：体积增长需要人工确认收益支撑；必须确认无文字、Logo、人脸、品牌色、低频平滑区损伤。

### andy_lau_commercial_portrait

- 类型：人物/角色海报
- 重点检查：人脸和手部、金色高光、中文小字、碎片边缘、背景低频、金属高光是否发灰
- 原图：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\01_original\andy_lau_commercial_portrait.png`
- Frozen：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\02_frozen\andy_lau_commercial_portrait.png`
- Candidate：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\03_candidate\andy_lau_commercial_portrait.png`
- 整图对比：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\04_full_compare\andy_lau_commercial_portrait.png`
- 同尺度对比：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\05_same_scale_compare\andy_lau_commercial_portrait.png`
- 100% 裁切目录：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\06_crops_100pct\andy_lau_commercial_portrait`（12 个文件）
- 200% 预览裁切目录：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_targeted\07_crops_200pct_preview\andy_lau_commercial_portrait`（12 个文件）
- 指标：edge_delta_proxy=0.327169，texture_delta_proxy=0.188796，p95_delta_e=2.0，saturation_delta=0.000623，size_ratio=1.116747
- 当前判断：证据 PASS；指标 PASS；风险 REVIEW；19 张准入 WAIT_FOR_HUMAN_REVIEW
- 风险点：体积增长需要人工确认收益支撑；必须确认无文字、Logo、人脸、品牌色、低频平滑区损伤。


## 8. Round 2.1 修正方向（如人工复核不通过）

如果人工复核认为收益不足或存在风险，只允许做以下小修：

1. 缩小增强区域 mask；
2. 降低中频增强强度；
3. 加强文字、Logo、人脸、肤色、品牌色、高光、平滑背景保护；
4. 降低体积增长；
5. 优化低频平滑区保护；
6. 调整不同样本类型的区域资格判断；
7. 不回到全图通透、全图锐化、全图对比、全图饱和路线。
