"""
10 fictional customer records with failed autopay information.
Each record includes:
  - id, name, phone, email
  - plan, amount_due, currency
  - failure_reason, due_date
  - attempts (how many times we've tried to collect)
  - status: 'failed' | 'recovered' | 'payment_plan' | 'escalated'
"""

from typing import Optional
import copy

CUSTOMERS: dict[str, dict] = {
    "C001": {
        "id": "C001",
        "name": "James Harrington",
        "phone": "+15550101001",
        "email": "james.harrington@email.com",
        "plan": "Premium Annual",
        "amount_due": 299.99,
        "currency": "USD",
        "failure_reason": "Insufficient funds",
        "due_date": "2026-09-28",
        "attempts": 1,
        "status": "failed",
        "notes": "",
    },
    "C002": {
        "id": "C002",
        "name": "Maria Santos",
        "phone": "+15550101002",
        "email": "maria.santos@email.com",
        "plan": "Business Monthly",
        "amount_due": 89.99,
        "currency": "USD",
        "failure_reason": "Card expired",
        "due_date": "2026-09-30",
        "attempts": 2,
        "status": "failed",
        "notes": "",
    },
    "C003": {
        "id": "C003",
        "name": "David Chen",
        "phone": "+15550101003",
        "email": "david.chen@email.com",
        "plan": "Starter Monthly",
        "amount_due": 29.99,
        "currency": "USD",
        "failure_reason": "Bank declined — do not honor",
        "due_date": "2026-09-29",
        "attempts": 1,
        "status": "failed",
        "notes": "",
    },
    "C004": {
        "id": "C004",
        "name": "Amelia Thompson",
        "phone": "+15550101004",
        "email": "amelia.thompson@email.com",
        "plan": "Pro Monthly",
        "amount_due": 59.99,
        "currency": "USD",
        "failure_reason": "Insufficient funds",
        "due_date": "2026-09-27",
        "attempts": 3,
        "status": "failed",
        "notes": "",
    },
    "C005": {
        "id": "C005",
        "name": "Robert Williams",
        "phone": "+15550101005",
        "email": "robert.williams@email.com",
        "plan": "Enterprise Annual",
        "amount_due": 1199.00,
        "currency": "USD",
        "failure_reason": "Card expired",
        "due_date": "2026-09-25",
        "attempts": 1,
        "status": "failed",
        "notes": "",
    },
    "C006": {
        "id": "C006",
        "name": "Priya Patel",
        "phone": "+15550101006",
        "email": "priya.patel@email.com",
        "plan": "Starter Monthly",
        "amount_due": 29.99,
        "currency": "USD",
        "failure_reason": "Account closed",
        "due_date": "2026-09-30",
        "attempts": 2,
        "status": "failed",
        "notes": "",
    },
    "C007": {
        "id": "C007",
        "name": "Ethan Moore",
        "phone": "+15550101007",
        "email": "ethan.moore@email.com",
        "plan": "Pro Monthly",
        "amount_due": 59.99,
        "currency": "USD",
        "failure_reason": "Insufficient funds",
        "due_date": "2026-09-28",
        "attempts": 1,
        "status": "failed",
        "notes": "",
    },
    "C008": {
        "id": "C008",
        "name": "Sofia Rodriguez",
        "phone": "+15550101008",
        "email": "sofia.rodriguez@email.com",
        "plan": "Business Monthly",
        "amount_due": 89.99,
        "currency": "USD",
        "failure_reason": "Card expired",
        "due_date": "2026-09-26",
        "attempts": 2,
        "status": "failed",
        "notes": "",
    },
    "C009": {
        "id": "C009",
        "name": "Liam O'Brien",
        "phone": "+15550101009",
        "email": "liam.obrien@email.com",
        "plan": "Premium Annual",
        "amount_due": 299.99,
        "currency": "USD",
        "failure_reason": "Stolen card flagged",
        "due_date": "2026-09-24",
        "attempts": 1,
        "status": "failed",
        "notes": "",
    },
    "C010": {
        "id": "C010",
        "name": "Aisha Johnson",
        "phone": "+15550101010",
        "email": "aisha.johnson@email.com",
        "plan": "Starter Monthly",
        "amount_due": 29.99,
        "currency": "USD",
        "failure_reason": "Insufficient funds",
        "due_date": "2026-09-30",
        "attempts": 3,
        "status": "failed",
        "notes": "",
    },
}

# In-memory state (mutated during agent tool calls)
_state: dict[str, dict] = copy.deepcopy(CUSTOMERS)


def get_customer(customer_id: str) -> Optional[dict]:
    """Return customer record or None."""
    return _state.get(customer_id)


def get_all_customers() -> list[dict]:
    return list(_state.values())


def update_customer_status(customer_id: str, status: str, notes: str = "") -> bool:
    if customer_id not in _state:
        return False
    _state[customer_id]["status"] = status
    if notes:
        _state[customer_id]["notes"] = notes
    return True


def mark_payment_collected(customer_id: str) -> bool:
    return update_customer_status(customer_id, "recovered", "Payment collected via phone call")


def mark_payment_plan(customer_id: str, plan_details: str) -> bool:
    return update_customer_status(customer_id, "payment_plan", plan_details)


def mark_escalated(customer_id: str, reason: str) -> bool:
    return update_customer_status(customer_id, "escalated", reason)


def increment_attempts(customer_id: str) -> int:
    if customer_id not in _state:
        return 0
    _state[customer_id]["attempts"] += 1
    return _state[customer_id]["attempts"]
