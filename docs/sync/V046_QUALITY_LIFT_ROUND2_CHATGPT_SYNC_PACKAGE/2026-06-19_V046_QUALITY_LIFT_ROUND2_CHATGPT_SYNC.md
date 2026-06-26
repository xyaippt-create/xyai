# 影界 VisualMasterPro V0.4.6 RC1前真实画质收益 Round 2 同步报告

生成日期：2026-06-19

## 1. 本轮结论

结论：`PASS_CANDIDATE_READY_FOR_19`

本轮完成了「V0.4.6 RC1前｜真实画质收益 Round 2：产品、文字、边缘、质感专项」的 7 张指定商业样本离线候选验证。

当前结论不是冻结，也不是正式算法提交，而是：

```text
Round 2 候选在 7 张指定样本上达到进入人工视觉复核与后续 19 张黄金集验证的最低门槛。
```

本轮未修改：

```text
API 字段名
XHR 上传
EventSource SSE
final_output_url / preview_output_url
前台核心交付状态映射
诊断 ZIP 接口合同
正式生产算法链路
```

本轮新增：

```text
tests/tools/v046_round2_targeted_candidate.py
tests/tools/v046_round2_targeted_candidate.ps1
tests/results/v046_quality_lift_round2_targeted/
docs/sync/2026-06-19_V046_QUALITY_LIFT_ROUND2_CHATGPT_SYNC.md
```

其中 `.py` 脚本为本轮有效离线验证工具；`.ps1` 为早期尝试版本，因逐像素方式过慢，仅保留为本地过程痕迹，不建议作为正式验证入口。

## 2. 基线与前提

当前后台事实：

```text
Phase 1-6 已冻结
Phase 6 结论：PASS_WITH_KNOWN_ISSUES
Round 1 通透度全局候选：FAIL
Round 1 结论：不得继续做全局通透度增强
```

Round 1 已证明：

```text
统一轻量全局透明度 / 低频洁净候选没有稳定收益；
真实产品和建筑样本容易触发低频污染、Delta E 或饱和度风险；
中文小字、合成渐变和品牌色样本应继续走保护或跳过路径。
```

因此 Round 2 策略调整为：

```text
先判断安全区域，再只处理安全区域；
不做全图增强；
不做全局亮度、对比度、饱和度或锐化；
不接入正式链路前先离线验证。
```

## 3. Round 2 候选策略

候选处理目标：

```text
产品材质非文字 / 非 Logo 区域
建筑与角色图中的中频结构
文字密集图中的边缘代理改善
人物海报中的衣物、发丝、暗部结构与复杂背景细节
```

保护策略：

```text
文字、Logo、强品牌色
大面积高光和平滑背景
皮肤与人脸五官
纯黑深阴影
低频平坦区域
合成渐变风险区域
```

当前实现方式：

```text
对 frozen V0.4.6 输出做离线候选试算；
在亮度域内做极低强度局部中频增强；
用区域门控抑制平坦区、高光、强色彩、肤色和深阴影；
生成候选、对比图、100% 裁切、200% 预览裁切和指标数据；
不接入 backend/v036_output_core.py；
不修改 engine/algorithms 正式模块；
不改变 API 或前台主流程。
```

## 4. 7 张决策样本

| sample_id | 对应素材 | 类型 |
| --- | --- | --- |
| `wechat_longscreenshot_2026-06-12_111900_080` | 微信长截图文字密集图 | text_dense_long_screenshot |
| `green_c_product_kv` | 维 C 焕亮精华产品 KV | product_kv |
| `purple_beauty_product_kv` | DERMAFIRM 紫色美妆产品 KV | product_kv |
| `dji_horizontal_infographic` | DJI 大疆创新横版信息图 | text_dense_infographic |
| `liu_qiangdong_commercial_portrait` | 刘强东商业人物海报 | portrait_poster |
| `wei_zhongxian_character_card` | 魏忠贤角色视觉档案 | character_info_card |
| `andy_lau_commercial_portrait` | 刘德华商业人物海报 | portrait_poster |

样本来源：

```text
D:\影界文件\输入图片
D:\影界文件\输出成品
```

## 5. 指标结果

| sample_id | 判断 | edge_delta_proxy | texture_delta_proxy | p95_delta_e | saturation_delta | size_ratio |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `wechat_longscreenshot_2026-06-12_111900_080` | minor_positive | 0.08083 | 0.135424 | 1.414214 | -0.000058 | 1.091413 |
| `green_c_product_kv` | minor_positive | 0.068722 | 0.102385 | 1.0 | 0.000054 | 1.103935 |
| `purple_beauty_product_kv` | minor_positive | 0.08068 | 0.113404 | 1.414214 | 0.000047 | 1.102005 |
| `dji_horizontal_infographic` | minor_positive | 0.406641 | 0.282267 | 1.732051 | 0.000304 | 1.100956 |
| `liu_qiangdong_commercial_portrait` | minor_positive | 0.55257 | 0.217462 | 2.236068 | 0.000986 | 1.13712 |
| `wei_zhongxian_character_card` | minor_positive | 0.55266 | 0.324381 | 2.236068 | 0.001231 | 1.123306 |
| `andy_lau_commercial_portrait` | minor_positive | 0.327169 | 0.188796 | 2.0 | 0.000623 | 1.116747 |

统计：

```text
样本总数：7
轻微正收益：7
中性或收益不足：0
风险样本：0
是否建议进入 19 张黄金集：是，但必须先做人工 100% 裁切复核
```

## 6. 关键判断

本轮候选通过的是“离线指标准入”，不是最终冻结：

```text
可以进入人工视觉复核
人工复核通过后建议进入 19 张黄金集
暂不冻结
暂不提交正式算法改动
暂不接入正式生产链
```

必须人工重点查看：

```text
微信长截图：小字是否更清楚，是否有灰边、黑边、重影或字腔堵塞
绿 C 产品 KV：包装文字、Logo、透明瓶体、高光、白底是否稳定
紫色美妆 KV：DERMAFIRM 字样、紫色品牌色、银色高光、产品边缘是否稳定
DJI 信息图：小图标、小字、浅色背景是否不脏
刘强东海报：脸部、发丝、服装、背景城市和中文标题是否自然
魏忠贤角色卡：毛发、服饰纹理、小字、红色标签、边框线是否稳定
刘德华海报：人脸、手部、金色高光、中文小字、碎片边缘是否无伪影
```

## 7. 文件体积判断

候选文件体积增长范围：

```text
约 1.091x - 1.137x
```

当前体积增长不属于严重膨胀，但仍需要人工确认肉眼收益是否足以支撑体积增长。

若人工观察认为只是“更硬”或“更锐”，但没有真实文字、材质、边缘和层次收益，则不能进入 19 张黄金集。

## 8. 当前产物

验证包目录：

```text
tests/results/v046_quality_lift_round2_targeted/
```

关键文件：

```text
tests/results/v046_quality_lift_round2_targeted/report.md
tests/results/v046_quality_lift_round2_targeted/manifest.json
tests/results/v046_quality_lift_round2_targeted/review_index.html
tests/results/v046_quality_lift_round2_targeted/08_metrics/*.json
```

视觉材料：

```text
01_original/
02_frozen/
03_candidate/
04_full_compare/
05_same_scale_compare/
06_crops_100pct/
07_crops_200pct_preview/
```

## 9. 对 ChatGPT 的建议判断

建议 ChatGPT 按以下口径继续拆解下一步：

```text
1. 先进行用户 100% 裁切人工视觉复核；
2. 若 7 张样本中至少 4 张确认有真实可见收益，且没有文字、Logo、人脸、品牌色、低频平滑区域退化，则允许进入 19 张黄金集；
3. 19 张黄金集通过后，再考虑将候选策略最小化接入 engine/algorithms 独立模块；
4. 接入时不得修改 API 字段名、XHR、SSE、final_output_url、preview_output_url；
5. 不得把当前离线候选直接视为生产算法冻结。
```

建议下一条任务：

```text
V0.4.6 RC1前｜真实画质收益 Round 2 人工视觉复核与 19 张黄金集准入判断
```

## 10. 当前 Git 状态说明

当前工作区存在大量历史脏文件，本轮未尝试清理，也未创建 Commit。

本轮新增/修改与 Round 2 相关的文件主要为：

```text
tests/tools/v046_round2_targeted_candidate.py
tests/tools/v046_round2_targeted_candidate.ps1
tests/results/v046_quality_lift_round2_targeted/
docs/sync/2026-06-19_V046_QUALITY_LIFT_ROUND2_CHATGPT_SYNC.md
```

注意：

```text
tests/results/ 不建议提交 Git；
用户原图和输出图不应提交 Git；
正式算法尚未提交；
正式生产链尚未变更。
```
