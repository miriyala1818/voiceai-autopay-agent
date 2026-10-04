"""
server.py — FastAPI server that bridges Twilio Media Streams ↔ Gemini Live API.

Architecture:
  Twilio phone call
    └── Twilio Media Stream (WebSocket, mulaw 8kHz)
          └── THIS SERVER
                └── Gemini Live API (WebSocket, PCM 16-bit 16kHz)

Flow per call:
  1. Twilio dials a customer and connects audio to /media-stream/<customer_id>
  2. Server opens a Gemini Live session with Aria's system prompt + customer context
  3. Audio is transcoded mulaw→PCM going IN, and PCM→mulaw going OUT
  4. Gemini function calls are dispatched to agent_tools.execute_tool()
  5. Call summary is printed/logged when the call ends

Usage:
  uvicorn server:app --host 0.0.0.0 --port 8000

Environment variables (put in .env or export before running):
  GEMINI_API_KEY      — your Google Gemini API key
  TWILIO_ACCOUNT_SID  — Twilio Account SID
  TWILIO_AUTH_TOKEN   — Twilio Auth Token
  TWILIO_FROM_NUMBER  — your Twilio phone number (E.164)
  BASE_URL            — your public HTTPS/WSS URL (ngrok or server)
                        e.g. https://abcd1234.ngrok-free.app
"""

import asyncio
import audioop  # stdlib mulaw codec (Python 3.13 still ships it on Windows)
import base64
import json
import logging
import os
import sys

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response
from google import genai
from google.genai import types
from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream

from agent_tools import TOOL_DECLARATIONS, execute_tool
from customers import get_customer, get_all_customers, increment_attempts
from system_prompt import SYSTEM_PROMPT

# ── Setup ─────────────────────────────────────────────────────────────────────

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("voiceai")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")

GEMINI_MODEL = "gemini-3.8-live"

app = FastAPI(title="Autopay Recovery Voice Agent")

# Twilio client (used for outbound dialling)
twilio_client: TwilioClient | None = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Gemini async client
gemini_client = genai.Client(api_key=GEMINI_API_KEY)


# ── Audio helpers ──────────────────────────────────────────────────────────────

MULAW_RATE = 8000   # Twilio media stream sample rate
PCM_RATE = 16000    # Gemini Live API native rate


def mulaw_to_pcm16(data: bytes) -> bytes:
    """Convert 8-bit µ-law at 8 kHz → linear 16-bit PCM at 16 kHz."""
    # Step 1: µ-law → linear 16-bit (still at 8 kHz)
    pcm8 = audioop.ulaw2lin(data, 2)
    # Step 2: upsample 8 kHz → 16 kHz
    pcm16, _ = audioop.ratecv(pcm8, 2, 1, MULAW_RATE, PCM_RATE, None)
    return pcm16


def pcm16_to_mulaw(data: bytes) -> bytes:
    """Convert linear 16-bit PCM at 24 kHz → 8-bit µ-law at 8 kHz."""
    # Gemini outputs 24 kHz; downsample to 8 kHz for Twilio
    downsampled, _ = audioop.ratecv(data, 2, 1, 24000, MULAW_RATE, None)
    return audioop.lin2ulaw(downsampled, 2)


# ── TwiML webhook ─────────────────────────────────────────────────────────────

@app.post("/twiml/{customer_id}")
async def twiml_webhook(customer_id: str, request: Request):
    """
    TwiML that Twilio fetches when the call connects.
    Returns a <Stream> verb pointing back to our WebSocket endpoint.
    """
    wss_url = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
    stream_url = f"{wss_url}/media-stream/{customer_id}"

    vr = VoiceResponse()
    connect = Connect()
    stream = Stream(url=stream_url)
    connect.append(stream)
    vr.append(connect)

    # Also add a short pause fallback in case WebSocket fails
    vr.pause(length=60)
    logger.info(f"[TwiML] Generated for customer {customer_id}, stream → {stream_url}")
    return Response(content=str(vr), media_type="application/xml")


# ── Gemini Live session manager ────────────────────────────────────────────────

class GeminiSession:
    """Wraps a single Gemini Live API session for one phone call."""

    def __init__(self, customer_id: str):
        self.customer_id = customer_id
        self.customer = get_customer(customer_id)
        self._session = None
        self._send_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._transcript_in: list[str] = []
        self._transcript_out: list[str] = []

    def _build_config(self) -> types.LiveConnectConfig:
        # Inject customer name into the opening turn
        name = self.customer["name"] if self.customer else "the customer"
        opening = (
            f"You are now connected to {name} (customer ID {self.customer_id}). "
            f"Start the call immediately by greeting them."
        )
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
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
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Aoede"  # warm, clear voice
                    )
                )
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

    async def connect(self):
        self._session = await gemini_client.aio.live.connect(
            model=GEMINI_MODEL,
            config=self._build_config(),
        ).__aenter__()
        # Inject opening context so Aria knows who to greet
        name = self.customer["name"] if self.customer else "the customer"
        await self._session.send_client_content(
            turns=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            text=(
                                f"[SYSTEM NOTE - NOT FROM CUSTOMER] "
                                f"You are connected to {name} (ID: {self.customer_id}). "
                                f"Begin the call now."
                            )
                        )
                    ],
                )
            ],
            turn_complete=True,
        )
        logger.info(f"[Gemini] Session opened for customer {self.customer_id}")

    async def send_audio(self, pcm_data: bytes):
        """Queue inbound customer audio (PCM 16-bit 16kHz)."""
        if self._session:
            await self._session.send_realtime_input(
                audio=types.Blob(data=pcm_data, mime_type="audio/pcm;rate=16000")
            )

    async def receive_loop(self, on_audio: callable):
        """
        Receive responses from Gemini. Calls on_audio(mulaw_bytes) for each audio chunk.
        Handles function calls synchronously (Gemini 3.8-live default).
        """
        async for response in self._session.receive():
            sc = response.server_content

            if sc:
                # Audio output
                if sc.model_turn:
                    for part in sc.model_turn.parts:
                        if part.inline_data:
                            mulaw = pcm16_to_mulaw(part.inline_data.data)
                            await on_audio(mulaw)

                # Transcription
                if sc.input_transcription and sc.input_transcription.text:
                    txt = sc.input_transcription.text
                    self._transcript_in.append(txt)
                    logger.info(f"[Customer] {txt}")

                if sc.output_transcription and sc.output_transcription.text:
                    txt = sc.output_transcription.text
                    self._transcript_out.append(txt)
                    logger.info(f"[Aria] {txt}")

            # Tool calls
            tool_call = response.tool_call
            if tool_call:
                results = []
                for fc in tool_call.function_calls:
                    result = execute_tool(fc.name, dict(fc.args))
                    results.append(
                        types.FunctionResponse(
                            id=fc.id,
                            name=fc.name,
                            response={"result": result},
                        )
                    )
                await self._session.send_tool_response(function_responses=results)

    async def close(self):
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
        self._print_summary()

    def _print_summary(self):
        customer = self.customer or {}
        logger.info("=" * 60)
        logger.info(f"CALL SUMMARY — {customer.get('name', self.customer_id)}")
        logger.info(f"  Plan       : {customer.get('plan', 'N/A')}")
        logger.info(f"  Amount Due : ${customer.get('amount_due', 'N/A')}")
        logger.info(f"  Failure    : {customer.get('failure_reason', 'N/A')}")
        fresh = get_customer(self.customer_id)
        logger.info(f"  Outcome    : {fresh.get('status', 'unknown') if fresh else 'unknown'}")
        if fresh and fresh.get("notes"):
            logger.info(f"  Notes      : {fresh['notes']}")
        logger.info("-" * 30)
        logger.info("Transcript (customer):")
        for t in self._transcript_in:
            logger.info(f"  > {t}")
        logger.info("Transcript (Aria):")
        for t in self._transcript_out:
            logger.info(f"  < {t}")
        logger.info("=" * 60)


# ── WebSocket handler (Twilio Media Stream) ────────────────────────────────────

@app.websocket("/media-stream/{customer_id}")
async def media_stream(ws: WebSocket, customer_id: str):
    """
    Twilio sends audio in and receives audio out over this WebSocket.
    Protocol: Twilio Media Stream v2 (JSON envelope, base64 mulaw payload).
    """
    await ws.accept()
    logger.info(f"[WS] Twilio connected for customer {customer_id}")

    gemini = GeminiSession(customer_id)
    increment_attempts(customer_id)

    try:
        await gemini.connect()
    except Exception as e:
        logger.error(f"[Gemini] Failed to open session: {e}")
        await ws.close()
        return

    stream_sid: str | None = None

    async def send_audio_to_twilio(mulaw_bytes: bytes):
        """Callback: send Aria's voice back to Twilio."""
        if stream_sid and ws.client_state.value == 1:  # CONNECTED
            payload = base64.b64encode(mulaw_bytes).decode()
            msg = json.dumps({
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": payload},
            })
            await ws.send_text(msg)

    # Run receive loop as background task
    receive_task = asyncio.create_task(gemini.receive_loop(send_audio_to_twilio))

    try:
        async for raw in ws.iter_text():
            data = json.loads(raw)
            event = data.get("event")

            if event == "start":
                stream_sid = data["start"]["streamSid"]
                logger.info(f"[WS] Stream started: {stream_sid}")

            elif event == "media":
                payload = data["media"]["payload"]
                mulaw_bytes = base64.b64decode(payload)
                pcm_bytes = mulaw_to_pcm16(mulaw_bytes)
                await gemini.send_audio(pcm_bytes)

            elif event == "stop":
                logger.info(f"[WS] Stream stopped: {stream_sid}")
                break

    except WebSocketDisconnect:
        logger.info(f"[WS] Twilio disconnected for customer {customer_id}")
    except Exception as e:
        logger.error(f"[WS] Error: {e}", exc_info=True)
    finally:
        receive_task.cancel()
        await gemini.close()
        logger.info(f"[WS] Session closed for customer {customer_id}")


# ── Outbound call trigger ──────────────────────────────────────────────────────

@app.post("/call/{customer_id}")
async def place_call(customer_id: str):
    """
    HTTP POST endpoint to trigger an outbound call to a customer.
    Example: curl -X POST http://localhost:8000/call/C001
    """
    customer = get_customer(customer_id)
    if not customer:
        return {"error": "Customer not found"}

    if not twilio_client:
        return {"error": "Twilio not configured (missing env vars)"}

    twiml_url = f"{BASE_URL}/twiml/{customer_id}"
    to_number = customer["phone"]

    call = twilio_client.calls.create(
        url=twiml_url,
        to=to_number,
        from_=TWILIO_FROM_NUMBER,
        method="POST",
    )
    logger.info(f"[Twilio] Call SID {call.sid} → {to_number} for customer {customer_id}")
    return {
        "call_sid": call.sid,
        "customer_id": customer_id,
        "to": to_number,
        "status": call.status,
    }


@app.post("/call-all")
async def call_all_customers():
    """Trigger outbound calls to ALL 10 customers (rate-limited, 1/sec)."""
    results = []
    for customer in get_all_customers():
        if customer["status"] == "failed":
            result = await place_call(customer["id"])
            results.append(result)
            await asyncio.sleep(1)  # avoid Twilio rate limits
    return {"calls_initiated": len(results), "results": results}


@app.get("/customers")
async def list_customers():
    """View current state of all customer records."""
    return get_all_customers()


@app.get("/health")
async def health():
    return {"status": "ok", "model": GEMINI_MODEL}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY is not set. Please add it to .env")
        sys.exit(1)
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
