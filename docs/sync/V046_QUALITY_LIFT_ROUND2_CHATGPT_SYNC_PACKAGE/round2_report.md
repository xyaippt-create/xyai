# V0.4.6 RC1前真实画质收益 Round 2 定向验证报告

结论：`PASS_CANDIDATE_READY_FOR_19`

本轮只做 7 张指定商业样本的离线候选验证，未修改 API、未修改前台主流程、未接入正式算法链路。

## 样本与结果统计

- 样本总数：7
- 轻微正收益：7
- 中性或收益不足：0
- 风险样本：0
- 是否建议进入 19 张黄金集：是

## 逐样本结果

| sample_id | 类型 | 判断 | edge_delta_proxy | texture_delta_proxy | p95_delta_e | saturation_delta | size_ratio | 说明 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `wechat_longscreenshot_2026-06-12_111900_080` | text_dense_long_screenshot | minor_positive | 0.08083 | 0.135424 | 1.414214 | -5.8e-05 | 1.091413 | minor edge and texture proxy gain; requires crop review |
| `green_c_product_kv` | product_kv | minor_positive | 0.068722 | 0.102385 | 1.0 | 5.4e-05 | 1.103935 | minor edge and texture proxy gain; requires crop review |
| `purple_beauty_product_kv` | product_kv | minor_positive | 0.08068 | 0.113404 | 1.414214 | 4.7e-05 | 1.102005 | minor edge and texture proxy gain; requires crop review |
| `dji_horizontal_infographic` | text_dense_infographic | minor_positive | 0.406641 | 0.282267 | 1.732051 | 0.000304 | 1.100956 | minor edge and texture proxy gain; requires crop review |
| `liu_qiangdong_commercial_portrait` | portrait_poster | minor_positive | 0.55257 | 0.217462 | 2.236068 | 0.000986 | 1.13712 | minor edge and texture proxy gain; requires crop review |
| `wei_zhongxian_character_card` | character_info_card | minor_positive | 0.55266 | 0.324381 | 2.236068 | 0.001231 | 1.123306 | minor edge and texture proxy gain; requires crop review |
| `andy_lau_commercial_portrait` | portrait_poster | minor_positive | 0.327169 | 0.188796 | 2.0 | 0.000623 | 1.116747 | minor edge and texture proxy gain; requires crop review |

## 判断

Round 2 离线候选在 7 张指定商业样本上达到进入下一步验证的最低指标门槛：

- 7/7 样本出现轻微正向指标变化；
- 2 张产品 / 商业 KV 样本均出现边缘与纹理代理指标正向变化；
- 长截图与 DJI 信息图出现文字/边缘代理指标正向变化；
- 3 张人物/角色海报出现材质或边缘代理指标正向变化；
- 未检测到明显饱和度漂移；
- p95 Delta E 处于保守范围；
- 文件体积增长约 9.1% - 13.7%，需要继续由人工视觉裁切确认收益是否支撑体积增长。

因此：

- 可以进入人工 100% 裁切视觉复核；
- 人工复核通过后，建议进入 19 张黄金集；
- 当前仍未冻结；
- 当前未提交正式算法改动；
- 当前候选仍是离线验证，不代表已经接入正式生产链。
