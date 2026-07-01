"""State Writer worker — Cloud Run Worker Pool (Pub/Sub PULL).

Replaces the old FastAPI push service. A worker pool is what a Pub/Sub-pull
workload is FOR: a long-running consumer with no request surface. It opens a
StreamingPull on the subscription, decodes each frame, and calls the same
idempotent `write_frame` the push service used — so the conversion is safe by
construction (deterministic event doc IDs; redelivery converges).

Transport only:
  push service:  Pub/Sub POSTs an envelope → HTTP handler → decode → write_frame
  this worker:   StreamingPull message → decode message.data → write_frame → ack

Env:
  GOOGLE_CLOUD_PROJECT (or PROJECT_ID)   the project
  SUBSCRIPTION_NAME                       pull subscription (default fe-state-writer-sub)
  MAX_MESSAGES                            flow-control cap (default 100)
"""
from __future__ import annotations

import json
import logging
import os
import signal
import threading

from google.cloud import pubsub_v1

from state_writer.writer_core import write_frame

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("state_writer.worker")

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("PROJECT_ID")
if not PROJECT_ID:
    raise RuntimeError("GOOGLE_CLOUD_PROJECT (or PROJECT_ID) env var required")

SUBSCRIPTION_NAME = os.environ.get("SUBSCRIPTION_NAME", "fe-state-writer-sub")
MAX_MESSAGES = int(os.environ.get("MAX_MESSAGES", "100"))


def _callback(message: "pubsub_v1.subscriber.message.Message") -> None:
    """One pulled message. message.data is the base64-decoded frame JSON bytes
    (the Pub/Sub client already un-base64s the wire payload; publishers send the
    raw frame JSON as the message body)."""
    try:
        frame = json.loads(message.data)
    except (ValueError, json.JSONDecodeError) as e:
        # Malformed → drop (ack). Mirrors the push path's 400 = "do not retry".
        logger.warning("dropping malformed message %s: %s", message.message_id, e)
        message.ack()
        return
    try:
        write_frame(frame)
        message.ack()
    except Exception as e:
        # Transient (e.g. Firestore) → nack → redeliver. Safe: write_frame is idempotent.
        logger.exception("write failed, will redeliver (%s): %s", message.message_id, e)
        message.nack()


def main() -> None:
    subscriber = pubsub_v1.SubscriberClient()
    sub_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_NAME)
    flow = pubsub_v1.types.FlowControl(max_messages=MAX_MESSAGES)

    future = subscriber.subscribe(sub_path, callback=_callback, flow_control=flow)
    logger.info("state writer worker online — pulling %s (project %s)",
                SUBSCRIPTION_NAME, PROJECT_ID)

    # Block until the pool is stopped (Cloud Run sends SIGTERM), then drain cleanly.
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    stop.wait()

    logger.info("shutting down — cancelling streaming pull")
    future.cancel()
    try:
        future.result(timeout=30)
    except Exception:
        pass
    subscriber.close()
    logger.info("worker stopped")


if __name__ == "__main__":
    main()
