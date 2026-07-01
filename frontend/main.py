"""Race-Day Companion frontend service.

FastAPI + websocket: streams live field-wide race state to the fan UI AND the
commentator's proactive broadcast calls (frontend/commentator_loop.py — the
trigger policy as a background task, spoken via TTS). The same socket carries the
fan's car SELECTION inbound ({type:"select", car_number}) → the commentator loop
narrows commentary onto that car. Q&A to the commentator rides the socket too.

Re-aimed from Ch2's pit-wall service: dropped the "our car #13" framing
(OUR_CAR_NUMBER) and the AGENT_PACKAGE-resolved tools.state_client; state now
comes from the vendored shared.state_client, and the agent is the commentator.
The CX concierge chat widget (ask-anything bot) is a follow-on embed (#5/#7).

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

from frontend.commentator_loop import CommentatorLoop
from frontend.tts import synthesize
from shared.models import RaceState
from shared.state_client import get_state_client

# The commentator is field-wide — no single "our car". The fan's SELECTED car
# arrives over the websocket ({type:"select"}) and is held in the loop. State is
# read from the vendored shared.state_client (the commentator package has no
# per-package state_client). (Re-aimed from Ch2, where this resolved
# OUR_CAR_NUMBER + tools.state_client through the AGENT_PACKAGE seam.)

# Uvicorn configures only ITS OWN loggers. Without this, every INFO line
# from the commentator loop — radio calls, restart notices, the scoreboard —
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
commentator: CommentatorLoop | None = None  # set in lifespan
latest = {"race_time_s": 0, "lap": None}    # for stamping Q&A log entries


async def radio_broadcast(message: dict) -> None:
    """Broadcast wrapper that gives the commentator a voice: synthesizes audio
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
    """Field-wide payload: the full car list, each with enough live detail for the
    selected-car stats panel. No "our car" — the fan picks one in the UI.
    """
    cars = []
    for c in sorted(state.cars, key=lambda c: (c.is_retired, c.position)):
        cars.append({
            "car": c.car_number,
            "driver": c.driver_short_name,
            "position": c.position,
            "lap": c.current_lap,
            "speed_kmh": round(c.speed_kmh, 0),
            "energy_pct": round(c.energy.pct_remaining, 1),
            "am_active": c.attack_mode.active,
            "am_used": c.attack_mode.activations_used,
            "am_budget_s": round(c.attack_mode.remaining_budget_s, 0),
            "am_scenario": c.attack_mode.scenario,
            "retired": c.is_retired,
            # GPS for the track map — plotted via the saved projection transform
            "lat": round(c.gps.lat, 6),
            "lng": round(c.gps.lng, 6),
        })
    return {
        "type": "state",
        "race_time_s": state.race_time_s,
        "race_phase": state.race_phase.value,
        "leader_lap": state.current_leader_lap,
        "cars": cars,
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
                latest["lap"] = payload["leader_lap"]
                await manager.broadcast(payload)
        except Exception:
            logger.exception("state poll failed")
        await asyncio.sleep(POLL_INTERVAL_S)


# ============================================================================
# App
# ============================================================================


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    global commentator
    poller = asyncio.create_task(state_poller())
    commentator = CommentatorLoop(radio_broadcast)
    commentator_task = asyncio.create_task(commentator.run())
    yield
    for task in (poller, commentator_task):
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await commentator.close()


app = FastAPI(title="Race-Day Companion", lifespan=lifespan)


# Dev convenience: never let the browser / Cloud Shell Web Preview cache the page
# or the outline, so a reload always picks up the latest build (the page and the
# track JSON change often during the build, and stale caches masquerade as bugs).
_NO_CACHE = {"Cache-Control": "no-store, must-revalidate"}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=_NO_CACHE)


@app.get("/track_outline.json")
async def track_outline() -> FileResponse:
    """The GPS-derived circuit outline + projection transform, generated by
    notebooks/track_map_outline.ipynb and dropped into frontend/static/. The page
    fetches this to draw the track and place car dots. 404 (handled gracefully in
    the UI) until the file is present."""
    path = STATIC_DIR / "track_outline.json"
    if not path.exists():
        raise HTTPException(404, "track_outline.json not staged in frontend/static/")
    return FileResponse(path, headers=_NO_CACHE)


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
            # The fan clicked a car (or cleared the selection). Thread it into
            # the commentator loop so commentary narrows onto that car; null /
            # missing car_number = back to pure field-wide.
            # (Ask-anything Q&A now lives in the embedded CX concierge widget,
            # not a websocket path — the commentator is the push voice only.)
            if data.get("type") == "select" and commentator:
                car = data.get("car_number")
                commentator.set_selection(int(car) if car is not None else None)
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


