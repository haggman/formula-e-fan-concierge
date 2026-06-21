"""Exposes root_agent for ADK discovery (get_fast_api_app / adk web) — guarded.

Import agent.py only in LLM mode (DETERMINISTIC != "1") and only when google-adk
and TOOLBOX_URL are present (agent.py constructs a ToolboxToolset at import). The
DETERMINISTIC guard matters: the deploy script sets TOOLBOX_URL even for the
first-light deterministic deploy, so without it, merely importing now_tools
(which runs this __init__) would pull in agent.py -> ToolboxToolset and crash the
deterministic container. Deterministic mode never needs the agent.

Relative import on purpose: this package is loaded both as
`solution.race_data_subagent` (in the repo) and as a top-level
`race_data_subagent` agent folder under an ADK agents_dir (in the container).
"""
import importlib.util
import os

if (
    os.environ.get("DETERMINISTIC", "1") != "1"
    and importlib.util.find_spec("google.adk") is not None
    and os.environ.get("TOOLBOX_URL")
):
    from . import agent  # noqa: F401 — exposes root_agent for ADK discovery (LLM mode)
