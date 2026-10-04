"""
agent_tools.py — Tool definitions for the autopay recovery voice agent.

These tools are called by Gemini Live API during a conversation with a customer.
"""

import json
import logging
from customers import (
    get_customer,
    mark_payment_collected,
    mark_payment_plan,
    mark_escalated,
    increment_attempts,
    update_customer_status,
)

logger = logging.getLogger(__name__)

# ── Tool schemas (passed to Gemini Live API config) ──────────────────────────

TOOL_DECLARATIONS = [
    {
        "name": "get_customer_details",
        "description": (
            "Retrieve the full account details for the current customer, "
            "including plan name, amount due, currency, failure reason, and due date. "
            "Call this at the start of every call to ground yourself."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "The unique customer ID (e.g. C001).",
                }
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "confirm_payment_collected",
        "description": (
            "Mark the account as recovered after the customer has agreed to pay "
            "or has confirmed payment details. Only call this when the customer "
            "explicitly agrees to complete payment."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "payment_method": {
                    "type": "string",
                    "description": (
                        "How the customer will pay: e.g. 'existing card on file', "
                        "'new card ending 4242', 'bank transfer'."
                    ),
                },
            },
            "required": ["customer_id", "payment_method"],
        },
    },
    {
        "name": "setup_payment_plan",
        "description": (
            "Arrange a payment plan when the customer cannot pay in full today. "
            "Offer 2- or 3-instalment plans only. Record the agreement."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "instalments": {
                    "type": "integer",
                    "description": "Number of instalments (2 or 3).",
                },
                "first_payment_date": {
                    "type": "string",
                    "description": "ISO-8601 date of the first instalment (YYYY-MM-DD).",
                },
            },
            "required": ["customer_id", "instalments", "first_payment_date"],
        },
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Escalate the account to a human agent when the customer is upset, "
            "requests to speak to a person, disputes the charge, or reports "
            "fraud / identity theft."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "reason": {
                    "type": "string",
                    "description": "Why the call is being escalated.",
                },
            },
            "required": ["customer_id", "reason"],
        },
    },
    {
        "name": "send_payment_link",
        "description": (
            "Send a secure payment link to the customer's email address on file "
            "so they can update their card or pay online without reading numbers "
            "aloud. Use when the customer doesn't have their card handy."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
            },
            "required": ["customer_id"],
        },
    },
]


# ── Tool execution ────────────────────────────────────────────────────────────

def execute_tool(name: str, args: dict) -> str:
    """Dispatch a tool call and return a JSON string result."""
    logger.info(f"[TOOL] {name}({args})")

    if name == "get_customer_details":
        customer = get_customer(args["customer_id"])
        if not customer:
            return json.dumps({"error": "Customer not found"})
        return json.dumps(customer)

    elif name == "confirm_payment_collected":
        cid = args["customer_id"]
        method = args.get("payment_method", "unspecified")
        success = mark_payment_collected(cid)
        if success:
            customer = get_customer(cid)
            amount = customer["amount_due"] if customer else "unknown"
            return json.dumps({
                "status": "recovered",
                "message": f"Payment of ${amount} marked as collected via {method}. "
                           f"Confirmation email will be sent.",
            })
        return json.dumps({"error": "Failed to update record"})

    elif name == "setup_payment_plan":
        cid = args["customer_id"]
        n = args.get("instalments", 2)
        date = args.get("first_payment_date", "TBD")
        customer = get_customer(cid)
        if not customer:
            return json.dumps({"error": "Customer not found"})
        amount_per = round(customer["amount_due"] / n, 2)
        details = (
            f"{n}-instalment plan: ${amount_per} each, "
            f"starting {date}."
        )
        mark_payment_plan(cid, details)
        return json.dumps({
            "status": "payment_plan",
            "plan": details,
            "message": "Payment plan recorded. Confirmation email will be sent.",
        })

    elif name == "escalate_to_human":
        cid = args["customer_id"]
        reason = args.get("reason", "customer requested")
        mark_escalated(cid, reason)
        return json.dumps({
            "status": "escalated",
            "message": f"Call flagged for human review. Reason: {reason}",
        })

    elif name == "send_payment_link":
        cid = args["customer_id"]
        customer = get_customer(cid)
        if not customer:
            return json.dumps({"error": "Customer not found"})
        update_customer_status(cid, "link_sent", "Secure payment link emailed")
        return json.dumps({
            "status": "link_sent",
            "email": customer["email"],
            "message": (
                f"A secure payment link has been sent to {customer['email']}. "
                f"The link expires in 24 hours."
            ),
        })

    else:
        return json.dumps({"error": f"Unknown tool: {name}"})
