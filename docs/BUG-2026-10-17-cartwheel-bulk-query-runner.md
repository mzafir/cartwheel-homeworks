# Cartwheel bulk query runner

## What I saw

There is no reproducible way to send a saved, role-tagged set of Cartwheel queries through the authenticated chat API in paced batches and classify each result. The existing scenario runner accepts a JSONL file and processes scenarios sequentially; it has no batch-size, pacing, or dry-run option. Its normal path invokes the agent, whose tools can change local order state.

The requested workflow is recorded in Woobi as BUG-0336, “Cartwheel: 100-query persona-based chat API batch runner with failure-mode classification.” BUG-0336 is held, and this document does not create a second bug record. The repository tracking issue is [#71](https://github.com/ai-evals-course/cartwheel-homeworks/issues/71).

## Root cause

This is a missing capability, not a regression. `scenarios/runner.py` runs the supplied scenarios one at a time through `POST /sessions` and `POST /sessions/{session_id}/messages`. It does not provide the 100-case persona corpus, batch pacing, failure-mode classification, or a plan-only preview. The authenticated API already returns structured tool calls that can support deterministic checks (`server/app.py`).

## The design flaw, named

Scenario replay and broad agent testing are separate workflows today. Reusing the replay runner without isolation would also let refund and cancellation cases alter the shared demo database. The missing layer is a controlled batch harness that validates a run before sending requests, isolates side effects, and preserves per-case results for resume and review.

## Status

Not implemented. Woobi BUG-0336 remains `hold`. No live scenario requests were sent. Implementation must wait for the decision cards on CARTWHEEL-G2 to be approved.

## Fix (as approved)

No fix has been approved yet. The proposed design and open decisions are in `docs/SPEC-cartwheel-bulk-query-runner.md`; the gate will decide the corpus, execution cadence, isolation, classification, and whether to include an offline dry-run preview.

## Validation

- `uv run python -m scenarios.runner --help` showed only `--base-url`, `--limit`, `--model`, `--output`, `--resume`, and `--ids`; there is no dry-run, batch, or interval option.
- Inspection of `scenarios/runner.py` confirmed sequential API execution. The existing authenticated message route and structured tool-call response are in `server/app.py`.
- The pre-existing local changes to these files only change the default server port from 8010 to 59001; they do not add the requested runner behavior.

## Follow-ups

Approve or revise the CARTWHEEL-G2 decisions, and only then implement the approved scope on a feature branch. No model calls or mutations are part of this record stage.