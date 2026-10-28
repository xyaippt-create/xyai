# 影界 HDDE｜4K 已关闭路线最小登记

适用版本：`V0.5.6-dev`

本文件只保留已失败或未证明路线的长期认知，不保留其执行器、候选图、专用验证器或复核包。

当前必须继承的安全边界：

- 正式 4K 处理器：`engine/image_processing_routing/four_k_v1.py::process_4k_v1_image`
- 已证明隔离安全核心：`engine/hd_core/safe_base.py`
- 候选隔离、真实性门禁与回退：`engine/hd_core/pipeline.py`
- 最小真实信息基准：`artifacts/e1_01_real_information_baseline_v1/`
- 正式 API 当前未调用隔离 SAFE_CORE 包装层；这是下一版本架构输入，不属于本轮清理范围。

## 已关闭路线

| ROUTE | RESULT | DROP_REASON | KEY_EVIDENCE_SUMMARY | DO_NOT_REOPEN |
| --- | --- | --- | --- | --- |
| SC-IBP | DROP | 源重投影收敛不能证明真实信息恢复 | 3/3 独立 GT 门禁均未通过；真实图未出现有意义可见增益。本行是 RESET-02 后保留的最小结论证据。 | 当前实现：YES |
| Simple Global Blind Degradation | DROP | 单图边缘扩散盲估计不足以可靠识别真实退化 | 已知退化 Tikhonov Oracle 仅证明研究上限；真实单图盲估计和真实信息增益未证明。本行是 RESET-02 后保留的最小结论证据。 | 当前估计器：YES |
| Selective High-Frequency Detail | DROP | `SHARPER_ONLY`、`HIGH_FREQUENCY_ONLY` | 高频与边缘增强未形成 GT 一致、可重复的真实信息恢复；执行阶段的 `PENDING_HUMAN_VISUAL_REVIEW` 已被正式 DROP 结论取代。 | 当前实现：YES |
| Restore-Then-Reconstruction | DROP | `NO_VISIBLE_GT_CONSISTENT_REAL_INFORMATION_GAIN`、`METRIC_ONLY_CHANGE` | 仅 3/11 ROI 指标方向改善，没有肉眼可见的 GT 一致信息恢复。本行是 RESET-02 后保留的最小结论证据。 | 当前实现：YES |
| Local Degradation Evidence | DROP | 只有全局 Case 信号，没有可信 patch 级定位能力 | 软化与重采样不可稳定区分，置信度未校准到局部真值；`UNCERTAIN` 只可作为安全回退，不能作为技术证明。 | 当前实现：YES |
| Single Learned Reconstruction | DROP | `METRIC_ONLY_OR_UNSTABLE_GT_CONSISTENCY`、无可信多 Case 可见增益 | 0/6 整图通过联合 GT 方向门禁，5/6 Case 的 overshoot 增加。本行是 RESET-02 后保留的最小结论证据。 | 当前候选：YES |
| UB-01 RealESRGAN Comparator | UPPER_BOUND_NOT_CONFIRMED | 感知锐化以身份、文字、Logo、材质真实性和 overshoot 为代价 | 7 个 GT Case 未形成可信适用范围，`READY_FOR_UB_02=false`。本行是 RESET-02 后保留的最小结论证据。 | 当前比较器作为 Core：YES |

## 已退出的前置实验家族

| FAMILY | FINAL KNOWLEDGE | CURRENT DISPOSITION |
| --- | --- | --- |
| 传统 Stage-1 三路线基线 | Pillow LANCZOS 是正式稳定基线；标准、选择结果与 E1-01 所需样本继续保留 | 删除旧执行器和重复过程数据 |
| Stage-2 Conservative AI | AI 安全增益未证明，Route B 不进入产品 | 只保留正式合同引用的负结论文件 |
| SRMD / Technical Bricks Round 1 | 少数文字、Logo 边缘更锐，不构成跨样本路线证明；JPEG/结构修复无有效增益 | 删除当前执行器 |
| PLKSR-Tiny / SwinIR Lightweight | 相对 SRMD 无明确真实画质突破，主要是边缘对比变化 | 删除当前执行器 |
| Controlled RealESRGAN x2 | 生成细节可被工程分离，但真实交付价值未证明 | 删除当前执行器 |
| FiDeSR OpenVINO 迁移 | 模型可加载且文本编码器可转换，但 VAE 转换和自适应控制不满足最小移植门禁，完整推理未执行，最终结论为 `DROP` | 删除 `runtime/`、`ir/`、模型、缓存与失败运行资产；仅保留 `artifacts/fidesr_openvino_poc_20260813/manifest.json` 和 `CONCLUSION.md` 作为最小证据指针 |
| Internal Self-Exemplar | 3/3 GT 反证残差方向，真实信息增益未证明 | 删除当前执行器；仅保留 OCR 仍引用的源 Crop |
| LQ-only GCV / Tikhonov selection | Oracle 已知退化上限成立，但单图参数与退化选择未证明 | Oracle 仅作知识结论，删除当前执行器 |
| Hybrid 4K Quality Breakthrough package | 技术包停留在 BLOCKED/DRAFT，未作价值通过声明 | 删除当前执行器和孤立输出 |

## RESET-02 Source Contract Integrity

- `E1_01_ARTIFACT_TREE=PASS`；E1-01 的 GT、ROI、Benchmark 与对照产物未重建。
- `ORIGINAL_STAGE1_SOURCE_CONTRACT_FOUND=YES`。
- `E1_01_SOURCE_CONTRACT_STATUS=ORIGINAL_RECOVERED`。
- `EVIDENCE_CLAIM_LEVEL=FROZEN`。
- 原始来源：`refs/codex/turn-diffs/captures/1786413224791/7f6f8fe6-2ebf-4359-99ad-625197ba05be/base` 中的 `artifacts/4k_stage1_baseline/` 四个冻结合同 blob。
- 已恢复 `4k_standard_v1.json`、`baseline_selection.json`、`golden_samples_manifest.json` 与 `comparison_manifest.json` 的原始规范内容；其中比较清单实际 SHA256 与冻结选择合同记录的 `3e72cb93770ebacb32a90f2bfbe45acb7d4d7b31519be3a00f40fda9c39b1850` 一致。

## 长期门禁

- 单纯锐化、高频增加、边缘变硬或指标改善不得记为 `REAL_INFORMATION_GAIN`。
- GT 不得进入 Candidate 推理；GT 只用于候选生成后的真实性验证。
- Case 必须按冻结的 `case_id`、样本、退化、INPUT 与 GT 事实绑定。
- Alpha 字节一致不能升级为完整 Alpha 质量门禁通过。
- 技术执行成功不能升级为画质机制成功。
- 重新打开任何当前实现，必须先提出与已关闭机制本质不同的新证据来源；不得继续调旧阈值、旧参数或轮换相似模型。
