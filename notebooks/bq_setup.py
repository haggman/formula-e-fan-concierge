"""
Formula E Race Engineer — BigQuery Setup
=========================================
Loads cleaned Berlin 2024 R10 Parquet files from gs://class-demo into BigQuery
dataset fe_race10 (us-central1, matching bucket region).

Run as:
    python notebooks/bq_setup.py

Or open in Cloud Shell Editor / Colab — cells separated by # %%.
Idempotent: re-running replaces existing tables and views.
"""

# %%
# Cell 1 — Imports and config
import os
import subprocess
from google.cloud import bigquery, storage

# Project: prefer GOOGLE_CLOUD_PROJECT (Cloud Run convention),
# fall back to DEVSHELL_PROJECT_ID (Cloud Shell), then gcloud config.
PROJECT_ID = (
    os.environ.get("GOOGLE_CLOUD_PROJECT")
    or os.environ.get("DEVSHELL_PROJECT_ID")
    or subprocess.check_output(
        ["gcloud", "config", "get-value", "project"], text=True
    ).strip()
)

REGION = os.environ.get("REGION")
if not REGION:
    raise RuntimeError(
        "REGION env var required. Run: source activate.sh"
    )
DATASET = "fe_race10"
BUCKET  = "class-demo"

print(f"Project:  {PROJECT_ID}")
print(f"Region:   {REGION}")
print(f"Dataset:  {DATASET}")
print(f"Bucket:   gs://{BUCKET}/formula-e/")

bq  = bigquery.Client(project=PROJECT_ID, location=REGION)
gcs = storage.Client(project=PROJECT_ID)

# %%
# Cell 2 — Verify bucket access
print("\nVerifying bucket access...")
bucket = gcs.bucket(BUCKET)
sample = next(bucket.list_blobs(prefix="formula-e/berlin_2024/r10/", max_results=1))
print(f"  ✓ Can read gs://{BUCKET}/  (sample: {sample.name})")

# %%
# Cell 3 — Create dataset
print(f"\nEnsuring dataset {PROJECT_ID}.{DATASET} exists in {REGION}...")
ds = bigquery.Dataset(f"{PROJECT_ID}.{DATASET}")
ds.location = REGION
ds.description = "Formula E Berlin 2024 R10 — race engineer agent reference data"
bq.create_dataset(ds, exists_ok=True)
print(f"  ✓ Dataset ready: {PROJECT_ID}.{DATASET}")

# %%
# Cell 4 — Table inventory
# bq_table_name -> (gcs_path, expected_min_rows, description)
TABLES = {
    "drivers": (
        "formula-e/berlin_2024/r10/timing/drivers.parquet",
        22,
        "Entry list: car, driver, team, manufacturer",
    ),
    "startgrid": (
        "formula-e/berlin_2024/r10/timing/startgrid.parquet",
        22,
        "Starting grid positions",
    ),
    "laps": (
        "formula-e/berlin_2024/r10/timing/laps.parquet",
        800,
        "Per-lap timing with sectors and loops",
    ),
    "attack": (
        "formula-e/berlin_2024/r10/timing/attack.parquet",
        80,
        "Attack Mode activations + scenario armings (R10)",
    ),
    "energy_per_lap": (
        "formula-e/berlin_2024/r10/energy/energy_per_lap.parquet",
        800,
        "Per-lap energy consumption (% of budget)",
    ),
    "racecontrol_classified": (
        "formula-e/berlin_2024/r10/derived/racecontrol_classified.parquet",
        40,
        "Race control messages with derived category",
    ),
    "event_stream": (
        "formula-e/berlin_2024/r10/derived/event_stream.parquet",
        1500,
        "Unified events (laps, AM, RC, overtakes)",
    ),
    # NOTE: telemetry is loaded separately below — Hive partitioning needs
    # special LoadJobConfig that doesn't fit the simple TABLES pattern.
    "career_driver": (
        "formula-e/cross_challenge/race_results/driver.parquet",
        80,
        "Career stats for all FE drivers",
    ),
    "career_race": (
        "formula-e/cross_challenge/race_results/race.parquet",
        2700,
        "10 seasons of FE race results",
    ),
}

print(f"\nWill load {len(TABLES)} tables:")
for name, (_, rows, desc) in TABLES.items():
    print(f"  {name:<25} ~{rows}+ rows  — {desc}")

# %%
# Cell 5 — Load function
def load_parquet(table_name: str, gcs_path: str) -> dict:
    table_id = f"{PROJECT_ID}.{DATASET}.{table_name}"
    uri = f"gs://{BUCKET}/{gcs_path}"
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        autodetect=True,
    )
    bq.load_table_from_uri(uri, table_id, job_config=job_config, location=REGION).result()
    t = bq.get_table(table_id)
    return {"table": table_name, "rows": t.num_rows, "size_mb": round(t.num_bytes / 1e6, 2)}

# %%
# Cell 6 — Run loads
print(f"\nLoading {len(TABLES)} tables...\n")
results = []
for name, (path, expected_min, _) in TABLES.items():
    print(f"  {name:<25} ", end="", flush=True)
    try:
        r = load_parquet(name, path)
        results.append({**r, "status": "ok"})
        flag = "✓" if r["rows"] >= expected_min else "⚠"
        print(f"{flag} {r['rows']:>6,} rows  ({r['size_mb']} MB)")
        if r["rows"] < expected_min:
            print(f"     WARN: expected ≥{expected_min}, got {r['rows']}")
    except Exception as e:
        results.append({"table": name, "status": "fail", "error": str(e)})
        print(f"✗ FAILED: {e}")

# %%
# Cell 6a — Telemetry load (Hive-partitioned, clustered on car_number)
#
# Layout: gs://class-demo/formula-e/berlin_2024/r10/telemetry/car_number=N/
# The car_number column is inferred from the directory name, not from the file.
# Clustering on car_number gives sub-second queries on per-car time ranges.

print("\nLoading telemetry (Hive-partitioned)...")
print("  ~1.28M rows across 22 cars — takes 30-60s")

TELEMETRY_TABLE = f"{PROJECT_ID}.{DATASET}.telemetry"
TELEMETRY_URI = f"gs://{BUCKET}/formula-e/berlin_2024/r10/telemetry/*"
TELEMETRY_SOURCE_PREFIX = f"gs://{BUCKET}/formula-e/berlin_2024/r10/telemetry/"

hive_opts = bigquery.HivePartitioningOptions()
hive_opts.mode = "AUTO"
hive_opts.source_uri_prefix = TELEMETRY_SOURCE_PREFIX

telemetry_job_config = bigquery.LoadJobConfig(
    source_format=bigquery.SourceFormat.PARQUET,
    write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    autodetect=True,
    hive_partitioning=hive_opts,
    clustering_fields=["car_number"],
)

try:
    load_job = bq.load_table_from_uri(
        TELEMETRY_URI,
        TELEMETRY_TABLE,
        job_config=telemetry_job_config,
        location=REGION,
    )
    load_job.result()
    t = bq.get_table(TELEMETRY_TABLE)
    print(f"  ✓ telemetry             {t.num_rows:>9,} rows  ({t.num_bytes / 1e6:.2f} MB)")
    print(f"     clustered on: {list(t.clustering_fields) if t.clustering_fields else 'none'}")
    # Track in results for the summary at the end
    results.append({
        "table": "telemetry",
        "rows": t.num_rows,
        "size_mb": round(t.num_bytes / 1e6, 2),
        "status": "ok",
    })
except Exception as e:
    print(f"  ✗ telemetry FAILED: {e}")
    results.append({"table": "telemetry", "status": "fail", "error": str(e)})

# %%
# Cell 6b  — Materialize top_speed_per_lap as a real table
#
# The correlated subquery (find lap for each 20Hz sample) is too expensive
# to run repeatedly via a view. Race data is frozen — materialize it once,
# cluster on car_number, fast queries forever.

print("\nMaterializing top_speed_per_lap (one-shot derived table)...")

TOP_SPEED_TABLE = f"{PROJECT_ID}.{DATASET}.top_speed_per_lap"

# Use a window-style join: anti-correlated subquery is fine for one-shot CTAS.
top_speed_sql = f"""
CREATE OR REPLACE TABLE `{TOP_SPEED_TABLE}`
CLUSTER BY car_number AS
WITH telem_with_lap AS (
    SELECT
        t.car_number,
        t.tv_speed,
        (
            SELECT MAX(l.lap_num)
            FROM `{PROJECT_ID}.{DATASET}.laps` l
            WHERE l.car_number = t.car_number
              AND l.start_time <= t.time
        ) AS lap_num
    FROM `{PROJECT_ID}.{DATASET}.telemetry` t
)
SELECT
    car_number,
    lap_num,
    ROUND(MAX(tv_speed), 1) AS top_speed_kmh,
    COUNT(*) AS telemetry_samples
FROM telem_with_lap
WHERE lap_num IS NOT NULL
GROUP BY car_number, lap_num
"""

try:
    bq.query(top_speed_sql, location=REGION).result()
    t = bq.get_table(TOP_SPEED_TABLE)
    print(f"  ✓ top_speed_per_lap     {t.num_rows:>9,} rows  ({t.num_bytes / 1e6:.2f} MB)")
    print(f"     clustered on: {list(t.clustering_fields) if t.clustering_fields else 'none'}")
except Exception as e:
    print(f"  ✗ top_speed_per_lap FAILED: {e}")

# %%
# Cell 7 — Convenience views
print("\nCreating convenience views...")
VIEWS = {
    "v_laps_with_driver": """
        SELECT l.car_number, d.driver_first_name, d.driver_last_name,
               d.driver_short_name, d.team, d.manufacturer,
               l.lap_num, l.time AS lap_time_ms,
               l.position, l.is_valid
        FROM `{p}.{d}.laps` l
        LEFT JOIN `{p}.{d}.drivers` d USING (car_number)
    """,
    "v_am_with_driver": """
        SELECT a.car_number, d.driver_short_name, d.team,
               a.eth_arrival_time AS event_time, a.active, a.scenario
        FROM `{p}.{d}.attack` a
        LEFT JOIN `{p}.{d}.drivers` d USING (car_number)
    """,
    "v_overtakes": """
        -- NOTE: in event_stream overtake rows, car_number is the subject's
        -- GRID POSITION, while attrs_json.other_car is a real car number.
        -- (Verified by position-adjacency scoring, 2026-06-04.) This view
        -- resolves both to real cars and regenerates human_summary; the
        -- source summary strings embed the grid IDs and must not be used.
        SELECT
            e.t AS event_time,
            g.car_number,
            d.driver_short_name,
            d.team,
            CAST(JSON_VALUE(e.attrs_json, '$.other_car') AS INT64) AS other_car_number,
            od.driver_short_name AS other_driver_short_name,
            CAST(JSON_VALUE(e.attrs_json, '$.position_change') AS INT64) AS position_change,
            CAST(JSON_VALUE(e.attrs_json, '$.at_loop') AS INT64) AS at_loop,
            CONCAT(
                d.driver_short_name, ' (#', CAST(g.car_number AS STRING), ') ',
                IF(CAST(JSON_VALUE(e.attrs_json, '$.position_change') AS INT64) < 0,
                   'passed', 'lost place to'),
                ' ', od.driver_short_name, ' (#',
                JSON_VALUE(e.attrs_json, '$.other_car'), ')'
            ) AS human_summary
        FROM `{p}.{d}.event_stream` e
        JOIN `{p}.{d}.startgrid` g ON g.position = e.car_number
        LEFT JOIN `{p}.{d}.drivers` d ON d.car_number = g.car_number
        LEFT JOIN `{p}.{d}.drivers` od
            ON od.car_number = CAST(JSON_VALUE(e.attrs_json, '$.other_car') AS INT64)
        WHERE e.source = 'overtake'
          AND CAST(JSON_VALUE(e.attrs_json, '$.position_change') AS INT64) != 0
          AND JSON_VALUE(e.attrs_json, '$.other_car') IS NOT NULL
    """,
}
for view_name, sql_t in VIEWS.items():
    sql = sql_t.format(p=PROJECT_ID, d=DATASET)
    try:
        bq.query(
            f"CREATE OR REPLACE VIEW `{PROJECT_ID}.{DATASET}.{view_name}` AS\n{sql}",
            location=REGION,
        ).result()
        print(f"  ✓ {view_name}")
    except Exception as e:
        print(f"  ✗ {view_name}: {e}")

# %%
# Cell 8 — Sanity samples
print("\nSanity checks:\n")
SAMPLES = [
    ("drivers",
     "SELECT car_number, driver_short_name, team, manufacturer "
     "FROM `{p}.{d}.drivers` ORDER BY car_number LIMIT 3"),
    ("attack (DAC car 13)",
     "SELECT car_number, active, scenario, eth_arrival_time "
     "FROM `{p}.{d}.attack` WHERE car_number = 13 ORDER BY eth_arrival_time LIMIT 5"),
    ("racecontrol_classified",
     "SELECT category, message_text FROM `{p}.{d}.racecontrol_classified` "
     "ORDER BY time LIMIT 3"),
    ("event_stream (first events)",
     "SELECT t, source, event_type, car_number, human_summary "
     "FROM `{p}.{d}.event_stream` ORDER BY t LIMIT 5"),
    ("v_overtakes",
     "SELECT event_time, driver_short_name, human_summary "
     "FROM `{p}.{d}.v_overtakes` LIMIT 3"),
    ("career_driver (DAC + CAS + EVA)",
     "SELECT shortcode, drivername, wins, podiums, points "
     "FROM `{p}.{d}.career_driver` "
     "WHERE shortcode IN ('DAC','CAS','EVA') ORDER BY shortcode"),
     ("telemetry (DAC car 13, first 3 samples)",
     "SELECT car_number, time, tv_speed, tv_brake "
     "FROM `{p}.{d}.telemetry` WHERE car_number = 13 "
     "ORDER BY time LIMIT 3"),
    ("top_speed_per_lap (DAC laps 1-5)",
     "SELECT lap_num, top_speed_kmh, telemetry_samples "
     "FROM `{p}.{d}.top_speed_per_lap` "
     "WHERE car_number = 13 AND lap_num BETWEEN 1 AND 5 "
     "ORDER BY lap_num"),
]
for label, sql_t in SAMPLES:
    print(f"  -- {label}")
    sql = sql_t.format(p=PROJECT_ID, d=DATASET)
    try:
        for row in bq.query(sql, location=REGION).result():
            print(f"     {dict(row.items())}")
    except Exception as e:
        print(f"     ERROR: {e}")
    print()

# %%
# Cell 9 — Summary
ok_count = sum(1 for r in results if r.get("status") == "ok")
fail_count = sum(1 for r in results if r.get("status") == "fail")
total_rows = sum(r.get("rows", 0) for r in results)
total_mb = sum(r.get("size_mb", 0) for r in results)

print("=" * 60)
print(f"  Setup complete: {PROJECT_ID}.{DATASET} ({REGION})")
print("=" * 60)
print(f"  Tables: {ok_count} loaded, {fail_count} failed")
print(f"  Total rows: {total_rows:,}")
print(f"  Total size: {total_mb:.2f} MB")
print()
print("  Next: chunk 3 — MCP Toolbox setup")
print("=" * 60)