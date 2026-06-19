"""Student commentator package. Build root_agent in agent.py (Tiers A–D)."""
import importlib.util
if importlib.util.find_spec("google.adk") is not None:
    from starter.commentator import agent  # noqa: F401
