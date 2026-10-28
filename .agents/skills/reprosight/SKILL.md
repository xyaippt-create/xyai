---
name: reprosight
description: Turn screenshots, screen recordings, and vague UI bug reports into reproducible failures, regression tests, minimal code fixes, and before/after evidence. Use when Codex is asked to diagnose and fix a visual or interaction bug in a local web repository, prove a patch resolves a reported issue, or create an auditable debugging report. Do not use for code review without a reported defect, feature development, or production incident response that lacks a safe local reproduction target.
---

# ReproSight

Convert a visual report into a verified repair. Keep an evidence trail under
`.reprosight/runs/<run-id>/` and never claim success without a failing-before,
passing-after check.

Resolve paths relative to this `SKILL.md`. The workflow CLI is
`scripts/reprosight.mjs`; run it with Node.js 20 or newer.

## Workflow

1. **Create the case.** Identify the repository root, reported behavior, expected
   behavior, target URL or route, and supplied image. Initialize a run:

   ```text
   node <skill-dir>/scripts/reprosight.mjs init --repo <repo> --title <title> \
     --description <report> --url <url> --screenshot <image>
   ```

2. **Inspect before running.** Read repository guidance and existing scripts.
   Preserve unrelated user changes. Prefer the project's own dev and test commands.

3. **Reproduce before editing.** Start the application locally, navigate the
   reported path with an available browser or Playwright, perform the reported
   interaction, and capture the visible failure. Record the reproduction:

   ```text
   node <skill-dir>/scripts/reprosight.mjs record --repo <repo> --run <id> \
     --stage reproduction --status complete --summary <what-happened> \
     --artifact <before-image>
   ```

4. **Prove the bug.** Add the smallest stable regression test that exercises the
   user-visible behavior. Run it before changing product code. It must fail for the
   reported reason, not because setup is broken. Record `test-before` with the
   command, exit code, and concise failure.

5. **Apply the minimum fix.** Patch only the code needed to satisfy the expected
   behavior. Record `patch` with a summary and changed files. Do not weaken, skip,
   or delete the regression test to make the run pass.

6. **Verify broadly enough.** Rerun the regression test, relevant existing tests,
   and a build or type check when available. Repeat the browser interaction and
   capture an after image. Record `verification` as `passed` only when the checks
   actually pass; otherwise record `failed` and continue debugging.

7. **Generate the proof.** Create the HTML and Markdown report:

   ```text
   node <skill-dir>/scripts/reprosight.mjs report --repo <repo> --run <id>
   ```

   Return links to the report, regression test, patch, and evidence images.

## Integrity rules

- Do not edit product code before capturing the failure unless reproduction is
  impossible and the user explicitly accepts a source-only diagnosis.
- Do not fabricate screenshots, commands, exit codes, or passing results.
- If the report is ambiguous, test the most concrete interpretation and state the
  assumption in the run summary.
- Stop before destructive actions, external writes, deployments, purchases, or
  expanding beyond the selected repository.
- Read [references/evidence-contract.md](references/evidence-contract.md) when a
  stage status or required evidence is unclear.

## Common commands

```text
node <skill-dir>/scripts/reprosight.mjs list --repo <repo>
node <skill-dir>/scripts/reprosight.mjs show --repo <repo> --run <id>
node <skill-dir>/scripts/reprosight.mjs serve --repo <repo> --port 4174
node <skill-dir>/scripts/reprosight.mjs doctor --repo <repo>
```
