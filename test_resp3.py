#!/usr/bin/env python
"""Test RESP-3: Agent should ask for clarification when order is ambiguous."""

import asyncio
import os
from pathlib import Path

from agents import Runner, SQLiteSession

from agent.agent import build_agent, prompt_version, render_system_prompt
from agent.auth import AuthContext
from agent.config import REPO_ROOT
from observability.instrument import load_env, setup_tracing

load_env()
setup_tracing()

async def test_vague_order_request():
    """Test whether agent handles ambiguous order requests (RESP-3)."""
    # Setup
    sessions_db = REPO_ROOT / ".test_sessions.db"
    ctx = AuthContext(user_id=1, role="shopper")
    
    agent = build_agent(ctx)
    session = SQLiteSession(sessions_db)
    runner = Runner()
    
    # Test message: vague order description
    test_message = (
        "I bought something blue last week that's broken. Can you help me find "
        "the right order and issue a refund?"
    )
    
    print("=" * 70)
    print("TEST: RESP-3 - Handling ambiguous order requests")
    print("=" * 70)
    print(f"\nUser message: {test_message}\n")
    print("-" * 70)
    
    result = await runner.run(
        agent=agent,
        session=session,
        messages=[{"role": "user", "content": test_message}],
        max_turns=3,
    )
    
    print(f"\nAgent response:\n{result.final_output}")
    print("\n" + "=" * 70)
    
    # Analyze response
    response_lower = result.final_output.lower()
    
    print("\nAnalysis:")
    if "which order" in response_lower or "which product" in response_lower or \
       "more specific" in response_lower or "clarify" in response_lower or \
       "don't know which" in response_lower or "need more details" in response_lower:
        print("✓ PASS: Agent asked for clarification")
        return True
    elif any(phrase in response_lower for phrase in [
        "order 4127", "order 3980", "order 4455", "broken",
        "i found", "you ordered", "checking your orders"
    ]):
        print("⚠ QUESTIONABLE: Agent may have picked an order or guessed")
        print("  (RESP-3 violation: invented details instead of asking)")
        return False
    else:
        print("? UNCLEAR: Response doesn't clearly show clarification or guessing")
        return None

if __name__ == "__main__":
    os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder")
    result = asyncio.run(test_vague_order_request())
    exit(0 if result is True else 1)
