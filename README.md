# Autopay Recovery Voice Agent

A complete voice agent that calls customers with failed autopay payments and attempts to recover them — built with **Gemini Live API** + **Twilio**.

## Architecture

```
Twilio Outbound Call
    └── Twilio Media Stream (WebSocket, µ-law 8kHz)
          └── FastAPI Server  (server.py)
                ├── µ-law ↔ PCM transcoding
                └── Gemini Live API (gemini-3.8-live)
                      ├── Voice: Aria (Aoede voice)
                      ├── System prompt: payment recovery specialist
                      └── Tools: get_customer_details, confirm_payment_collected,
                                 setup_payment_plan, escalate_to_human, send_payment_link
```

## Files

| File | Purpose |
|---|---|
| `customers.py` | 10 fictional customer records + state management |
| `agent_tools.py` | 5 Gemini function-calling tool schemas + executors |
| `system_prompt.py` | Aria's persona, call flow, and rules |
| `server.py` | FastAPI server: Twilio ↔ Gemini Live bridge |
| `demo.py` | Local demo without a real phone (text mode) |
| `requirements.txt` | Python dependencies |
| `.env.example` | Environment variable template |

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set environment variables
```bash
cp .env.example .env
# Edit .env — add your GEMINI_API_KEY at minimum
```

### 3. Run the text-only demo (no phone needed)

**Interactive session with one customer:**
```bash
python demo.py C001          # James Harrington — insufficient funds
python demo.py C004          # Amelia Thompson — 3rd attempt, upset
python demo.py C009          # Liam O'Brien — stolen card
```

**Scripted auto-demo for ALL 10 customers:**
```bash
python demo.py --all
```
This runs pre-written customer responses and prints a batch campaign results table.

### 4. Run live phone calls (requires Twilio)

**Start the server:**
```bash
# Expose publicly with ngrok first:
ngrok http 8000
# Copy the https URL into .env as BASE_URL

uvicorn server:app --host 0.0.0.0 --port 8000
```

**Trigger a single outbound call:**
```bash
curl -X POST http://localhost:8000/call/C001
```

**Trigger calls to all 10 customers:**
```bash
curl -X POST http://localhost:8000/call-all
```

**Monitor customer status:**
```bash
curl http://localhost:8000/customers
```

## The 10 Customer Records

| ID | Name | Plan | Amount | Failure Reason |
|---|---|---|---|---|
| C001 | James Harrington | Premium Annual | $299.99 | Insufficient funds |
| C002 | Maria Santos | Business Monthly | $89.99 | Card expired |
| C003 | David Chen | Starter Monthly | $29.99 | Bank declined |
| C004 | Amelia Thompson | Pro Monthly | $59.99 | Insufficient funds (3rd attempt) |
| C005 | Robert Williams | Enterprise Annual | $1,199.00 | Card expired |
| C006 | Priya Patel | Starter Monthly | $29.99 | Account closed |
| C007 | Ethan Moore | Pro Monthly | $59.99 | Insufficient funds |
| C008 | Sofia Rodriguez | Business Monthly | $89.99 | Card expired |
| C009 | Liam O'Brien | Premium Annual | $299.99 | Stolen card flagged |
| C010 | Aisha Johnson | Starter Monthly | $29.99 | Insufficient funds (3rd attempt) |

## Agent Capabilities

**Aria** (the recovery agent) can:
- Greet the customer by name and explain the failed payment
- Accept payment on the card on file
- Set up a 2- or 3-instalment payment plan
- Email a secure payment link for customers without their card
- Escalate to a human agent (fraud, disputes, upset customers)

**Outcomes tracked:**
- `recovered` — payment collected
- `payment_plan` — instalment arrangement made
- `link_sent` — secure payment link emailed
- `escalated` — transferred to human
- `failed` — unresolved

## Twilio Configuration Notes

1. Create a Twilio account at twilio.com
2. Buy a phone number with Voice capability
3. The server handles TwiML dynamically — no static XML needed
4. Use a verified caller ID or Twilio number as `TWILIO_FROM_NUMBER`
5. Only call numbers you own or have explicit permission to call
