"""Subagent prompts — STARTER. Author the time-honesty doctrine + tool-choice rules.

Write two strings the agent uses:
  ROOT_AGENT_DESCRIPTION — one sentence: what this agent answers, time-honest.
  ROOT_AGENT_INSTRUCTION — the system prompt. It must cover:
    1. The two worlds: "now" tools (get_field_now/get_car_now/get_recent_events)
       vs the BigQuery Toolbox tools ("then"/career).
    2. TIME-HONESTY: read a "now" tool FIRST, read its race_wall_time_ns, pass it
       as `through_time_ns` to EVERY BigQuery tool, and NEVER reveal anything
       after the current moment (refuse "who wins?"-style questions warmly).
    3. Career/historical data from prior seasons is fair game (it predates now).
    4. Style: lead with the answer, 1-3 sentences, driver short names + car numbers.

Reference: solution/race_data_subagent/prompts.py.
"""

ROOT_AGENT_DESCRIPTION = ""  # TODO(student)
ROOT_AGENT_INSTRUCTION = ""  # TODO(student)
