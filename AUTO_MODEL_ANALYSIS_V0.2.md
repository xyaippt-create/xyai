# Topaz Gigapixel AutoModel 分析 V0.2

生成日期：2026-08-20

## 1. 判定边界

- **FACT**：只认 JSON 顶层 `$.autoModel` 字段及其字符串值。
- “进一步选择规则”检查精确键：`route/routing/selector/selection/rule/rules/when/condition/conditions/threshold/priority/fallback`。
- backend、scale、nets、enabled、optional 是能力描述，不自动等同于主模型选择规则。

## 2. 全部 autoModel 记录

| 文件名 | shortName | autoModel | 出现位置 | 目标 JSON 存在 | 进一步选择规则 |
|---|---|---|---|---|---|
| gde.json | gde | gde_ap | gde.json:12 / `$.autoModel` | True | NOT_FOUND |
| ggi.json | ggi | gde_ap | ggi.json:12 / `$.autoModel` | True | NOT_FOUND |
| ggn_noee.json | ggn_noee | ggn_ap | ggn_noee.json:17 / `$.autoModel` | True | NOT_FOUND |
| ggn.json | ggn | ggn_ap | ggn.json:14 / `$.autoModel` | True | NOT_FOUND |
| ggnv2.json | ggnv2 | ggn_ap | ggnv2.json:14 / `$.autoModel` | True | NOT_FOUND |
| ghc.json | ghc | ggn_ap | ghc.json:12 / `$.autoModel` | True | NOT_FOUND |
| ghq_noee.json | ghq_noee | ggn_ap | ghq_noee.json:17 / `$.autoModel` | True | NOT_FOUND |
| ghq.json | ghq | ggn_ap | ghq.json:14 / `$.autoModel` | True | NOT_FOUND |
| ghqv2_ldn.json | ghqv2_ldn | ggn_ap | ghqv2_ldn.json:13 / `$.autoModel` | True | NOT_FOUND |
| ghqv2.json | ghqv2 | ggn_ap | ghqv2.json:14 / `$.autoModel` | True | NOT_FOUND |
| gmp.json | gmp | ggn_ap | gmp.json:12 / `$.autoModel` | True | NOT_FOUND |
| gmpv2.json | gmpv2 | ggn_ap | gmpv2.json:14 / `$.autoModel` | True | NOT_FOUND |

## 3. FACT

- 含 `autoModel` 的配置共 12 个。
- 指向 `gde_ap`：`gde.json`、`ggi.json`。
- 指向 `ggn_ap`：`ggn_noee.json`、`ggn.json`、`ggnv2.json`、`ghc.json`、`ghq_noee.json`、`ghq.json`、`ghqv2_ldn.json`、`ghqv2.json`、`gmp.json`、`gmpv2.json`。
- `gde_ap.json` 与 `ggn_ap.json` 均存在。
- 12 个配置内均未发现上述进一步选择规则键。

## 4. INFERENCE

- `autoModel` 字段可证明主配置静态关联一个自动辅助配置；结合目标配置的 `parameterNames`，可合理推断其与自动参数估计有关。
- 它不能证明主模型之间的选择、阈值、优先级、回退顺序或运行时调用。

## 5. UNKNOWN

- `autoModel` 的实际执行时机。
- 辅助输出如何映射为主模型参数。
- 是否存在于扫描目录之外的应用层路由逻辑。
- 日志会话中是否实际调用过这些 autoModel。

```text
AUTO_MODEL_REFERENCE=FOUND
AUTO_MODEL_CONFIG_COUNT=12
ROUTING_EVIDENCE=NOT_FOUND
```

