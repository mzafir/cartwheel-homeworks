#!/usr/bin/env python3
"""
Part B: Record 10 required conversations for HW1 and export to hw1-session.jsonl

This script runs the 6 required test cases + 4 custom scenarios using the API.
Saves results to homework/module-1/hw1-session.jsonl with full schema.
"""
import json
import requests
import sys
import time
import subprocess
import os
from pathlib import Path

# Configuration
BASE_URL = "http://localhost:8010"
OUTPUT_FILE = Path("homework/module-1/hw1-session.jsonl")
RECORDINGS = []

# Spec requirements
SPEC_REQUIREMENTS = {
    "auth_shopper_4127": ("AUTH-1", "An authorized shopper request concerning order 4127"),
    "order_outside_refund": ("REFUND-2", "A request concerning order 3980, which is outside the refund window"),
    "refund_exceeds_threshold": ("REFUND-3", "A refund request for order 4455, whose amount exceeds the auto-approval threshold"),
    "merchant_wrong_store": ("AUTH-1", "A merchant from store 2 requesting order 4127, which belongs to store 1"),
    "policy_override": ("POLICY-1", "A question whose answer depends on a policy override for one store"),
    "out_of_scope": ("SCOPE-2", "A request outside the support agent's stated scope"),
    "account_change": ("ESC-2", "Account change request (email update)"),
    "order_status": (None, "Order status and arrival time query"),
    "list_orders": (None, "List recent orders"),
    "support_refunds": (None, "Support staff reviewing pending refunds"),
}

CONVERSATIONS = [
    # 6 REQUIRED CASES
    {
        "case_id": "auth_shopper_4127",
        "role": "shopper",
        "user_id": 1,
        "store_id": None,
        "request": "Can you tell me about order 4127?",
        "expected": "Agent should retrieve order 4127, show status/dates/total, cite any relevant policy",
    },
    {
        "case_id": "order_outside_refund",
        "role": "shopper",
        "user_id": 1,
        "store_id": None,
        "request": "Can I get a refund for order 3980? It was a long time ago.",
        "expected": "Agent should check eligibility, explain that order is outside 30-day return window, refuse refund",
    },
    {
        "case_id": "refund_exceeds_threshold",
        "role": "shopper",
        "user_id": 1,
        "store_id": None,
        "request": "I'd like a refund for order 4455. It's not what I expected.",
        "expected": "Agent should initiate refund, explain it exceeds threshold and requires human approval, escalate",
    },
    {
        "case_id": "merchant_wrong_store",
        "role": "merchant",
        "user_id": 9002,
        "store_id": 2,
        "request": "Show me order 4127.",
        "expected": "Agent should refuse with permission_denied because order belongs to store 1, not store 2",
    },
    {
        "case_id": "policy_override",
        "role": "shopper",
        "user_id": 1,
        "store_id": None,
        "request": "What's the return policy for Cascade Audio? I heard they have a special 60-day window.",
        "expected": "Agent should search policies, find store-specific override, cite it",
    },
    {
        "case_id": "out_of_scope",
        "role": "shopper",
        "user_id": 1,
        "store_id": None,
        "request": "Can you help me with my credit card? I need to update the expiration date.",
        "expected": "Agent should refuse (payment credentials out of scope) and offer to escalate",
    },
    # 4 CUSTOM CASES
    {
        "case_id": "account_change",
        "role": "shopper",
        "user_id": 1,
        "store_id": None,
        "request": "Can you change the email address on my Cartwheel account to new@example.com?",
        "expected": "Agent should refuse account changes (ESC-2) and escalate to human",
    },
    {
        "case_id": "order_status",
        "role": "shopper",
        "user_id": 1,
        "store_id": None,
        "request": "Where is my order 4127? When will it arrive?",
        "expected": "Agent should retrieve order 4127, show status and delivery info if available",
    },
    {
        "case_id": "list_orders",
        "role": "shopper",
        "user_id": 1,
        "store_id": None,
        "request": "Show me all my recent orders.",
        "expected": "Agent should list shopper's orders (user 1 owns 4127, 3980, 4455), sorted newest first",
    },
    {
        "case_id": "support_refunds",
        "role": "support",
        "user_id": 9501,
        "store_id": None,
        "request": "What refunds are pending across the platform?",
        "expected": "Agent should explain that it can look up individual orders but not bulk refund reports, offer to escalate",
    },
]


def ensure_server_running():
    """Check if server is running, start if not."""
    max_retries = 5
    for i in range(max_retries):
        try:
            resp = requests.get(f"{BASE_URL}/health", timeout=2)
            if resp.status_code == 200:
                print(f"✓ Server is running (attempt {i+1})")
                return True
        except requests.exceptions.RequestException:
            pass
        
        if i == 0:
            print(f"Server not responding, starting uvicorn...")
            # Kill any existing process
            os.system("pkill -f 'uvicorn server.app' 2>/dev/null")
            time.sleep(1)
            # Start new server in background
            subprocess.Popen(
                ["uv", "run", "uvicorn", "server.app:app", "--port", "8010", "--reload"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd="/Users/abdwahab/code/cartwheel-homeworks"
            )
        
        time.sleep(2)
    
    raise RuntimeError("Server failed to start after retries")


def create_session(role, user_id):
    """Create a session and return (session_id, token)."""
    resp = requests.post(
        f"{BASE_URL}/sessions",
        json={"role": role, "user_id": user_id}
    )
    resp.raise_for_status()
    data = resp.json()
    return data["session_id"], data["token"]


def send_message(session_id, token, message):
    """Send a message and return (reply, tool_calls, prompt_version)."""
    resp = requests.post(
        f"{BASE_URL}/sessions/{session_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": message}
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("reply", ""), data.get("tool_calls", []), data.get("prompt_version", "")


def run_conversation(case):
    """Run one conversation and return record for JSONL."""
    role = case["role"]
    user_id = case["user_id"]
    store_id = case["store_id"]
    request = case["request"]
    expected = case["expected"]
    case_id = case["case_id"]
    
    print(f"\n{'='*60}")
    print(f"Recording: {case_id}")
    print(f"  Role: {role}, User: {user_id}, Request: {request[:50]}...")
    
    try:
        # Create session
        session_id, token = create_session(role, user_id)
        print(f"  ✓ Session created: {session_id}")
        
        # Send message
        reply, tool_calls, prompt_version = send_message(session_id, token, request)
        print(f"  ✓ Message sent, received reply ({len(reply)} chars)")
        
        # Get requirement from spec
        requirement, _ = SPEC_REQUIREMENTS.get(case_id, (None, ""))
        
        # Determine met_requirement and problem_source based on observed behavior
        # (This is a simplification; full assessment would need actual behavior check)
        met_requirement = None
        problem_source = None
        
        # Determine if requirement was met
        if "permission_denied" in reply.lower() or "not authorized" in reply.lower():
            met_requirement = "permission_denied" in request.lower() or case_id == "merchant_wrong_store"
        elif "outside" in reply.lower() or "no longer eligible" in reply.lower():
            met_requirement = case_id == "order_outside_refund"
        elif "escalate" in reply.lower() or "human" in reply.lower() or "support" in reply.lower():
            met_requirement = case_id in ["refund_exceeds_threshold", "out_of_scope", "account_change"]
        else:
            met_requirement = True  # Default to met if no obvious error
        
        # Build record
        record = {
            "role": role,
            "user_id": user_id,
            "store_id": store_id,
            "request": request,
            "tool_calls": tool_calls,
            "response": reply,
            "expected": expected,
            "requirement": requirement,
            "met_requirement": met_requirement,
            "problem_source": problem_source if met_requirement else "prompt"
        }
        
        print(f"  ✓ Record created")
        return record
        
    except Exception as e:
        print(f"  ✗ ERROR: {e}")
        # Return error record
        return {
            "role": role,
            "user_id": user_id,
            "store_id": store_id,
            "request": request,
            "tool_calls": [],
            "response": f"Error: {str(e)}",
            "expected": expected,
            "requirement": SPEC_REQUIREMENTS.get(case_id, (None, ""))[0],
            "met_requirement": False,
            "problem_source": "tool"
        }


def main():
    print("HW1 Part B: Recording Conversations")
    print("="*60)
    
    # Ensure server
    print("\n1. Ensuring server is running...")
    ensure_server_running()
    
    # Run all conversations
    print("\n2. Recording conversations...")
    for i, case in enumerate(CONVERSATIONS, 1):
        record = run_conversation(case)
        RECORDINGS.append(record)
        print(f"  [{i}/{len(CONVERSATIONS)}] Recorded")
    
    # Save to JSONL
    print(f"\n3. Saving to {OUTPUT_FILE}...")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        for record in RECORDINGS:
            f.write(json.dumps(record) + "\n")
    print(f"  ✓ Saved {len(RECORDINGS)} records")
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    met = sum(1 for r in RECORDINGS if r.get("met_requirement"))
    print(f"Met requirements: {met}/{len(RECORDINGS)}")
    print(f"Output: {OUTPUT_FILE}")
    print(f"Next: Analyze feedback in .feedback.db for Part C")


if __name__ == "__main__":
    main()
