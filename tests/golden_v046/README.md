# V0.4.6 Golden Image Set

This directory contains the V0.4.6 golden image test set for VisualMasterPro / Yingjie.

Baseline relation:

- Stable base: V0.4.5.3 (`780d49b`)
- Phase 1 production freeze commit: `8bf051cd3fcc6e8f7c363c2b43eac819c1c4e6b3`
- Phase 1 complete baseline commit: `e98afe81ec401f04458fbaccaaa0d80b81f2fda8`
- Baseline tag: `v0.4.6-phase1-baseline`

Rules:

- `private/` is local-only and must not be committed.
- Ready public samples are copied test assets or project-created synthetic technical samples.
- Missing entries are intentionally recorded in `manifest.json` and `manifest.csv`; do not fill gaps with unrelated images.
- Excluded entries document large legacy-output sample gaps that are not committed as golden inputs.
- T02 does not change image algorithms, quality gates, API, SSE, frontend, or output selection logic.
