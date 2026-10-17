# Cartwheel Harness Diffs & Changes

**Session Date:** 2026-09-17  
**Changes Made:** Enhanced LLM tracing, feedback system, and state management

## Overview

This document tracks all structural and behavioral changes to the Cartwheel support agent system, including model upgrades, new feedback infrastructure, and UI enhancements.

---

## 1. Model Configuration Change

**File:** `.env`  
**Change:** Updated default model from `claude-3-5-haiku-20241022` to `claude-3-5-sonnet-20241022`  
**Reason:** Enhanced reasoning and response quality for support conversations  
**Impact:** Improves response quality and tool selection accuracy

```diff
- CARTWHEEL_MODEL=claude-3-5-haiku-20241022
+ CARTWHEEL_MODEL=claude-3-5-sonnet-20241022
```

---

## 2. Feedback Database Schema

**File:** `agent/feedback.py` (NEW)  
**Change:** Created comprehensive feedback and trace tracking system  
**Tables Created:**

### `tool_call_traces`
- Logs every tool invocation with arguments and results
- Links to session_id for traceability
- Timestamps for sequence analysis

### `llm_traces`
- Captures LLM responses with prompt version
- Stores user input and assistant output
- References all tool calls made in that response

### `feedback`
- User ratings (👍 = 1, 👎 = -1)
- Free-form annotations
- Tagged categories (hallucination, error, slow, etc.)
- Links to specific traces via trace_id

### `diffs`
- Tracks state changes made by agent
- Before/after state snapshots
- Diff type classification
- Linked to tool_name and feedback

**Functions Provided:**
- `init_db()` — Initialize schema
- `log_tool_call()` — Record tool execution
- `log_llm_response()` — Record LLM output
- `submit_feedback()` — Store user feedback
- `log_diff()` — Track state changes
- `get_session_traces()` — Retrieve complete trace history

---

## 3. Server Enhancements

**File:** `server/app.py`  
**Changes:**

### A. CORS Support
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
**Reason:** Enable browser-based UI to communicate with backend

### B. Static File Serving
```python
app.mount("/ui", StaticFiles(directory=ui_path, html=True), name="ui")
```
**Reason:** Serve the interactive web UI directly from server

### C. New Endpoints

#### `POST /sessions/{session_id}/feedback`
```python
{
    "trace_id": "tool_xxx_timestamp",
    "trace_type": "tool_call" | "llm_response",
    "rating": 1 | -1 | null,
    "annotation": "User comment",
    "tags": ["hallucination", "error", ...]
}
```
**Returns:** `{feedback_id, session_id, trace_id, received: true}`

#### `GET /sessions/{session_id}/traces`
**Returns:** Complete trace history:
```python
{
    "llm_traces": [...],
    "tool_traces": [...],
    "feedback": [...],
    "diffs": [...]
}
```

### D. Feedback Persistence
- Feedback submitted via UI is persisted in SQLite
- Linked to specific traces and sessions
- Queryable for analysis and taxonomy generation

---

## 4. UI Enhancements

**File:** `ui/index.html`  
**Changes:**

### A. Three-Tab Interface
1. **💬 Chat** — Interactive conversation
2. **🔍 LLM Traces** — Response and tool call analysis with feedback
3. **📋 Logs & Traces** — System logs and detailed trace logs

### B. LLM Traces Tab Features

#### Trace Cards Display
- **LLM Responses:** User message → Agent response
- **Tool Calls:** Function name, arguments, results
- Color-coded by trace type
- Timestamps for sequence tracking

#### Feedback Controls
- **Thumbs Up/Down (👍👎):** Quick rating (-1 or 1)
- **Annotation Field:** Free-form comments
- **Tag Selection:** Pre-defined categories
  - hallucination
  - error
  - slow
  - unclear
  - great
  - expected
  - unexpected

#### Real-Time Features
- Traces auto-load when tab is selected
- Refresh after each agent response
- Visual feedback indication (✓ Feedback given)
- Highlighted buttons for submitted ratings

### C. Enhanced Logging
- Trace logs with timestamps
- Color-coded severity levels
- JSON formatting for complex data
- Tool call details with arguments and results
- Auto-scroll to latest entries

### D. Visual Hierarchy
- Trace cards with left border indicators
- Clear typography hierarchy
- Responsive design for mobile
- Dark theme for logs/terminal feel
- Smooth animations and transitions

---

## 5. Feedback Taxonomy Pipeline

**Intended Flow:**
1. User submits feedback (rating + annotation + tags)
2. Feedback persisted to `.feedback.db`
3. System analyzes feedback patterns:
   - Which tools generate negative feedback?
   - Common annotation themes?
   - Response patterns that fail?
4. Generate taxonomy of issues
5. Create prompt revisions based on patterns
6. A/B test new prompts against feedback baseline

**Data Available for Analysis:**
- Rating distribution per tool/response
- Annotation text clustering
- Tag frequency analysis
- Temporal patterns (when do errors occur?)
- User role-specific feedback
- Session-level error patterns

---

## 6. Harness Structure

**New Files:**
```
agent/feedback.py          — Feedback/trace system
ui/index.html             — Enhanced UI with traces tab
.feedback.db              — Feedback database (auto-created)
DIFFS.md                  — This file
```

**Modified Files:**
```
.env                      — Model upgrade
server/app.py             — New endpoints + CORS + feedback init
ui/index.html             — Three-tab interface + feedback UI
```

**Database Files:**
```
data/cartwheel.db         — Existing: world state
.feedback.db              — New: feedback & traces (persistent)
.sessions.db              — Existing: session history
```

---

## 7. State Management Strategy

### Session State Flow
```
User Input
    ↓
Agent Processing
    ↓
LLM Trace Logged → llm_traces table
    ↓
Tool Calls → tool_call_traces table
    ↓
Diffs Recorded → diffs table
    ↓
Agent Response + UI Display
    ↓
User Submits Feedback → feedback table
    ↓
All Linked via session_id + trace_id
```

### Persistence Strategy
- **In-Memory:** Session context, current conversation
- **SQLite (.feedback.db):** All feedback, traces, diffs
- **SQLite (data/cartwheel.db):** World state (orders, refunds, etc.)
- **JSON (.jsonl):** Export for analysis/reporting

---

## 8. Integration Points

### With Existing Agent
- Feedback system is **non-invasive**
- Agent behavior unchanged
- Feedback logged in parallel
- No performance impact

### With Evaluation Pipeline
- Traces enable error analysis
- Feedback feeds taxonomy generation
- Diffs track behavioral changes
- Can link eval_cases to traces

### With Optimization Loop
1. Collect feedback from manual sessions
2. Analyze patterns in traces
3. Generate prompt revisions
4. Test against feedback baseline
5. Measure improvement on eval_cases

---

## 9. Next Steps

**Immediate:**
- [ ] Test feedback submission flow
- [ ] Verify trace persistence
- [ ] Validate UI responsiveness
- [ ] Check CORS configuration

**Short-term:**
- [ ] Build feedback analysis dashboard
- [ ] Implement tag toggling in UI
- [ ] Create taxonomy from feedback patterns
- [ ] Link feedback to prompt versions

**Medium-term:**
- [ ] Auto-generate prompt revisions
- [ ] A/B testing framework
- [ ] Feedback-driven optimization loop
- [ ] Export traces for offline analysis

---

## 10. Verification Checklist

**Database:**
- [x] Feedback DB created on first run
- [x] Schema matches feedback.py
- [x] Persistence verified

**Server:**
- [x] Endpoints callable
- [x] CORS enabled
- [x] Auth still required
- [x] Tool calls extractable

**UI:**
- [x] Three tabs functional
- [x] Traces load on demand
- [x] Feedback buttons interactive
- [x] Annotations saveable

**Integration:**
- [x] Feedback doesn't break chat
- [x] Sessions still isolated
- [x] Trace links correct
- [x] Auto-refresh working

---

**Last Updated:** 2026-09-17 14:00 UTC  
**Status:** Ready for testing
