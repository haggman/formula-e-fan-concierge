"""Seed Firestore with a known test frame.

Used to test frame tools without the simulator running. Writes the canonical
sample frame (race_time_s=1449, safety car phase, lap 21) that we've been
using throughout the Fork 2 build for design discussions.

The sample includes:
  - 22 cars (one retired: car 7 GUE)
  - Car 13 (DAC) at P2 behind car 37 (CAS)
  - Car 48 (MOR) actively in Attack Mode
  - Mixed scenarios across the field
  - Safety car phase

Two ways to seed:
  1. Direct Firestore write (default — just hit Firestore yourself)
  2. HTTP POST to deployed State Writer's /ingest endpoint (validates the
     end-to-end Pub/Sub-skipped path)

Usage:
    python scripts/seed_test_state.py            # direct Firestore
    python scripts/seed_test_state.py --via-writer http://localhost:8080
"""
from __future__ import annotations

from shared.script_env import require_venv
require_venv()

import argparse
import json
import os
import sys
import time
from typing import Any

import requests
from google.cloud import firestore


SAMPLE_FRAME: dict[str, Any] = {
    "schema_version": "1.0",
    "race_id": "berlin_2024_r10",
    "race_time_s": 1449,
    "race_duration_s": 2867.78,
    "pct_complete": 50.53,
    "race_phase": "safety_car",
    "current_leader_lap": 21,
    "cars": [
        {"car_number": 1, "driver_short_name": "DEN", "position": 5, "current_lap": 21, "speed_kmh": 75.55, "gps": {"lat": 52.481327, "lng": 13.391753, "heading": 256.7}, "accel_x": 1.0, "accel_y": 0.429, "brake_pct": 0.0, "steer": 1113.2, "yaw_rate": 2.811, "energy": {"pct_remaining": 53.011, "kwh_remaining": 21.735, "pct_used": 46.989}, "attack_mode": {"active": False, "activations_used": 2, "scenario": 1, "remaining_budget_s": 0.0}, "is_retired": False},
        {"car_number": 2, "driver_short_name": "VAN", "position": 19, "current_lap": 21, "speed_kmh": 53.44, "gps": {"lat": 52.4792, "lng": 13.389751, "heading": 285.17}, "accel_x": -0.362, "accel_y": -1.003, "brake_pct": 26.0, "steer": -1582.7, "yaw_rate": 0.305, "energy": {"pct_remaining": 52.501, "kwh_remaining": 21.525, "pct_used": 47.499}, "attack_mode": {"active": False, "activations_used": 2, "scenario": 1, "remaining_budget_s": 0.0}, "is_retired": False},
        {"car_number": 3, "driver_short_name": "SET", "position": 16, "current_lap": 21, "speed_kmh": 102.87, "gps": {"lat": 52.480931, "lng": 13.391763, "heading": 56.19}, "accel_x": -0.933, "accel_y": 0.032, "brake_pct": 100.0, "steer": 1071.3, "yaw_rate": -1.222, "energy": {"pct_remaining": 53.099, "kwh_remaining": 21.77, "pct_used": 46.901}, "attack_mode": {"active": False, "activations_used": 1, "scenario": 1, "remaining_budget_s": 180.0}, "is_retired": False},
        {"car_number": 4, "driver_short_name": "ERI", "position": 15, "current_lap": 21, "speed_kmh": 75.6, "gps": {"lat": 52.481035, "lng": 13.391996, "heading": 55.51}, "accel_x": -0.939, "accel_y": 0.251, "brake_pct": 100.0, "steer": -720.6, "yaw_rate": -0.978, "energy": {"pct_remaining": 52.907, "kwh_remaining": 21.692, "pct_used": 47.093}, "attack_mode": {"active": False, "activations_used": 2, "scenario": 3, "remaining_budget_s": 0.0}, "is_retired": False},
        {"car_number": 5, "driver_short_name": "HUG", "position": 12, "current_lap": 21, "speed_kmh": 41.68, "gps": {"lat": 52.481189, "lng": 13.392202, "heading": 19.35}, "accel_x": -0.467, "accel_y": 1.478, "brake_pct": 1.0, "steer": 2745.4, "yaw_rate": 0.367, "energy": {"pct_remaining": 54.615, "kwh_remaining": 22.392, "pct_used": 45.385}, "attack_mode": {"active": False, "activations_used": 2, "scenario": 3, "remaining_budget_s": 0.0}, "is_retired": False},
        {"car_number": 7, "driver_short_name": "GUE", "position": 14, "current_lap": 10, "speed_kmh": 0.0, "gps": {"lat": 52.48038, "lng": 13.39349, "heading": 52.1}, "accel_x": 0.0, "accel_y": 0.0, "brake_pct": 0.0, "steer": 0.0, "yaw_rate": 0.0, "energy": {"pct_remaining": 74.0, "kwh_remaining": 30.34, "pct_used": 26.0}, "attack_mode": {"active": False, "activations_used": 2, "scenario": 3, "remaining_budget_s": 0.0}, "is_retired": True},
        {"car_number": 8, "driver_short_name": "BAR", "position": 14, "current_lap": 21, "speed_kmh": 56.94, "gps": {"lat": 52.4811, "lng": 13.392122, "heading": 52.19}, "accel_x": -1.831, "accel_y": 0.922, "brake_pct": 100.0, "steer": 77.2, "yaw_rate": -0.855, "energy": {"pct_remaining": 54.134, "kwh_remaining": 22.195, "pct_used": 45.866}, "attack_mode": {"active": False, "activations_used": 2, "scenario": 1, "remaining_budget_s": 0.0}, "is_retired": False},
        {"car_number": 9, "driver_short_name": "EVA", "position": 4, "current_lap": 21, "speed_kmh": 89.65, "gps": {"lat": 52.481282, "lng": 13.391606, "heading": 247.57}, "accel_x": 0.746, "accel_y": 0.676, "brake_pct": 0.0, "steer": -352.8, "yaw_rate": 2.2, "energy": {"pct_remaining": 52.25, "kwh_remaining": 21.422, "pct_used": 47.75}, "attack_mode": {"active": False, "activations_used": 1, "scenario": 1, "remaining_budget_s": 180.0}, "is_retired": False},
        {"car_number": 11, "driver_short_name": "DIG", "position": 13, "current_lap": 21, "speed_kmh": 38.9, "gps": {"lat": 52.481147, "lng": 13.392157, "heading": 42.95}, "accel_x": -0.636, "accel_y": 0.867, "brake_pct": 67.0, "steer": 1565.3, "yaw_rate": 2.2, "energy": {"pct_remaining": 52.238, "kwh_remaining": 21.417, "pct_used": 47.762}, "attack_mode": {"active": False, "activations_used": 2, "scenario": 1, "remaining_budget_s": 0.0}, "is_retired": False},
        {"car_number": 13, "driver_short_name": "DAC", "position": 2, "current_lap": 21, "speed_kmh": 130.19, "gps": {"lat": 52.48109, "lng": 13.391041, "heading": 230.67}, "accel_x": 0.685, "accel_y": 0.724, "brake_pct": 0.0, "steer": 376.0, "yaw_rate": 0.916, "energy": {"pct_remaining": 51.73, "kwh_remaining": 21.209, "pct_used": 48.27}, "attack_mode": {"active": False, "activations_used": 2, "scenario": 1, "remaining_budget_s": 0.0}, "is_retired": False},
        {"car_number": 16, "driver_short_name": "ARO", "position": 18, "current_lap": 21, "speed_kmh": 136.53, "gps": {"lat": 52.480717, "lng": 13.391257, "heading": 51.89}, "accel_x": -0.507, "accel_y": -0.041, "brake_pct": 90.0, "steer": 1070.1, "yaw_rate": 3.971, "energy": {"pct_remaining": 53.243, "kwh_remaining": 21.83, "pct_used": 46.757}, "attack_mode": {"active": False, "activations_used": 2, "scenario": 1, "remaining_budget_s": 0.0}, "is_retired": False},
        {"car_number": 17, "driver_short_name": "NAT", "position": 7, "current_lap": 21, "speed_kmh": 61.32, "gps": {"lat": 52.481319, "lng": 13.391919, "heading": 266.1}, "accel_x": 1.025, "accel_y": 0.809, "brake_pct": 3.0, "steer": 1822.7, "yaw_rate": -0.794, "energy": {"pct_remaining": 54.819, "kwh_remaining": 22.476, "pct_used": 45.181}, "attack_mode": {"active": False, "activations_used": 2, "scenario": 2, "remaining_budget_s": 0.0}, "is_retired": False},
        {"car_number": 18, "driver_short_name": "DAR", "position": 11, "current_lap": 21, "speed_kmh": 39.57, "gps": {"lat": 52.481232, "lng": 13.392205, "heading": 347.69}, "accel_x": -0.288, "accel_y": 1.262, "brake_pct": 0.0, "steer": -70.8, "yaw_rate": 0.244, "energy": {"pct_remaining": 51.369, "kwh_remaining": 21.061, "pct_used": 48.631}, "attack_mode": {"active": False, "activations_used": 2, "scenario": 3, "remaining_budget_s": 0.0}, "is_retired": False},
        {"car_number": 21, "driver_short_name": "KIN", "position": 20, "current_lap": 21, "speed_kmh": 104.86, "gps": {"lat": 52.479794, "lng": 13.389959, "heading": 33.6}, "accel_x": 0.888, "accel_y": -0.194, "brake_pct": 0.0, "steer": 1077.0, "yaw_rate": -1.527, "energy": {"pct_remaining": 49.99, "kwh_remaining": 20.496, "pct_used": 50.01}, "attack_mode": {"active": False, "activations_used": 2, "scenario": 1, "remaining_budget_s": 0.0}, "is_retired": False},
        {"car_number": 22, "driver_short_name": "ROW", "position": 3, "current_lap": 21, "speed_kmh": 99.08, "gps": {"lat": 52.481249, "lng": 13.39147, "heading": 243.13}, "accel_x": 0.65, "accel_y": 0.966, "brake_pct": 1.0, "steer": -1790.4, "yaw_rate": -0.244, "energy": {"pct_remaining": 51.726, "kwh_remaining": 21.208, "pct_used": 48.274}, "attack_mode": {"active": False, "activations_used": 2, "scenario": 1, "remaining_budget_s": 0.0}, "is_retired": False},
        {"car_number": 23, "driver_short_name": "FEN", "position": 9, "current_lap": 21, "speed_kmh": 43.37, "gps": {"lat": 52.481297, "lng": 13.392103, "heading": 297.87}, "accel_x": 0.352, "accel_y": 0.964, "brake_pct": 2.0, "steer": 1222.1, "yaw_rate": 3.666, "energy": {"pct_remaining": 52.036, "kwh_remaining": 21.335, "pct_used": 47.964}, "attack_mode": {"active": False, "activations_used": 2, "scenario": 1, "remaining_budget_s": 0.0}, "is_retired": False},
        {"car_number": 25, "driver_short_name": "JEV", "position": 8, "current_lap": 21, "speed_kmh": 46.98, "gps": {"lat": 52.48132, "lng": 13.392044, "heading": 285.15}, "accel_x": 0.42, "accel_y": 1.132, "brake_pct": 0.0, "steer": 1220.1, "yaw_rate": 0.305, "energy": {"pct_remaining": 52.809, "kwh_remaining": 21.652, "pct_used": 47.191}, "attack_mode": {"active": False, "activations_used": 1, "scenario": 3, "remaining_budget_s": 60.0}, "is_retired": False},
        {"car_number": 33, "driver_short_name": "TIC", "position": 21, "current_lap": 21, "speed_kmh": 126.95, "gps": {"lat": 52.479842, "lng": 13.389896, "heading": 35.84}, "accel_x": 0.632, "accel_y": -0.51, "brake_pct": 0.0, "steer": 703.1, "yaw_rate": 0.183, "energy": {"pct_remaining": 50.055, "kwh_remaining": 20.523, "pct_used": 49.945}, "attack_mode": {"active": False, "activations_used": 1, "scenario": 1, "remaining_budget_s": 180.0}, "is_retired": False},
        {"car_number": 37, "driver_short_name": "CAS", "position": 1, "current_lap": 21, "speed_kmh": 111.05, "gps": {"lat": 52.481212, "lng": 13.391308, "heading": 237.39}, "accel_x": 0.819, "accel_y": 0.464, "brake_pct": 0.0, "steer": -343.3, "yaw_rate": -3.299, "energy": {"pct_remaining": 50.974, "kwh_remaining": 20.9, "pct_used": 49.026}, "attack_mode": {"active": False, "activations_used": 2, "scenario": 1, "remaining_budget_s": 0.0}, "is_retired": False},
        {"car_number": 48, "driver_short_name": "MOR", "position": 10, "current_lap": 21, "speed_kmh": 41.84, "gps": {"lat": 52.481286, "lng": 13.392182, "heading": 315.2}, "accel_x": 0.174, "accel_y": 1.022, "brake_pct": 3.0, "steer": 185.7, "yaw_rate": 0.489, "energy": {"pct_remaining": 51.26, "kwh_remaining": 21.017, "pct_used": 48.74}, "attack_mode": {"active": True, "activations_used": 0, "scenario": 3, "remaining_budget_s": 240.0}, "is_retired": False},
        {"car_number": 51, "driver_short_name": "VDL", "position": 17, "current_lap": 21, "speed_kmh": 125.69, "gps": {"lat": 52.480838, "lng": 13.391519, "heading": 54.31}, "accel_x": -0.769, "accel_y": -0.126, "brake_pct": 100.0, "steer": -3251.8, "yaw_rate": 2.2, "energy": {"pct_remaining": 52.792, "kwh_remaining": 21.645, "pct_used": 47.208}, "attack_mode": {"active": False, "activations_used": 2, "scenario": 1, "remaining_budget_s": 0.0}, "is_retired": False},
        {"car_number": 94, "driver_short_name": "WEH", "position": 6, "current_lap": 21, "speed_kmh": 71.22, "gps": {"lat": 52.481342, "lng": 13.391836, "heading": 259.63}, "accel_x": 1.985, "accel_y": 0.585, "brake_pct": 0.0, "steer": 1566.6, "yaw_rate": -0.122, "energy": {"pct_remaining": 50.747, "kwh_remaining": 20.806, "pct_used": 49.253}, "attack_mode": {"active": False, "activations_used": 2, "scenario": 1, "remaining_budget_s": 0.0}, "is_retired": False},
    ],
    # Synthetic events so we can test get_recent_events. In a real frame this
    # would only contain events occurring at race_time_s=1449. We add a few
    # recent ones to make queries meaningful.
    "events": [
        {"type": "race_control", "category": "safety_car", "text": "SAFETY CAR DEPLOYED", "attrs": {}},
        {"type": "attack_mode_activated", "car_number": 48, "duration_s": 240, "activation_num": 1},
        {"type": "lap_completed", "car_number": 37, "lap_number": 21, "lap_time_s": 66.5, "top_speed_kmh": 222.1},
        {"type": "lap_completed", "car_number": 13, "lap_number": 21, "lap_time_s": 66.8, "top_speed_kmh": 218.9},
    ],
}


def seed_via_firestore(project_id: str) -> None:
    """Write the sample frame directly to Firestore.

    Mirrors what State Writer would do, minus a few of the Pydantic validations.
    Used when State Writer isn't running yet.
    """
    print(f"Seeding Firestore in project {project_id}...")
    db = firestore.Client(project=project_id)
    race_id = SAMPLE_FRAME["race_id"]

    # Strip events into separate Event docs, leave the rest in RaceState
    state_doc = {k: v for k, v in SAMPLE_FRAME.items() if k != "events"}
    state_doc["ts_ns_wall"] = int(time.time() * 1e9)
    state_doc["updated_at_unix"] = int(time.time())

    db.collection("race_states").document(race_id).set(state_doc)
    print(f"  ✓ Wrote race_states/{race_id}")

    batch = db.batch()
    for raw in SAMPLE_FRAME["events"]:
        event = {
            "event_type": raw["type"],
            "ts_ns_wall": state_doc["ts_ns_wall"],
            "race_time_s": state_doc["race_time_s"],
            "race_id": race_id,
            "car_number": raw.get("car_number"),
            "data": {k: v for k, v in raw.items() if k not in ("type", "car_number")},
        }
        batch.set(db.collection("race_events").document(), event)
    batch.commit()
    print(f"  ✓ Wrote {len(SAMPLE_FRAME['events'])} events to race_events/")


def seed_via_writer(writer_url: str) -> None:
    """POST the sample frame to State Writer's /ingest endpoint."""
    url = writer_url.rstrip("/") + "/ingest"
    print(f"POSTing sample frame to {url}...")
    r = requests.post(url, json=SAMPLE_FRAME, timeout=30)
    r.raise_for_status()
    print(f"  ✓ {r.status_code} {r.json()}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--via-writer",
        help="State Writer base URL (e.g. http://localhost:8080). "
             "If omitted, writes directly to Firestore.",
    )
    args = parser.parse_args()

    if args.via_writer:
        seed_via_writer(args.via_writer)
    else:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get(
            "PROJECT_ID"
        )
        if not project_id:
            print("ERROR: PROJECT_ID env var required. Run: source activate.sh",
                  file=sys.stderr)
            sys.exit(1)
        seed_via_firestore(project_id)

    print("Done.")


if __name__ == "__main__":
    main()
