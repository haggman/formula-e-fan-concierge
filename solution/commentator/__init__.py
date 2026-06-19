"""Exposes root_agent for `adk web` discovery — best-effort guard.

Import agent.py only when google-adk is present, so the frontend container
(which ships this package for prompts/config/frame_tools but without ADK) can
import the package without crashing. Mirrors the Ch2 guard.
"""
import importlib.util

if importlib.util.find_spec("google.adk") is not None:
    from solution.commentator import agent  # noqa: F401 — exposes root_agent
