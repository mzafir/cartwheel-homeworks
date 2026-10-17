# Cartwheel bulk query runner

**Status:** approved by CARTWHEEL-G2 CBR1-CBR6; implementation is in progress on `feat/cartwheel-bulk-runner`. A live run is started only by an explicit Run action in the loopback UI and remains bounded by its configured USD ceiling.

## Intent

Build a chat-facing way to store a representative set of Cartwheel test queries and submit them through the authenticated API in batches of ten, spaced five seconds apart, with coverage across Cartwheel roles and capabilities. The operator also asked whether scenarios could be dry-run; the current runner has no dry-run mode, so this spec puts a plan-only preview to a gate decision.

## What exists today

`scenarios/runner.py` loads validated JSONL scenarios, creates a session through `POST /sessions`, and sends each turn through `POST /sessions/{session_id}/messages`. It runs sequentially and writes JSONL results with `--resume` support, but it has no batch scheduler, batch pacing, persona query bank, failure-mode classification, or dry-run option. `server/app.py` returns the reply and structured `tool_calls` from the authenticated message route.

The supported roles and tool behavior are defined in `SPEC.md`. Some tools mutate orders: refunds, cancellations, and human escalations. Database selection is controlled by `CARTWHEEL_DB` in `agent/config.py`; `tests/conftest.py` already creates temporary worlds and gives mutating tests a separate database copy.

The current runner help output has no dry-run flag. The operator checkout also has uncommitted port changes from 8010 to 59001 in `server/app.py`, `scenarios/runner.py`, and `ui/index.html`; those changes are not part of this record branch and must not be overwritten during later implementation.

## Proposed shape

The recommendation is a batch-testing view in the existing Cartwheel UI backed by a deterministic runner that reuses the authenticated session and message endpoints. The query bank should be versioned JSONL, with one stable case ID, role/user identity, utterance, feature/failure-mode tags, and expected checks per case. Results should be appendable and resumable, retaining the prompt, role, model, timestamps, reply, structured tool calls, status, errors, and check outcomes.

The current implementation uses `scenarios/bulk_queries.jsonl`, `/ui/batch.html`, and `/api/batch-tests/*` plus `/api/batch-runs/*`. It shows the four course models (GPT-4o mini, Claude Haiku 4.5, Claude Opus 4.6, GLM-5.2), disables choices whose provider key is absent, and accepts only one USD ceiling. The model-rate card is dated 2026-10-17; per-case cost is calculated from SDK input/output token usage. The UI explains the estimate is approximate because provider billing can vary.

The target is 100 curated cases, not a claim to enumerate every possible failure. Coverage should span shopper, merchant, and support permissions; order lookup; product and policy questions; refunds and the $100 approval boundary; cancellation; escalation; and the relevant injection, exfiltration, and prompt-leak probes. Cases stay user inputs to the application and must not be copied into the agent system prompt.

Execution uses a fresh disposable database, session store, and feedback store per case. A plan-only preview validates the selected cases and schedule without opening a session, calling the model, or writing results that look like completed runs. The worker stops at case boundaries on cancellation or when the spend cap is reached; it stops immediately after any case where model usage cannot be confirmed.

## Decisions for the gate

**CBR1 — Query corpus.** Approve a fixed, reviewed 100-case bank with stable IDs and explicit expected checks across the three roles and the failure-mode categories above. Alternative: start with a smaller bank assembled only from existing evaluation fixtures, then expand after review.

**CBR2 — User interface.** Approve a batch-testing view in the existing Cartwheel UI, with case selection, role/model controls, preview, start/stop, and run status. Alternative: ship a CLI runner first and defer the UI. Both choices use the existing authenticated API rather than adding an unauthenticated message route.

**CBR3 — Cadence.** Confirm what “five-second intervals” means: wait five seconds between every request, or wait five seconds between ten-request batches. These yield materially different run times for 100 cases: 99 waits (about 8 minutes 15 seconds) versus nine waits (45 seconds). Recommendation: five seconds between requests, with no extra batch pause, unless the operator intended the shorter schedule.

**CBR4 — Mutation isolation.** Approve a disposable database for each run, copied from a known seed, with before/after state checks for mutating cases. Alternative: isolate every case in its own database/process for stronger independence at higher startup cost. The production/demo database is never a target.

**CBR5 — Results and classification.** Approve JSONL run records with deterministic code checks for exact facts and explicit `inconclusive` when a result needs an unvalidated subjective judge. Resume must skip only completed case IDs whose inputs and model match the run manifest. Alternative: persist runs in SQLite for indexed review, which adds a schema and migration surface.

**CBR6 — Dry-run and spend controls.** Decide whether the UI/CLI must provide a plan-only preview and require an explicit model plus a per-run spend ceiling before execution. Recommendation: include preview, require the model and ceiling, and default to preview until the operator starts the run. A preview must make zero HTTP calls to the Cartwheel API and must not imply that any case passed.

## Non-goals

This is not exhaustive testing of every natural-language input, a replacement for HW4 human error analysis, a new production API, or permission to run a live model campaign now. It does not weaken Cartwheel authorization, refund thresholds, human approval, or kill-switch behavior. It does not use the adversarial campaign's in-process execution path as a substitute for the requested chat API path.

## Verification after approval

1. Validate the query bank offline: exactly 100 unique IDs, supported role/user pairs, required tags, schema validity, and at least one case for each approved coverage boundary.
2. If CBR6 is approved, test the plan-only preview with a mocked transport and assert zero HTTP requests, zero model construction, and zero output records marked completed.
3. Test batching and pacing with a fake clock/transport; assert the selected ten-case grouping and the approved wait placement without sleeping in the test suite.
4. Test resume against completed, failed, changed-input, and changed-model records; only matching completed cases may be skipped.
5. Run API contract tests against a mock server for session creation, bearer-token message calls, error responses, and structured tool-call capture.
6. Run mutating integration cases only against a copied disposable database; compare state before and after against each case's expected checks. Confirm the configured demo database is unchanged.
7. A live-model campaign is a separate action after gate approval, with the approved model and spend ceiling. Report live-model and offline checks separately.

## Hooks

The existing scenario validation and runner are in `scenarios/validate.py` and `scenarios/runner.py`; authenticated API contracts are in `server/app.py`; role and side-effect rules are in `SPEC.md`, `agent/auth.py`, and `agent/tools.py`; database isolation uses `agent/config.py` and the `world_copy` pattern in `tests/conftest.py`. No implementation files are changed by this proposal.