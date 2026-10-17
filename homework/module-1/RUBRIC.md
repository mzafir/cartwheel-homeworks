# HW1 Self-Grading Rubric (Parts B & C)

Use this rubric to evaluate your own HW1 Part B and C submissions.

## Part B: Conversation Recordings

**Submission:** `homework/module-1/hw1-session.jsonl` (one JSONL record per conversation)

### Requirement Checklist

#### Format
- [ ] File exists at `homework/module-1/hw1-session.jsonl`
- [ ] Each line is valid JSON
- [ ] Exactly 10 records (10 conversations)
- [ ] Each record has all required fields: `role`, `user_id`, `store_id`, `request`, `tool_calls`, `response`, `expected`, `requirement`, `met_requirement`, `problem_source`

#### 6 Required Cases (must include all)
- [ ] **Case 1 (AUTH-1):** Authorized shopper order lookup
  - Role: shopper, User: 1, Request about order 4127
  - Expected: Retrieve order, show status/dates/total, cite policy
  - Success: `met_requirement: true`

- [ ] **Case 2 (REFUND-2):** Out-of-window refund denial
  - Role: shopper, User: 1, Request refund for order 3980 (outside 30-day window)
  - Expected: Agent checks eligibility, explains outside window, refuses
  - Success: `met_requirement: true`

- [ ] **Case 3 (REFUND-3):** Above-threshold refund escalation
  - Role: shopper, User: 1, Request refund for order 4455 (total $150+, exceeds $100 threshold)
  - Expected: Agent escalates to human, explains threshold
  - Success: `met_requirement: true`

- [ ] **Case 4 (AUTH-1):** Merchant permission denial
  - Role: merchant, User: 9002 (store 2), Request order 4127 (store 1)
  - Expected: Agent refuses with `permission_denied`
  - Success: `met_requirement: true`

- [ ] **Case 5 (POLICY-1):** Policy override lookup
  - Role: shopper, User: 1, Question about Cascade Audio return policy (store override)
  - Expected: Agent finds and cites 60-day policy for that store
  - Success: `met_requirement: true`

- [ ] **Case 6 (SCOPE-2):** Out-of-scope refusal
  - Role: shopper, User: 1, Request payment credential change (credit card expiration)
  - Expected: Agent refuses (payment credentials out of scope)
  - Success: `met_requirement: true`

#### 4 Custom Cases (design your own)
- [ ] **Custom Case 1:** Your choice
  - Define: role, user_id, request, expected behavior, requirement
  - Met: `met_requirement` correct for your scenario

- [ ] **Custom Case 2:** Your choice
  - Define: role, user_id, request, expected behavior, requirement
  - Met: `met_requirement` correct for your scenario

- [ ] **Custom Case 3:** Your choice
  - Define: role, user_id, request, expected behavior, requirement
  - Met: `met_requirement` correct for your scenario

- [ ] **Custom Case 4:** Your choice
  - Define: role, user_id, request, expected behavior, requirement
  - Met: `met_requirement` correct for your scenario

### Scoring: Part B
- **Met all 6 required cases + submitted 4 custom cases:** ✅ PASS B
- **Met 5-6 required cases + submitted 2-4 custom cases:** ⚠️ PARTIAL (revise)
- **Met <5 required cases or <2 custom cases:** ❌ INCOMPLETE

**Part B Target:** 10 records with ≥9 meeting requirements

---

## Part C: System Prompt Revision Analysis

**Submission:** `homework/module-1/hw1-part-c.md` (analysis document)

### Content Checklist

#### 1. Problem Identification
- [ ] Identified at least one failing case from Part B (e.g., Case 3: above-threshold refund not escalating)
- [ ] Explained why it failed (model instruction issue, not tool or auth bug)
- [ ] Cited specific behavior mismatch (e.g., "agent proposed refund instead of escalating")

#### 2. Root Cause Analysis
- [ ] Diagnosed the system prompt gap (e.g., "SYSTEM_PROMPT_TEMPLATE doesn't explicitly state above-threshold refunds MUST escalate")
- [ ] Explained why the agent made the wrong decision (ambiguity in prompt, not code)
- [ ] Distinguished from tool/auth issues (those are code, not prompt)

#### 3. Proposed Revision
- [ ] Included revised text for SYSTEM_PROMPT_TEMPLATE
- [ ] Revision is **specific and minimal** (3-5 targeted sentence changes, not a rewrite)
- [ ] Revision removes ambiguity (adds clear directive, not vague guidance)
- [ ] Examples of good changes:
  - "MUST escalate" (mandatory language)
  - "Call get_order first to check refund_eligible" (explicit pre-check)
  - "Never support X" (clear refusal)

#### 4. Validation / Testing
- [ ] Tested revision on the failing case (before/after comparison)
- [ ] Documented observed difference:
  - Before: [describe incorrect behavior]
  - After: [describe improved behavior]
- [ ] Verified existing tests still pass (tool tests, auth tests)

#### 5. Documentation Quality
- [ ] Clear, concise analysis (1-2 pages max)
- [ ] Includes:
  - Summary statement (what failed, why)
  - Root cause (prompt gap, not tool/auth)
  - Proposed fix (revised prompt section)
  - Test results (before/after)
  - Recommendation (merge, revise, or reject)

### Scoring: Part C
- **Identified problem + analyzed root cause + proposed specific revision + tested + documented:** ✅ PASS C
- **Identified problem + analyzed root cause + proposed revision (not tested OR weak doc):** ⚠️ PARTIAL (add validation)
- **Identified problem but weak analysis OR no proposed revision OR not tested:** ❌ INCOMPLETE

**Part C Target:** Clear problem statement + specific revision + evidence it helps

---

## Quick Self-Check

**Part B:**
```bash
# Count records
wc -l homework/module-1/hw1-session.jsonl  # Should be 10
# Check schema
head -1 homework/module-1/hw1-session.jsonl | python3 -m json.tool | head -20  # Verify all fields
# Check met_requirement distribution
python3 -c "import json; f = open('homework/module-1/hw1-session.jsonl'); records = [json.loads(l) for l in f]; print(f'Met: {sum(1 for r in records if r[\"met_requirement\"])}/10')"
```

**Part C:**
```bash
# Verify file exists and has content
wc -l homework/module-1/hw1-part-c.md  # Should be >20 lines
# Check for key sections
grep -c "root cause\|proposed\|revision\|test" homework/module-1/hw1-part-c.md  # Should match all 4
```

---

## Common Issues & Fixes

**Part B Issues:**
| Problem | Fix |
|---------|-----|
| `met_requirement` always true | Review failure cases; check if tool actually returned error. Use `problem_source` to mark prompt issues. |
| Missing required cases | Add conversations for all 6 spec cases (4127, 3980, 4455, merchant/store2, policy override, out-of-scope). |
| Only 5-6 records | Custom cases are required. Design 4 additional conversations covering different scenarios. |
| Invalid JSON | Ensure each line is one JSON object, not split across lines. |

**Part C Issues:**
| Problem | Fix |
|---------|-----|
| No revision proposed | Identify what the prompt should say differently. Add explicit guidance where ambiguous. |
| Too vague (e.g., "be more helpful") | Replace with specific language: "call X before Y", "always Z", "never W". |
| Tested but not documented | Add before/after transcript excerpts showing the improvement. |
| Revised prompt breaks tests | Roll back and propose narrower change. Revision must be backward compatible. |

---

## Success Criteria Summary

| Part | Criteria | Status |
|------|----------|--------|
| **A** | 5 tools implemented, all tests pass | (Pre-req for B/C) |
| **B** | 10 conversations (6 required + 4 custom), ≥9 met requirements | ✅ or ⚠️ |
| **C** | Problem identified + root cause + specific revision + tested + documented | ✅ or ⚠️ |

**Overall:** Parts A + B + C complete with ≥90% requirement pass rate = **HW1 PASSING**
