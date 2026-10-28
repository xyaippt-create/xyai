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
