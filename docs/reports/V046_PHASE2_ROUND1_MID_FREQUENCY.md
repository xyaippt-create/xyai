# V0.4.6 Phase 2 Round 1 Mid-Frequency Candidate

Date: 2026-06-17
Conclusion: PASS_WITH_BLOCKERS

## Scope

Phase 2 Round 1 adds a restrained mid-frequency material candidate in `backend/v036_output_core.py`.

The candidate runs after the existing resize and basic mid-frequency detail pass, before edge enhancement. It only adjusts Lab luminance and keeps the existing color lock, highlight protection, text-safe flow, alpha output path, API, task polling, SSE, output directory, and `final_output_url` behavior unchanged.

## Seven Failure Samples

| sample_id | image_type | primary_failure_reason | belongs_to_phase2 | notes |
|---|---|---|---|---|
| smoke_text_poster_cn_small_legacy | text_poster | file_size_expansion + text gate remains failed | no | text_safe protected; not a Phase 2 material target |
| smoke_product_png_legacy | product_kv | file_size_expansion; product layer still thin | yes | useful Phase 2 decision sample |
| smoke_original_unprocessed_jpg | product_kv | low source clarity + file_size_expansion + type mismatch | partial | ordinary JPG is misread as product_kv |
| core_text_synthetic_microcopy | unknown | image_type mismatch + texture/over-smoothing risk | no | expected text_poster, current unknown |
| core_product_low_png | product_kv | file_size_expansion; low product detail | yes | useful Phase 2 decision sample |
| synthetic_gradient_band | product_kv | file_size_expansion + synthetic gradient/type mismatch | no | not a material restoration target |
| synthetic_fine_line_table | architecture | fine-line/text synthetic risk | no | protect in later text/edge phase |

## Six Decision Samples

| sample_id | quality | clarity_delta | text_delta | edge_delta | detail_delta | size_delta | keep |
|---|---|---:|---:|---:|---:|---:|---|
| smoke_original_unprocessed_jpg | false -> false | +0.8480 | -0.4994 | +0.4951 | +0.0686 | +3364 | cautious |
| smoke_product_png_legacy | false -> false | +0.3659 | +0.1160 | +0.1264 | +0.0863 | +2457 | yes |
| smoke_transparent_png_legacy | true -> true | +0.3620 | -0.3665 | +0.2176 | +0.0809 | +5813 | yes |
| smoke_text_poster_cn_small_legacy | false -> false | +0.0000 | +0.0000 | +0.0000 | +0.0000 | 0 | protected |
| core_product_low_png | false -> false | +0.3724 | +0.2453 | +0.1670 | +0.0936 | +787 | yes |
| smoke_architecture_low | true -> true | -0.0424 | +0.0175 | +0.0334 | +0.0492 | -63 | yes |

## Regression

- Phase 2 decision script: PASS, 6/6 completed.
- API upload, task polling, SSE, SSE reconnect, double subscribe, failed SSE, and final output URL: PASS.
- Text-safe sample output hash unchanged.
- Transparent PNG remains `quality_1080p_pass=true`.
- No full 19-sample golden run was executed.

## Remaining Risk

The ordinary JPG sample is still weak because it is classified as `product_kv` and has little real material texture. The candidate is worth keeping as a first-round conservative implementation, but the next step should be a second small correction around type/texture gating.
