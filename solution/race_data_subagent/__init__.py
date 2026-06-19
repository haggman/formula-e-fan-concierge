"""Exposes root_agent for `adk web` discovery — best-effort guard.

Import agent.py only when google-adk and TOOLBOX_URL are present (agent.py needs
both), mirroring the Ch2 guard so other containers can import the package safely.
"""
import importlib.util
import os

if importlib.util.find_spec("google.adk") is not None and os.environ.get("TOOLBOX_URL"):
    from solution.race_data_subagent import agent  # noqa: F401 — exposes root_agent
