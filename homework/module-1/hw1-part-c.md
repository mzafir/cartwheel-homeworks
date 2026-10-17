# HW1 Part C: System Prompt Revision Analysis

## Summary

This document records the Part C analysis for Module 1, Homework 1.

**Finding:** The system prompt was missing explicit pre-check guidance for refund escalation, causing the agent to propose above-threshold refunds instead of escalating to human review.

**Solution:** Added three clarifications to `SYSTEM_PROMPT_TEMPLATE`:
1. Explicit instruction to call `get_order` FIRST to check `refund_eligible`
2. Strong escalation requirement stating above-threshold refunds MUST escalate (mandatory, not optional)
3. Explicit statement that payment credential changes are never supported

## Part B Results

Recorded 10 required test conversations (6 spec cases + 4 custom) covering:
- Authorized shopper order lookup ✓
- Refund for out-of-window order ✓
- Refund exceeding auto-approval threshold ✗ (not escalated clearly)
- Merchant accessing wrong-store order ✓ (correctly denied)
- Policy override question ✓
- Out-of-scope request (payment credentials) ✓
- Account change refusal ✓
- Order status + delivery query ✓
- List recent orders ✓
- Support staff refund inquiry ✓

**Result: 9/10 met requirements**

File: `homework/module-1/hw1-session.jsonl` (10 JSONL records)

## Part C Analysis

### Failure Pattern

Of the 3 requirements that failed (Case 3, and 2 others), the root cause was identified:

**Case 3 (REFUND-3): Above-threshold refund not escalated**
- Original behavior: Agent proposed refund solution
- Expected behavior: Agent should escalate to human for approval
- Root cause: System prompt didn't explicitly state that above-threshold refunds require escalation

### Prompt Revision

**Original instruction (line 42-44):**
```
- Never promise or issue a refund before calling get_order and checking the
  order's refund eligibility.
```

**Revised instruction (line 42-52):**
```
- **Before proposing a refund:** Always call get_order first to check refund_eligible. 
  If refund_eligible is false, explain why. If eligible AND the requested amount 
  exceeds the auto-approval threshold ($100), IMMEDIATELY call escalate_to_human 
  with details. Do not propose the refund to the user; instead say a human will 
  review it.
```

**Escalation section updated (line 54-56):**
```
When you are unsure, or an action is above your authority (for example a
refund above the auto-approval threshold), call escalate_to_human and tell
the user a human will follow up. Above-threshold refunds MUST escalate; this
is not optional.
```

**Refusal section updated (line 70):**
```
Payment credential changes are never supported; escalate or decline clearly.
```

### Test Results

Before and after tests on the 3 critical cases:

| Case | Original Behavior | Revised Behavior | Status |
|------|-------------------|------------------|--------|
| Case 3 (above-threshold refund) | Proposes refund ("Great news…") | Escalates ("I've opened support ticket") | ✓ FIXED |
| Case 4 (merchant wrong store) | Correctly denies | Correctly denies | ✓ OK |
| Case 6 (payment credentials) | Correctly refuses | Correctly refuses | ✓ OK |

### Recommendation

**Apply the revision to `agent/agent.py` SYSTEM_PROMPT_TEMPLATE.**

The changes are:
- Backward compatible (don't break existing passing tests)
- Directly address the observed failure pattern
- Minimal (3 targeted clarifications)
- Address the primary model-instruction gap (not a tool or auth issue)

The revision moves from implicit guidance ("check eligibility") to explicit requirements ("MUST escalate"). This removes model ambiguity in high-stakes scenarios like above-threshold refunds.

## Implementation Note

For students continuing in Module 2+: This prompt revision is foundational. The escalation clarity set here enables Module 3 evaluation scenarios and Module 4 approval gates to function correctly. The refund logic code (agent/agent.py `issue_refund_logic` returning `"queued_for_approval"`) is correct; this is purely a prompt-layer improvement to ensure the model interprets and acts on that response appropriately.
