# V0.4.6 Round 2.1 人工视觉复核辅助指南

生成时间：2026-06-20  
项目路径：`D:\Codex\04_Visual-Master-Pro`  
证据目录：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted`  
依据文件：`tests/results/v046_quality_lift_round2_1_targeted/manifest.json`

## 1. 当前结论

```text
WAIT_FOR_HUMAN_VISUAL_REVIEW / NOT_READY_FOR_19 / EVIDENCE_COMPLETE
```

本报告只做人工复核证据归纳，不重新生成图片，不重新运行算法，不修改 metrics，不修改正式生产代码，不接入正式生产链，不运行 19 张黄金集，不冻结。

## 2. 人工复核总原则

本轮不是确认“工程是否能跑”，而是确认 Round 2.1 是否出现真实可见收益，并且没有破坏中文文字、Logo、品牌色、人脸、低频平滑区域和高光区域。

复核顺序建议：

1. 先看 `review_index_chatgpt.html` 的整图和同尺度对比，确认是否有全局色偏、低频脏块或高光污染。
2. 再看每张样本的 100% 裁切，判断真实细节、文字边缘、Logo、脸部和产品边缘。
3. 最后看 200% preview 裁切，只用于辅助观察边缘和脏块，不把 200% 放大感当作真实提升。

必须保持当前门禁：

```text
不要进入19张黄金集
不要冻结
不要接正式生产链
Gemini复核建议：YES
```

## 3. 复核优先级总表

| 优先级 | sample_id | 当前预判 | risk_status | size_benefit | 复核重点 | 当前建议 |
|---|---|---:|---|---|---|---|
| P0 | `wechat_longscreenshot_2026-06-12_111900_080` | NEEDS_HUMAN_REVIEW | REJECT | NOT_ACCEPTABLE | 文字密集、灰字/黑字边缘、白底洁净、体积收益比 | 必须进入 Round 2.2 |
| P0 | `green_c_product_kv` | MINOR_POSITIVE | REVIEW | ACCEPTABLE | 瓶身轮廓、透明材质、Logo、包装文字、白色平滑面 | 可能成为 MINOR_POSITIVE |
| P0 | `dji_horizontal_infographic` | MINOR_POSITIVE | REVIEW | ACCEPTABLE | 中文小字、图标线条、浅色背景、信息区边缘 | 可能成为 MINOR_POSITIVE |
| P1 | `andy_lau_commercial_portrait` | MINOR_POSITIVE | REVIEW | WEAK | 非脸部材质、金色高光、碎片边缘、手部和中文小字 | 可能成为 MINOR_POSITIVE，需重点看人脸和手 |
| P1 | `purple_beauty_product_kv` | MINOR_POSITIVE | REVIEW | ACCEPTABLE | DERMAFIRM 字样、紫色品牌色、银色高光、产品边缘 | 可能成为 MINOR_POSITIVE |
| P1 | `liu_qiangdong_commercial_portrait` | MINOR_POSITIVE | REVIEW | WEAK | 服装纹理、背景城市、脸部和肤色保护 | 倾向 Round 2.2 观察池 |
| P1 | `wei_zhongxian_character_card` | MINOR_POSITIVE | REVIEW | WEAK | 毛发、服饰纹理、小字、红色标签、边框线 | 倾向 Round 2.2 观察池 |

## 4. 逐样本复核指南

### 4.1 wechat_longscreenshot_2026-06-12_111900_080

复核优先级：P0  
当前风险：`risk_status=REJECT`，`size_benefit_ratio_judgement=NOT_ACCEPTABLE`  
关键指标：

```text
edge_delta_proxy=0.053305
texture_delta_proxy=0.079538
p95_delta_e=1.000000
saturation_delta=0.000044
size_ratio=1.154430
size_delta_vs_round2_bytes=48708
gate_to_19=NO
```

最值得看的裁切：

```text
100%:
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\wechat_longscreenshot_2026-06-12_111900_080\text_logo__frozen.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\wechat_longscreenshot_2026-06-12_111900_080\text_logo__round2.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\wechat_longscreenshot_2026-06-12_111900_080\text_logo__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\wechat_longscreenshot_2026-06-12_111900_080\low_frequency_bg__round2_1.png

200% preview:
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\08_crops_200pct_preview\wechat_longscreenshot_2026-06-12_111900_080\text_logo__round2_1__200pct_preview.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\08_crops_200pct_preview\wechat_longscreenshot_2026-06-12_111900_080\low_frequency_bg__round2_1__200pct_preview.png
```

看哪里：灰字、黑字、小图标、白底和浅灰底、字腔、笔画端点。  
判断什么：文字边缘是否比 frozen 更稳，是否减少灰边；Round 2.1 是否比 Round 2 更干净；体积增长是否有足够可见收益支撑。  
通过标准：小字边缘更稳、白底无脏雾、无断笔、无黑边/灰边扩大，并且收益足以解释 1.154x 体积。  
失败标准：只是变大或轻微锐化，文字仍糊、灰边更重、白底变脏、体积增长无肉眼收益。  
结论建议：当前必须进入 Round 2.2，优先压低文字密集图强度与体积增长。

### 4.2 green_c_product_kv

复核优先级：P0  
当前风险：`risk_status=REVIEW`，`size_benefit_ratio_judgement=ACCEPTABLE`  
关键指标：

```text
edge_delta_proxy=0.073010
texture_delta_proxy=0.110356
p95_delta_e=1.000000
saturation_delta=0.000052
size_ratio=1.103135
size_delta_vs_round2_bytes=-1176
gate_to_19=WAIT_FOR_HUMAN_REVIEW
```

最值得看的裁切：

```text
100%:
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\green_c_product_kv\material_texture__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\green_c_product_kv\subject_edge__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\green_c_product_kv\text_logo__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\green_c_product_kv\highlight_flat__round2_1.png

200% preview:
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\08_crops_200pct_preview\green_c_product_kv\material_texture__round2_1__200pct_preview.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\08_crops_200pct_preview\green_c_product_kv\subject_edge__round2_1__200pct_preview.png
```

看哪里：瓶身轮廓、透明材质、产品高光、包装文字、Logo、白色平滑面。  
判断什么：产品是否更有质感和边缘稳定；包装字和 Logo 是否没有描边、变形或发灰；白色平滑面是否保持干净。  
通过标准：瓶身透明质感或轮廓层次可见提升，Logo/文字不变形，白面不发脏，高光不发灰。  
失败标准：产品边缘白边、透明材质塑料化、Logo 被锐化描边、白底出现脏雾或低频块。  
结论建议：最有希望成为稳定 `MINOR_POSITIVE` 的产品样本之一。

### 4.3 purple_beauty_product_kv

复核优先级：P1  
当前风险：`risk_status=REVIEW`，`size_benefit_ratio_judgement=ACCEPTABLE`  
关键指标：

```text
edge_delta_proxy=0.079057
texture_delta_proxy=0.126431
p95_delta_e=1.414214
saturation_delta=0.000092
size_ratio=1.101290
size_delta_vs_round2_bytes=-1231
gate_to_19=WAIT_FOR_HUMAN_REVIEW
```

最值得看的裁切：

```text
100%:
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\purple_beauty_product_kv\text_logo__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\purple_beauty_product_kv\subject_edge__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\purple_beauty_product_kv\highlight_flat__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\purple_beauty_product_kv\low_frequency_bg__round2_1.png

200% preview:
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\08_crops_200pct_preview\purple_beauty_product_kv\text_logo__round2_1__200pct_preview.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\08_crops_200pct_preview\purple_beauty_product_kv\highlight_flat__round2_1__200pct_preview.png
```

看哪里：DERMAFIRM 字样、紫色品牌色、银色高光、产品边缘、背景渐变。  
判断什么：质感是否真实提升；品牌紫是否稳定；银色高光是否没有发灰、发脏或过硬。  
通过标准：产品边缘和材质层次轻微改善，品牌色和高光稳定，文字不变形。  
失败标准：品牌色偏移、银色高光发灰、渐变背景出现色带或块状脏污。  
结论建议：可能成为 `MINOR_POSITIVE`，但必须由 Gemini 和人工确认品牌色与高光。

### 4.4 dji_horizontal_infographic

复核优先级：P0  
当前风险：`risk_status=REVIEW`，`size_benefit_ratio_judgement=ACCEPTABLE`  
关键指标：

```text
edge_delta_proxy=0.293530
texture_delta_proxy=0.188768
p95_delta_e=1.732051
saturation_delta=0.000309
size_ratio=1.097542
size_delta_vs_round2_bytes=-7506
gate_to_19=WAIT_FOR_HUMAN_REVIEW
```

最值得看的裁切：

```text
100%:
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\dji_horizontal_infographic\text_logo__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\dji_horizontal_infographic\subject_edge__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\dji_horizontal_infographic\low_frequency_bg__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\dji_horizontal_infographic\highlight_flat__round2_1.png

200% preview:
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\08_crops_200pct_preview\dji_horizontal_infographic\text_logo__round2_1__200pct_preview.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\08_crops_200pct_preview\dji_horizontal_infographic\subject_edge__round2_1__200pct_preview.png
```

看哪里：中文小字、小图标、线条、浅色背景、中间结构和底部信息区。  
判断什么：是否至少有一张文字密集图出现真实文字或边缘收益；是否无断笔、堵塞、双边和灰边。  
通过标准：小字或线条边缘更稳，图标不变形，浅底无脏块，信息区可读性略有提高。  
失败标准：小字堵塞、线条变粗、浅底脏雾、图标边缘出现双边或重影。  
结论建议：最适合证明“文字密集图也能有轻微安全收益”；如果人工不认可，应进入 Round 2.2。

### 4.5 liu_qiangdong_commercial_portrait

复核优先级：P1  
当前风险：`risk_status=REVIEW`，`size_benefit_ratio_judgement=WEAK`  
关键指标：

```text
edge_delta_proxy=0.538488
texture_delta_proxy=0.210600
p95_delta_e=2.236068
saturation_delta=0.000934
size_ratio=1.137202
size_delta_vs_round2_bytes=304
gate_to_19=WAIT_FOR_HUMAN_REVIEW
```

最值得看的裁切：

```text
100%:
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\liu_qiangdong_commercial_portrait\material_texture__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\liu_qiangdong_commercial_portrait\subject_edge__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\liu_qiangdong_commercial_portrait\low_frequency_bg__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\liu_qiangdong_commercial_portrait\text_logo__round2_1.png

200% preview:
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\08_crops_200pct_preview\liu_qiangdong_commercial_portrait\material_texture__round2_1__200pct_preview.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\08_crops_200pct_preview\liu_qiangdong_commercial_portrait\subject_edge__round2_1__200pct_preview.png
```

看哪里：服装纹理、背景城市、中文标题、脸部边缘、肤色。  
判断什么：非脸部材质是否提升；脸部和肤色是否稳定；背景是否更干净而不结块。  
通过标准：衣物或背景层次略有提升，脸部无勾边、无磨皮、无肤色漂移，中文标题不变形。  
失败标准：脸部轮廓变硬、皮肤颗粒化、背景低频结块、体积增长缺少可见收益。  
结论建议：当前更适合放入 Round 2.2 观察池，除非人工明确确认非脸部材质收益。

### 4.6 wei_zhongxian_character_card

复核优先级：P1  
当前风险：`risk_status=REVIEW`，`size_benefit_ratio_judgement=WEAK`  
关键指标：

```text
edge_delta_proxy=0.466152
texture_delta_proxy=0.253883
p95_delta_e=2.236068
saturation_delta=0.001071
size_ratio=1.122815
size_delta_vs_round2_bytes=-1695
gate_to_19=WAIT_FOR_HUMAN_REVIEW
```

最值得看的裁切：

```text
100%:
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\wei_zhongxian_character_card\material_texture__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\wei_zhongxian_character_card\subject_edge__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\wei_zhongxian_character_card\text_logo__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\wei_zhongxian_character_card\shadow_structure__round2_1.png

200% preview:
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\08_crops_200pct_preview\wei_zhongxian_character_card\material_texture__round2_1__200pct_preview.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\08_crops_200pct_preview\wei_zhongxian_character_card\text_logo__round2_1__200pct_preview.png
```

看哪里：毛发、服饰纹理、小字、红色标签、边框线、暗部。  
判断什么：毛发和服饰是否有真实层次；文字标签和边框是否无描边；暗部是否没有结块。  
通过标准：非脸部毛发/服饰有轻微层次，脸和文字稳定，红色标签不溢色，边框线不双边。  
失败标准：脸部或手部被强化、红色标签色漂、小字变粗、暗部结块。  
结论建议：当前更适合放入 Round 2.2 观察池，优先收紧角色卡文字和脸部保护。

### 4.7 andy_lau_commercial_portrait

复核优先级：P1  
当前风险：`risk_status=REVIEW`，`size_benefit_ratio_judgement=WEAK`  
关键指标：

```text
edge_delta_proxy=0.357583
texture_delta_proxy=0.217520
p95_delta_e=2.236068
saturation_delta=0.000621
size_ratio=1.116537
size_delta_vs_round2_bytes=-521
gate_to_19=WAIT_FOR_HUMAN_REVIEW
```

最值得看的裁切：

```text
100%:
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\andy_lau_commercial_portrait\material_texture__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\andy_lau_commercial_portrait\subject_edge__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\andy_lau_commercial_portrait\highlight_flat__round2_1.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\07_crops_100pct\andy_lau_commercial_portrait\text_logo__round2_1.png

200% preview:
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\08_crops_200pct_preview\andy_lau_commercial_portrait\material_texture__round2_1__200pct_preview.png
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\08_crops_200pct_preview\andy_lau_commercial_portrait\highlight_flat__round2_1__200pct_preview.png
```

看哪里：非脸部材质、金色高光、碎片边缘、背景低频、手部、中文小字。  
判断什么：是否有至少一张人物/角色图出现非脸部材质收益；脸、手、肤色和中文小字是否稳定。  
通过标准：服饰/碎片/金属或背景结构有轻微层次，人脸和手不变形，高光不发灰。  
失败标准：脸或手出现锐化边、肤色变化、金色高光脏化、小字变粗或断笔。  
结论建议：可能成为人物类 `MINOR_POSITIVE` 代表，但必须人工确认脸和手无异常。

## 5. 可能成为 MINOR_POSITIVE 的样本

优先候选：

```text
green_c_product_kv
dji_horizontal_infographic
andy_lau_commercial_portrait
purple_beauty_product_kv
```

条件：

1. `green_c_product_kv` 必须确认产品轮廓、透明材质或瓶身质感有真实收益，且 Logo/包装文字稳定。
2. `dji_horizontal_infographic` 必须确认小字、图标或线条至少有轻微收益，浅底无脏块。
3. `andy_lau_commercial_portrait` 必须确认收益集中在非脸部材质区域，脸、手、肤色稳定。
4. `purple_beauty_product_kv` 必须确认品牌紫、高光和渐变稳定，产品边缘或材质有轻微收益。

## 6. 必须进入或倾向进入 Round 2.2 的样本

必须进入 Round 2.2：

```text
wechat_longscreenshot_2026-06-12_111900_080
```

原因：

```text
risk_status=REJECT
size_benefit_ratio_judgement=NOT_ACCEPTABLE
size_ratio=1.154430
Round 2.1 相比 Round 2 的体积增加 48708 bytes
文字密集图收益不足以支撑体积增长，需要降低强度并收紧文字/低频保护。
```

倾向进入 Round 2.2 观察池：

```text
liu_qiangdong_commercial_portrait
wei_zhongxian_character_card
```

原因：

```text
二者均为人物/角色类，size_benefit_ratio_judgement=WEAK。
如果人工无法明确看到非脸部材质收益，就不应进入 19 张黄金集。
下一轮应继续强化脸部、肤色、小字和暗部保护，同时只允许非脸部材质区域低强度处理。
```

## 7. Gemini 复核建议

```text
是否建议 Gemini 进入下一步复核：YES
```

Gemini 应重点判断：

1. `wechat_longscreenshot_2026-06-12_111900_080`：文字边缘是否真实改善；白底/浅灰底是否变脏；体积增长是否完全不值。
2. `green_c_product_kv`：瓶身透明材质和产品轮廓是否有真实质感收益；Logo、包装文字、白面是否稳定。
3. `purple_beauty_product_kv`：紫色品牌色、银色高光、背景渐变是否保持；是否有产品材质收益。
4. `dji_horizontal_infographic`：中文小字、图标、细线是否有轻微收益；是否出现字腔堵塞、断笔或线条变粗。
5. `andy_lau_commercial_portrait`：非脸部材质收益是否成立；脸、手、肤色、金色高光是否安全。
6. `liu_qiangdong_commercial_portrait`：服装/背景收益是否足以支撑体积增长；脸部是否无勾边。
7. `wei_zhongxian_character_card`：毛发/服饰收益是否真实；红色标签、小字、边框和暗部是否稳定。

## 8. 复核后决策门

只有满足以下条件，才允许讨论进入 19 张黄金集：

```text
至少 4 张样本被人工确认 POSITIVE 或 MINOR_POSITIVE
至少 1 张文字密集图有真实文字或边缘收益
2 张产品 KV 至少 1 张有明确质感收益
至少 1 张人物/角色图有非脸部材质收益
wechat_longscreenshot 不再作为阻断项，或明确进入 Round 2.2 修正后再判断
没有文字损伤、Logo损伤、人脸异常、品牌色漂移、低频脏块
文件体积增长有可见收益支撑
```

当前建议：

```text
NOT_READY_FOR_19
WAIT_FOR_HUMAN_VISUAL_REVIEW
Gemini复核建议：YES
```

## 9. 相关入口

人工复核 HTML：

```text
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_1_targeted\review_index_chatgpt.html
```

Round 2.1 调参报告：

```text
D:\Codex\04_Visual-Master-Pro\docs\reports\2026-06-19_V046_ROUND2_1_TUNING_REPORT.md
```

ChatGPT 交接报告：

```text
D:\Codex\04_Visual-Master-Pro\docs\reports\2026-06-19_V046_ROUND2_1_CHATGPT_HANDOFF.md
```

样本表：

```text
D:\Codex\04_Visual-Master-Pro\docs\reports\2026-06-19_V046_ROUND2_1_SAMPLE_TABLE.csv
```

本指南：

```text
D:\Codex\04_Visual-Master-Pro\docs\reports\2026-06-19_V046_ROUND2_1_HUMAN_REVIEW_GUIDE.md
```

