# 影界 HDDE｜颜色校正"挑档校色"合同补充 V1

状态：`ACTIVE`（S64-A 落地；页面交互由 S64-B 承接）
生效日期：2026-10-28
授权：产品负责人于 2026-10-28 批准 S64 产品决策与 S64-A、S64-B 任务卡（`docs/drafts/S64_AI_COLOR_LEVEL_PICK_INTEGRATION_CARDS_DRAFT.md`）。

本补充只为颜色校正新增第三种模式"挑档校色"，不修改以下内容：
- `HDDE_V0.5.7_D_LINE_COMMERCIAL_COLOR_RESTORATION_PRODUCT_TECH_CONTRACT_V1.md` 正文；
- Color Core V2 冻结记录；
- 自动校色、参考图校色两种模式的合同与行为。

## 1. 定位

- 面向 AI 生成图。用户要求修正时才修正，修正多少由用户从四档中挑选。
- 系统只做三件事：测量偏色、生成候选、做安全检查。系统不判断"这张图该不该修"。
- 依据：S63-AICOLOR-POC 已证明，对真实偏色图，中档修正可见、安全、可直接交付；而自动判定无法区分偏色与设计用色。

## 2. 修正方法（冻结自 S63）

实现位于 `engine/color_correction/level_pick.py`，版本号 `hdde.color-level-pick.v1`。

- **中性估计**：只在低饱和像素（C\* ≤ 30）中，选取最接近中性的低饱和簇；高饱和的品牌色不参与。
- **分亮度偏色曲线**：6 个 L\* 段各自测偏色，白端钉为中性，黑端沿用最暗一段的实测值。
- **色适应**：在线性光中按 Bradford 方法，把中性簇向中性移动；三档强度分别为实测偏色量的 40% / 70% / 100%。
- **灰雾修正**：只有最暗或最亮像素接近中性（C\* ≤ 12）时才认定为灰雾，用两端锚定的 L\* 分段曲线修正。
- **溢出处理**：高光柔和收顶，上限 0.995；暗部连续收底，最大到 0.002。
- **肤色保护**：检测到人脸后，脸部邻域的肤色保留 80% 原色。
- **Alpha 与隐藏 RGB**：Alpha 逐像素不变；完全透明像素的 RGB 也逐字节不变。

参数调整必须另开阶段，并重新对照 S63 的 15 张样本做验证。

## 3. 安全检查（每一档都必须通过，未通过的档位不可选择）

- 尺寸、位深、Alpha 不变；
- 裁切增量 ≤ 0.5%；
- 可信人脸（中心为肤色）的色相偏移 ≤ 10°，色度保留 ≥ 60%。

## 4. 接口

### `POST /api/color-correction/level-preview`

请求：`{source_token, client_context?}`，不接受其他字段。

处理：
1. 用现有的正式色彩管理边界解码源图；
2. 生成轻、中、强三档，PNG 格式，带 sRGB ICC；
3. 三档写入受管缓存 `tmp_dir/color-level-preview/preview_<id>/`，不写入正式输出目录，也不登记 Task 或 Result。

返回：
- `preview_id`；
- `measurement`：偏色类别、摘要、偏色量、推荐档位、意图提示；
- `levels`：原图、轻、中、强四项，每项包含预览地址、是否可选、安全失败项、色差。

### `POST /api/color-correction/level-run`

请求：`{preview_id, level, current_task_output_root?, client_context?}`，其中 `level` 只能是 `original`、`light`、`medium`、`strong`。

**选择原图（`original`）**：
- 不生成文件，不登记 Task；
- 记录运行事件 `COLOR_LEVEL_PICK_ORIGINAL_SELECTED`；
- 该组预览随即作废。

**选择轻、中、强**：
1. 按现有颜色任务流程创建 Task，`operation_mode=LEVEL_PICK_COLOR_CORRECTION`；
2. 从源图重新渲染所选档位，像素摘要必须与预览一致，否则阻断；
3. 再做一次安全检查；
4. 经正式发布路径写入 `<输出根>\颜色校正`；
5. 校验格式、尺寸、SHA 和元数据后，登记 Result。

**错误码**：

| 情况 | 返回 |
|---|---|
| 预览不存在（含服务重启） | 404 `LEVEL_PREVIEW_NOT_FOUND` |
| 预览已过期 | 410 `LEVEL_PREVIEW_EXPIRED` |
| 预览已使用或正在执行 | 409 `LEVEL_PREVIEW_ALREADY_USED` |
| 所选档位不可选 | 409 `LEVEL_NOT_SELECTABLE` |
| 源图已变化 | 409 `SOURCE_IDENTITY_CHANGED` |
| 档位未知 | 400 `LEVEL_PICK_UNKNOWN_LEVEL` |
| 请求含未知字段 | 400 `LEVEL_RUN_REQUEST_INVALID` |

预览会话只存在于当前服务进程内，服务重启后全部失效，因此正式结果不可能来自用户在本次运行中没有看到的预览。

`GET /api/color-correction/capabilities` 新增：`level_pick_available`、`level_pick_version`、`level_pick_preview_endpoint`、`level_pick_run_endpoint`、`level_pick_levels`。

## 5. Result 语义（复用现有的人工确认交付，不新增 FinalAction）

用户选定某一档，即视为对该候选的人工确认。Result 字段如下：

| 字段 | 值 |
|---|---|
| `result_action` / `d3_final_action` | `REVIEW_REQUIRED` |
| `output_selected` | `REVIEW_CANDIDATE` |
| `result_review_status` | `confirmed` |
| `delivery_acceptance_authority` | `HUMAN_CONFIRMED_REVIEW` |
| `delivery_eligible` | `true` |
| `d3_status` | `LEVEL_PICK_USER_SELECTED`（表示没有 D3 自动接受） |
| `d1_action` | `NOT_APPLICABLE_USER_LEVEL_PICK` |

- 输出中心和智能交付沿用现有的"颜色人工确认交付"判定，无需另做改动。
- Result 中的 `analysis.LEVEL_PICK`、`analysis.LEVEL_PICK_SAFETY`、`selected_level` 和 `parameters.strength`，记录了实际测量结果、安全检查结果和所选档位。

## 6. 不变项

- 原图不被覆盖；
- 正式目录只新增用户选定的结果文件；
- Settings、版本号、其他功能页面不变；
- 自动校色、参考图校色、批量颜色校正的行为不变。

## 7. 参考图挑档（S66-A，2026-10-28 增补）

授权：负责人于 2026-10-28 批准 S66 决策（选方案 A：用新流程升级"参考图校色"页签，页面改动在 S66-B）及 S66-A、S66-B 任务卡（`docs/drafts/S66_REFERENCE_LEVEL_PICK_INTEGRATION_CARDS_DRAFT.md`）。

### 7.1 方法（冻结自 S65 R3）

实现位于 `engine/color_correction/reference_level_pick.py`，版本号 `hdde.color-reference-level-pick.v1`。

- 把目标图（C\* ≤ 50）与参考图（C\* ≤ 30）中合格像素的颜色，换算到对数色度 (log R/G, log B/G)，用二维互相关求出两者之间的偏移；搜索范围 ±0.40，并做亚格精修。
- 分三个亮度段（15–40、40–70、70–99）分别对齐。某段证据不足，或与整图偏移相差超过 0.15 时，改用整图偏移。段与段之间分段线性过渡，两端平延。
- 在线性光中用通道增益 exp(−强度 × 偏移) 修正，并保持每个像素的亮度；三档强度 40% / 70% / 100%。肤色保护、柔和收顶与收底、Alpha 规则、安全检查均沿用第 2、3 节。
- 参考图只提供"白应该是什么白"，不提供颜色、明暗或内容。
- 两张图色度分布的互相关峰值不明显（峰值比 < 1.15）时，判定参考图"不可用"：各档保持原样，且不可选择。

### 7.2 接口

`POST /api/color-correction/level-preview` 增加可选字段 `reference_source_token`：

- 带这个字段时，走参考图挑档流程；不带时，行为与第 4 节完全相同。
- 参考图会话无效返回 404 `REFERENCE_TOKEN_INVALID`；参考图内容已变化返回 409 `REFERENCE_IDENTITY_CHANGED`。
- 响应增加 `reference_preview_url`、`reference_display_name`。
- `measurement` 包含以下字段：
  - `summary`：如"目标图比参考图偏黄"，或"两张图的色调已接近"；
  - `measured_offset`：中灰的 Lab 偏移量；
  - `recommended_level`：偏移量 ≥ 3 时为"中"，否则为"原图"；
  - `reference_usable`；
  - `notice`：可用时提示"结果会采用参考图的白，请选同一系列、同一光线的参考图"，不可用时提示换参考图。

`POST /api/color-correction/level-run` 的请求字段不变：
- 参考图挑档的会话在执行前会再次校验参考图 SHA，不一致返回 409 `REFERENCE_IDENTITY_CHANGED`。
- 预览中不可选的档位返回 409 `LEVEL_NOT_SELECTABLE`。

`GET /api/color-correction/capabilities` 增加 `reference_level_pick_available` 和 `reference_level_pick_version`。

### 7.3 Result

- `operation_mode` 为 `REFERENCE_LEVEL_PICK_COLOR_CORRECTION`。交付语义与第 5 节完全相同：用户选定即人工确认，不新增 FinalAction。
- Result 额外记录以下内容：
  - `analysis.REFERENCE_LEVEL_PICK`：偏移量、分段结果、描述、推荐档位；
  - `analysis.REFERENCE_PROVENANCE.reference_source_fingerprint`（参考图 SHA）；
  - `parameters.reference_sha256`。
- 参考图只读：不被修改，不作为输出，也不进入输出中心。

### 7.4 旧参考图校色

`POST /api/color-correction/reference-run` 及其 `REFERENCE_COLOR_CORRECTION` 结果保持原样，历史任务照常可读。按方案 A，S66-B 起页面不再调用这个接口：参考图页签改为四档预览，由用户挑选；参考图不可用时，被锁定的档位提示"参考图不可用，不可选"。

