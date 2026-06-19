# State Writer → Cloud Run Worker Pool (Pub/Sub pull)

Resolves open question **#5**. Converts the state writer from a FastAPI **push**-subscription
Cloud Run *service* into a **Cloud Run Worker Pool** doing Pub/Sub **pull**. Safe because the
writer is already idempotent (deterministic event doc IDs); redelivery converges.

## Why

A worker pool is what Pub/Sub-pull workloads are *for*: a long-running, no-request-surface
consumer that pulls and processes continuously. The push service exists only to receive HTTP
POSTs from Pub/Sub — a wrapper we don't need once we pull. Pull also drops the OIDC push-auth
SA + `run.invoker` + endpoint juggling.

## What stays (the core is unchanged)

`state_writer/main.py`'s domain logic is transport-agnostic and **kept verbatim**:
- `write_frame(frame_dict)` — validate `RaceState`, overwrite `race_states/{race_id}`, batch
  the events.
- `build_event(...)` and `event_doc_id(...)` — deterministic IDs → idempotency. **This is the
  reason the conversion is safe.**

Only the *transport* changes: instead of an HTTP handler decoding the Pub/Sub push envelope,
a pull loop receives messages, decodes `message.data` (base64 JSON), calls `write_frame`, and
acks. Same idempotency, same Firestore writes.

## New shape

```
state_writer/
  worker.py        # NEW: pull loop — StreamingPull, decode → write_frame → ack; nack on transient
  writer_core.py   # write_frame / build_event / event_doc_id (lifted from main.py, unchanged)
  Dockerfile       # CMD runs the worker (no web server, no $PORT contract)
  requirements.txt # drop fastapi/uvicorn; add google-cloud-pubsub
```

Keep a tiny `main.py`/`/ingest` path **only** for local manual seeding if useful, or move
that into `scripts/seed_test_state.py` against Firestore directly.

### Pull loop sketch

```python
from google.cloud import pubsub_v1
from state_writer.writer_core import write_frame
import base64, json, os

sub_path = pubsub_v1.SubscriberClient.subscription_path(PROJECT_ID, SUBSCRIPTION_NAME)

def callback(msg):
    try:
        write_frame(json.loads(base64.b64decode(msg.data)))  # data is the frame JSON
        msg.ack()
    except (ValueError, json.JSONDecodeError):
        msg.ack()                 # malformed → drop (matches the push 400 = no-retry)
    except Exception:
        msg.nack()                # transient (Firestore) → redeliver (idempotent)

with pubsub_v1.SubscriberClient() as sub:
    future = sub.subscribe(sub_path, callback=callback,
                           flow_control=pubsub_v1.types.FlowControl(max_messages=100))
    future.result()
```

## Subscription config

- Subscription type: **pull** (not push). No `--push-endpoint`, no `--push-auth-service-account`.
- `--ack-deadline=60`, `--message-retention-duration=10m` (as today).
- The worker's SA keeps `roles/datastore.user`; add `roles/pubsub.subscriber` on the
  subscription/topic. **Drop** the `run.invoker` grant and the `iam.serviceAccountTokenCreator`
  grant to the Pub/Sub service agent (those were push-auth only).

## Scaling

- 1 Hz frames, single race → tiny load. **Worker pool size 1** (min=max=1) is plenty and gives
  in-order-ish processing; raise `max` only if we replay multiple races concurrently.
- Idempotency means horizontal scale is *safe* but unnecessary here.
- No scale-to-zero need (the simulator runs for a bounded replay); start the pool with the
  simulator, stop after.

## Local-dev story (the real tradeoff)

Push was trivially `curl`-able (`POST /` with an envelope, or `POST /ingest` with a raw frame).
Pull needs a subscription to read from. Options, simplest first:
1. **Pub/Sub emulator** (`gcloud beta emulators pubsub start`): set `PUBSUB_EMULATOR_HOST`, run
   the simulator's publisher and the worker against the emulator. Fully offline.
2. **Real topic + a dev pull subscription**: run the worker locally against a deployed sub.
3. **Keep `scripts/seed_test_state.py`** writing frames straight to Firestore for tests that
   don't care about Pub/Sub at all (fastest inner loop for frame_tools work).

Document #1 as the canonical local path in the student guide; it's the closest analog to the
old `curl`.

## Setup/deploy changes

- **`setup/5_deploy_state_writer.sh`** — rename intent to "deploy state writer worker pool";
  call the rewritten deploy script.
- **`deploy/deploy_state_writer.sh`** — rewrite: build the worker image; `gcloud run
  worker-pools deploy` (or the current worker-pool deploy verb — confirm in `gcloud` at build
  time); create a **pull** subscription instead of push; grant `pubsub.subscriber`; drop the
  push-auth/tokenCreator/invoker blocks.
- The simulator + topic (`fe-telemetry`) are unchanged.

> Verify the exact `gcloud run worker-pools` surface/flags when implementing — worker pools
> were GA-ing around this period and the deploy verb/flags should be confirmed against current
> `gcloud`, not assumed from this spec.
