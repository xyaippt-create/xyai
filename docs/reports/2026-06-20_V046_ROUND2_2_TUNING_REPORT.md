# V0.4.6 Round 2.2 小幅修正 / 收缩型安全微调报告

生成日期：2026-06-20

## 1. 本轮结论

```text
WAIT_FOR_GEMINI_REVIEW / NOT_RUN_19 / NOT_FROZEN / EVIDENCE_COMPLETE
```

本轮完成 7 张目标样本的 Round 2.2 离线收缩型候选。证据完整性：`PASS`。

当前不进入 19 张黄金集，不冻结，不接正式生产链。原因是 Round 2.2 虽然修复了体积收益比，并把 6 张样本推回 `MINOR_POSITIVE` 指标区间，但仍需要 Gemini 或人工复核 100% 裁切确认真实可见收益。

## 2. 边界确认

```text
是否修改正式生产代码：否
是否接入正式生产链：否
是否运行19张黄金集：否
是否冻结：否
是否扩展前台UI：否
是否新增模式：否
是否做2K/4K：否
```

本轮只新增测试侧离线候选脚本、报告脚本和证据包。

## 3. Round 2.2 修正策略

- 文字密集图：显著降低增强强度，缩小文字边缘 mask，保护白底、浅灰底、小字、灰字和低频区域。
- 产品 KV：保留产品轮廓、透明材质、瓶身和中频质感的轻微收益，继续锁定 Logo、包装文字、品牌色、白色平滑面、高光和渐变。
- 人物图：扩大脸、五官、肤色、手部保护，只允许衣物、发丝、背景结构、碎片、金属等非脸部材质低强度增强。
- 角色卡：加强红色标签、小字、边框、暗部保护，不把版式边框、小字和标签当作材质收益区域。
- 体积控制：所有样本 `size_ratio <= 1.11`，本轮范围 `1.037101` - `1.107944`。

## 4. 样本总表

| sample_id | 类型 | 策略 | 强度 | 预判 | 风险 | 体积收益 | size_ratio | 19张准入 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `wechat_longscreenshot_2026-06-12_111900_080` | 文字密集长截图 | text_dense_shrink | 0.022 | NEEDS_HUMAN_REVIEW | REVIEW | ACCEPTABLE | 1.089038 | WAIT_FOR_HUMAN_REVIEW |
| `green_c_product_kv` | 产品KV | product_kv_safe | 0.066 | MINOR_POSITIVE | REVIEW | ACCEPTABLE | 1.037101 | WAIT_FOR_HUMAN_REVIEW |
| `purple_beauty_product_kv` | 产品KV | product_kv_safe | 0.063 | MINOR_POSITIVE | REVIEW | ACCEPTABLE | 1.045954 | WAIT_FOR_HUMAN_REVIEW |
| `dji_horizontal_infographic` | 文字信息图 | infographic_safe | 0.071 | MINOR_POSITIVE | REVIEW | ACCEPTABLE | 1.091383 | WAIT_FOR_HUMAN_REVIEW |
| `liu_qiangdong_commercial_portrait` | 商业人物海报 | portrait_nonface | 0.066 | MINOR_POSITIVE | REVIEW | ACCEPTABLE | 1.107944 | WAIT_FOR_HUMAN_REVIEW |
| `wei_zhongxian_character_card` | 角色信息卡 | character_card_nontext | 0.06 | MINOR_POSITIVE | REVIEW | ACCEPTABLE | 1.097847 | WAIT_FOR_HUMAN_REVIEW |
| `andy_lau_commercial_portrait` | 商业人物海报 | portrait_nonface | 0.062 | MINOR_POSITIVE | REVIEW | ACCEPTABLE | 1.091374 | WAIT_FOR_HUMAN_REVIEW |

## 5. 指标变化

| sample_id | R2.1 edge | R2.2 edge | R2.1 texture | R2.2 texture | p95_delta_e | sat_delta | R2.1 size | R2.2 size |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `wechat_longscreenshot_2026-06-12_111900_080` | 0.053305 | 0.039335 | 0.079538 | 0.064037 | 0.0 | 5.5e-05 | 1.15443 | 1.089038 |
| `green_c_product_kv` | 0.07301 | 0.062626 | 0.110356 | 0.082911 | 1.0 | 8.5e-05 | 1.103135 | 1.037101 |
| `purple_beauty_product_kv` | 0.079057 | 0.057692 | 0.126431 | 0.079286 | 1.0 | 0.000117 | 1.10129 | 1.045954 |
| `dji_horizontal_infographic` | 0.29353 | 0.16613 | 0.188768 | 0.112358 | 1.732051 | 0.000263 | 1.097542 | 1.091383 |
| `liu_qiangdong_commercial_portrait` | 0.538488 | 0.486637 | 0.2106 | 0.178828 | 1.732051 | 0.000964 | 1.137202 | 1.107944 |
| `wei_zhongxian_character_card` | 0.466152 | 0.275938 | 0.253883 | 0.140537 | 1.732051 | 0.001065 | 1.122815 | 1.097847 |
| `andy_lau_commercial_portrait` | 0.357583 | 0.276724 | 0.21752 | 0.149418 | 1.732051 | 0.000595 | 1.116537 | 1.091374 |

## 6. 关键修复点

- `wechat_longscreenshot_2026-06-12_111900_080`：size_ratio 从 Round 2.1 的 `1.15443` 降至 `1.089038`，达到 `<= 1.11` 目标；但文字收益仍弱，只能标记为 `NEEDS_HUMAN_REVIEW`。
- `liu_qiangdong_commercial_portrait`：size_ratio 降至 `1.107944`，脸部保护扩大，非脸部区域仍需人工确认收益。
- `wei_zhongxian_character_card`：size_ratio 降至 `1.097847`，红标、小字、边框保护加强，毛发/服饰收益仍需人工确认。
- `green_c_product_kv`、`purple_beauty_product_kv`、`dji_horizontal_infographic`、`andy_lau_commercial_portrait`：保留 `MINOR_POSITIVE` 方向，同时明显降低体积压力。

## 7. 逐样本说明

### wechat_longscreenshot_2026-06-12_111900_080

- 类型：文字密集长截图
- Round 2.2 策略：text_dense_shrink，强度 `0.022`
- 修正目标：压低体积增长，保留极轻微文字边缘稳定，保护白底和浅灰底
- Round 2.1 -> Round 2.2：edge `0.053305` -> `0.039335`，texture `0.079538` -> `0.064037`，size_ratio `1.15443` -> `1.089038`
- 色彩风险：p95_delta_e=`0.0`，saturation_delta=`5.5e-05`
- 证据完整：`PASS`，100%裁切 `18`，200%预览裁切 `18`
- 当前预判：`NEEDS_HUMAN_REVIEW`，风险：`REVIEW`，体积收益：`ACCEPTABLE`
- 复核建议：体积目标已修复，但文字收益仍弱；必须由人工确认是否只算保护通过。

### green_c_product_kv

- 类型：产品KV
- Round 2.2 策略：product_kv_safe，强度 `0.066`
- 修正目标：保留瓶身透明材质和产品轮廓轻微收益，锁定Logo、包装文字、白面和高光
- Round 2.1 -> Round 2.2：edge `0.07301` -> `0.062626`，texture `0.110356` -> `0.082911`，size_ratio `1.103135` -> `1.037101`
- 色彩风险：p95_delta_e=`1.0`，saturation_delta=`8.5e-05`
- 证据完整：`PASS`，100%裁切 `18`，200%预览裁切 `18`
- 当前预判：`MINOR_POSITIVE`，风险：`REVIEW`，体积收益：`ACCEPTABLE`
- 复核建议：延续 MINOR_POSITIVE 方向；重点确认 Logo、文字、品牌色、高光和低频平滑区安全。

### purple_beauty_product_kv

- 类型：产品KV
- Round 2.2 策略：product_kv_safe，强度 `0.063`
- 修正目标：保留产品边缘和银色材质轻微收益，锁定品牌紫、银色高光和背景渐变
- Round 2.1 -> Round 2.2：edge `0.079057` -> `0.057692`，texture `0.126431` -> `0.079286`，size_ratio `1.10129` -> `1.045954`
- 色彩风险：p95_delta_e=`1.0`，saturation_delta=`0.000117`
- 证据完整：`PASS`，100%裁切 `18`，200%预览裁切 `18`
- 当前预判：`MINOR_POSITIVE`，风险：`REVIEW`，体积收益：`ACCEPTABLE`
- 复核建议：延续 MINOR_POSITIVE 方向；重点确认 Logo、文字、品牌色、高光和低频平滑区安全。

### dji_horizontal_infographic

- 类型：文字信息图
- Round 2.2 策略：infographic_safe，强度 `0.071`
- 修正目标：保留大结构、图标和线条轻微收益，保护小字、浅底和细线
- Round 2.1 -> Round 2.2：edge `0.29353` -> `0.16613`，texture `0.188768` -> `0.112358`，size_ratio `1.097542` -> `1.091383`
- 色彩风险：p95_delta_e=`1.732051`，saturation_delta=`0.000263`
- 证据完整：`PASS`，100%裁切 `18`，200%预览裁切 `18`
- 当前预判：`MINOR_POSITIVE`，风险：`REVIEW`，体积收益：`ACCEPTABLE`
- 复核建议：延续 MINOR_POSITIVE 方向；重点确认 Logo、文字、品牌色、高光和低频平滑区安全。

### liu_qiangdong_commercial_portrait

- 类型：商业人物海报
- Round 2.2 策略：portrait_nonface，强度 `0.066`
- 修正目标：扩大脸部和肤色保护，只允许服装、背景城市和非脸部结构轻微处理
- Round 2.1 -> Round 2.2：edge `0.538488` -> `0.486637`，texture `0.2106` -> `0.178828`，size_ratio `1.137202` -> `1.107944`
- 色彩风险：p95_delta_e=`1.732051`，saturation_delta=`0.000964`
- 证据完整：`PASS`，100%裁切 `18`，200%预览裁切 `18`
- 当前预判：`MINOR_POSITIVE`，风险：`REVIEW`，体积收益：`ACCEPTABLE`
- 复核建议：人物/角色弱收益已收缩体积并加强保护；仍需看脸部、文字、红标和非脸部材质。

### wei_zhongxian_character_card

- 类型：角色信息卡
- Round 2.2 策略：character_card_nontext，强度 `0.06`
- 修正目标：加强红色标签、小字、边框和暗部保护，只保留毛发服饰低强度收益
- Round 2.1 -> Round 2.2：edge `0.466152` -> `0.275938`，texture `0.253883` -> `0.140537`，size_ratio `1.122815` -> `1.097847`
- 色彩风险：p95_delta_e=`1.732051`，saturation_delta=`0.001065`
- 证据完整：`PASS`，100%裁切 `18`，200%预览裁切 `18`
- 当前预判：`MINOR_POSITIVE`，风险：`REVIEW`，体积收益：`ACCEPTABLE`
- 复核建议：人物/角色弱收益已收缩体积并加强保护；仍需看脸部、文字、红标和非脸部材质。

### andy_lau_commercial_portrait

- 类型：商业人物海报
- Round 2.2 策略：portrait_nonface，强度 `0.062`
- 修正目标：保留碎片、服装和金属/背景结构轻微收益，保护脸、手、肤色和高光
- Round 2.1 -> Round 2.2：edge `0.357583` -> `0.276724`，texture `0.21752` -> `0.149418`，size_ratio `1.116537` -> `1.091374`
- 色彩风险：p95_delta_e=`1.732051`，saturation_delta=`0.000595`
- 证据完整：`PASS`，100%裁切 `18`，200%预览裁切 `18`
- 当前预判：`MINOR_POSITIVE`，风险：`REVIEW`，体积收益：`ACCEPTABLE`
- 复核建议：延续 MINOR_POSITIVE 方向；重点确认 Logo、文字、品牌色、高光和低频平滑区安全。


## 8. 是否建议进入 19 张黄金集

当前结论：

```text
不建议直接进入19张黄金集
建议先交给 Gemini / 人工做一轮 Round 2.2 视觉复核
```

如果复核确认：

```text
至少4张为 MINOR_POSITIVE 或更高
wechat_longscreenshot 不再因为体积收益比阻断
2张产品KV至少1张有明确轻微材质收益
至少1张人物/角色图有非脸部材质收益
无文字损伤、Logo损伤、人脸异常、品牌色漂移、低频脏块、高光发灰、白底发脏
```

则可以进入 19 张黄金集离线回归。否则继续 Round 2.3 或回退该方向。

## 9. Gemini 判断门

```text
是否建议 Gemini 进入下一步复核：YES
```

重点看：

1. 长截图体积修复后，文字边缘是否仍有足够收益；
2. 两张产品 KV 是否保住 Logo、文字、品牌色、白面、高光，同时有轻微材质提升；
3. DJI 信息图小字、图标、细线是否没有断笔、堵塞、变粗；
4. 三张人物/角色图是否只提升非脸部材质，脸、手、肤色是否稳定；
5. 所有样本是否存在低频脏块、高光发灰或白底发脏。

## 10. 输出文件

```text
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_2_targeted
D:\Codex\04_Visual-Master-Pro\docs\reports\2026-06-20_V046_ROUND2_2_SAMPLE_TABLE.csv
D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_2_targeted\review_index_chatgpt.html
```
