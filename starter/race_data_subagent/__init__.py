"""Student race-data subagent package. Build root_agent + the MCP wrapper."""
import importlib.util, os
if importlib.util.find_spec("google.adk") is not None and os.environ.get("TOOLBOX_URL"):
    from starter.race_data_subagent import agent  # noqa: F401
