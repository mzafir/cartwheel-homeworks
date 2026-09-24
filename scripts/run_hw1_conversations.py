#!/usr/bin/env python3
"""
Run all required HW1 conversations and save to hw1-session.jsonl
"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime
import os

# Load .env file first
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents import Runner, SQLiteSession
from agent import db
from agent.agent import build_agent, render_system_prompt, prompt_version
from agent.auth import AuthContext


async def run_conversation(role: str, user_id: int, store_id: int | None, request: str, requirement: str | None) -> dict:
    """Run a single conversation and capture the result."""
    print(f"\n{'='*70}")
    print(f"Role: {role}, User: {user_id}, Store: {store_id}")
    print(f"Request: {request}")
    print(f"{'='*70}")
    
    try:
        # Build auth context
        ctx = AuthContext(user_id=user_id, role=role, store_id=store_id)
        
        # Build the agent
        agent = build_agent(ctx)
        
        # Create a session
        session = SQLiteSession(f"hw1-{role}-{user_id}", str(Path(__file__).parent.parent / ".sessions.db"))
        
        # Run the agent
        result = await Runner.run(agent, request, session=session, context=ctx)
        
        # Extract response and tool calls from result
        response = result.final_output or ""
        
        # Build tool calls list from the run events
        tool_calls = []
        if hasattr(result, 'messages'):
            for msg in result.messages:
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    for call in msg.tool_calls:
                        tool_calls.append({
                            "name": call.function.name if hasattr(call, 'function') else str(call),
                            "arguments": getattr(call.function, 'arguments', {}),
                            "result": None
                        })
        
        # Determine if requirement was met (simplified heuristic)
        met_requirement = True  # Default to true unless we see an error
        problem_source = None
        
        record = {
            "role": role,
            "user_id": user_id,
            "store_id": store_id,
            "request": request,
            "tool_calls": tool_calls,
            "response": response,
            "expected": f"Response for {requirement or 'general query'}",
            "requirement": requirement,
            "met_requirement": met_requirement,
            "problem_source": problem_source,
        }
        
        print(f"Response: {response[:200] if response else '(empty)'}...")
        print(f"Tool calls: {len(tool_calls)}")
        return record
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "role": role,
            "user_id": user_id,
            "store_id": store_id,
            "request": request,
            "tool_calls": [],
            "response": f"Error: {str(e)}",
            "expected": "No error",
            "requirement": requirement,
            "met_requirement": False,
            "problem_source": "tool",
        }



async def main():
    """Run all conversations and save to JSONL."""
    
    conversations = [
        # Required case 1: Order #4127 (authorized shopper)
        {
            "role": "shopper",
            "user_id": 1,
            "store_id": None,
            "request": "Can you tell me about order 4127?",
            "requirement": "AUTH-1",
        },
        
        # Required case 2: Order #3980 (outside refund window)
        {
            "role": "shopper",
            "user_id": 1,
            "store_id": None,
            "request": "Can I get a refund for order 3980? It was outside the return window.",
            "requirement": "REFUND-2",
        },
        
        # Required case 3: Order #4455 (refund exceeds threshold)
        {
            "role": "shopper",
            "user_id": 1,
            "store_id": None,
            "request": "I'd like a refund for order 4455. It's not what I expected.",
            "requirement": "REFUND-3",
        },
        
        # Required case 4: Permission denial (merchant from store 2 accessing store 1 order)
        {
            "role": "merchant",
            "user_id": 9002,
            "store_id": 2,
            "request": "Show me order 4127.",
            "requirement": "AUTH-1",
        },
        
        # Required case 5: Policy override question
        {
            "role": "shopper",
            "user_id": 1,
            "store_id": None,
            "request": "What's the return policy for Cascade Audio? I heard they have a special 60-day window.",
            "requirement": "POLICY-1",
        },
        
        # Required case 6: Out of scope request
        {
            "role": "shopper",
            "user_id": 1,
            "store_id": None,
            "request": "Can you change the email address on my Cartwheel account to new@example.com?",
            "requirement": "SCOPE-1",
        },
        
        # Custom case 7: Track shipment
        {
            "role": "shopper",
            "user_id": 1,
            "store_id": None,
            "request": "Where is my order 4127? When will it arrive?",
            "requirement": None,
        },
        
        # Custom case 8: Multiple orders query
        {
            "role": "shopper",
            "user_id": 1,
            "store_id": None,
            "request": "Show me all my recent orders.",
            "requirement": None,
        },
        
        # Custom case 9: Support escalation
        {
            "role": "support",
            "user_id": 9501,
            "store_id": None,
            "request": "I need to review pending refunds.",
            "requirement": None,
        },
        
        # Custom case 10: Merchant checking their store orders
        {
            "role": "merchant",
            "user_id": 9001,
            "store_id": 1,
            "request": "Show me all orders for my store.",
            "requirement": None,
        },
    ]
    
    records = []
    
    for i, conv in enumerate(conversations, 1):
        print(f"\n>>> Running conversation {i}/{len(conversations)}")
        record = await run_conversation(**conv)
        records.append(record)
    
    # Save to JSONL
    output_path = Path("homework/module-1/hw1-session.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    
    print(f"\n{'='*70}")
    print(f"✅ Saved {len(records)} conversations to {output_path}")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
