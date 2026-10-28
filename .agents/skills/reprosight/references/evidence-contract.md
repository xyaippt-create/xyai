# Evidence contract

ReproSight stores one `case.json` per run. Treat the file as an audit record rather
than a scratchpad.

## Stages

| Stage | Successful status | Minimum evidence |
| --- | --- | --- |
| `intake` | `complete` | title, report, repository, optional source image |
| `reproduction` | `complete` | observed steps and preferably a before image |
| `test-before` | `failed` | command, non-zero exit code, relevant failure |
| `patch` | `complete` | summary and changed file list |
| `verification` | `passed` | passing command and preferably an after image |
| `report` | `complete` | generated HTML and Markdown reports |

`test-before: failed` is positive evidence: it proves the regression test catches
the defect. `verification: failed` means the repair is not complete.

## Evidence quality

- Use the exact command that was run.
- Keep summaries factual and short.
- Store screenshots and logs under the run's `artifacts/` directory through the
  CLI instead of linking to temporary files.
- Mention assumptions when the report does not specify a route, viewport, account
  state, or exact expected behavior.
- Never mark a stage complete based only on code inspection when an executable
  check is available.

## Completion gate

A run is verified only when the defect was reproduced, the regression test failed
before the patch, the patch was recorded, and verification passed after the patch.
If any gate is missing, report the run as incomplete and name the missing gate.
