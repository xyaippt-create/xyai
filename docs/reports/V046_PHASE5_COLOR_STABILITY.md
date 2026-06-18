# V0.4.6 Phase 5 Color Stability Regression

## 1. Git Baseline

- Phase 4 freeze commit: `72bfc4bf3fed040c04be939a328031627c5bd1fc`
- Phase 5 start HEAD: `72bfc4bf3fed040c04be939a328031627c5bd1fc`
- Phase 5 scope:
  - default fidelity color stability
  - user-enabled single-image color correction
  - diagnostics for color drift, saturation drift, fallback and correction skip reasons

## 2. Implementation Summary

Phase 5 is implemented as independent algorithm modules:

- `engine/algorithms/color_stability.py`
- `engine/algorithms/single_image_color_correction.py`

Formal call chain remains:

```text
main.py
-> engine.pipeline.process_v046_delivery
-> rules/pipeline_rules.yaml
-> v046_delivery_adapter
-> process_v036_output
-> Phase 1
-> Phase 2
-> Phase 3
-> Phase 4
-> Phase 5 color stability / correction
-> safe_copy_final
-> final_output_url
```

`backend/v036_output_core.py` only performs orchestration, parameter mapping and diagnostic field assembly.

## 3. Default Fidelity Color Stability

Default mode does not perform creative color correction. It only monitors and limits unintended color drift from the prior processing chain.

Main fields added:

```text
phase5_color_stability_active
phase5_color_lock_mode
phase5_color_drift_detected
phase5_color_fallback_triggered
phase5_color_fallback_reason
phase5_mean_delta_e_before / after
phase5_p95_delta_e_before / after
phase5_saturation_delta_before / after
phase5_high_saturation_pixel_ratio_delta_before / after
phase5_skin_tone_delta_before / after
phase5_brand_color_delta_before / after
phase5_highlight_color_delta_before / after
phase5_shadow_color_delta_before / after
```

Protection behavior:

- Alpha images: default color stability is disabled.
- clean brand KV / dense text / fine-line layout: skipped or monitored only.
- saturation drift: uses `saturation_guard`.
- chroma drift without saturation drift: uses `chroma_saturation_guard`.
- if color locking increases mean Delta E or p95 Delta E beyond guard limits: fallback to the Phase 4 frozen image.

## 4. Huawei Color Stability Case

Tracked issue:

```text
issue_id: phase5_color_stability_huawei_sample
source_stage: original_to_phase2
mean_delta_e_original_to_phase2: 2.054837
p95_delta_e_original_to_phase2: 5.09902
mean_saturation_delta: +0.037547
high_saturation_pixel_ratio_delta: +0.055545
target_phase: Phase 5
```

Current targeted result:

| metric | Phase 4 frozen | Phase 5 default |
|---|---:|---:|
| quality_1080p_pass | true | true |
| lock mode | - | saturation_guard |
| mean Delta E | 2.898571 | 2.932656 |
| p95 Delta E | 7.348469 | 7.348469 |
| saturation delta | +0.042640 | +0.005192 |
| brand color Delta E | 3.224577 | 3.258030 |
| skin tone Delta E | 3.180677 | 3.226803 |

Conclusion:

- The visible saturation lift is controlled in default fidelity mode.
- The p95 Delta E does not increase.
- Huawei red, deep blue background and highlight regions are protected by conservative drift guards.
- The original Huawei color drift still originates before Phase 5, from the earlier processing chain. Phase 5 does not rewrite color style; it prevents further unintended saturation expansion.

## 5. Targeted Samples

Targeted samples completed: `9/9`.

| sample_id | default result | correction-enabled behavior |
|---|---|---|
| huawei_enterprise | saturation_guard; quality unchanged | skipped: brand_or_text_color_protected |
| real_low_light_person | chroma_saturation_guard; quality unchanged | skipped: brand_or_text_color_protected |
| real_product_lowquality | saturation_guard; quality unchanged | skipped: brand_or_text_color_protected |
| real_architecture_lowquality | delta_e_guard_preserve_phase4; quality unchanged | skipped: brand_or_text_color_protected |
| synthetic_brand_color_bars | disabled; unchanged | skipped: brand_or_text_color_protected |
| synthetic_gradient_band | monitor_pass; unchanged | skipped: brand_or_text_color_protected |
| smoke_text_poster_cn_small_legacy | disabled; unchanged | skipped: brand_or_text_color_protected |
| synthetic_highlight_clip | disabled; unchanged | skipped: brand_or_text_color_protected |
| synthetic_neutral_yellow_cast_portrait | monitor_pass; unchanged | skipped by formal text/brand risk gate |

Known limitation:

The current formal targeted samples do not include a clean real photo with clear color cast and no brand/text risk. Therefore, the formal pipeline correctly proves safe skip behavior, but does not yet provide a user-visual positive example for active correction.

Algorithm-level probe for user-enabled correction:

| probe | disabled | enabled |
|---|---|---|
| correction active | false | true |
| cast direction | yellow | yellow |
| correction strength | 0.0 | 0.16 |
| mean Delta E vs neutral probe | 35.314560 | 33.912117 |
| p95 Delta E vs neutral probe | 35.972210 | 34.496376 |
| saturation delta vs neutral probe | +0.196777 | +0.145828 |

This verifies:

- `color_correction_enabled=false` keeps correction disabled.
- `color_correction_enabled=true` can activate on a reliable non-brand cast probe.
- low-confidence and brand/text-risk inputs remain skipped.

## 6. Golden Regression

Golden ready set completed: `19/19`.

| metric | result |
|---|---:|
| completed | 19 |
| failed | 0 |
| quality pass before | 12 |
| quality pass after | 12 |
| Phase 5 stability active | 3 |
| color fallback count | 2 |
| user correction count | 0 |

Active/default color stability samples:

```text
smoke_portrait_ready
core_product_low_png
core_unknown_opaque_rgba
```

Fallback samples:

```text
core_product_low_png: delta_e_guard
core_unknown_opaque_rgba: delta_e_guard
```

Quality gate changes:

```text
none
```

Alpha samples:

```text
smoke_transparent_png_legacy: disabled
core_unknown_opaque_rgba: delta_e_guard_preserve_phase4
synthetic_alpha_edges: disabled
```

## 7. API And SSE Regression

Validated:

```text
engine.pipeline formal entry: PASS
pipeline_call_count=1: PASS
JPG upload: PASS
ordinary PNG upload: PASS
transparent PNG upload: PASS
Chinese small text upload: PASS
task polling: PASS
SSE: PASS
SSE reconnect: PASS
double subscribe: PASS
failed-task SSE: PASS
final_output_url: PASS
final file exists: PASS
```

The API accepts:

```text
color_correction_enabled: boolean
default: false
```

Default upload behavior remains unchanged.

## 8. Known Issues

Allowed known issues:

- historical file-size expansion remains outside Phase 5 scope.
- some clean brand / text / layout samples are fully skipped by safety policy.
- Huawei original-to-Phase2 color drift remains recorded as a historical color-stability issue.
- user-enabled correction still needs a clean real color-cast photo without brand/text risk for user visual confirmation.

## 9. Freeze Decision

Conclusion: `PASS_WITH_KNOWN_ISSUES`

Phase 5 default fidelity color stability is allowed to freeze.

User-enabled single-image color correction is implemented and safe-gated. It is allowed to ship as a conservative opt-in candidate, with the limitation that active correction needs an additional real-world cast sample for final visual proof.

Allowed next step:

```text
可以进入下一阶段，但主动色偏修复建议补充真实偏色照片继续用户视觉确认。
```
