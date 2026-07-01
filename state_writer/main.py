"""SUPERSEDED — the State Writer is now a Cloud Run Worker Pool (Pub/Sub PULL).

This was the FastAPI PUSH-subscription service. The transport moved to a pull
worker; the domain logic moved out unchanged:

  - state_writer/writer_core.py  — write_frame / build_event / event_doc_id (unchanged)
  - state_writer/worker.py       — the StreamingPull loop that calls write_frame
  - deploy/deploy_state_writer.sh — deploys the worker pool + a pull subscription

See spec/state_writer_worker_pool.md. Safe to delete this file
(`git rm state_writer/main.py`); kept as a tombstone only because this
environment couldn't remove it directly. For local seeding without Pub/Sub,
use scripts/seed_test_state.py (writes straight to Firestore).
"""
