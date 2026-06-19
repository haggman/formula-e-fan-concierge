"""Race Engineer frontend service (chunk 9; packaging P1.2 routes the agent
package through the AGENT_PACKAGE seam).

Pass 2: FastAPI + websocket streaming live race state AND the engineer's
proactive radio calls (frontend/engineer_loop.py — the chunk 8 trigger
policy as a background task). Pass 3 adds Q&A over the same socket.

Packaging P1.2: OUR_CAR_NUMBER and get_state_client resolve through
agent_module() so the WHOLE frontend (this poller and the engineer loop)
shares one state_client module — and therefore one Firestore-client
singleton — from whichever package AGENT_PACKAGE selects.

Run locally (Cloud Shell, Web Preview on 8080):
    uvicorn frontend.main:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from pathlib import Path

import httpx
from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from frontend.agent_client import agent_module
from frontend.engineer_loop import EngineerLoop
from frontend.stt import transcribe
from frontend.tts import synthesize
from shared.models import RaceState

# --- resolved through the AGENT_PACKAGE seam (starter vs solution) ---
OUR_CAR_NUMBER = agent_module("config").OUR_CAR_NUMBER
get_state_client = agent_module("tools.state_client").get_state_client

# Uvicorn configures only ITS OWN loggers. Without this, every INFO line
# from the engineer loop — radio calls, restart notices, the scoreboard —
# is silently dropped by Python's WARNING-level lastResort handler.
# Found the hard way: the scoreboard shipped and nobody could hear it.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # SIM-proxy chatter

logger = logging.getLogger("frontend")
STATIC_DIR = Path(__file__).parent / "static"
POLL_INTERVAL_S = 1.0
SIM_URL = os.environ.get("SIM_URL", "").rstrip("/")

# Hard stop for the universal-503s footgun: a recycled Cloud Shell session
# drops exports, the pit wall comes up sim-less, and EVERYTHING on the SIM
# bar 503s. Local mode requires SIM_URL — fail loudly at startup with the
# exact fix instead of limping. (Engine-mode deploys set SIM_URL in the
# service env, so this never trips there.)
if os.environ.get("AGENT_MODE", "local") == "local" and not SIM_URL:
    raise SystemExit(
        "SIM_URL is not set — the SIM bar (and the whole local pit wall) "
        "would 503 on everything.\nFix:\n"
        '  export SIM_URL=$(gcloud run services describe fe-simulator '
        '--region "$REGION" --format="value(status.url)")\n'
        "or just launch with:  bash demo.sh  (does all of this itself)"
    )


# ============================================================================
# Websocket connection registry
# ============================================================================


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        logger.info("client connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        logger.info("client disconnected (%d total)", len(self._connections))

    async def broadcast(self, message: dict) -> None:
        """Send to every client; drop the ones that have gone away."""
        if not self._connections:
            return
        payload = json.dumps(message)
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
engineer: EngineerLoop | None = None        # set in lifespan
latest = {"race_time_s": 0, "lap": None}    # for stamping Q&A log entries


async def radio_broadcast(message: dict) -> None:
    """Broadcast wrapper that gives the engineer a voice: synthesizes audio
    for every spoken radio kind before fan-out. Questions stay silent; a
    synthesis failure degrades to text-only."""
    if message.get("type") == "radio" and message.get("kind") != "question":
        audio = await synthesize(message.get("text", ""))
        if audio:
            message["audio"] = audio
    await manager.broadcast(message)


# ============================================================================
# State payload for the UI
# ============================================================================


def ui_state(state: RaceState) -> dict:
    """Full-field payload for the position tower + our-car panel."""
    cars = []
    for c in sorted(state.cars, key=lambda c: (c.is_retired, c.position)):
        cars.append({
            "car": c.car_number,
            "driver": c.driver_short_name,
            "position": c.position,
            "lap": c.current_lap,
            "am_active": c.attack_mode.active,
            "am_used": c.attack_mode.activations_used,
            "retired": c.is_retired,
            "us": c.car_number == OUR_CAR_NUMBER,
        })
    our = state.car_by_number(OUR_CAR_NUMBER)
    return {
        "type": "state",
        "race_time_s": state.race_time_s,
        "race_phase": state.race_phase.value,
        "cars": cars,
        "our": None if our is None else {
            "position": our.position,
            "lap": our.current_lap,
            "energy_pct": round(our.energy.pct_remaining, 1),
            "am_active": our.attack_mode.active,
            "am_used": our.attack_mode.activations_used,
            "am_budget_s": our.attack_mode.remaining_budget_s,
            "am_scenario": our.attack_mode.scenario,
        },
    }


# ============================================================================
# Background poller
# ============================================================================


async def state_poller() -> None:
    client = get_state_client()
    while True:
        try:
            state = client.get_race_state(fresh=True)
            if state is not None:
                payload = ui_state(state)
                latest["race_time_s"] = payload["race_time_s"]
                latest["lap"] = payload["our"]["lap"] if payload["our"] else None
                await manager.broadcast(payload)
        except Exception:
            logger.exception("state poll failed")
        await asyncio.sleep(POLL_INTERVAL_S)


# ============================================================================
# App
# ============================================================================


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    global engineer
    poller = asyncio.create_task(state_poller())
    engineer = EngineerLoop(radio_broadcast)
    engineer_task = asyncio.create_task(engineer.run())
    yield
    for task in (poller, engineer_task):
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await engineer.close()


app = FastAPI(title="Race Engineer", lifespan=lifespan)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


async def _handle_ask(question: str) -> None:
    stamp = {"race_time_s": latest["race_time_s"], "lap": latest["lap"]}
    t0 = time.monotonic()
    try:
        answer = await engineer.ask(question)
        await radio_broadcast({"type": "radio", "kind": "qa",
                               "text": answer,
                               "secs": round(time.monotonic() - t0, 1),
                               **stamp})
    except Exception as e:
        logger.warning("qa failed: %s", str(e).splitlines()[0][:160])
        await radio_broadcast({"type": "radio", "kind": "qa",
                               "text": "Radio failure on that one — ask again.",
                               "error": True, **stamp})


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            question = (data.get("question") or "").strip()
            if data.get("type") == "ask" and question and engineer:
                await manager.broadcast({
                    "type": "radio", "kind": "question", "text": question,
                    "race_time_s": latest["race_time_s"], "lap": latest["lap"],
                })
                asyncio.create_task(_handle_ask(question))
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ============================================================================
# Simulator control proxy (pit-wall systems panel)
# ============================================================================

_SIM_ACTIONS = {
    "restart": "/restart",
    "pause": "/pause",
    "resume": "/resume",
    "speed": "/speed",
    "auto-restart": "/auto-restart",
}


@app.get("/api/sim/config")
async def sim_config() -> dict:
    if not SIM_URL:
        raise HTTPException(503, "SIM_URL not configured")
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SIM_URL}/config", timeout=10)
        r.raise_for_status()
        return r.json()


@app.post("/api/sim/finish")
async def sim_finish() -> dict:
    """FINISH: jump the replay to ~10s before the checkered flag and let it
    play out — the fast path to end-of-race states for rehearsal. Lives
    server-side so /jump itself stays OFF the generic proxy whitelist.
    Registered BEFORE the {action} catch-all: FastAPI matches in
    registration order, so this must stay above sim_control.
    Note: /status exposes no end_tick — the end is race_time_s +
    seconds_remaining, and /jump clamps to the valid range anyway."""
    if not SIM_URL:
        raise HTTPException(503, "SIM_URL not configured")
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SIM_URL}/status", timeout=10)
        r.raise_for_status()
        st = r.json()
        target = (float(st.get("race_time_s", 0))
                  + float(st.get("seconds_remaining", 0)) - 10)
        r = await client.post(f"{SIM_URL}/jump",
                              json={"race_time_s": max(0.0, target)},
                              timeout=15)
        r.raise_for_status()
        return r.json()


@app.post("/api/sim/{action}")
async def sim_control(action: str, payload: dict | None = Body(default=None)) -> dict:
    if action not in _SIM_ACTIONS:
        raise HTTPException(404, f"unknown sim action: {action}")
    if not SIM_URL:
        raise HTTPException(503, "SIM_URL not configured")
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{SIM_URL}{_SIM_ACTIONS[action]}", json=payload, timeout=15)
        r.raise_for_status()
        return r.json()


# ============================================================================
# Push-to-talk transcription
# ============================================================================


@app.post("/api/stt")
async def stt(request: Request) -> dict:
    """Body: raw audio bytes from MediaRecorder (webm/opus or whatever the
    browser produced — Speech V2 auto-detects). Returns the transcript."""
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "empty audio")
    try:
        transcript = await transcribe(audio)
    except Exception as e:
        logger.warning("stt failed: %s", str(e).splitlines()[0][:160])
        raise HTTPException(502, "transcription failed")
    return {"transcript": transcript}
