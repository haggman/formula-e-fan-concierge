"""Exposes root_agent for ADK discovery (get_fast_api_app / adk web) — guarded.

Import agent.py only when google-adk and TOOLBOX_URL are present (agent.py needs
both), so other containers / the DETERMINISTIC first-light path can import this
package without Vertex creds or a deployed Toolbox.

Relative import on purpose: this package is loaded both as
`solution.race_data_subagent` (in the repo) and as a top-level
`race_data_subagent` agent folder under an ADK agents_dir (in the container).
"""
import importlib.util
import os

if importlib.util.find_spec("google.adk") is not None and os.environ.get("TOOLBOX_URL"):
    from . import agent  # noqa: F401 — exposes root_agent for ADK discovery
