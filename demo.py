"""
demo.py — End-to-end demonstration WITHOUT a real phone call.

This script simulates a conversation with Aria using TEXT input/output
so you can demo the agent locally without Twilio credentials.

The simulation:
  1. Selects a customer (default: C001, James Harrington)
  2. Opens a Gemini Live session (TEXT mode for demo)
  3. You type customer responses; Aria responds as text + prints transcripts
  4. Type 'quit' to end the session and print the call summary

Usage:
  python demo.py                  # demo customer C001
  python demo.py C004             # demo a different customer
  python demo.py --all            # run a scripted auto-demo for all 10 customers
"""

import asyncio
import json
import os
import sys
import argparse
import logging
from dotenv import load_dotenv
from google import genai
from google.genai import types

from agent_tools import TOOL_DECLARATIONS, execute_tool
from customers import get_customer, get_all_customers, increment_attempts, get_customer
from system_prompt import SYSTEM_PROMPT

load_dotenv()

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("demo")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.8-live"

# ── Scripted customer responses for auto-demo mode ────────────────────────────

AUTO_SCRIPTS: dict[str, list[str]] = {
    "C001": [  # James — pays now
        "Yes, this is James.",
        "Oh, I didn't realize my payment failed. How much is it?",
        "Sure, you can use the card I have on file.",
        "Great, thank you!",
    ],
    "C002": [  # Maria — card expired, wants to pay but no card handy
        "Hi, yes this is Maria.",
        "My card expired? Oh I see. I don't have my new card with me right now.",
        "Yes, please send me the link. I'll update it tonight.",
        "Thanks, have a good day!",
    ],
    "C003": [  # David — requests payment plan
        "Yeah, this is David.",
        "I've been having some cash flow issues. Can I pay in installments?",
        "Two payments sounds good. Can we start in two weeks?",
        "Perfect, thank you.",
    ],
    "C004": [  # Amelia — upset, wants human
        "Yes?",
        "I'm really frustrated. This is the third time you've called me!",
        "I want to speak to a real person, not a bot.",
    ],
    "C005": [  # Robert — disputes, fraud concern
        "Hello?",
        "What? I didn't sign up for any Enterprise plan. This is fraud!",
        "I need to speak to someone immediately.",
    ],
    "C006": [  # Priya — account closed, pays now with new details
        "This is Priya.",
        "Yes, I closed that bank account. Let me give you my new card.",
        "It's a Visa ending in 7890.",
        "Yes please confirm the payment.",
    ],
    "C007": [  # Ethan — short on cash, payment plan
        "Hey, yeah it's Ethan.",
        "Yeah I know. I'm a bit short this month.",
        "Can we do 3 payments instead of 2?",
        "Okay, first one next Friday. Works for me.",
    ],
    "C008": [  # Sofia — wants email link
        "Sofia speaking.",
        "I just got a new card but I don't have it memorized yet.",
        "Can you email me a link?",
        "Thanks a lot!",
    ],
    "C009": [  # Liam — stolen card, needs to escalate
        "This is Liam.",
        "Stolen card? Oh no, that card was stolen last week.",
        "Yes, I'd like to speak to someone about this.",
    ],
    "C010": [  # Aisha — hardship, negotiates
        "Hi, this is Aisha.",
        "I really can't afford it right now. It's been a tough month.",
        "Can we split it into two payments, maybe 2 weeks apart?",
        "Alright, that works. Thank you for being understanding.",
    ],
}


async def run_demo_session(customer_id: str, auto_responses: list[str] | None = None):
    """Run an interactive (or scripted) demo session for one customer."""
    customer = get_customer(customer_id)
    if not customer:
        print(f"[ERROR] Customer {customer_id} not found")
        return

    increment_attempts(customer_id)
    print("\n" + "=" * 60)
    print(f"  DEMO SESSION — {customer['name']} ({customer_id})")
    print(f"  Plan: {customer['plan']}  |  Amount: ${customer['amount_due']}")
    print(f"  Failure: {customer['failure_reason']}")
    print("=" * 60)
    print("  Type customer responses and press Enter.")
    print("  Type 'quit' to end the call.")
    print("=" * 60 + "\n")

    transcript_in: list[str] = []
    transcript_out: list[str] = []

    gemini_client = genai.Client(api_key=GEMINI_API_KEY)

    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.TEXT],  # TEXT mode for demo
        system_instruction=types.Content(
            parts=[types.Part(text=SYSTEM_PROMPT)]
        ),
        tools=[
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(**decl)
                    for decl in TOOL_DECLARATIONS
                ]
            )
        ],
    )

    auto_idx = 0

    async with gemini_client.aio.live.connect(model=GEMINI_MODEL, config=config) as session:
        # Inject opening instruction
        await session.send_client_content(
            turns=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            text=(
                                f"[SYSTEM NOTE - NOT FROM CUSTOMER] "
                                f"You are connected to {customer['name']} (ID: {customer_id}). "
                                f"Begin the call now."
                            )
                        )
                    ],
                )
            ],
            turn_complete=True,
        )

        async def collect_response() -> bool:
            """Collect one full Aria response, return False if we should stop."""
            response_parts: list[str] = []
            tool_pending = False

            async for response in session.receive():
                sc = response.server_content
                if sc:
                    if sc.model_turn:
                        for part in sc.model_turn.parts:
                            if part.text:
                                response_parts.append(part.text)
                    if sc.turn_complete:
                        break

                tc = response.tool_call
                if tc:
                    tool_pending = True
                    results = []
                    for fc in tc.function_calls:
                        result_str = execute_tool(fc.name, dict(fc.args))
                        result_data = json.loads(result_str)
                        results.append(
                            types.FunctionResponse(
                                id=fc.id,
                                name=fc.name,
                                response={"result": result_str},
                            )
                        )
                        # Print tool call info
                        print(f"\n  🔧 [{fc.name}] → {json.dumps(result_data, indent=2)}\n")
                    await session.send_tool_response(function_responses=results)

            full_response = "".join(response_parts).strip()
            if full_response:
                print(f"\n  🤖 Aria: {full_response}\n")
                transcript_out.append(full_response)

            return True

        # Start with Aria's opening
        await collect_response()

        # Conversation loop
        while True:
            if auto_responses and auto_idx < len(auto_responses):
                user_input = auto_responses[auto_idx]
                auto_idx += 1
                print(f"  👤 {customer['name']}: {user_input}")
                await asyncio.sleep(0.5)  # slight pause for readability
            else:
                if auto_responses:
                    # Auto-script exhausted — end call
                    user_input = "quit"
                else:
                    try:
                        user_input = input(f"  👤 {customer['name']}: ").strip()
                    except (EOFError, KeyboardInterrupt):
                        user_input = "quit"

            if user_input.lower() in ("quit", "exit", "bye", ""):
                print("\n  [Call ended by demo script]\n")
                break

            transcript_in.append(user_input)

            await session.send_realtime_input(text=user_input)
            keep_going = await collect_response()
            if not keep_going:
                break

    # Summary
    fresh = get_customer(customer_id)
    print("─" * 60)
    print(f"  OUTCOME: {fresh['status'].upper() if fresh else 'UNKNOWN'}")
    if fresh and fresh.get("notes"):
        print(f"  NOTES  : {fresh['notes']}")
    print("─" * 60 + "\n")
    return fresh["status"] if fresh else "unknown"


async def main():
    parser = argparse.ArgumentParser(description="Autopay Recovery Voice Agent Demo")
    parser.add_argument("customer_id", nargs="?", default="C001",
                        help="Customer ID to demo (default: C001)")
    parser.add_argument("--all", action="store_true",
                        help="Run scripted auto-demo for all 10 customers")
    args = parser.parse_args()

    if not GEMINI_API_KEY:
        print("[ERROR] GEMINI_API_KEY is not set. Add it to .env or export it.")
        sys.exit(1)

    if args.all:
        print("\n🚀 Running scripted auto-demo for all 10 customers...\n")
        results: dict[str, str] = {}
        for cid, script in AUTO_SCRIPTS.items():
            outcome = await run_demo_session(cid, auto_responses=script)
            results[cid] = outcome
            await asyncio.sleep(2)

        print("\n" + "=" * 60)
        print("  BATCH CAMPAIGN RESULTS")
        print("=" * 60)
        for cid, outcome in results.items():
            c = get_customer(cid)
            name = c["name"] if c else cid
            icon = {"recovered": "✅", "payment_plan": "📅", "escalated": "👤",
                    "link_sent": "📧", "failed": "❌"}.get(outcome, "❓")
            print(f"  {icon} {cid} {name:<20} → {outcome}")
        print("=" * 60 + "\n")
    else:
        await run_demo_session(args.customer_id)


if __name__ == "__main__":
    asyncio.run(main())
