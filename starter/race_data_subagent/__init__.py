"""Student race-data subagent package. Build root_agent + now_tools + prompts.

Relative import on purpose (it must load as a top-level `race_data_subagent`
agent folder under an ADK agents_dir in the container — see app.py). Guarded so
the package imports cleanly before you've wired the agent / set TOOLBOX_URL, and
so the DETERMINISTIC first-light container (which sets TOOLBOX_URL but never uses
the LLM agent) doesn't pull in agent.py -> ToolboxToolset.
"""
import importlib.util
import os

if (
    os.environ.get("DETERMINISTIC", "1") != "1"
    and importlib.util.find_spec("google.adk") is not None
    and os.environ.get("TOOLBOX_URL")
):
    from . import agent  # noqa: F401 — exposes root_agent for ADK discovery (LLM mode)
