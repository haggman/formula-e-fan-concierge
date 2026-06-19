"""The starter/solution agent-package seam (packaging P1.2; moved here in P1.4).

AGENT_PACKAGE selects WHICH agent package the rest of the system loads:

    solution.race_engineer   the complete reference (the answer key)
    starter.race_engineer    the student build

Both packages mirror the same file layout (agent, prompts, config, snapshot,
tools.state_client, tools.frame_tools), so every consumer resolves modules
through agent_module() below and works unchanged whichever package is active.

WHY THIS LIVES IN shared/: every consumer needs it — the frontend (engineer
loop, state poller, agent client) AND the dev scripts (agent_chat,
test_frame_tools, local_test). shared/ is an installed package; frontend/ is
not. Putting the resolver here means `python scripts/agent_chat.py` resolves
the exact same package the frontend does, with no sys.path games.

The code default is solution.race_engineer so the deployed engine-mode
container (which never sources activate.sh) gets the reference. activate.sh
exports the per-session choice — starter.race_engineer by default for local
work; instructors override with AGENT_PACKAGE=solution.race_engineer.
"""
from __future__ import annotations

import importlib
import os

AGENT_PACKAGE = os.environ.get("AGENT_PACKAGE", "solution.race_engineer").strip()


def agent_module(sub: str = ""):
    """Import a module from the ACTIVE agent package.

    agent_module("config")             -> e.g. starter.race_engineer.config
    agent_module("tools.state_client") -> e.g. starter.race_engineer.tools.state_client
    agent_module("agent")              -> the module exposing root_agent

    Raises ImportError naming the resolved module on a typo'd or missing
    package — fail loudly, don't fall back.
    """
    name = AGENT_PACKAGE + (f".{sub}" if sub else "")
    try:
        return importlib.import_module(name)
    except ImportError as e:
        raise ImportError(
            f"AGENT_PACKAGE={AGENT_PACKAGE!r}: could not import {name!r}. "
            "Valid values are 'solution.race_engineer' (the reference) or "
            "'starter.race_engineer' (the student build). Did you run "
            "'pip install -e .' after changing packages?"
        ) from e
