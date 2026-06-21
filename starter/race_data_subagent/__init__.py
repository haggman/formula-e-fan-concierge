"""Student race-data subagent package. Build root_agent + now_tools + prompts.

Relative import on purpose (it must load as a top-level `race_data_subagent`
agent folder under an ADK agents_dir in the container — see app.py). Guarded so
the package imports cleanly before you've wired the agent / set TOOLBOX_URL.
"""
import importlib.util
import os

if importlib.util.find_spec("google.adk") is not None and os.environ.get("TOOLBOX_URL"):
    from . import agent  # noqa: F401 — exposes root_agent for ADK discovery
