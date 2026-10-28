# Topaz Gigapixel 技术分析 V0.2

生成日期：2026-08-20  
用途：影界 HDDE 自研 4K 增强技术路线决策参考

## 1. 执行边界

- Topaz 内容读取白名单仅为 `.json/.tzlog/.log`。
- 模型目录其他文件仅执行用户明确要求的 SHA256 哈希流读取，同时记录文件名、大小和修改时间；未输出、解析或加载模型内容。
- logs 下不在白名单的 `.txt` 未读取正文，也未计算 SHA256。
- 未启动 Topaz、未执行模型、未修改或复制 Topaz 文件、未修改 HDDE 代码、未执行 Git 写操作。
- 本轮仅新增四份指定 V0.2 Markdown 报告。

## 2. 交付物

- `TOPAZ_MODEL_ASSET_MAP_V0.2.md`：164 个文件的完整元数据/哈希清单、9 类资产地图、60 个 JSON 的无省略解析与 backend 矩阵。
- `MODEL_DEPENDENCY_GRAPH_V0.2.md`：594 条精确 net 引用、12 条 autoModel 引用及 FACT/INFERENCE 关系图。
- `AUTO_MODEL_ANALYSIS_V0.2.md`：全部 autoModel 出现位置、目标和进一步选择规则检查。
- `TOPAZ_GIGAPIXEL_TECHNICAL_ANALYSIS_V0.2.md`：本总报告。

## A. FACT

### A.1 资产

- 扫描文件 164 个，总计 24,583,463,353 bytes（22.895134 GiB）。
- models：157 个文件、24,576,503,889 bytes；logs：7 个文件、6,959,464 bytes。
- JSON 60 个；`.tz2` 87 个；其他文件 17 个。
- models 下 157 个文件均取得 SHA256。logs 中 5 个 `.tzlog/.log` 取得 SHA256；2 个 `.txt` 明确未读取、未哈希。
- 资产族：Wonder、GMP、TRF、GFP、IRWN、GCLC、LDCLC、SSD、UNKNOWN，共 9 类（含 UNKNOWN）。

### A.2 JSON 完整解析

- 60/60 JSON 成功解析。
- 每个 JSON 均输出：name、shortName、category、version、enabled、optional、autoModel。
- 每个 JSON 均保存 inputs 完整键值映射。
- 每个 backend/scale 均逐项保存 backend、model、parallel、scale、nets、blocks、outputs；节点名称没有缩写。
- 每个配置还附带完整解析对象，保留所有未列入矩阵的原始字段。
- 配置声明能力：OpenVINO 任一变体 43 个、ONNX 任一变体 50 个、CoreML 58 个、TensorRT 38 个；这些是配置事实，不是本机运行证明。

### A.3 依赖关系

- 完整记录 594 条 backend/scale/net 引用。
- 13 个配置明确引用 GCLC：`gde`、`ggi`、`ggn_noee`、`ggn`、`ggnv2`、`ghc`、`ghq_noee`、`ghq`、`ghqv2_ldn`、`ghqv2`、`gmp`、`gmpv2`、`trf`。
- 10 个配置明确引用 LDCLC：`ldd21`、`lddv21`、`rxl_decoder0`、`ssddec0_0`、`ssddec0_5`、`ssddec1_0`、`tpn_900_nogpu`、`tpn_900`、`tpn_nogpu`、`tpn`。
- `ap_all` 明确并列 `ggn_ap/apnb/slsp_ap`；TPN 配置明确并列 enc/unet/dec/LDCLC/embeds 资产。

### A.4 AutoModel

- 12 个配置含顶层 `$.autoModel`。
- `gde/ggi -> gde_ap`；其余 10 个配置指向 `ggn_ap`。
- 目标 `gde_ap.json`、`ggn_ap.json` 均存在。
- 这些配置中不存在 route、selector、rule、condition、threshold、priority、fallback 等进一步选择规则字段。
- `ROUTING_EVIDENCE=NOT_FOUND`。

### A.5 日志

- 深度读取 4 个 `.tzlog` 与 1 个 `.log`，共 264 行；两个 `.txt` 不在白名单，未读取。
- 日志证明 Topaz Gigapixel 1.3.4、AIEngine Normal 2.9.24、Windows 11、Intel Core i9-13900H、Intel Iris Xe Graphics。
- 日志两次出现 `loadModelInfo` 和模型注册列表；这只证明配置被发现/注册。
- 未发现实际模型推理调用。
- 未发现 OpenVINO/ONNX/CoreML/TensorRT 实际 backend 选择。
- 未发现处理参数值。
- 未发现具体输入文件、输出文件、预览或导出路径。存在一条 `Loading images from merged instance` 生命周期消息，但没有文件名或后续处理证据。
- `RUNTIME_ROUTING_EVIDENCE=NONE`。

## B. INFERENCE

- 多个主配置在同一 backend/scale 中并列主 net 与 GCLC/LDCLC，支持“主能力 + 共享辅助依赖”的结构判断；辅助模块的算法语义仍未知。
- `ghqv3_cache` 输出 `cond`、`ghqv3` 输入 `cond`，可推断候选两段关系，但没有显式调用或日志验证。
- IRWN enc/dit/dec 与 SSD enc/unet/dec 存在命名、scale 和张量衔接线索，但扫描资料没有总编排规则，不能认定实际调用顺序。
- `autoModel` 可合理理解为静态自动辅助配置引用；不能扩张为主模型自动路由证据。

## C. HDDE_REFERENCE

- 借鉴“输入证据/路由/参数计划/执行器/结果质量门禁”分层，不复用 Topaz 权重或私有格式。
- 共享辅助模块应在 HDDE 中转化为自研、可解释的文字/Logo、颜色、人物结构、光晕和伪纹理保护合同。
- backend 能力必须区分配置声明、设备可用、实际选中和运行成功四个状态。
- 多阶段模型若进入 HDDE PoC，必须有单一权威编排、完整中间合同、失败回退和真实样本净增益证明。
- UNKNOWN/UNCERTAIN 输入必须安全回退；不能因外部产品存在某模型族就推定 HDDE 路线有效。

## D. UNKNOWN

- GCLC、LDCLC 及多数缩写的算法语义。
- 多 net 数组的串行、并行、条件和融合方式。
- backend 的实际优先级、失败回退与设备选择算法。
- 主模型之间是否存在扫描目录之外的自动选择逻辑。
- Wonder/neuroserver 外部资产的实际安装位置与运行路径。
- 任何模型在当前日志会话中的真实画质效果。

## 3. 对 HDDE 当前结论的影响

- 本分析不改变影界 HDDE 当前 `REAL_VISUAL_GAIN=NOT_PROVEN`。
- Topaz 资产不得成为 HDDE 直接方案；只能作为外部架构观察。
- 后续自研验证仍需使用合法自有资产与 HDDE 真实样本门禁。

## 4. 最终状态

```text
STATUS=PASS
FILES_SCANNED=164
JSON_ANALYZED=60/60
JSON_FULL_EXTRACTION=YES
TZ2_CONTENT_READ=SHA256_STREAM_ONLY_NO_PARSE
MODEL_FAMILY_COUNT=9
MODEL_GRAPH_CREATED=YES
ROUTING_EVIDENCE=NOT_FOUND
RUNTIME_ROUTING_EVIDENCE=NONE
REPORT_CREATED=YES
GIT_WRITE=NONE
HDDE_FILES_MODIFIED=NO
```
