"""Smoke test for the deployed Agent Engine instance (chunk 12, Pass 2).

Reads deploy/.engine_resource, opens a remote session, asks two questions —
one that exercises the BigQuery path (Toolbox over its public URL) and one
that exercises Firestore (proving the datastore.user grant) — and times
each. Prints the engine's registered operations first, so if the SDK method
names have drifted we see what IS available instead of a bare AttributeError.

Run:  python scripts/engine_smoke.py
"""
from __future__ import annotations

from shared.script_env import require_venv
require_venv()

import json
import pathlib
import sys
import time

import vertexai
from vertexai import agent_engines

RESOURCE_FILE = pathlib.Path(__file__).resolve().parent.parent / "deploy" / ".engine_resource"

QUESTIONS = [
    ("BigQuery via Toolbox", "Who is driving car 13 and what team is he with?"),
    ("Firestore live state", "What is our current position and energy right now?"),
]


def main() -> None:
    if not RESOURCE_FILE.exists():
        sys.exit(f"{RESOURCE_FILE} not found — run deploy/deploy_agent_engine.sh first")
    resource = RESOURCE_FILE.read_text().strip()
    project, location = resource.split("/")[1], resource.split("/")[3]
    print(f"Engine: {resource}")

    vertexai.init(project=project, location=location)
    app = agent_engines.get(resource)

    ops = sorted({s.get("name", "?") for s in app.operation_schemas()})
    print(f"Registered operations: {', '.join(ops)}\n")

    session = app.create_session(user_id="smoke")
    session_id = session["id"] if isinstance(session, dict) else session.id
    print(f"Session: {session_id}\n")

    verbose = "--verbose" in sys.argv
    for label, question in QUESTIONS:
        print(f"[{label}] {question}")
        t0 = time.monotonic()
        final_text = []
        raw_events = []
        for event in app.stream_query(
            user_id="smoke", session_id=session_id, message=question,
        ):
            raw_events.append(event)
            content = event.get("content") if isinstance(event, dict) else None
            for part in (content or {}).get("parts", []):
                if part.get("function_call"):
                    print(f"      ▶ {part['function_call'].get('name')}")
                if part.get("function_response") and verbose:
                    resp = json.dumps(part["function_response"], default=str)
                    print(f"      ◀ {resp[:300]}")
                if part.get("text"):
                    final_text.append(part["text"])
            if isinstance(event, dict) and event.get("error_message"):
                print(f"      !! error event: {event.get('error_code')}: "
                      f"{event['error_message'][:200]}")
        answer = "".join(final_text).strip()
        print(f"  ENGINEER: {answer if answer else '(EMPTY)'}")
        print(f"  ({time.monotonic() - t0:.1f}s)")
        if not answer:
            print("  -- empty answer: raw events follow --")
            for i, ev in enumerate(raw_events):
                print(f"  [{i}] {json.dumps(ev, default=str)[:600]}")
        print()

    print("Smoke test complete.")


if __name__ == "__main__":
    main()