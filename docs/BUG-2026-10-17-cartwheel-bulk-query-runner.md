# Cartwheel bulk query runner

## What I saw

There is no reproducible way to send a saved, role-tagged set of Cartwheel queries through the authenticated chat API in paced batches and classify each result. The existing scenario runner accepts a JSONL file and processes scenarios sequentially; it has no batch-size, pacing, or dry-run option. Its normal path invokes the agent, whose tools can change local order state.

The requested workflow is recorded in Woobi as BUG-0336, “Cartwheel: 100-query persona-based chat API batch runner with failure-mode classification.” BUG-0336 is held, and this document does not create a second bug record. The repository tracking issue is [#71](https://github.com/ai-evals-course/cartwheel-homeworks/issues/71).

## Root cause

This is a missing capability, not a regression. `scenarios/runner.py` runs the supplied scenarios one at a time through `POST /sessions` and `POST /sessions/{session_id}/messages`. It does not provide the 100-case persona corpus, batch pacing, failure-mode classification, or a plan-only preview. The authenticated API already returns structured tool calls that can support deterministic checks (`server/app.py`).

## The design flaw, named

Scenario replay and broad agent testing are separate workflows today. Reusing the replay runner without isolation would also let refund and cancellation cases alter the shared demo database. The missing layer is a controlled batch harness that validates a run before sending requests, isolates side effects, and preserves per-case results for resume and review.

## Status

Implementation is in progress on `feat/cartwheel-bulk-runner`, based on the operator's local Cartwheel `main`. Woobi BUG-0336 remains `hold` until the implementation is reviewed and the gate is closed. The initial record commit was not pushable to the course-owned upstream with the available account; no fork or PR was created.

## Fix (as approved)

The operator approved CBR1-CBR6 on CARTWHEEL-G2. The implementation adds a 100-case role-tagged bank, plan-only preview, per-request five-second pacing, isolated per-case world/session/feedback stores, resumable JSONL results, deterministic checks plus human-review notes, provider-aware model selection, and an estimated USD cap. No code has been pushed or deployed.

## Validation

- `uv run python -m scenarios.runner --help` showed only `--base-url`, `--limit`, `--model`, `--output`, `--resume`, and `--ids`; there is no dry-run, batch, or interval option.
- Inspection of `scenarios/runner.py` confirmed sequential API execution. The existing authenticated message route and structured tool-call response are in `server/app.py`.
- The pre-existing local changes to these files only change the default server port from 8010 to 59001; they do not add the requested runner behavior.
- `scenarios.batch_runner.load_cases()` validates 100 unique cases: shopper 38, merchant 35, support 27; 72 have deterministic checks and 28 carry explicit human-review notes.
- Focused offline regression suite: 31 passed. Editor diagnostics: no errors in touched Python modules/tests. Full suite: 164 passed, 4 skipped, 18 xfailed, 9 xpassed; one Langfuse-backed Module 2 test timed out connecting to its configured host.
- Feature smoke app `127.0.0.1:59008/health` returned `db_exists: true` with a disposable database at `/tmp/cartwheel-ui-smoke`. Session creation returned a session ID; no chat message was sent by this smoke check.
- Langfuse Docker was healthy and `GET /api/public/traces?limit=50` returned 50 traces, including 20 Cartwheel session traces; the newest observed Cartwheel trace was `2026-10-17T07:06:54.858Z`. The latest inspected Anthropic trace contained two GENERATION observations with `usage.input=0`, `usage.output=0`, and empty `usageDetails`.
- The 59008 smoke process was launched with blank `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`, so it intentionally did not export Langfuse traces. The user-started GLM-5.2 batch run was at 36/100 and $0.2334746 at the last status check; its local JSONL had nonzero SDK token counts. It was not started or stopped by this validation.
- Trace delivery was then fixed in two steps, both at the user's explicit request to get traces into Langfuse. First, the smoke server's child environment is now built from the checkout's `.env` in Python (uvicorn `--env-file` did not override inherited empty values), and `server/app.py`'s lifespan flushes the Langfuse client on shutdown so the short-lived per-case worker servers export their spans before exiting. A one-case GLM-5.2 probe (run `507455a4`, $0.0049612) then produced a new `cartwheel.session_message` trace, but its two GENERATION observations still reported `usage.input=0`/`usage.output=0`.
- Root cause of the zero usage: OpenLLMetry's OpenAI Agents hook (`opentelemetry/instrumentation/openai_agents/_hooks.py`, `_extract_response_attributes`) reads token counts only from `span_data.response.usage`, which the SDK populates for the OpenAI Responses API. `agents/extensions/models/litellm_model.py` writes the same counts to `span_data.usage` and leaves `response` unset, so every LiteLLM-routed generation (Anthropic, Together) exported no `gen_ai.usage.*` attributes. `observability/instrument.py` now wraps the hook's `_end_generation_span` with `record_generation_usage_fallback`, which copies `span_data.usage` onto the span when `response` is absent. Two unit tests cover the fallback and its idempotence (`tests/test_observability.py`, 6 passed).
- Verification after restarting 59008 with the fix (pid 39005): run `ee07c360` (one GLM-5.2 case, $0.0048542) recorded local usage 2845 input / 198 output across 2 requests; the matching Langfuse trace's GENERATION observations show 1495+1350 = 2845 input and 142+56 = 198 output tokens. Langfuse `totalCost` stays 0 because no pricing model is defined there for `together_ai/zai-org/GLM-5.2`; that is Langfuse-side model configuration, not an exporter defect.

## Follow-ups

Finish implementation validation, record the final SHA, and publish only after remote-push authorization. The Langfuse usage fallback and lifespan flush were implemented outside the original CARTWHEEL-G2 cards on the user's direct instruction and must be called out in the hand-back and the gate's `/done` evidence. Do not restart the existing 59001 service or mutate its database as part of this record.