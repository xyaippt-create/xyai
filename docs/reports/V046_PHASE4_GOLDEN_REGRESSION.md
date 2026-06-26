# V0.4.6 Phase 4 Golden Regression

## Conclusion

FAIL

Phase 4 cannot be frozen in this run because the final coverage and golden regression exposed blocking issues.

## Git Baseline

- Phase 4 candidate commit: `6d1e1e8e75bb9bc3d2489ee22c4c3559e6831014`
- Test HEAD: `6d1e1e8e75bb9bc3d2489ee22c4c3559e6831014`

## Blocking Issues

1. Real product coverage was not proven: `real_product_lowquality` was routed to `synthetic_gradient_protected`, Phase 4 strength `0.0`, with no Phase 4 change or benefit.
2. Golden sample `core_product_low_png` showed a new low-frequency uneven dark area after Phase 4. This is a visible negative regression in a product-like sample.
3. `core_product_low_png` also recorded `detail_delta=-6.1406` and `saturation_delta=+0.037893`, which violates the Phase 4 color/fidelity guardrail for product material.

## Coverage Results

- `real_product_lowquality`: active `False`, strength `0.0`, skip `synthetic_gradient_protected`, clarity_delta `0.0`, detail_delta `0.0`, mean_delta_e `0.0`
- `real_architecture_lowquality`: active `True`, strength `0.0266`, skip `local_text_protected`, clarity_delta `0.1586`, detail_delta `-0.542`, mean_delta_e `0.977772`

## Golden Summary

- total: `19`
- completed: `19`
- failed: `0`
- phase4_active_count: `4`
- local_text_protection_count: `10`
- global_or_disabled_protection_count: `8`
- skipped_count: `15`
- quality_pass_before: `12`
- quality_pass_after: `12`

Active samples:
- `smoke_product_png_legacy`
- `smoke_original_unprocessed_jpg`
- `core_product_low_png`
- `core_unknown_opaque_rgba`

## API/SSE Regression

- JPG: upload `PASS`, polling `PASS`, SSE `PASS`, reconnect `PASS`, double subscribe `PASS`, final URL `PASS`
- 普通PNG: upload `PASS`, polling `PASS`, SSE `PASS`, reconnect `PASS`, double subscribe `PASS`, final URL `PASS`
- 透明PNG: upload `PASS`, polling `PASS`, SSE `PASS`, reconnect `PASS`, double subscribe `PASS`, final URL `PASS`
- 中文小字图: upload `PASS`, polling `PASS`, SSE `PASS`, reconnect `PASS`, double subscribe `PASS`, final URL `PASS`
- failed-task SSE: `PASS`

## Output Artifacts

- Coverage: `tests/results/v046_phase4_final_coverage/`
- Golden regression: `tests/results/v046_phase4_golden_regression/`
- Blocking sample Phase 3: `tests/results/v046_phase4_golden_regression/01_phase3_frozen/core_product_low_png/`
- Blocking sample Phase 4: `tests/results/v046_phase4_golden_regression/02_phase4_candidate/core_product_low_png/`

## Freeze Decision

Phase 4 is not frozen. Do not enter Phase 5 until the product coverage and low-frequency artifact regression are fixed and re-tested.