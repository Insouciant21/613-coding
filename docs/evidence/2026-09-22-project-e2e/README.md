# Real project, single-conversation verification

The real `ai2` / `gpt-5.6-terra` Responses provider built a standard-library temperature
converter module and CLI through the project's ConversationService, RunService, owned
AgentLoop, governed repository tools, subprocess validator, and SQLite store. The measurement
wrapper only records actual provider responses; it does not supply fake actions or content.

Each run started from a new Git repository containing requirements, ten acceptance tests,
a validation configuration and an ignore file. The same single user request asked the agent to
create the module, add at least three tests, document usage, validate and finish. No human or
outer assistant edited the generated implementation. Limits: 12 model calls, 4,096 output
tokens per request and 300 seconds of accounted model time.

| Run | Harness result | Calls | Input tokens | Cached input | Model-call time |
| --- | --- | ---: | ---: | ---: | ---: |
| Before repairs | budget exhausted before finish | 12 | 83,413 | 50,688 (60.8%) | 140.45 s |
| Multi-file patch repair | completed | 6 | 37,041 | 29,696 (80.2%) | 50.37 s |
| Patch repair + explicit budget-state guidance | completed | 5 | 31,240 | 10,240 (32.8%) | 47.20 s |

The baseline eventually produced a passing project, but its run is recorded as failed because
it exhausted its budget before calling finish. It was not granted extra calls or silently
relabelled a success. The failures exposed an actual multi-file patch parsing bug: adjacent
new-file diffs both use `/dev/null`, confusing the unidiff parser. File-aware parsing fixed it.
Both earlier runs also repeated budget selection. Tail guidance now explicitly tells the model
that a profile is already selected, without changing the tool schema.

The final run made exactly these calls:

1. `set_task_budget`
2. `read_file`, `read_file`, `list_files`
3. `apply_patch` (module, extra tests and README in one action)
4. `run_validation`
5. `finish`

Final verification: all 14 project tests passed inside the harness and again independently;
45 additional conversion-matrix cases passed; `python -m tempconvert 100 C F` printed
`212.00 F`. Git comparison confirmed that the original acceptance tests and `harness.toml`
were unchanged. The harness itself passed 711 offline tests, Ruff and mypy.

Cache ratios vary significantly across these sequential runs. This is evidence of working
cache accounting and successful project execution, not a controlled claim that caching
improved. No monetary cost is inferred from the harness's default `provider_cost=0`.
Textual interactions and Docker Supervisor workers are outside this test's scope.

## Artifacts

- [summary.json](summary.json): comparison and scope.
- [before.json](before.json), [patch-fixed.json](patch-fixed.json), [final.json](final.json):
  per-call usage/actions and run/validation evidence.
- [tempconvert-project.zip](tempconvert-project.zip): generated final project, excluding Git,
  state databases, credentials and caches. Extract it and run
  `python -m unittest discover -s tests -v` to verify the delivered application.
- [runner.py.txt](runner.py.txt): the exact project setup/execution script used. From the harness
  repository, `uv run python docs/evidence/2026-09-22-project-e2e/runner.py.txt` creates a fresh
  temporary repository and performs a new real-provider test with the current active profile.
  The script writes `/tmp/613-project-e2e-result.json`; inspect its `summary.status` and
  `independent_validation.exit_code` to assess the run. User provider configuration is copied to
  a temporary non-secret profile with the test limits; the original configuration is unchanged.
