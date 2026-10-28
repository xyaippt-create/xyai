# Topaz Gigapixel 外部技术资产只读分析 V0.1

生成日期：2026-08-20  
研究目标：为影界 HDDE 自研 4K 增强路线提供外部资产结构参考  
扫描范围：`D:\Adobe\Topaz Gigapixel\models`、`D:\Adobe\Topaz Gigapixel\logs`

## 0. 结论摘要

- **FACT**：两个目录合计扫描 164 个文件、24,583,463,353 bytes（22.895134 GiB）。其中 `models` 157 个文件、24,576,503,889 bytes；`logs` 7 个文件、6,959,464 bytes。
- **FACT**：存在 60 个 JSON，60/60 均可由 PowerShell JSON 解析器解析；但 Topaz 自身日志两次报告 `neuroserver.json` 因缺少 `shortName` 而不能被 ModelManager 按普通模型配置解码。
- **FACT**：按扩展名严格计数有 87 个 `.tz2`（13,512,385,759 bytes）；另有 3 个 `.onnx.data` 和 2 个 `.pb`。若只作“模型二进制候选”宽口径统计，则为 92 个文件、24,572,236,511 bytes。`.bin` 未计入权重，因为配置显示其可作为 prompt/embed 辅助资产，不能只凭扩展名认定为模型权重。
- **FACT**：请求指定的 7 个命名族均有证据：Wonder、GMP、TRF、GFP、IRWN、GCLC、SSD；其余 103 个文件严格标为 `UNKNOWN`，不将缩写擅自展开为模型含义。
- **FACT**：35 个 JSON 在至少一个 backend/scale 中声明多个 `nets`；13 个配置明确引用 `gclc`，10 个配置明确引用 `ldclc`；12 个主配置含 `autoModel`。
- **FACT**：配置层声明支持 OpenVINO 系列的 JSON 有 43 个、ONNX 系列 50 个、CoreML 58 个、TensorRT 38 个；34 个同时声明四类 backend。配置文本中 53 个出现 fp16、37 个出现 fp32，其中 36 个两者都出现。
- **FACT**：现有日志没有模型推理事件、输入/输出文件、增强参数或实际 backend 选择。因此实际调用模型、参数、backend 和完整推理调用链均为 `NOT_OBSERVED`。
- **INFERENCE**：静态配置显示这是“任务模型 + 参数预测/条件生成 + 共享颜色/参考模块 + 多 backend 变体”的组合资产体系，而不是单一超分模型集合。该结论是结构推断，不是运行验证。
- **HDDE_REFERENCE**：可借鉴的是能力分层、输入证据路由、共享保护模块、backend 能力矩阵和组合链路的显式契约；不可借用或直接接入任何 Topaz 权重、格式、参数或私有运行链。

## 1. 方法、边界与证据等级

### 1.1 执行方法

1. 递归枚举目录、文件名、扩展名、大小和修改时间。
2. 只对 `.json` 使用文本读取与 JSON 解析；提取顶层字段、backend、scale、net 引用和输出张量名。
3. 只对 `*.tzlog` 和 `*.log` 做文本读取与关键词核验；安装器 `.txt` 只进入资产统计，不进入运行调用链结论。
4. 不启动 Topaz，不实例化模型运行时，不执行推理，不计算权重哈希，不解析模型内部图结构。
5. 不修改 Topaz 目录、HDDE 代码、配置、Git staging 或既有工作区成果；仅创建本报告。

### 1.2 标签定义

- **FACT**：目录元数据、JSON 明文或日志明文直接证明。
- **INFERENCE**：根据文件命名、张量衔接和配置结构作出的有限推断。
- **HDDE_REFERENCE**：仅针对影界 HDDE 自研架构的可借鉴方向，不代表可复制 Topaz 实现。
- **UNKNOWN**：缺乏足够直接证据，不猜测缩写或用途。

### 1.3 执行偏差

- **FACT / NOTE**：一次读取代表文件的命令误将 `gclc-v1-fp16-192x192-4x-ov.tz2` 包含在文本读取列表中。PowerShell 将其作为原始字节读入并输出乱码；没有模型解析、反序列化、运行时加载或推理，也没有任何文件写入。
- 这不构成模型执行或逆向，但按“不得加载 `.tz2`”的严格字面要求属于一次读取偏差。发现后已停止所有 `.tz2` 内容读取，后续只使用文件元数据和 JSON 中的文件名引用。因此本报告状态为 `PASS_WITH_NOTES`，不是无条件 `PASS`。

## 2. 资产统计

### 2.1 根目录统计

| 根目录 | 文件数 | 字节数 | 约合 |
|---|---:|---:|---:|
| `models` | 157 | 24,576,503,889 | 22.89 GiB |
| `logs` | 7 | 6,959,464 | 6.64 MiB |
| 合计 | 164 | 24,583,463,353 | 22.895134 GiB |

目录结构中还存在一个空目录：`models\neuroserver`。

### 2.2 文件类型统计

| 扩展名 | 数量 | 字节数 | GiB |
|---|---:|---:|---:|
| `.tz2` | 87 | 13,512,385,759 | 12.584390 |
| `.data`（均为 `.onnx.data`） | 3 | 6,179,651,584 | 5.755249 |
| `.pb` | 2 | 4,880,199,168 | 4.545040 |
| `.txt` | 4 | 8,503,087 | 0.007919 |
| `.yaml` | 1 | 1,746,924 | 0.001627 |
| `.bin` | 2 | 788,480 | 0.000734 |
| `.json` | 60 | 147,393 | 0.000137 |
| `.tzlog` | 4 | 40,875 | 0.000038 |
| `.log` | 1 | 83 | 0 |

**FACT**：`.tz2` 数量 87 是基于扩展名的严格统计，不证明每个文件都是完整独立权重。特别是 10 个本机 `gclc` 文件总计只有 293,681 bytes，不能只凭后缀判定其内部承载方式。

## 3. 模型族资产地图

分类规则仅使用用户给定族名与文件名前缀。未命中者一律 `UNKNOWN`。

| 模型族 | 全部文件 | JSON | `.tz2` | 字节数 | 关键资产事实 |
|---|---:|---:|---:|---:|---|
| Wonder | 4 | 4 | 0 | 5,938 | 只有 JSON；配置引用外部 zip 包，扫描根目录中无对应 zip |
| GMP | 8 | 2 | 6 | 619,827,903 | `gmp`/`gmpv2`，2x/4x，含 fp16/fp32 文件 |
| TRF | 5 | 2 | 3 | 104,062,947 | `trf` 2x/4x；`trfn` 1x |
| GFP | 6 | 3 | 3 | 222,996,184 | `gfp-l`、`gfp-s`、`gfpf`，均为 Face Recovery 配置 |
| IRWN | 9 | 3 | 3 | 6,190,532,773 | enc/dit/dec 三段；另有 3 个大型 `.onnx.data` |
| GCLC | 10 | 0 | 10 | 293,681 | 无独立 JSON；作为多个主配置的第二网络被引用 |
| SSD | 12 | 7 | 5 | 2,099,876,017 | enc、unet、3 个 dec 配置及 mac 专用配置 |
| UNKNOWN | 103 | 39 | 57 | 15,338,908,446 | 所有未命中指定前缀的资产；不猜测缩写 |

### 3.1 Wonder

- **FACT**：`wonder-2.json`、`wonder-3.json`、`wonder-all.json` 均标记 `isNeuroserverModel=true`，并以平台 zip 名作为 net；`wonder-3.5.json` 的 `backends` 为空。
- **FACT**：`neuroserver.json` 的 `models` 只列出 `wonder-2` 和 `wonder-all`，不含 `wonder-3` 或 `wonder-3.5`。
- **FACT**：日志中的特性状态包含 `local-wonder-model=on`，但当前扫描目录没有 Wonder zip，且没有 Wonder 推理记录。
- **INFERENCE**：Wonder 的模型安装/运行可能由独立 neuroserver 资产管理，不等同于本目录内 `.tz2` 模型体系。没有运行证据，不进一步推断其实现。

### 3.2 GMP / TRF / GCLC

- **FACT**：GMP、GMP V2、TRF 的主配置在同一 scale 下都列出主 net 与 `gclc` net，并为两者分别声明输出。
- **FACT**：GMP/GMP V2 支持 2x、4x；TRF 支持 2x、4x；TRFN 支持 1x，且引用的是 `clc` 而不是 `gclc`。
- **INFERENCE**：`gclc` 是多种增强主模型共享的辅助模块；其确切语义未知。不能仅凭 `clc` 字符串将其断言为颜色校正器。

### 3.3 GFP

- **FACT**：`gfp-l`、`gfp-s`、`gfpf` 的配置名称分别为 `Face Parse Large`、`Face Parse Small`、`Face Parse Filtering`，category 均为 `Face Recovery`，scale 均为 1。
- **INFERENCE**：它们更像面部恢复链的解析/过滤辅助能力，而非通用 4K 主模型；是否与 `gfg/gfrf/gfrg` 在运行时组合，日志未证明。

### 3.4 IRWN

- **FACT**：`irwn_enc` 输出 `latent_sample`、scale 0.125；`irwn_dit` 输入 `sample` 并输出 `out_sample`、scale 1；`irwn_dec` 输入 `latent_sample` 并输出 `sample`、scale 8。
- **FACT**：ONNX/OpenVINO 变体引用 `.tz2 + .onnx.data` 双文件组合。
- **INFERENCE**：文件名与张量/scale 构成 encoder → latent processing → decoder 的三段结构线索，但配置没有提供一个显式总编排文件，故顺序与数据转换细节未验证。

### 3.5 SSD

- **FACT**：`ssdenc` 输出 `latent`，`ssdunet` 输出 `noise_pred`，三个 `ssddec*` 输出 `image` 与 `netOutput`；decoder 同时引用 `ldclc`。
- **FACT**：encoder 还引用 `default_prompt.bin`；mac 专用 enc/unet 配置只声明 CoreML。
- **INFERENCE**：这是明显的多段组合资产，但现有配置没有单一顶层文件明确列出全部执行顺序，不能把静态张量名当作已验证调用链。

## 4. JSON 深度解析总览

### 4.1 完整性与字段覆盖

| 项目 | 结果 |
|---|---:|
| JSON 总数 | 60 |
| 成功解析 | 60 |
| 解析失败 | 0 |
| 含 `name` | 56 |
| 含 `shortName` | 59 |
| 含 `category` | 56 |
| 含 `version` | 60 |
| 含 `enabled` | 60 |
| 含 `optional` | 59 |
| `enabled=3` / `enabled=1` | 39 / 21 |
| `optional=0` / `optional=1` / 缺失 | 20 / 39 / 1 |

**FACT**：`enabled`、`optional` 是数值字段；配置未提供其枚举语义，因此本报告不猜测 1、3 的业务含义。

category 明文分布：Enhance 41、Face Recovery 7、Super Focus 3、Exposure Adjust 1、Wonder All/V2/V3/V3.5 各 1、空值 4。

### 4.2 Backend 与精度声明

| 能力 | 含该声明的 JSON 数 | 说明 |
|---|---:|---|
| OpenVINO 任一变体 | 43 | `openvino` 或 `openvino16` |
| ONNX 任一变体 | 50 | `onnx`、`onnx16` 或 `onnx_qnn` |
| CoreML | 58 | 配置键 `coreml` |
| TensorRT | 38 | 配置键 `tensorrt` |
| 同时声明以上四类 | 34 | 配置能力，不是本机实测 |
| fp16 only | 17 | net 文件名/引用只出现 fp16 |
| fp32 only | 1 | net 文件名/引用只出现 fp32 |
| fp16 + fp32 | 36 | 两种精度都出现 |
| 两者均未出现 | 6 | 含 Wonder/neuroserver 等配置 |

细分 backend 键出现次数：`openvino=32`、`openvino16=15`、`onnx=44`、`onnx16=34`、`onnx_qnn=26`、`coreml=58`、`tensorrt=38`。同一 JSON 可同时计入多个变体。

**FACT**：这些是配置声明，不等于本机安装了相应引擎或成功运行。日志没有 backend 实际选择记录。

### 4.3 全部 JSON 配置字段表

说明：`en/op` 为原始 `enabled/optional` 数值；inputs 列出输入键；outputs 汇总 backend/scale 下声明的输出张量；`CML/OX/QNN/OX16/OV/OV16/TRT` 分别代表 CoreML、ONNX、ONNX QNN、ONNX16、OpenVINO、OpenVINO16、TensorRT。空白即配置未提供。

| 配置 | name | shortName | category | v | en/op | inputs | outputs | scales | backends | precision |
|---|---|---|---|---:|---|---|---|---|---|---|
| ap_all.json |  | ap_all |  | 2 | 3/0 | ggn_gamma,input,mask | output | 1 | CML,OX,OV | fp16 |
| claa.json | Color Light General | claa | Exposure Adjust | 1 | 3/0 | input0 | netOutput | 1 | CML,OX,OV | fp32 |
| gde_ap.json |  | gde_ap |  | 1 | 1/0 | input | output | 1 | CML,OX,OV | fp16 |
| gde.json | Compression | gde | Enhance | 1 | 1/1 | cinput,gamma,input,output,param1,param2 | Identity,clip,netOutput1X,netOutput2X,netOutput4X | 1,2,4 | CML,OX,QNN,OX16,OV,OV16,TRT | fp16,fp32 |
| gffm.json | Face Mask | gffm | Face Recovery | 1 | 3/0 | input0 | netOutput | 1 | CML,OX,QNN,OX16,OV,TRT | fp16,fp32 |
| gfg.json | Face Perfect | gfg | Face Recovery | 1 | 3/1 | input0 | netOutput | 1 | CML,OX,QNN,OV,TRT | fp16,fp32 |
| gfp-l.json | Face Parse Large | gfp-l | Face Recovery | 1 | 3/0 | input0 | modelOutput | 1 | CML,OX,QNN,OV,TRT | fp16,fp32 |
| gfp-s.json | Face Parse Small | gfp-s | Face Recovery | 1 | 3/0 | input0 | modelOutput | 1 | CML,OX,QNN,OV,TRT | fp16,fp32 |
| gfpf.json | Face Parse Filtering | gfpf | Face Recovery | 1 | 3/0 | input0 | modelOutput,netOutput | 1 | CML,OX,QNN,OV,TRT | fp16,fp32 |
| gfrf.json | Face Perfect fidelity | gfrf | Face Recovery | 2 | 3/0 | input0 | netOutput | 1 | CML,OX,OX16,OV,TRT | fp16,fp32 |
| gfrg.json | Face Perfect generative v3 | gfrg | Face Recovery | 3 | 3/0 | input0 | netOutput | 1 | CML,OX,QNN,OV,TRT | fp16,fp32 |
| ggi.json | CGI | ggi | Enhance | 1 | 3/1 | cinput,gamma,input,output,param1,param2 | Identity,clip,netOutput2X,netOutput4X | 2,4 | CML,OX,QNN,OX16,OV,OV16,TRT | fp16,fp32 |
| ggn_ap.json |  | ggn_ap |  | 2 | 1/0 | input | output | 1 | CML,OX,OV | fp16 |
| ggn_noee.json | Standard noee | ggn_noee | Enhance | 3 | 3/1 | cinput,gamma,input,output,param1,param2,param3 | Identity,clip,netOutput | 2,4 | CML,OV | fp16 |
| ggn.json | Standard | ggn | Enhance | 3 | 3/1 | cinput,gamma,input,output,param1,param2,param3 | Identity,clip,netOutput | 2,4 | CML,OX,QNN,OX16,OV,TRT | fp16,fp32 |
| ggnv2.json | Standard V2 | ggnv2 | Enhance | 3 | 3/0 | cinput,gamma,input,output,param1,param2,param3 | Identity,clip,netOutput | 2,4 | CML,OX,QNN,OX16,OV,TRT | fp16,fp32 |
| ghc.json | High Compression | ghc | Enhance | 2 | 1/1 | cinput,gamma,input,output,param1,param2 | Identity,clip,strided_slice,tf_identity | 1,2,4 | CML,OX,QNN,OX16,OV,OV16,TRT | fp16,fp32 |
| ghq_noee.json | High Fidelity noee | ghq_noee | Enhance | 1 | 3/1 | cinput,gamma,input,output,param1,param2,param3 | Identity,clip,netOutput | 2,4 | CML,OV | fp16 |
| ghq.json | High Fidelity | ghq | Enhance | 1 | 3/1 | cinput,gamma,input,output,param1,param2,param3 | Identity,clip,netOutput | 2,4 | CML,OX,QNN,OX16,OV,TRT | fp16,fp32 |
| ghqv2_ldn.json | High Fidelity V2 LDN | ghqv2_ldn | Enhance | 1 | 3/0 | cinput,gamma,input,output,param1,param2,param3 | Identity,clip,netOutput | 2,4 | CML,OX,QNN,OX16,OV,TRT | fp16,fp32 |
| ghqv2.json | High Fidelity V2 | ghqv2 | Enhance | 1 | 3/0 | cinput,gamma,input,output,param1,param2,param3 | Identity,clip,netOutput | 2,4 | CML,OX,QNN,OX16,OV,TRT | fp16,fp32 |
| ghqv3_cache.json | High Fidelity V3 Cache | ghqv3_cache | Enhance | 2 | 3/0 | input0,strength,upscale | cond | 1 | CML,OX,OV,TRT | fp16 |
| ghqv3.json | High Fidelity V3 | ghqv3 | Enhance | 2 | 3/0 | input0,input1 | output | 1 | CML,OX,OV,TRT | fp16 |
| gmp.json | Low Resolution | gmp | Enhance | 1 | 3/0 | cinput,gamma,input,output,param1,param2 | Identity,clip,netOutput2X,netOutput4X | 2,4 | CML,OX,QNN,OX16,OV,OV16,TRT | fp16,fp32 |
| gmpv2.json | Low Resolution V2 | gmpv2 | Enhance | 13 | 1/1 | cinput,gamma,input,output,param1,param2,param3 | Identity,clip,netOutput | 2,4 | CML,OX,QNN,OX16,OV,TRT | fp16,fp32 |
| irwn_dec.json | irwn_dec | irwn_dec | Enhance | 2 | 3/1 | input | sample | 8 | CML,OX16,OV16 | fp16,fp32 |
| irwn_dit.json | irwn_dit | irwn_dit | Enhance | 2 | 3/1 | input | out_sample | 1 | CML,OX,OX16,OV16,TRT | fp16,fp32 |
| irwn_enc.json | irwn_enc | irwn_enc | Enhance | 2 | 3/1 | input | latent_sample | 0.125 | CML,OX16,OV16 | fp16,fp32 |
| ldd21.json | RescueD | ldd21 | Enhance | 2 | 1/1 | cinput,input,output | netOutput,sample | 8 | CML,OX,QNN,OX16,OV,TRT | fp16,fp32 |
| lddv21_noclc.json | RescueDV_NOCLC | lddv21_noclc | Enhance | 1 | 1/1 | input | sample | 8 | CML,OX,QNN,OX16,OV,TRT | fp16,fp32 |
| lddv21.json | RescueDV | lddv21 | Enhance | 1 | 1/1 | cinput,input,output | netOutput,sample | 8 | CML,OX,QNN,OX16,OV,TRT | fp16,fp32 |
| lde21.json | RescueE | lde21 | Enhance | 1 | 1/1 | input0 | latent_sample | 0.125 | CML,OX,QNN,OX16,OV,TRT | fp16,fp32 |
| ldu21.json | RescueU | ldu21 | Enhance | 2 | 1/1 | input0,input1,timestep | noise_pred,out_sample | 1 | CML,OX,OX16,OV,TRT | fp16,fp32 |
| neuroserver.json |  |  |  | 20260728.0 | 3/- |  |  |  |  |  |
| rxl_decoder0.json | RecoveryXLD0 | rxl_decoder0 | Enhance | 1 | 1/1 | cinput,input,output | netOutput,sample | 8 | CML,OX,QNN,OX16,TRT | fp16,fp32 |
| rxl_decoder1.json | RecoveryXLD1 | rxl_decoder1 | Enhance | 1 | 1/1 | input | sample | 8 | CML,OX,QNN,OX16,TRT | fp16,fp32 |
| rxl_embed.json | RecoveryXL Embed | rxl_embed | Enhance | 1 | 1/1 | input | last_hidden_state | 1 | CML,OX,OV16,TRT | fp16,fp32 |
| rxl_encoder0.json | RecoveryXLE0 | rxl_encoder0 | Enhance | 1 | 1/1 | input0 | latent_sample | 0.125 | CML,OX,QNN,OX16,TRT | fp16,fp32 |
| rxl_encoder1.json | RecoveryXLE1 | rxl_encoder1 | Enhance | 1 | 1/1 | input0 | latent_sample | 0.125 | CML,OX,QNN,OX16,TRT | fp16,fp32 |
| rxl_unet0.json | RecoveryXLU0 | rxl_unet0 | Enhance | 2 | 1/1 | conditioning_scale,input0,input1,input2,timestep | noise_pred | 1 | CML,OX16 | fp16 |
| rxl_unet1.json | RecoveryXLU1 | rxl_unet1 | Enhance | 2 | 1/1 | conditioning_scale,input0,input1,input2,timestep | noise_pred | 1 | CML,OX16 | fp16 |
| ssddec0_0.json | SingleStepSharpenDecLow | ssddec0_0 | Super Focus | 1 | 3/1 | cinput,input,output | image,netOutput | 8 | CML,OX,OX16,OV16,TRT | fp16,fp32 |
| ssddec0_5.json | SingleStepSharpenDecMid | ssddec0_5 | Super Focus | 1 | 3/1 | cinput,input,output | image,netOutput | 8 | CML,OX,OX16,OV16,TRT | fp16,fp32 |
| ssddec1_0.json | SingleStepSharpenDecHigh | ssddec1_0 | Super Focus | 1 | 3/1 | cinput,input,output | image,netOutput | 8 | CML,OX,OX16,OV16,TRT | fp16,fp32 |
| ssdenc-gpu-mac.json | SingleStepResizeEnc GPU Mac | ssdenc-gpu-mac | Enhance | 1 | 1/1 | input | latent | 0.125 | CML | fp16 |
| ssdenc.json | SingleStepResizeEnc | ssdenc | Enhance | 1 | 1/1 | input | latent | 0.125 | CML,OX,OV16,TRT | fp16 |
| ssdunet-gpu-mac.json | SingelStepResizeUnet GPU Mac | ssdunet-gpu-mac | Enhance | 1 | 1/1 | input0,input1 | noise_pred | 1 | CML | fp16 |
| ssdunet.json | SingelStepResizeUnet | ssdunet | Enhance | 1 | 1/1 | input0,input1 | noise_pred | 1 | CML,OX,OX16,OV16,TRT | fp16,fp32 |
| stdmax_noee.json | StandardMaxNoNeuralEngine | stdmax_noee | Enhance | 1 | 3/1 | input0 | noise_pred | 4 | CML | mixed |
| stdmax.json | StandardMax | stdmax | Enhance | 1 | 3/1 | input0 | noise_pred | 4 | CML,OX16,OV16,TRT | fp16 |
| tpn_900_nogpu.json | NaturalUpscale900NoGpu | tpn_900_nogpu | Enhance | 1 | 3/1 | clcInput,clcRef,decInput,encInput,unetEmbeds,unetInput,unetTimestep | netOutput,out,output | 1 | CML | fp16 |
| tpn_900.json | NaturalUpscale900 | tpn_900 | Enhance | 1 | 3/1 | clcInput,clcRef,decInput,encInput,unetEmbeds,unetInput,unetTimestep | netOutput,out,output | 1 | CML | fp16 |
| tpn_nogpu.json | NaturalUpscaleNoGpu | tpn_nogpu | Enhance | 1 | 3/1 | clcInput,clcRef,decInput,encInput,unetEmbeds,unetInput,unetTimestep | netOutput,out,output | 1 | CML | fp16 |
| tpn.json | NaturalUpscale | tpn | Enhance | 1 | 3/1 | clcInput,clcRef,decInput,encInput,unetEmbeds,unetInput,unetTimestep | netOutput,out,out_sample,output | 1 | CML,OX16,OV16 | fp16 |
| trf.json | Text Refine | trf | Enhance | 1 | 3/1 | cinput,input,output,param1,param2,param3 | Identity,clip,netOutput | 2,4 | CML,OX,QNN,OX16,OV,TRT | fp16,fp32 |
| trfn.json | Text Refine Noisy | trfn | Enhance | 1 | 3/1 | cinput,input,output,param1,param2 | Identity,netOutput | 1 | CML,OX,QNN,OX16,OV,TRT | fp16,fp32 |
| wonder-2.json | Wonder 2 | Wonder V2 | Wonder V2 | 1 | 3/0 |  | output | 1 | CML,OX |  |
| wonder-3.5.json | Wonder 3.5 | Wonder V3.5 | Wonder V3.5 | 1 | 3/0 |  |  |  |  |  |
| wonder-3.json | Wonder 3 | Wonder V3 | Wonder V3 | 1 | 3/0 |  | output | 1 | CML,OX |  |
| wonder-all.json | Wonder All | Wonder All | Wonder All | 1 | 3/0 |  | output | 1 | CML,OX |  |

## 5. 模型关系与组合结构

### 5.1 主模型与自动参数模型

**FACT**：以下 12 个配置存在显式 `autoModel` 字段：

- `gde`、`ggi` → `gde_ap`
- `ggn`、`ggn_noee`、`ggnv2`、`ghc`、`ghq`、`ghq_noee`、`ghqv2`、`ghqv2_ldn`、`gmp`、`gmpv2` → `ggn_ap`

**FACT**：`gde_ap` 输入键为 `input`，参数名为 `param1,param2`；`ggn_ap` 输入键为 `input`，参数名为 `param2,param1,param3`。`ap_all` 进一步声明 9 个 parameterNames，并在一个 scale 中组合 `ggn_ap + apnb + slsp_ap` 三个网络。

**INFERENCE**：存在“先由辅助模型估计参数，再调用主增强模型”的结构证据。`autoModel` 是明确关联，但日志没有显示实际参数值或执行先后，不能宣称运行时已验证。

### 5.2 共享 GCLC / LDCLC

**FACT**：明确引用 `gclc` 的 13 个配置为：`gde`、`ggi`、`ggn_noee`、`ggn`、`ggnv2`、`ghc`、`ghq_noee`、`ghq`、`ghqv2_ldn`、`ghqv2`、`gmp`、`gmpv2`、`trf`。

**FACT**：明确引用 `ldclc` 的 10 个配置为：`ldd21`、`lddv21`、`rxl_decoder0`、`ssddec0_0`、`ssddec0_5`、`ssddec1_0`、`tpn`、`tpn_nogpu`、`tpn_900`、`tpn_900_nogpu`。

**INFERENCE**：两者都是共享辅助模块的强结构证据。`gclc` 常与 1x/2x/4x 主输出并列；`ldclc` 常出现在 latent/decoder 路线。但它们的真实算法功能仍为 `UNKNOWN`。

### 5.3 其他组合链证据

| 结构 | FACT | INFERENCE |
|---|---|---|
| GHQ V3 | `ghqv3_cache` 输出 `cond`；`ghqv3` 输入包含 `cond` | cache/condition → tile model 的两段链证据较强 |
| IRWN | enc 0.125 → `latent_sample`；dit 1 → `out_sample`；dec 8 → `sample` | 三段编码/处理/解码链，但总编排未显式出现 |
| SSD | enc → `latent`；unet → `noise_pred`；3 个 dec → `image/netOutput` | 多档 decoder 可能代表不同强度/区域；实际选择规则未知 |
| TPN | 单个配置同时列出 enc、unet、dec、`ldclc`、`tpn_embeds.bin` 及对应输入/输出 | 当前静态证据中最明确的单配置多模型组合 |
| RXL | embed、两组 encoder/unet/decoder、vocab/merges/negative embedding 均存在 | 多阶段文本条件/恢复结构可能性高，但按用户分类仍为 UNKNOWN |

### 5.4 自动模型选择逻辑

- **FACT**：存在 `autoModel` 字段，证明主模型与参数预测配置的静态关联。
- **FACT**：存在不同 category/name、`enabled/optional`、backend、scale 和精度变体。
- **FACT**：日志只显示 ModelManager 注册模型列表，没有记录“输入特征 → 选择某主模型”的决策。
- **INFERENCE**：可确认“自动参数辅助”证据；不能确认“自动在 GMP/TRF/GHQ/SSD/Wonder 等主模型之间路由”的实现。
- `ROUTING_EVIDENCE=PARTIAL_CONFIG_ONLY`。

## 6. 日志分析

### 6.1 覆盖范围

| 类型 | 文件数 | 读取结果 |
|---|---:|---|
| `.tzlog` | 4 | 全部文本读取 |
| `.log` | 1 | 全部文本读取；仅 83 bytes 的 installer 起始行 |
| 合计 | 5 | 264 行 |

目录中的 2 个 `.txt`（一个 installer 大日志、一个空的 session 文件）不属于用户指定的 `*.tzlog`/`*.log` 深度日志范围，仅纳入资产统计。

### 6.2 运行环境

- **FACT**：Topaz Gigapixel 版本 1.3.4。
- **FACT**：AIEngine mode `Normal`，版本 2.9.24。
- **FACT**：Windows 11，Intel Core i9-13900H，20 threads，AVX/AVX2/VNNI 均标记为 1。
- **FACT**：总内存日志值 31.730705 GB；两次已用值约 16.48/16.87 GB。
- **FACT**：枚举到 1 个设备：Intel Iris Xe Graphics；`CudaId=-1`、`Capability=0`。
- **FACT / DATA_QUALITY_NOTE**：日志同时写出 `VRAM 0.125000 GB Total / 7.682676 GB Used`，已用值大于总值，明显内部口径不一致，不应拿来判断真实显存容量。
- 隐私字段（Machine ID、设备 Serial、账号 UID、鉴权令牌相关信息）未写入本报告。

### 6.3 实际调用与调用链

| 要求项 | 日志证据 | 结论 |
|---|---|---|
| 实际调用模型 | 只有 `Loaded following models` 注册列表，没有推理调用 | `NOT_OBSERVED` |
| 参数 | 无 denoise/增强参数值，无输入参数对象 | `NOT_OBSERVED` |
| backend | 无 OpenVINO/ONNX/CoreML/TensorRT 实际选择行 | `NOT_OBSERVED` |
| 输入/输出 | 无 input file、output file、preview、export 事件 | `NOT_OBSERVED` |
| 调用链 | 只看到启动 → AIEngine 初始化 → loadModelInfo → 模型列表注册 → UI → 退出 | 仅启动链被证明，推理链 `NOT_OBSERVED` |

两次可复现的启动链：

```text
Topaz Gigapixel 1.3.4 start
  -> Model Dir 指向扫描目录
  -> AIEngine Normal 2.9.24
  -> loadModelInfo
  -> neuroserver.json 缺 shortName 警告
  -> ModelManager 注册模型配置列表
  -> System Information 枚举
  -> 无图像处理事件
  -> 正常退出
```

**FACT**：日志中的多次 `Cancelling processing` 出现在初始化/退出工作线程阶段；没有对应任务开始或输入文件，因此不能当作真实增强任务被取消。

## 7. 对影界 HDDE 的技术参考

### 7.1 可借鉴方向

1. **HDDE_REFERENCE：路由与执行分离**  
   输入证据、模型/策略选择、参数计划、执行器、结果质量门禁应保持独立合同。Topaz 的 `autoModel`/主模型关系可作为“结构存在性”参考，但 HDDE 应使用自有可解释特征与冻结阈值。

2. **HDDE_REFERENCE：共享保护模块**  
   多个主模型共享辅助 net 的结构值得参考。HDDE 可将文字/Logo、肤色、边缘光晕、色彩/曝光保护作为独立、可审计的前后置模块，而不是把所有职责塞进一个模型。

3. **HDDE_REFERENCE：多 backend 能力矩阵**  
   配置应显式声明 backend、精度、tile/block、scale、最小系统能力与失败策略，并在运行结果中记录“实际选中项”，避免“配置支持”被误报为“设备已验证”。

4. **HDDE_REFERENCE：组合链显式化**  
   encoder/condition/core/decoder/refine 组合若进入 HDDE 自研 PoC，应有单一权威编排、张量/图像合同、失败回退和逐段可验证指标，不能只靠文件名约定。

5. **HDDE_REFERENCE：输入证据驱动的专用能力**  
   低分辨率、压缩、文字、面部、失焦等能力分型可作为研究维度，但任何自动路由必须先证明分类可靠度，再证明所选路线的真实净增益；`UNKNOWN/UNCERTAIN` 必须安全回退。

6. **HDDE_REFERENCE：能力安装与模型注册分离**  
   Wonder/neuroserver 的静态形态提示可把大型能力包安装、校验、注册与实际执行分开。HDDE 若未来需要可选模型，也应坚持本地、授权、可校验、不可静默下载/回退。

### 7.2 明确禁止转化为 HDDE 方案的内容

- 不复制、转换、加载、调用或再分发 Topaz `.tz2`、`.onnx.data`、`.pb`、zip 引用或辅助二进制。
- 不照搬未解释的模型缩写、参数名、backend 模板、张量名或私有格式。
- 不因 Topaz 存在某模型族就宣称 HDDE 的同类路线有效。
- 不把“配置声明多 backend/多精度”当成 HDDE 的设备兼容证明。
- 不绕过许可、鉴权、安装校验或模型注册机制。

### 7.3 对 E 线下一步的约束性建议

- 继续保持 HDDE 当前事实：4K 真实画质增益仍为 `NOT_PROVEN`，Topaz 资产地图不改变该结论。
- 若开展自研研究，优先验证一个窄问题：输入退化识别是否可靠，或一个保护模块是否产生可重复净收益；不要直接建设全模型路由平台。
- 每个候选必须使用 HDDE 自有/合法模型与真实样本，继续执行文字/Logo、人物身份、颜色、结构、伪纹理、光晕和交付价值门禁。

## 8. 限制与未证明事项

- 未读取 `.tz2` 内部结构，除“执行偏差”中说明的一次原始字节误读外；未做模型格式分析、图节点分析、权重统计或逆向。
- 未运行 Topaz，日志也没有真实推理，因此无法证明具体模型在本机可执行。
- `enabled/optional` 数值语义、`gclc/ldclc` 算法语义、主模型自动路由规则均未被公开配置直接定义。
- Wonder 引用的 zip 不在扫描目录；不能判断是否另存于其他目录或远端。
- 文件数量和大小是 2026-08-20 本次扫描快照，后续安装/更新可能变化。

## 9. 最终状态

```text
STATUS=PASS_WITH_NOTES
FILES_SCANNED=164
JSON_ANALYZED=60/60
MODEL_FAMILIES_FOUND=Wonder,GMP,TRF,GFP,IRWN,GCLC,SSD,UNKNOWN
ROUTING_EVIDENCE=PARTIAL_CONFIG_ONLY
REPORT_CREATED=TOPAZ_GIGAPIXEL_TECHNICAL_ANALYSIS_V0.1.md
```

