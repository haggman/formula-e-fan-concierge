"""State Writer — domain logic (transport-agnostic).

Validate a frame → overwrite race_states/{race_id} → idempotently write its
events to race_events/. This is the core of the data plane:

  Simulator → Pub/Sub fe-telemetry → [State Writer] → Firestore ← Agent + Frontend

Lifted VERBATIM from the former FastAPI push service (state_writer/main.py) when
the transport changed to a Cloud Run Worker Pool doing Pub/Sub PULL
(state_writer/worker.py). The transport changed; this logic did not.

Idempotency: event docs use DETERMINISTIC IDs derived from the event content
(race_id + race_time_s + event_type + car_number + data hash). Pub/Sub
at-least-once redelivery and full race replays therefore overwrite the same
docs instead of appending duplicates. Making the WRITE idempotent (not the
delivery exact) is exactly what makes the pull conversion safe.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any

from google.cloud import firestore

from shared.models import Event, EventType, RaceState

logger = logging.getLogger("state_writer.core")

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("PROJECT_ID")
if not PROJECT_ID:
    raise RuntimeError("GOOGLE_CLOUD_PROJECT (or PROJECT_ID) env var required")

# Firestore client — default database, same project. One per process.
db = firestore.Client(project=PROJECT_ID)


def event_doc_id(event: Event) -> str:
    """Deterministic Firestore doc ID for an event.

    Same event content → same ID → idempotent writes. The data hash
    disambiguates distinct events that share (time, type, car) — e.g. two
    different race_control messages in the same second.

    Format: {race_id}_{race_time_s}_{event_type}_{car_or_x}_{sha1[:12]}
    """
    payload = json.dumps(
        event.data, sort_keys=True, separators=(",", ":"), default=str
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    car = event.car_number if event.car_number is not None else "x"
    return f"{event.race_id}_{event.race_time_s}_{event.event_type.value}_{car}_{digest}"


def write_frame(frame_dict: dict[str, Any]) -> None:
    """Parse a frame dict, validate via Pydantic, write RaceState + Events.

    Fully idempotent: RaceState is an overwrite, and Event docs use
    deterministic IDs (see event_doc_id), so re-delivering the same frame —
    whether via Pub/Sub retry or a full race replay — converges to the same
    Firestore state instead of accumulating duplicates.
    """
    # Stamp wall-clock ns onto the frame before validating
    if "ts_ns_wall" not in frame_dict:
        frame_dict["ts_ns_wall"] = time.time_ns()

    state = RaceState.model_validate(frame_dict)
    race_id = state.race_id
    race_time_s = state.race_time_s
    ts_ns_wall = state.ts_ns_wall or time.time_ns()

    # ------------------------------------------------------------------
    # 1) Overwrite the current RaceState doc
    # ------------------------------------------------------------------
    state_doc = state.model_dump(mode="json")
    state_doc["updated_at_unix"] = int(time.time())  # for monitoring
    db.collection("race_states").document(race_id).set(state_doc)

    # ------------------------------------------------------------------
    # 2) Write any events in this tick to race_events/ (idempotent set)
    # ------------------------------------------------------------------
    raw_events = frame_dict.get("events") or []
    if not raw_events:
        logger.info("frame t=%d phase=%s no events", race_time_s, state.race_phase.value)
        return

    batch = db.batch()
    written = 0
    for raw in raw_events:
        try:
            event = build_event(raw, ts_ns_wall, race_time_s, race_id)
        except (ValueError, KeyError) as e:
            logger.warning("skipping malformed event at t=%d: %s (%s)",
                           race_time_s, raw, e)
            continue
        doc_ref = db.collection("race_events").document(event_doc_id(event))
        batch.set(doc_ref, event.model_dump(mode="json"))
        written += 1

    if written:
        batch.commit()
        logger.info("frame t=%d wrote %d events", race_time_s, written)


def build_event(
    raw: dict[str, Any], ts_ns_wall: int, race_time_s: int, race_id: str
) -> Event:
    """Convert a raw frame event into our Event model.

    Frame events have a "type" field plus type-specific keys. We promote
    `car_number` to a top-level indexed field and stash the rest in `data`.
    """
    event_type_str = raw.get("type")
    if not event_type_str:
        raise ValueError("event missing 'type'")

    event_type = EventType(event_type_str)  # validates against enum

    # car_number may be absent for some race_control events; preserve as None
    car_number = raw.get("car_number")

    # Everything except the well-known top-level fields goes in `data`
    data = {k: v for k, v in raw.items() if k not in ("type", "car_number")}

    return Event(
        event_type=event_type,
        ts_ns_wall=ts_ns_wall,
        race_time_s=race_time_s,
        race_id=race_id,
        car_number=car_number,
        data=data,
    )
