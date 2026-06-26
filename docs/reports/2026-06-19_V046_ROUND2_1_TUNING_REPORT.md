# V0.4.6 Round 2.1 安全局部收益微调报告

生成日期：2026-06-20

## 1. 本轮结论

结论：`WAIT_FOR_HUMAN_VISUAL_REVIEW`

是否建议进入 19 张黄金集：`等待人工视觉确认后再决定是否进入 19 张黄金集`

本轮完成了 7 张决策样本的 Round 2.1 离线微调。证据包完整，指标方向 7/7 为正，但仍不能替代人工肉眼视觉判断，因此不直接进入 19 张黄金集。

## 2. 本轮改了什么

- 新增测试侧跨平台路径解析预留：`tests/tools/v046_path_resolver.py`；
- 新增 Round 2.1 离线候选脚本：`tests/tools/v046_round2_1_targeted_candidate.py`；
- 微调局部中频增强 mask：更强调安全边缘与材质结构，继续抑制平坦区、高光、强品牌色、肤色、深阴影和强边缘；
- 生成完整证据包：original / frozen / Round2 / Round2.1 / 全图对比 / 同尺度对比 / 100% 裁切 / 200% 裁切 / metrics / path_index。

## 3. 本轮没改什么

- 未修改正式生产代码；
- 未接入正式生产链；
- 未进入 19 张黄金集；
- 未冻结；
- 未修改 API 字段名；
- 未修改 XHR 上传；
- 未修改 EventSource SSE；
- 未修改 final_output_url / preview_output_url；
- 未扩展前台 UI；
- 未做第四模式或输出格式选择。

## 4. 7 张样本结果

| sample_id | 类型 | 指标 | 肉眼预判 | 风险 | 体积收益比 | 19张准入 |
| --- | --- | --- | --- | --- | --- | --- |
| `wechat_longscreenshot_2026-06-12_111900_080` | 文字/信息图 | PASS | NEEDS_HUMAN_REVIEW | REJECT | NOT_ACCEPTABLE | NO |
| `green_c_product_kv` | 产品/商业KV | PASS | MINOR_POSITIVE | REVIEW | ACCEPTABLE | WAIT_FOR_HUMAN_REVIEW |
| `purple_beauty_product_kv` | 产品/商业KV | PASS | MINOR_POSITIVE | REVIEW | ACCEPTABLE | WAIT_FOR_HUMAN_REVIEW |
| `dji_horizontal_infographic` | 文字/信息图 | PASS | MINOR_POSITIVE | REVIEW | ACCEPTABLE | WAIT_FOR_HUMAN_REVIEW |
| `liu_qiangdong_commercial_portrait` | 人物/角色海报 | PASS | MINOR_POSITIVE | REVIEW | WEAK | WAIT_FOR_HUMAN_REVIEW |
| `wei_zhongxian_character_card` | 人物/角色海报 | PASS | MINOR_POSITIVE | REVIEW | WEAK | WAIT_FOR_HUMAN_REVIEW |
| `andy_lau_commercial_portrait` | 人物/角色海报 | PASS | MINOR_POSITIVE | REVIEW | WEAK | WAIT_FOR_HUMAN_REVIEW |

## 5. 与 Round 2 的收益对比

| sample_id | Round2 edge | Round2.1 edge | Round2 texture | Round2.1 texture | p95_delta_e | saturation_delta | size_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `wechat_longscreenshot_2026-06-12_111900_080` | 0.08083 | 0.053305 | 0.135424 | 0.079538 | 1.0 | 4.4e-05 | 1.15443 |
| `green_c_product_kv` | 0.068722 | 0.07301 | 0.102385 | 0.110356 | 1.0 | 5.2e-05 | 1.103135 |
| `purple_beauty_product_kv` | 0.08068 | 0.079057 | 0.113404 | 0.126431 | 1.414214 | 9.2e-05 | 1.10129 |
| `dji_horizontal_infographic` | 0.406641 | 0.29353 | 0.282267 | 0.188768 | 1.732051 | 0.000309 | 1.097542 |
| `liu_qiangdong_commercial_portrait` | 0.55257 | 0.538488 | 0.217462 | 0.2106 | 2.236068 | 0.000934 | 1.137202 |
| `wei_zhongxian_character_card` | 0.55266 | 0.466152 | 0.324381 | 0.253883 | 2.236068 | 0.001071 | 1.122815 |
| `andy_lau_commercial_portrait` | 0.327169 | 0.357583 | 0.188796 | 0.21752 | 2.236068 | 0.000621 | 1.116537 |

## 6. 风险变化

- 文字与信息图：指标增强更明显，但必须人工确认没有黑边、灰边、断笔、字腔堵塞和白底变脏。
- 产品 KV：产品边缘与材质代理指标为正，但必须人工确认包装文字、Logo、透明材质、高光和品牌色稳定。
- 人物/角色海报：非脸部材质与边缘代理指标为正，但必须人工确认人脸、肤色、手部、发丝没有假锐化、塑料感或磨皮感。
- 体积收益比：Round 2.1 size_ratio 范围为 1.097542 - 1.15443，仍需人工确认收益是否支撑体积增长。

## 7. 逐样本摘要

### wechat_longscreenshot_2026-06-12_111900_080

- 类型：文字/信息图
- 重点风险点：小字、灰字/黑字边缘、字腔、白底和浅灰背景
- Round 2 → Round 2.1 指标变化：edge 0.08083 → 0.053305（Δ -0.027525），texture 0.135424 → 0.079538（Δ -0.055886），size_ratio 1.091413 → 1.15443（Δ 0.063017）。
- 色彩与风险：p95_delta_e=1.0，saturation_delta=4.4e-05，risk_status=REJECT。
- 证据：original / frozen / Round2 / Round2.1 独立文件均已生成；100% 裁切 18 个，200% 预览裁切 18 个。
- 当前判断：NEEDS_HUMAN_REVIEW；仍需人工查看 100% 裁切确认真实可见收益。

### green_c_product_kv

- 类型：产品/商业KV
- 重点风险点：包装文字、Logo、透明瓶体、高光、白底、产品轮廓
- Round 2 → Round 2.1 指标变化：edge 0.068722 → 0.07301（Δ 0.004288），texture 0.102385 → 0.110356（Δ 0.007971），size_ratio 1.103935 → 1.103135（Δ -0.000800）。
- 色彩与风险：p95_delta_e=1.0，saturation_delta=5.2e-05，risk_status=REVIEW。
- 证据：original / frozen / Round2 / Round2.1 独立文件均已生成；100% 裁切 18 个，200% 预览裁切 18 个。
- 当前判断：MINOR_POSITIVE；仍需人工查看 100% 裁切确认真实可见收益。

### purple_beauty_product_kv

- 类型：产品/商业KV
- 重点风险点：DERMAFIRM 字样、紫色品牌色、银色高光、产品边缘、背景渐变
- Round 2 → Round 2.1 指标变化：edge 0.08068 → 0.079057（Δ -0.001623），texture 0.113404 → 0.126431（Δ 0.013027），size_ratio 1.102005 → 1.10129（Δ -0.000715）。
- 色彩与风险：p95_delta_e=1.414214，saturation_delta=9.2e-05，risk_status=REVIEW。
- 证据：original / frozen / Round2 / Round2.1 独立文件均已生成；100% 裁切 18 个，200% 预览裁切 18 个。
- 当前判断：MINOR_POSITIVE；仍需人工查看 100% 裁切确认真实可见收益。

### dji_horizontal_infographic

- 类型：文字/信息图
- 重点风险点：中文小字、小图标、线条、浅色背景、中间结构和底部信息区
- Round 2 → Round 2.1 指标变化：edge 0.406641 → 0.29353（Δ -0.113111），texture 0.282267 → 0.188768（Δ -0.093499），size_ratio 1.100956 → 1.097542（Δ -0.003414）。
- 色彩与风险：p95_delta_e=1.732051，saturation_delta=0.000309，risk_status=REVIEW。
- 证据：original / frozen / Round2 / Round2.1 独立文件均已生成；100% 裁切 18 个，200% 预览裁切 18 个。
- 当前判断：MINOR_POSITIVE；仍需人工查看 100% 裁切确认真实可见收益。

### liu_qiangdong_commercial_portrait

- 类型：人物/角色海报
- 重点风险点：人脸、肤色、发丝、服装纹理、背景城市、中文标题
- Round 2 → Round 2.1 指标变化：edge 0.55257 → 0.538488（Δ -0.014082），texture 0.217462 → 0.2106（Δ -0.006862），size_ratio 1.13712 → 1.137202（Δ 0.000082）。
- 色彩与风险：p95_delta_e=2.236068，saturation_delta=0.000934，risk_status=REVIEW。
- 证据：original / frozen / Round2 / Round2.1 独立文件均已生成；100% 裁切 18 个，200% 预览裁切 18 个。
- 当前判断：MINOR_POSITIVE；仍需人工查看 100% 裁切确认真实可见收益。

### wei_zhongxian_character_card

- 类型：人物/角色海报
- 重点风险点：毛发、服饰纹理、小字、红色标签、边框线、暗部
- Round 2 → Round 2.1 指标变化：edge 0.55266 → 0.466152（Δ -0.086508），texture 0.324381 → 0.253883（Δ -0.070498），size_ratio 1.123306 → 1.122815（Δ -0.000491）。
- 色彩与风险：p95_delta_e=2.236068，saturation_delta=0.001071，risk_status=REVIEW。
- 证据：original / frozen / Round2 / Round2.1 独立文件均已生成；100% 裁切 18 个，200% 预览裁切 18 个。
- 当前判断：MINOR_POSITIVE；仍需人工查看 100% 裁切确认真实可见收益。

### andy_lau_commercial_portrait

- 类型：人物/角色海报
- 重点风险点：人脸、手部、金色高光、中文小字、碎片边缘、背景低频
- Round 2 → Round 2.1 指标变化：edge 0.327169 → 0.357583（Δ 0.030414），texture 0.188796 → 0.21752（Δ 0.028724），size_ratio 1.116747 → 1.116537（Δ -0.000210）。
- 色彩与风险：p95_delta_e=2.236068，saturation_delta=0.000621，risk_status=REVIEW。
- 证据：original / frozen / Round2 / Round2.1 独立文件均已生成；100% 裁切 18 个，200% 预览裁切 18 个。
- 当前判断：MINOR_POSITIVE；仍需人工查看 100% 裁切确认真实可见收益。


## 8. 是否建议继续人工视觉复核

建议继续人工视觉复核。当前证据完整、指标方向为正，但商业质量准入必须看 100% 裁切。

## 9. 是否建议进入 19 张黄金集

当前不直接建议进入。建议在人工确认至少 4 张样本有真实可见收益，且无文字、Logo、人脸、品牌色、低频平滑区损伤后，再进入 19 张黄金集离线验证。

## 10. 如果仍不建议进入，下一轮怎么修

只允许 Round 2.2 小修：

1. 缩小增强区域 mask；
2. 降低中频增强强度；
3. 加强文字、Logo、人脸、肤色、品牌色、高光和平滑背景保护；
4. 降低体积增长；
5. 优化低频平滑区保护；
6. 不回到全图锐化、全图对比、全图饱和或全图通透路线。

## 11. Gemini 判断门

是否建议 Gemini 进入下一步复核：YES

原因：当前证据完整、指标方向为正，但是否进入 19 张黄金集仍依赖人工视觉判断；100% / 200% 裁切中的文字、Logo、人脸、品牌色、低频平滑区和体积收益比仍需视觉复核。
