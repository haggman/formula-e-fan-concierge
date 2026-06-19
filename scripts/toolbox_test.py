"""Validate every Toolbox tool against a running Toolbox server.

Uses the official toolbox-core SDK rather than raw HTTP, which handles
version-specific protocol details (REST in v0.x, MCP in v1.x).

Run with the local server in another tab:
    cd toolbox && ./toolbox --tools-file tools.yaml --port 5000

Then:
    python scripts/toolbox_test.py

For the deployed instance, set TOOLBOX_URL:
    TOOLBOX_URL=https://fe-toolbox-xxx.run.app python scripts/toolbox_test.py
"""
import asyncio
import json
import os
import sys

from toolbox_core import ToolboxClient

TOOLBOX_URL = os.environ.get("TOOLBOX_URL", "http://127.0.0.1:5000").rstrip("/")

# Wall-clock-ns anchor past R10 chequered (green 1_715_519_045_726_000_000 + 2868s race ≈ ...521_913...; this is t≈+2954s)
POST_RACE = 1_715_522_000_000_000_000

# (tool_name, kwargs)
TESTS = [
    ("get_driver_info",
     {"car_number": 13}),

    ("get_lap_history",
     {"car_number": 13, "lap_start": 1, "lap_end": 10}),

    ("get_top_speed_history",
     {"car_number": 13, "lap_start": 1, "lap_end": 10}),

    ("get_energy_curve",
     {"car_number": 13, "through_lap": 10}),

    ("get_recent_race_control",
     {"through_time_ns": POST_RACE, "limit_n": 5}),

    ("get_am_activations",
     {"through_time_ns": POST_RACE}),

    ("get_am_armings",
     {"car_number": 13, "through_time_ns": POST_RACE}),

    ("get_overtakes_involving",
     {"car_number": 13, "through_time_ns": POST_RACE}),

    ("get_driver_career_stats",
     {"driver_code": "DAC"}),

    ("get_field_position_at_lap",
     {"lap_number": 5}),

    ("execute_sql_bq",
     {"sql": "SELECT COUNT(*) AS n FROM `fe_race10.event_stream`"}),
     
     ("get_lap_time_windows",
     {"car_number": 13}),

    ("bigquery_list_table_ids",
     {"dataset": "fe_race10"}),

    ("bigquery_get_table_info",
     {"dataset": "fe_race10", "table": "laps"}),
]


def normalize_result(result):
    """Result may come back as str, list, or dict depending on tool. Normalize."""
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return result
    return result


def render(result):
    """Print result in the same shape as the old REST-based test."""
    if isinstance(result, list):
        print(f"  ✓ {len(result)} row(s)")
        for row in result[:3]:
            print(f"    {row}")
        if len(result) > 3:
            print(f"    ... +{len(result) - 3} more")
    else:
        s = json.dumps(result, default=str, indent=2)
        if len(s) > 400:
            s = s[:400] + f"\n... ({len(s)} chars total)"
        print(f"  ✓ result: {s}")


async def main():
    print(f"Testing toolbox at: {TOOLBOX_URL}\n")
    fails = 0

    async with ToolboxClient(TOOLBOX_URL) as client:
        # Load the race-engineer toolset
        tools = await client.load_toolset("race-engineer")
        by_name = {t.__name__: t for t in tools}
        print(f"Loaded {len(tools)} tools from toolset 'race-engineer'")
        print(f"  names: {sorted(by_name.keys())}\n")

        for name, args in TESTS:
            print(f"── {name} ──")
            print(f"args: {args}")
            tool = by_name.get(name)
            if tool is None:
                print(f"  ✗ tool not found in toolset")
                fails += 1
                continue
            try:
                result = await tool(**args)
                result = normalize_result(result)
                render(result)
            except Exception as e:
                print(f"  ✗ {type(e).__name__}: {e}")
                fails += 1
            print()

    print("=" * 50)
    if fails:
        print(f"  ✗ {fails} tool(s) failed")
        sys.exit(1)
    else:
        print(f"  ✓ All {len(TESTS)} tools passed")


if __name__ == "__main__":
    asyncio.run(main())