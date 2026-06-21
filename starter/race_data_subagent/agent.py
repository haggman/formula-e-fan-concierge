"""Race-data subagent (ADK) — STARTER.

Build `root_agent`: the now_tools (Firestore "now") + the Ch2 BigQuery Toolbox
(ToolboxToolset), with the time-honest prompt. The agent owns both worlds and is
served to CX by app.py (given) as POST /ask_race_data.

USE RELATIVE IMPORTS inside this package (from .prompts import ...,
from .tools.now_tools import ...) so it loads as a top-level `race_data_subagent`
agent folder in the container. `shared.*` stays absolute.

Sketch (fill in — see solution/race_data_subagent/agent.py):

    import os
    from google.adk.agents import Agent
    from google.adk.tools.toolbox_toolset import ToolboxToolset
    from .prompts import ROOT_AGENT_DESCRIPTION, ROOT_AGENT_INSTRUCTION
    from .tools.now_tools import get_field_now, get_car_now, get_recent_events

    TOOLBOX_URL = os.environ["TOOLBOX_URL"]            # deployed fe-toolbox
    toolbox_tools = ToolboxToolset(server_url=TOOLBOX_URL.rstrip("/"),
                                   toolset_name="race-engineer")  # the 14 Ch2 tools

    root_agent = Agent(
        name="race_data_subagent",
        model=os.environ.get("FE_MODEL", "gemini-3.5-flash"),
        description=ROOT_AGENT_DESCRIPTION,
        instruction=ROOT_AGENT_INSTRUCTION,
        tools=[get_field_now, get_car_now, get_recent_events, toolbox_tools],
    )
"""
# TODO(student): build root_agent (see the sketch above and the solution).
